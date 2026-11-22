"""Tests for the Playlab chat provider. All HTTP is faked; nothing reaches Playlab or Aurora."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from rag_eng import playlab_generation
from rag_eng.playlab_client import AsyncPlaylabClient, PlaylabClient, PlaylabError
from rag_eng.playlab_generation import (
    PlaylabTurn,
    build_playlab_message,
    build_session_context,
    stream_playlab_reply,
)
from rag_eng.playlab_sessions import (
    InMemoryPlaylabSessionStore,
    PlaylabConversationRef,
    set_playlab_session_store,
)
from rag_eng.schemas import AdminLlmConfigUpdate
from rag_eng.service import _generate_llm_response, run_chat
from rag.context_assembler import format_syllabus_block
from test.test_rag_eng_service import _FakeTelemetryStore, _runtime_config


def _sse(*deltas: str, error: str | None = None, junk: bool = False) -> str:
    lines = []
    if junk:
        lines += ["id: 0", "event: append", "data: {not json"]
    for i, d in enumerate(deltas):
        lines += [f"id: {i + 1}", "event: append", f"data: {json.dumps({'delta': d})}", ""]
    if error:
        lines += ["event: error", f"data: {json.dumps({'error': error, 'conversationId': 'c'})}", ""]
    return "\n".join(lines) + "\n"


class FakePlaylab:
    """In-memory stand-in for Playlab's three endpoints."""

    def __init__(self, reply=("<analysis>\n- Cognitive_Stage: 4. Debugging\n</analysis>\n", "What index does the loop end on?"),
                 variables_supported=False):
        self.reply = reply
        self.variables_supported = variables_supported
        self.conversations: dict[str, list[str]] = {}
        self.created_with: list[dict] = []
        self.sent: list[tuple[str, str]] = []
        self.fail_next: tuple[int, dict] | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer sk-pl-v1-org.test"
        path = request.url.path
        if self.fail_next:
            status, body = self.fail_next
            self.fail_next = None
            return httpx.Response(status, json=body)
        if request.method == "POST" and path.endswith("/conversations"):
            body = json.loads(request.content or b"{}")
            self.created_with.append(body)
            cid = f"conv{len(self.conversations) + 1}"
            self.conversations[cid] = []
            values = []
            if self.variables_supported and body.get("instructionVariables"):
                values = [{"name": k, "value": v} for k, v in body["instructionVariables"].items()]
            return httpx.Response(200, json={"conversation": {
                "id": cid, "provider": "anthropic", "modelName": "claude-haiku-5-5",
                "instructionVariableValues": values}})
        cid = path.split("/conversations/")[1].split("/")[0]
        if cid not in self.conversations:
            return httpx.Response(404, json={"error": "Conversation not found."})
        if request.method == "POST":
            msg = json.loads(request.content)["input"]["message"]
            self.sent.append((cid, msg))
            self.conversations[cid].append(msg)
            return httpx.Response(200, text=_sse(*self.reply), headers={"content-type": "text/plain"})
        return httpx.Response(200, json={"messages": [{"source": "user", "content": m} for m in self.conversations[cid]]})

    def sync_client(self) -> PlaylabClient:
        return PlaylabClient(api_key="sk-pl-v1-org.test", project_id="proj",
                             transport=httpx.MockTransport(self.handler))

    def async_client(self) -> AsyncPlaylabClient:
        return AsyncPlaylabClient(api_key="sk-pl-v1-org.test", project_id="proj",
                                  transport=httpx.MockTransport(self.handler))


@pytest.fixture
def fake(monkeypatch):
    server = FakePlaylab()
    monkeypatch.setattr(playlab_generation, "AsyncPlaylabClient", server.async_client)
    store = InMemoryPlaylabSessionStore()
    set_playlab_session_store(store)
    server.store = store
    yield server
    set_playlab_session_store(None)


# --------------------------------------------------------------------------- client


