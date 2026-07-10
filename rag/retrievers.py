"""
Retrievers: three parallel retrieval strategies.
1. SyllabusRetriever — exact lookup by week (payload filter, no vector search needed)
2. SemanticRetriever — vector similarity with week filter, excludes syllabus
3. RulesRetriever — vector similarity with week + Strict_Rules category filter + threshold cutoff

The main change here is that the retrievers no longer hard-code a local
filesystem Qdrant instance or a fixed collection/model name. Those values now
come from `rag.runtime`, which lets the same retrieval code work in local mode
and in the new cloud-backed `rag_eng` service without changing call sites.
"""
from __future__ import annotations

from collections import OrderedDict
from threading import Lock

from qdrant_client.models import Filter

from rag.schemas import DocCategory, RetrievedDoc, SourceDomain
from rag.runtime import create_qdrant_client, get_runtime_config

# ---------------------------------------------------------------------------
# Shared state (initialized once, reused across calls)
# ---------------------------------------------------------------------------
_client = None
_model = None
_model_lock = Lock()
_LEGACY_SOURCE_DOMAIN_ALIASES: dict[str, SourceDomain] = {
    "cpp_reference": SourceDomain.CPP_CORE_GUIDELINES,
}


def _get_client():
    global _client
    if _client is None:
        # Client construction is centralized so the rest of the retrievers do
        # not need to know whether Qdrant is local-on-disk or remote/cloud.
        _client = create_qdrant_client()
    return _client


def _get_model():
    global _model
    if _model is None:
        # The first load is protected by a lock because the pipeline can warm
        # up retrieval in parallel with multiple worker threads.
        with _model_lock:
            if _model is None:
                # The model name is configurable so the service layer can
                # override the embedding backend without rewriting retrieval
                # code.
                from sentence_transformers import SentenceTransformer

                _model = SentenceTransformer(get_runtime_config().embedding_model)
    return _model


# ---------------------------------------------------------------------------
# Query embedding (shared, cached, batched)
# ---------------------------------------------------------------------------
# Embedding is the dominant CPU cost of retrieval. The pipeline now computes
# vectors once before dispatching the parallel Qdrant lanes. This helper keeps
# repeated queries cheap and batches cache misses into a single model forward
# pass so the worker threads stay focused on I/O.
_EMBED_CACHE_MAX = 512
_embed_cache: "OrderedDict[str, list[float]]" = OrderedDict()
_embed_cache_lock = Lock()


def embed_queries(texts: list[str]) -> list[list[float]]:
    """Encode query strings into Qdrant-ready vectors, cached and batched."""
    results: list[list[float] | None] = [None] * len(texts)
    miss_positions: OrderedDict[str, list[int]] = OrderedDict()

    with _embed_cache_lock:
        for index, text in enumerate(texts):
            cached = _embed_cache.get(text)
            if cached is not None:
                _embed_cache.move_to_end(text)
                results[index] = cached
            else:
                miss_positions.setdefault(text, []).append(index)

    if miss_positions:
        unique_misses = list(miss_positions.keys())
        vectors = _get_model().encode(unique_misses)

        with _embed_cache_lock:
            for text, vector in zip(unique_misses, vectors):
                vector_list = vector.tolist()
                for position in miss_positions[text]:
                    results[position] = vector_list
                _embed_cache[text] = vector_list
                _embed_cache.move_to_end(text)
            while len(_embed_cache) > _EMBED_CACHE_MAX:
                _embed_cache.popitem(last=False)

    return [vector for vector in results if vector is not None]


def embed_query(text: str) -> list[float]:
    """Encode a single query string into a Qdrant-ready vector (cached)."""
    return embed_queries([text])[0]


def close_client() -> None:
    """Close the shared Qdrant client explicitly to avoid shutdown warnings."""
    global _client
    if _client is not None:
        try:
            _client.close()
        finally:
            _client = None


