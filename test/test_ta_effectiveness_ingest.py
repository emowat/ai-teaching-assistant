from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from rag_eng.ta_effectiveness_ingest import ingest_ta_effectiveness_scores

MACRO_METRICS = ["ZPD_progression", "direct_code_leakage", "human_ta_referral"]
MICRO_METRICS = ["scaffold_justified_syntax", "code_correctness"]


class _FakeCursor:
    def __init__(self, connection: "_FakeConnection") -> None:
        self._connection = connection
        self._rows: list[tuple[Any, ...]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, sql: str, params: Any = None) -> None:
        self._connection.executed.append((" ".join(sql.split()), params))
        normalized = " ".join(sql.split())
        if "FROM tutor_sessions" in normalized:
            requested_ids = set(params[0])
            self._rows = [
                row for row in self._connection.session_rows if row[0] in requested_ids
            ]
        elif "INSERT INTO ta_effectiveness_session_scores" in normalized:
            self._connection.session_upserts.append(params)
            self._rows = []
        elif "INSERT INTO ta_effectiveness_turn_scores" in normalized:
            self._connection.turn_upserts.append(params)
            self._rows = []
        else:
            self._rows = []

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None


class _FakeConnection:
    def __init__(self, session_rows: list[tuple[Any, ...]]) -> None:
        self.session_rows = session_rows
        self.executed: list[tuple[str, Any]] = []
        self.session_upserts: list[dict[str, Any]] = []
        self.turn_upserts: list[dict[str, Any]] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)


def _macro_record(**overrides: Any) -> dict[str, Any]:
    record = {
        "conversation_id": 0,
        "session_id": "session-1",
        "mode": "homework",
        "total_ratio_score": 0.9,
        "passed": True,
        "ZPD_progression": 1,
        "ZPD_progression_reason": "Student moved from understanding to debugging.",
        "direct_code_leakage": 1,
        "direct_code_leakage_reason": "No leak.",
        "human_ta_referral": "NA",
        "human_ta_referral_reason": "",
    }
    record.update(overrides)
    return record


def _micro_record(**overrides: Any) -> dict[str, Any]:
    record = {
        "conversation_id": 0,
        "session_id": "session-1",
        "turn_id": "turn-1",
        "turn_index": 0,
        "mode": "homework",
        "total_ratio_score": 0.75,
        "passed": True,
        "input_action": "NA",
        "output_action": "conceptual_hint",
        "scaffold_justified_syntax": 1,
        "scaffold_justified_syntax_reason": "Scaffolding matched the syllabus.",
        "code_correctness": 0,
        "code_correctness_reason": "Suggested code had an off-by-one error.",
    }
    record.update(overrides)
    return record


def test_ingest_happy_path_writes_session_and_turn_rows() -> None:
    connection = _FakeConnection(
        session_rows=[("session-1", "user-1", "section-1", "course-1")]
    )
    macro_results = [_macro_record()]
    micro_results = [_micro_record()]
    drift_results = {
        "per_convo": [
            {"conversation_id": 0, "delta": -0.2, "leak_turn": None, "drifted": True}
        ]
    }

    result = ingest_ta_effectiveness_scores(
        connection,
        evaluation_run_id="run-1",
        macro_results=macro_results,
        micro_results=micro_results,
        drift_results=drift_results,
        macro_metric_names=MACRO_METRICS,
        micro_metric_names=MICRO_METRICS,
    )

    assert result == {
        "sessions_written": 1,
        "turns_written": 1,
        "sessions_skipped_no_session_row": 0,
    }
    assert len(connection.session_upserts) == 1
    session_params = connection.session_upserts[0]
    assert session_params["evaluation_run_id"] == "run-1"
    assert session_params["session_id"] == "session-1"
    assert session_params["app_user_id"] == "user-1"
    assert session_params["section_id"] == "section-1"
    assert session_params["course_id"] == "course-1"
    assert session_params["session_effectiveness_score"] == 0.9
    assert session_params["session_passed"] is True
    assert session_params["drift_delta"] == -0.2
    assert session_params["drift_flag"] is True
    assert session_params["code_leak_turn_index"] is None
    # pedagogical_impact_score is the mean of this session's micro scores.
    assert session_params["pedagogical_impact_score"] == 0.75
    assert session_params["turn_count"] == 1

    macro_metric_results = session_params["macro_metric_results"]
    payload = macro_metric_results if isinstance(macro_metric_results, dict) else macro_metric_results.obj
    assert payload["ZPD_progression"]["value"] == 1
    assert "understanding" in payload["ZPD_progression"]["reason"]
    assert payload["human_ta_referral"]["value"] == "NA"

    assert len(connection.turn_upserts) == 1
    turn_params = connection.turn_upserts[0]
    assert turn_params["turn_id"] == "turn-1"
    assert turn_params["session_id"] == "session-1"
    assert turn_params["app_user_id"] == "user-1"
    assert turn_params["pedagogical_turn_score"] == 0.75
    micro_metric_results = turn_params["micro_metric_results"]
    micro_payload = (
        micro_metric_results if isinstance(micro_metric_results, dict) else micro_metric_results.obj
    )
    assert micro_payload["code_correctness"]["value"] == 0


