"""
Query builder: fuses student natural language, AST features, and terminal output
into a dense embedding query string for vector similarity search.
(Filters are handled in retrievers.py.)
"""
from __future__ import annotations

from rag.schemas import QueryInput


def build_query(input: QueryInput) -> str:
    """
    Returns a dense query string combining:
    - Student's natural language question
    - Terminal output (error messages carry strong signal)
    - AST-derived keyword hints for query expansion
    """
    parts = [input.student_message]

    if input.terminal_output:
        parts.append(input.terminal_output)

    ast = input.ast_features
    ast_hints = []

    if ast.has_pointer:
        ast_hints.append("pointer dereference address memory nullptr")
    if ast.has_reference:
        ast_hints.append("reference alias lvalue")
    if ast.has_new or ast.has_delete:
        ast_hints.append("new delete allocation heap memory leak")
    if ast.has_malloc or ast.has_free:
        ast_hints.append("malloc free heap C style allocation")
    if ast.has_loop:
        ast_hints.append("loop iteration bounds off-by-one for while")
    if ast.has_recursion:
        ast_hints.append("recursion base case stack overflow")
    if ast.target_variables:
        ast_hints.append(" ".join(ast.target_variables))

    if ast_hints:
        parts.append(" ".join(ast_hints))

    return "\n".join(parts)
