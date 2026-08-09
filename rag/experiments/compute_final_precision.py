#!/usr/bin/env python3
"""Final context precision for always-cpp / g0.60 / g0.72 on the mit14 golden set.

Precision = of the final post-rerank chunks that reach the LLM, how many are
relevant (LLM-judged, item1 rubric). Two metrics per config:
  * flat  — relevant / total final chunks (micro), plus per-turn mean (macro)
  * MAP   — rank-aware context precision over the order chunks are presented

Phases (run retrieval first, eyeball counts, then judge):
  python compute_final_precision.py            # retrieval only -> artifact + counts
  python compute_final_precision.py --judge     # judge cached artifact + report

All three configs run through the SAME conditional retrieval path for parity;
always-cpp is reproduced by forcing the C++ lane on (trigger='study_assist'),
i.e. guidelines are always fetched, at its native 0.60 floor.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import mean

import llm_eval_retrieval_mit14_claude as H
import item1_semantic_threshold_pr as J
from rag.schemas import DocCategory

EXPERIMENTS_DIR = Path(__file__).resolve().parent
ARTIFACT = EXPERIMENTS_DIR / "logs" / "final_precision_retrieval.json"
CACHE = EXPERIMENTS_DIR / "logs" / "final_precision_cache.json"
SOURCE = "mit14"
EMB_MODEL = "BAAI/bge-large-en-v1.5"

# Fixed run params — the sweep's shipping config.
FINAL_K = 5
RULES_TOP_K = 3
GUIDELINES_TOP_K = 5
RERANK = "similarity"
WEIGHTS = H.WEIGHT_PRESETS["guideline_supplementary_equal"]

# (name, thresholds preset, force_cpp)
CONFIGS = [
    ("g0.60", H.THRESHOLD_PRESETS["g0.60_r0.60_s0.50"], False),
    ("g0.72", H.THRESHOLD_PRESETS["g0.72_r0.60_s0.50"], False),
    ("always-cpp", H.THRESHOLD_PRESETS["g0.60_r0.60_s0.50"], True),
]

# Judge highest-priority configs first so a mid-run usage limit still leaves the
# most-wanted results complete. Checkpoint after every CKPT_EVERY sessions.
JUDGE_ORDER = ["g0.72", "always-cpp", "g0.60"]
CKPT_EVERY = 5
BATCH_SIZE = 15  # chunks judged per LLM call (amortizes the ~40k CLI overhead)

_SEC = re.compile(
    r"\[Code_Context\](.*?)(?=\[Terminal_Context\]|\[Student_Question\]|\Z)"
    r".*?\[Terminal_Context\](.*?)(?=\[Student_Question\]|\Z)"
    r".*?\[Student_Question\](.*)\Z",
    re.S,
)


def user_turn_triple(query: str) -> str:
    """Mirror item1's get_user_turn: code + terminal + question only, no context."""
    m = _SEC.search(query)
    if not m:
        q = query.split("[Student_Question]")[-1].strip()
        return f"[Code_Context]\n\n[Terminal_Context]\n\n[Student_Question]\n{q}"
    code, term, ques = (s.strip() for s in m.groups())
    # Drop any retrieved-context block that trails the question.
    ques = re.split(r"\n\[[A-Z]", ques)[0].strip()
    return (f"[Code_Context]\n{code}\n[Terminal_Context]\n{term}\n"
            f"[Student_Question]\n{ques}")


def _install_embed_cache():
    """Memoize query embedding so all three configs reuse one vector per query.

    The guideline floor / cpp toggle never change the embedding, so without this
    each turn is embedded 3x. Cuts embeddings from 3*N to N distinct queries.
    """
    cache: dict[str, list[float]] = {}
    orig = H._query_vector

    def cached(model, query_text):
        if query_text not in cache:
            cache[query_text] = orig(model, query_text)
        return cache[query_text]

    H._query_vector = cached


