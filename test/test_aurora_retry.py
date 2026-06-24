from __future__ import annotations

from dataclasses import dataclass

import pytest

from rag_eng.config import (
    AuroraRetryConfig,
    AuroraRetryProfileConfig,
    ChatLogExportConfig,
    InputGuardrailOrchestrationConfig,
    RuntimeGuardrailPenaltyConfig,
    RuntimePolicyConfig,
)
from rag_eng.aurora_retry import (
    INTERACTIVE_RETRY_PROFILE,
    RELIABLE_RETRY_PROFILE,
    connect_postgres_with_retry,
    get_retry_profile,
)


@dataclass
class _FakePsycopg:
    outcomes: list[object]
    calls: list[tuple[str, int]]

    def connect(self, database_url: str, *, connect_timeout: int):
        self.calls.append((database_url, connect_timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_get_retry_profile_returns_expected_defaults() -> None:
    assert get_retry_profile("interactive") == INTERACTIVE_RETRY_PROFILE
    assert get_retry_profile("reliable") == RELIABLE_RETRY_PROFILE


def test_get_retry_profile_prefers_runtime_policy_config(monkeypatch) -> None:
    runtime_policy = RuntimePolicyConfig(
        input_guardrail_orchestration=InputGuardrailOrchestrationConfig(
            enabled=True,
            warning_threshold=1,
            end_chat_threshold=2,
            session_termination_enabled=True,
            penalty=RuntimeGuardrailPenaltyConfig(enabled=True, amount=5),
        ),
        aurora_retry=AuroraRetryConfig(
            interactive=AuroraRetryProfileConfig(
                connect_timeout_seconds=9,
                max_attempts=2,
                retry_sleep_seconds=0.25,
            ),
            reliable=AuroraRetryProfileConfig(
                connect_timeout_seconds=11,
                max_attempts=4,
                retry_sleep_seconds=0.5,
            ),
        ),
        chat_log_export=ChatLogExportConfig(prefix="eval/chat_logs/turn_logs"),
    )

    monkeypatch.setattr(
        "rag_eng.aurora_retry.get_runtime_policy_config",
        lambda: runtime_policy,
    )

    interactive = get_retry_profile("interactive")
    reliable = get_retry_profile("reliable")

    assert interactive.connect_timeout_seconds == 9
    assert interactive.max_attempts == 2
    assert interactive.retry_sleep_seconds == 0.25
    assert reliable.connect_timeout_seconds == 11
    assert reliable.max_attempts == 4
    assert reliable.retry_sleep_seconds == 0.5


def test_connect_postgres_with_retry_uses_retries_until_success(monkeypatch) -> None:
    sleep_calls: list[float] = []
    fake_psycopg = _FakePsycopg(
        outcomes=[
            RuntimeError("connection timeout expired"),
            RuntimeError("connection timeout expired"),
            object(),
        ],
        calls=[],
    )

    monkeypatch.setattr(
        "rag_eng.aurora_retry._load_psycopg_module",
        lambda: fake_psycopg,
    )

    connection = connect_postgres_with_retry(
        "postgresql://example",
        profile="interactive",
        sleep_func=sleep_calls.append,
    )

    assert connection is not None
    assert fake_psycopg.calls == [
        ("postgresql://example", 3),
        ("postgresql://example", 3),
        ("postgresql://example", 3),
    ]
    assert sleep_calls == [1.0, 1.0]


def test_connect_postgres_with_retry_reraises_last_error(monkeypatch) -> None:
    fake_psycopg = _FakePsycopg(
        outcomes=[RuntimeError("boom")] * 5,
        calls=[],
    )

    monkeypatch.setattr(
        "rag_eng.aurora_retry._load_psycopg_module",
        lambda: fake_psycopg,
    )

    with pytest.raises(RuntimeError, match="boom"):
        connect_postgres_with_retry(
            "postgresql://example",
            profile="interactive",
            sleep_func=lambda _seconds: None,
        )

    assert len(fake_psycopg.calls) == 5
