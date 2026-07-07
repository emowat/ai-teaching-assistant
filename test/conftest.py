from __future__ import annotations

import os
import pytest

os.environ["GUARDRAILS_LOG_ONLY"] = "false"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-aurora-wakeup-benchmark",
        action="store_true",
        default=False,
        help="Run the live Aurora wake-up benchmark test.",
    )
    parser.addoption(
        "--aurora-wakeup-runs",
        action="store",
        type=int,
        default=1,
        help="Number of wake-up benchmark runs to execute.",
    )
    parser.addoption(
        "--aurora-wakeup-idle-seconds",
        action="store",
        type=int,
        default=400,
        help="Idle wait before each run to allow Aurora to auto-pause.",
    )
    parser.addoption(
        "--aurora-wakeup-connect-timeout-seconds",
        action="store",
        type=int,
        default=3,
        help="Per-attempt PostgreSQL connect timeout during wake-up probing.",
    )
    parser.addoption(
        "--aurora-wakeup-poll-interval-seconds",
        action="store",
        type=float,
        default=1.0,
        help="Delay between connection attempts while waiting for Aurora to wake up.",
    )
    parser.addoption(
        "--aurora-wakeup-max-wait-seconds",
        action="store",
        type=int,
        default=180,
        help="Maximum total wait for one Aurora wake-up run before failing.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "aurora_wakeup: live Aurora wake-up benchmark that must be explicitly enabled.",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    if config.getoption("--run-aurora-wakeup-benchmark"):
        return

    skip_marker = pytest.mark.skip(
        reason="use --run-aurora-wakeup-benchmark to run the Aurora wake-up benchmark",
    )
    for item in items:
        if "aurora_wakeup" in item.keywords:
            item.add_marker(skip_marker)
