"""Join offline LLM-as-a-judge results to tutor sessions/students and persist them.

This module has no dependency on `model_eval` — it accepts plain Python
lists/dicts for the macro/micro/drift judge output plus the metric-name
lists, so it can be called from the ECS evaluation worker, a one-off backfill
script, and unit tests alike without importing judge-specific code.

Callers own the connection's transaction (mirroring `_persist_run_state` in
`model_eval/evaluation_worker.py`): open the connection with `with ...:` so
the transaction commits on successful exit.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

_SESSION_UPSERT_SQL = """
INSERT INTO ta_effectiveness_session_scores (
  evaluation_run_id, session_id, app_user_id, course_id, section_id, mode,
  conversation_id, session_effectiveness_score, session_passed,
  macro_metric_results, pedagogical_impact_score, turn_count,
  drift_delta, drift_flag, code_leak_turn_index, scored_at
) VALUES (
  %(evaluation_run_id)s, %(session_id)s, %(app_user_id)s, %(course_id)s, %(section_id)s, %(mode)s,
  %(conversation_id)s, %(session_effectiveness_score)s, %(session_passed)s,
  %(macro_metric_results)s, %(pedagogical_impact_score)s, %(turn_count)s,
  %(drift_delta)s, %(drift_flag)s, %(code_leak_turn_index)s, %(scored_at)s
)
ON CONFLICT (evaluation_run_id, session_id) DO UPDATE SET
  app_user_id = EXCLUDED.app_user_id,
  course_id = EXCLUDED.course_id,
  section_id = EXCLUDED.section_id,
  mode = EXCLUDED.mode,
  conversation_id = EXCLUDED.conversation_id,
  session_effectiveness_score = EXCLUDED.session_effectiveness_score,
  session_passed = EXCLUDED.session_passed,
  macro_metric_results = EXCLUDED.macro_metric_results,
  pedagogical_impact_score = EXCLUDED.pedagogical_impact_score,
  turn_count = EXCLUDED.turn_count,
  drift_delta = EXCLUDED.drift_delta,
  drift_flag = EXCLUDED.drift_flag,
  code_leak_turn_index = EXCLUDED.code_leak_turn_index,
  scored_at = EXCLUDED.scored_at,
  updated_at = now()
"""

_TURN_UPSERT_SQL = """
INSERT INTO ta_effectiveness_turn_scores (
  evaluation_run_id, session_id, turn_id, app_user_id, section_id, course_id,
  turn_index, mode, pedagogical_turn_score, turn_passed,
  micro_metric_results, input_action, output_action
) VALUES (
  %(evaluation_run_id)s, %(session_id)s, %(turn_id)s, %(app_user_id)s, %(section_id)s, %(course_id)s,
  %(turn_index)s, %(mode)s, %(pedagogical_turn_score)s, %(turn_passed)s,
  %(micro_metric_results)s, %(input_action)s, %(output_action)s
)
ON CONFLICT (evaluation_run_id, turn_id) DO UPDATE SET
  session_id = EXCLUDED.session_id,
  app_user_id = EXCLUDED.app_user_id,
  section_id = EXCLUDED.section_id,
  course_id = EXCLUDED.course_id,
  turn_index = EXCLUDED.turn_index,
  mode = EXCLUDED.mode,
  pedagogical_turn_score = EXCLUDED.pedagogical_turn_score,
  turn_passed = EXCLUDED.turn_passed,
  micro_metric_results = EXCLUDED.micro_metric_results,
  input_action = EXCLUDED.input_action,
  output_action = EXCLUDED.output_action,
  updated_at = now()
"""


def _json_safe_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _json_adapter(data: dict[str, Any]) -> Any:
    try:
        from psycopg.types.json import Jsonb
    except ImportError:  # pragma: no cover - only if dependency missing
        return data
    return Jsonb(_json_safe_value(data))


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _lookup_session_context(
    connection, session_ids: list[str]
) -> dict[str, dict[str, Any]]:
    if not session_ids:
        return {}
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT session_id, app_user_id, section_id, course_id
            FROM tutor_sessions
            WHERE session_id = ANY(%s)
            """,
            (session_ids,),
        )
        rows = cursor.fetchall()
    return {
        row[0]: {"app_user_id": row[1], "section_id": row[2], "course_id": row[3]}
        for row in rows
    }