def test_client_create_send_list(fake):
    with fake.sync_client() as c:
        conv = c.create_conversation({"session_context": "Week: 2"})
        assert conv["id"] == "conv1" and conv["modelName"] == "claude-haiku-5-5"
        assert fake.created_with == [{"instructionVariables": {"session_context": "Week: 2"}}]
        seen = []
        result = c.send_message("conv1", "hi", on_delta=seen.append)
        assert result.text == "".join(fake.reply) and seen == list(fake.reply)
        assert c.list_messages("conv1") == [{"source": "user", "content": "hi"}]


def test_client_create_without_variables_sends_empty_body(fake):
    with fake.sync_client() as c:
        c.create_conversation()
    assert fake.created_with == [{}]


@pytest.mark.parametrize("status,body,expect", [
    (401, {"error": "Expired API key."}, "Expired API key."),
    (401, {"error": "Invalid API Key for Project."}, "Invalid API Key for Project."),
    (403, {"error": 'Quota unavailable for the "CodingRabbit" project'}, "Quota unavailable"),
    (404, {"error": "Project not found."}, "Project not found."),
    (400, {"error": {"issues": [{"path": ["input"], "message": "Required"}]}}, "schema validation failed"),
])
def test_client_error_paths(fake, status, body, expect):
    fake.fail_next = (status, body)
    with fake.sync_client() as c, pytest.raises(PlaylabError) as err:
        c.create_conversation()
    assert err.value.status == status and expect in str(err.value)


def test_send_message_errors_and_stream_error_event(fake):
    with fake.sync_client() as c:
        with pytest.raises(PlaylabError) as err:
            c.send_message("missing", "hi")
        assert err.value.conversation_not_found
        c.create_conversation()
        fake.fail_next = (400, {"error": "Message is too long for this AI model, try splitting into multiple messages."})
        with pytest.raises(PlaylabError, match="too long"):
            c.send_message("conv1", "x" * 10)

    def stream_error(request):
        return httpx.Response(200, text=_sse("partial", error="model overloaded"))
    with PlaylabClient(api_key="k", project_id="p", transport=httpx.MockTransport(stream_error)) as c:
        with pytest.raises(PlaylabError, match="model overloaded"):
            c.send_message("conv1", "hi")


def test_sse_parser_ignores_junk_and_collects_tool_events():
    def handler(request):
        text = _sse("A", "B", junk=True) + 'event: tool_call\ndata: {"messageToolCalls": [{"id": 1}]}\n'
        return httpx.Response(200, text=text)
    with PlaylabClient(api_key="k", project_id="p", transport=httpx.MockTransport(handler)) as c:
        result = c.send_message("c", "hi")
    assert result.text == "AB" and result.tool_calls == [{"id": 1}]


def test_network_failure_is_wrapped():
    def boom(request):
        raise httpx.ConnectError("no route")
    with PlaylabClient(api_key="k", project_id="p", transport=httpx.MockTransport(boom)) as c:
        with pytest.raises(PlaylabError, match="network"):
            c.create_conversation()


def test_missing_env_raises(monkeypatch):
    monkeypatch.delenv("PLAYLAB_API_KEY", raising=False)
    monkeypatch.delenv("PLAYLAB_PROJECT_ID", raising=False)
    with pytest.raises(PlaylabError, match="PLAYLAB_API_KEY"):
        PlaylabClient()


# --------------------------------------------------------------------------- generation


def _collect(turn, message, **kw) -> str:
    async def go():
        out = []
        async for chunk in stream_playlab_reply(turn, message, **kw):
            out.append(json.loads(chunk)["message"]["content"])
        return "".join(out)
    return asyncio.run(go())


def test_new_chat_creates_and_stores_conversation(fake):
    turn = PlaylabTurn(user_key="u1", session_id="s1", is_new_chat=True, session_context="Week: 2")
    assert _collect(turn, "hello") == "".join(fake.reply)
    assert fake.store.get("u1", "s1") == PlaylabConversationRef("conv1", False, "", 1)
    assert turn.meta["new_conversation"] is True and turn.meta["variables_applied"] is False
    assert turn.meta["playlab_model_name"] == "claude-haiku-5-5"


