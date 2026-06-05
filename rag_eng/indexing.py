"""Reusable indexing flows for Qdrant Cloud bootstrap and rebuild operations."""

from __future__ import annotations

from dataclasses import dataclass

from rag.loader import CourseMaterialLoader
from rag.runtime import create_qdrant_client

from rag_eng.config import get_settings


VECTOR_SIZE = 768


@dataclass(frozen=True)
class IndexingResult:
    """Summary returned by ensure/rebuild index operations."""

    collection_name: str
    indexed_documents: int
    created_collection: bool
    message: str


def _collection_name() -> str:
    return get_settings().qdrant_collection_name


def _embedding_model_name() -> str:
    return get_settings().embedding_model


def _raw_data_path() -> str:
    return get_settings().raw_data_path


def _ensure_collection(client, *, recreate: bool) -> bool:
    """Create the collection if it is missing, optionally recreating it."""
    from qdrant_client.models import Distance, VectorParams

    collection_name = _collection_name()
    exists = client.collection_exists(collection_name)
    if exists and recreate:
        client.delete_collection(collection_name)
        exists = False

    if not exists:
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.DOT),
        )
        return True
    return False


def _ensure_payload_indexes(client) -> None:
    """Best-effort payload index creation for exact-match filters."""
    from qdrant_client.models import PayloadSchemaType

    index_specs = (
        ("week", PayloadSchemaType.INTEGER),
        ("category", PayloadSchemaType.KEYWORD),
        ("priority", PayloadSchemaType.INTEGER),
        ("source_domain", PayloadSchemaType.KEYWORD),
    )

    for field_name, schema in index_specs:
        try:
            client.create_payload_index(
                collection_name=_collection_name(),
                field_name=field_name,
                field_schema=schema,
            )
        except Exception:
            # Qdrant may reject duplicate payload index creation. Repeated ensure
            # runs should stay safe, so duplicate-index errors are ignored.
            continue


def _build_points():
    """Load, embed, and convert chunks into Qdrant point structs."""
    from qdrant_client.models import PointStruct
    from sentence_transformers import SentenceTransformer

    loader = CourseMaterialLoader(_raw_data_path())
    model = SentenceTransformer(_embedding_model_name())

    points: list[PointStruct] = []
    chunks = loader.load_all()
    for chunk in chunks:
        vector = model.encode(chunk.content).tolist()
        payload = {
            "chunk_id": chunk.chunk_id,
            "content": chunk.content,
            "week": chunk.week,
            "category": chunk.category.value,
            "topic": chunk.topic,
            "priority": chunk.priority,
            "parent_chunk_id": chunk.parent_chunk_id,
            "source_domain": chunk.source_domain.value,
            "source_type": chunk.source_type,
            "page_number": chunk.page_number,
        }
        points.append(
            PointStruct(
                id=chunk.chunk_id,
                vector=vector,
                payload=payload,
            )
        )
    return points


def _upsert_points(client, points) -> int:
    """Batch upsert point payloads into Qdrant."""
    batch_size = 100
    for start in range(0, len(points), batch_size):
        batch = points[start : start + batch_size]
        client.upsert(collection_name=_collection_name(), points=batch)
    return len(points)


def ensure_index() -> IndexingResult:
    """Safely ensure the collection exists and upsert all indexed documents."""
    client = create_qdrant_client()
    try:
        created_collection = _ensure_collection(client, recreate=False)
        _ensure_payload_indexes(client)
        indexed_documents = _upsert_points(client, _build_points())
    finally:
        client.close()

    message = "Collection ensured and documents upserted successfully."
    return IndexingResult(
        collection_name=_collection_name(),
        indexed_documents=indexed_documents,
        created_collection=created_collection,
        message=message,
    )


def rebuild_index() -> IndexingResult:
    """Explicitly rebuild the collection from scratch."""
    client = create_qdrant_client()
    try:
        _ensure_collection(client, recreate=True)
        _ensure_payload_indexes(client)
        indexed_documents = _upsert_points(client, _build_points())
    finally:
        client.close()

    return IndexingResult(
        collection_name=_collection_name(),
        indexed_documents=indexed_documents,
        created_collection=True,
        message="Collection rebuilt and documents reindexed successfully.",
    )
