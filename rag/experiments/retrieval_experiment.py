#!/usr/bin/env python3
"""
retrieval_experiment.py  —  Phases 2-5: Retrieval Experiment Grid Search

Grid: embeddings × corpus × retriever × top_k × rerank × mode × weights ×
      rule_threshold. Index rebuilds only depend on embedding × corpus.

Workflow per run:
  1. Load Harvard CS50 chunks with the same loader used by golden labeling.
  2. Build Qdrant Cloud index with selected embedding model.
  3. For each retrieval/rerank config:
     a. Retrieve top_k chunks per query.
     b. Compute Recall@K, MRR, NDCG, Precision@K vs golden labels.
     c. Log to MLflow.

Usage:
  export QDRANT_URL="https://..." QDRANT_API_KEY="..."
  export MLFLOW_TRACKING_URI="https://..."  # or "file:///tmp/mlruns" for local
  python retrieval_experiment.py                     # full grid
  python retrieval_experiment.py --quick             # 1 model × 1 chunking only
  python retrieval_experiment.py --dry-run           # validate setup, no index builds
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

import numpy as np

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

GOLDEN_LABELS_PATH = Path(__file__).resolve().parent / "outputs" / "golden_labels_filtered.json"
RAW_DATA_PATH = Path("/Users/lynw/Projects/ai-teaching-assistant/raw_data")
OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"

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


def load_golden_queries(path: Path) -> list[GoldenQuery]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    queries: list[GoldenQuery] = []
    for qid, entry in data.items():
        queries.append(GoldenQuery(
            query_id=qid,
            student_message=entry["student_message"],
            week=entry["week"],
            mode=entry["mode"],
            golden_chunk_ids=set(entry["found_chunks"].keys()),
        ))
    return queries


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


def load_harvard_cs50_chunks(raw_data_path: Path, overlap: int = 0) -> list[ExpChunk]:
    """
    Load the Harvard CS50 note chunks used by the labeling pipeline.

    `golden_labels_filtered.json` was generated from labeling_chunks.py's
    Harvard loader, so the retrieval experiment must index those same chunk IDs
    for recall/precision metrics to be meaningful. The overlap argument is
    accepted only to keep the experiment loop's loader call uniform.
    """
    experiments_dir = Path(__file__).resolve().parent
    if str(experiments_dir) not in sys.path:
        sys.path.insert(0, str(experiments_dir))

    from labeling_chunks import load_harvard_notes

    if overlap:
        print("  [chunking] overlap ignored for Harvard CS50 note chunks.")

    chunks = []
    for c in load_harvard_notes(raw_data_path):
        chunks.append(ExpChunk(
            chunk_id=c.chunk_id,
            content=c.content,
            week=c.week,
            category=c.category,
            source_domain=c.source_domain,
        ))
    return chunks


# ---------------------------------------------------------------------------
# 3. Qdrant Indexing
# ---------------------------------------------------------------------------

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
    from sentence_transformers import SentenceTransformer
    from qdrant_client.models import Distance, PointStruct, VectorParams, PayloadSchemaType

    print(f"  Loading embedding model: {embedding_model_name} ...")
    model = SentenceTransformer(embedding_model_name)
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

    # Build points
    points: list[PointStruct] = []
    batch_size = 128
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start:start + batch_size]
        texts = [c.content for c in batch]
        vectors = model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).tolist()
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

    # Upsert
    for start in range(0, len(points), 100):
        client.upsert(collection_name=collection_name, points=points[start:start+100])

    # Payload indexes for filtered search
    for field in ["week", "category"]:
        schema = PayloadSchemaType.INTEGER if field == "week" else PayloadSchemaType.KEYWORD
        try:
            client.create_payload_index(collection_name=collection_name, field_name=field, field_schema=schema)
        except Exception:
            pass

    print(f"  Indexed {len(points)} points.")
    return client, model


# ---------------------------------------------------------------------------
# 4. Retrieval
# ---------------------------------------------------------------------------

def _week_filter(week: int) -> Any:
    from qdrant_client.models import FieldCondition, Filter, MatchValue
    return Filter(must=[FieldCondition(key="week", match=MatchValue(value=week))])


def _category_filter(week: int, category: str) -> Any:
    from qdrant_client.models import FieldCondition, Filter, MatchValue
    return Filter(must=[
        FieldCondition(key="week", match=MatchValue(value=week)),
        FieldCondition(key="category", match=MatchValue(value=category)),
    ])


def _semantic_filter(week: int) -> Any:
    from qdrant_client.models import FieldCondition, Filter, MatchValue
    return Filter(
        must=[FieldCondition(key="week", match=MatchValue(value=week))],
        must_not=[FieldCondition(key="category", match=MatchValue(value="Syllabus"))],
    )


def _rules_filter(week: int) -> Any:
    from qdrant_client.models import FieldCondition, Filter, MatchValue
    return Filter(must=[
        FieldCondition(key="week", match=MatchValue(value=week)),
        FieldCondition(key="category", match=MatchValue(value="Strict_Rules")),
    ])


def _pedagogy_filter(week: int) -> Any:
    """Filter: exclude Syllabus and Strict_Rules (Pedagogical_Context + Supplementary only)."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue
    return Filter(
        must=[FieldCondition(key="week", match=MatchValue(value=week))],
        must_not=[
            FieldCondition(key="category", match=MatchValue(value="Syllabus")),
            FieldCondition(key="category", match=MatchValue(value="Strict_Rules")),
        ],
    )


