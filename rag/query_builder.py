"""
Query builder: produces separate dense query strings for the two distinct
retrieval concerns in the RAG pipeline.

  build_course_query()  — driven by the student's NL question only.
                          Used to search course material (lectures, syllabus,
                          strict rules). AST hints are excluded because they
                          would pull unrelated technical chunks into a
                          conceptual/debugging question.

  build_cpp_query()     — driven by AST features only.
                          Used to search the week-agnostic CPP reference
                          collection. The student's question is excluded
                          because it carries no signal for reference lookup.

(Filters are handled in retrievers.py.)
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

from rag.schemas import ASTFeatures, QueryInput

logger = logging.getLogger(__name__)


def build_course_query(input: QueryInput) -> str:
    """Return the dense query for course content retrieval.

    Prefers a backend-provided standalone query (retrieval_query) when present
    — this carries resolved context for follow-up turns that the current
    student_message alone lacks. Falls back to the student's message otherwise.

    Terminal output and AST hints are intentionally excluded:
    - Terminal output is already in the LLM context window.
    - AST hints belong to the separate CPP reference query.
    """
    return input.retrieval_query or input.student_message or ""


def build_cpp_query(input: QueryInput) -> str:
    """Return the dense query for CPP reference retrieval.

    Uses AST-derived keyword hints as the primary signal. Also scans the
    student's message for any explicitly mentioned std:: identifiers (e.g.
    "I think I use std::unique_lock<mutex> right?") since these are strong
    retrieval signals that may not yet appear in the AST.
    """
    ast = input.ast_features
    ast_hints = _ast_hints(ast)
    # Scan the same effective query text that should_search_cpp() keys off of —
    # the contextualized retrieval_query when present, else the raw message — so
    # a std:: mentioned only in a follow-up's pulled-in code is picked up here too.
    message_hints = _message_std_hints(input.retrieval_query or input.student_message or "")
    combined = ast_hints
    if message_hints:
        # Avoid duplicating terms already in the AST hints
        for term in message_hints:
            if term not in ast_hints:
                combined = f"{combined} {term}".strip()
    return combined


def _ast_hints(ast: ASTFeatures) -> str:
    """Build a keyword string from AST features for CPP reference lookup."""
    hints: list[str] = []

    if ast.has_stl_algorithm:
        hints.append("std::find std::sort std::count algorithm iterator range")
    if ast.has_smart_pointer:
        hints.append("std::unique_ptr std::shared_ptr smart pointer ownership")
    if ast.has_iterator:
        hints.append("iterator begin end range-based for std::iterator")
    if ast.has_pointer:
        hints.append("pointer dereference address memory nullptr")
    if ast.has_reference:
        hints.append("reference alias lvalue")
    if ast.has_new or ast.has_delete:
        hints.append("new delete allocation heap memory leak")
    if ast.has_malloc or ast.has_free:
        hints.append("malloc free heap C style allocation")
    if ast.has_loop:
        hints.append("loop iteration bounds off-by-one for while")
    if ast.has_recursion:
        hints.append("recursion base case stack overflow")

    # Near-cursor STL function/type calls are the strongest signal.
    # The extension strips "std::" when building near_cursor_stl (it captures
    # only the part after std::), so we re-add it here for clarity.
    seen: set[str] = set()
    if ast.near_cursor_stl:
        for name in ast.near_cursor_stl:
            term = f"std::{name}"
            if term not in seen:
                seen.add(term)
                hints.append(term)

    # target_variables covers the full function scope — always include STL
    # types from it, not just as a fallback when near_cursor_stl is empty.
    # e.g. "std::vector<Item>" → "std::vector", "std::thread" → "std::thread"
    if ast.target_variables:
        for v in ast.target_variables:
            base = v.split("<")[0].strip()
            if base.startswith("std::") and base not in ("std::cout", "std::cin") and base not in seen:
                seen.add(base)
                hints.append(base)

    return " ".join(hints)


def _message_std_hints(message: str) -> list[str]:
    """Extract std:: identifiers explicitly mentioned in the student's message.

    Matches patterns like std::unique_lock, std::unique_lock<mutex>,
    std::vector<int>, etc. and returns the base type (stripping template args)
    so it matches CPP reference index entries.
    """
    matches = re.findall(r"std::[a-zA-Z_][a-zA-Z0-9_]*(?:<[^>]*>)?", message)
    seen: set[str] = set()
    result: list[str] = []
    for m in matches:
        base = m.split("<")[0].strip()
        if base not in ("std::cout", "std::cin", "std::endl") and base not in seen:
            seen.add(base)
            result.append(base)
    return result


# ---------------------------------------------------------------------------
# Follow-up contextualization (shared by the backend and the retrieval eval)
#
# Retrieval is single-turn, but follow-ups like "How about now" carry no
# standalone signal. Generation resolves them by consuming the full message
# history natively; retrieval cannot. Centralizing the condense logic here keeps
# rag_eng (production) and the retrieval eval embedding the identical string.
# ---------------------------------------------------------------------------

# Exact block tags emitted by the VS Code extension — used as delimiters.
# The explicit allowlist avoids false matches on C++ identifiers like
# [MAX_SIZE_BUFFER], lambda captures [&]/[=]/[], or any other [] in student text.
_KNOWN_TAGS = (
    "Code_Context|Terminal_Context|Student_Question"
    "|State_Tracking|/State_Tracking"
)
_TAG_BOUNDARY = rf"(?=\[(?:{_KNOWN_TAGS})\]|$)"


def extract_block(content: str, tag: str) -> str:
    """Return the text of a single [tag] block from one message's content."""
    m = re.search(rf"\[{tag}\](.*?){_TAG_BOUNDARY}", content, re.DOTALL)
    return m.group(1).strip() if m else ""


