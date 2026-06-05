"""Internal Gradio UI for the `rag_eng` FastAPI service."""

from __future__ import annotations

import json
from urllib import error, request

import gradio as gr

from rag.schemas import AssistMode

from rag_eng.config import Settings, get_settings


def _post_json(url: str, payload: dict) -> dict:
    """Send a JSON request to the FastAPI backend."""
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _query_api(
    student_message: str,
    code_raw: str,
    terminal_output: str,
    week: int,
    mode: str,
    result_count: int,
    has_pointer: bool,
    has_reference: bool,
    has_loop: bool,
    has_new: bool,
    has_delete: bool,
    has_malloc: bool,
    has_free: bool,
    has_recursion: bool,
) -> tuple[str, str, str, str]:
    """Call the FastAPI `/query` endpoint and format its response.

    The selected `result_count` is forwarded to the backend so the user can
    control the final number of returned chunks without changing code.
    """
    settings = get_settings()
    payload = {
        "student_message": student_message,
        "code_raw": code_raw,
        "terminal_output": terminal_output,
        "exit_code": 0,
        "week": int(week),
        "mode": mode,
        "result_count": int(result_count),
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
            "Request completed successfully.",
        )
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return "", "", "", f"HTTP {exc.code}: {detail}"
    except Exception as exc:
        return "", "", "", f"Request failed: {exc}"


def build_gradio_app(settings: Settings | None = None) -> gr.Blocks:
    """Build the internal Gradio app mounted under the FastAPI server."""
    runtime = settings or get_settings()

    with gr.Blocks(title="rag_eng Query Console") as demo:
        gr.Markdown(
            """
            # `rag_eng` Query Console
            Internal UI for querying the FastAPI-backed capstone RAG service.
            """
        )
        with gr.Row():
            student_message = gr.Textbox(
                label="Student Message",
                placeholder="Why does my program crash when I dereference this pointer?",
                lines=4,
            )
            code_raw = gr.Textbox(
                label="Code Snippet",
                placeholder="int* p; *p = 5;",
                lines=10,
            )
        terminal_output = gr.Textbox(
            label="Terminal Output",
            placeholder="Segmentation fault (core dumped)",
            lines=4,
        )
        with gr.Row():
            week = gr.Slider(
                label="Course Week",
                minimum=1,
                maximum=8,
                value=3,
                step=1,
            )
            mode = gr.Dropdown(
                label="Assist Mode",
                choices=[item.value for item in AssistMode],
                value=AssistMode.HOMEWORK_ASSIST.value,
            )
            # User-facing control for the final post-rerank result count.
            result_count = gr.Slider(
                label="Number of Results",
                minimum=1,
                maximum=10,
                value=5,
                step=1,
            )
        with gr.Accordion("AST Flags", open=False):
            with gr.Row():
                has_pointer = gr.Checkbox(label="Has Pointer", value=True)
                has_reference = gr.Checkbox(label="Has Reference", value=False)
                has_loop = gr.Checkbox(label="Has Loop", value=False)
                has_new = gr.Checkbox(label="Has new", value=False)
            with gr.Row():
                has_delete = gr.Checkbox(label="Has delete", value=False)
                has_malloc = gr.Checkbox(label="Has malloc", value=False)
                has_free = gr.Checkbox(label="Has free", value=False)
                has_recursion = gr.Checkbox(label="Has Recursion", value=False)

        submit = gr.Button("Query RAG", variant="primary")
        answer = gr.Textbox(label="TA Answer", lines=4)
        retrieval_result = gr.Code(label="Retrieved Documents", language="json")
        formatted_context = gr.Textbox(label="Formatted Context", lines=16)
        status = gr.Textbox(
            label="Status",
            value=f"FastAPI backend target: {runtime.api_base_url}",
            interactive=False,
        )

        submit.click(
            fn=_query_api,
            inputs=[
                student_message,
                code_raw,
                terminal_output,
                week,
                mode,
                result_count,
                has_pointer,
                has_reference,
                has_loop,
                has_new,
                has_delete,
                has_malloc,
                has_free,
                has_recursion,
            ],
            outputs=[answer, retrieval_result, formatted_context, status],
        )

    return demo