def test_follow_up_reuses_conversation_and_new_chat_replaces_it(fake):
    _collect(PlaylabTurn(user_key="u1", session_id="s1", is_new_chat=True), "turn 1")
    follow = PlaylabTurn(user_key="u1", session_id="s1", is_new_chat=False)
    _collect(follow, "How about now?")
    assert fake.sent[-1] == ("conv1", "How about now?") and follow.meta["new_conversation"] is False
    # After [END_CHAT]/reset the extension history is empty again -> fresh conversation.
    _collect(PlaylabTurn(user_key="u1", session_id="s1", is_new_chat=True), "start over")
    assert fake.sent[-1][0] == "conv2" and fake.store.get("u1", "s1").conversation_id == "conv2"


HISTORY = [
    {"role": "user", "content": "my average is a huge negative number"},
    {"role": "assistant", "content": "What index does your loop end on?"},
]


def _turn(mode="Homework Assist", history=HISTORY, **kw):
    kw.setdefault("user_key", "u1")
    kw.setdefault("session_id", "s1")
    return PlaylabTurn(is_new_chat=not history, mode=mode, history=list(history), **kw)


def test_turn_count_increments_on_reuse(fake):
    _collect(_turn(history=[]), "turn 1")
    t2 = _turn()
    _collect(t2, "How about now?")
    assert fake.sent[-1] == ("conv1", "How about now?")  # reused conversations get no history block
    assert fake.store.get("u1", "s1").turn_count == 2 and t2.meta["turn_count"] == 2


def test_mode_switch_starts_seeded_conversation(fake):
    _collect(_turn(history=[]), "turn 1")
    study = _turn(mode="Study Assist")
    _collect(study, "what is an array?")
    cid, msg = fake.sent[-1]
    assert cid == "conv2" and study.meta["new_conversation_reason"] == "mode_switch"
    assert msg.startswith("[Conversation_History]\n")
    assert "Student:\nmy average is a huge negative number" in msg
    assert "CodingRabbit:\nWhat index does your loop end on?" in msg
    assert msg.endswith("\n\nwhat is an array?") and study.meta["history_seeded_messages"] == 2
    ref = fake.store.get("u1", "s1")
    assert (ref.conversation_id, ref.mode, ref.turn_count) == ("conv2", "Study Assist", 1)
    # Switching back is another switch.
    _collect(_turn(), "back to homework")
    assert fake.sent[-1][0] == "conv3"


def test_turn_limit_starts_seeded_conversation(fake, monkeypatch):
    monkeypatch.setenv("PLAYLAB_MAX_TURNS_PER_CONVERSATION", "2")
    _collect(_turn(history=[]), "t1")
    _collect(_turn(), "t2")
    third = _turn()
    _collect(third, "t3")
    assert [cid for cid, _ in fake.sent] == ["conv1", "conv1", "conv2"]
    assert third.meta["new_conversation_reason"] == "turn_limit"
    assert fake.sent[-1][1].startswith("[Conversation_History]")


def test_new_chat_and_missing_record_reasons(fake):
    first = _turn(history=[])
    _collect(first, "hi")
    assert first.meta["new_conversation_reason"] == "new_chat"
    assert fake.sent[-1][1] == "hi"  # nothing to seed on a new chat
    orphan = _turn(session_id="other")
    _collect(orphan, "hi")
    assert orphan.meta["new_conversation_reason"] == "no_record"
    assert fake.sent[-1][1].startswith("[Conversation_History]")


def test_history_block_keeps_last_six_and_skips_junk():
    hist = [{"role": "user", "content": f"m{i}"} for i in range(8)]
    hist += [{"role": "system", "content": "sys"}, {"role": "assistant", "content": "  "}]
    block = playlab_generation.build_history_block(hist)
    assert "m0" not in block and "m1" not in block and "m7" in block and "sys" not in block
    assert playlab_generation.build_history_block([]) == ""


