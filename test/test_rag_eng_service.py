from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from rag_eng.api import create_app
from rag_eng.service import _extract_chat_context


def test_extract_chat_context_defaults_week_and_empty_strings() -> None:
    ctx = _extract_chat_context(
        [{"role": "user", "content": "Why does my pointer segfault?"}]
    )

    assert ctx["student_message"] == "Why does my pointer segfault?"
    assert ctx["code_raw"] == ""
    assert ctx["terminal_output"] == ""
    assert ctx["week"] == 1
    assert ctx["mode"] == "Homework Assist"


def test_extract_chat_context_parses_extension_blocks() -> None:
    content = """[State_Tracking]
Mode: Study Assist
[Code_Context]
int* p;
[Terminal_Context]
Segmentation fault
Week: 4

[Student_Question]
Why does my pointer segfault?"""

    ctx = _extract_chat_context([{"role": "user", "content": content}])

    assert ctx["student_message"] == "Why does my pointer segfault?"
    assert "int* p" in ctx["code_raw"]
    assert "Segmentation fault" in ctx["terminal_output"]
    assert ctx["week"] == 4
    assert ctx["mode"] == "Study Assist"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def test_chat_endpoint_accepts_simple_message(monkeypatch, client: TestClient) -> None:
    async def fake_run_chat(messages, model_name, settings, stream=False):
        assert messages[0]["role"] == "user"
        return {"message": {"content": "Try checking whether the pointer is initialized."}}

    monkeypatch.setattr("rag_eng.api.run_chat", fake_run_chat)

    response = client.post(
        "/api/chat",
        json={
            "model": "codingrabbit",
            "messages": [{"role": "user", "content": "Why does my pointer segfault?"}],
        },
    )

    assert response.status_code == 200
    assert "pointer" in response.json()["message"]["content"].lower()
