"""
Retrievers: three parallel retrieval strategies.
1. SyllabusRetriever — exact lookup by week (payload filter, no vector search needed)
2. SemanticRetriever — vector similarity with week filter, excludes syllabus
3. RulesRetriever — vector similarity with week + Strict_Rules category filter + threshold cutoff
"""
from __future__ import annotations

import os

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue, Range
from sentence_transformers import SentenceTransformer

from rag.schemas import DocCategory, RetrievedDoc, SourceDomain

# ---------------------------------------------------------------------------
# Shared state (initialized once, reused across calls)
# ---------------------------------------------------------------------------
QDRANT_PATH = os.path.join(os.path.dirname(__file__), "..", "qdrant_local_data")
COLLECTION_NAME = "course_knowledge"

_client: QdrantClient | None = None
_model: SentenceTransformer | None = None


def _get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(path=QDRANT_PATH)
    return _client


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer("sentence-transformers/multi-qa-mpnet-base-dot-v1")
    return _model


def close_client() -> None:
    """Close the shared Qdrant client explicitly to avoid shutdown warnings."""
    global _client
    if _client is not None:
        try:
            _client.close()
        finally:
            _client = None


def _hit_to_doc(hit) -> RetrievedDoc:
    """Convert a Qdrant search hit to a RetrievedDoc."""
    p = hit.payload or {}
    return RetrievedDoc(
        chunk_id=p.get("chunk_id", ""),
        content=p.get("content", ""),
        category=DocCategory(p.get("category", "Supplementary")),
        week=p.get("week", 0),
        priority=p.get("priority", 3),
        score=hit.score,
        source_domain=SourceDomain(p.get("source_domain", "mit_ocw_lecture")),
        source_type=p.get("source_type", ""),
    )


# ---------------------------------------------------------------------------
# Filter helpers (qdrant_client.models.Filter, not raw dicts)
# ---------------------------------------------------------------------------

def _week_filter(week: int, *, cumulative: bool = False) -> Filter:
    """Include course material + external references (week 0)."""
    course_condition = (
        FieldCondition(key="week", range=Range(gte=1, lte=week))
        if cumulative
        else FieldCondition(key="week", match=MatchValue(value=week))
    )
    return Filter(should=[
        course_condition,
        FieldCondition(key="week", match=MatchValue(value=0)),
    ])


def _syllabus_filter(week: int) -> Filter:
    return Filter(must=[
        FieldCondition(key="week", match=MatchValue(value=week)),
        FieldCondition(key="category", match=MatchValue(value="Syllabus")),
    ])


def _semantic_filter(week: int, *, cumulative: bool = False) -> Filter:
    """Course material + external refs (week 0), excluding syllabus."""
    course_condition = (
        FieldCondition(key="week", range=Range(gte=1, lte=week))
        if cumulative
        else FieldCondition(key="week", match=MatchValue(value=week))
    )
    return Filter(
        must=[
            Filter(should=[
                course_condition,
                FieldCondition(key="week", match=MatchValue(value=0)),
            ]),
        ],
        must_not=[FieldCondition(key="category", match=MatchValue(value="Syllabus"))],
    )


def _rules_filter(week: int, *, cumulative: bool = False) -> Filter:
    """Course Strict_Rules only (no external refs in Strict_Rules)."""
    course_condition = (
        FieldCondition(key="week", range=Range(gte=1, lte=week))
        if cumulative
        else FieldCondition(key="week", match=MatchValue(value=week))
    )
    return Filter(must=[
        course_condition,
        FieldCondition(key="category", match=MatchValue(value="Strict_Rules")),
    ])


# ---------------------------------------------------------------------------
# Retriever A: Syllabus (exact lookup, no vector search)
# ---------------------------------------------------------------------------

def retrieve_syllabus(week: int) -> RetrievedDoc | None:
    """Exact lookup of the syllabus document for a given week."""
    client = _get_client()
    records, _ = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=_syllabus_filter(week),
        limit=1,
    )

    if not records:
        return None

    r = records[0]
    p = r.payload or {}
    return RetrievedDoc(
        chunk_id=p.get("chunk_id", ""),
        content=p.get("content", ""),
        category=DocCategory.SYLLABUS,
        week=week,
        priority=1,
        score=1.0,
        source_domain=SourceDomain(p.get("source_domain", "mit_ocw_syllabus")),
        source_type=p.get("source_type", ""),
    )


# ---------------------------------------------------------------------------
# Retriever B: Semantic (vector search, current week, exclude syllabus)
# ---------------------------------------------------------------------------

def retrieve_semantic(
    dense_query: str, week: int, top_k: int = 5, *, cumulative: bool = False,
) -> list[RetrievedDoc]:
    """Vector similarity search. cumulative=True → weeks 1..X; False → exact week."""
    model = _get_model()
    client = _get_client()

    query_vector = model.encode(dense_query).tolist()

    hits = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        query_filter=_semantic_filter(week, cumulative=cumulative),
        limit=top_k,
    ).points

    return [_hit_to_doc(h) for h in hits]


# ---------------------------------------------------------------------------
# Retriever C: Rules (vector search, cumulative weeks 1..X + Strict_Rules only, threshold)
# ---------------------------------------------------------------------------

def retrieve_strict_rules(
    dense_query: str, week: int, top_k: int = 3, threshold: float = 0.55,
    *, cumulative: bool = False,
) -> list[RetrievedDoc]:
    """Vector search for Strict_Rules. cumulative=True → weeks 1..X; False → exact week."""
    model = _get_model()
    client = _get_client()

    query_vector = model.encode(dense_query).tolist()

    hits = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        query_filter=_rules_filter(week, cumulative=cumulative),
        limit=top_k,
        score_threshold=threshold,
    ).points

    return [_hit_to_doc(h) for h in hits]
