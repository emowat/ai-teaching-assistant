#!/usr/bin/env python3
"""
llm_eval_retrieval.py — LLM-based RAG Retrieval Evaluation

Two evaluation levels:
  1. Turn-level  — Context Recall (configured eval LLM): did retrieved chunks
                   cover the claims in the golden answer for this turn?
  2. Session-level — per-session mean/max/min recall: how does the
                   multi-turn QA perform on average? which sessions are weak?

Supports two sources:
  --source cs50   → Harvard CS50 corpus + cs50 golden set
  --source mit14  → MIT OCW corpus + mit14 golden set

Uses Qdrant collections for retrieval. If enabled, missing per-embedding
collections can be created by re-embedding payloads from the baseline Qdrant
collections.

Usage:
  export OPENAI_API_KEY="..."
  export RAG_EVAL_LLM_MODEL="gpt-4o-mini"
  export RAG_EVAL_GOLDEN_CS50_PATH="path/to/cs50_golden.json"
  export RAG_EVAL_GOLDEN_MIT14_PATH="path/to/mit14_golden.json"

  python llm_eval_retrieval.py --source cs50  --dry-run
  python llm_eval_retrieval.py --source cs50  --llm-eval
  python llm_eval_retrieval.py --source mit14 --llm-eval
  # If only use existing Qdrant collections; do not try to create/rebuild missing ones
  python llm_eval_retrieval.py --source cs50 --llm-eval --no-index-missing-collections
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import random
import re
import sys
import time
from collections import Counter
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import numpy as np

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

EXPERIMENTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXPERIMENTS_DIR.parents[1]


def load_repo_env() -> None:
    """Load repo .env so direct script runs see OPENAI_API_KEY and path config."""
    env_path = REPO_ROOT / ".env"
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=env_path)
        return
    except ImportError:
        pass

    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_repo_env()

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(EXPERIMENTS_DIR))
from retrieval_experiment import (
    S3_BUCKET,
    OUTPUT_PREFIX,
    _read_text,
    _write_json,
    _log_mlflow_metrics,
    _load_embedding_model,
)
from rag.context_assembler import build_retrieval_result
from rag.reranker import merge_and_rerank
from rag.runtime import create_qdrant_client, get_runtime_config
from rag.schemas import AssistMode, DocCategory, RetrievedDoc, SourceDomain


EVAL_EMBEDDING_MODELS = [
    # "all-MiniLM-L6-v2",
    "sentence-transformers/multi-qa-mpnet-base-dot-v1",
    # "BAAI/bge-base-en-v1.5",
    # "BAAI/bge-large-en-v1.5",
    # "Alibaba-NLP/gte-large-en-v1.5",
    # "text-embedding-3-small",
]
# "intfloat/e5-large-v2",

# EVAL_TOP_K_VALUES = [5, 8, 10, 15, 20, 30]
EVAL_TOP_K_VALUES = [8]
EVAL_BASELINE_EMBEDDING_MODEL = "sentence-transformers/multi-qa-mpnet-base-dot-v1"
EVAL_BASELINE_COURSE_COLLECTIONS = {
    "cs50": "harvard_cs50",
}
EVAL_BASELINE_GUIDELINES_COLLECTION = "cpp_guidelines"
EVAL_RERANK_STRATEGY = "similarity"
EVAL_LLM_MODEL = os.getenv("RAG_EVAL_LLM_MODEL", "gpt-4o-mini")
CPP_FEATURE_FLAGS = {"Has_Iterator", "Has_STL_Algorithm", "Has_Smart_Pointer"}
EVAL_RULES_TOP_K = 8
EVAL_RULES_THRESHOLD = 0.5
EVAL_GUIDELINES_TOP_K = 8
EVAL_GUIDELINES_THRESHOLD = 0.45
EVAL_SESSIONS_PER_WEEK = int(os.getenv("RAG_EVAL_SESSIONS_PER_WEEK", "4"))
EVAL_SAMPLE_SEED = int(os.getenv("RAG_EVAL_SAMPLE_SEED", "42"))
EVAL_INDEX_BATCH_SIZE = int(os.getenv("RAG_EVAL_INDEX_BATCH_SIZE", "8"))
EVAL_EMBED_DEVICE = os.getenv("RAG_EVAL_EMBED_DEVICE", "cpu")
EVAL_MAX_SEQ_LENGTH = int(os.getenv("RAG_EVAL_MAX_SEQ_LENGTH", "512"))
EVAL_GTE_MAX_SEQ_LENGTH = int(os.getenv("RAG_EVAL_GTE_MAX_SEQ_LENGTH", "8192"))
EVAL_MAX_TEXT_CHARS = int(os.getenv("RAG_EVAL_MAX_TEXT_CHARS", "6000"))
EVAL_GTE_MAX_TEXT_CHARS = int(os.getenv("RAG_EVAL_GTE_MAX_TEXT_CHARS", "32000"))
EVAL_RETRY_TEXT_CHARS = int(os.getenv("RAG_EVAL_RETRY_TEXT_CHARS", "1500"))
COLLECTION_FALLBACKS = {
    "cs50": ["harvard_cs50", "codingrabbit_rag_vectordb"],
    "mit14": ["mit14_course", "course_knowledge"],
    "guidelines": ["cpp_guidelines"],
}

RAG_EVAL_GOLDEN_CS50_PATH = os.getenv(
    "RAG_EVAL_GOLDEN_CS50_PATH",
    f"s3://{S3_BUCKET}/prepared/synthetic-transcripts/cs50_homework_debug_dataset.jsonl",
)
RAG_EVAL_GOLDEN_MIT14_PATH = (
    os.getenv("RAG_EVAL_GOLDEN_MIT14_PATH")
    or os.getenv(
        "RAG_EXPERIMENT_RESULTS_PATH",
        f"s3://{S3_BUCKET}/prepared/synthetic-transcripts/synthetic_c_plus_plus_dataset.jsonl",
    )
)

SOURCE_CONFIG: dict[str, dict[str, Any]] = {
    "cs50": {
        "golden_path": RAG_EVAL_GOLDEN_CS50_PATH,
    },
    "mit14": {
        "golden_path": RAG_EVAL_GOLDEN_MIT14_PATH,
    },
}


# ---------------------------------------------------------------------------
# 1. Parser — sessions → turn dicts
# ---------------------------------------------------------------------------

def _load_golden_records(path: str) -> list[dict[str, Any]]:
    """Load golden sessions from JSON or JSONL, local or S3."""
    text = _read_text(path)
    stripped = text.strip()
    if not stripped:
        return []

    if stripped.startswith("["):
        data = json.loads(stripped)
        if not isinstance(data, list):
            raise ValueError(f"Golden session JSON must be a list: {path}")
        return data

    return [
        json.loads(line)
        for line in stripped.splitlines()
        if line.strip()
    ]


def extract_features_from_text(text: str) -> dict[str, Any]:
    """Extract AST feature flags from embedded session context, if present."""
    match = re.search(r"Features:\s*(\{[^\n]*\})", text)
    if not match:
        return {}
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def should_search_cpp(
    query_text: str,
    features: dict[str, Any] | None = None,
    original_query_text: str = "",
) -> bool:
    """Search C++ reference/guidelines only for STL-ish queries or std:: usage."""
    if "std::" in query_text or "std::" in original_query_text:
        return True
    feature_flags = features or extract_features_from_text(query_text)
    return any(bool(feature_flags.get(name)) for name in CPP_FEATURE_FLAGS)


def parse_golden_sessions(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Parse the golden set into individual evaluation turns.

    Input format:
      [
        {
          "messages": [
            {"role": "system",    "content": "..."},
            {"role": "user",      "content": "..."},
            {"role": "assistant", "content": "..."},
            {"role": "user",      "content": "..."},   # follow-up
            {"role": "assistant", "content": "..."},
            ...
          ],
          "metadata": {"week": 5, "topic": "...", "trigger": "homework_paste"}
        },
        ...
      ]

    Each (user → assistant) pair becomes one turn dict.
    conversation_history for turn N = all messages before that user message.
    """
    turns: list[dict[str, Any]] = []

    for session_idx, session in enumerate(sessions):
        messages = session.get("messages", [])
        meta = session.get("metadata", {})
        week = int(meta.get("week", 0))
        topic = str(meta.get("topic", ""))
        trigger = str(meta.get("trigger", ""))
        session_features = meta.get("features") or meta.get("Features") or {}
        session_id = str(session.get("_sample_original_index", session_idx))

        history: list[dict] = []
        turn_index = 0
        i = 0

        while i < len(messages):
            msg = messages[i]
            role = msg.get("role", "")

            if role == "system":
                history.append(msg)
                i += 1

            elif role == "user":
                # Pair with the immediately following assistant message
                if (
                    i + 1 < len(messages)
                    and messages[i + 1].get("role") == "assistant"
                ):
                    assistant_msg = messages[i + 1]
                    turn_features = (
                        session_features
                        if isinstance(session_features, dict) and session_features
                        else extract_features_from_text(msg["content"])
                    )
                    turns.append({
                        "turn_id": f"{session_id}_turn_{turn_index}",
                        "session_id": session_id,
                        "turn_index": turn_index,
                        "query": msg["content"],
                        "golden_answer": assistant_msg["content"],
                        "conversation_history": list(history),
                        "contextualized_query": "",
                        "week": week,
                        "topic": topic,
                        "trigger": trigger,
                        "features": turn_features,
                    })
                    history.append(msg)
                    history.append(assistant_msg)
                    i += 2
                    turn_index += 1
                else:
                    history.append(msg)
                    i += 1
            else:
                i += 1

    return turns


