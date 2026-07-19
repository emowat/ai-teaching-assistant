"""
Compare current *adaptive* retrieval against what production actually retrieved,
using real MIT-14 turn logs.

For every turn in the logs we:
  1. Reconstruct the conversation history (group by session, order by turn_index).
  2. Build the adaptive retrieval query with the SAME `build_retrieval_query`
     the production backend now uses (anchor + recent + current code/terminal for
     low-signal follow-ups; the message itself otherwise).
  3. Run the live retrieval pipeline and compare the retrieved chunk_ids with the
     chunk_ids stored in the log.

We also run a *baseline* pass (retrieval on the raw current message, no
contextualization) through the same pipeline, so the diff isolates the effect of
the adaptive query from any pipeline drift since the log was written.

Usage:
  # after `aws sso login`
  python rag/experiments/compare_adaptive_vs_log_mit14.py \
      --input s3://codingrabbit-data-dev/eval/chat_logs/turn_logs/course_id=mit14/date=2026-07-16/

  # or against a local directory / glob of turn_snapshots.jsonl files
  python rag/experiments/compare_adaptive_vs_log_mit14.py --input model_eval/eval/date=2026-07-05/
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from rag.schemas import ASTFeatures, AssistMode, CourseSource, QueryInput
from rag.query_builder import build_retrieval_query
from rag.pipeline import run_retrieval
from rag.runtime import create_qdrant_client, get_runtime_config

DEFAULT_INPUT = (
    "s3://codingrabbit-data-dev/eval/chat_logs/turn_logs/"
    "course_id=mit14/date=2026-07-16/"
)
COURSE_COLLECTION = "mit14_course_BAAI_bge_large_en_v1_5"


# ---------------------------------------------------------------------------
# Loading turn logs (S3 or local)
# ---------------------------------------------------------------------------

def _load_jsonl_lines(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def load_turn_logs(source: str) -> list[dict]:
    """Load all turn-snapshot rows from an s3:// prefix or a local dir/glob."""
    exts = (".jsonl", ".json", ".ndjson")
    rows: list[dict] = []
    if source.startswith("s3://"):
        import boto3

        bucket, _, prefix = source[len("s3://"):].partition("/")
        s3 = boto3.client("s3")
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if not key.endswith(exts):
                    continue
                body = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
                rows.extend(_load_jsonl_lines(body))
    else:
        if source.endswith(exts):
            paths = [source]
        else:
            paths = [
                p
                for ext in exts
                for p in glob.glob(os.path.join(source, "**", f"*{ext}"), recursive=True)
            ]
        for path in paths:
            with open(path, encoding="utf-8") as handle:
                rows.extend(_load_jsonl_lines(handle.read()))
    return rows


# ---------------------------------------------------------------------------
# Field extraction from a snapshot row
# ---------------------------------------------------------------------------

def _student_message(row: dict) -> str:
    return (row.get("student_phase") or {}).get("raw_input", "") or ""


def _logged_chunk_ids(row: dict) -> list[str]:
    chunks = (row.get("backend_retrieval_phase") or {}).get("retrieved_rag_chunks", [])
    return [str(c["chunk_id"]) for c in chunks if c.get("chunk_id")]


_AST_FIELDS = set(ASTFeatures.model_fields.keys())


def _ast_features(row: dict) -> ASTFeatures:
    meta = (row.get("ide_context") or {}).get("ast_metadata") or {}
    return ASTFeatures(**{k: v for k, v in meta.items() if k in _AST_FIELDS})


def _mode(row: dict) -> AssistMode:
    raw = (row.get("ide_context") or {}).get("mode", "Homework Assist")
    return AssistMode.STUDY_ASSIST if raw == "Study Assist" else AssistMode.HOMEWORK_ASSIST


