"""Best-effort tutoring session and telemetry persistence for Aurora."""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, replace
from typing import Any, Mapping

from rag.schemas import QueryInput
from rag_eng.aurora_retry import connect_postgres_with_retry


logger = logging.getLogger(__name__)


def _normalize_text(value: object | None) -> str:
    if value is None:
        return ""
    return str(value)


def _normalize_course_key(value: str | None) -> str:
    """Normalize course identifiers so aliases collapse to the canonical key."""
    if not value:
        return ""
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def _connect_postgres(database_url: str, connect_timeout_seconds: int):
    """Open Aurora telemetry connections with the interactive retry profile."""
    return connect_postgres_with_retry(
        database_url,
        profile="interactive",
        connect_timeout_seconds=connect_timeout_seconds,
    )


def _json_adapter(data: dict[str, Any]) -> Any:
    """Adapt dictionaries to JSONB if psycopg is available."""
    try:
        from psycopg.types.json import Jsonb
    except ImportError:  # pragma: no cover - handled by the connection helper
        return data

    return Jsonb(data)


@dataclass(frozen=True)
class TraceContext:
    """Identifiers and coarse routing metadata for one tutoring request."""

    request_id: str
    session_id: str
    turn_id: str
    turn_index: int
    source: str
    course_id: str
    course_source: str
    section_id: str | None = None
    user_sub: str | None = None
    mode: str = ""
    week: int = 0
    persisted: bool = False


@dataclass(frozen=True)
class SessionOrchestrationState:
    """Session-scoped orchestrator state stored in `tutor_sessions.metadata`."""

    adversarial_warnings: int = 0
    terminated: bool = False
    termination_reason: str = ""
    last_flag_reason: str = ""
    last_action_taken: str = ""

    @classmethod
    def from_metadata(
        cls,
        metadata: Mapping[str, Any] | None,
        *,
        status: str | None = None,
    ) -> SessionOrchestrationState:
        payload = dict(metadata or {})
        warnings_value = (
            payload.get("Session_Adversarial_Warnings")
            or payload.get("session_adversarial_warnings")
            or 0
        )
        return cls(
            adversarial_warnings=int(warnings_value),
            terminated=bool(
                payload.get("Session_Adversarial_Terminated")
                or payload.get("session_terminated")
                or status == "ended"
            ),
            termination_reason=_normalize_text(
                payload.get("Session_Adversarial_Termination_Reason")
                or payload.get("session_termination_reason")
            ),
            last_flag_reason=_normalize_text(
                payload.get("Session_Adversarial_Last_Flag_Reason")
                or payload.get("session_last_flag_reason")
            ),
            last_action_taken=_normalize_text(
                payload.get("Session_Adversarial_Last_Action")
                or payload.get("session_last_action_taken")
            ),
        )

    def to_metadata_patch(self) -> dict[str, Any]:
        """Return the canonical metadata keys persisted on `tutor_sessions`."""
        patch: dict[str, Any] = {
            "Session_Adversarial_Warnings": self.adversarial_warnings,
            "Session_Adversarial_Terminated": self.terminated,
        }
        if self.termination_reason:
            patch["Session_Adversarial_Termination_Reason"] = self.termination_reason
        if self.last_flag_reason:
            patch["Session_Adversarial_Last_Flag_Reason"] = self.last_flag_reason
        if self.last_action_taken:
            patch["Session_Adversarial_Last_Action"] = self.last_action_taken
        return patch

    def to_snapshot_dict(self) -> dict[str, Any]:
        """Return a snapshot-friendly representation for turn logs."""
        return {
            "Session_Adversarial_Warnings": self.adversarial_warnings,
            "Session_Adversarial_Terminated": self.terminated,
            "Session_Adversarial_Termination_Reason": (
                self.termination_reason or None
            ),
            "Session_Adversarial_Last_Flag_Reason": self.last_flag_reason or None,
            "Session_Adversarial_Last_Action": self.last_action_taken or None,
        }