def sample_sessions_by_week(
    sessions: list[dict[str, Any]],
    per_week: int = EVAL_SESSIONS_PER_WEEK,
    seed: int = EVAL_SAMPLE_SEED,
) -> list[dict[str, Any]]:
    """Sample full sessions per week, preferring distinct topic/trigger pairs."""
    if per_week <= 0:
        return sessions

    by_week: dict[int, list[tuple[int, dict[str, Any]]]] = collections.defaultdict(list)
    for idx, session in enumerate(sessions):
        meta = session.get("metadata", {})
        by_week[int(meta.get("week", 0))].append((idx, session))

    rng = random.Random(seed)
    selected: list[tuple[int, dict[str, Any]]] = []
    for week in sorted(by_week):
        candidates = list(by_week[week])
        rng.shuffle(candidates)

        chosen: list[tuple[int, dict[str, Any]]] = []
        seen_pairs: set[tuple[str, str]] = set()
        for idx, session in candidates:
            meta = session.get("metadata", {})
            pair = (str(meta.get("topic", "")), str(meta.get("trigger", "")))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            chosen.append((idx, session))
            if len(chosen) >= per_week:
                break

        if len(chosen) < per_week:
            chosen_ids = {idx for idx, _ in chosen}
            for idx, session in candidates:
                if idx in chosen_ids:
                    continue
                chosen.append((idx, session))
                if len(chosen) >= per_week:
                    break

        selected.extend(chosen)

    sampled = []
    for idx, session in sorted(selected, key=lambda item: item[0]):
        copied = dict(session)
        copied["_sample_original_index"] = idx
        sampled.append(copied)
    return sampled


# ---------------------------------------------------------------------------
# 3. Query Contextualization
# ---------------------------------------------------------------------------

def uses_max_completion_tokens(model_name: str) -> bool:
    return model_name.startswith("gpt-5")


def chat_completion(
    client: Any,
    *,
    model: str,
    max_output_tokens: int,
    messages: list[dict[str, Any]],
    response_format: dict[str, Any] | None = None,
) -> Any:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    if uses_max_completion_tokens(model):
        kwargs["max_completion_tokens"] = max_output_tokens
    else:
        kwargs["max_tokens"] = max_output_tokens
    if response_format is not None:
        kwargs["response_format"] = response_format
    return client.chat.completions.create(**kwargs)


def _contextualize_one(query: str, history: list[dict], client) -> str:
    """Rewrite a follow-up question as a self-contained standalone question."""
    non_system = [m for m in history if m.get("role") != "system"]
    recent = non_system[-4:]  # last 2 exchanges max
    if not recent:
        return query

    history_text = "\n".join(
        f"{m['role'].capitalize()}: {str(m['content'])[:400]}"
        for m in recent
    )
    resp = chat_completion(
        client,
        model=EVAL_LLM_MODEL,
        max_output_tokens=120,
        messages=[{
            "role": "user",
            "content": (
                f"Conversation so far:\n{history_text}\n\n"
                f"Follow-up question: {query}\n\n"
                "Rewrite the follow-up as a self-contained question with no pronouns "
                "that require the conversation to resolve. Output only the question."
            )
        }]
    )
    return resp.choices[0].message.content.strip()


def precompute_contextualized_queries(turns: list[dict[str, Any]], client) -> None:
    """
    In-place: fill contextualized_query for all follow-up turns that lack one.
    Run once before evaluation so retrieval uses the same rewritten follow-ups.
    """
    followups = [
        t for t in turns
        if t.get("turn_index", 0) > 0 and not t.get("contextualized_query")
    ]
    if not followups:
        return
    print(f"  Contextualizing {len(followups)} follow-up queries ...")
    for t in followups:
        t["contextualized_query"] = _contextualize_one(
            t["query"],
            t["conversation_history"],
            client,
        )
    print("  Done.")


