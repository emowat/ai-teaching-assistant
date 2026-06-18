#!/usr/bin/env python3
"""
labeling_chunks.py  —  Phase 1: Golden Chunk Labeling for Retrieval Experiment

Workflow:
  1. Load synthetic dataset, sample 200 queries evenly from weeks 1..5.
  2. Load Harvard CS50 course chunks (notes + transcripts) + C++ Core Guidelines.
  3. For each query, build candidate pool via BM25 keyword retrieval.
  4. Send query + golden answer + candidate chunks to LLM (OpenAI GPT-5 mini).
  5. Golden labels = LLM output. Save to golden_labels_cs50.json.

Outputs (written to OUTPUT_PREFIX):
  eval_queries_cs50.jsonl       — sampled queries
  golden_labels_cs50.json        — golden chunk IDs (OpenAI GPT-5 mini)
  labeling_report_cs50.json      — per-query summary stats

Usage:
  python labeling_chunks.py                          # full run
  python labeling_chunks.py --dry-run                # sample + pool only, no LLM
  python labeling_chunks.py --sample-size 100        # override sample size
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sys
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import tempfile
import shutil
from urllib.parse import urlparse, parse_qs

# Optional S3 support (boto3 imported lazily in helpers)
import boto3
import botocore
from botocore import UNSIGNED
from botocore.client import Config
from botocore.exceptions import NoCredentialsError
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

# ---------------------------------------------------------------------------
# Paths (edit these if your setup differs)
# ---------------------------------------------------------------------------

# S3_BUCKET = os.getenv("LABELING_S3_BUCKET", "codingrabbit-data-dev")
# DATASET_PATH = os.getenv(
#     "LABELING_DATASET_PATH",
#     f"s3://{S3_BUCKET}/prepared/synthetic-transcripts/synthetic_c_plus_plus_dataset.jsonl",
# )
S3_BUCKET = os.getenv("LABELING_S3_BUCKET", "codingrabbit-data-dev")
DATASET_PATH = os.getenv(
    "LABELING_DATASET_PATH",
    f"s3://{S3_BUCKET}/prepared/synthetic-transcripts/cs50_homework_debug_dataset.jsonl",
)

HARVARD_NOTES_PATH = os.getenv(
    "LABELING_HARVARD_NOTES_PATH",
    f"s3://{S3_BUCKET}/raw/rag_sources/Harvard/cs50_output/notes_json/",
)
HARVARD_TRANSCRIPTS_PATH = os.getenv(
    "LABELING_HARVARD_TRANSCRIPTS_PATH",
    f"s3://{S3_BUCKET}/raw/rag_sources/Harvard/cs50_transcripts/",
)
CPP_GUIDELINES_PATH = os.getenv(
    "LABELING_CPP_GUIDELINES_PATH",
    f"s3://{S3_BUCKET}/raw/rag_sources/cppcoreguidelines/cppcoreguidelines.json",
)
MIT_RAW_DATA_PATH = os.getenv(
    "LABELING_MIT_RAW_DATA_PATH",
    f"s3://{S3_BUCKET}/raw/rag_sources/MIT/",
)
OUTPUT_PREFIX = os.getenv(
    "LABELING_OUTPUT_PREFIX",
    "/Users/lynw/Projects/ai-teaching-assistant/rag/experiments/outputs",
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Notes/transcript filename → week mapping for Harvard CS50
_LECTURE_WEEK_MAP: dict[str, int] = {
    "notes_0_scratch": 0,
    "notes_1_c": 1,
    "notes_2_arrays": 2,
    "notes_3_algorithms": 3,
    "notes_4_memory": 4,
    "notes_5_data_structures": 5,
}

# CS50 syllabus matrix (weeks 1-5)
SYLLABUS_MATRIX: dict[int, dict[str, str]] = {
    1: {"name": "C", "allowed": "printf, primitive types, conditionals, loops, main",
        "forbidden": "pointers, arrays, dynamic allocation"},
    2: {"name": "Arrays", "allowed": "arrays, strings, string.h, command-line arguments, functions",
        "forbidden": "pointers, dynamic allocation, structures"},
    3: {"name": "Algorithms", "allowed": "linear search, binary search, bubble sort, selection sort, recursion, Big O",
        "forbidden": "pointers, dynamic allocation, structures"},
    4: {"name": "Memory", "allowed": "pointers, malloc, free, valgrind, stack/heap, memory addresses",
        "forbidden": "new/delete, RAII, smart pointers, vectors"},
    5: {"name": "Data Structures", "allowed": "structs, linked lists, hash tables, tries, stacks, queues, typedef",
        "forbidden": "C++ classes, templates, inheritance"},
}

# Category classification keywords (mirrors rag/loader.py)
_STRICT_RULE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(must|always|never)\b", re.IGNORECASE),
    re.compile(r"\b(remember to|ensure that|be careful|make sure)\b", re.IGNORECASE),
    re.compile(r"\b(do not|don't|avoid|forbidden|prohibited)\b", re.IGNORECASE),
    re.compile(r"\b(critical|mandatory|required|essential)\b", re.IGNORECASE),
]

# UUID namespace for deterministic chunk IDs (mirrors rag/loader.py)
_CHUNK_NAMESPACE = uuid.UUID("58dbf568-51bb-4d4e-8cf9-c6a8a797d065")


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    """Minimal chunk representation for labeling (avoids rag package dependency)."""
    chunk_id: str
    content: str
    week: int
    category: str            # Syllabus | Strict_Rules | Pedagogical_Context | Supplementary
    source_file: str         # e.g. "01_lecture_1_compilation_pipeline.json"
    page_number: int | None
    source_domain: str       # mit_ocw_lecture | mit_ocw_syllabus | mit_ocw_assignment | cpp_core_guidelines
    retrieval_score: float | None = None  # set by BM25 / embedding for Tier 2; shown in prompt


@dataclass
class EvalQuery:
    """A single evaluation query extracted from the synthetic dataset."""
    query_id: str
    student_message: str
    golden_answer: str
    week: int
    mode: str               # "Homework Assist" | "Study Assist"
    topic: str
    trigger: str


@dataclass
class LabelingResult:
    """Per-query labeling output."""
    query_id: str
    labels_openai: list[str] = field(default_factory=list)
    golden_labels: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 1. Dataset Loading & Sampling
# ---------------------------------------------------------------------------

def trigger_to_mode(trigger: str) -> str:
    """Map dataset trigger to AssistMode."""
    return "Study Assist" if trigger == "study_assist" else "Homework Assist"


def load_dataset(path: Path) -> list[dict]:
    """Load all records from the synthetic JSONL, excluding Out-of-Scope."""
    records: list[dict] = []
    text = _read_text(path)
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if rec["metadata"].get("trigger") == "Out-of-Scope":
            continue
        records.append(rec)
    return records


def _is_s3_url(path: str | Path) -> bool:
    s = str(path)
    return s.startswith("s3://") or "console.aws.amazon.com/s3/object/" in s


def _parse_s3_url(url: str) -> tuple[str, str | None]:
    """Return (bucket, key) for s3://bucket/key or console S3 object URLs.

    For console URLs, expects query param `prefix` to contain the object key.
    """
    s = str(url)
    if s.startswith("s3://"):
        rest = s[len("s3://") :]
        parts = rest.split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else None
        return bucket, key

    p = urlparse(s)
    # console URL: /s3/object/{bucket}
    if "console.aws.amazon.com" in p.netloc and "/s3/object/" in p.path:
        bucket = p.path.split("/s3/object/", 1)[1].strip("/ ")
        qs = parse_qs(p.query)
        key = qs.get("prefix", [None])[0]
        return bucket, key

    raise ValueError(f"Unrecognized S3 URL: {url}")


def _get_s3_client() -> Any:
    if os.environ.get("S3_ANONYMOUS", "0") in ("1", "true", "True"):
        return boto3.client("s3", config=Config(signature_version=UNSIGNED))
    return boto3.client("s3")


def _read_text(path: Path | str) -> str:
    """Read text from a local path or an S3 object (s3:// or console URL)."""
    if isinstance(path, Path):
        path = str(path)

    if _is_s3_url(path):
        bucket, key = _parse_s3_url(path)
        if not key:
            raise ValueError(f"S3 object key not found in URL: {path}")
        s3 = _get_s3_client()
        try:
            obj = s3.get_object(Bucket=bucket, Key=key)
            body = obj["Body"].read()
            return body.decode("utf-8")
        except NoCredentialsError:
            raise RuntimeError(
                "AWS credentials not found. Configure credentials via environment variables (AWS_ACCESS_KEY_ID,AWS_SECRET_ACCESS_KEY), ~/.aws/credentials, or an attached IAM role."
            )
        except botocore.exceptions.ClientError as e:
            raise FileNotFoundError(f"Could not read s3://{bucket}/{key}: {e}") from e

    # fallback: local file
    with open(path, encoding="utf-8") as f:
        return f.read()


def _write_text(path: Path | str, text: str) -> None:
    """Write text to a local path or an S3 object."""
    if isinstance(path, Path):
        path = str(path)

    if _is_s3_url(path):
        bucket, key = _parse_s3_url(path)
        if not key:
            raise ValueError(f"S3 object key not found in URL: {path}")
        s3 = _get_s3_client()
        try:
            s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=text.encode("utf-8"),
                ContentType="application/json" if key.endswith(".json") else "text/plain",
            )
            return
        except NoCredentialsError:
            raise RuntimeError(
                "AWS credentials not found. Configure credentials via environment variables (AWS_ACCESS_KEY_ID,AWS_SECRET_ACCESS_KEY), ~/.aws/credentials, or an attached IAM role."
            )
        except botocore.exceptions.ClientError as e:
            raise RuntimeError(f"Could not write s3://{bucket}/{key}: {e}") from e

    local_path = Path(path)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(text, encoding="utf-8")


