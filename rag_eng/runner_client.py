"""Invoke the C++ sandbox runner locally via Docker."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from rag_eng.config import Settings, get_settings
from rag_eng.run_schemas import RunResult


class RunnerError(RuntimeError):
    pass


RUNNER_IMAGE_DEFAULT = "codingrabbit-cpp-runner:0.1"
HOST_DOCKER_TIMEOUT_SEC = 12


def _prepare_job_dir_for_container(job_dir: Path) -> None:
    """Allow the non-root runner user (uid 10001) to read/write bind-mounted /job."""
    os.chmod(job_dir, 0o777)
    for path in job_dir.iterdir():
        os.chmod(path, 0o666)


def _docker_run(job_dir: Path, image: str) -> None:
    cmd = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--cpus",
        "1",
        "--memory",
        "256m",
        "--memory-swap",
        "256m",
        "--pids-limit",
        "64",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--tmpfs",
        "/workspace:rw,nosuid,nodev,size=64m,mode=1777",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=16m,mode=1777",
        "--mount",
        f"type=bind,src={job_dir},dst=/job",
        image,
    ]

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=HOST_DOCKER_TIMEOUT_SEC,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RunnerError("Sandbox host timeout. The job was terminated.") from exc

    if proc.returncode != 0 and not (job_dir / "result.json").exists():
        detail = proc.stderr.strip() or proc.stdout.strip() or "unknown docker error"
        raise RunnerError(f"Docker runner failed: {detail}")


def _subprocess_run(job_dir: Path) -> None:
    """Run the runner script directly (tests / dev without Docker)."""
    import os
    import sys

    repo_root = Path(__file__).resolve().parent.parent
    script = repo_root / "runner" / "run_cpp.py"
    workspace = job_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["JOB_DIR"] = str(job_dir)
    env["RUNNER_WORKSPACE"] = str(workspace)

    proc = subprocess.run(
        [sys.executable, str(script)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=HOST_DOCKER_TIMEOUT_SEC,
        check=False,
    )
    if proc.returncode != 0 and not (job_dir / "result.json").exists():
        detail = proc.stderr.strip() or proc.stdout.strip() or "unknown runner error"
        raise RunnerError(f"Subprocess runner failed: {detail}")


def run_cpp_job(payload: dict[str, Any], settings: Settings | None = None) -> RunResult:
    """Compile (and optionally run) student C++ in the sandbox."""
    settings = settings or get_settings()
    job_id = payload.get("job_id") or f"job_{uuid.uuid4().hex}"

    with tempfile.TemporaryDirectory(prefix=f"codingrabbit_{job_id}_") as tmp:
        job_dir = Path(tmp)
        (job_dir / "request.json").write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

        if settings.runner_mode == "docker":
            _prepare_job_dir_for_container(job_dir)

        if settings.runner_mode == "subprocess":
            _subprocess_run(job_dir)
        else:
            _docker_run(job_dir, settings.runner_image)

        result_path = job_dir / "result.json"
        if not result_path.exists():
            raise RunnerError("Runner did not produce result.json")

        data = json.loads(result_path.read_text(encoding="utf-8"))
        return RunResult.model_validate(data)