def test_ingest_skips_sessions_with_no_tutor_sessions_row() -> None:
    connection = _FakeConnection(session_rows=[])
    macro_results = [_macro_record(session_id="unknown-session")]
    micro_results = [_micro_record(session_id="unknown-session")]

    result = ingest_ta_effectiveness_scores(
        connection,
        evaluation_run_id="run-1",
        macro_results=macro_results,
        micro_results=micro_results,
        drift_results={},
        macro_metric_names=MACRO_METRICS,
        micro_metric_names=MICRO_METRICS,
    )

    assert result == {
        "sessions_written": 0,
        "turns_written": 0,
        "sessions_skipped_no_session_row": 1,
    }
    assert connection.session_upserts == []
    assert connection.turn_upserts == []


def test_ingest_excludes_null_scores_from_pedagogical_impact_average() -> None:
    connection = _FakeConnection(
        session_rows=[("session-1", "user-1", "section-1", "course-1")]
    )
    macro_results = [_macro_record()]
    micro_results = [
        _micro_record(turn_id="turn-1", turn_index=0, total_ratio_score=1.0),
        _micro_record(turn_id="turn-2", turn_index=1, total_ratio_score=None),
        _micro_record(turn_id="turn-3", turn_index=2, total_ratio_score=0.5),
    ]

    ingest_ta_effectiveness_scores(
        connection,
        evaluation_run_id="run-1",
        macro_results=macro_results,
        micro_results=micro_results,
        drift_results={},
        macro_metric_names=MACRO_METRICS,
        micro_metric_names=MICRO_METRICS,
    )

    session_params = connection.session_upserts[0]
    # (1.0 + 0.5) / 2 == 0.75 — the None-scored turn must not count toward
    # the average or the denominator, matching calculate_scoring's NA rule.
    assert session_params["pedagogical_impact_score"] == 0.75
    assert session_params["turn_count"] == 2
    assert len(connection.turn_upserts) == 3


def test_ingest_is_idempotent_across_repeated_calls() -> None:
    connection = _FakeConnection(
        session_rows=[("session-1", "user-1", "section-1", "course-1")]
    )
    macro_results = [_macro_record()]
    micro_results = [_micro_record()]
    scored_at = datetime(2026, 7, 16, tzinfo=timezone.utc)

    first = ingest_ta_effectiveness_scores(
        connection,
        evaluation_run_id="run-1",
        macro_results=macro_results,
        micro_results=micro_results,
        drift_results={},
        macro_metric_names=MACRO_METRICS,
        micro_metric_names=MICRO_METRICS,
        scored_at=scored_at,
    )
    second = ingest_ta_effectiveness_scores(
        connection,
        evaluation_run_id="run-1",
        macro_results=macro_results,
        micro_results=micro_results,
        drift_results={},
        macro_metric_names=MACRO_METRICS,
        micro_metric_names=MICRO_METRICS,
        scored_at=scored_at,
    )

    assert first == second
    assert len(connection.session_upserts) == 2
    # Jsonb doesn't implement __eq__, so unwrap it before comparing —
    # equal SQL param dicts otherwise look unequal via plain `==`.
    assert _normalize_upsert(connection.session_upserts[0]) == _normalize_upsert(
        connection.session_upserts[1]
    )


def _normalize_upsert(params: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(params)
    for key, value in normalized.items():
        if not isinstance(value, (dict, list, str, int, float, bool)) and value is not None:
            normalized[key] = getattr(value, "obj", value)
    return normalized