def _write_json(path: Path | str, data: Any) -> None:
    _write_text(path, json.dumps(data, indent=2, ensure_ascii=False))


def _output_path(filename: str) -> str:
    if _is_s3_url(OUTPUT_PREFIX):
        return f"{str(OUTPUT_PREFIX).rstrip('/')}/{filename}"
    return str(Path(OUTPUT_PREFIX) / filename)


def _ensure_local_raw_data(raw_path: Path | str) -> str:
    """If `raw_path` is an S3 prefix, download objects under that prefix to a temp dir and return its path.
    If local, return the string path unchanged.
    """
    if isinstance(raw_path, Path):
        raw_path = str(raw_path)
    if not _is_s3_url(raw_path):
        return str(raw_path)

    bucket, prefix = _parse_s3_url(raw_path)
    if prefix is None:
        prefix = ""
    # Normalize prefix
    prefix = prefix.lstrip("/")

    s3 = _get_s3_client()
    paginator = s3.get_paginator("list_objects_v2")
    tempdir = tempfile.mkdtemp(prefix="labeling_raw_")

    try:
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                rel = key[len(prefix) :].lstrip("/") if prefix and key.startswith(prefix) else key
                local_path = os.path.join(tempdir, rel)
                local_dir = os.path.dirname(local_path)
                if not os.path.exists(local_dir):
                    os.makedirs(local_dir, exist_ok=True)
                try:
                    with open(local_path, "wb") as fh:
                        s3.download_fileobj(bucket, key, fh)
                except botocore.exceptions.ClientError:
                    # skip problematic files but continue
                    continue
    except NoCredentialsError:
        # Give a clear actionable message when credentials are missing
        shutil.rmtree(tempdir, ignore_errors=True)
        raise RuntimeError(
            "AWS credentials not found. Configure credentials via environment variables (AWS_ACCESS_KEY_ID,AWS_SECRET_ACCESS_KEY), ~/.aws/credentials, or an attached IAM role. Alternatively, set S3_ANONYMOUS=1 for public buckets or run `aws s3 sync` to download data locally."
        )

    return tempdir


