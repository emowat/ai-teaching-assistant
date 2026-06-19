"""Internal Gradio UI for the `rag_eng` FastAPI service."""

from __future__ import annotations

import json
from typing import Any
from urllib import error, request

import gradio as gr

from rag.schemas import AssistMode

from rag_eng.config import Settings, get_settings
from rag_eng.gradio_tools import (
    fetch_sagemaker_status,
    format_traffic_lights_html,
    invoke_guardrail_review,
    invoke_pipeline_chat,
    invoke_sagemaker_direct,
)
from rag_eng.schemas import RERANK_STRATEGY_CHOICES

RETRIEVAL_PRESET_CUSTOM = "Custom (manual controls)"
RETRIEVAL_PRESET_CHOICES: tuple[str, ...] = (
    RETRIEVAL_PRESET_CUSTOM,
    "Experiment baseline (K=8, similarity)",
    "MMR balanced (K=8, lambda=0.5)",
    "MMR relevance (K=8, lambda=0.7)",
    "MMR focus (K=8, lambda=0.9)",
)
RETRIEVAL_PRESET_CONFIGS: dict[str, tuple[int, str]] = {
    "Experiment baseline (K=8, similarity)": (8, "similarity"),
    "MMR balanced (K=8, lambda=0.5)": (8, "mmr_0.5"),
    "MMR relevance (K=8, lambda=0.7)": (8, "mmr_0.7"),
    "MMR focus (K=8, lambda=0.9)": (8, "mmr_0.9"),
}


