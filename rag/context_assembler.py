"""
Context assembler: formats the retrieval results into the [Vector_Database_Results]
block that gets injected into the TA system prompt, matching the format expected
by generate_dataset.py's get_automated_context().
"""
from __future__ import annotations

import random

from rag.schemas import AssistMode, RetrievedDoc, RetrievalResult


def assemble_context(
    syllabus: RetrievedDoc | None,
    rules: list[RetrievedDoc],
    pedagogical: list[RetrievedDoc],
    supplementary: list[RetrievedDoc],
    mode: AssistMode = AssistMode.HOMEWORK_ASSIST,
) -> str:
    """
    Formats retrieved documents into the [Vector_Database_Results] block.

    Mirrors the structure produced by get_automated_context() in generate_dataset.py:
    - Syllabus chunk first (if present)
    - Then relevant pedagogical/supplementary/strict_rules chunks
    - Each chunk tagged with its category
    """
    chunks: list[str] = []

    # Syllabus — always first if available
    if syllabus:
        chunks.append(f"[Retrieved_Syllabus_Chunk]\n{syllabus.content}")

    # Strict rules — prefixed for the TA to recognize as mandatory
    for doc in rules:
        chunks.append(f"[Strict_Rules]\nWeek: {doc.week}\nContent: {doc.content}")

    # Pedagogical context
    for doc in pedagogical:
        chunks.append(f"[Pedagogical_Context]\nWeek: {doc.week}\nContent: {doc.content}")

    # Supplementary
    for doc in supplementary:
        chunks.append(f"[Supplementary]\nWeek: {doc.week}\nContent: {doc.content}")

    # If no RAG docs retrieved at all (syllabus-only or empty), avoid empty block
    if not chunks:
        return ""

    return "\n\n".join(chunks)


def build_retrieval_result(
    syllabus: RetrievedDoc | None,
    rules: list[RetrievedDoc],
    pedagogical: list[RetrievedDoc],
    supplementary: list[RetrievedDoc],
    mode: AssistMode = AssistMode.HOMEWORK_ASSIST,
) -> RetrievalResult:
    """Build the complete RetrievalResult including formatted context."""
    return RetrievalResult(
        syllabus=syllabus,
        strict_rules=rules,
        pedagogical=pedagogical,
        supplementary=supplementary,
        formatted_context=assemble_context(syllabus, rules, pedagogical, supplementary, mode),
    )