def ingest_ta_effectiveness_scores(
    connection,
    *,
    evaluation_run_id: str,
    macro_results: list[dict[str, Any]],
    micro_results: list[dict[str, Any]],
    drift_results: dict[str, Any] | None,
    macro_metric_names: list[str],
    micro_metric_names: list[str],
    scored_at: datetime | None = None,
) -> dict[str, int]:
    """Join macro/micro/drift judge output to `tutor_sessions` and upsert
    `ta_effectiveness_session_scores`/`ta_effectiveness_turn_scores`.

    Sessions with no matching `tutor_sessions` row (e.g. seeded test data,
    or sessions predating the `app_user_id` backfill) are skipped, not
    raised, since a bug here must never fail the parent evaluation run.
    """
    scored_at = scored_at or datetime.now(timezone.utc)
    drift_results = drift_results or {}

    session_ids = sorted(
        {
            record.get("session_id")
            for record in (*macro_results, *micro_results)
            if record.get("session_id")
        }
    )
    session_context = _lookup_session_context(connection, session_ids)

    # `drift_results["per_convo"]` keys on the run-local `conversation_id`,
    # not `session_id` — recover session_id via the macro records, since
    # conversation_id is consistent across macro/micro/drift within one run
    # (assigned by `stratified_sample`) but never stable across runs.
    conversation_to_session = {
        record.get("conversation_id"): record.get("session_id")
        for record in macro_results
        if record.get("conversation_id") is not None and record.get("session_id")
    }
    drift_by_session: dict[str, dict[str, Any]] = {}
    for drift_record in drift_results.get("per_convo") or []:
        session_id = conversation_to_session.get(drift_record.get("conversation_id"))
        if session_id:
            drift_by_session[session_id] = drift_record

    micro_scores_by_session: dict[str, list[float]] = defaultdict(list)
    for record in micro_results:
        session_id = record.get("session_id")
        score = record.get("total_ratio_score")
        if session_id and score is not None:
            micro_scores_by_session[session_id].append(float(score))

    sessions_written = 0
    sessions_skipped = 0
    turns_written = 0

    with connection.cursor() as cursor:
        for record in macro_results:
            session_id = record.get("session_id")
            context = session_context.get(session_id) if session_id else None
            if context is None:
                sessions_skipped += 1
                continue

            macro_metric_results = {
                name: {
                    "value": record.get(name, "NA"),
                    "reason": record.get(f"{name}_reason", ""),
                }
                for name in macro_metric_names
            }
            drift_record = drift_by_session.get(session_id, {})
            turn_scores = micro_scores_by_session.get(session_id, [])

            cursor.execute(
                _SESSION_UPSERT_SQL,
                {
                    "evaluation_run_id": evaluation_run_id,
                    "session_id": session_id,
                    "app_user_id": context.get("app_user_id"),
                    "course_id": context.get("course_id"),
                    "section_id": context.get("section_id"),
                    "mode": record.get("mode") or "",
                    "conversation_id": record.get("conversation_id"),
                    "session_effectiveness_score": record.get("total_ratio_score"),
                    "session_passed": record.get("passed"),
                    "macro_metric_results": _json_adapter(macro_metric_results),
                    "pedagogical_impact_score": _mean(turn_scores),
                    "turn_count": len(turn_scores),
                    "drift_delta": drift_record.get("delta"),
                    "drift_flag": bool(drift_record.get("drifted", False)),
                    "code_leak_turn_index": drift_record.get("leak_turn"),
                    "scored_at": scored_at,
                },
            )
            sessions_written += 1

        for record in micro_results:
            session_id = record.get("session_id")
            turn_id = record.get("turn_id")
            context = session_context.get(session_id) if session_id else None
            if context is None or not turn_id:
                continue

            micro_metric_results = {
                name: {
                    "value": record.get(name, "NA"),
                    "reason": record.get(f"{name}_reason", ""),
                }
                for name in micro_metric_names
            }

            cursor.execute(
                _TURN_UPSERT_SQL,
                {
                    "evaluation_run_id": evaluation_run_id,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "app_user_id": context.get("app_user_id"),
                    "section_id": context.get("section_id"),
                    "course_id": context.get("course_id"),
                    "turn_index": record.get("turn_index"),
                    "mode": record.get("mode") or "",
                    "pedagogical_turn_score": record.get("total_ratio_score"),
                    "turn_passed": record.get("passed"),
                    "micro_metric_results": _json_adapter(micro_metric_results),
                    "input_action": record.get("input_action") or "",
                    "output_action": record.get("output_action") or "",
                },
            )
            turns_written += 1

    return {
        "sessions_written": sessions_written,
        "turns_written": turns_written,
        "sessions_skipped_no_session_row": sessions_skipped,
    }
