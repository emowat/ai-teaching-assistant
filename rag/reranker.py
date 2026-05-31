"""
Reranker: mode-aware category-priority weighting + MMR diversification.
"""
from __future__ import annotations

import math

from rag.schemas import AssistMode, DocCategory, RetrievedDoc


# ---------------------------------------------------------------------------
# Mode-aware category weights
# ---------------------------------------------------------------------------

# Fallback (used when no mode specified)
BASE_WEIGHTS: dict[DocCategory, float] = {
    DocCategory.SYLLABUS: 1.5,
    DocCategory.STRICT_RULES: 1.5,
    DocCategory.PEDAGOGICAL_CONTEXT: 1.0,
    DocCategory.SUPPLEMENTARY: 0.5,
}

MODE_WEIGHTS: dict[AssistMode, dict[DocCategory, float]] = {
    AssistMode.HOMEWORK_ASSIST: {
        DocCategory.SYLLABUS: 1.5,
        DocCategory.STRICT_RULES: 1.8,          # rules are critical during debugging
        DocCategory.PEDAGOGICAL_CONTEXT: 0.9,
        DocCategory.SUPPLEMENTARY: 0.3,          # dampen distractions
    },
    AssistMode.STUDY_ASSIST: {
        DocCategory.SYLLABUS: 1.5,
        DocCategory.STRICT_RULES: 1.0,
        DocCategory.PEDAGOGICAL_CONTEXT: 1.5,    # concepts are the focus
        DocCategory.SUPPLEMENTARY: 0.8,           # extra material is valuable
    },
}


# ---------------------------------------------------------------------------
# Weighting
# ---------------------------------------------------------------------------

def apply_category_weights(
    docs: list[RetrievedDoc],
    weights: dict[DocCategory, float] | None = None,
) -> list[RetrievedDoc]:
    """
    Multiply each document's score by its category weight.
    Returns the same list with scores adjusted in place, re-sorted descending.
    """
    w = weights or BASE_WEIGHTS
    for doc in docs:
        doc.score = doc.score * w.get(doc.category, 1.0)
    docs.sort(key=lambda d: d.score, reverse=True)
    return docs


# ---------------------------------------------------------------------------
# MMR diversification
# ---------------------------------------------------------------------------

def mmr_diversify(
    docs: list[RetrievedDoc],
    lambda_param: float = 0.7,
    final_k: int = 5,
) -> list[RetrievedDoc]:
    """
    Maximal Marginal Relevance: pick documents that are both relevant (high score)
    and diverse (low Jaccard similarity to already-selected docs).

    lambda_param: 1.0 = pure relevance, 0.0 = pure diversity.
    """
    if len(docs) <= final_k:
        return docs

    selected: list[RetrievedDoc] = []
    remaining = list(docs)

    def _token_set(doc: RetrievedDoc) -> set[str]:
        return set(doc.content.lower().split())

    remaining_sets = [_token_set(d) for d in remaining]

    while len(selected) < final_k and remaining:
        if not selected:
            best_idx = 0
        else:
            best_score = -math.inf
            best_idx = 0
            for i, doc in enumerate(remaining):
                relevance = doc.score
                max_sim = max(
                    _jaccard_sim(remaining_sets[i], _token_set(s))
                    for s in selected
                )
                mmr = lambda_param * relevance - (1 - lambda_param) * max_sim
                if mmr > best_score:
                    best_score = mmr
                    best_idx = i

        selected.append(remaining.pop(best_idx))
        remaining_sets.pop(best_idx)

    return selected


def _jaccard_sim(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two token sets."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ---------------------------------------------------------------------------
# Merge + rerank (public entry point)
# ---------------------------------------------------------------------------

def merge_and_rerank(
    syllabus: RetrievedDoc | None,
    semantic: list[RetrievedDoc],
    rules: list[RetrievedDoc],
    mode: AssistMode = AssistMode.HOMEWORK_ASSIST,
    lambda_param: float = 0.7,
    final_k: int | None = None,
) -> tuple[RetrievedDoc | None, list[RetrievedDoc], list[RetrievedDoc], list[RetrievedDoc]]:
    """
    Merge results from three retrievers, apply mode-aware category weights, MMR diversify.

    Returns (syllabus, strict_rules, pedagogical, supplementary).
    """
    weights = MODE_WEIGHTS.get(mode, BASE_WEIGHTS)
    if final_k is None:
        final_k = 5 if mode == AssistMode.HOMEWORK_ASSIST else 8

    # Merge all non-syllabus docs
    all_docs: list[RetrievedDoc] = list(semantic) + list(rules)

    # Deduplicate by chunk_id
    seen: set[str] = set()
    unique: list[RetrievedDoc] = []
    for d in all_docs:
        if d.chunk_id not in seen:
            seen.add(d.chunk_id)
            unique.append(d)

    # Apply mode-aware category weights
    unique = apply_category_weights(unique, weights=weights)

    # MMR diversify
    diverse = mmr_diversify(unique, lambda_param=lambda_param, final_k=final_k)

    # Group for structured output
    rules_out = [d for d in diverse if d.category == DocCategory.STRICT_RULES]
    pedagogical_out = [d for d in diverse if d.category == DocCategory.PEDAGOGICAL_CONTEXT]
    supplementary_out = [d for d in diverse if d.category == DocCategory.SUPPLEMENTARY]

    return syllabus, rules_out, pedagogical_out, supplementary_out