def _coerce_source_domain(
    raw_value: object | None,
    *,
    default: SourceDomain,
) -> SourceDomain:
    """Map stored payload values to the canonical SourceDomain enum.

    Older Qdrant points may still use legacy labels such as ``cpp_reference``.
    We normalize those values here so retrieval can continue to read old points
    while new indexing continues to write the canonical enum value.
    """
    if raw_value is None:
        return default

    normalized = str(raw_value).strip()
    if not normalized:
        return default

    legacy = _LEGACY_SOURCE_DOMAIN_ALIASES.get(normalized.casefold())
    if legacy is not None:
        return legacy

    try:
        return SourceDomain(normalized)
    except ValueError as exc:
        allowed = ", ".join(domain.value for domain in SourceDomain)
        raise ValueError(
            f"{normalized!r} is not a valid SourceDomain; allowed values: {allowed}"
        ) from exc


def _hit_to_doc(
    hit,
    *,
    default_source_domain: SourceDomain = SourceDomain.MIT_OCW_LECTURE,
) -> RetrievedDoc:
    """Convert a Qdrant search hit to a RetrievedDoc."""
    p = hit.payload or {}
    return RetrievedDoc(
        chunk_id=p.get("chunk_id", ""),
        content=p.get("content", ""),
        category=DocCategory(p.get("category", "Supplementary")),
        week=p.get("week", 0),
        priority=p.get("priority", 3),
        score=hit.score,
        source_domain=_coerce_source_domain(
            p.get("source_domain"),
            default=default_source_domain,
        ),
        source_type=p.get("source_type", ""),
    )


# ---------------------------------------------------------------------------
# Filter helpers (qdrant_client.models.Filter, not raw dicts)
# ---------------------------------------------------------------------------

def _week_filter(week: int, *, cumulative: bool = False) -> Filter:
    """Include course material + external references (week 0)."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue, Range

    # Homeworks stay narrow by default, while study mode can widen the search
    # to all earlier weeks to support review and concept reinforcement.
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
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    # Syllabus retrieval remains an exact filter because we only need the
    # single authoritative week entry, not a semantic search.
    return Filter(must=[
        FieldCondition(key="week", match=MatchValue(value=week)),
        FieldCondition(key="category", match=MatchValue(value="Syllabus")),
    ])


def _semantic_filter(week: int, *, cumulative: bool = False) -> Filter:
    """Course material + external refs (week 0), excluding syllabus."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue, Range

    # Excluding syllabus from semantic search prevents the general retrieval
    # pool from being dominated by policy text that should only appear once.
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
    from qdrant_client.models import FieldCondition, Filter, MatchValue, Range

    # Strict rules are a separate retrieval lane because they should be ranked
    # and surfaced differently from conceptual lecture context.
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
# Retriever B: Semantic (vector search, current week, exclude syllabus)
# ---------------------------------------------------------------------------

def retrieve_semantic(
    query_vector: list[float],
    week: int,
    top_k: int = 5,
    *,
    cumulative: bool = False,
    collection_name: str,
) -> list[RetrievedDoc]:
    """Vector similarity search. cumulative=True → weeks 1..X; False → exact week."""
    client = _get_client()

    hits = client.query_points(
        # Semantic retrieval shares the same collection as the other lanes; the
        # filter is what separates concept text from rules and syllabus.
        collection_name=collection_name,
        query=query_vector,
        query_filter=_semantic_filter(week, cumulative=cumulative),
        limit=top_k,
    ).points

    return [
        _hit_to_doc(h, default_source_domain=SourceDomain.MIT_OCW_LECTURE)
        for h in hits
    ]


# ---------------------------------------------------------------------------
# Retriever C: Rules (vector search, cumulative weeks 1..X + Strict_Rules only, threshold)
# ---------------------------------------------------------------------------