def setup():
    """Client + BAAI collections + embedding model, mirroring the harness main()."""
    H.load_repo_env()
    _install_embed_cache()
    runtime = H.get_runtime_config()
    client = H.create_qdrant_client(runtime)
    course = H.resolve_collection_name(
        client, runtime.collection_for(SOURCE),
        H.COLLECTION_FALLBACKS.get(SOURCE, []), f"{SOURCE} course")
    guidelines = H.resolve_collection_name(
        client, runtime.collection_guidelines,
        H.COLLECTION_FALLBACKS["guidelines"], "guidelines")
    model = H.load_eval_embedding_model(EMB_MODEL)
    dim = H.embedding_dimension(model)
    course, guidelines = H.ensure_embedding_collections(
        client=client, source=SOURCE, embedding_model_name=EMB_MODEL,
        model=model, model_dim=dim,
        base_collection_name=course, base_guidelines_collection_name=guidelines,
        create_missing=False)
    print(f"collections: course={course}  guidelines={guidelines}  dim={dim}")
    return client, model, course, guidelines


def run_retrieval():
    client, model, course, guidelines = setup()
    records = H._load_golden_records(H.RAG_EVAL_GOLDEN_MIT14_PATH)
    # Match the sweep exactly: sample 4 sessions/week (seed 42) before parsing.
    sampled = H.sample_sessions_by_week(records)
    turns = H.parse_golden_sessions(sampled)
    print(f"sessions: {len(sampled)}  turns: {len(turns)}", flush=True)

    out = []
    for i, turn in enumerate(turns):
        if i % 10 == 0:
            print(f"  turn {i}/{len(turns)}", flush=True)
        query_text = (turn["contextualized_query"]
                      if turn["turn_index"] > 0 and turn.get("contextualized_query")
                      else turn["query"])
        row = {"turn_index_global": i, "turn_id": turn["turn_id"],
               "session_id": turn["session_id"], "turn_index": turn["turn_index"],
               "trigger": turn["trigger"], "week": turn["week"],
               "topic": turn["topic"],
               "user_turn": user_turn_triple(turn["query"]), "configs": {}}
        for name, thresholds, force_cpp in CONFIGS:
            r = H.retrieve_assembled_context(
                client=client, model=model, query_text=query_text,
                query_week=turn["week"], query_features=turn.get("features"),
                original_query_text=turn["query"], collection_name=course,
                guidelines_collection_name=guidelines, source=SOURCE,
                final_k=FINAL_K, rerank_strategy=RERANK, category_weights=WEIGHTS,
                rules_top_k=RULES_TOP_K, guidelines_top_k=GUIDELINES_TOP_K,
                thresholds=thresholds,
                trigger="study_assist" if force_cpp else turn.get("trigger", ""))
            row["configs"][name] = {"retrieved_ids": r["retrieved_ids"],
                                    "searched_cpp": r["searched_cpp"]}
        out.append(row)

    ARTIFACT.write_text(json.dumps(out, indent=2))
    _resolve_and_attach_content(client, course, guidelines, out)
    print_retrieval_summary(out)
    client.close()


def _resolve_and_attach_content(client, course, guidelines, rows):
    """Look up chunk content+label by id (turn-independent) from both collections."""
    ids = {cid for row in rows for cfg in row["configs"].values()
           for cid in cfg["retrieved_ids"]}
    content = {}
    for coll in (course, guidelines):
        missing = [i for i in ids if i not in content]
        if not missing:
            break
        for pt in client.retrieve(collection_name=coll, ids=missing,
                                  with_payload=True):
            p = pt.payload or {}
            content[str(pt.id)] = {"content": p.get("content", ""),
                                   "label": p.get("category", "")}
    (EXPERIMENTS_DIR / "logs" / "final_precision_content.json").write_text(
        json.dumps(content, indent=2))
    print(f"resolved content for {len(content)}/{len(ids)} unique chunks")


