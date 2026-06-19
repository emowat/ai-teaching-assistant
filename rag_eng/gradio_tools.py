"""Admin Gradio helpers: SageMaker status, direct invoke, and pipeline chat."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rag_eng.config import Settings, get_settings
from rag_eng.inference import _invoke_sagemaker
from rag_eng.service import run_chat

_DEPLOY_DIR = Path(__file__).resolve().parent.parent / "deploy"


@dataclass(frozen=True)
class TrafficLight:
    label: str
    state: str  # ok | warn | error | unknown
    detail: str


@dataclass(frozen=True)
class SageMakerStatus:
    endpoint_name: str
    endpoint_status: str
    instance_count: int | None
    desired_count: int | None
    use_sagemaker: bool
    inference_backend: str
    max_model_len: str | None
    lights: list[TrafficLight]
    summary: str
    checked_at: str


def _light_state(status: str) -> str:
    normalized = status.lower()
    if normalized in {"inservice", "ok", "ready", "true"}:
        return "ok"
    if normalized in {"creating", "updating", "rollingback", "warn", "false", "scaled_to_zero"}:
        return "warn"
    if normalized in {"failed", "notfound", "error", "missing"}:
        return "error"
    return "unknown"


def _load_deploy_config():
    if str(_DEPLOY_DIR) not in sys.path:
        sys.path.insert(0, str(_DEPLOY_DIR))
    from deployment_config import load_deploy_config

    return load_deploy_config()


def _boto_session(settings: Settings):
    import boto3

    return boto3.Session(
        profile_name=settings.aws_profile or None,
        region_name=settings.aws_region,
    )


def fetch_sagemaker_status(settings: Settings | None = None) -> SageMakerStatus:
    """Collect endpoint status for admin traffic lights."""
    settings = settings or get_settings()
    endpoint_name = settings.sagemaker_endpoint
    lights: list[TrafficLight] = []
    endpoint_status = "NotFound"
    instance_count: int | None = None
    desired_count: int | None = None
    max_model_len: str | None = None

    try:
        deploy_cfg = _load_deploy_config()
        max_model_len = deploy_cfg.sagemaker.container.extra_env.get("SM_VLLM_MAX_MODEL_LEN")
        lights.append(
            TrafficLight(
                "Deploy config",
                "ok",
                str(deploy_cfg.config_path),
            )
        )
    except Exception as exc:
        lights.append(
            TrafficLight("Deploy config", "warn", f"Could not load deployment.yaml: {exc}")
        )

    try:
        sm = _boto_session(settings).client("sagemaker")
        desc = sm.describe_endpoint(EndpointName=endpoint_name)
        endpoint_status = desc.get("EndpointStatus", "Unknown")
        variant = (desc.get("ProductionVariants") or [{}])[0]
        instance_count = variant.get("CurrentInstanceCount")
        desired_count = variant.get("DesiredInstanceCount")
    except Exception as exc:
        err = str(exc)
        if "Could not find" in err or "ValidationException" in err:
            endpoint_status = "NotFound"
        lights.append(TrafficLight("AWS describe_endpoint", "error", err))

    lights.extend(
        [
            TrafficLight(
                "Endpoint",
                _light_state(endpoint_status),
                f"{endpoint_name} — {endpoint_status}",
            ),
            TrafficLight(
                "GPU instances",
                "ok"
                if instance_count and instance_count > 0
                else "warn"
                if endpoint_status == "InService"
                else "unknown",
                "scaled to zero (cold start on next request)"
                if instance_count == 0
                else f"{instance_count} running (desired {desired_count})"
                if instance_count is not None
                else "unknown",
            ),
            TrafficLight(
                "rag_eng routing",
                _light_state("true" if settings.use_sagemaker else "false"),
                "USE_SAGEMAKER=true"
                if settings.use_sagemaker
                else "USE_SAGEMAKER=false (Ollama/local)",
            ),
            TrafficLight(
                "Inference backend",
                "ok",
                settings.sagemaker_inference_backend,
            ),
        ]
    )

    if max_model_len:
        lights.append(
            TrafficLight(
                "vLLM max_model_len",
                "ok",
                f"{max_model_len} tokens (deploy/deployment.yaml)",
            )
        )

    summary = (
        f"Endpoint {endpoint_name} is {endpoint_status}."
        if endpoint_status != "NotFound"
        else f"Endpoint {endpoint_name} was not found in {settings.aws_region}."
    )
    return SageMakerStatus(
        endpoint_name=endpoint_name,
        endpoint_status=endpoint_status,
        instance_count=instance_count,
        desired_count=desired_count,
        use_sagemaker=settings.use_sagemaker,
        inference_backend=settings.sagemaker_inference_backend,
        max_model_len=max_model_len,
        lights=lights,
        summary=summary,
        checked_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    )


def format_traffic_lights_html(status: SageMakerStatus) -> str:
    """Render traffic lights as HTML for Gradio."""
    colors = {
        "ok": "#22c55e",
        "warn": "#eab308",
        "error": "#ef4444",
        "unknown": "#94a3b8",
    }
    rows = []
    for light in status.lights:
        color = colors.get(light.state, colors["unknown"])
        rows.append(
            f"""
            <div style="display:flex;align-items:center;gap:10px;margin:8px 0;">
              <span style="width:14px;height:14px;border-radius:50%;background:{color};
                display:inline-block;box-shadow:0 0 6px {color};"></span>
              <div>
                <div style="font-weight:600;">{light.label}</div>
                <div style="font-size:12px;color:#64748b;">{light.detail}</div>
              </div>
            </div>
            """
        )
    return (
        f"<div style='font-family:system-ui,sans-serif;'>"
        f"<p><strong>{status.summary}</strong></p>"
        f"<p style='font-size:12px;color:#64748b;'>Checked {status.checked_at}</p>"
        f"{''.join(rows)}</div>"
    )


def invoke_sagemaker_direct(prompt: str, settings: Settings | None = None) -> tuple[str, str]:
    """Smoke-test the async endpoint (deploy invoke style)."""
    settings = settings or get_settings()
    prompt = (prompt or "").strip()
    if not prompt:
        return "", "Enter a prompt first."

    try:
        deploy_cfg = _load_deploy_config()
        smoke = deploy_cfg.inference_smoke_test
        messages = [
            {"role": "system", "content": smoke.system_message},
            {"role": "user", "content": prompt},
        ]
    except Exception as exc:
        return "", f"Failed to load deploy config: {exc}"

    started = time.time()
    try:
        text = asyncio.run(_invoke_sagemaker(messages, settings))
    except Exception as exc:
        elapsed = time.time() - started
        return "", f"Invoke failed after {elapsed:.1f}s: {exc}"

    elapsed = time.time() - started
    return text, f"Completed in {elapsed:.1f}s via {settings.sagemaker_endpoint}"


def build_extension_user_message(
    *,
    mode: str,
    week: int,
    code_raw: str,
    terminal_output: str,
    student_message: str,
) -> str:
    """Format a user message like the VS Code extension."""
    return (
        f"Mode: {mode}\n"
        f"Week: {week}\n"
        f"[Code_Context]\n{code_raw}\n"
        f"[Terminal_Context]\n{terminal_output}\n"
        f"[Student_Question]\n{student_message}"
    )


async def _pipeline_chat_async(
    student_message: str,
    code_raw: str,
    terminal_output: str,
    week: int,
    mode: str,
    settings: Settings,
    course_id: str | None = None,
    session_id: str | None = None,
    request_id: str | None = None,
    turn_id: str | None = None,
    section_id: str | None = None,
    result_count: int | None = None,
    rerank_strategy: str | None = None,
) -> dict[str, Any]:
    content = build_extension_user_message(
        mode=mode,
        week=int(week),
        code_raw=code_raw or "",
        terminal_output=terminal_output or "",
        student_message=student_message or "",
    )
    return await run_chat(
        messages=[{"role": "user", "content": content}],
        model_name="codingrabbit",
        settings=settings,
        stream=False,
        course_id=(course_id or "").strip() or None,
        session_id=(session_id or "").strip() or None,
        request_id=(request_id or "").strip() or None,
        turn_id=(turn_id or "").strip() or None,
        section_id=(section_id or "").strip() or None,
        result_count=result_count,
        rerank_strategy=(rerank_strategy or "").strip() or None,
    )


def invoke_pipeline_chat(
    student_message: str,
    code_raw: str,
    terminal_output: str,
    week: int,
    mode: str,
    course_id: str | None = None,
    session_id: str | None = None,
    request_id: str | None = None,
    turn_id: str | None = None,
    section_id: str | None = None,
    result_count: int | None = None,
    rerank_strategy: str | None = None,
    settings: Settings | None = None,
) -> tuple[str, str, str]:
    """Run the full RAG + inference pipeline (POST /api/chat equivalent)."""
    settings = settings or get_settings()
    if not (student_message or "").strip():
        return "", "", "Enter a student question."

    route = (
        f"SageMaker ({settings.sagemaker_endpoint})"
        if settings.use_sagemaker
        else f"Ollama ({settings.ollama_url})"
    )
    started = time.time()
    try:
        result = asyncio.run(
            _pipeline_chat_async(
                student_message,
                code_raw,
                terminal_output,
                int(week),
                mode,
                settings,
                course_id,
                session_id,
                request_id,
                turn_id,
                section_id,
                result_count,
                rerank_strategy,
            )
        )
    except Exception as exc:
        elapsed = time.time() - started
        return "", "", f"Pipeline failed after {elapsed:.1f}s: {exc}"

    elapsed = time.time() - started
    if isinstance(result, dict):
        content = (result.get("message") or {}).get("content", "")
        if not content and "content" in result:
            content = str(result.get("content", ""))
        trace_summary_parts = [
            f"session={result.get('session_id')}" if result.get("session_id") else None,
            f"request={result.get('request_id')}" if result.get("request_id") else None,
            f"turn={result.get('turn_id')}" if result.get("turn_id") else None,
        ]
        trace_summary = " · ".join(part for part in trace_summary_parts if part)
        meta = (
            f"Completed in {elapsed:.1f}s · route: {route} · "
            f"USE_SAGEMAKER={settings.use_sagemaker}"
        )
        if trace_summary:
            meta = f"{meta} · {trace_summary}"
        if result_count is not None:
            meta = f"{meta} · k={int(result_count)}"
        if rerank_strategy:
            meta = f"{meta} · rerank={rerank_strategy}"
        return content, json.dumps(result, indent=2), meta
    return str(result), "", f"Unexpected result type after {elapsed:.1f}s"
