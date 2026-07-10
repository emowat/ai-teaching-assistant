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

import re

from rag.schemas import ASTFeatures, QueryInput


def build_course_query(input: QueryInput) -> str:
    """Return the dense query for course content retrieval.

    Uses the student's natural language question only.
    Terminal output and AST hints are intentionally excluded:
    - Terminal output is already in the LLM context window.
    - AST hints belong to the separate CPP reference query.
    """
    return input.student_message or ""


def build_cpp_query(input: QueryInput) -> str:
    """Return the dense query for CPP reference retrieval.

    Uses AST-derived keyword hints as the primary signal. Also scans the
    student's message for any explicitly mentioned std:: identifiers (e.g.
    "I think I use std::unique_lock<mutex> right?") since these are strong
    retrieval signals that may not yet appear in the AST.
    """
    ast = input.ast_features
    ast_hints = _ast_hints(ast)
    message_hints = _message_std_hints(input.student_message or "")
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
# Legacy shim: kept so any existing callers don't break immediately.
# Prefer build_course_query() / build_cpp_query() for new code.
# ---------------------------------------------------------------------------

def build_query(input: QueryInput) -> str:
    """Deprecated: use build_course_query() and build_cpp_query() instead."""
    return build_course_query(input)