def print_retrieval_summary(rows):
    print("\n=== retrieval summary ===")
    pairs = set()
    for name, _, _ in CONFIGS:
        tot = sum(len(r["configs"][name]["retrieved_ids"]) for r in rows)
        cpp = sum(1 for r in rows if r["configs"][name]["searched_cpp"])
        per_turn = tot / len(rows)
        print(f"  {name:11s} chunks={tot:4d}  ({per_turn:.1f}/turn)  cpp_on={cpp}/{len(rows)}")
        for r in rows:
            for cid in r["configs"][name]["retrieved_ids"]:
                pairs.add((r["turn_index_global"], cid))
    cached = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    todo = sum(1 for (t, c) in pairs if f"{t}:{c}" not in cached)
    print(f"\n  unique (turn,chunk) pairs to judge = {len(pairs)}  "
          f"(cached={len(pairs)-todo}, new judge calls={todo})")


# --------------------------------------------------------------------------
# Judge phase
# --------------------------------------------------------------------------

_BATCH_PROMPT = """You are grading retrieval relevance for a C/C++ teaching \
assistant, like the production context-precision metric.

STUDENT TURN (code + terminal + question):
{user_turn}

Below are {n} retrieved chunks. For EACH chunk decide whether it could help a \
tutor answer THIS student's question or debug their code.
- relevant (true): syllabus guidance, lecture material, API/reference info, or an \
example on-topic for the student's specific question or bug that could plausibly \
contribute to answering it.
- not relevant (false): off-topic / unrelated, or pure course logistics with no \
bearing on the technical question.
Judge topical usefulness, not whether it is the single best chunk.

CHUNKS:
{chunks}

Respond with JSON only, a list of exactly {n} booleans in chunk order:
{{"verdicts": [true, false, ...]}}"""


def judge_relevance_batch(user_turn: str, contents: list[str]) -> list[bool]:
    """Judge N chunks against one student turn in a single LLM call."""
    import subprocess
    numbered = "\n\n".join(f"[{i+1}] {c}" for i, c in enumerate(contents))
    prompt = _BATCH_PROMPT.format(user_turn=user_turn, n=len(contents),
                                  chunks=numbered)
    cmd = ["claude", "-p", "--model", J.LLM_MODEL, "--output-format", "json",
           "--allowed-tools", ""]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                       timeout=J.CLAUDE_CLI_TIMEOUT_SECONDS)
    if r.returncode != 0:
        raise RuntimeError(f"claude CLI failed: {r.stderr[:200]}")
    data = json.loads(r.stdout)
    if data.get("is_error"):
        raise RuntimeError(f"claude CLI error: {str(data)[:200]}")
    m = re.search(r'"verdicts"\s*:\s*\[([^\]]*)\]', data["result"])
    if not m:
        raise ValueError(f"no verdicts array in: {data['result'][:150]!r}")
    verdicts = [t.lower() == "true"
                for t in re.findall(r"true|false", m.group(1), re.IGNORECASE)]
    if len(verdicts) != len(contents):
        raise ValueError(
            f"expected {len(contents)} verdicts, got {len(verdicts)}")
    return verdicts


def _sessions_in_order(rows):
    order, seen = [], set()
    by_session = defaultdict(list)
    for r in rows:
        sid = r["session_id"]
        if sid not in seen:
            seen.add(sid)
            order.append(sid)
        by_session[sid].append(r)
    return order, by_session


def _judge_window(name, sids, by_session, content, cache):
    """Judge all uncached chunks for `name` over the given sessions, batched."""
    batches = []  # (turn_index_global, chunk_ids, contents)
    for sid in sids:
        for r in by_session[sid]:
            tig = r["turn_index_global"]
            ids = [c for c in r["configs"][name]["retrieved_ids"]
                   if f"{tig}:{c}" not in cache and content.get(c, {}).get("content")]
            for i in range(0, len(ids), BATCH_SIZE):
                grp = ids[i:i + BATCH_SIZE]
                batches.append((tig, grp, [content[c]["content"] for c in grp]))
    if not batches:
        return 0
    with ThreadPoolExecutor(max_workers=J.MAX_CONCURRENCY) as pool:
        # user_turn is per turn; look it up once per batch via the first row.
        ut_by_tig = {r["turn_index_global"]: r["user_turn"]
                     for sid in sids for r in by_session[sid]}
        fut = {pool.submit(judge_relevance_batch, ut_by_tig[tig], conts): (tig, ids)
               for (tig, ids, conts) in batches}
        for f in as_completed(fut):
            tig, ids = fut[f]
            try:
                for cid, v in zip(ids, f.result()):
                    cache[f"{tig}:{cid}"] = bool(v)
            except Exception as e:
                print(f"    WARN batch turn {tig} failed: {str(e)[:80]}", flush=True)
    return len(batches)