# ---------------------------------------------------------------------------
# 4. Context Recall (LLM) — primary metric
# ---------------------------------------------------------------------------

def _extract_claims(golden_answer: str, client) -> list[str]:
    """Break a golden answer into atomic, verifiable claims."""
    resp = chat_completion(
        client,
        model=EVAL_LLM_MODEL,
        max_output_tokens=512,
        messages=[{
            "role": "user",
            "content": (
                "Break the following answer into atomic, self-contained factual claims.\n"
                "One claim per line. No bullets or numbering.\n\n"
                f"Answer: {golden_answer}\n\nClaims:"
            )
        }]
    )
    return [
        line.strip()
        for line in resp.choices[0].message.content.splitlines()
        if line.strip()
    ]


def _claims_supported_batch(claims: list[str], context: str, client) -> list[bool]:
    """Judge all claims in one call to reduce LLM request volume."""
    numbered_claims = "\n".join(
        f"{idx}. {claim}"
        for idx, claim in enumerate(claims, start=1)
    )
    resp = chat_completion(
        client,
        model=EVAL_LLM_MODEL,
        max_output_tokens=max(64, len(claims) * 12),
        response_format={"type": "json_object"},
        messages=[{
            "role": "user",
            "content": (
                f"Context:\n{context[:4000]}\n\n"
                "For each claim below, decide whether it is directly supported "
                "by the context. Return only JSON with this exact shape:\n"
                '{"supported": [true, false, ...]}\n\n'
                f"Claims:\n{numbered_claims}"
            )
        }]
    )
    content = resp.choices[0].message.content.strip()
    try:
        data = json.loads(content)
        supported = data.get("supported", [])
        if not isinstance(supported, list):
            raise ValueError("supported is not a list")
        values = [bool(item) for item in supported[:len(claims)]]
        if len(values) < len(claims):
            values.extend([False] * (len(claims) - len(values)))
        return values
    except Exception as e:
        print(f"  [llm warning] could not parse batch claim judgment: {e}")
        return [False] * len(claims)


def compute_context_recall_llm(
    retrieved_contents: list[str],
    golden_answer: str,
    client,
) -> dict[str, Any]:
    """
    score = covered_claims / total_claims

    Low  → retriever is the bottleneck (wrong chunks, embedding mismatch,
            top-K too small, chunks too coarse)
    High → retrieval is fine; look elsewhere for quality issues
    """
    if not golden_answer or not retrieved_contents:
        return {"context_recall_llm": 0.0, "n_claims": 0, "n_covered": 0}

    context = "\n\n---\n\n".join(retrieved_contents)
    claims = _extract_claims(golden_answer, client)
    if not claims:
        return {"context_recall_llm": 1.0, "n_claims": 0, "n_covered": 0}

    supported = _claims_supported_batch(claims, context, client)
    covered = sum(1 for value in supported if value)
    return {
        "context_recall_llm": round(covered / len(claims), 4),
        "n_claims":            len(claims),
        "n_covered":           covered,
    }


# ---------------------------------------------------------------------------
# 5. Two-Level Aggregation
# ---------------------------------------------------------------------------

def aggregate_sessions(turn_results: list[dict]) -> list[dict]:
    """
    Group turn-level results by session.
    Returns one summary per session, sorted by recall_mean ascending
    (worst sessions first — easy to spot where RAG fails).
    """
    by_session: dict[str, list[dict]] = collections.defaultdict(list)
    for r in turn_results:
        by_session[r["session_id"]].append(r)

    summaries = []
    for session_id, turns in by_session.items():
        recalls = [t["context_recall_llm"] for t in turns if "context_recall_llm" in t]
        if not recalls:
            continue
        first = turns[0]
        summaries.append({
            "session_id":  session_id,
            "n_turns":     len(turns),
            "recall_mean": round(float(np.mean(recalls)), 4),
            "recall_max":  round(float(np.max(recalls)), 4),   # best turn in session
            "recall_min":  round(float(np.min(recalls)), 4),   # worst turn in session
            "recall_std":  round(float(np.std(recalls)), 4),
            "week":        first.get("week", 0),
            "topic":       first.get("topic", ""),
            "trigger":     first.get("trigger", ""),
        })

    # Sorted ascending: worst sessions at index 0
    return sorted(summaries, key=lambda s: s["recall_mean"])


def aggregate_run(
    turn_results: list[dict],
    session_summaries: list[dict],
) -> dict[str, Any]:
    """Run-level metrics for one (embedding, top_k, rerank) config."""
    all_r      = [t["context_recall_llm"] for t in turn_results if "context_recall_llm" in t]
    turn0_r    = [t["context_recall_llm"] for t in turn_results
                  if t.get("turn_index") == 0 and "context_recall_llm" in t]
    followup_r = [t["context_recall_llm"] for t in turn_results
                  if t.get("turn_index", 0) > 0 and "context_recall_llm" in t]
    sess_means = [s["recall_mean"] for s in session_summaries]

    def _mean(lst: list) -> float:
        return round(float(np.mean(lst)), 4) if lst else 0.0

    return {
        # Turn-weighted mean (every turn counts equally)
        "recall_mean":          _mean(all_r),
        "recall_mean_turn0":    _mean(turn0_r),    # standalone questions only
        "recall_mean_followup": _mean(followup_r), # follow-ups only
        # Session-weighted mean (every session counts equally regardless of length)
        "session_recall_mean":         _mean(sess_means),
        "pct_sessions_above_0.7":      round(
            sum(1 for s in sess_means if s >= 0.7) / len(sess_means), 4
        ) if sess_means else 0.0,
        "n_turns_evaluated": len(all_r),
        "n_sessions":        len(session_summaries),
    }


# ---------------------------------------------------------------------------
# 6. Production-shaped retrieval assembly
# ---------------------------------------------------------------------------

def safe_model_name(model_name: str) -> str:
    return (
        model_name.replace("/", "_")
        .replace("-", "_")
        .replace(".", "_")
        .replace(":", "_")
    )


def collection_env_name(source: str, model_name: str) -> str:
    return f"QDRANT_COLLECTION_{source.upper()}_{safe_model_name(model_name).upper()}"


def is_openai_embedding_model(model: Any) -> bool:
    return model.__class__.__name__ == "OpenAIEmbeddingModel"


def to_vector_list(vectors: Any, single_input: bool) -> list[float] | list[list[float]]:
    if hasattr(vectors, "tolist"):
        converted = vectors.tolist()
    else:
        converted = [
            vector.tolist() if hasattr(vector, "tolist") else list(vector)
            for vector in vectors
        ]

    if single_input and converted and isinstance(converted[0], list):
        return converted[0]
    return converted