_BASE_WEIGHTS = {
    "Syllabus": 1.5,
    "Strict_Rules": 1.5,
    "Pedagogical_Context": 1.0,
    "Guideline": 0.8,
    "Supplementary": 0.5,
}

_MODE_WEIGHTS = {
    "homework": {
        "Syllabus": 1.5,
        "Strict_Rules": 1.8,
        "Pedagogical_Context": 0.9,
        "Guideline": 0.3,
        "Supplementary": 0.3,
    },
    "study": {
        "Syllabus": 1.5,
        "Strict_Rules": 1.0,
        "Pedagogical_Context": 1.5,
        "Guideline": 1.2,
        "Supplementary": 0.8,
    },
}

_WEIGHT_PROFILE_OVERRIDES = {
    "production": {},
    "neutral": {
        "Syllabus": 1.0,
        "Strict_Rules": 1.0,
        "Pedagogical_Context": 1.0,
        "Guideline": 1.0,
        "Supplementary": 1.0,
    },
    "rules_heavy": {
        "Syllabus": 1.5,
        "Strict_Rules": 2.0,
        "Pedagogical_Context": 0.8,
        "Guideline": 0.5,
        "Supplementary": 0.4,
    },
    "pedagogy_heavy": {
        "Syllabus": 1.2,
        "Strict_Rules": 0.8,
        "Pedagogical_Context": 1.8,
        "Guideline": 1.0,
        "Supplementary": 0.8,
    },
}


