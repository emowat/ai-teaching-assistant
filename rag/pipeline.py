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
"""
from __future__ import annotations

from rag.schemas import AssistMode, QueryInput, RetrievalResult
from rag.query_builder import build_query
from rag.retrievers import retrieve_syllabus, retrieve_semantic, retrieve_strict_rules
from rag.reranker import merge_and_rerank
from rag.context_assembler import build_retrieval_result


# ---------------------------------------------------------------------------
# Mode-aware retrieval parameters
# ---------------------------------------------------------------------------

MODE_PARAMS: dict[AssistMode, dict] = {
    AssistMode.HOMEWORK_ASSIST: {
        "cumulative": False,      # current week only — stay focused
        "semantic_top_k": 5,
        "rules_top_k": 3,
        "rules_threshold": 0.55,
        "final_k": 5,
    },
    AssistMode.STUDY_ASSIST: {
        "cumulative": True,       # weeks 1..X — allow review of past concepts
        "semantic_top_k": 8,
        "rules_top_k": 3,
        "rules_threshold": 0.45,  # relaxed — more conceptual material
        "final_k": 8,
    },
}


def run_retrieval(query: QueryInput) -> RetrievalResult:
    """
    Full RAG pipeline: given a student query, return structured + formatted context.

    1. Build dense query from student NL, AST, terminal
    2. Mode-aware parameter selection
    3. Parallel retrieval: syllabus (exact), semantic (vector), rules (vector+filter)
    4. Merge, category-weight, MMR diversify
    5. Format into [Vector_Database_Results] block
    """
    params = MODE_PARAMS[query.mode]

    dense_query = build_query(query)

    # Three parallel retrievers
    syllabus = retrieve_syllabus(query.week)
    semantic = retrieve_semantic(
        dense_query, query.week,
        top_k=params["semantic_top_k"],
        cumulative=params["cumulative"],
    )
    rules = retrieve_strict_rules(
        dense_query, query.week,
        top_k=params["rules_top_k"],
        threshold=params["rules_threshold"],
        cumulative=params["cumulative"],
    )

    # Merge + rerank
    syllabus, rules_out, pedagogical_out, supplementary_out = merge_and_rerank(
        syllabus=syllabus,
        semantic=semantic,
        rules=rules,
        mode=query.mode,
    )

    return build_retrieval_result(
        syllabus=syllabus,
        rules=rules_out,
        pedagogical=pedagogical_out,
        supplementary=supplementary_out,
        mode=query.mode,
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
