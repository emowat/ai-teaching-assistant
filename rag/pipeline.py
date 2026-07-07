"""
Main RAG pipeline: orchestrates query building → retrieval → reranking → context assembly.
This is the single entry point that the FastAPI layer (and eval) will call.

Two entry points:
  - run_retrieval(query)  → RetrievalResult (Layer 1+2: context only)
  - generate_response(query, llm) → str (Layer 1+2+3: full TA answer)

Mode flows directly from QueryInput (user-selected, not auto-classified):
  - Homework Assist → exact week match, rules-heavy, tight top_k
  - Study Assist     → cumulative weeks 1..X, pedagogy-heavy, wide top_k

The new helper functions below split prompt construction from model invocation.
That separation keeps the service layer from re-running retrieval when it only
needs to format a prompt, and it makes the FastAPI/Gradio wrappers easier to
test because they can reuse the retrieval result directly.

Course routing now resolves an explicit `course_id` first, then falls back to
the legacy `course_source` compatibility path for older callers through the
course registry layer.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from rag.course_registry import resolve_course_route
from rag.schemas import AssistMode, CourseSource, QueryInput, RetrievalResult
from rag.query_builder import build_course_query, build_cpp_query
from rag.retrievers import (
    retrieve_semantic, retrieve_strict_rules, retrieve_guidelines,
    retrieve_harvard, retrieve_harvard_rules,
)
from rag.reranker import merge_and_rerank, CATEGORY_WEIGHTS, CATEGORY_WEIGHTS_CPP, should_search_cpp
from rag.context_assembler import build_retrieval_result


# ---------------------------------------------------------------------------
# Mode-aware retrieval parameters
# ---------------------------------------------------------------------------

MODE_PARAMS: dict[AssistMode, dict] = {
    AssistMode.HOMEWORK_ASSIST: {
        "cumulative": False,  # current week only — stay focused
        "semantic_top_k": 5,
        "rules_top_k": 3,
        "rules_threshold": 0.55,
        "guidelines_top_k": 5,
        "guidelines_threshold": 0.6,   # high threshold — minimal distraction
        "final_k": 5,
    },
    AssistMode.STUDY_ASSIST: {
        "cumulative": True,  # weeks 1..X — allow review of past concepts
        "semantic_top_k": 5,
        "rules_top_k": 3,
        "rules_threshold": 0.45,  # relaxed — more conceptual material
        "guidelines_top_k": 5,
        "guidelines_threshold": 0.45,  # lower threshold — deeper study
        "final_k": 5,
    },
}

RERANK_STRATEGY_LAMBDAS: dict[str, float] = {
    "similarity": 1.0,
    "mmr_0.5": 0.5,
    "mmr_0.7": 0.7,
    "mmr_0.9": 0.9,
}

RERANK_STRATEGY_MULTIPLIERS: dict[str, int] = {
    "similarity": 1,
    "mmr_0.5": 4,
    "mmr_0.7": 4,
    "mmr_0.9": 4,
}


def _normalize_rerank_strategy(value: object | None) -> str:
    """Coerce rerank strategies into a stable string key."""
    if value is None:
        return "similarity"
    raw = getattr(value, "value", value)
    normalized = str(raw).strip().casefold()
    if normalized not in RERANK_STRATEGY_LAMBDAS:
        raise ValueError(f"Unsupported rerank strategy: {value}")
    return normalized


def _resolve_retrieval_controls(
    query: QueryInput,
    params: dict[str, object],
) -> tuple[int, int, float, str]:
    """Return the effective final_k, candidate fetch k, lambda, and strategy."""
    requested_final_k = getattr(query, "result_count", None)
    final_k = int(params["final_k"])
    if isinstance(requested_final_k, int) and requested_final_k > 0:
        final_k = requested_final_k

    rerank_strategy = _normalize_rerank_strategy(getattr(query, "rerank_strategy", None))
    lambda_param = RERANK_STRATEGY_LAMBDAS[rerank_strategy]
    fetch_multiplier = RERANK_STRATEGY_MULTIPLIERS[rerank_strategy]
    candidate_fetch_k = final_k * fetch_multiplier
    return final_k, candidate_fetch_k, lambda_param, rerank_strategy


def run_retrieval(query: QueryInput) -> RetrievalResult:
    """
    Full RAG pipeline: given a student query, return structured + formatted context.

    1. Build dense query from student NL, AST, terminal
    2. Mode-aware parameter selection
    3. Parallel retrieval: syllabus (exact), semantic (vector), rules (vector+filter),
       guidelines (vector, separate collection). Routes to the resolved course
       collection based on explicit course_id first, then legacy course_source.
    4. Merge, category-weight, MMR diversify
    5. Format into [Vector_Database_Results] block
    """
    params = MODE_PARAMS[query.mode]
    route = resolve_course_route(query)
    # Keep the mode defaults intact unless the caller explicitly requests a
    # different final K; MMR widens the candidate fetch behind the scenes.
    final_k, candidate_fetch_k, lambda_param, rerank_strategy = (
        _resolve_retrieval_controls(query, params)
    )
    retrieval_top_k = candidate_fetch_k if rerank_strategy != "similarity" else final_k
    guidelines_top_k = params["guidelines_top_k"]

    # Build two separate query strings for the two retrieval concerns:
    # - course_query: student's NL question only → course content collections
    # - cpp_query:    AST keyword hints only     → CPP reference collection
    course_query = build_course_query(query)
    cpp_query = build_cpp_query(query)

    # Determine course-content retrieval callables
    if query.course_source == CourseSource.MIT_14:
        def _fetch_semantic():
            return retrieve_semantic(
                course_query, query.week,
                top_k=params["semantic_top_k"],
                cumulative=params["cumulative"],
                collection_name=route.collection_name,
            )
        def _fetch_rules():
            return retrieve_strict_rules(
                course_query, query.week,
                top_k=params["rules_top_k"],
                threshold=params["rules_threshold"],
                cumulative=params["cumulative"],
                collection_name=route.collection_name,
            )
    elif query.course_source == CourseSource.CS50:
        def _fetch_semantic():
            return retrieve_harvard(
                course_query, query.week,
                top_k=params["semantic_top_k"],
                cumulative=params["cumulative"],
            )
        def _fetch_rules():
            return retrieve_harvard_rules(
                course_query, query.week,
                top_k=params["rules_top_k"],
                threshold=params["rules_threshold"],
                cumulative=params["cumulative"],
            )
    else:
        def _fetch_semantic():
            return retrieve_semantic(
                course_query, query.week,
                top_k=retrieval_top_k,
                cumulative=params["cumulative"],
                collection_name=route.collection_name,
            )
        def _fetch_rules():
            return retrieve_strict_rules(
                course_query, query.week,
                top_k=retrieval_top_k,
                threshold=params["rules_threshold"],
                cumulative=params["cumulative"],
                collection_name=route.collection_name,
            )

    syllabus = None

    # Fire course content and (optionally) CPP reference in parallel.
    # Guidelines are skipped entirely when there are no AST hints to query with.
    if cpp_query:
        def _fetch_guidelines():
            return retrieve_guidelines(
                cpp_query,
                top_k=guidelines_top_k,
                threshold=params["guidelines_threshold"],
            )
        with ThreadPoolExecutor(max_workers=3) as pool:
            f_sem = pool.submit(_fetch_semantic)
            f_rules = pool.submit(_fetch_rules)
            f_guidelines = pool.submit(_fetch_guidelines)
        semantic = f_sem.result()
        rules = f_rules.result()
        guidelines = f_guidelines.result()
    else:
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_sem = pool.submit(_fetch_semantic)
            f_rules = pool.submit(_fetch_rules)
        semantic = f_sem.result()
        rules = f_rules.result()
        guidelines = []

    # Merge + rerank (now returns 5-tuple with guidelines)
    search_cpp = should_search_cpp(course_query, query.ast_features)
    weights = CATEGORY_WEIGHTS_CPP if search_cpp else CATEGORY_WEIGHTS
    syllabus, rules_out, pedagogical_out, supplementary_out, guidelines_out = merge_and_rerank(
        syllabus=syllabus,
        semantic=semantic,
        rules=rules,
        guidelines=guidelines,
        mode=query.mode,
        weights=weights,
        final_k=final_k,
        lambda_param=lambda_param,
    )

    return build_retrieval_result(
        syllabus=syllabus,
        rules=rules_out,
        pedagogical=pedagogical_out,
        supplementary=supplementary_out,
        guidelines=guidelines_out,
        mode=query.mode,
        query_week=query.week,
        syllabus_matrix=query.syllabus_matrix,
        style_guide=query.style_guide,
        query_string=course_query,
        cpp_query_string=cpp_query,
    )


# ---------------------------------------------------------------------------
# Full RAG: retrieval + LLM generation (Layer 1+2+3)
# ---------------------------------------------------------------------------

BASE_TA_SYSTEM_PROMPT = """You are an expert, patient Socratic C++ Teaching Assistant helping a student debug.