def test_retry_after_seeded_create_sends_only_correction(fake):
    turn = _turn(mode="Study Assist")
    _collect(turn, "q")
    turn.attempt = 1
    _collect(turn, "Your previous response was rejected")
    assert fake.sent[-1] == ("conv1", "Your previous response was rejected")
    assert fake.store.get("u1", "s1").turn_count == 1


def test_bad_turn_limit_env_falls_back(monkeypatch):
    monkeypatch.setenv("PLAYLAB_MAX_TURNS_PER_CONVERSATION", "lots")
    assert playlab_generation.max_turns_per_conversation() == 10


def test_session_is_scoped_to_user(fake):
    _collect(PlaylabTurn(user_key="alice", session_id="s1", is_new_chat=True), "hi")
    _collect(PlaylabTurn(user_key="mallory", session_id="s1", is_new_chat=False), "hi")
    assert [cid for cid, _ in fake.sent] == ["conv1", "conv2"]


def test_retry_reuses_same_conversation(fake):
    turn = PlaylabTurn(user_key="u1", session_id="s1", is_new_chat=True)
    _collect(turn, "first draft please")
    turn.attempt = 1
    _collect(turn, "Your previous response was rejected")
    assert [cid for cid, _ in fake.sent] == ["conv1", "conv1"] and len(fake.created_with) == 1


def test_vanished_conversation_is_recreated_once(fake):
    fake.store.put("u1", "s1", PlaylabConversationRef("gone", False))
    turn = PlaylabTurn(user_key="u1", session_id="s1", is_new_chat=False)
    assert _collect(turn, "hi") == "".join(fake.reply)
    assert fake.store.get("u1", "s1").conversation_id == "conv1"


def test_store_failure_does_not_fail_the_turn(fake):
    class BrokenStore:
        def get(self, *a):
            raise TimeoutError("aurora waking")

        def put(self, *a):
            raise TimeoutError("aurora waking")
    turn = PlaylabTurn(user_key="u1", session_id="s1", is_new_chat=False)
    assert _collect(turn, "hi", store=BrokenStore()) == "".join(fake.reply)
    assert turn.meta["store_error"] == "TimeoutError" and turn.meta["new_conversation"] is True


def test_variables_applied_when_app_defines_them(fake):
    fake.variables_supported = True
    turn = PlaylabTurn(user_key="u1", session_id="s1", is_new_chat=True, session_context="Week: 2")
    _collect(turn, "hi")
    assert turn.meta["variables_applied"] is True


def test_message_and_session_context_builders():
    assert build_playlab_message("", "Q") == "Q"
    assert build_playlab_message("[Strict_Rules]\nx", "Q") == "[Vector_Database_Results]\n[Strict_Rules]\nx\n\nQ"
    matrix = json.dumps({"2": {"allowed": "arrays", "forbidden": "pointers"}})
    syllabus = format_syllabus_block(matrix, 2)
    assert "Week 2 Forbidden topics: pointers" in syllabus
    ctx = build_session_context(week=2, syllabus_block=syllabus, style_guide="2 spaces",
                                teaching_plan_block="[Section_Teaching_Plan_Context]\nplan")
    assert ctx.startswith("Week: 2\n\n[Retrieved_Syllabus_Chunk]")
    assert "[Style_Rules]\n2 spaces" in ctx and ctx.endswith("plan")
    assert format_syllabus_block(None, 2) == ""


# --------------------------------------------------------------------------- service integration


