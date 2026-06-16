#!/usr/bin/env python3
"""
retrieval_experiment.py  —  Phases 2-5: Retrieval Experiment Grid Search

Grid: 3 embedding × 2 chunking × 6 retriever × 5 top_k = 180 runs
      Actual index rebuilds: 3 × 2 = 6 (top_k and retriever reuse same index)

Workflow per run:
  1. Load chunks with selected chunking strategy (slide / slide+overlap).
  2. Build Qdrant Cloud index with selected embedding model.
  3. For each retriever type × top_k value:
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
import hashlib
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
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
# 2. Chunking Strategies
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
    from qdrant_client.models import (
        Distance, PointStruct, VectorParams,
        PayloadSchemaType, FieldCondition, Filter, MatchValue,
    )

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
        vectors = model.encode(texts, show_progress_bar=False).tolist()
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


_CATEGORY_WEIGHTS = {
    "Syllabus": 2.0,
    "Strict_Rules": 0.8,
    "Pedagogical_Context": 1.0,
    "Supplementary": 0.5,
}


def retrieve(
    client: Any,
    model: Any,
    query_text: str,
    week: int,
    collection_name: str,
    retriever_type: str,
    top_k: int,
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
    query_vector = model.encode(query_text).tolist()
    retrieved: list[tuple[str, float]] = []

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
            limit=top_k if retriever_type == "vector" else top_k,
        ).points
        for h in hits:
            payload = h.payload or {}
            cat = payload.get("category", "")
            weight = _CATEGORY_WEIGHTS.get(cat, 1.0)
            retrieved.append((str(h.id), h.score * weight))

    if retriever_type in ("rules", "pedagogy+rules", "full"):
        hits = client.query_points(
            collection_name=collection_name,
            query=query_vector,
            query_filter=_rules_filter(week),
            limit=max(2, top_k // 2),
        ).points
        for h in hits:
            retrieved.append((str(h.id), h.score * 1.5))

    if retriever_type in ("syllabus", "full"):
        records, _ = client.scroll(
            collection_name=collection_name,
            scroll_filter=_week_filter(week),
            limit=1,
        )
        for r in records:
            p = r.payload or {}
            if p.get("category") == "Syllabus":
                retrieved.append((str(r.id), 2.0))

    # Dedup & sort by score descending
    seen: set[str] = set()
    unique: list[str] = []
    for cid, _ in sorted(retrieved, key=lambda x: x[1], reverse=True):
        if cid not in seen:
            seen.add(cid)
            unique.append(cid)

    return unique[:top_k]


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
        f"recall@{k}": round(recall, 4),
        f"precision@{k}": round(precision, 4),
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
    "slide",            # baseline: one slide per chunk
    "slide+overlap1",   # include adjacent slide content
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

    params = {
        "embedding_model": embedding_model_name,
        "chunking": chunking,
        "retriever_type": retriever_type,
        "top_k": top_k,
        "num_queries": len(golden_queries),
        "num_chunks": len(chunks),
        "collection_name": collection_name,
    }

    # Print result
    print(f"    top_k={top_k:>2}  {retriever_type:<18}  "
          f"recall@{top_k}={agg[f'recall@{top_k}']:.4f}  "
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
        mlflow.set_experiment("rag-retrieval-experiment")
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
        chunkings = [CHUNKING_STRATEGIES[0]]  # slide only
        retrievers = RETRIEVER_TYPES
        top_ks = TOP_K_VALUES
    else:
        embeddings = EMBEDDING_MODELS
        chunkings = CHUNKING_STRATEGIES
        retrievers = RETRIEVER_TYPES
        top_ks = TOP_K_VALUES

    total_runs = len(embeddings) * len(chunkings) * len(retrievers) * len(top_ks)
    total_rebuilds = len(embeddings) * len(chunkings)
    print(f"\nGrid: {len(embeddings)} embedding × {len(chunkings)} chunking × "
          f"{len(retrievers)} retriever × {len(top_ks)} top_k = {total_runs} runs")
    print(f"Index rebuilds: {total_rebuilds}")

    if args.dry_run:
        print("\n[DRY RUN] Configs that would be tested:")
        for emb in embeddings:
            for ch in chunkings:
                print(f"  [{emb}] × [{ch}]")
                for rt in retrievers:
                    for k in top_ks:
                        print(f"      retriever={rt:<18}  top_k={k}")
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
            chunks = load_slide_chunks(RAW_DATA_PATH, overlap=overlap)
            print(f"  Loaded {len(chunks)} chunks (overlap={overlap}).")

            # --- Build index ---
            safe_name = emb_model.replace("/", "_").replace("-", "_")
            collection_name = f"exp_{chunking}_{safe_name}"
            if args.dry_run:
                print(f"  [DRY RUN] Would create collection: {collection_name}")
                continue

            client, model = build_index(
                chunks, emb_model, collection_name,
            )

            # --- Run retrievers × top_k ---
            print(f"\n  {'top_k':<6} {'retriever':<18} {'recall@K':<10} {'mrr':<10} {'ndcg@K':<10} {'latency'}")
            print(f"  {'-'*6} {'-'*18} {'-'*10} {'-'*10} {'-'*10} {'-'*8}")

            for retriever_type in retrievers:
                for top_k in top_ks:
                    with mlflow.start_run(
                        run_name=f"{safe_name}_{chunking}_{retriever_type}_k{top_k}"
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
              f"retriever={p['retriever_type']}  top_k={k}")
        print(f"  recall@{k}={m[f'recall@{k}']:.4f}  "
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
