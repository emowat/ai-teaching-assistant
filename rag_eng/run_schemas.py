"""Schemas for the C++ compile/run sandbox."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CommandResult(BaseModel):
    success: bool
    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    timed_out: bool = False


class RunSummary(BaseModel):
    compile_failed: bool
    passed: int = 0
    failed: int = 0


class RunResult(BaseModel):
    compile: CommandResult
    run: CommandResult | None = None
    tests: list[dict] = Field(default_factory=list)
    summary: RunSummary


class CompileRequest(BaseModel):
    files: dict[str, str]
    entrypoint: str = "main.cpp"
    mode: Literal["compile", "sample"] = "compile"
    stdin: str = ""
    session_id: str | None = None


class CompileResponse(BaseModel):
    job_id: str
    status: Literal["completed", "failed"]
    result: RunResult | None = None
    message: str = ""
