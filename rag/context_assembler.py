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
    guidelines: list[RetrievedDoc] | None = None,
    mode: AssistMode = AssistMode.HOMEWORK_ASSIST,
    query_week: int = 1,
    syllabus_matrix: str | None = None,
    style_guide: str | None = None,
) -> str:
    """
    Formats retrieved documents into the [Vector_Database_Results] block.

    Mirrors the structure produced by get_automated_context() in generate_dataset.py:
    - Syllabus chunk first (if present)
    - Then relevant pedagogical/supplementary/strict_rules chunks
    - Guidelines last (separate collection, week-agnostic reference)
    - Each chunk tagged with its category
    """
    chunks: list[str] = []

    # Syllabus — directly from Postgres matrix string now
    if syllabus_matrix:
        import json
        try:
            matrix = json.loads(syllabus_matrix)
            week_key = str(query_week)
            if week_key in matrix:
                week_data = matrix[week_key]
                allowed = week_data.get("allowed", "")
                forbidden = week_data.get("forbidden", "")
                chunks.append(f"[Retrieved_Syllabus_Chunk]\nWeek {query_week} Allowed topics: {allowed}\nWeek {query_week} Forbidden topics: {forbidden}")
            else:
                chunks.append(f"[Retrieved_Syllabus_Chunk]\nNo specific topics defined for week {query_week}.")
        except Exception as e:
            # Fallback if invalid JSON
            chunks.append(f"[Retrieved_Syllabus_Chunk]\n{syllabus_matrix}")
    elif syllabus:
        chunks.append(f"[Retrieved_Syllabus_Chunk]\n{syllabus.content}")

    # Style Guide
    if style_guide:
        chunks.append(f"[Style_Rules]\n{style_guide}")

    # Strict rules — prefixed for the TA to recognize as mandatory
    for doc in rules:
        chunks.append(f"[Strict_Rules]\nWeek: {doc.week}\nContent: {doc.content}")

    # Pedagogical context
    for doc in pedagogical:
        chunks.append(f"[Pedagogical_Context]\nWeek: {doc.week}\nContent: {doc.content}")

    # Supplementary
    for doc in supplementary:
        chunks.append(f"[Supplementary]\nWeek: {doc.week}\nContent: {doc.content}")

    # C++ Core Guidelines — separate collection, no week tag
    if guidelines:
        for doc in guidelines:
            chunks.append(f"[CppCoreGuidelines]\nContent: {doc.content}")

    # If no RAG docs retrieved at all (syllabus-only or empty), avoid empty block
    if not chunks:
        return ""

    return "\n\n".join(chunks)


def build_retrieval_result(
    syllabus: RetrievedDoc | None,
    rules: list[RetrievedDoc],
    pedagogical: list[RetrievedDoc],
    supplementary: list[RetrievedDoc],
    guidelines: list[RetrievedDoc] | None = None,
    mode: AssistMode = AssistMode.HOMEWORK_ASSIST,
    query_week: int = 1,
    syllabus_matrix: str | None = None,
    style_guide: str | None = None,
) -> RetrievalResult:
    """Build the complete RetrievalResult including formatted context."""
    return RetrievalResult(
        syllabus=syllabus,
        strict_rules=rules,
        pedagogical=pedagogical,
        supplementary=supplementary,
        guidelines=guidelines or [],
        formatted_context=assemble_context(
            syllabus=syllabus,
            rules=rules,
            pedagogical=pedagogical,
            supplementary=supplementary,
            guidelines=guidelines,
            mode=mode,
            query_week=query_week,
            syllabus_matrix=syllabus_matrix,
            style_guide=style_guide,
        ),
    )
