"""
Qdrant setup: create collection with payload indexes, load course materials
via CourseMaterialLoader, embed with multi-qa-mpnet-base-dot-v1, and index.
Uses Qdrant local mode — no Docker required.
"""
from __future__ import annotations

import os
import sys

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PayloadSchemaType,
    PointStruct,
)
from sentence_transformers import SentenceTransformer

# Add parent dir for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rag.loader import CourseMaterialLoader, CppGuidelinesLoader

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
QDRANT_PATH = os.path.join(os.path.dirname(__file__), "..", "qdrant_local_data")
RAW_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "raw_data")
COLLECTION_NAME = "course_knowledge"
GUIDELINES_COLLECTION_NAME = "cpp_guidelines"

# multi-qa-mpnet-base-dot-v1: 768-dim, trained for dot-product similarity
EMBEDDING_MODEL = "sentence-transformers/multi-qa-mpnet-base-dot-v1"
VECTOR_SIZE = 768


def create_collection(client: QdrantClient) -> None:
    """Create collection with payload indexes for filtered retrieval."""
    if client.collection_exists(COLLECTION_NAME):
        print(f"Collection '{COLLECTION_NAME}' already exists. Recreating...")
        client.delete_collection(COLLECTION_NAME)

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.DOT),
    )

    # Payload indexes for exact-filter retrievers
    client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="week",
        field_schema=PayloadSchemaType.INTEGER,
    )
    client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="category",
        field_schema=PayloadSchemaType.KEYWORD,
    )
    client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="priority",
        field_schema=PayloadSchemaType.INTEGER,
    )
    client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="source_domain",
        field_schema=PayloadSchemaType.KEYWORD,
    )

    print(
        f"Collection '{COLLECTION_NAME}' created "
        f"(dot-product, {VECTOR_SIZE}-dim) "
        f"with payload indexes on [week, category, priority, source_domain]."
    )


def load_and_index(client: QdrantClient, model: SentenceTransformer) -> int:
    """Load course materials via CourseMaterialLoader, embed, and upsert."""
    print(f"Loading course materials from {RAW_DATA_PATH}...")
    loader = CourseMaterialLoader(RAW_DATA_PATH)
    chunks = loader.load_all()

    print(f"Embedding {len(chunks)} chunks with {EMBEDDING_MODEL}...")

    points: list[PointStruct] = []
    for i, chunk in enumerate(chunks):
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
        points.append(PointStruct(id=chunk.chunk_id, vector=vector, payload=payload))

        if (i + 1) % 50 == 0:
            print(f"  embedded {i + 1}/{len(chunks)}...")

    # Batch upsert
    batch_size = 100
    for i in range(0, len(points), batch_size):
        batch = points[i:i + batch_size]
        client.upsert(collection_name=COLLECTION_NAME, points=batch)

    print(f"Indexed {len(points)} documents in '{COLLECTION_NAME}'.")
    return len(points)


def create_guidelines_collection(client: QdrantClient) -> None:
    """Create the C++ Core Guidelines collection with minimal payload indexes."""
    if client.collection_exists(GUIDELINES_COLLECTION_NAME):
        print(f"Collection '{GUIDELINES_COLLECTION_NAME}' already exists. Recreating...")
        client.delete_collection(GUIDELINES_COLLECTION_NAME)

    client.create_collection(
        collection_name=GUIDELINES_COLLECTION_NAME,
        vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.DOT),
    )

    # Guidelines collection needs fewer indexes: no week, no category filter
    client.create_payload_index(
        collection_name=GUIDELINES_COLLECTION_NAME,
        field_name="source_domain",
        field_schema=PayloadSchemaType.KEYWORD,
    )

    print(
        f"Collection '{GUIDELINES_COLLECTION_NAME}' created "
        f"(dot-product, {VECTOR_SIZE}-dim) "
        f"with payload index on [source_domain]."
    )


def load_and_index_guidelines(client: QdrantClient, model: SentenceTransformer) -> int:
    """Load C++ Core Guidelines via CppGuidelinesLoader, embed, and upsert."""
    print(f"Loading C++ Core Guidelines from {RAW_DATA_PATH}...")
    loader = CppGuidelinesLoader(RAW_DATA_PATH)
    chunks = loader.load_all()

    print(f"Embedding {len(chunks)} guideline chunks with {EMBEDDING_MODEL}...")

    points: list[PointStruct] = []
    for i, chunk in enumerate(chunks):
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
        points.append(PointStruct(id=chunk.chunk_id, vector=vector, payload=payload))

        if (i + 1) % 50 == 0:
            print(f"  embedded {i + 1}/{len(chunks)}...")

    batch_size = 100
    for i in range(0, len(points), batch_size):
        batch = points[i:i + batch_size]
        client.upsert(collection_name=GUIDELINES_COLLECTION_NAME, points=batch)

    print(f"Indexed {len(points)} documents in '{GUIDELINES_COLLECTION_NAME}'.")
    return len(points)


def main():
    client = QdrantClient(path=QDRANT_PATH)
    try:
        print(f"Qdrant local mode active. Data path: {QDRANT_PATH}")

        print(f"Loading embedding model: {EMBEDDING_MODEL}...")
        model = SentenceTransformer(EMBEDDING_MODEL)

        # Course knowledge collection
        create_collection(client)
        course_count = load_and_index(client, model)
        print(f"Setup complete. {course_count} documents indexed in '{COLLECTION_NAME}'.")

        # C++ Core Guidelines collection
        create_guidelines_collection(client)
        guidelines_count = load_and_index_guidelines(client, model)
        print(f"Setup complete. {guidelines_count} documents indexed in '{GUIDELINES_COLLECTION_NAME}'.")

        total = course_count + guidelines_count
        print(f"\nTotal: {total} documents across 2 collections.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