def test_generate_llm_response_playlab_branch(fake):
    route = SimpleNamespace(provider="playlab", model="claude-haiku-5-5")
    turn = PlaylabTurn(user_key="u1", session_id="s1", is_new_chat=True)
    msgs = [{"role": "user", "content": "Mode: Homework Assist\n[Student_Question]\nwhy?"}]
    text, _, stream = asyncio.run(_generate_llm_response(
        route, msgs, "SYSTEM PROMPT", "[Strict_Rules]\nr", {}, None, None, False, "m", playlab_turn=turn))
    assert stream is None and text == "".join(fake.reply)
    sent = fake.sent[-1][1]
    assert sent.startswith("[Vector_Database_Results]\n[Strict_Rules]") and "SYSTEM PROMPT" not in sent

    turn.attempt = 1
    retry = msgs + [{"role": "assistant", "content": "leaky"}, {"role": "user", "content": "Your previous response was rejected"}]
    asyncio.run(_generate_llm_response(route, retry, "S", "[Strict_Rules]\nr", {}, None, None, False, "m", playlab_turn=turn))
    assert fake.sent[-1] == ("conv1", "Your previous response was rejected")


def test_run_chat_with_playlab_provider_end_to_end(fake, monkeypatch):
    runtime = _runtime_config(rag_provider="bedrock", chat_provider="bedrock")
    runtime = replace(runtime, chat=replace(runtime.chat, provider="playlab", model="claude-haiku-5-5"))
    monkeypatch.setattr("rag_eng.service.get_inference_config", lambda: runtime)
    telemetry = _FakeTelemetryStore()
    monkeypatch.setattr("rag_eng.service.get_telemetry_store", lambda: telemetry)
    monkeypatch.setattr("rag_eng.service.run_retrieval",
                        lambda query: SimpleNamespace(formatted_context="[Strict_Rules]\nrule", syllabus=None))
    monkeypatch.setattr("rag_eng.service.apply_all_guardrails",
                        lambda answer, user_query, student_code, history: {
                            "safe": True, "blocked": False, "violation_type": "none", "severity": "",
                            "action": "pass", "evidence": "", "final_answer": answer, "v2_score": 0.0, "stage": "v1"})

    def call(messages, stream):
        result = asyncio.run(run_chat(messages, model_name="codingrabbit", settings=SimpleNamespace(),
                                      stream=stream, session_id="sess-1", app_user_id="user-1"))
        if not stream:
            return result

        async def drain():
            return [c async for c in result]
        return asyncio.run(drain())

    turn1 = {"role": "user", "content": "Mode: Homework Assist\nWeek: 2\n[Code_Context]\nint a[5];\n[Student_Question]\nwhy?"}
    payload = call([turn1], stream=False)
    assert "What index" in payload["message"]["content"]
    # Raw text incl. <analysis> goes back as with Bedrock; the extension strips it for display.
    assert payload["message"]["content"].startswith("<analysis>")
    assert fake.sent[0][1].startswith("[Vector_Database_Results]\n[Strict_Rules]\nrule\n\nMode: Homework Assist")

    # Second turn: extension resends history; only the new message goes to Playlab, same conversation.
    turn2 = {"role": "user", "content": "Mode: Homework Assist\nWeek: 2\n[Student_Question]\nHow about now?"}
    chunks = call([turn1, {"role": "assistant", "content": "earlier"}, turn2], stream=True)
    streamed = "".join(json.loads(c)["message"]["content"] for c in chunks if b'"message"' in c)
    assert "What index" in streamed
    assert [cid for cid, _ in fake.sent] == ["conv1", "conv1"]
    assert "earlier" not in fake.sent[1][1]

    attempt = telemetry.snapshots[-1]["snapshot"]["ta_generation_phase"]["generation_history"][-1]
    assert attempt["model_provider"] == "playlab" and attempt["analysis_present"] is True
    assert attempt["provider_metadata"]["conversation_id"] == "conv1"
    assert attempt["cot_keys"]["Cognitive_Stage"] == "4. Debugging"


# --------------------------------------------------------------------------- config


def test_playlab_allowed_for_chat_only():
    ok = AdminLlmConfigUpdate(rag={"provider": "bedrock", "model": "m"},
                              chat={"provider": "playlab", "model": "claude-haiku-5-5"})
    assert ok.chat.provider == "playlab"
    with pytest.raises(ValueError, match="chat provider"):
        AdminLlmConfigUpdate(rag={"provider": "playlab", "model": "x"}, chat={"provider": "bedrock", "model": "m"})
