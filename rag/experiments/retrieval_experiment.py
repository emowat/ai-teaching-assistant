#!/usr/bin/env python3
"""
retrieval_experiment.py  —  Reusable RAG Retrieval Experiment Pipeline

Exports: load_golden_queries, load_harvard_cs50_chunks, build_index,
         compute_metrics, run_experiment, GoldenQuery, ExpChunk.

Grid: embeddings x top_k x rerank.  Index rebuilds per embedding model.

run_experiment() accepts an optional retrieve_fn for custom retrieval strategies
(e.g. BM25+vector hybrid). Import this module from add_bm25.py or similar.

Usage:
  export QDRANT_URL="https://..." QDRANT_API_KEY="..."
  export MLFLOW_TRACKING_URI="https://..."
  python retrieval_experiment.py                     # full grid
  python retrieval_experiment.py --quick             # 1 model, fewer rerank
  python retrieval_experiment.py --dry-run           # validate setup
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import os
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import numpy as np

# ---------------------------------------------------------------------------
# Paths (S3-first, mirrors labeling_chunks.py)
# ---------------------------------------------------------------------------

S3_BUCKET = os.getenv("RAG_EXPERIMENT_S3_BUCKET", "codingrabbit-data-dev")

# Raw data path (S3 or local)
RAW_DATA_PATH = os.getenv(
    "RAG_EXPERIMENT_RAW_DATA_PATH",
    f"s3://{S3_BUCKET}/raw/rag_sources/Harvard/cs50_output/notes_json/",
)

# Golden labels path (S3 or local)
GOLDEN_LABELS_PATH = os.getenv(
    "RAG_EXPERIMENT_GOLDEN_LABELS_PATH",
    f"s3://{S3_BUCKET}/prepared/outputs/golden_labels_cs50_validated.json",
)

HARVARD_TRANSCRIPTS_PATH = os.getenv(
    "RAG_EXPERIMENT_TRANSCRIPTS_PATH",
    f"s3://{S3_BUCKET}/raw/rag_sources/Harvard/cs50_transcripts/",
)

CPP_GUIDELINES_PATH = os.getenv(
    "RAG_EXPERIMENT_GUIDELINES_PATH",
    f"s3://{S3_BUCKET}/raw/rag_sources/cppcoreguidelines/cppcoreguidelines.json",
)

EVAL_QUERIES_PATH = os.getenv(
    "RAG_EXPERIMENT_EVAL_QUERIES_PATH",
    f"s3://{S3_BUCKET}/prepared/rag/experiments/outputs/eval_queries_cs50.jsonl",
)

# Output prefix (S3 or local)
OUTPUT_PREFIX = os.getenv(
    "RAG_EXPERIMENT_OUTPUT_PREFIX",
    f"s3://{S3_BUCKET}/prepared/rag/experiments/outputs/",
)

OUTPUT_DIR = OUTPUT_PREFIX

def _is_s3_url(path: str | Path) -> bool:
    s = str(path)
    return s.startswith("s3://") or "console.aws.amazon.com/s3/object/" in s


def _parse_s3_url(url: str) -> tuple[str, str | None]:
    s = str(url)
    if s.startswith("s3://"):
        rest = s[len("s3://"):]
        parts = rest.split("/", 1)
        return parts[0], parts[1] if len(parts) > 1 else None

    p = urlparse(s)
    if "console.aws.amazon.com" in p.netloc and "/s3/object/" in p.path:
        bucket = p.path.split("/s3/object/", 1)[1].strip("/ ")
        key = parse_qs(p.query).get("prefix", [None])[0]
        return bucket, key

    raise ValueError(f"Unrecognized S3 URL: {url}")


def _get_s3_client() -> Any:
    try:
        import boto3
        from botocore import UNSIGNED
        from botocore.client import Config
    except ModuleNotFoundError as e:
        raise RuntimeError("S3 paths require boto3/botocore. Install boto3 or use local paths.") from e

    if os.environ.get("S3_ANONYMOUS", "0") in ("1", "true", "True"):
        return boto3.client("s3", config=Config(signature_version=UNSIGNED))
    return boto3.client("s3")


def _read_text(path: Path | str) -> str:
    if isinstance(path, Path):
        path = str(path)

    if _is_s3_url(path):
        bucket, key = _parse_s3_url(path)
        if not key:
            raise ValueError(f"S3 object key not found in URL: {path}")
        s3 = _get_s3_client()
        try:
            obj = s3.get_object(Bucket=bucket, Key=key)
        except Exception as e:
            raise FileNotFoundError(f"Could not read s3://{bucket}/{key}: {e}") from e
        return obj["Body"].read().decode("utf-8")

    return Path(path).read_text(encoding="utf-8")


def _write_json(path: Path | str, data: Any) -> None:
    if isinstance(path, Path):
        path = str(path)
    text = json.dumps(data, indent=2, default=str)

    if _is_s3_url(path):
        bucket, key = _parse_s3_url(path)
        if not key:
            raise ValueError(f"S3 object key not found in URL: {path}")
        s3 = _get_s3_client()
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=text.encode("utf-8"),
            ContentType="application/json",
        )
        return

    local_path = Path(path)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(text, encoding="utf-8")

# ---------------------------------------------------------------------------
# 1. Golden Labels Loading
# ---------------------------------------------------------------------------

@dataclass
class GoldenQuery:
    query_id: str
    student_message: str
    week: int
    mode: str
    golden_chunk_ids: set[str]          # chunk IDs that should be retrieved


def load_golden_queries(path: Path | str) -> list[GoldenQuery]:
    """Load golden queries from a local file or S3 path."""
    attempted: list[str] = []
    text = ""
    loaded_path = ""
    for candidate in [str(path)]:
        if candidate in attempted:
            continue
        attempted.append(candidate)
        try:
            text = _read_text(candidate)
            loaded_path = candidate
            break
        except (FileNotFoundError, RuntimeError) as e:
            print(f"  [golden labels] not found: {candidate} ({e})")

    if not text:
        raise FileNotFoundError(
            "Could not load golden labels from any candidate path:\n"
            + "\n".join(f"  - {p}" for p in attempted)
        )

    if loaded_path != str(path):
        print(f"  [golden labels] using fallback: {loaded_path}")

    data = json.loads(text)

    # New labeling output is qid -> [chunk_id, ...]. Merge it with eval_queries.jsonl.
    if data and all(isinstance(v, list) for v in data.values()):
        eval_queries = _load_eval_query_metadata()
        return [
            GoldenQuery(
                query_id=qid,
                student_message=eval_queries[qid]["student_message"],
                week=eval_queries[qid]["week"],
                mode=eval_queries[qid]["mode"],
                golden_chunk_ids=set(chunk_ids),
            )
            for qid, chunk_ids in data.items()
            if qid in eval_queries
        ]

    queries: list[GoldenQuery] = []
    for qid, entry in data.items():
        found_chunks = entry.get("found_chunks", {})
        if isinstance(found_chunks, list):
            golden_ids = set(found_chunks)
        else:
            golden_ids = set(found_chunks.keys())
        queries.append(GoldenQuery(
            query_id=qid,
            student_message=entry["student_message"],
            week=entry["week"],
            mode=entry["mode"],
            golden_chunk_ids=golden_ids,
        ))
    return queries


def _load_eval_query_metadata() -> dict[str, dict[str, Any]]:
    candidates = [
        EVAL_QUERIES_PATH,
        str(Path(__file__).resolve().parent / "outputs" / "eval_queries.jsonl"),
    ]
    for candidate in candidates:
        try:
            text = _read_text(candidate)
            return {
                rec["query_id"]: rec
                for rec in (json.loads(line) for line in text.splitlines() if line.strip())
            }
        except (FileNotFoundError, RuntimeError) as e:
            print(f"  [eval queries] not found: {candidate} ({e})")

    raise FileNotFoundError(
        "Golden labels are stored as qid -> list, so eval_queries.jsonl is required. "
        "Set RAG_EXPERIMENT_EVAL_QUERIES_PATH or upload eval_queries.jsonl beside the labels."
    )


# ---------------------------------------------------------------------------
# 2. Corpus Loading
# ---------------------------------------------------------------------------

@dataclass
class ExpChunk:
    """Lightweight chunk for experiment indexing."""
    chunk_id: str
    content: str
    week: int
    category: str
    source_domain: str


# Reuse the standalone loader logic from labeling_chunks
_STRICT_RULE_PATTERNS = [
    __import__("re").compile(r"\b(must|always|never)\b", __import__("re").IGNORECASE),
    __import__("re").compile(r"\b(remember to|ensure that|be careful|make sure)\b", __import__("re").IGNORECASE),
    __import__("re").compile(r"\b(do not|don't|avoid|forbidden|prohibited)\b", __import__("re").IGNORECASE),
    __import__("re").compile(r"\b(critical|mandatory|required|essential)\b", __import__("re").IGNORECASE),
]
_CHUNK_NAMESPACE = uuid.UUID("58dbf568-51bb-4d4e-8cf9-c6a8a797d065")
_LECTURE_WEEK_MAP = {
    "01_lecture_1_compilation_pipeline": 1,
    "02_lecture_2_core_c": 2,
    "03_lecture_3_c_memory_management": 3,
    "04_lecture_4_data_structures_debugging": 4,
    "05_lecture_5_c_introduction_classes_and_templates": 5,
    "06_lecture_6_c_inheritance": 6,
    "07_lecture_7_parent_destructors": 7,
    "08_lecture_8_standard_template_library": 8,
}
SYLLABUS_MATRIX = {
    1: {"name": "C Basics", "allowed": "printf, primitive types, main",
        "forbidden": "pointers, arrays, structures, new/delete"},
    2: {"name": "Arrays & Strings", "allowed": "arrays, string.h, functions",
        "forbidden": "pointers, dynamic allocation, structures"},
    3: {"name": "Pointers & Memory", "allowed": "raw pointers, references, stack allocation, address-of (&)",
        "forbidden": "new/delete, vectors, smart pointers"},
    4: {"name": "Manual Heap Management", "allowed": "new, delete, malloc, free, references",
        "forbidden": "std::vector, smart pointers, RAII objects"},
    5: {"name": "Object-Oriented C++", "allowed": "classes, inheritance, virtual functions, operator overload",
        "forbidden": "templates"},
    6: {"name": "Modern C++ & STL", "allowed": "std::vector, std::unique_ptr, RAII, templates, STL",
        "forbidden": "raw malloc/free, bare new/delete"},
    7: {"name": "Algorithms & Complexity", "allowed": "recursion, sorting algorithms, Big O notation, binary search trees",
        "forbidden": "raw malloc/free, bare new/delete"},
    8: {"name": "Advanced Data Structures", "allowed": "hash tables, tries, queues, stacks, linked lists",
        "forbidden": "raw malloc/free, bare new/delete"},
}


def _resolve_week(filename: str) -> int:
    for key, week in _LECTURE_WEEK_MAP.items():
        if key in filename:
            return week
    return 1


def _stable_chunk_id(*parts: object) -> str:
    return str(uuid.uuid5(_CHUNK_NAMESPACE, "::".join(str(p) for p in parts)))


def _classify_category(text: str, has_code: bool, source: str) -> str:
    if source == "syllabus":
        return "Syllabus"
    if source == "assignment_solution":
        return "Supplementary"
    for pat in _STRICT_RULE_PATTERNS:
        if pat.search(text):
            return "Strict_Rules"
    return "Pedagogical_Context"


def _strip_headers(text: str) -> str:
    lines = text.split("\n")
    result: list[str] = []
    header_done, has_marker = False, False
    for line in lines:
        if header_done:
            result.append(line)
        elif line.startswith("==="):
            header_done = True
            has_marker = True
    if not has_marker:
        return text.strip()
    return "\n".join(result).strip()


def load_slide_chunks(raw_data_path: Path, overlap: int = 0) -> list[ExpChunk]:
    """
    Load MIT course chunks. If overlap > 0, each slide chunk includes up to
    `overlap` adjacent slides' content appended, keeping the same chunk_id
    (so golden labels remain valid).
    """
    import json as _json

    chunks: list[ExpChunk] = []
    lecture_dir = raw_data_path / "lecture_text"
    syllabus_path = raw_data_path / "mit_ocw_output" / "syllabus.txt"

    # --- Lecture slides ---
    json_files = sorted(lecture_dir.glob("*.json"))
    json_files = [f for f in json_files if "assignment" not in f.name.lower()]

    for json_file in json_files:
        week = _resolve_week(json_file.name)
        try:
            data = _json.loads(json_file.read_text(encoding="utf-8"))
        except _json.JSONDecodeError:
            continue

        # Collect non-empty slides for this lecture
        slides: list[dict] = []
        for slide in data:
            if str(slide.get("text", "")).strip():
                slides.append(slide)

        for i, slide in enumerate(slides):
            text = str(slide["text"]).strip()
            section = str(slide.get("section", ""))
            has_code = bool(slide.get("has_code", False))
            page = slide.get("page")

            # Build content with optional overlap
            content_parts = [f"[{section}] {text}" if section else text]
            for offset in range(1, overlap + 1):
                for direction in [-1, 1]:
                    ni = i + offset * (1 if direction == 1 else -1)
                    if 0 <= ni < len(slides):
                        adj = slides[ni]
                        adj_text = str(adj["text"]).strip()
                        if adj_text:
                            adj_section = str(adj.get("section", ""))
                            prefix = f"[{adj_section}] " if adj_section else ""
                            content_parts.append(f"(adjacent {direction:+d}) {prefix}{adj_text}")

            content = " | ".join(content_parts)[:3000]

            category = _classify_category(text, has_code, source="lecture")
            chunk_id = _stable_chunk_id("lecture", json_file.name, page, section, text[:2000])
            # Note: chunk_id uses ORIGINAL content (not overlap), so golden labels match

            chunks.append(ExpChunk(
                chunk_id=chunk_id, content=content, week=week,
                category=category, source_domain="mit_ocw_lecture",
            ))

    # --- Syllabus ---
    if syllabus_path.exists():
        raw_text = syllabus_path.read_text(encoding="utf-8")
        body = _strip_headers(raw_text)
        for week, info in SYLLABUS_MATRIX.items():
            chunk_id = _stable_chunk_id("syllabus", week, info["name"])
            content = (
                f"Week: {week} - {info['name']}\n"
                f"Allowed: {info['allowed']}\n"
                f"Forbidden: {info['forbidden']}\n\n"
                f"Course Description: {body[:500]}"
            )
            chunks.append(ExpChunk(
                chunk_id=chunk_id, content=content, week=week,
                category="Syllabus", source_domain="mit_ocw_syllabus",
            ))

    # --- Assignment solutions ---
    for json_file in sorted(lecture_dir.glob("assignment*_solution.json")):
        try:
            data = _json.loads(json_file.read_text(encoding="utf-8"))
        except _json.JSONDecodeError:
            continue
        for slide in data:
            text = str(slide.get("text", "")).strip()
            if not text:
                continue
            chunk_id = _stable_chunk_id("assignment_solution", json_file.name, slide.get("page"), text[:2000])
            chunks.append(ExpChunk(
                chunk_id=chunk_id, content=text[:2000], week=4,
                category="Supplementary", source_domain="mit_ocw_assignment",
            ))

    return chunks


def load_harvard_cs50_chunks(raw_data_path: Path | str, overlap: int = 0) -> list[ExpChunk]:
    """Load Harvard CS50 notes, transcripts, and C++ Core Guidelines — same chunks as labeling."""
    experiments_dir = Path(__file__).resolve().parent
    if str(experiments_dir) not in sys.path:
        sys.path.insert(0, str(experiments_dir))

    from labeling_chunks import load_harvard_notes, load_harvard_transcripts, load_cpp_guidelines

    if overlap:
        print("  [chunking] overlap ignored for Harvard CS50 chunks.")

    def _to_exp(c) -> ExpChunk:
        return ExpChunk(chunk_id=c.chunk_id, content=c.content, week=c.week,
                        category=c.category, source_domain=c.source_domain)

    chunks = [_to_exp(c) for c in load_harvard_notes(raw_data_path)]
    print(f"  Notes: {len(chunks)} chunks")

    tx = load_harvard_transcripts(HARVARD_TRANSCRIPTS_PATH)
    chunks.extend(_to_exp(c) for c in tx)
    print(f"  Transcripts: {len(tx)} chunks")

    cpp = load_cpp_guidelines(CPP_GUIDELINES_PATH)
    chunks.extend(_to_exp(c) for c in cpp)
    print(f"  C++ Guidelines: {len(cpp)} chunks")

    return chunks


# ---------------------------------------------------------------------------
# 3. Qdrant Indexing
# ---------------------------------------------------------------------------

class OpenAIEmbeddingModel:
    """Small adapter matching the SentenceTransformer encode() surface we use."""

    def __init__(self, model_name: str):
        try:
            from openai import OpenAI
        except ModuleNotFoundError as e:
            raise RuntimeError(
                "OpenAI embedding models require the openai package. "
                "Install dependencies with `pip install -r requirements.txt`."
            ) from e

        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError(f"{model_name} requires OPENAI_API_KEY to be set.")

        self.model_name = model_name
        self.client = OpenAI()
        self._dimension: int | None = None

    def get_sentence_embedding_dimension(self) -> int:
        if self._dimension is None:
            vector = self.encode("dimension probe", normalize_embeddings=True)
            self._dimension = int(vector.shape[0])
        return self._dimension

    def encode(
        self,
        texts: str | list[str],
        normalize_embeddings: bool = True,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        single_input = isinstance(texts, str)
        input_texts = [texts] if single_input else texts
        if not input_texts:
            return np.array([])

        response = self.client.embeddings.create(
            model=self.model_name,
            input=input_texts,
        )
        vectors = np.array(
            [item.embedding for item in sorted(response.data, key=lambda item: item.index)],
            dtype=np.float32,
        )
        if normalize_embeddings:
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            vectors = vectors / np.maximum(norms, 1e-12)

        if self._dimension is None and vectors.size:
            self._dimension = int(vectors.shape[1])

        return vectors[0] if single_input else vectors


def _load_embedding_model(embedding_model_name: str) -> Any:
    if embedding_model_name.startswith("text-embedding-"):
        return OpenAIEmbeddingModel(embedding_model_name)

    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(embedding_model_name)


def _get_qdrant_client():
    from qdrant_client import QdrantClient
    url = os.getenv("QDRANT_URL", "")
    api_key = os.getenv("QDRANT_API_KEY", "")
    if url:
        return QdrantClient(url=url, api_key=api_key)
    # Fallback: local temp directory
    import tempfile
    local_path = os.path.join(tempfile.gettempdir(), f"qdrant_exp_{uuid.uuid4().hex[:8]}")
    print(f"  [qdrant] Local fallback: {local_path}")
    return QdrantClient(path=local_path)


def build_index(
    chunks: list[ExpChunk],
    embedding_model_name: str,
    collection_name: str,
    vector_size: int = 768,
) -> Any:
    """Build a Qdrant collection with embedded chunk vectors. Returns the client."""
    from qdrant_client.models import Distance, PointStruct, VectorParams, PayloadSchemaType

    print(f"  Loading embedding model: {embedding_model_name} ...")
    model = _load_embedding_model(embedding_model_name)
    actual_dim = model.get_sentence_embedding_dimension()

    client = _get_qdrant_client()

    # Ensure collection
    if client.collection_exists(collection_name):
        print(f"  Deleting existing collection: {collection_name}")
        client.delete_collection(collection_name)

    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=actual_dim, distance=Distance.COSINE),
    )
    print(f"  Created collection: {collection_name} (dim={actual_dim})")

    # Embed and upsert in small batches so SageMaker jobs do not retain all
    # vectors and full text payloads in memory at once.
    batch_size = int(os.getenv("RAG_EXPERIMENT_EMBED_BATCH_SIZE", "8"))
    indexed_count = 0
    print(f"  Embedding/upserting in batches of {batch_size} ...")
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start:start + batch_size]
        texts = [c.content for c in batch]
        vectors = model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).tolist()
        points = []
        for c, vec in zip(batch, vectors):
            points.append(PointStruct(
                id=c.chunk_id,
                vector=vec,
                payload={
                    "chunk_id": c.chunk_id,
                    "content": c.content,
                    "week": c.week,
                    "category": c.category,
                    "source_domain": c.source_domain,
                },
            ))
        client.upsert(collection_name=collection_name, points=points)
        indexed_count += len(points)

    # Payload indexes for filtered search
    for field in ["week", "category"]:
        schema = PayloadSchemaType.INTEGER if field == "week" else PayloadSchemaType.KEYWORD
        try:
            client.create_payload_index(collection_name=collection_name, field_name=field, field_schema=schema)
        except Exception:
            pass

    print(f"  Indexed {indexed_count} points.")
    return client, model


# ---------------------------------------------------------------------------
# 4. Retrieval
# ---------------------------------------------------------------------------

def _token_set(text: str) -> set[str]:
    return set(text.lower().split())


def _jaccard_sim(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _mmr_rerank(
    candidates: list[tuple[str, float, str]],
    top_k: int,
    lambda_param: float,
) -> list[tuple[str, float, str]]:
    """Diversify scored candidates with the same Jaccard-token MMR style as production."""
    if len(candidates) <= top_k:
        return candidates

    selected: list[tuple[str, float, str]] = []
    remaining = list(candidates)
    remaining_sets = [_token_set(content) for _, _, content in remaining]

    while len(selected) < top_k and remaining:
        if not selected:
            best_idx = 0
        else:
            best_score = -math.inf
            best_idx = 0
            selected_sets = [_token_set(content) for _, _, content in selected]
            for i, (_, score, _) in enumerate(remaining):
                max_sim = max(_jaccard_sim(remaining_sets[i], s) for s in selected_sets)
                mmr_score = lambda_param * score - (1 - lambda_param) * max_sim
                if mmr_score > best_score:
                    best_score = mmr_score
                    best_idx = i

        selected.append(remaining.pop(best_idx))
        remaining_sets.pop(best_idx)

    return selected


def retrieve(
    client: Any,
    model: Any,
    query_text: str,
    query_week: int,
    collection_name: str,
    top_k: int,
    rerank_strategy: str,
) -> list[str]:
    """Vector retrieval with week filter (current week and prior only) + optional MMR rerank."""

    query_vector = model.encode(query_text, normalize_embeddings=True).tolist()
    fetch_k = top_k * 4 if rerank_strategy.startswith("mmr") else top_k

    from qdrant_client.models import FieldCondition, Filter, Range
    week_filter = Filter(
        must=[FieldCondition(key="week", range=Range(lte=query_week))]
    )

    hits = client.query_points(
        collection_name=collection_name,
        query=query_vector,
        query_filter=week_filter,
        limit=fetch_k,
    ).points

    retrieved: list[tuple[str, float, str]] = [
        (str(h.id), h.score, str((h.payload or {}).get("content", "")))
        for h in hits
    ]

    if rerank_strategy.startswith("mmr"):
        lambda_param = float(rerank_strategy.removeprefix("mmr_"))
        retrieved = _mmr_rerank(retrieved, top_k=top_k, lambda_param=lambda_param)

    return [cid for cid, _, _ in retrieved[:top_k]]


# ---------------------------------------------------------------------------
# 5. Metrics Computation
# ---------------------------------------------------------------------------

def compute_metrics(
    retrieved_ids: list[str],
    golden_ids: set[str],
    k: int,
) -> dict[str, float]:
    """Compute Recall@K, Precision@K, MRR, NDCG@K."""
    retrieved_set = set(retrieved_ids[:k])
    retrieved_list = retrieved_ids[:k]

    # Recall@K
    hits = golden_ids & retrieved_set
    recall = len(hits) / len(golden_ids) if golden_ids else 1.0

    # Precision@K
    precision = len(hits) / k if k > 0 else 0.0

    # F1@K
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall > 0
        else 0.0
    )

    # MRR
    mrr = 0.0
    for i, cid in enumerate(retrieved_list):
        if cid in golden_ids:
            mrr = 1.0 / (i + 1)
            break

    # NDCG@K
    dcg = 0.0
    idcg = 0.0
    for i, cid in enumerate(retrieved_list):
        rel = 1.0 if cid in golden_ids else 0.0
        dcg += rel / np.log2(i + 2)  # i+2 because log2(1)=0
    for i in range(min(len(golden_ids), k)):
        idcg += 1.0 / np.log2(i + 2)
    ndcg = dcg / idcg if idcg > 0 else 0.0

    return {
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "f1": round(f1, 4),
        f"recall@{k}": round(recall, 4),
        f"precision@{k}": round(precision, 4),
        f"f1@{k}": round(f1, 4),
        "mrr": round(mrr, 4),
        f"ndcg@{k}": round(ndcg, 4),
    }


# ---------------------------------------------------------------------------
# 6. Experiment Runner
# ---------------------------------------------------------------------------

# --- Config Grid ---
EMBEDDING_MODELS = [
    "all-MiniLM-L6-v2",
    "sentence-transformers/multi-qa-mpnet-base-dot-v1",
    # "BAAI/bge-base-en-v1.5",
    # "intfloat/e5-base-v2",
    "text-embedding-3-small",
    # "intfloat/e5-large-v2",
]

# TOP_K_VALUES = [3, 5, 8, 10, 15, 20]
TOP_K_VALUES = [15, 20]

RERANK_STRATEGIES = [
    "similarity",
    "mmr_0.5",
    "mmr_0.7",
    "mmr_0.9",
]


def _metric_key(metric_name: str, top_k: int) -> str:
    return f"{metric_name}@{top_k}"


def _mlflow_metric_name(metric_name: str) -> str:
    """Convert display metric names like recall@10 into MLflow-safe names."""
    return metric_name.replace("@", "_at_")


def _log_mlflow_metrics(metrics: dict[str, float], latency: float | None = None) -> None:
    import mlflow

    mlflow.log_metrics({
        _mlflow_metric_name(key): value
        for key, value in metrics.items()
    })
    if latency is not None:
        mlflow.log_metric("latency_seconds", latency)


def _f1_for_result(result: dict) -> float:
    top_k = result["params"]["top_k"]
    return result["metrics"].get(_metric_key("f1", top_k), result["metrics"].get("f1", 0.0))


def _log_best_f1_run(best: dict, total_runs: int) -> None:
    import mlflow

    params = best["params"]
    metrics = best["metrics"]
    top_k = params["top_k"]

    best_params = {
        f"best_{key}": value
        for key, value in params.items()
    }
    best_params["selection_metric"] = _metric_key("f1", top_k)
    best_params["total_candidate_runs"] = total_runs

    best_metrics = {
        "best_f1": _f1_for_result(best),
        "best_recall": metrics.get(_metric_key("recall", top_k), metrics.get("recall", 0.0)),
        "best_precision": metrics.get(_metric_key("precision", top_k), metrics.get("precision", 0.0)),
        "best_mrr": metrics.get("mrr", 0.0),
        "best_ndcg": metrics.get(_metric_key("ndcg", top_k), 0.0),
        "best_latency_seconds": best["latency"],
    }

    with mlflow.start_run(run_name="best_f1_summary"):
        mlflow.log_params(best_params)
        _log_mlflow_metrics(best_metrics)


def run_experiment(
    golden_queries: list[GoldenQuery],
    chunks: list[ExpChunk],
    embedding_model_name: str,
    top_k: int,
    collection_name: str,
    client: Any,
    model: Any,
    rerank_strategy: str,
    retrieve_fn: Any = None,
    mlflow_active: bool = True,
) -> dict:
    """Run one full experiment: retrieve for all queries, compute metrics.

    retrieve_fn(client, model, query_text, query_week, collection_name, top_k, rerank_strategy) -> list[str]
    Defaults to the built-in pure vector retrieve().
    """
    if retrieve_fn is None:
        retrieve_fn = retrieve

    t0 = time.perf_counter()

    all_metrics: list[dict] = []
    for q in golden_queries:
        retrieved = retrieve_fn(
            client=client, model=model,
            query_text=q.student_message,
            query_week=q.week,
            collection_name=collection_name,
            top_k=top_k,
            rerank_strategy=rerank_strategy,
        )
        metrics = compute_metrics(retrieved, q.golden_chunk_ids, top_k)
        all_metrics.append(metrics)

    # Aggregate
    keys = list(all_metrics[0].keys())
    agg = {}
    for key in keys:
        vals = [m[key] for m in all_metrics]
        agg[key] = round(float(np.mean(vals)), 4)

    latency = round(time.perf_counter() - t0, 3)
    rerank_lambda = (
        float(rerank_strategy.removeprefix("mmr_"))
        if rerank_strategy.startswith("mmr")
        else "none"
    )

    params = {
        "embedding_model": embedding_model_name,
        "top_k": top_k,
        "rerank_strategy": rerank_strategy,
        "rerank_lambda": rerank_lambda,
        "fetch_multiplier": 4 if rerank_strategy.startswith("mmr") else 1,
        "num_queries": len(golden_queries),
        "num_chunks": len(chunks),
        "collection_name": collection_name,
    }

    # Print result
    print(f"    top_k={top_k:>2}  {rerank_strategy:<10}  "
          f"recall@{top_k}={agg[f'recall@{top_k}']:.4f}  "
          f"precision@{top_k}={agg[f'precision@{top_k}']:.4f}  "
          f"f1@{top_k}={agg[f'f1@{top_k}']:.4f}  "
          f"mrr={agg['mrr']:.4f}  ndcg@{top_k}={agg[f'ndcg@{top_k}']:.4f}  "
          f"lat={latency:.1f}s")

    if mlflow_active:
        try:
            import mlflow
            mlflow.log_params(params)
            _log_mlflow_metrics(agg, latency=latency)
        except Exception as e:
            print(f"    [mlflow warning] {e}")

    return {"params": params, "metrics": agg, "latency": latency}
# ---------------------------------------------------------------------------
# 7. Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Retrieval experiment grid search")
    parser.add_argument("--quick", action="store_true",
                        help="Quick mode: 1 embedding model, fewer rerank strategies.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate setup, print configs, no actual indexing.")
    args = parser.parse_args()

    # --- MLflow setup ---
    mlflow_active = True
    try:
        import mlflow
        tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "")
        if tracking_uri:
            mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment("rag_retrieval")
        print(f"MLflow tracking: {mlflow.get_tracking_uri()}")
    except ImportError:
        print("WARNING: mlflow not installed. Metrics will not be logged.")
        mlflow_active = False
    except Exception as e:
        print(f"WARNING: MLflow setup failed: {e}")
        mlflow_active = False

    # --- Load golden queries ---
    print(f"\nLoading golden labels from {GOLDEN_LABELS_PATH} ...")
    golden_queries = load_golden_queries(GOLDEN_LABELS_PATH)
    print(f"  Loaded {len(golden_queries)} golden queries.")
    weeks = collections.Counter(q.week for q in golden_queries)
    print(f"  Week distribution: {dict(sorted(weeks.items()))}")

    # --- Config grid ---
    if args.quick:
        embeddings = [EMBEDDING_MODELS[0]]
        rerank_strategies = ["similarity", "mmr_0.7"]
    else:
        embeddings = EMBEDDING_MODELS
        rerank_strategies = RERANK_STRATEGIES

    top_ks = TOP_K_VALUES
    total_runs = len(embeddings) * len(top_ks) * len(rerank_strategies)
    print(f"\nGrid: {len(embeddings)} embedding x {len(top_ks)} top_k x "
          f"{len(rerank_strategies)} rerank = {total_runs} runs")

    if args.dry_run:
        print("\n[DRY RUN] Configs that would be tested:")
        for emb in embeddings:
            print(f"  [{emb}]")
            for k in top_ks:
                for rerank_strategy in rerank_strategies:
                    print(f"      top_k={k:<2}  rerank={rerank_strategy}")
        return

    # --- Main loop ---
    all_results: list[dict] = []
    rebuild_count = 0

    for emb_model in embeddings:
        rebuild_count += 1
        print(f"\n{'=' * 60}")
        print(f"[Rebuild {rebuild_count}/{len(embeddings)}] embedding={emb_model}")
        print(f"{'=' * 60}")

        # Load chunks
        chunks = load_harvard_cs50_chunks(RAW_DATA_PATH)
        print(f"  Loaded {len(chunks)} Harvard CS50 chunks.")

        # Build index
        safe_name = emb_model.replace("/", "_").replace("-", "_")
        collection_name = f"exp_{safe_name}"
        client, model = build_index(chunks, emb_model, collection_name)

        # Run top_k x rerank
        print(f"\n  {'top_k':<6} {'rerank':<10} "
              f"{'recall@K':<10} {'precision@K':<12} {'f1@K':<10} "
              f"{'mrr':<10} {'ndcg@K':<10} {'latency'}")
        print(f"  {'-'*6} {'-'*10} "
              f"{'-'*10} {'-'*12} {'-'*10} {'-'*10} {'-'*10} {'-'*8}")

        for top_k in top_ks:
            for rerank_strategy in rerank_strategies:
                run_name = f"{safe_name}_k{top_k}_{rerank_strategy}"
                with mlflow.start_run(run_name=run_name) if mlflow_active else _NoopContext():
                    result = run_experiment(
                        golden_queries=golden_queries,
                        chunks=chunks,
                        embedding_model_name=emb_model,
                        top_k=top_k,
                        collection_name=collection_name,
                        client=client,
                        model=model,
                        rerank_strategy=rerank_strategy,
                        mlflow_active=mlflow_active,
                    )
                    all_results.append(result)

        # Cleanup
        try:
            client.delete_collection(collection_name)
        except Exception:
            pass
        try:
            client.close()
        except Exception:
            pass

    # --- Final report ---
    if all_results:
        print(f"\n{'=' * 60}")
        print(f"Experiment complete. {len(all_results)} runs.")
        print(f"{'=' * 60}")

        # Best by recall
        best = max(all_results, key=lambda r: r["metrics"].get(
            f"recall@{r['params']['top_k']}", 0))
        print(f"\nBest by recall:")
        p = best["params"]
        m = best["metrics"]
        k = p["top_k"]
        print(f"  embedding={p['embedding_model']}  top_k={k}  "
              f"rerank={p['rerank_strategy']}")
        print(f"  recall@{k}={m[f'recall@{k}']:.4f}  "
              f"precision@{k}={m[f'precision@{k}']:.4f}  "
              f"f1@{k}={m[f'f1@{k}']:.4f}  "
              f"mrr={m['mrr']:.4f}  ndcg@{k}={m[f'ndcg@{k}']:.4f}")

        # Best by F1
        best_f1 = max(all_results, key=_f1_for_result)
        p = best_f1["params"]
        m = best_f1["metrics"]
        k = p["top_k"]
        print(f"\nBest by F1:")
        print(f"  embedding={p['embedding_model']}  top_k={k}  "
              f"rerank={p['rerank_strategy']}")
        print(f"  recall@{k}={m[f'recall@{k}']:.4f}  "
              f"precision@{k}={m[f'precision@{k}']:.4f}  "
              f"f1@{k}={m[f'f1@{k}']:.4f}  "
              f"mrr={m['mrr']:.4f}  ndcg@{k}={m[f'ndcg@{k}']:.4f}")

        if mlflow_active:
            try:
                _log_best_f1_run(best_f1, total_runs=len(all_results))
                print("  Logged best F1 summary to MLflow.")
            except Exception as e:
                print(f"  [mlflow warning] best F1 summary not logged: {e}")

        # Save results
        results_path = OUTPUT_PREFIX.rstrip("/") + "/experiment_results_cs50.json"
        _write_json(results_path, all_results)
        print(f"\nResults saved -> {results_path}")


class _NoopContext:
    """Context manager that does nothing (when mlflow is unavailable)."""
    def __enter__(self): return self
    def __exit__(self, *args): pass


if __name__ == "__main__":
    main()