def extract_query(rec: dict, idx: int) -> EvalQuery:
    """Extract a single EvalQuery from a dataset record (excludes system msg)."""
    messages = rec["messages"]
    meta = rec["metadata"]

    # First user turn → student_message
    user_msg = next((m["content"] for m in messages if m["role"] == "user"), "")
    # First assistant turn → golden_answer
    asst_msg = next((m["content"] for m in messages if m["role"] == "assistant"), "")

    week = meta.get("week", 3)
    trigger = meta.get("trigger", "terminal_help")

    return EvalQuery(
        query_id=f"q{idx:04d}",
        student_message=user_msg,
        golden_answer=asst_msg,
        week=week,
        mode=trigger_to_mode(trigger),
        topic=meta.get("topic", ""),
        trigger=trigger,
    )


def sample_queries(
    records: list[dict],
    target: int = 200,
    seed: int = 42,
) -> list[EvalQuery]:
    """Evenly sample `target` queries from weeks 1..5, stratified by week."""
    random.seed(seed)

    # Group records by week 1..5
    by_week: dict[int, list[dict]] = {w: [] for w in range(1, 6)}
    for r in records:
        w = r["metadata"].get("week", 0)
        if w in by_week:
            by_week[w].append(r)

    active_weeks = sorted(w for w in by_week if by_week[w])
    if not active_weeks:
        return []

    per_week = target // len(active_weeks)  # 200 / 5 = 40
    remainder = target % len(active_weeks)

    sampled: list[EvalQuery] = []

    for i, w in enumerate(active_weeks):
        n = per_week + (1 if i < remainder else 0)
        n = min(n, len(by_week[w]))
        chosen = random.sample(by_week[w], n)
        for rec in chosen:
            sampled.append(extract_query(rec, len(sampled)))

    random.shuffle(sampled)
    return sampled


# ---------------------------------------------------------------------------
# 2. Chunk Loading (standalone — no rag package dependency)
# ---------------------------------------------------------------------------

def _resolve_week(filename: str) -> int:
    for key, week in _LECTURE_WEEK_MAP.items():
        if key in filename:
            return week
    return 1


def _stable_chunk_id(*parts: object) -> str:
    normalized = "::".join(str(part) for part in parts)
    return str(uuid.uuid5(_CHUNK_NAMESPACE, normalized))


def _classify_category(text: str, has_code: bool, source: str) -> str:
    if source == "syllabus":
        return "Syllabus"
    if source == "assignment_solution":
        return "Supplementary"
    for pat in _STRICT_RULE_PATTERNS:
        if pat.search(text):
            return "Strict_Rules"
    return "Pedagogical_Context"