def run_judge():
    run_ts = time.strftime("%Y%m%d_%H%M%S")
    checkpoint_path = str(
        EXPERIMENTS_DIR / "logs" / f"checkpoint_mit14_final_precision_{run_ts}.json")
    snapshot_path = str(
        EXPERIMENTS_DIR / "logs" / f"eval_results_mit14_final_precision_{run_ts}.json")

    rows = json.loads(ARTIFACT.read_text())
    content = json.loads(
        (EXPERIMENTS_DIR / "logs" / "final_precision_content.json").read_text())
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    cfg = {name: (thr, fc) for name, thr, fc in CONFIGS}
    order, by_session = _sessions_in_order(rows)

    t0 = time.perf_counter()
    calls = 0
    runs = []
    for name in JUDGE_ORDER:
        print(f"\n=== judging {name} ({len(order)} sessions) ===", flush=True)
        for start in range(0, len(order), CKPT_EVERY):
            window = order[start:start + CKPT_EVERY]
            calls += _judge_window(name, window, by_session, content, cache)
            CACHE.write_text(json.dumps(cache, indent=2))
            _write_checkpoint(checkpoint_path, rows, cache)
            print(f"  {name}: {min(start+CKPT_EVERY, len(order))}/{len(order)} "
                  f"sessions  ({calls} calls, {time.perf_counter()-t0:.0f}s)",
                  flush=True)
        thr, fc = cfg[name]
        runs.append(build_run(name, thr, fc, rows, cache, time.perf_counter() - t0))
        save_snapshot(snapshot_path, runs)
        print(f"  [config complete] {name} -> snapshot ({len(runs)} configs)",
              flush=True)

    print(f"\ncheckpoint -> {checkpoint_path}")
    print(f"results    -> {snapshot_path}")
    report(runs)


def _ap(rels: list[bool]) -> float:
    """Average precision over the presented order; 0 if no relevant chunk."""
    n_rel = sum(rels)
    if not n_rel:
        return 0.0
    hits = 0.0
    s = 0.0
    for i, r in enumerate(rels, start=1):
        if r:
            hits += 1
            s += hits / i
    return s / n_rel


def build_turn_results(name, rows, cache):
    """Per-turn precision records, mirroring the harness turn_results shape."""
    out = []
    for row in rows:
        ids = row["configs"][name]["retrieved_ids"]
        rels = [bool(cache.get(f"{row['turn_index_global']}:{c}")) for c in ids]
        n = len(rels)
        n_rel = sum(rels)
        out.append({
            "config": name,
            "turn_id": row["turn_id"],
            "session_id": row["session_id"],
            "turn_index": row["turn_index"],
            "week": row["week"],
            "topic": row["topic"],
            "trigger": row["trigger"],
            "searched_cpp": row["configs"][name]["searched_cpp"],
            "retrieved_ids": ids,
            "chunk_relevant": rels,
            "n_chunks": n,
            "n_relevant": n_rel,
            "precision": round(n_rel / n, 4) if n else 0.0,
            "average_precision": round(_ap(rels), 4),
        })
    return out


def aggregate_precision_sessions(turn_results):
    """One summary per session, sorted worst-first (mirrors aggregate_sessions)."""
    by = defaultdict(list)
    for t in turn_results:
        by[t["session_id"]].append(t)
    summaries = []
    for sid, ts in by.items():
        precs = [t["precision"] for t in ts]
        aps = [t["average_precision"] for t in ts]
        first = ts[0]
        summaries.append({
            "session_id": sid,
            "n_turns": len(ts),
            "precision_mean": round(mean(precs), 4),
            "precision_max": round(max(precs), 4),
            "precision_min": round(min(precs), 4),
            "map": round(mean(aps), 4),
            "week": first["week"],
            "topic": first["topic"],
            "trigger": first["trigger"],
            "n_turns_cpp_on": sum(1 for t in ts if t["searched_cpp"]),
        })
    return sorted(summaries, key=lambda s: s["precision_mean"])