def _category_weights(mode: str, weight_profile: str) -> dict[str, float]:
    if weight_profile == "production":
        return _MODE_WEIGHTS.get(mode, _BASE_WEIGHTS)
    return _WEIGHT_PROFILE_OVERRIDES.get(weight_profile, _BASE_WEIGHTS)


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
    week: int,
    collection_name: str,
    retriever_type: str,
    top_k: int,
    rerank_strategy: str,
    mode: str,
    weight_profile: str,
    rule_threshold: float | None,
) -> list[str]:
    """
    Run retrieval. Returns list of chunk IDs (ordered by score descending).

    Retriever types (6 category-based lanes):
      vector          — pure vector, no filter, all categories
      pedagogy        — vector, filtered to Pedagogical_Context + Supplementary
      rules           — vector, filtered to Strict_Rules only
      syllabus        — exact lookup, Syllabus only
      pedagogy+rules  — pedagogy + rules combined (no syllabus)
      full            — all three lanes (production config)
    """
    query_vector = model.encode(query_text, normalize_embeddings=True).tolist()
    fetch_k = top_k * 4 if rerank_strategy.startswith("mmr") else top_k
    weights = _category_weights(mode, weight_profile)
    retrieved: list[tuple[str, float, str]] = []

    # --- Individual category lanes ---

    if retriever_type in ("vector", "pedagogy", "pedagogy+rules", "full"):
        if retriever_type == "vector":
            filt = None  # no filter at all
        else:
            filt = _pedagogy_filter(week)  # pedagogy + supplementary only
        hits = client.query_points(
            collection_name=collection_name,
            query=query_vector,
            query_filter=filt,
            limit=fetch_k,
        ).points
        for h in hits:
            payload = h.payload or {}
            cat = payload.get("category", "")
            weight = weights.get(cat, 1.0)
            retrieved.append((str(h.id), h.score * weight, str(payload.get("content", ""))))

    if retriever_type in ("rules", "pedagogy+rules", "full"):
        query_kwargs = {
            "collection_name": collection_name,
            "query": query_vector,
            "query_filter": _rules_filter(week),
            "limit": max(2, fetch_k // 2),
        }
        if rule_threshold is not None:
            query_kwargs["score_threshold"] = rule_threshold
        hits = client.query_points(**query_kwargs).points
        for h in hits:
            payload = h.payload or {}
            cat = payload.get("category", "Strict_Rules")
            weight = weights.get(cat, 1.0)
            retrieved.append((str(h.id), h.score * weight, str(payload.get("content", ""))))

    if retriever_type in ("syllabus", "full"):
        records, _ = client.scroll(
            collection_name=collection_name,
            scroll_filter=_category_filter(week, "Syllabus"),
            limit=1,
        )
        for r in records:
            payload = r.payload or {}
            weight = weights.get("Syllabus", 1.0)
            retrieved.append((str(r.id), 1.0 * weight, str(payload.get("content", ""))))

    # Dedup & sort by score descending
    seen: set[str] = set()
    unique: list[tuple[str, float, str]] = []
    for cid, score, content in sorted(retrieved, key=lambda x: x[1], reverse=True):
        if cid not in seen:
            seen.add(cid)
            unique.append((cid, score, content))

    if rerank_strategy.startswith("mmr"):
        lambda_param = float(rerank_strategy.removeprefix("mmr_"))
        unique = _mmr_rerank(unique, top_k=top_k, lambda_param=lambda_param)

    return [cid for cid, _, _ in unique[:top_k]]


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
    "BAAI/bge-base-en-v1.5",
]

CHUNKING_STRATEGIES = [
    "harvard_notes",    # same chunk IDs used by golden_labels_filtered.json
]

RETRIEVER_TYPES = [
    # Individual category lanes — which categories are retrievable?
    "vector",           # pure vector, no filter — baseline
    "pedagogy",         # Pedagogical_Context + Supplementary only
    "rules",            # Strict_Rules only
    "syllabus",         # Syllabus exact lookup only
    # Category lane combinations
    "pedagogy+rules",   # pedagogy + rules (no syllabus)
    "full",             # all three lanes (production config)
]

TOP_K_VALUES = [3, 5, 8, 10, 15]

RERANK_STRATEGIES = [
    "similarity",
    "mmr_0.5",
    "mmr_0.7",
    "mmr_0.9",
]

MODES = [
    "homework",
    "study",
]

WEIGHT_PROFILES = [
    "production",
    "neutral",
    "rules_heavy",
    "pedagogy_heavy",
]

RULE_THRESHOLDS = [
    None,
    0.45,
    0.55,
    0.65,
]

_RULE_RETRIEVERS = {"rules", "pedagogy+rules", "full"}


def _rule_thresholds_for(retriever_type: str) -> list[float | None]:
    if retriever_type in _RULE_RETRIEVERS:
        return RULE_THRESHOLDS
    return [None]