def clip_embedding_text(text: str, max_chars: int = EVAL_MAX_TEXT_CHARS) -> str:
    return text if len(text) <= max_chars else text[:max_chars]


def is_embedding_bounds_error(error: Exception) -> bool:
    message = str(error).lower()
    return "out of bounds" in message or "indexerror" in error.__class__.__name__.lower()


def encode_embeddings(model: Any, texts: str | list[str]) -> list[float] | list[list[float]]:
    """Encode through one conservative path for both queries and re-indexing."""
    single_input = isinstance(texts, str)
    input_texts = [texts] if single_input else list(texts)
    if not input_texts:
        return [] if single_input else []
    max_text_chars = int(getattr(model, "_rag_eval_max_text_chars", EVAL_MAX_TEXT_CHARS))
    input_texts = [clip_embedding_text(str(text), max_text_chars) for text in input_texts]
    encode_input = input_texts[0] if single_input else input_texts

    if is_openai_embedding_model(model):
        vectors = model.encode(
            encode_input,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return to_vector_list(vectors, single_input)

    encode_kwargs = {
        "batch_size": min(EVAL_INDEX_BATCH_SIZE, len(input_texts)),
        "show_progress_bar": False,
        "convert_to_numpy": True,
        "convert_to_tensor": False,
        "device": EVAL_EMBED_DEVICE,
        "normalize_embeddings": True,
    }
    try:
        vectors = model.encode(encode_input, **encode_kwargs)
    except Exception as e:
        if not is_embedding_bounds_error(e):
            raise
        if not single_input and len(input_texts) > 1:
            print("  [embed warning] batch encode failed; retrying one text at a time")
            return [encode_embeddings(model, text) for text in input_texts]

        retry_text = input_texts[0][:EVAL_RETRY_TEXT_CHARS]
        print(
            "  [embed warning] single encode hit an index error; "
            f"retrying with {len(retry_text)} chars"
        )
        vectors = model.encode(retry_text, **{**encode_kwargs, "batch_size": 1})
    return to_vector_list(vectors, single_input)


def _query_vector(model: Any, query_text: str) -> list[float]:
    vector = encode_embeddings(model, query_text)
    return vector if isinstance(vector, list) else list(vector)


def embedding_dimension(model: Any) -> int:
    if hasattr(model, "get_embedding_dimension"):
        dim = model.get_embedding_dimension()
        if dim:
            return int(dim)
    if hasattr(model, "get_sentence_embedding_dimension"):
        dim = model.get_sentence_embedding_dimension()
        if dim:
            return int(dim)
    return len(_query_vector(model, "dimension probe"))


def patch_gte_position_cache(model: Any, seq_len: int) -> None:
    """Patch Alibaba GTE long-context buffers after SentenceTransformer load."""
    try:
        import torch

        inner = model[0].auto_model
        param = next(inner.parameters())
        patched_rope = 0
        for module in inner.modules():
            if hasattr(module, "_set_cos_sin_cache"):
                module._set_cos_sin_cache(
                    seq_len=seq_len,
                    device=param.device,
                    dtype=param.dtype,
                )
                patched_rope += 1

        embeddings = getattr(inner, "embeddings", None)
        if embeddings is not None:
            embeddings.register_buffer(
                "position_ids",
                torch.arange(seq_len, device=param.device),
                persistent=False,
            )
        print(
            f"  [embed] patched GTE position cache: "
            f"seq_len={seq_len}, rope_modules={patched_rope}"
        )
    except Exception as e:
        print(f"  [embed warning] could not patch GTE position cache: {e}")


def load_eval_embedding_model(model_name: str) -> Any:
    if model_name.startswith("text-embedding-"):
        return _load_embedding_model(model_name)

    from sentence_transformers import SentenceTransformer
    is_gte = model_name == "Alibaba-NLP/gte-large-en-v1.5"
    sentence_transformer_kwargs: dict[str, Any] = {}
    if is_gte:
        from transformers import AutoConfig

        config = AutoConfig.from_pretrained(
            model_name,
            trust_remote_code=True,
        )
        print(
            f"  [embed] {model_name} max_position_embeddings: "
            f"{getattr(config, 'max_position_embeddings', 'unknown')} -> "
            f"{EVAL_GTE_MAX_SEQ_LENGTH}"
        )
        config.max_position_embeddings = EVAL_GTE_MAX_SEQ_LENGTH
        sentence_transformer_kwargs = {
            "truncate_dim": None,
            "config_kwargs": {
                "trust_remote_code": True,
                "max_position_embeddings": EVAL_GTE_MAX_SEQ_LENGTH,
            },
        }

    model = SentenceTransformer(
        model_name,
        device=EVAL_EMBED_DEVICE,
        trust_remote_code=True,
        **sentence_transformer_kwargs,
    )
    if hasattr(model, "max_seq_length"):
        model.max_seq_length = EVAL_GTE_MAX_SEQ_LENGTH if is_gte else EVAL_MAX_SEQ_LENGTH
    if is_gte:
        patch_gte_position_cache(model, EVAL_GTE_MAX_SEQ_LENGTH)
        model._rag_eval_max_text_chars = EVAL_GTE_MAX_TEXT_CHARS
    return model


def collection_vector_size(client: Any, collection_name: str) -> int | None:
    try:
        config = client.get_collection(collection_name).config.params.vectors
        if hasattr(config, "size"):
            return int(config.size)
        if isinstance(config, dict) and config:
            first_vector = next(iter(config.values()))
            return int(first_vector.size)
    except Exception as e:
        print(f"  [qdrant warning] could not inspect '{collection_name}' vectors: {e}")
    return None


def _doc_priority(category: DocCategory) -> int:
    if category in (DocCategory.SYLLABUS, DocCategory.STRICT_RULES):
        return 1
    if category == DocCategory.SUPPLEMENTARY:
        return 3
    return 2


def _to_doc(hit: Any, default_score: float = 0.0) -> RetrievedDoc:
    payload = hit.payload or {}
    category = DocCategory(payload.get("category", DocCategory.SUPPLEMENTARY.value))
    source_domain = SourceDomain(
        payload.get("source_domain", SourceDomain.HARVARD_CS50.value)
    )
    return RetrievedDoc(
        chunk_id=str(payload.get("chunk_id", hit.id)),
        content=str(payload.get("content", "")),
        category=category,
        week=int(payload.get("week", 0)),
        priority=int(payload.get("priority", _doc_priority(category))),
        score=float(getattr(hit, "score", default_score) or default_score),
        source_domain=source_domain,
        source_type=str(payload.get("source_type", "")),
    )


def _query_docs(
    client: Any,
    collection_name: str,
    query_vector: list[float],
    query_filter: Any | None,
    top_k: int,
    threshold: float | None = None,
) -> list[RetrievedDoc]:
    kwargs = {
        "collection_name": collection_name,
        "query": query_vector,
        "limit": top_k,
    }
    if query_filter is not None:
        kwargs["query_filter"] = query_filter
    if threshold is not None:
        kwargs["score_threshold"] = threshold
    hits = client.query_points(**kwargs).points
    return [_to_doc(hit) for hit in hits]


def _retrieve_syllabus(
    client: Any,
    collection_name: str,
    week: int,
) -> RetrievedDoc | None:
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    records, _ = client.scroll(
        collection_name=collection_name,
        scroll_filter=Filter(must=[
            FieldCondition(key="week", match=MatchValue(value=week)),
            FieldCondition(key="category", match=MatchValue(value=DocCategory.SYLLABUS.value)),
        ]),
        limit=1,
    )
    return _to_doc(records[0], default_score=1.0) if records else None


def _semantic_filter(source: str, week: int) -> Any:
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    if source == "cs50":
        return Filter(must=[
            FieldCondition(key="week", match=MatchValue(value=week)),
        ])

    return Filter(
        must=[FieldCondition(key="week", match=MatchValue(value=week))],
        must_not=[
            FieldCondition(key="category", match=MatchValue(value=DocCategory.SYLLABUS.value)),
        ],
    )


def _rules_filter(week: int) -> Any:
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    return Filter(must=[
        FieldCondition(key="week", match=MatchValue(value=week)),
        FieldCondition(key="category", match=MatchValue(value=DocCategory.STRICT_RULES.value)),
    ])


def retrieve_assembled_context(
    client: Any,
    model: Any,
    query_text: str,
    query_week: int,
    query_features: dict[str, Any] | None,
    original_query_text: str,
    collection_name: str,
    guidelines_collection_name: str,
    source: str,
    final_k: int,
) -> dict[str, Any]:
    """Mirror rag.pipeline retrieval lanes, then format via context_assembler."""
    vector = _query_vector(model, query_text)
    syllabus = None if source == "cs50" else _retrieve_syllabus(
        client, collection_name, query_week,
    )
    semantic = _query_docs(
        client,
        collection_name,
        vector,
        _semantic_filter(source, query_week),
        top_k=final_k,
    )
    rules = _query_docs(
        client,
        collection_name,
        vector,
        _rules_filter(query_week),
        top_k=EVAL_RULES_TOP_K,
        threshold=EVAL_RULES_THRESHOLD,
    )
    search_cpp = should_search_cpp(
        query_text,
        query_features,
        original_query_text=original_query_text,
    )
    guidelines = (
        _query_docs(
            client,
            guidelines_collection_name,
            vector,
            None,
            top_k=EVAL_GUIDELINES_TOP_K,
            threshold=EVAL_GUIDELINES_THRESHOLD,
        )
        if search_cpp
        else []
    )

    syllabus, rules, pedagogical, supplementary, guidelines = merge_and_rerank(
        syllabus=syllabus,
        semantic=semantic,
        rules=rules,
        guidelines=guidelines,
        mode=AssistMode.HOMEWORK_ASSIST,
        final_k=final_k,
        lambda_param=1.0,
    )
    result = build_retrieval_result(
        syllabus=syllabus,
        rules=rules,
        pedagogical=pedagogical,
        supplementary=supplementary,
        guidelines=guidelines,
        mode=AssistMode.HOMEWORK_ASSIST,
    )
    docs = [d for group in (
        [result.syllabus] if result.syllabus else [],
        result.strict_rules,
        result.pedagogical,
        result.supplementary,
        result.guidelines,
    ) for d in group]
    return {
        "retrieved_ids": [d.chunk_id for d in docs],
        "formatted_context": result.formatted_context,
        "n_syllabus": 1 if result.syllabus else 0,
        "n_rules": len(result.strict_rules),
        "n_pedagogical": len(result.pedagogical),
        "n_supplementary": len(result.supplementary),
        "n_guidelines": len(result.guidelines),
        "searched_cpp": search_cpp,
    }


def count_collection_points(client: Any, collection_name: str) -> int | None:
    try:
        return int(client.count(collection_name=collection_name, exact=True).count)
    except Exception as e:
        print(f"  [qdrant warning] could not count '{collection_name}': {e}")
        return None


def resolve_collection_name(
    client: Any,
    preferred: str,
    fallbacks: list[str],
    label: str,
) -> str:
    candidates = [preferred] + [name for name in fallbacks if name != preferred]
    for name in candidates:
        try:
            if client.collection_exists(name):
                if name != preferred:
                    print(f"  [qdrant] using {label} fallback collection: {name}")
                return name
        except Exception as e:
            print(f"  [qdrant warning] could not check collection '{name}': {e}")

    try:
        available = [c.name for c in client.get_collections().collections]
    except Exception:
        available = []
    raise ValueError(
        f"No existing Qdrant {label} collection found. Tried: {candidates}. "
        f"Available: {available}"
    )


def resolve_embedding_collection_name(
    client: Any,
    source: str,
    embedding_model_name: str,
    base_collection_name: str,
    report_missing: bool = True,
) -> str | None:
    if embedding_model_name == EVAL_BASELINE_EMBEDDING_MODEL:
        baseline_name = EVAL_BASELINE_COURSE_COLLECTIONS.get(source, base_collection_name)
        return resolve_collection_name(
            client,
            baseline_name,
            [base_collection_name],
            f"{source} baseline course",
        )

    safe = safe_model_name(embedding_model_name)
    env_value = os.getenv(collection_env_name(source, embedding_model_name), "")
    candidates = [
        env_value,
        f"{base_collection_name}_{safe}",
        f"{base_collection_name}__{safe}",
        f"{source}_{safe}",
        f"{source}_course_{safe}",
    ]
    candidates = [name for name in candidates if name]

    for name in candidates:
        try:
            if client.collection_exists(name):
                return name
        except Exception as e:
            print(f"  [qdrant warning] could not check collection '{name}': {e}")

    if report_missing:
        print(
            f"  [skip] {embedding_model_name}: no pre-indexed {source} collection found. "
            f"Set {collection_env_name(source, embedding_model_name)} or create one of: {candidates}"
        )
    return None


def resolve_embedding_guidelines_collection_name(
    client: Any,
    embedding_model_name: str,
    base_guidelines_collection_name: str,
    report_missing: bool = True,
) -> str | None:
    if embedding_model_name == EVAL_BASELINE_EMBEDDING_MODEL:
        return resolve_collection_name(
            client,
            EVAL_BASELINE_GUIDELINES_COLLECTION,
            [base_guidelines_collection_name],
            "baseline guidelines",
        )

    safe = safe_model_name(embedding_model_name)
    env_name = f"QDRANT_COLLECTION_GUIDELINES_{safe.upper()}"
    env_value = os.getenv(env_name, "")
    candidates = [
        env_value,
        f"{base_guidelines_collection_name}_{safe}",
        f"{base_guidelines_collection_name}__{safe}",
    ]
    candidates = [name for name in candidates if name]

    for name in candidates:
        try:
            if client.collection_exists(name):
                return name
        except Exception as e:
            print(f"  [qdrant warning] could not check collection '{name}': {e}")

    if report_missing:
        print(
            f"  [skip] {embedding_model_name}: no pre-indexed guidelines collection found. "
            f"Set {env_name} or create one of: {candidates}"
        )
    return None


def embedding_collection_name(base_collection_name: str, embedding_model_name: str) -> str:
    return f"{base_collection_name}_{safe_model_name(embedding_model_name)}"


def scroll_payloads(client: Any, collection_name: str, batch_size: int = 256):
    offset = None
    while True:
        records, offset = client.scroll(
            collection_name=collection_name,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        if not records:
            break
        for record in records:
            yield record
        if offset is None:
            break


def reembed_collection_payloads(
    client: Any,
    source_collection_name: str,
    target_collection_name: str,
    model: Any,
    batch_size: int = EVAL_INDEX_BATCH_SIZE,
) -> int:
    batch = []
    indexed = 0
    for record in scroll_payloads(client, source_collection_name):
        payload = dict(record.payload or {})
        content = str(payload.get("content", ""))
        if not content:
            continue
        batch.append((record.id, payload, content))
        if len(batch) >= batch_size:
            indexed += upsert_reembedded_batch(client, target_collection_name, model, batch)
            print(f"    indexed {indexed} points...")
            batch = []

    if batch:
        indexed += upsert_reembedded_batch(client, target_collection_name, model, batch)

    return indexed


def create_reembedded_collection(
    client: Any,
    source_collection_name: str,
    target_collection_name: str,
    model: Any,
    vector_size: int,
    batch_size: int = EVAL_INDEX_BATCH_SIZE,
) -> str:
    from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

    source_count = count_collection_points(client, source_collection_name)
    if client.collection_exists(target_collection_name):
        target_dim = collection_vector_size(client, target_collection_name)
        target_count = count_collection_points(client, target_collection_name)
        if target_dim is not None and target_dim != vector_size:
            print(
                f"  [index] recreating {target_collection_name}: "
                f"dim={target_dim}, expected={vector_size}"
            )
            client.delete_collection(target_collection_name)
        elif source_count is not None and target_count == source_count:
            print(f"  [index] using existing complete collection {target_collection_name}")
            return target_collection_name
        else:
            print(
                f"  [index] resuming/rebuilding {target_collection_name} "
                f"from {source_collection_name} ({target_count}/{source_count} points)"
            )
            indexed = reembed_collection_payloads(
                client,
                source_collection_name,
                target_collection_name,
                model,
                batch_size,
            )
            print(f"  [index] indexed {indexed} points into {target_collection_name}")
            return target_collection_name

    print(
        f"  [index] creating {target_collection_name} from {source_collection_name} "
        f"(dim={vector_size}, batch={batch_size})"
    )
    client.create_collection(
        collection_name=target_collection_name,
        vectors_config=VectorParams(size=vector_size, distance=Distance.DOT),
    )
    for field in ["week", "category", "priority", "source_domain"]:
        schema = PayloadSchemaType.INTEGER if field in ("week", "priority") else PayloadSchemaType.KEYWORD
        try:
            client.create_payload_index(
                collection_name=target_collection_name,
                field_name=field,
                field_schema=schema,
            )
        except Exception:
            pass

    indexed = reembed_collection_payloads(
        client,
        source_collection_name,
        target_collection_name,
        model,
        batch_size,
    )
    print(f"  [index] indexed {indexed} points into {target_collection_name}")
    return target_collection_name


def upsert_reembedded_batch(
    client: Any,
    collection_name: str,
    model: Any,
    batch: list[tuple[Any, dict[str, Any], str]],
) -> int:
    from qdrant_client.models import PointStruct

    vectors = encode_embeddings(model, [content for _, _, content in batch])
    if not vectors or not isinstance(vectors[0], list):
        vectors = [vectors]
    points = [
        PointStruct(id=point_id, vector=vector, payload=payload)
        for (point_id, payload, _), vector in zip(batch, vectors)
    ]
    client.upsert(collection_name=collection_name, points=points)
    return len(points)


def ensure_embedding_collections(
    client: Any,
    source: str,
    embedding_model_name: str,
    model: Any,
    model_dim: int,
    base_collection_name: str,
    base_guidelines_collection_name: str,
    create_missing: bool,
) -> tuple[str | None, str | None]:
    collection_name = resolve_embedding_collection_name(
        client,
        source,
        embedding_model_name,
        base_collection_name,
        report_missing=not create_missing,
    )
    guidelines_collection_name = resolve_embedding_guidelines_collection_name(
        client,
        embedding_model_name,
        base_guidelines_collection_name,
        report_missing=not create_missing,
    )
    if collection_name and guidelines_collection_name:
        if not create_missing or embedding_model_name == EVAL_BASELINE_EMBEDDING_MODEL:
            return collection_name, guidelines_collection_name

    if not create_missing:
        return collection_name, guidelines_collection_name

    collection_name = create_reembedded_collection(
        client=client,
        source_collection_name=base_collection_name,
        target_collection_name=collection_name or embedding_collection_name(
            base_collection_name,
            embedding_model_name,
        ),
        model=model,
        vector_size=model_dim,
    )
    guidelines_collection_name = create_reembedded_collection(
        client=client,
        source_collection_name=base_guidelines_collection_name,
        target_collection_name=guidelines_collection_name or embedding_collection_name(
            base_guidelines_collection_name,
            embedding_model_name,
        ),
        model=model,
        vector_size=model_dim,
    )
    return collection_name, guidelines_collection_name


# ---------------------------------------------------------------------------
# 7. Experiment Runner
# ---------------------------------------------------------------------------

def run_experiment(
    turns: list[dict[str, Any]],
    embedding_model_name: str,
    top_k: int,
    collection_name: str,
    guidelines_collection_name: str,
    qdrant_client: Any,
    embed_model: Any,
    rerank_strategy: str,
    source: str,
    mlflow_active: bool = True,
    llm_eval: bool = False,
    llm_client: Any = None,
) -> dict:
    t0 = time.perf_counter()
    turn_results: list[dict] = []

    for turn in turns:
        # Use the pre-computed standalone rewrite for follow-ups
        query_text = (
            turn["contextualized_query"]
            if turn["turn_index"] > 0 and turn.get("contextualized_query")
            else turn["query"]
        )

        retrieval = retrieve_assembled_context(
            client=qdrant_client,
            model=embed_model,
            query_text=query_text,
            query_week=turn["week"],
            query_features=turn.get("features"),
            original_query_text=turn["query"],
            collection_name=collection_name,
            guidelines_collection_name=guidelines_collection_name,
            source=source,
            final_k=top_k,
        )

        result: dict[str, Any] = {
            "turn_id":    turn["turn_id"],
            "session_id": turn["session_id"],
            "turn_index": turn["turn_index"],
            "query":      query_text,
            "week":       turn["week"],
            "topic":      turn["topic"],
            "trigger":    turn["trigger"],
            "retrieved_ids": retrieval["retrieved_ids"],
            "n_syllabus": retrieval["n_syllabus"],
            "n_rules": retrieval["n_rules"],
            "n_pedagogical": retrieval["n_pedagogical"],
            "n_supplementary": retrieval["n_supplementary"],
            "n_guidelines": retrieval["n_guidelines"],
            "searched_cpp": retrieval["searched_cpp"],
        }

        if llm_eval and llm_client and turn["golden_answer"]:
            result.update(compute_context_recall_llm(
                [retrieval["formatted_context"]],
                turn["golden_answer"],
                llm_client,
            ))

        turn_results.append(result)

    latency = round(time.perf_counter() - t0, 3)

    session_summaries = aggregate_sessions(turn_results) if llm_eval else []
    run_agg = aggregate_run(turn_results, session_summaries) if llm_eval else {}
    run_agg["latency_seconds"] = latency

    params = {
        "embedding_model": embedding_model_name,
        "top_k":           top_k,
        "rerank_strategy": rerank_strategy,
        "rerank_lambda": "none",
        "rules_top_k": EVAL_RULES_TOP_K,
        "rules_threshold": EVAL_RULES_THRESHOLD,
        "guidelines_top_k": EVAL_GUIDELINES_TOP_K,
        "guidelines_threshold": EVAL_GUIDELINES_THRESHOLD,
        "llm_eval":        llm_eval,
        "llm_model":       EVAL_LLM_MODEL,
        "num_turns":       len(turns),
        "num_sessions":    len(set(t["session_id"] for t in turns)),
        "collection_name": collection_name,
        "guidelines_collection_name": guidelines_collection_name,
    }

    if llm_eval and "recall_mean" in run_agg:
        print(
            f"    k={top_k:<2}  {rerank_strategy:<10}  "
            f"recall={run_agg['recall_mean']:.4f}  "
            f"turn0={run_agg['recall_mean_turn0']:.4f}  "
            f"followup={run_agg['recall_mean_followup']:.4f}  "
            f"sessions≥0.7={run_agg['pct_sessions_above_0.7']:.2%}  "
            f"lat={latency:.1f}s"
        )
    else:
        print(f"    k={top_k:<2}  {rerank_strategy:<10}  lat={latency:.1f}s")

    if mlflow_active:
        try:
            import mlflow
            mlflow.log_params(params)
            metrics = {
                k: v
                for k, v in run_agg.items()
                if isinstance(v, (int, float))
            }
            metrics.pop("latency_seconds", None)
            _log_mlflow_metrics(metrics, latency=latency)
        except Exception as e:
            print(f"    [mlflow warning] {e}")

    return {
        "params":            params,
        "run_metrics":       run_agg,
        "session_summaries": session_summaries,
        "turn_results":      turn_results,
    }


def save_results_snapshot(path: str, results: list[dict]) -> None:
    """Persist completed runs so a later crash does not lose prior results."""
    _write_json(path, [
        {
            "params":            r["params"],
            "run_metrics":       r["run_metrics"],
            "session_summaries": r["session_summaries"],
        }
        for r in results
    ])


# ---------------------------------------------------------------------------
# 7. Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source",   choices=["cs50", "mit14"], required=True)
    parser.add_argument("--dry-run",  action="store_true", help="Validate parsing only, no indexing")
    parser.add_argument("--llm-eval", action="store_true",
                        help="Enable Context Recall via the configured eval LLM. Requires OPENAI_API_KEY.")
    parser.add_argument("--no-index-missing-collections", action="store_true",
                        help="Do not create missing per-embedding Qdrant collections.")
    args = parser.parse_args()

    config = SOURCE_CONFIG[args.source]

    # MLflow
    mlflow_active = True
    try:
        import mlflow
        tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "")
        if tracking_uri:
            mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment(f"rag_retrieval_{args.source}")
        print(f"MLflow tracking: {mlflow.get_tracking_uri()}")
    except ImportError:
        print("WARNING: mlflow not installed. Metrics will not be logged.")
        mlflow_active = False
    except Exception as e:
        print(f"WARNING: MLflow setup failed: {e}")
        mlflow_active = False

    # LLM client
    llm_client = None
    if args.llm_eval:
        try:
            from openai import OpenAI
            llm_client = OpenAI()
            print(f"LLM eval enabled ({EVAL_LLM_MODEL})")
        except ImportError as e:
            raise RuntimeError("pip install openai") from e

    # Load and parse golden sessions
    golden_path = config["golden_path"]
    if not golden_path:
        raise ValueError(f"Set RAG_EVAL_GOLDEN_{args.source.upper()}_PATH")
    print(f"\nLoading golden sessions ({args.source}) from {golden_path} ...")
    sessions = _load_golden_records(golden_path)
    total_sessions = len(sessions)
    sampled_sessions = sample_sessions_by_week(sessions)
    turns = parse_golden_sessions(sampled_sessions)
    n_sessions = len(set(t["session_id"] for t in turns))
    n_followups = sum(1 for t in turns if t["turn_index"] > 0)
    sampled_weeks = Counter(
        int(session.get("metadata", {}).get("week", 0))
        for session in sampled_sessions
    )
    print(
        f"  Sampled {len(sampled_sessions)}/{total_sessions} sessions  |  "
        f"{len(turns)} turns  |  {n_followups} follow-ups"
    )
    print(f"  Sessions per week: {dict(sorted(sampled_weeks.items()))}")

    if args.dry_run:
        weeks    = Counter(t["week"]    for t in turns)
        triggers = Counter(t["trigger"] for t in turns)
        runtime = get_runtime_config()
        print(f"  Weeks:    {dict(sorted(weeks.items()))}")
        print(f"  Triggers: {dict(triggers.most_common())}")
        print("\n[DRY RUN] Config:")
        print(f"  embeddings={EVAL_EMBEDDING_MODELS}")
        print(f"  top_k_values={EVAL_TOP_K_VALUES}")
        print(f"  rerank={EVAL_RERANK_STRATEGY}")
        print(f"  llm_model={EVAL_LLM_MODEL}")
        print("  rerank_lambda=none")
        print(f"  index_missing_collections={not args.no_index_missing_collections}")
        print(f"  index_batch_size={EVAL_INDEX_BATCH_SIZE}")
        print(f"  rules_top_k={EVAL_RULES_TOP_K}  rules_threshold={EVAL_RULES_THRESHOLD}")
        print(f"  guidelines_top_k={EVAL_GUIDELINES_TOP_K}  guidelines_threshold={EVAL_GUIDELINES_THRESHOLD}")
        print(f"  course_collection={runtime.collection_for(args.source)}")
        print(f"  guidelines_collection={runtime.collection_guidelines}")
        print(
            "  baseline_collections="
            f"course={EVAL_BASELINE_COURSE_COLLECTIONS.get(args.source, runtime.collection_for(args.source))} "
            f"guidelines={EVAL_BASELINE_GUIDELINES_COLLECTION}"
        )
        return

    # Pre-compute contextualized queries once before retrieval.
    if llm_client:
        precompute_contextualized_queries(turns, llm_client)

    embeddings = EVAL_EMBEDDING_MODELS
    top_ks = EVAL_TOP_K_VALUES
    reranks = [EVAL_RERANK_STRATEGY]
    print(
        "\nConfig: "
        f"embeddings={EVAL_EMBEDDING_MODELS}  "
        f"top_k_values={EVAL_TOP_K_VALUES}  "
        f"rerank={EVAL_RERANK_STRATEGY}"
    )

    all_results: list[dict] = []
    out = OUTPUT_PREFIX.rstrip("/") + f"/eval_results_{args.source}_embeddings_v1_cppref.json"
    runtime = get_runtime_config()

    qdrant_client = create_qdrant_client(runtime)
    try:
        base_collection_name = resolve_collection_name(
            qdrant_client,
            runtime.collection_for(args.source),
            COLLECTION_FALLBACKS.get(args.source, []),
            f"{args.source} course",
        )
        base_guidelines_collection_name = resolve_collection_name(
            qdrant_client,
            runtime.collection_guidelines,
            COLLECTION_FALLBACKS["guidelines"],
            "guidelines",
        )
        print(
            f"Qdrant baseline collections: course={base_collection_name}  "
            f"guidelines={base_guidelines_collection_name}"
        )

        course_count = count_collection_points(qdrant_client, base_collection_name)
        guidelines_count = count_collection_points(qdrant_client, base_guidelines_collection_name)
        if course_count is not None:
            print(f"  Course collection points: {course_count}")
        if guidelines_count is not None:
            print(f"  Guidelines collection points: {guidelines_count}")

        for emb_model in embeddings:
            print(f"\n{'='*60}\n[Embed] {emb_model}\n{'='*60}")
            embed_model_obj = load_eval_embedding_model(emb_model)
            model_dim = embedding_dimension(embed_model_obj)
            collection_name, guidelines_collection_name = ensure_embedding_collections(
                client=qdrant_client,
                source=args.source,
                embedding_model_name=emb_model,
                model=embed_model_obj,
                model_dim=model_dim,
                base_collection_name=base_collection_name,
                base_guidelines_collection_name=base_guidelines_collection_name,
                create_missing=not args.no_index_missing_collections,
            )
            if not collection_name or not guidelines_collection_name:
                continue

            course_dim = collection_vector_size(qdrant_client, collection_name)
            guidelines_dim = collection_vector_size(qdrant_client, guidelines_collection_name)
            if course_dim is not None and course_dim != model_dim:
                print(
                    f"  [skip] {emb_model}: course collection '{collection_name}' "
                    f"dim={course_dim}, model dim={model_dim}"
                )
                continue
            if guidelines_dim is not None and guidelines_dim != model_dim:
                print(
                    f"  [skip] {emb_model}: guidelines collection '{guidelines_collection_name}' "
                    f"dim={guidelines_dim}, model dim={model_dim}"
                )
                continue

            print(
                f"  Collections: course={collection_name}  "
                f"guidelines={guidelines_collection_name}  dim={model_dim}"
            )
            safe = safe_model_name(emb_model)

            for top_k in top_ks:
                for rerank in reranks:
                    run_name = f"{args.source}_{safe}_k{top_k}_{rerank}"
                    ctx = mlflow.start_run(run_name=run_name) if mlflow_active else nullcontext()
                    with ctx:
                        result = run_experiment(
                            turns=turns,
                            embedding_model_name=emb_model,
                            top_k=top_k,
                            collection_name=collection_name,
                            guidelines_collection_name=guidelines_collection_name,
                            qdrant_client=qdrant_client,
                            embed_model=embed_model_obj,
                            rerank_strategy=rerank,
                            source=args.source,
                            mlflow_active=mlflow_active,
                            llm_eval=args.llm_eval,
                            llm_client=llm_client,
                        )
                        all_results.append(result)
                        save_results_snapshot(out, all_results)
                        print(f"    checkpoint saved -> {out}")
    finally:
        try:
            qdrant_client.close()
        except Exception:
            pass

    # Final report
    if all_results and args.llm_eval:
        print(f"\n{'='*60}\n{len(all_results)} runs complete\n{'='*60}")

        best = max(all_results, key=lambda r: r["run_metrics"].get("recall_mean", 0))
        p, m = best["params"], best["run_metrics"]
        print(f"\nBest run:")
        print(f"  embedding={p['embedding_model']}  top_k={p['top_k']}  rerank={p['rerank_strategy']}")
        print(f"  recall_mean={m['recall_mean']:.4f}  "
              f"turn0={m['recall_mean_turn0']:.4f}  "
              f"followup={m['recall_mean_followup']:.4f}  "
              f"sessions≥0.7={m['pct_sessions_above_0.7']:.2%}")

        sessions = best["session_summaries"]  # sorted ascending (worst first)
        print(f"\nBottom 5 sessions (lowest recall — where RAG fails):")
        for s in sessions[:5]:
            print(f"  {s['session_id']:<20}  mean={s['recall_mean']:.4f}  "
                  f"max={s['recall_max']:.4f}  min={s['recall_min']:.4f}  "
                  f"n={s['n_turns']}  week={s['week']}  topic={s['topic']}")

        print(f"\nTop 5 sessions (highest recall):")
        for s in sessions[-5:][::-1]:
            print(f"  {s['session_id']:<20}  mean={s['recall_mean']:.4f}  "
                  f"max={s['recall_max']:.4f}  min={s['recall_min']:.4f}  "
                  f"n={s['n_turns']}  week={s['week']}  topic={s['topic']}")

    save_results_snapshot(out, all_results)
    print(f"\nResults → {out}")


if __name__ == "__main__":
    main()
