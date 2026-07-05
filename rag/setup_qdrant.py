"""
Qdrant setup: create collections and index course materials.

<<<<<<< Updated upstream
Collections:
  mit13_course     — MIT 6.0013 (lecture slides + syllabus + assignments)
  mit14_course     — MIT 6.0014 (placeholder: same as MIT13)
  harvard_cs50     — Harvard CS50 (lecture notes + transcripts)
  cpp_guidelines   — C++ Core Guidelines (shared, week 0)
=======
Collections (3):
  cs50_course      — Harvard CS50 (lecture notes + transcripts)
  mit14_course     — MIT 6.0014 (lecture slides + syllabus + assignments)
  cpp_knowledge    — C++ Core Guidelines + cppreference.com (shared, week 0)

Cloud support:
  Set QDRANT_URL + QDRANT_API_KEY in .env; optional QDRANT_COLLECTION_NAME as prefix.
>>>>>>> Stashed changes

Usage:
  python setup_qdrant.py                    # index all 3 collections
  python setup_qdrant.py --course cs50      # CS50 only
  python setup_qdrant.py --course mit14     # MIT 2014 only
  python setup_qdrant.py --course cpp       # C++ knowledge only
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
    CppReferenceLoader,
    HarvardNotesLoader,
    HarvardTranscriptsLoader,
    MIT14Loader,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
QDRANT_PATH = os.path.join(os.path.dirname(__file__), "..", "qdrant_local_data")
RAW_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "raw_data")
EMBEDDING_MODEL = "BAAI/bge-large-en-v1.5"
VECTOR_SIZE = 1024

# Cloud support — set these env vars to use Qdrant Cloud instead of local
QDRANT_URL = os.environ.get("QDRANT_URL", "")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", "")
# Optional suffix for all collection names on cloud (e.g. "BAAI_bge_large_en_v1_5")
QDRANT_COLLECTION_SUFFIX = os.environ.get("QDRANT_COLLECTION_NAME", "")

COLLECTIONS = {
    "mit14": "mit14_course",
    "cs50": "harvard_cs50",
}
CPP_KNOWLEDGE_COLLECTION = "cpp_guidelines"  # guidelines + cppreference combined

# Apply suffix for cloud collections
if QDRANT_COLLECTION_SUFFIX:
    COLLECTIONS = {k: f"{v}_{QDRANT_COLLECTION_SUFFIX}" for k, v in COLLECTIONS.items()}
    CPP_KNOWLEDGE_COLLECTION = f"{CPP_KNOWLEDGE_COLLECTION}_{QDRANT_COLLECTION_SUFFIX}"

STANDARD_PAYLOAD_INDEXES = ["week", "category", "priority", "source_domain"]
GUIDELINES_PAYLOAD_INDEXES = ["source_domain"]


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------

def _ensure_collection(client: QdrantClient, name: str, indexes: list[str]) -> bool:
    """Create collection if missing. Returns True if newly created, False if already existed."""
    if client.collection_exists(name):
        print(f"Collection '{name}' already exists, skipping.")
        return False

    client.create_collection(
        collection_name=name,
        vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.DOT),
    )

    for field in indexes:
        schema = PayloadSchemaType.INTEGER if field in ("week", "priority") else PayloadSchemaType.KEYWORD
        client.create_payload_index(collection_name=name, field_name=field, field_schema=schema)

    print(f"Collection '{name}' created ({VECTOR_SIZE}-dim DOT) with indexes {indexes}.")
    return True


def _chunk_to_point(chunk) -> PointStruct:
    return PointStruct(
        id=chunk.chunk_id,
        vector=[],  # placeholder — filled by _embed_and_upsert
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
    if not _ensure_collection(client, collection, STANDARD_PAYLOAD_INDEXES):
        return 0

    # Lecture notes
    notes = HarvardNotesLoader(RAW_DATA_PATH).load_all()
    total = _embed_and_upsert(client, model, collection, notes, "CS50 notes")

    # Transcripts
    transcripts = HarvardTranscriptsLoader(RAW_DATA_PATH).load_all()
    total += _embed_and_upsert(client, model, collection, transcripts, "CS50 transcripts")

    print(f"CS50 total: {total} chunks in '{collection}'.")
    return total


def index_mit14(client: QdrantClient, model: SentenceTransformer) -> int:
    collection = COLLECTIONS["mit14"]
    if not _ensure_collection(client, collection, STANDARD_PAYLOAD_INDEXES):
        return 0

    chunks = MIT14Loader(RAW_DATA_PATH).load_all()
    total = _embed_and_upsert(client, model, collection, chunks, "MIT 2014")

    print(f"MIT14 total: {total} chunks in '{collection}'.")
    return total


def index_cpp_knowledge(client: QdrantClient, model: SentenceTransformer) -> int:
    """Combined C++ knowledge: guidelines + cppreference in one collection."""
    if not _ensure_collection(client, CPP_KNOWLEDGE_COLLECTION, GUIDELINES_PAYLOAD_INDEXES):
        return 0

    total = 0
    chunks = CppGuidelinesLoader(RAW_DATA_PATH).load_all()
    total += _embed_and_upsert(client, model, CPP_KNOWLEDGE_COLLECTION, chunks, "C++ guidelines")

    chunks = CppReferenceLoader(RAW_DATA_PATH).load_all()
    total += _embed_and_upsert(client, model, CPP_KNOWLEDGE_COLLECTION, chunks, "C++ reference")

    print(f"C++ knowledge total: {total} chunks in '{CPP_KNOWLEDGE_COLLECTION}'.")
    return total


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Set up Qdrant collections for RAG courses")
    parser.add_argument("--course", type=str, default=None,
                        choices=["cs50", "mit14", "cpp"],
                        help="Index a specific course only (default: all)")
    args = parser.parse_args()

    if QDRANT_URL:
        client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
        print(f"Qdrant Cloud mode active. Endpoint: {QDRANT_URL}")
        if QDRANT_COLLECTION_SUFFIX:
            print(f"Collection suffix: _{QDRANT_COLLECTION_SUFFIX}")
    else:
        client = QdrantClient(path=QDRANT_PATH)
        print(f"Qdrant local mode active. Data path: {QDRANT_PATH}")
    try:
        print(f"Loading embedding model: {EMBEDDING_MODEL}...")
        model = SentenceTransformer(EMBEDDING_MODEL)

        total = 0

        if args.course == "cs50" or args.course is None:
            total += index_cs50(client, model)

        if args.course in ("mit14", None):
            total += index_mit14(client, model)

        if args.course in ("cpp", None):
            total += index_cpp_knowledge(client, model)

        print(f"\nSetup complete. {total} total documents indexed.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