def extract_student_question(content: str) -> str:
    """Return the student's natural-language question from one message.

    Prefers the explicit [Student_Question] block; falls back to the raw message
    with known context blocks stripped. Plain messages with no blocks (as in the
    eval golden set) are returned unchanged.
    """
    question = extract_block(content, "Student_Question")
    if not question:
        question = re.sub(
            rf"\[(?:{_KNOWN_TAGS})\][\s\S]*?{_TAG_BOUNDARY}", "", content
        ).strip()
    return question


# A turn "names the problem" when it mentions a week/problem/assignment number —
# the strongest anchor for what the whole conversation is about.
_ANCHOR_RE = re.compile(r"\b(?:week|problem|assignment|part|lecture)\s*#?\s*\d", re.I)

_RECENT_PRIOR = 3        # student turns of recent history kept before the current one
_CTX_CHAR_CAP = 400      # cap on current code/terminal added to a low-signal query

# Low-signal (general) follow-up detection.
#
# A follow-up is "general" (needs conversation context) when it contains no
# TOPICAL word. A word is topical iff it is specialized in general English (low
# wordfreq zipf) and/or salient in the course corpus (appears in >= min_df
# chunks — see experiments/build_corpus_terms.py). This separates conversational
# turns ("how about now", "I am lost", "yay it works") from questions that carry
# their own retrieval signal ("what is mantissa", "use-after-free crash") without
# any hand-maintained vocabulary. zipf runs ~8 ("the") down to ~0 (never seen).
_TOKEN = re.compile(r"[a-z][a-z0-9_]+")
_ZIPF_STRONG = 3.5   # specialized in general English on its own (mantissa, segfault)
_ZIPF_WEAK = 4.6     # moderately uncommon; topical only if also a course term
_CORPUS_TERMS_PATH = Path(__file__).resolve().parent / "corpus_terms.json"

try:
    from wordfreq import zipf_frequency as _zipf_frequency
except Exception:  # pragma: no cover - wordfreq is a declared dependency
    _zipf_frequency = None
    logger.warning(
        "wordfreq unavailable — follow-up contextualization is disabled; "
        "build_retrieval_query() will return None for every turn."
    )


@lru_cache(maxsize=1)
def _corpus_terms() -> frozenset[str]:
    """Tokens appearing in >= min_df course chunks (from corpus_terms.json)."""
    try:
        data = json.loads(_CORPUS_TERMS_PATH.read_text(encoding="utf-8"))
        return frozenset(data.get("terms", []))
    except (OSError, ValueError):
        return frozenset()


def _is_topical(token: str) -> bool:
    """A word carries standalone retrieval signal."""
    zipf = _zipf_frequency(token, "en")
    if zipf <= 0:                    # out-of-vocabulary: topical only if a course term
        return token in _corpus_terms()
    if zipf < _ZIPF_STRONG:          # specialized in general English
        return True
    return zipf < _ZIPF_WEAK and token in _corpus_terms()


def is_low_signal(question: str) -> bool:
    """True when a question has no topical word (contentless follow-up).

    Used both to decide whether to contextualize a follow-up and to decide
    whether a query string is worth caching (low-signal strings are not).
    """
    if _zipf_frequency is None:      # detector unavailable → treat as specific
        return False
    return not any(_is_topical(t) for t in _TOKEN.findall(question.lower()))


def _find_anchor(prior_questions: list[str]) -> str | None:
    """The turn that established the problem: the most recent one naming a
    week/problem, else the first turn (turn 1)."""
    for q in reversed(prior_questions):
        if _ANCHOR_RE.search(q):
            return q
    return prior_questions[0] if prior_questions else None


def build_retrieval_query(messages: list[dict]) -> str | None:
    """Condense conversation history into a standalone retrieval query.

    `messages` is the ordered conversation (roles user/assistant), including the
    current user turn. Behaviour is adaptive:

    - First turn (one student question): return None — embed the message as-is.
    - Current turn is specific (has non-filler tokens): return None — it already
      retrieves well on its own, so don't look back and dilute it.
    - Current turn is low-signal ("how about now", "check now"): expand it with
      the problem anchor (turn naming the week/problem, else turn 1), the recent
      student turns, and the current turn's code + terminal context.

    Returns None whenever the current message should be embedded unchanged.
    """
    user_msgs = [m for m in messages if m.get("role") == "user"]
    if not user_msgs:
        return None

    # Low-signal detection must run on the *current* turn specifically, not the
    # last non-empty question — the latest turn may be a code-only paste whose
    # question text is empty while earlier turns still carry questions.
    current_content = str(user_msgs[-1].get("content", ""))
    current_question = extract_student_question(current_content)

    questions = [
        q
        for m in user_msgs
        for q in (extract_student_question(str(m.get("content", ""))),)
        if q
    ]
    if len(questions) < 2:
        return None
    if not current_question or not is_low_signal(current_question):
        return None

    # Low-signal follow-up: anchor + recent window + current code & terminal.
    # current_question is non-empty here, so it is questions[-1].
    window = questions[-(_RECENT_PRIOR + 1):]                 # recent turns + current
    anchor = _find_anchor(questions[: -(_RECENT_PRIOR + 1)])  # problem-naming turn / turn 1

    parts: list[str] = []
    if anchor and anchor not in window:
        parts.append(anchor)
    parts.extend(window)

    for tag in ("Code_Context", "Terminal_Context"):
        block = extract_block(current_content, tag)
        if block:
            parts.append(block[:_CTX_CHAR_CAP])

    return " ".join(p for p in parts if p).strip() or None