def aggregate_precision_run(turn_results, sessions, latency):
    rel = sum(t["n_relevant"] for t in turn_results)
    tot = sum(t["n_chunks"] for t in turn_results)
    cpp = sum(1 for t in turn_results if t["searched_cpp"])
    return {
        "precision_micro": round(rel / tot, 4) if tot else 0.0,
        "precision_macro": round(mean(t["precision"] for t in turn_results), 4),
        "map": round(mean(t["average_precision"] for t in turn_results), 4),
        "n_relevant": rel,
        "n_chunks": tot,
        "cpp_searches": f"{cpp}/{len(turn_results)} turns",
        "session_precision_mean": round(
            mean(s["precision_mean"] for s in sessions), 4) if sessions else 0.0,
        "n_sessions": len(sessions),
        "n_turns_evaluated": len(turn_results),
        "latency_seconds": round(latency, 1),
    }


def build_params(name, thresholds, force_cpp, turn_results):
    return {
        "config": name,
        "embedding_model": EMB_MODEL,
        "top_k": FINAL_K,
        "semantic_top_k": FINAL_K,
        "rerank_strategy": RERANK,
        "weight_preset": "guideline_supplementary_equal",
        "weight_guideline": WEIGHTS[DocCategory.GUIDELINE],
        "weight_supplementary": WEIGHTS[DocCategory.SUPPLEMENTARY],
        "rules_top_k": RULES_TOP_K,
        "rules_threshold": thresholds.get("rules"),
        "guidelines_top_k": GUIDELINES_TOP_K,
        "guidelines_threshold": thresholds.get("guidelines"),
        "semantic_threshold": thresholds.get("semantic"),
        "force_cpp": force_cpp,
        "llm_judge_model": J.LLM_MODEL,
        "num_turns": len(turn_results),
        "num_sessions": len({t["session_id"] for t in turn_results}),
    }


def build_run(name, thresholds, force_cpp, rows, cache, latency):
    turn_results = build_turn_results(name, rows, cache)
    sessions = aggregate_precision_sessions(turn_results)
    return {
        "params": build_params(name, thresholds, force_cpp, turn_results),
        "run_metrics": aggregate_precision_run(turn_results, sessions, latency),
        "session_summaries": sessions,
        "turn_results": turn_results,
    }


def _write_checkpoint(path, rows, cache):
    """Flat per-turn results across all configs, computed from the current cache."""
    turn_results = [t for name, _, _ in CONFIGS
                    for t in build_turn_results(name, rows, cache)]
    H._write_json(path, turn_results)


def save_snapshot(path, runs):
    """Same schema as the harness eval_results_*.json (drops turn_results)."""
    H._write_json(path, [
        {
            "params": r["params"],
            "run_metrics": r["run_metrics"],
            "session_summaries": r["session_summaries"],
        }
        for r in runs
    ])


def report(runs):
    print(f"\n{'='*72}\nFINAL CONTEXT PRECISION\n{'='*72}")
    print(f"{'config':12s} {'micro':>8s} {'macro':>8s} {'MAP':>8s} "
          f"{'rel':>5s} {'total':>6s} {'cpp':>12s}")
    for r in runs:
        m, p = r["run_metrics"], r["params"]
        print(f"{p['config']:12s} {m['precision_micro']:8.4f} "
              f"{m['precision_macro']:8.4f} {m['map']:8.4f} "
              f"{m['n_relevant']:5d} {m['n_chunks']:6d} {m['cpp_searches']:>12s}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", action="store_true",
                    help="judge the cached retrieval artifact and report")
    args = ap.parse_args()
    if args.judge:
        run_judge()
    else:
        run_retrieval()