def _current_turn_message(row: dict) -> str:
    """Rebuild the current user message in extension-block form so the adaptive
    query can pull the turn's code + terminal, matching production input."""
    ide = row.get("ide_context") or {}
    code = ide.get("raw_code_snippet") or ""
    terminal = ide.get("terminal_context") or ""
    question = _student_message(row)
    parts = []
    if code:
        parts.append(f"[Code_Context]\n{code}")
    if terminal:
        parts.append(f"[Terminal_Context]\n{terminal}")
    parts.append(f"[Student_Question]\n{question}")
    return "\n".join(parts)


def _infer_week(qdrant, chunk_ids: list[str], chunks: list[dict]) -> int | None:
    """Infer the query week from the logged course chunks.

    Course (lecture/assignment) chunks are week-tagged in Qdrant, so the query
    week is the max non-zero week among the logged course chunks (works for both
    exact-week homework and cumulative study). Falls back to parsing "Week N"
    from a syllabus chunk's content.
    """
    if chunk_ids:
        try:
            points = qdrant.retrieve(COURSE_COLLECTION, ids=chunk_ids, with_payload=True)
            weeks = [
                int((p.payload or {}).get("week", 0))
                for p in points
                if (p.payload or {}).get("week")
            ]
            if weeks:
                return max(weeks)
        except Exception:
            pass
    for c in chunks:
        m = re.search(r"Week\s+(\d+)", (c.get("Content") or "")[:80])
        if m:
            return int(m.group(1))
    return None


# ---------------------------------------------------------------------------
# History reconstruction
# ---------------------------------------------------------------------------

def build_sessions(rows: list[dict]) -> dict[str, list[dict]]:
    """Group rows by session and order by turn_index (missing → 0)."""
    sessions: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        sid = (row.get("trace") or {}).get("session_id") or row.get("session_id") or "?"
        sessions[sid].append(row)
    for sid, turns in sessions.items():
        turns.sort(key=lambda r: (r.get("trace") or {}).get("turn_index", 0))
    return sessions


def history_messages(prior_rows: list[dict], current_row: dict) -> list[dict]:
    """Messages list for build_retrieval_query: prior student turns + current
    (block-formatted so code/terminal can be pulled). Assistant turns are omitted
    because build_retrieval_query only reads user turns."""
    messages = [
        {"role": "user", "content": _student_message(r)}
        for r in prior_rows
        if _student_message(r)
    ]
    messages.append({"role": "user", "content": _current_turn_message(current_row)})
    return messages


# ---------------------------------------------------------------------------
# Retrieval + comparison
# ---------------------------------------------------------------------------

def _retrieved_ids(query: QueryInput) -> list[str]:
    result = run_retrieval(query)
    docs = (
        ([result.syllabus] if result.syllabus else [])
        + result.strict_rules + result.pedagogical
        + result.supplementary + result.guidelines + result.harvard
    )
    return [d.chunk_id for d in docs if d.chunk_id]


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b) if (a | b) else 0.0