class TelemetryStore:
    """Write session, turn, snapshot, and coarse telemetry events to Aurora."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        connect_timeout_seconds: int = 3,
    ) -> None:
        self.database_url = database_url
        self.connect_timeout_seconds = connect_timeout_seconds

    @classmethod
    def from_env(cls) -> TelemetryStore:
        """Create a store from the current process environment."""
        database_url = (
            os.getenv("COURSE_REGISTRY_DATABASE_URL")
            or os.getenv("DATABASE_URL")
        )
        return cls(database_url=database_url)

    def _trace_context(
        self,
        *,
        query: QueryInput,
        source: str,
        user_sub: str | None = None,
    ) -> TraceContext:
        course_id = _normalize_course_key(query.course_id or query.course_source.value)
        course_source = (
            _normalize_course_key(query.course_id)
            if query.course_id
            else query.course_source.value
        )
        return TraceContext(
            request_id=query.request_id or uuid.uuid4().hex,
            session_id=query.session_id or uuid.uuid4().hex,
            turn_id=query.turn_id or uuid.uuid4().hex,
            turn_index=1,
            source=source,
            course_id=course_id,
            course_source=course_source,
            section_id=query.section_id,
            user_sub=user_sub,
            mode=str(query.mode.value),
            week=query.week,
        )

    def start_turn(
        self,
        *,
        query: QueryInput,
        source: str,
        user_sub: str | None = None,
    ) -> TraceContext:
        """Create or update the session/turn rows and log request start."""
        trace = self._trace_context(query=query, source=source, user_sub=user_sub)
        if not self.database_url:
            return trace

        paste_event_inc = 1 if (query.clipboard_event and query.clipboard_event.external_paste_detected) else 0
        paste_char_inc = query.clipboard_event.pasted_char_count if paste_event_inc and query.clipboard_event else 0

        metadata = {
            "source": source,
            "mode": trace.mode,
            "week": trace.week,
            "course_id": trace.course_id,
            "course_source": trace.course_source,
            "section_id": trace.section_id,
            "total_paste_events": paste_event_inc,
            "total_paste_characters": paste_char_inc,
        }

        try:
            with _connect_postgres(
                self.database_url,
                self.connect_timeout_seconds,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO tutor_sessions (
                          session_id,
                          user_sub,
                          course_id,
                          section_id,
                          first_request_id,
                          last_request_id,
                          turn_count,
                          status,
                          metadata
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, 1, 'active', %s)
                        ON CONFLICT (session_id) DO UPDATE SET
                          user_sub = COALESCE(tutor_sessions.user_sub, EXCLUDED.user_sub),
                          course_id = COALESCE(EXCLUDED.course_id, tutor_sessions.course_id),
                          section_id = COALESCE(EXCLUDED.section_id, tutor_sessions.section_id),
                          last_request_id = EXCLUDED.last_request_id,
                          last_seen_at = now(),
                          turn_count = tutor_sessions.turn_count + 1,
                          status = 'active',
                          metadata = (
                              COALESCE(tutor_sessions.metadata, '{}'::jsonb) || 
                              COALESCE(EXCLUDED.metadata, '{}'::jsonb) ||
                              jsonb_build_object(
                                  'total_paste_events', COALESCE((tutor_sessions.metadata->>'total_paste_events')::int, 0) + COALESCE((EXCLUDED.metadata->>'total_paste_events')::int, 0),
                                  'total_paste_characters', COALESCE((tutor_sessions.metadata->>'total_paste_characters')::int, 0) + COALESCE((EXCLUDED.metadata->>'total_paste_characters')::int, 0)
                              )
                          ),
                          updated_at = now()
                        RETURNING turn_count
                        """,
                        (
                            trace.session_id,
                            trace.user_sub,
                            trace.course_id,
                            trace.section_id,
                            trace.request_id,
                            trace.request_id,
                            _json_adapter(metadata),
                        ),
                    )
                    turn_index = int(cursor.fetchone()[0] or 1)
                    trace = replace(trace, turn_index=turn_index, persisted=True)
                    cursor.execute(
                        """
                        INSERT INTO tutor_turns (
                          turn_id,
                          session_id,
                          request_id,
                          turn_index,
                          user_sub,
                          course_id,
                          section_id,
                          course_source,
                          mode,
                          week,
                          status,
                          model_provider,
                          model_name,
                          retrieval_doc_count,
                          answer_chars,
                          metadata
                        )
                        VALUES (
                          %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                          'started', '', '', 0, 0, %s
                        )
                        """,
                        (
                            trace.turn_id,
                            trace.session_id,
                            trace.request_id,
                            trace.turn_index,
                            trace.user_sub,
                            trace.course_id,
                            trace.section_id,
                            trace.course_source,
                            trace.mode,
                            trace.week,
                            _json_adapter(metadata),
                        ),
                    )
                    cursor.execute(
                        """
                        INSERT INTO telemetry_events (
                          request_id,
                          session_id,
                          turn_id,
                          turn_index,
                          user_sub,
                          course_id,
                          section_id,
                          course_source,
                          event_type,
                          stage,
                          status,
                          metadata
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            trace.request_id,
                            trace.session_id,
                            trace.turn_id,
                            trace.turn_index,
                            trace.user_sub,
                            trace.course_id,
                            trace.section_id,
                            trace.course_source,
                            "request_started",
                            "request",
                            "started",
                            _json_adapter(metadata),
                        ),
                    )
            return trace
        except Exception as exc:
            logger.warning(
                "Aurora telemetry unavailable; skipping trace write: %s",
                exc,
            )
            return trace

    def record_event(
        self,
        trace: TraceContext,
        *,
        event_type: str,
        stage: str,
        status: str,
        latency_ms: int | None = None,
        model_provider: str | None = None,
        model_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Write a single stage event; failures are logged and ignored."""
        if not self.database_url or not trace.persisted:
            return False

        try:
            with _connect_postgres(
                self.database_url,
                self.connect_timeout_seconds,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO telemetry_events (
                          request_id,
                          session_id,
                          turn_id,
                          turn_index,
                          user_sub,
                          course_id,
                          section_id,
                          course_source,
                          event_type,
                          stage,
                          status,
                          latency_ms,
                          model_provider,
                          model_name,
                          metadata
                        )
                        VALUES (
                          %s, %s, %s, %s, %s, %s, %s, %s,
                          %s, %s, %s, %s, %s, %s, %s
                        )
                        """,
                        (
                            trace.request_id,
                            trace.session_id,
                            trace.turn_id,
                            trace.turn_index,
                            trace.user_sub,
                            trace.course_id,
                            trace.section_id,
                            trace.course_source,
                            event_type,
                            stage,
                            status,
                            latency_ms,
                            _normalize_text(model_provider),
                            _normalize_text(model_name),
                            _json_adapter(metadata or {}),
                        ),
                    )
            return True
        except Exception as exc:
            logger.warning(
                "Aurora telemetry event skipped for %s/%s: %s",
                trace.session_id,
                trace.turn_id,
                exc,
            )
            return False

    def get_session_orchestration_state(
        self,
        session_id: str,
    ) -> SessionOrchestrationState:
        """Read the current session-level guardrail/orchestrator state."""
        if not self.database_url:
            return SessionOrchestrationState()

        try:
            with _connect_postgres(
                self.database_url,
                self.connect_timeout_seconds,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT metadata, status
                        FROM tutor_sessions
                        WHERE session_id = %s
                        """,
                        (session_id,),
                    )
                    row = cursor.fetchone()
        except Exception as exc:
            logger.warning(
                "Aurora session state lookup skipped for %s: %s",
                session_id,
                exc,
            )
            return SessionOrchestrationState()

        if row is None:
            return SessionOrchestrationState()

        metadata, status = row
        return SessionOrchestrationState.from_metadata(metadata, status=status)

    def update_session_orchestration_state(
        self,
        session_id: str,
        state: SessionOrchestrationState,
    ) -> bool:
        """Persist the orchestrator state back onto the session row."""
        if not self.database_url:
            return False

        try:
            with _connect_postgres(
                self.database_url,
                self.connect_timeout_seconds,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE tutor_sessions
                        SET
                          metadata = COALESCE(metadata, '{}'::jsonb) || COALESCE(%s, '{}'::jsonb),
                          updated_at = now(),
                          last_seen_at = now()
                        WHERE session_id = %s
                        """,
                        (_json_adapter(state.to_metadata_patch()), session_id),
                    )
            return True
        except Exception as exc:
            logger.warning(
                "Aurora session state update skipped for %s: %s",
                session_id,
                exc,
            )
            return False

    def record_turn_snapshot(
        self,
        trace: TraceContext,
        snapshot: dict[str, Any],
    ) -> bool:
        """Persist the canonical per-turn evaluation snapshot."""
        if not self.database_url or not trace.persisted:
            return False

        schema_version = _normalize_text(snapshot.get("schema_version") or "v1")
        try:
            with _connect_postgres(
                self.database_url,
                self.connect_timeout_seconds,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO tutor_turn_snapshots (
                          turn_id,
                          session_id,
                          request_id,
                          turn_index,
                          user_sub,
                          course_id,
                          course_source,
                          section_id,
                          schema_version,
                          snapshot
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (turn_id) DO UPDATE SET
                          session_id = EXCLUDED.session_id,
                          request_id = EXCLUDED.request_id,
                          turn_index = EXCLUDED.turn_index,
                          user_sub = EXCLUDED.user_sub,
                          course_id = EXCLUDED.course_id,
                          course_source = EXCLUDED.course_source,
                          section_id = EXCLUDED.section_id,
                          schema_version = EXCLUDED.schema_version,
                          snapshot = EXCLUDED.snapshot,
                          updated_at = now()
                        """,
                        (
                            trace.turn_id,
                            trace.session_id,
                            trace.request_id,
                            trace.turn_index,
                            trace.user_sub,
                            trace.course_id,
                            trace.course_source,
                            trace.section_id,
                            schema_version,
                            _json_adapter(snapshot),
                        ),
                    )
            return True
        except Exception as exc:
            logger.warning(
                "Aurora turn snapshot skipped for %s/%s: %s",
                trace.session_id,
                trace.turn_id,
                exc,
            )
            return False

    def record_out_of_band_telemetry(
        self,
        session_id: str,
        mode: str,
        engagement_metrics: dict[str, int]
    ) -> bool:
        """Persist out-of-band engagement metrics without needing a full chat turn."""
        if not self.database_url or not session_id:
            return False

        try:
            with _connect_postgres(
                self.database_url,
                self.connect_timeout_seconds,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT course_id FROM tutor_sessions WHERE session_id = %s LIMIT 1", (session_id,))
                    row = cursor.fetchone()
                    course_id = row[0] if row else None

                    cursor.execute(
                        """
                        INSERT INTO telemetry_events (
                          request_id,
                          session_id,
                          course_id,
                          event_type,
                          stage,
                          status,
                          metadata
                        )
                        VALUES (
                          %s, %s, %s, %s, %s, %s, %s
                        )
                        """,
                        (
                            uuid.uuid4().hex,
                            session_id,
                            course_id,
                            "out_of_band_telemetry",
                            mode,
                            "success",
                            _json_adapter(engagement_metrics)
                        )
                    )
                connection.commit()
            return True
        except Exception as exc:
            logger.warning("Failed to record out of band telemetry for %s: %s", session_id, exc)
            return False

    def record_feedback(
        self,
        session_id: str,
        message_index: int,
        rating: str,
        reason: str | None
    ) -> bool:
        """Update the turn snapshot with user feedback."""
        if not self.database_url or not session_id or not message_index:
            return False

        # Convert frontend message_index (0-indexed: 1, 3, 5) to backend turn_index (1-indexed: 1, 2, 3)
        turn_index = (message_index + 1) // 2
        thumbs_up = "positive" if rating == "up" else "negative"

        try:
            with _connect_postgres(
                self.database_url,
                self.connect_timeout_seconds,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE tutor_turn_snapshots
                        SET snapshot = jsonb_set(
                            snapshot,
                            '{feedback}',
                            jsonb_build_object('thumbs_up', %s, 'explanation', %s)
                        )
                        WHERE session_id = %s AND turn_index = %s
                        """,
                        (thumbs_up, reason, session_id, turn_index)
                    )
                connection.commit()
            return True
        except Exception as e:
            logger.warning("Aurora telemetry feedback update failed: %s", e)
            return False

    def finish_turn(
        self,
        trace: TraceContext,
        *,
        status: str,
        latency_ms: int | None = None,
        model_provider: str | None = None,
        model_name: str | None = None,
        answer_chars: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Mark the turn complete and emit the terminal telemetry event."""
        if not self.database_url or not trace.persisted:
            return False

        event_type = "request_failed" if status == "failed" else "answer_returned"
        session_status = "ended" if (metadata or {}).get("session_terminated") else status
        try:
            with _connect_postgres(
                self.database_url,
                self.connect_timeout_seconds,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE tutor_sessions
                        SET
                          last_request_id = %s,
                          last_seen_at = now(),
                          status = %s
                        WHERE session_id = %s
                        """,
                        (trace.request_id, session_status, trace.session_id),
                    )
                    cursor.execute(
                        """
                        UPDATE tutor_turns
                        SET
                          status = %s,
                          latency_ms = COALESCE(%s, latency_ms),
                          answer_chars = COALESCE(%s, answer_chars),
                          completed_at = now(),
                          updated_at = now(),
                          model_provider = COALESCE(NULLIF(%s, ''), model_provider),
                          model_name = COALESCE(NULLIF(%s, ''), model_name),
                          metadata = COALESCE(tutor_turns.metadata, '{}'::jsonb) || COALESCE(%s, '{}'::jsonb)
                        WHERE turn_id = %s
                        """,
                        (
                            status,
                            latency_ms,
                            answer_chars,
                            _normalize_text(model_provider),
                            _normalize_text(model_name),
                            _json_adapter(metadata or {}),
                            trace.turn_id,
                        ),
                    )
            return self.record_event(
                trace,
                event_type=event_type,
                stage="answer",
                status=status,
                latency_ms=latency_ms,
                model_provider=model_provider,
                model_name=model_name,
                metadata={
                    "status": status,
                    "answer_chars": answer_chars,
                    "latency_ms": latency_ms,
                    **(metadata or {}),
                },
            )
        except Exception as exc:
            logger.warning(
                "Aurora telemetry finish skipped for %s/%s: %s",
                trace.session_id,
                trace.turn_id,
                exc,
            )
            return False


def get_telemetry_store(database_url: str | None = None) -> TelemetryStore:
    """Return a telemetry store bound to the active Aurora connection string."""
    resolved = database_url or (
        os.getenv("COURSE_REGISTRY_DATABASE_URL") or os.getenv("DATABASE_URL")
    )
    return TelemetryStore(database_url=resolved)