def run_experiment(
    golden_queries: list[GoldenQuery],
    chunks: list[ExpChunk],
    embedding_model_name: str,
    chunking: str,
    retriever_type: str,
    top_k: int,
    collection_name: str,
    client: Any,
    model: Any,
    rerank_strategy: str,
    mode: str,
    weight_profile: str,
    rule_threshold: float | None,
    mlflow_active: bool = True,
) -> dict:
    """Run one full experiment: retrieve for all queries, compute metrics."""
    t0 = time.perf_counter()

    all_metrics: list[dict] = []
    for q in golden_queries:
        retrieved = retrieve(
            client=client, model=model,
            query_text=q.student_message,
            week=q.week,
            collection_name=collection_name,
            retriever_type=retriever_type,
            top_k=top_k,
            rerank_strategy=rerank_strategy,
            mode=mode,
            weight_profile=weight_profile,
            rule_threshold=rule_threshold,
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
    weights = _category_weights(mode, weight_profile)
    rerank_lambda = (
        float(rerank_strategy.removeprefix("mmr_"))
        if rerank_strategy.startswith("mmr")
        else "none"
    )

    params = {
        "embedding_model": embedding_model_name,
        "chunking": chunking,
        "retriever_type": retriever_type,
        "top_k": top_k,
        "rerank_strategy": rerank_strategy,
        "rerank_lambda": rerank_lambda,
        "fetch_multiplier": 4 if rerank_strategy.startswith("mmr") else 1,
        "mode": mode,
        "weight_profile": weight_profile,
        "weight_syllabus": weights.get("Syllabus", 1.0),
        "weight_strict_rules": weights.get("Strict_Rules", 1.0),
        "weight_pedagogical_context": weights.get("Pedagogical_Context", 1.0),
        "weight_guideline": weights.get("Guideline", 1.0),
        "weight_supplementary": weights.get("Supplementary", 1.0),
        "rule_threshold": "none" if rule_threshold is None else rule_threshold,
        "normalize_embeddings": True,
        "num_queries": len(golden_queries),
        "num_chunks": len(chunks),
        "collection_name": collection_name,
    }

    # Print result
    threshold_label = "none" if rule_threshold is None else f"{rule_threshold:.2f}"
    print(f"    top_k={top_k:>2}  {retriever_type:<15}  {rerank_strategy:<10}  "
          f"{mode:<8}  {weight_profile:<14}  rule_t={threshold_label:<4}  "
          f"recall@{top_k}={agg[f'recall@{top_k}']:.4f}  "
          f"precision@{top_k}={agg[f'precision@{top_k}']:.4f}  "
          f"f1@{top_k}={agg[f'f1@{top_k}']:.4f}  "
          f"mrr={agg['mrr']:.4f}  ndcg@{top_k}={agg[f'ndcg@{top_k}']:.4f}  "
          f"lat={latency:.1f}s")

    if mlflow_active:
        try:
            import mlflow
            mlflow.log_params(params)
            mlflow.log_metrics(agg)
            mlflow.log_metric("latency_seconds", latency)
        except Exception as e:
            print(f"    [mlflow warning] {e}")

    return {"params": params, "metrics": agg, "latency": latency}


# ---------------------------------------------------------------------------
# 7. Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Retrieval experiment grid search")
    parser.add_argument("--quick", action="store_true",
                        help="Quick mode: 1 model × 1 chunking only.")
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
        embeddings = [EMBEDDING_MODELS[1]]  # mpnet only
        chunkings = [CHUNKING_STRATEGIES[0]]  # Harvard CS50 notes only
        retrievers = RETRIEVER_TYPES
        top_ks = TOP_K_VALUES
        rerank_strategies = ["similarity", "mmr_0.7"]
        modes = MODES
        weight_profiles = ["production"]
    else:
        embeddings = EMBEDDING_MODELS
        chunkings = CHUNKING_STRATEGIES
        retrievers = RETRIEVER_TYPES
        top_ks = TOP_K_VALUES
        rerank_strategies = RERANK_STRATEGIES
        modes = MODES
        weight_profiles = WEIGHT_PROFILES

    retriever_run_count = sum(
        len(_rule_thresholds_for(rt))
        for rt in retrievers
    )
    total_runs = (
        len(embeddings) * len(chunkings) * len(top_ks) *
        len(rerank_strategies) * len(modes) * len(weight_profiles) *
        retriever_run_count
    )
    total_rebuilds = len(embeddings) * len(chunkings)
    print(f"\nGrid: {len(embeddings)} embedding × {len(chunkings)} chunking × "
          f"{len(retrievers)} retriever × {len(top_ks)} top_k × "
          f"{len(rerank_strategies)} rerank × {len(modes)} mode × "
          f"{len(weight_profiles)} weight profile × rule thresholds = {total_runs} runs")
    print(f"Index rebuilds: {total_rebuilds}")

    if args.dry_run:
        print("\n[DRY RUN] Configs that would be tested:")
        for emb in embeddings:
            for ch in chunkings:
                print(f"  [{emb}] × [{ch}]")
                for rt in retrievers:
                    for k in top_ks:
                        for rerank_strategy in rerank_strategies:
                            for mode in modes:
                                for weight_profile in weight_profiles:
                                    for rule_threshold in _rule_thresholds_for(rt):
                                        threshold_label = (
                                            "none" if rule_threshold is None
                                            else f"{rule_threshold:.2f}"
                                        )
                                        print(
                                            f"      retriever={rt:<15} top_k={k:<2} "
                                            f"rerank={rerank_strategy:<10} mode={mode:<8} "
                                            f"weights={weight_profile:<14} rule_t={threshold_label}"
                                        )
        return

    # --- Main loop ---
    all_results: list[dict] = []
    rebuild_count = 0

    for emb_model in embeddings:
        for chunking in chunkings:
            rebuild_count += 1
            print(f"\n{'=' * 60}")
            print(f"[Rebuild {rebuild_count}/{total_rebuilds}] "
                  f"embedding={emb_model}  chunking={chunking}")
            print(f"{'=' * 60}")

            # --- Load chunks ---
            overlap = 1 if "overlap1" in chunking else 0
            chunks = load_harvard_cs50_chunks(RAW_DATA_PATH, overlap=overlap)
            print(f"  Loaded {len(chunks)} Harvard CS50 chunks.")

            # --- Build index ---
            safe_name = emb_model.replace("/", "_").replace("-", "_")
            collection_name = f"exp_{chunking}_{safe_name}"
            if args.dry_run:
                print(f"  [DRY RUN] Would create collection: {collection_name}")
                continue

            client, model = build_index(
                chunks, emb_model, collection_name,
            )

            # --- Run retrievers × top_k × rerank/mode/weight/threshold ---
            print(
                f"\n  {'top_k':<6} {'retriever':<15} {'rerank':<10} "
                f"{'mode':<8} {'weights':<14} {'rule_t':<11} "
                f"{'recall@K':<10} {'precision@K':<12} {'f1@K':<10} "
                f"{'mrr':<10} {'ndcg@K':<10} {'latency'}"
            )
            print(
                f"  {'-'*6} {'-'*15} {'-'*10} {'-'*8} {'-'*14} {'-'*11} "
                f"{'-'*10} {'-'*12} {'-'*10} {'-'*10} {'-'*10} {'-'*8}"
            )

            for retriever_type in retrievers:
                for top_k in top_ks:
                    for rerank_strategy in rerank_strategies:
                        for mode in modes:
                            for weight_profile in weight_profiles:
                                for rule_threshold in _rule_thresholds_for(retriever_type):
                                    threshold_name = (
                                        "none" if rule_threshold is None
                                        else str(rule_threshold).replace(".", "p")
                                    )
                                    run_name = (
                                        f"{safe_name}_{chunking}_{retriever_type}_k{top_k}_"
                                        f"{rerank_strategy}_{mode}_{weight_profile}_rt{threshold_name}"
                                    )
                                    with mlflow.start_run(
                                        run_name=run_name
                                    ) if mlflow_active else _NoopContext():
                                        result = run_experiment(
                                            golden_queries=golden_queries,
                                            chunks=chunks,
                                            embedding_model_name=emb_model,
                                            chunking=chunking,
                                            retriever_type=retriever_type,
                                            top_k=top_k,
                                            collection_name=collection_name,
                                            client=client,
                                            model=model,
                                            rerank_strategy=rerank_strategy,
                                            mode=mode,
                                            weight_profile=weight_profile,
                                            rule_threshold=rule_threshold,
                                            mlflow_active=mlflow_active,
                                        )
                                        all_results.append(result)

            # --- Cleanup ---
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
        print(f"  embedding={p['embedding_model']}  chunking={p['chunking']}  "
              f"retriever={p['retriever_type']}  top_k={k}  "
              f"rerank={p['rerank_strategy']}  mode={p['mode']}  "
              f"weights={p['weight_profile']}  rule_threshold={p['rule_threshold']}")
        print(f"  recall@{k}={m[f'recall@{k}']:.4f}  "
              f"precision@{k}={m[f'precision@{k}']:.4f}  "
              f"f1@{k}={m[f'f1@{k}']:.4f}  "
              f"mrr={m['mrr']:.4f}  ndcg@{k}={m[f'ndcg@{k}']:.4f}")

        # Save results
        results_path = OUTPUT_DIR / "experiment_results.json"
        with open(results_path, "w", encoding="utf-8") as f:
            json.dump(all_results, f, indent=2, default=str)
        print(f"\nResults saved → {results_path}")


class _NoopContext:
    """Context manager that does nothing (when mlflow is unavailable)."""
    def __enter__(self): return self
    def __exit__(self, *args): pass


if __name__ == "__main__":
    main()
