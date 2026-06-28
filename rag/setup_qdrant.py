"""
Qdrant setup: create collections and index course materials per course.

Collections:
  mit13_course     — MIT 6.0013 (lecture slides + syllabus + assignments)
  mit14_course     — MIT 6.0014 (placeholder: same as MIT13)
  harvard_cs50     — Harvard CS50 (lecture notes + transcripts)
  cpp_guidelines   — C++ Core Guidelines (shared, week 0)

Usage:
  python setup_qdrant.py                    # index all courses
  python setup_qdrant.py --course cs50      # index CS50 only
  python setup_qdrant.py --course mit13     # index MIT13 only
"""

from __future__ import annotations

import argparse
import os
import sys

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)
from sentence_transformers import SentenceTransformer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rag.loader import (
    CourseMaterialLoader,
    CppGuidelinesLoader,
    HarvardNotesLoader,
    HarvardTranscriptsLoader,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
QDRANT_PATH = os.path.join(os.path.dirname(__file__), "..", "qdrant_local_data")
RAW_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "raw_data")
EMBEDDING_MODEL = "sentence-transformers/multi-qa-mpnet-base-dot-v1"
VECTOR_SIZE = 768

COLLECTIONS = {
    "mit13": "mit13_course",
    "mit14": "mit14_course",
    "cs50": "harvard_cs50",
}
GUIDELINES_COLLECTION = "cpp_guidelines"

STANDARD_PAYLOAD_INDEXES = ["week", "category", "priority", "source_domain"]
GUIDELINES_PAYLOAD_INDEXES = ["source_domain"]


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------

def _ensure_collection(client: QdrantClient, name: str, indexes: list[str]) -> None:
    if client.collection_exists(name):
        print(f"Collection '{name}' already exists. Recreating...")
        client.delete_collection(name)

    client.create_collection(
        collection_name=name,
        vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.DOT),
    )

    for field in indexes:
        schema = PayloadSchemaType.INTEGER if field in ("week", "priority") else PayloadSchemaType.KEYWORD
        client.create_payload_index(collection_name=name, field_name=field, field_schema=schema)

    print(f"Collection '{name}' created ({VECTOR_SIZE}-dim DOT) with indexes {indexes}.")


def _chunk_to_point(chunk) -> PointStruct:
    return PointStruct(
        id=chunk.chunk_id,
        vector=None,  # filled later
        payload={
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
        },
    )


def _embed_and_upsert(
    client: QdrantClient,
    model: SentenceTransformer,
    collection_name: str,
    chunks: list,
    label: str,
) -> int:
    if not chunks:
        print(f"  No {label} chunks to index.")
        return 0

    print(f"  Embedding {len(chunks)} {label} chunks...")
    points = [_chunk_to_point(c) for c in chunks]

    for i, pt in enumerate(points):
        text = pt.payload["content"]
        pt.vector = model.encode(text).tolist()
        if (i + 1) % 200 == 0:
            print(f"    embedded {i + 1}/{len(points)}...")

    batch_size = 100
    for i in range(0, len(points), batch_size):
        client.upsert(collection_name=collection_name, points=points[i:i + batch_size])

    print(f"  Indexed {len(points)} {label} chunks in '{collection_name}'.")
    return len(points)


# ---------------------------------------------------------------------------
# Per-course indexing
# ---------------------------------------------------------------------------

def index_cs50(client: QdrantClient, model: SentenceTransformer) -> int:
    collection = COLLECTIONS["cs50"]
    _ensure_collection(client, collection, STANDARD_PAYLOAD_INDEXES)

    # Lecture notes
    notes = HarvardNotesLoader(RAW_DATA_PATH).load_all()
    total = _embed_and_upsert(client, model, collection, notes, "CS50 notes")

    # Transcripts
    transcripts = HarvardTranscriptsLoader(RAW_DATA_PATH).load_all()
    total += _embed_and_upsert(client, model, collection, transcripts, "CS50 transcripts")

    print(f"CS50 total: {total} chunks in '{collection}'.")
    return total


def index_mit(client: QdrantClient, model: SentenceTransformer, course: str) -> int:
    collection = COLLECTIONS[course]
    _ensure_collection(client, collection, STANDARD_PAYLOAD_INDEXES)

    chunks = CourseMaterialLoader(RAW_DATA_PATH).load_all()
    total = _embed_and_upsert(client, model, collection, chunks, f"{course} course")

    print(f"{course.upper()} total: {total} chunks in '{collection}'.")
    return total


def index_guidelines(client: QdrantClient, model: SentenceTransformer) -> int:
    _ensure_collection(client, GUIDELINES_COLLECTION, GUIDELINES_PAYLOAD_INDEXES)

    chunks = CppGuidelinesLoader(RAW_DATA_PATH).load_all()
    return _embed_and_upsert(client, model, GUIDELINES_COLLECTION, chunks, "C++ guidelines")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Set up Qdrant collections for RAG courses")
    parser.add_argument("--course", type=str, default=None,
                        choices=["cs50", "mit13", "mit14", "guidelines"],
                        help="Index a specific course only (default: all)")
    args = parser.parse_args()

    client = QdrantClient(path=QDRANT_PATH)
    try:
        print(f"Qdrant local mode active. Data path: {QDRANT_PATH}")
        print(f"Loading embedding model: {EMBEDDING_MODEL}...")
        model = SentenceTransformer(EMBEDDING_MODEL)

        total = 0

        if args.course == "cs50" or args.course is None:
            total += index_cs50(client, model)

        if args.course in ("mit13", None):
            total += index_mit(client, model, "mit13")

        if args.course in ("mit14", None):
            total += index_mit(client, model, "mit14")

        if args.course in ("guidelines", None):
            total += index_guidelines(client, model)

        print(f"\nSetup complete. {total} total documents indexed.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
