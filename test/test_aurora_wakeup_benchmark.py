from __future__ import annotations

import json
import os
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import pytest
from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class WakeupRunResult:
    run_index: int
    idle_seconds: int
    connect_timeout_seconds: int
    poll_interval_seconds: float
    started_at: str
    connected_at: str
    elapsed_seconds: float
    attempts: int
    last_error: str | None


def _resolve_database_url() -> str:
    database_url = (
        os.getenv("COURSE_REGISTRY_DATABASE_URL", "").strip()
        or os.getenv("DATABASE_URL", "").strip()
    )
    if not database_url:
        raise RuntimeError(
            "COURSE_REGISTRY_DATABASE_URL or DATABASE_URL must be set for the Aurora wake-up benchmark."
        )
    return database_url


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _summarize_results(results: list[WakeupRunResult]) -> dict[str, object]:
    if not results:
        raise ValueError("At least one wake-up run result is required.")

    elapsed_seconds = [result.elapsed_seconds for result in results]
    return {
        "runs_completed": len(results),
        "min_elapsed_seconds": round(min(elapsed_seconds), 3),
        "max_elapsed_seconds": round(max(elapsed_seconds), 3),
        "avg_elapsed_seconds": round(statistics.fmean(elapsed_seconds), 3),
        "median_elapsed_seconds": round(statistics.median(elapsed_seconds), 3),
        "runs": [asdict(result) for result in results],
    }


def _wait_for_aurora_wakeup(
    *,
    database_url: str,
    run_index: int,
    idle_seconds: int,
    connect_timeout_seconds: int,
    poll_interval_seconds: float,
    max_wait_seconds: int,
) -> WakeupRunResult:
    psycopg = pytest.importorskip("psycopg")

    print(
        f"[aurora-wakeup] run={run_index} sleeping {idle_seconds}s to allow auto-pause"
    )
    time.sleep(idle_seconds)

    started_at = _utc_now()
    deadline = time.monotonic() + max_wait_seconds
    attempts = 0
    last_error: str | None = None

    while True:
        attempts += 1
        try:
            with psycopg.connect(
                database_url,
                connect_timeout=connect_timeout_seconds,
            ) as connection:
                connection.autocommit = True
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
        except Exception as exc:
            last_error = str(exc)
            if time.monotonic() >= deadline:
                raise AssertionError(
                    "Aurora did not wake up before the benchmark deadline.\n"
                    f"run={run_index} attempts={attempts} last_error={last_error}"
                ) from exc
            time.sleep(poll_interval_seconds)
            continue

        connected_at = _utc_now()
        elapsed_seconds = (connected_at - started_at).total_seconds()
        return WakeupRunResult(
            run_index=run_index,
            idle_seconds=idle_seconds,
            connect_timeout_seconds=connect_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            started_at=started_at.isoformat(),
            connected_at=connected_at.isoformat(),
            elapsed_seconds=round(elapsed_seconds, 3),
            attempts=attempts,
            last_error=last_error,
        )


def test_resolve_database_url_prefers_course_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COURSE_REGISTRY_DATABASE_URL", "postgresql://primary")
    monkeypatch.setenv("DATABASE_URL", "postgresql://fallback")

    assert _resolve_database_url() == "postgresql://primary"


def test_summarize_results_computes_expected_statistics() -> None:
    results = [
        WakeupRunResult(
            run_index=1,
            idle_seconds=400,
            connect_timeout_seconds=3,
            poll_interval_seconds=1.0,
            started_at="2026-06-23T00:00:00+00:00",
            connected_at="2026-06-23T00:00:12+00:00",
            elapsed_seconds=12.0,
            attempts=4,
            last_error=None,
        ),
        WakeupRunResult(
            run_index=2,
            idle_seconds=400,
            connect_timeout_seconds=3,
            poll_interval_seconds=1.0,
            started_at="2026-06-23T00:10:00+00:00",
            connected_at="2026-06-23T00:10:18+00:00",
            elapsed_seconds=18.0,
            attempts=6,
            last_error="connection timeout expired",
        ),
    ]

    summary = _summarize_results(results)

    assert summary["runs_completed"] == 2
    assert summary["min_elapsed_seconds"] == 12.0
    assert summary["max_elapsed_seconds"] == 18.0
    assert summary["avg_elapsed_seconds"] == 15.0
    assert summary["median_elapsed_seconds"] == 15.0


@pytest.mark.aurora_wakeup
def test_aurora_wakeup_benchmark(pytestconfig: pytest.Config) -> None:
    database_url = _resolve_database_url()
    runs = pytestconfig.getoption("--aurora-wakeup-runs")
    idle_seconds = pytestconfig.getoption("--aurora-wakeup-idle-seconds")
    connect_timeout_seconds = pytestconfig.getoption(
        "--aurora-wakeup-connect-timeout-seconds"
    )
    poll_interval_seconds = pytestconfig.getoption(
        "--aurora-wakeup-poll-interval-seconds"
    )
    max_wait_seconds = pytestconfig.getoption("--aurora-wakeup-max-wait-seconds")

    if runs < 1:
        raise ValueError("--aurora-wakeup-runs must be at least 1.")
    if idle_seconds < 0:
        raise ValueError("--aurora-wakeup-idle-seconds must be non-negative.")
    if connect_timeout_seconds < 1:
        raise ValueError(
            "--aurora-wakeup-connect-timeout-seconds must be at least 1."
        )
    if poll_interval_seconds <= 0:
        raise ValueError(
            "--aurora-wakeup-poll-interval-seconds must be greater than 0."
        )
    if max_wait_seconds < 1:
        raise ValueError("--aurora-wakeup-max-wait-seconds must be at least 1.")

    results: list[WakeupRunResult] = []
    for run_index in range(1, runs + 1):
        result = _wait_for_aurora_wakeup(
            database_url=database_url,
            run_index=run_index,
            idle_seconds=idle_seconds,
            connect_timeout_seconds=connect_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            max_wait_seconds=max_wait_seconds,
        )
        results.append(result)
        print(
            "[aurora-wakeup] "
            f"run={run_index} elapsed={result.elapsed_seconds}s attempts={result.attempts}"
        )

    summary = _summarize_results(results)
    print(json.dumps(summary, indent=2))

    assert summary["runs_completed"] == runs