RULES:
1. SOCRATIC BREVITY: Be extremely concise (1-2 sentences). Use a "Short Observation + Question".
2. DO NOT EXPLAIN THE BUG: Lead the student to discover the error themselves.
3. ABSOLUTELY NO CODE: Never write code solutions or C++ code blocks.
4. SYLLABUS ALIGNMENT: Obey the [Retrieved_Syllabus_Chunk] Forbidden concepts strictly.
5. Use information from other retrieved documents if helpful, ignore if irrelevant.
6. FORBIDDEN WORDS: Never mention "syllabus", "context", "metadata", "week", "allowed", "forbidden".
"""


def build_prompt(
    query: QueryInput,
    result: RetrievalResult,
    system_prompt: str | None = None,
) -> str:
    """Build the final prompt from a query and already-fetched retrieval result.

    This is intentionally separate from `generate_response` so external callers
    can inspect or reuse the final prompt without forcing a second retrieval.
    """
    return (
        f"{system_prompt or BASE_TA_SYSTEM_PROMPT}\n\n"
        f"{result.formatted_context}\n\n"
        f"Student: {query.student_message}"
    )


def generate_response_from_result(
    query: QueryInput,
    result: RetrievalResult,
    llm,
    system_prompt: str | None = None,
) -> str:
    """Generate an answer from an existing retrieval result.

    The caller is responsible for retrieval; this function only performs prompt
    assembly and LLM invocation.
    """
    prompt = build_prompt(query=query, result=result, system_prompt=system_prompt)
    response = llm.invoke(prompt)

    if hasattr(response, "content"):
        return response.content
    return str(response)


def generate_response(
    query: QueryInput,
    llm,  # ChatCohere or any LangChain-compatible chat model
    system_prompt: str | None = None,
) -> str:
    """
    Full RAG pipeline: retrieve context → prompt LLM → return TA response.

    Returns the Socratic TA's response string.
    """
    # Step 1: Retrieval (Layer 1+2). This keeps the public API intact for
    # existing callers while allowing the service layer to reuse the lower-level
    # prompt helper when it already has a retrieval result in hand.
    result = run_retrieval(query)
    return generate_response_from_result(
        query=query,
        result=result,
        llm=llm,
        system_prompt=system_prompt,
    )