def _post_json(url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _resolve_retrieval_preset(
    retrieval_preset: str,
    result_count: int,
    rerank_strategy: str,
) -> tuple[int, str, str]:
    """Return the effective retrieval controls for the selected preset."""
    preset = (retrieval_preset or "").strip()
    preset_config = RETRIEVAL_PRESET_CONFIGS.get(preset)
    if preset_config is None:
        return int(result_count), rerank_strategy, RETRIEVAL_PRESET_CUSTOM
    preset_count, preset_rerank = preset_config
    return preset_count, preset_rerank, preset


def _query_api(
    student_message: str,
    code_raw: str,
    terminal_output: str,
    week: int,
    mode: str,
    retrieval_preset: str,
    result_count: int,
    rerank_strategy: str,
    has_pointer: bool,
    has_reference: bool,
    has_loop: bool,
    has_new: bool,
    has_delete: bool,
    has_malloc: bool,
    has_free: bool,
    has_recursion: bool,
) -> tuple[str, str, str, str]:
    settings = get_settings()
    effective_result_count, effective_rerank_strategy, active_preset = _resolve_retrieval_preset(
        retrieval_preset,
        result_count,
        rerank_strategy,
    )
    payload = {
        "student_message": student_message,
        "code_raw": code_raw,
        "terminal_output": terminal_output,
        "exit_code": 0,
        "week": int(week),
        "mode": mode,
        "result_count": int(effective_result_count),
        "rerank_strategy": effective_rerank_strategy,
        "ast_features": {
            "has_pointer": has_pointer,
            "has_reference": has_reference,
            "has_loop": has_loop,
            "has_new": has_new,
            "has_delete": has_delete,
            "has_malloc": has_malloc,
            "has_free": has_free,
            "has_recursion": has_recursion,
            "target_variables": [],
        },
    }
    try:
        data = _post_json(f"{settings.api_base_url}/query", payload)
        return (
            data["answer"],
            json.dumps(data["retrieval_result"], indent=2),
            data["formatted_context"],
            (
                "Request completed successfully."
                if active_preset == RETRIEVAL_PRESET_CUSTOM
                else f"Request completed successfully. Preset: {active_preset}."
            ),
        )
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return "", "", "", f"HTTP {exc.code}: {detail}"
    except Exception as exc:
        return "", "", "", f"Request failed: {exc}"


def _refresh_sagemaker_status() -> str:
    try:
        status = fetch_sagemaker_status()
        return format_traffic_lights_html(status)
    except Exception as exc:
        return f"<p style='color:#ef4444;'>Status check failed: {exc}</p>"


def _sagemaker_invoke(prompt: str) -> tuple[str, str]:
    return invoke_sagemaker_direct(prompt)


def _clear_sagemaker_request() -> tuple[str, str]:
    return (
        "",
        "Request cancelled. The prompt is still in the textbox, so you can send it again.",
    )


def _pipeline_invoke(
    student_message: str,
    code_raw: str,
    terminal_output: str,
    week: int,
    mode: str,
    retrieval_preset: str,
    result_count: int,
    rerank_strategy: str,
    course_id: str,
    session_id: str,
    request_id: str,
    turn_id: str,
    section_id: str,
) -> tuple[str, str, str]:
    effective_result_count, effective_rerank_strategy, active_preset = _resolve_retrieval_preset(
        retrieval_preset,
        result_count,
        rerank_strategy,
    )
    answer, raw, status = invoke_pipeline_chat(
        student_message,
        code_raw,
        terminal_output,
        week,
        mode,
        result_count=effective_result_count,
        rerank_strategy=effective_rerank_strategy,
        course_id=course_id,
        session_id=session_id,
        request_id=request_id,
        turn_id=turn_id,
        section_id=section_id,
    )
    if active_preset != RETRIEVAL_PRESET_CUSTOM:
        status = f"{status} · preset={active_preset}"
    return answer, raw, status


def _guardrail_invoke(
    draft_answer: str,
    student_question: str,
    student_code: str,
    conversation_history_json: str,
) -> tuple[str, str, str]:
    return invoke_guardrail_review(
        draft_answer,
        student_question,
        student_code,
        conversation_history_json,
    )


def build_gradio_app(settings: Settings | None = None) -> gr.Blocks:
    """Single Gradio app with three admin tabs, mounted once at /gradio."""
    runtime = settings or get_settings()
    route_hint = (
        f"SageMaker `{runtime.sagemaker_endpoint}`"
        if runtime.use_sagemaker
        else "Ollama (see inference_config.yaml)"
    )

    with gr.Blocks(title="Backend Diagnostic Console") as demo:
        gr.Markdown("# Backend Diagnostic Console")

        with gr.Tab("RAG Query"):
            gr.Markdown(
                "Retrieval + Cohere answer via `POST /query` — tests RAG without the LLM pipeline."
            )
            with gr.Row():
                rq_student = gr.Textbox(
                    label="Student Message",
                    placeholder="Why does my program crash when I dereference this pointer?",
                    lines=4,
                )
                rq_code = gr.Textbox(
                    label="Code Snippet",
                    placeholder="int* p; *p = 5;",
                    lines=10,
                )
            rq_terminal = gr.Textbox(
                label="Terminal Output",
                placeholder="Segmentation fault (core dumped)",
                lines=4,
            )
            with gr.Row():
                rq_week = gr.Slider(label="Course Week", minimum=1, maximum=8, value=3, step=1)
                rq_mode = gr.Dropdown(
                    label="Assist Mode",
                    choices=[item.value for item in AssistMode],
                    value=AssistMode.HOMEWORK_ASSIST.value,
                )
                rq_preset = gr.Dropdown(
                    label="Retrieval Preset",
                    choices=list(RETRIEVAL_PRESET_CHOICES),
                    value=RETRIEVAL_PRESET_CUSTOM,
                )
                rq_count = gr.Slider(
                    label="Top K / Final Results",
                    minimum=1,
                    maximum=20,
                    value=8,
                    step=1,
                )
                rq_rerank = gr.Dropdown(
                    label="Rerank Strategy",
                    choices=list(RERANK_STRATEGY_CHOICES),
                    value="similarity",
                )
            with gr.Accordion("AST Flags", open=False):
                with gr.Row():
                    rq_ptr = gr.Checkbox(label="Has Pointer", value=True)
                    rq_ref = gr.Checkbox(label="Has Reference", value=False)
                    rq_loop = gr.Checkbox(label="Has Loop", value=False)
                    rq_new = gr.Checkbox(label="Has new", value=False)
                with gr.Row():
                    rq_del = gr.Checkbox(label="Has delete", value=False)
                    rq_malloc = gr.Checkbox(label="Has malloc", value=False)
                    rq_free = gr.Checkbox(label="Has free", value=False)
                    rq_rec = gr.Checkbox(label="Has Recursion", value=False)
            rq_submit = gr.Button("Query RAG", variant="primary")
            rq_answer = gr.Textbox(label="TA Answer", lines=4)
            rq_docs = gr.Code(label="Retrieved Documents", language="json")
            rq_ctx = gr.Textbox(label="Formatted Context", lines=16)
            rq_status = gr.Textbox(
                label="Status",
                value=f"Backend: {runtime.api_base_url}",
                interactive=False,
            )
            rq_submit.click(
                fn=_query_api,
                inputs=[
                    rq_student, rq_code, rq_terminal, rq_week, rq_mode, rq_preset, rq_count,
                    rq_rerank,
                    rq_ptr, rq_ref, rq_loop, rq_new, rq_del, rq_malloc, rq_free, rq_rec,
                ],
                outputs=[rq_answer, rq_docs, rq_ctx, rq_status],
            )

        with gr.Tab("SageMaker Console"):
            gr.Markdown(
                f"Traffic lights + direct async invoke — same path as "
                f"`deploy-custom-model-to-sagemaker-ai.sh invoke`.  \n"
                f"Endpoint: **{runtime.sagemaker_endpoint}**"
            )
            sm_lights = gr.HTML(value=_refresh_sagemaker_status())
            sm_refresh = gr.Button("Refresh status", variant="secondary")
            gr.Markdown("### Direct invoke")
            sm_prompt = gr.Textbox(
                label="Prompt",
                placeholder="Why does my C++ pointer cause a segmentation fault?",
                lines=4,
            )
            with gr.Row():
                sm_invoke = gr.Button("Invoke SageMaker", variant="primary")
                sm_retry = gr.Button("Send again", variant="secondary")
                sm_cancel = gr.Button("Cancel request", variant="stop")
            sm_response = gr.Textbox(label="Model response", lines=16)
            sm_status = gr.Textbox(label="Invoke status", interactive=False)
            sm_refresh.click(fn=_refresh_sagemaker_status, outputs=sm_lights)
            sm_invoke_event = sm_invoke.click(
                fn=_sagemaker_invoke,
                inputs=sm_prompt,
                outputs=[sm_response, sm_status],
            )
            sm_retry_event = sm_retry.click(
                fn=_sagemaker_invoke,
                inputs=sm_prompt,
                outputs=[sm_response, sm_status],
            )
            sm_cancel.click(
                fn=_clear_sagemaker_request,
                cancels=[sm_invoke_event, sm_retry_event],
                outputs=[sm_response, sm_status],
            )
            gr.Markdown(
                "Use **Cancel request** to stop the active call. The prompt stays in place, "
                "so you can press **Send again** or **Invoke SageMaker** to resubmit it."
            )

        with gr.Tab("Guardrail Console"):
            gr.Markdown(
                "Direct V1 + V2 output guardrails for a draft answer.  \n"
                "Use this tab to inspect pass / log_only / replace outcomes before wiring a response into the pipeline."
            )
            gd_draft = gr.Textbox(
                label="Draft Answer",
                placeholder="Paste the candidate answer from the model here.",
                lines=10,
            )
            gd_question = gr.Textbox(
                label="Student Question",
                placeholder="Why does my pointer segfault?",
                lines=4,
            )
            gd_code = gr.Textbox(
                label="Student Code",
                placeholder="int *p;\n*p = 42;",
                lines=8,
            )
            gd_history = gr.Textbox(
                label="Conversation History (JSON list)",
                placeholder='[{"role": "user", "content": "..." }]',
                lines=6,
            )
            gd_run = gr.Button("Run guardrails", variant="primary")
            gd_final = gr.Textbox(label="Final Answer", lines=10)
            gd_raw = gr.Code(label="Raw JSON response", language="json")
            gd_status = gr.Textbox(label="Guardrail status", interactive=False)
            gd_run.click(
                fn=_guardrail_invoke,
                inputs=[gd_draft, gd_question, gd_code, gd_history],
                outputs=[gd_final, gd_raw, gd_status],
            )

        with gr.Tab("Pipeline Console"):
            gr.Markdown(
                f"Full extension-style pipeline: context extraction → RAG → prompt budget → inference → guardrails.  \n"
                f"Current route: **{route_hint}**"
            )
            with gr.Row():
                pp_question = gr.Textbox(
                    label="Student Question",
                    placeholder="Why does my pointer segfault?",
                    lines=3,
                )
                pp_code = gr.Textbox(
                    label="Code Context",
                    placeholder="int *p;\n*p = 42;",
                    lines=8,
                )
            pp_terminal = gr.Textbox(
                label="Terminal Context",
                placeholder="Segmentation fault (core dumped)",
                lines=3,
            )
            with gr.Row():
                pp_week = gr.Slider(label="Course Week", minimum=1, maximum=8, value=1, step=1)
                pp_mode = gr.Dropdown(
                    label="Assist Mode",
                    choices=[item.value for item in AssistMode],
                    value=AssistMode.HOMEWORK_ASSIST.value,
                )
                pp_preset = gr.Dropdown(
                    label="Retrieval Preset",
                    choices=list(RETRIEVAL_PRESET_CHOICES),
                    value=RETRIEVAL_PRESET_CUSTOM,
                )
                pp_result_count = gr.Slider(
                    label="Top K / Final Results",
                    minimum=1,
                    maximum=20,
                    value=8,
                    step=1,
                )
                pp_rerank = gr.Dropdown(
                    label="Rerank Strategy",
                    choices=list(RERANK_STRATEGY_CHOICES),
                    value="similarity",
                )
            with gr.Accordion("Routing and Trace Overrides", open=False):
                pp_course_id = gr.Textbox(
                    label="Course ID",
                    placeholder="mit14",
                    info="Optional explicit course route for the pipeline request.",
                )
                with gr.Row():
                    pp_session_id = gr.Textbox(
                        label="Session ID",
                        placeholder="session-123",
                    )
                    pp_request_id = gr.Textbox(
                        label="Request ID",
                        placeholder="request-123",
                    )
                with gr.Row():
                    pp_turn_id = gr.Textbox(
                        label="Turn ID",
                        placeholder="turn-123",
                    )
                    pp_section_id = gr.Textbox(
                        label="Section ID",
                        placeholder="section-1",
                    )
            pp_run = gr.Button("Run pipeline", variant="primary")
            pp_response = gr.Textbox(label="Assistant response", lines=14)
            pp_raw = gr.Code(label="Raw JSON response", language="json")
            pp_status = gr.Textbox(label="Pipeline status", interactive=False)
            pp_run.click(
                fn=_pipeline_invoke,
                inputs=[
                    pp_question,
                    pp_code,
                    pp_terminal,
                    pp_week,
                    pp_mode,
                    pp_preset,
                    pp_result_count,
                    pp_rerank,
                    pp_course_id,
                    pp_session_id,
                    pp_request_id,
                    pp_turn_id,
                    pp_section_id,
                ],
                outputs=[pp_response, pp_raw, pp_status],
            )

    return demo


def mount_gradio_consoles(app: Any) -> Any:
    """Mount the single tabbed admin console at /gradio."""
    return gr.mount_gradio_app(app, build_gradio_app(), path="/gradio")


# Keep these for any code that imports them directly (tests, etc.)
build_rag_query_app = build_gradio_app
build_sagemaker_console_app = build_gradio_app
build_pipeline_console_app = build_gradio_app
