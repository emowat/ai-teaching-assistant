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

    Uses AST-derived keyword hints only, not the student's question.
    The student's question (e.g. 'why did my program crash?') carries
    no meaningful signal for a CPP reference lookup.
    """
    ast = input.ast_features
    return _ast_hints(ast)


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

    # Near-cursor STL variables are the strongest signal for reference lookup
    if ast.near_cursor_stl:
        hints.append(" ".join(ast.near_cursor_stl))
    elif ast.target_variables:
        stl_vars = [v for v in ast.target_variables
                    if v.startswith("std::") and v not in ("std::cout", "std::cin")]
        if stl_vars:
            hints.append(" ".join(stl_vars))

    return " ".join(hints)


# ---------------------------------------------------------------------------
# Legacy shim: kept so any existing callers don't break immediately.
# Prefer build_course_query() / build_cpp_query() for new code.
# ---------------------------------------------------------------------------

def build_query(input: QueryInput) -> str:
    """Deprecated: use build_course_query() and build_cpp_query() instead."""
    return build_course_query(input)
