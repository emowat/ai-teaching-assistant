"""Compile and optionally run C++ inside an ephemeral workspace."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

JOB_DIR = Path(os.environ.get("JOB_DIR", "/job"))
WORKSPACE = Path(os.environ.get("RUNNER_WORKSPACE", "/workspace"))
RESULT_FILE = JOB_DIR / "result.json"

MAX_OUTPUT_BYTES = 20_000
COMPILE_TIMEOUT_SEC = 5
RUN_TIMEOUT_SEC = 3

ALLOWED_EXTENSIONS = {".cpp", ".cc", ".cxx", ".h", ".hpp", ".txt"}


def safe_rel_path(name: str) -> Path:
    path = Path(name)

    if path.is_absolute():
        raise ValueError(f"Absolute paths are not allowed: {name}")

    if ".." in path.parts:
        raise ValueError(f"Parent traversal is not allowed: {name}")

    if path.suffix not in ALLOWED_EXTENSIONS:
        raise ValueError(f"File extension not allowed: {name}")

    return path


def truncate_output(value: str) -> str:
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) <= MAX_OUTPUT_BYTES:
        return value

    truncated = encoded[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
    return truncated + "\n...[output truncated]"


def run_command(
    cmd: list[str],
    timeout_sec: int,
    stdin: str | None = None,
    cwd: Path | None = None,
) -> dict[str, Any]:
    started = time.time()
    workdir = cwd or WORKSPACE

    try:
        proc = subprocess.run(
            cmd,
            input=stdin,
            text=True,
            cwd=str(workdir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_sec,
        )

        return {
            "success": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": truncate_output(proc.stdout),
            "stderr": truncate_output(proc.stderr),
            "duration_ms": int((time.time() - started) * 1000),
            "timed_out": False,
        }

    except subprocess.TimeoutExpired as exc:
        return {
            "success": False,
            "exit_code": None,
            "stdout": truncate_output(exc.stdout or ""),
            "stderr": truncate_output((exc.stderr or "") + "\n[timeout]"),
            "duration_ms": int((time.time() - started) * 1000),
            "timed_out": True,
        }


def write_files(files: dict[str, str], workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)

    # Do not rmtree the workspace root — it may be a Docker tmpfs mount point.
    for child in workspace.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    for filename, content in files.items():
        rel = safe_rel_path(filename)
        target = workspace / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def execute_cpp_job(request: dict[str, Any], workspace: Path) -> dict[str, Any]:
    files = request["files"]
    entrypoint = request.get("entrypoint", "main.cpp")
    mode = request.get("mode", "compile")
    stdin = request.get("stdin", "")

    write_files(files, workspace)

    entrypoint_path = safe_rel_path(entrypoint)
    binary_path = workspace / "program.out"

    compile_cmd = [
        "g++",
        "-std=c++17",
        "-Wall",
        "-Wextra",
        "-pedantic",
        "-O0",
        str(workspace / entrypoint_path),
        "-o",
        str(binary_path),
    ]

    compile_result = run_command(
        compile_cmd,
        timeout_sec=COMPILE_TIMEOUT_SEC,
        cwd=workspace,
    )

    result: dict[str, Any] = {
        "compile": compile_result,
        "run": None,
        "tests": [],
        "summary": {
            "compile_failed": not compile_result["success"],
            "passed": 0,
            "failed": 0,
        },
    }

    if compile_result["success"] and mode in {"sample", "test"}:
        run_result = run_command(
            [str(binary_path)],
            timeout_sec=RUN_TIMEOUT_SEC,
            stdin=stdin,
            cwd=workspace,
        )
        result["run"] = run_result

    return result


def main() -> None:
    request_path = JOB_DIR / "request.json"

    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        result = execute_cpp_job(request, WORKSPACE)
        RESULT_FILE.write_text(json.dumps(result, indent=2), encoding="utf-8")

    except Exception as exc:
        failure = {
            "compile": {
                "success": False,
                "exit_code": None,
                "stdout": "",
                "stderr": f"Runner internal error: {type(exc).__name__}: {exc}",
                "duration_ms": 0,
                "timed_out": False,
            },
            "run": None,
            "tests": [],
            "summary": {
                "compile_failed": True,
                "passed": 0,
                "failed": 0,
            },
        }
        RESULT_FILE.write_text(json.dumps(failure, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