def compare_turn(qdrant, prior_rows: list[dict], row: dict) -> dict | None:
    student_msg = _student_message(row)
    if not student_msg:
        return None

    logged = _logged_chunk_ids(row)
    chunks = (row.get("backend_retrieval_phase") or {}).get("retrieved_rag_chunks", [])
    week = _infer_week(qdrant, logged, chunks)
    if week is None:
        return None

    messages = history_messages(prior_rows, row)
    adaptive_query = build_retrieval_query(messages)

    common = dict(
        week=week, mode=_mode(row), course_source=CourseSource.MIT_14,
        ast_features=_ast_features(row),
        code_raw=(row.get("ide_context") or {}).get("raw_code_snippet", "") or "",
    )
    baseline_q = QueryInput(student_message=student_msg, retrieval_query=None, **common)
    adaptive_q = QueryInput(student_message=student_msg, retrieval_query=adaptive_query, **common)

    logged_set = set(logged)
    baseline_set = set(_retrieved_ids(baseline_q))
    adaptive_set = set(_retrieved_ids(adaptive_q))

    return {
        "session_id": (row.get("trace") or {}).get("session_id"),
        "turn_index": (row.get("trace") or {}).get("turn_index", 0),
        "week": week,
        "mode": common["mode"].value,
        "student_message": student_msg,
        "adaptive_query": adaptive_query,           # None → embedded the message as-is
        "contextualized": adaptive_query is not None,
        "n_logged": len(logged_set),
        "n_adaptive": len(adaptive_set),
        "overlap_adaptive_vs_log": len(adaptive_set & logged_set),
        "jaccard_adaptive_vs_log": round(_jaccard(adaptive_set, logged_set), 3),
        "jaccard_baseline_vs_log": round(_jaccard(baseline_set, logged_set), 3),
        "adaptive_changed_retrieval": adaptive_set != baseline_set,
        "added_vs_log": sorted(adaptive_set - logged_set),
        "dropped_vs_log": sorted(logged_set - adaptive_set),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=DEFAULT_INPUT, help="s3:// prefix or local dir/glob")
    parser.add_argument("--max-turns", type=int, default=0, help="limit turns (0 = all)")
    parser.add_argument("--out", default="", help="optional path to write per-turn JSON")
    parser.add_argument("--show-followups-only", action="store_true",
                        help="only print rows where the adaptive query differed from the message")
    args = parser.parse_args()

    print(f"Loading turn logs from {args.input} ...")
    rows = load_turn_logs(args.input)
    print(f"  {len(rows)} rows")
    sessions = build_sessions(rows)
    print(f"  {len(sessions)} sessions")

    qdrant = create_qdrant_client(get_runtime_config())
    results: list[dict] = []
    try:
        for turns in sessions.values():
            for idx, row in enumerate(turns):
                res = compare_turn(qdrant, turns[:idx], row)
                if res:
                    results.append(res)
                if args.max_turns and len(results) >= args.max_turns:
                    break
            if args.max_turns and len(results) >= args.max_turns:
                break
    finally:
        try:
            qdrant.close()
        except Exception:
            pass

    print(f"\nEvaluated {len(results)} turns "
          f"({sum(r['contextualized'] for r in results)} contextualized follow-ups)\n")
    header = (
        f"{'sess':>8} {'t':>2} {'wk':>2} {'ctx':>3} "
        f"{'J(adap)':>7} {'J(base)':>7} {'ovl':>3} | query / message"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        if args.show_followups_only and not r["contextualized"]:
            continue
        shown = r["adaptive_query"] or r["student_message"]
        print(
            f"{(r['session_id'] or '?')[:8]:>8} {r['turn_index']:>2} {r['week']:>2} "
            f"{'Y' if r['contextualized'] else '-':>3} "
            f"{r['jaccard_adaptive_vs_log']:>7} {r['jaccard_baseline_vs_log']:>7} "
            f"{r['overlap_adaptive_vs_log']:>3} | {shown[:70]!r}"
        )

    if results:
        ctx = [r for r in results if r["contextualized"]]
        print("\n--- aggregate ---")
        print(f"  turns evaluated:            {len(results)}")
        print(f"  contextualized follow-ups:  {len(ctx)}")
        print(f"  adaptive changed retrieval: {sum(r['adaptive_changed_retrieval'] for r in results)}")
        print(f"  mean Jaccard adaptive-vs-log: {mean(r['jaccard_adaptive_vs_log'] for r in results):.3f}")
        print(f"  mean Jaccard baseline-vs-log: {mean(r['jaccard_baseline_vs_log'] for r in results):.3f}")
        if ctx:
            print(f"  mean Jaccard adaptive-vs-log (follow-ups only): "
                  f"{mean(r['jaccard_adaptive_vs_log'] for r in ctx):.3f}")
            print(f"  mean Jaccard baseline-vs-log (follow-ups only): "
                  f"{mean(r['jaccard_baseline_vs_log'] for r in ctx):.3f}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(results, handle, indent=2, ensure_ascii=False)
        print(f"\nPer-turn detail → {args.out}")


if __name__ == "__main__":
    main()