def load_chunks(raw_data_path: Path | str) -> list[Chunk]:
    """Load all course chunks from raw_data/ (mirrors rag/loader.py).

    If `raw_data_path` is an S3 prefix/URL, download the objects locally first.
    """
    chunks: list[Chunk] = []
    # Ensure local copy when provided as S3 URL
    if _is_s3_url(raw_data_path):
        local_root = _ensure_local_raw_data(raw_data_path)
        raw_data_path = Path(local_root)
    else:
        raw_data_path = Path(raw_data_path)

    lecture_dir = raw_data_path / "lecture_text"
    syllabus_path = raw_data_path / "mit_ocw_output" / "syllabus.txt"

    # --- Lecture slides ---
    json_files = sorted(lecture_dir.glob("*.json"))
    json_files = [f for f in json_files if "assignment" not in f.name.lower()]

    for json_file in json_files:
        week = _resolve_week(json_file.name)
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"  WARNING: could not parse {json_file.name}")
            continue

        for slide in data:
            text = str(slide.get("text", "")).strip()
            if not text:
                continue
            has_code = bool(slide.get("has_code", False))
            section = str(slide.get("section", ""))
            page = slide.get("page")
            content = f"[{section}] {text}" if section else text
            content = content[:2000]

            category = _classify_category(text, has_code, source="lecture")
            chunk_id = _stable_chunk_id("lecture", json_file.name, page, section, text[:2000])

            chunks.append(Chunk(
                chunk_id=chunk_id,
                content=content,
                week=week,
                category=category,
                source_file=json_file.name,
                page_number=page,
                source_domain="mit_ocw_lecture",
            ))

    # --- Syllabus ---
    if syllabus_path.exists():
        raw_text = syllabus_path.read_text(encoding="utf-8")
        content_body = _strip_headers(raw_text)
        for week, info in SYLLABUS_MATRIX.items():
            chunk_id = _stable_chunk_id("syllabus", week, info["name"])
            syllabus_content = (
                f"Week: {week} - {info['name']}\n"
                f"Allowed: {info['allowed']}\n"
                f"Forbidden: {info['forbidden']}\n\n"
                f"Course Description: {content_body[:500]}"
            )
            chunks.append(Chunk(
                chunk_id=chunk_id,
                content=syllabus_content,
                week=week,
                category="Syllabus",
                source_file="syllabus.txt",
                page_number=None,
                source_domain="mit_ocw_syllabus",
            ))

    # --- Assignment solutions ---
    for json_file in sorted(lecture_dir.glob("assignment*_solution.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"  WARNING: could not parse {json_file.name}")
            continue
        week = 4  # assignments mapped to mid-course
        for slide in data:
            text = str(slide.get("text", "")).strip()
            if not text:
                continue
            content = text[:2000]
            chunk_id = _stable_chunk_id("assignment_solution", json_file.name, slide.get("page"), text[:2000])
            chunks.append(Chunk(
                chunk_id=chunk_id,
                content=content,
                week=week,
                category="Supplementary",
                source_file=json_file.name,
                page_number=slide.get("page"),
                source_domain="mit_ocw_assignment",
            ))

    return chunks


def _strip_headers(text: str) -> str:
    """Remove TITLE/BREADCRUMB/SOURCE prefix lines before the first === marker."""
    lines = text.split("\n")
    result: list[str] = []
    header_done = False
    has_marker = False
    for line in lines:
        if header_done:
            result.append(line)
        elif line.startswith("==="):
            header_done = True
            has_marker = True
    if not has_marker:
        return text.strip()
    return "\n".join(result).strip()


def load_harvard_notes(raw_data_path: Path | str) -> list[Chunk]:
    """Load Harvard CS50 notes from notes_json sections.

    If `raw_data_path` is an S3 prefix/URL, download the objects locally first.
    The S3 path already points directly to the notes_json directory.
    """
    if _is_s3_url(raw_data_path):
        # S3 prefix *is* the notes_json dir (e.g. s3://.../notes_json/)
        # Files land at <tempdir>/notes_0.json etc.
        notes_dir = Path(_ensure_local_raw_data(raw_data_path))
    else:
        # Local: traverse raw_data/ → Harvard/cs50_output/notes_json/
        notes_dir = Path(raw_data_path) / "Harvard" / "cs50_output" / "notes_json"
    if not notes_dir.exists():
        raise FileNotFoundError(f"Harvard notes_json not found: {notes_dir}")

    chunks: list[Chunk] = []

    for json_file in sorted(notes_dir.glob("notes_*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"  WARNING: could not parse {json_file.name}")
            continue

        week = data.get("week", 0)
        title = data.get("title", "")

        for i, section in enumerate(data.get("sections", [])):
            heading = str(section.get("heading", "")).strip()
            text = str(section.get("text", "")).strip()
            has_code = bool(section.get("has_code", False))

            if not text and not heading:
                continue

            # Chunk content: heading as context prefix + text
            content = f"[{heading}] {text}" if heading and text else (heading or text)
            content = content[:2000]

            # Simple category classification (same heuristic as MIT)
            category = _classify_category(text, has_code, source="lecture")

            chunk_id = _stable_chunk_id("harvard_cs50", json_file.name, i, heading, text[:2000])

            chunks.append(Chunk(
                chunk_id=chunk_id,
                content=content,
                week=week,
                category=category,
                source_file=f"notes_{week}_{title}",
                page_number=i,  # section index acts as page
                source_domain="harvard_cs50",
            ))

    return chunks


def load_harvard_transcripts(raw_data_path: Path | str) -> list[Chunk]:
    """Load Harvard CS50 lecture transcripts (paragraph-level chunks)."""
    if _is_s3_url(raw_data_path):
        transcripts_dir = Path(_ensure_local_raw_data(raw_data_path))
    else:
        transcripts_dir = Path(raw_data_path) / "Harvard" / "cs50_transcripts"

    if not transcripts_dir.exists():
        print(f"  WARNING: Transcripts dir not found: {transcripts_dir}")
        return []

    chunks: list[Chunk] = []
    for json_file in sorted(transcripts_dir.glob("lecture*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue

        week = int(data.get("week", 0))
        title = str(data.get("title", ""))
        for para in data.get("paragraphs", []):
            text = str(para.get("text", "")).strip()
            if len(text) < 50:
                continue
            idx = para.get("index", 0)

            chunk_id = _stable_chunk_id("harvard_cs50_transcript", json_file.name, str(idx), text[:500])
            chunks.append(Chunk(
                chunk_id=chunk_id,
                content=text[:3000],
                week=week,
                category="Pedagogical_Context",
                source_file=json_file.name,
                page_number=None,
                source_domain="harvard_cs50",
            ))

    print(f"  Harvard transcripts: {len(chunks)} chunks")
    return chunks


def load_cpp_guidelines(guidelines_path: Path | str) -> list[Chunk]:
    """Load C++ Core Guidelines as week-0 reference chunks."""
    try:
        raw_text = _read_text(guidelines_path)
    except FileNotFoundError:
        print(f"  WARNING: Guidelines not found: {guidelines_path}")
        return []

    data = json.loads(raw_text)
    chunks: list[Chunk] = []
    for entry in data:
        if entry.get("level") != 3:
            continue
        title = str(entry.get("title", ""))
        rule_number = str(entry.get("rule_number", ""))
        section = str(entry.get("section", ""))
        reason = str(entry.get("reason", ""))
        examples = entry.get("examples", [])
        enforcement = str(entry.get("enforcement", ""))

        parts = [f"Section: {section}", f"Rule: {title}"]
        if reason:
            parts.append(f"Reason: {reason}")
        for ex in examples:
            code = ex.get("code", "")
            if code:
                parts.append(f"Example:\n{code}")
        if enforcement:
            parts.append(f"Enforcement: {enforcement}")
        content = "\n\n".join(parts)[:3000]

        chunk_id = _stable_chunk_id("cpp_guideline", rule_number or title, content[:500])
        chunks.append(Chunk(
            chunk_id=chunk_id,
            content=content,
            week=0,
            category="Guideline",
            source_file="cppcoreguidelines.json",
            page_number=None,
            source_domain="cpp_core_guidelines",
        ))

    print(f"  C++ Core Guidelines: {len(chunks)} chunks (week 0)")
    return chunks


# ---------------------------------------------------------------------------
# 3. Candidate Pool Construction
# ---------------------------------------------------------------------------


def _simple_bm25(
    query_text: str,
    corpus_chunks: list[Chunk],
    top_k: int,
) -> list[Chunk]:
    """
    Minimal BM25-like keyword ranking (TF * IDF).
    Uses scikit-learn style TF-IDF if available, otherwise falls back to
    a simple term-overlap scorer.
    """
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        corpus_texts = [c.content for c in corpus_chunks]
        vectorizer = TfidfVectorizer(stop_words="english", max_features=5000)
        tfidf_matrix = vectorizer.fit_transform(corpus_texts)
        query_vec = vectorizer.transform([query_text])
        scores = cosine_similarity(query_vec, tfidf_matrix).flatten()

        ranked = sorted(
            zip(corpus_chunks, scores), key=lambda x: x[1], reverse=True
        )
        result = []
        for c, s in ranked[:top_k]:
            c.retrieval_score = float(s)
            result.append(c)
        return result
    except ImportError:
        pass

    # Fallback: simple term-overlap BM25 approximation
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text.lower())

    query_tokens = set(_tokenize(query_text))
    if not query_tokens:
        return corpus_chunks[:top_k]

    # Simple IDF: log(N / df)
    N = len(corpus_chunks)
    df: dict[str, int] = defaultdict(int)
    tokenized_corpus: list[set[str]] = []
    for c in corpus_chunks:
        tokens = set(_tokenize(c.content))
        tokenized_corpus.append(tokens)
        for t in tokens:
            df[t] += 1

    idf = {t: math.log((N - df[t] + 0.5) / (df[t] + 0.5) + 1) for t in df}

    scored: list[tuple[Chunk, float]] = []
    for i, c in enumerate(corpus_chunks):
        doc_tokens = tokenized_corpus[i]
        score = sum(idf.get(t, 0) for t in (query_tokens & doc_tokens))
        # BM25-like len normalization (simple)
        dl = len(doc_tokens) or 1
        score = score / (1 + 0.5 * (dl / 50))  # k1=1.0, b=0.5, avgdl~50 words
        scored.append((c, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    result = []
    for c, s in scored[:top_k]:
        c.retrieval_score = float(s)
        result.append(c)
    return result


def build_candidate_pool(
    query: EvalQuery,
    all_chunks: list[Chunk],
) -> list[Chunk]:
    """Build BM25 candidate pool with week-priority."""

    retrieval_query = _build_retrieval_query(query)
    is_ast = _is_ast_query(query.student_message, query.golden_answer)

    if is_ast:
        # AST queries: guidelines (week 0) get heavy weight for rule lookup
        guidelines = [c for c in all_chunks if c.week == 0]
        others = [c for c in all_chunks if 0 < c.week <= query.week]
        pool = _simple_bm25(retrieval_query, guidelines, top_k=40)
        seen = {c.chunk_id for c in pool}
        for c in _simple_bm25(retrieval_query, others, top_k=20):
            if c.chunk_id not in seen:
                pool.append(c)
    else:
        # Non-AST: equal split between current week and history
        current = [c for c in all_chunks if c.week == query.week]
        history = [c for c in all_chunks if c.week < query.week]
        pool = _simple_bm25(retrieval_query, current, top_k=30)
        seen = {c.chunk_id for c in pool}
        for c in _simple_bm25(retrieval_query, history, top_k=30):
            if c.chunk_id not in seen:
                pool.append(c)

    return pool

def _build_retrieval_query(query: EvalQuery) -> str:
    """
    Build retrieval query for candidate generation.

    Uses:
      - student question
      - golden answer

    Avoids:
      - raw code
      - AST metadata
      - terminal context
    """

    m = re.search(
        r"\[Student_Question\](.*)",
        query.student_message,
        flags=re.DOTALL,
    )

    if m:
        student_question = m.group(1).strip()
    else:
        student_question = query.student_message[:500]

    golden = query.golden_answer[:1500]

    return f"""
Question:
{student_question}

Expected Answer:
{golden}
"""

# ---------------------------------------------------------------------------
# 4. LLM Labeling
# ---------------------------------------------------------------------------

def _build_labeling_prompt(query: EvalQuery, candidate_chunks: list[Chunk]) -> str:
    """Build the LLM prompt for chunk relevance labeling."""
    chunks_text: list[str] = []
    # Sort by week descending so current week appears first
    sorted_chunks = sorted(candidate_chunks, key=lambda c: c.week, reverse=True)

    current_week_header = False
    prev_week: int | None = None
    for c in sorted_chunks:
        if c.week != prev_week:
            if c.week >= query.week:
                label = f"Week {c.week} (Current — all shown)" if not current_week_header else f"Week {c.week}"
                if c.week == query.week:
                    current_week_header = True
            else:
                label = f"Week {c.week} (Prerequisite)"
            chunks_text.append(f"\n### {label}")
            prev_week = c.week

        # Truncate content for prompt
        content_preview = c.content[:300]

        # Show retrieval score for Tier 2 (prerequisite) chunks; omit for Tier 1
        if c.week < query.week and c.retrieval_score is not None:
            chunks_text.append(
                f"[{c.chunk_id}] [sim={c.retrieval_score:.3f}] "
                f"[Week {c.week}, {c.category}] {content_preview}"
            )
        else:
            chunks_text.append(
                f"[{c.chunk_id}] [Week {c.week}, {c.category}] {content_preview}"
            )

    chunks_block = "\n".join(chunks_text)

    # Truncate golden answer to keep prompt size manageable
    golden_preview = query.golden_answer[:800]

    # Base prompt header (shared by both modes)
    header = f"""You are labeling which course documents are relevant to a specific student question. Your job is to identify which document chunks contain information that directly helps answer the question.

## Student Question
{query.student_message}

## Expected TA Response (Golden Answer)
{golden_preview}

## Candidate Document Chunks
The candidate pool contains structured lecture notes, spoken lecture
transcripts, and C++ Core Guidelines (week 0, global reference).
Chunks are ordered with current-week content first, then prerequisites.

{chunks_block}

## Task
Return a JSON array of chunk IDs that contain information directly useful for answering this student's question.

Guidelines:
- Include chunks that provide syllabus rules relevant to the question.
- Include chunks whose content is directly referenced or implied by the golden answer.
- Include chunks that provide necessary conceptual background.
- Prefer recall over precision. When uncertain, INCLUDE the chunk.
- The golden answer is a hint about what information matters — use it to guide your selection, but don't select chunks just because they share keywords with the golden answer."""

    # AST-specific guideline (appended only for AST-related queries)
    ast_guidelines = """You are extracting C++ concepts for retrieval. Given:
    - source code
    - AST metadata
    - runtime output
    Rewrite this question using the accompanying AST data as a query for C++ reference material."""

    prompt = header
    if _is_ast_query(query.student_message, query.golden_answer):
        prompt += "\n" + ast_guidelines

    prompt += ("\n\nOutput ONLY a JSON array with no other text. "
               "Do not explain your reasoning. "
               "Format: [\"chunk_id_1\", \"chunk_id_2\", ...]")
    return prompt

def _is_ast_query(
    student_message: str,
    golden_answer: str,
) -> bool:

    if "AST_Metadata:" not in student_message:
        return False

    text = golden_answer.lower()

    signals = [
        "type mismatch",
        "pointer",
        "reference",
        "dereference",
        "array",
        "loop",
        "parameter",
        "argument",
        "variable",
        "scope",
        "control flow",
        "return type",
        "function call",
        "nullptr",
        "memory",
    ]

    return any(x in text for x in signals)

def _call_openai(prompt: str, api_key: str | None = None, model: str = "gpt-5-mini") -> list[str]:
    """Call OpenAI chat API for labeling. Returns list of chunk IDs."""
    if api_key is None:
        api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set. Set env var or pass api_key.")

    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("openai package not installed. Run: pip install openai")

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        seed=42,
        max_completion_tokens=2000,
    )
    raw = response.choices[0].message.content or ""
    result = _parse_label_output(raw)
    if not result:
        print(f"  WARNING: could not parse LLM output: {raw[:200]}")
    return result


def _parse_label_output(raw: str) -> list[str]:
    """Extract a JSON array of chunk IDs from LLM output. Robust to markdown and
    temperature=1 verbosity (explanatory text before/after the array)."""
    raw = raw.strip()
    # Strip markdown code fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    # Try parsing the whole string as JSON
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except json.JSONDecodeError:
        pass

    # Extract any JSON array embedded in the text (handles "Here are: [\"id1\"]")
    array_match = re.search(r"\[.*?\]", raw, re.DOTALL)
    if array_match:
        try:
            parsed = json.loads(array_match.group(0))
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            pass

    # Fallback: extract UUIDs
    ids = re.findall(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", raw)
    if ids:
        return ids
    return []


# ---------------------------------------------------------------------------
# Main Orchestration
# ---------------------------------------------------------------------------

def _print_distribution(queries: list[EvalQuery], max_week: int = 8) -> None:
    """Print week × mode distribution table."""
    dist: dict[tuple[int, str], int] = defaultdict(int)
    for q in queries:
        dist[(q.week, q.mode)] += 1
    min_w = min(q.week for q in queries) if queries else 0
    print("\n  Query Distribution:")
    print(f"  {'Week':<6} {'Homework':>10} {'Study':>10} {'Total':>8}")
    for w in range(min_w, max_week + 1):
        hw = dist.get((w, "Homework Assist"), 0)
        st = dist.get((w, "Study Assist"), 0)
        print(f"  {w:<6} {hw:>10} {st:>10} {hw+st:>8}")
    hw_total = sum(v for (_, m), v in dist.items() if m == "Homework Assist")
    st_total = sum(v for (_, m), v in dist.items() if m == "Study Assist")
    print(f"  {'Total':<6} {hw_total:>10} {st_total:>10} {hw_total+st_total:>8}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Golden chunk labeling for retrieval experiment")
    parser.add_argument("--dry-run", action="store_true",
                        help="Sample queries + build pools, but skip LLM calls.")
    parser.add_argument("--course", type=str, default="harvard",
                        choices=["mit", "harvard"],
                        help="Course to label: mit or harvard (default: harvard).")
    parser.add_argument("--sample-size", type=int, default=200,
                        help="Target number of queries to sample (default: 200).")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed (default: 42).")
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    if not _is_s3_url(OUTPUT_PREFIX):
        Path(OUTPUT_PREFIX).mkdir(parents=True, exist_ok=True)
    random.seed(args.seed)

    print("=" * 60)
    print("Phase 1: Golden Chunk Labeling")
    print("=" * 60)
    print(f"Dataset:       {DATASET_PATH}")
    print(f"Output prefix: {OUTPUT_PREFIX}")

    course = args.course.lower()

    # ------------------------------------------------------------------
    # Step 1: Load dataset & sample queries
    # ------------------------------------------------------------------
    print("\n[1/4] Loading dataset & sampling queries ...")
    records = load_dataset(DATASET_PATH)
    # Filter to course-relevant weeks
    if course == "harvard":
        records = [r for r in records if r["metadata"].get("week", 0) <= 5]
        print(f"  Filtered to weeks 0-5: {len(records)} records (Harvard).")
    print(f"  Loaded {len(records)} records (excl. Out-of-Scope).")

    # Per-week availability (diagnostic)
    week_counts = Counter(r["metadata"].get("week", 0) for r in records)
    print(f"  Records per week: {dict(sorted(week_counts.items()))}")

    queries = sample_queries(records, target=args.sample_size, seed=args.seed)
    print(f"  Sampled {len(queries)} queries.")
    _print_distribution(queries, max_week=5 if course == "harvard" else 8)

    # Save eval queries
    eval_path = _output_path("eval_queries_cs50.jsonl")
    eval_lines = []
    for q in queries:
        eval_lines.append(json.dumps({
            "query_id": q.query_id,
            "student_message": q.student_message,
            "golden_answer": q.golden_answer,
            "week": q.week,
            "mode": q.mode,
            "topic": q.topic,
            "trigger": q.trigger,
        }, ensure_ascii=False))
    _write_text(eval_path, "\n".join(eval_lines) + "\n")
    print(f"  Saved eval queries → {eval_path}")

    # ------------------------------------------------------------------
    # Step 2: Load chunks
    # ------------------------------------------------------------------
    print(f"\n[2/4] Loading {course.upper()} course chunks ...")
    if course == "harvard":
        print(f"  Harvard notes:       {HARVARD_NOTES_PATH}")
        print(f"  Harvard transcripts: {HARVARD_TRANSCRIPTS_PATH}")
        all_chunks = load_harvard_notes(HARVARD_NOTES_PATH)
        all_chunks.extend(load_harvard_transcripts(HARVARD_TRANSCRIPTS_PATH))
    else:
        print(f"  MIT raw data: {MIT_RAW_DATA_PATH}")
        all_chunks = load_chunks(MIT_RAW_DATA_PATH)
    # Always include C++ Core Guidelines (week 0, course-agnostic)
    print(f"  C++ Guidelines: {CPP_GUIDELINES_PATH}")
    all_chunks.extend(load_cpp_guidelines(CPP_GUIDELINES_PATH))

    if len(all_chunks) == 0:
        print("  WARNING: No chunks loaded from any source (notes, transcripts, guidelines).")
    print(f"  Loaded {len(all_chunks)} chunks.")

    # Print chunk distribution
    week_dist = Counter(c.week for c in all_chunks)
    cat_dist = Counter(c.category for c in all_chunks)
    src_dist = Counter(c.source_domain for c in all_chunks)
    print(f"  Week distribution: {dict(sorted(week_dist.items()))}")
    print(f"  Category distribution: {dict(cat_dist)}")
    print(f"  Source type distribution: {dict(src_dist)}")

    # ------------------------------------------------------------------
    # Step 3: Build candidate pools (BM25-only, notes + transcripts)
    # ------------------------------------------------------------------
    print("\n[3/4] Building candidate pools (BM25 only) ...")

    # Build candidate pool per query
    query_pools: dict[str, list[Chunk]] = {}
    total_pool_sizes: list[int] = []
    for i, q in enumerate(queries):
        pool = build_candidate_pool(q, all_chunks)
        query_pools[q.query_id] = pool
        total_pool_sizes.append(len(pool))
        if (i + 1) % 20 == 0:
            print(f"  Built pools for {i + 1}/{len(queries)} queries ...")

    avg_pool = sum(total_pool_sizes) / len(total_pool_sizes)
    print(f"  Pool sizes: min={min(total_pool_sizes)}, max={max(total_pool_sizes)}, "
          f"avg={avg_pool:.1f}")

    if args.dry_run:
        print("\n  [DRY RUN] Skipping LLM labeling. Pools built successfully.")
        # Save pool summary
        pool_summary = {
            q.query_id: {
                "week": q.week,
                "mode": q.mode,
                "pool_size": len(query_pools[q.query_id]),
            }
            for q in queries
        }
        pool_summary_path = _output_path("pool_summary_cs50.json")
        _write_json(pool_summary_path, pool_summary)
        print(f"  Pool summary saved → {pool_summary_path}")
        return

    # ------------------------------------------------------------------
    # Step 4: LLM Labeling (OpenAI GPT-5 mini only)
    # ------------------------------------------------------------------
    print("\n[4/4] LLM Labeling (OpenAI GPT-5 mini) ...")
    results: list[LabelingResult] = []

    openai_key = os.getenv("OPENAI_API_KEY", "")
    if not openai_key:
        print("  ERROR: OPENAI_API_KEY not set. Set env var or pass api_key.")
        sys.exit(1)

    for i, q in enumerate(queries):
        result = LabelingResult(query_id=q.query_id)
        pool = query_pools[q.query_id]
        prompt = _build_labeling_prompt(q, pool)

        print(f"\n  [{i + 1}/{len(queries)}] Query: {q.query_id} "
              f"(Week {q.week}, {q.mode}, pool={len(pool)})")

        # OpenAI GPT-5 mini
        try:
            result.labels_openai = _call_openai(prompt, api_key=openai_key)
            print(f"    OpenAI → {len(result.labels_openai)} chunks")
        except Exception as e:
            print(f"    OpenAI ERROR: {e}")
            result.labels_openai = []

        # Golden labels = OpenAI output directly
        result.golden_labels = result.labels_openai

        results.append(result)

        # Rate limiting
        if i < len(queries) - 1:
            time.sleep(1.0)

    # ------------------------------------------------------------------
    # Save outputs
    # ------------------------------------------------------------------
    print("\n--- Saving Outputs ---")

    # Golden labels (OpenAI GPT-5 mini)
    golden_out = {r.query_id: r.golden_labels for r in results}
    golden_path = _output_path("golden_labels_cs50.json")
    _write_json(golden_path, golden_out)
    print(f"  Golden labels → {golden_path}")

    # Summary report
    report = []
    for r in results:
        total_golden = len(r.golden_labels)
        total_pool = len(query_pools.get(r.query_id, []))
        report.append({
            "query_id": r.query_id,
            "labels_openai": len(r.labels_openai),
            "golden_labels": total_golden,
            "pool_size": total_pool,
            "golden_ratio": round(total_golden / total_pool, 3) if total_pool else 0,
        })
    report_path = _output_path("labeling_report_cs50.json")
    _write_json(report_path, report)
    print(f"  Labeling report → {report_path}")

    # Summary
    total_labeled = sum(len(r.golden_labels) for r in results)
    avg_labels = total_labeled / len(results) if results else 0
    print(f"\n{'=' * 60}")
    print(f"Labeling complete.")
    print(f"  Total queries:     {len(queries)}")
    print(f"  Total labels:      {total_labeled}")
    print(f"  Avg labels/query:  {avg_labels:.1f}")
    print(f"  Output prefix:     {OUTPUT_PREFIX}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