def retrieve_strict_rules(
    query_vector: list[float],
    week: int,
    top_k: int = 3,
    threshold: float = 0.55,
    *,
    cumulative: bool = False,
    collection_name: str,
) -> list[RetrievedDoc]:
    """Vector search for Strict_Rules. cumulative=True → weeks 1..X; False → exact week."""
    client = _get_client()

    hits = client.query_points(
        # Thresholding keeps low-similarity rules from leaking into the
        # response when the student query is only weakly related to policy text.
        collection_name=collection_name,
        query=query_vector,
        query_filter=_rules_filter(week, cumulative=cumulative),
        limit=top_k,
        score_threshold=threshold,
    ).points

    return [
        _hit_to_doc(h, default_source_domain=SourceDomain.MIT_OCW_LECTURE)
        for h in hits
    ]


# ---------------------------------------------------------------------------
# Retriever D: C++ Core Guidelines (separate collection, no week filter)
# ---------------------------------------------------------------------------

def retrieve_guidelines(
    query_vector: list[float],
    top_k: int = 3,
    threshold: float = 0.5,
) -> list[RetrievedDoc]:
    """Vector search against the C++ Core Guidelines collection.

    Guidelines are week-agnostic; no week filter is applied.  They are queried
    via a dedicated collection so that the syllabus-bound course search is never
    polluted by advanced C++ concepts from outside the current week.
    """
    client = _get_client()

    hits = client.query_points(
        collection_name=get_runtime_config().collection_guidelines,
        query=query_vector,
        limit=top_k,
        score_threshold=threshold,
    ).points

    return [
        _hit_to_doc(h, default_source_domain=SourceDomain.CPP_CORE_GUIDELINES)
        for h in hits
    ]


# ---------------------------------------------------------------------------
# Retriever E: Harvard CS50 (separate collection, week-filtered)
# ---------------------------------------------------------------------------

def _harvard_semantic_filter(week: int, *, cumulative: bool = False) -> Filter:
    """Harvard lecture notes (Pedagogical_Context + Strict_Rules), week-filtered."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue, Range

    course_condition = (
        FieldCondition(key="week", range=Range(gte=0, lte=week))
        if cumulative
        else FieldCondition(key="week", match=MatchValue(value=week))
    )
    return Filter(must=[course_condition])


def _harvard_rules_filter(week: int, *, cumulative: bool = False) -> Filter:
    """Harvard Strict_Rules only, week-filtered."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue, Range

    course_condition = (
        FieldCondition(key="week", range=Range(gte=0, lte=week))
        if cumulative
        else FieldCondition(key="week", match=MatchValue(value=week))
    )
    return Filter(must=[
        course_condition,
        FieldCondition(key="category", match=MatchValue(value="Strict_Rules")),
    ])


def retrieve_harvard(
    query_vector: list[float],
    week: int,
    top_k: int = 5,
    *,
    cumulative: bool = False,
    collection_name: str,
) -> list[RetrievedDoc]:
    """Vector similarity search against the Harvard CS50 collection."""
    client = _get_client()

    hits = client.query_points(
        collection_name=collection_name,
        query=query_vector,
        query_filter=_harvard_semantic_filter(week, cumulative=cumulative),
        limit=top_k,
    ).points

    return [
        _hit_to_doc(h, default_source_domain=SourceDomain.HARVARD_CS50)
        for h in hits
    ]


def retrieve_harvard_rules(
    query_vector: list[float],
    week: int,
    top_k: int = 3,
    threshold: float = 0.55,
    *,
    cumulative: bool = False,
    collection_name: str,
) -> list[RetrievedDoc]:
    """Vector search for Strict_Rules within the Harvard CS50 collection."""
    client = _get_client()

    hits = client.query_points(
        collection_name=collection_name,
        query=query_vector,
        query_filter=_harvard_rules_filter(week, cumulative=cumulative),
        limit=top_k,
        score_threshold=threshold,
    ).points

    return [
        _hit_to_doc(h, default_source_domain=SourceDomain.HARVARD_CS50)
        for h in hits
    ]
