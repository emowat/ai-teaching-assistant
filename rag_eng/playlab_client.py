"""Server-side client for the Playlab API (beta).

Playlab hosts the LLM, the app's instructions, and the conversation history;
CodingRabbit keeps orchestration, retrieval, guardrails, and telemetry. The
API key must never leave the backend.

Endpoints (https://www.playlab.ai/api/v1):
  POST /projects/{project}/conversations                      -> create
  POST /projects/{project}/conversations/{conv}/messages      -> SSE stream
  GET  /projects/{project}/conversations/{conv}/messages      -> history

Env: PLAYLAB_API_KEY, PLAYLAB_PROJECT_ID, PLAYLAB_API_BASE_URL (optional).

Both a sync client (scripts) and an async client (the chat path) are provided;
they share request building and SSE parsing.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Optional

import httpx

DEFAULT_BASE_URL = "https://www.playlab.ai/api/v1"


class PlaylabError(RuntimeError):
    """Any Playlab API failure. `status` is None for network/stream errors."""

    def __init__(self, message: str, status: Optional[int] = None, body: Any = None):
        super().__init__(f"Playlab API error{f' {status}' if status else ''}: {message}")
        self.status = status
        self.body = body

    @property
    def conversation_not_found(self) -> bool:
        return self.status == 404 and "conversation" in str(self.body).lower()


@dataclass
class StreamResult:
    text: str
    tool_calls: list = field(default_factory=list)
    tool_results: list = field(default_factory=list)


def playlab_configured() -> bool:
    return bool(os.getenv("PLAYLAB_API_KEY") and os.getenv("PLAYLAB_PROJECT_ID"))


def _error_from_response(status: int, raw: bytes | str) -> PlaylabError:
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    try:
        body = json.loads(text)
    except ValueError:
        return PlaylabError(text or "unknown error", status, text)
    err = body.get("error") if isinstance(body, dict) else body
    if isinstance(err, dict) and "issues" in err:
        return PlaylabError(f"schema validation failed: {err['issues']}", status, body)
    return PlaylabError(str(err), status, body)


class _SSEParser:
    """Incremental parser for Playlab's SSE stream (`event:` / `data:` lines)."""

    def __init__(self) -> None:
        self.event: Optional[str] = None
        self.result = StreamResult(text="")
        self._chunks: list[str] = []

    def feed(self, line: str) -> Optional[str]:
        """Consume one line; return the text delta it carried, if any."""
        if line.startswith("event:"):
            self.event = line[6:].strip()
            return None
        if not line.startswith("data:"):
            return None
        try:
            data = json.loads(line[5:])
        except ValueError:
            return None  # ignore unparseable chunks, per Playlab docs
        if not isinstance(data, dict):
            return None
        if self.event == "error" or ("error" in data and "delta" not in data):
            raise PlaylabError(f"stream error: {data.get('error')}", None, data)
        if data.get("delta"):
            self._chunks.append(data["delta"])
            return data["delta"]
        if "messageToolCalls" in data:
            self.result.tool_calls.extend(data["messageToolCalls"] or [])
        elif "toolCallResult" in data:
            self.result.tool_results.append(data["toolCallResult"])
        return None

    def finish(self) -> StreamResult:
        self.result.text = "".join(self._chunks)
        return self.result


def _settings(api_key, project_id, base_url) -> tuple[str, str, str]:
    api_key = api_key or os.getenv("PLAYLAB_API_KEY")
    project_id = project_id or os.getenv("PLAYLAB_PROJECT_ID")
    base_url = (base_url or os.getenv("PLAYLAB_API_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    if not api_key:
        raise PlaylabError("PLAYLAB_API_KEY is not set")
    if not project_id:
        raise PlaylabError("PLAYLAB_PROJECT_ID is not set")
    return api_key, project_id, f"{base_url}/projects/{project_id}"


def _create_payload(instruction_variables: Optional[dict]) -> dict:
    return {"instructionVariables": instruction_variables} if instruction_variables else {}


def _conversation_from(status: int, body: bytes) -> dict:
    if status >= 400:
        raise _error_from_response(status, body)
    try:
        conv = json.loads(body).get("conversation")
    except (ValueError, AttributeError):
        conv = None
    if not conv or "id" not in conv:
        raise PlaylabError("response missing conversation.id", status, body[:500])
    return conv


class PlaylabClient:
    """Synchronous client (scripts, smoke tests)."""

    def __init__(self, api_key=None, project_id=None, base_url=None, timeout: float = 120.0,
                 transport: Optional[httpx.BaseTransport] = None):
        api_key, self.project_id, url = _settings(api_key, project_id, base_url)
        self._http = httpx.Client(base_url=url, headers={"Authorization": f"Bearer {api_key}"},
                                  timeout=timeout, transport=transport)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "PlaylabClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def create_conversation(self, instruction_variables: Optional[dict] = None) -> dict:
        """Create a conversation; returns the full `conversation` object (id, modelName, ...)."""
        try:
            resp = self._http.post("/conversations", json=_create_payload(instruction_variables))
        except httpx.HTTPError as exc:
            raise PlaylabError(f"network error creating conversation: {exc}") from exc
        return _conversation_from(resp.status_code, resp.content)

    def send_message(self, conversation_id: str, message: str,
                     on_delta: Optional[Callable[[str], None]] = None) -> StreamResult:
        """Send a user message, consume the SSE stream, return the accumulated text."""
        parser = _SSEParser()
        try:
            with self._http.stream("POST", f"/conversations/{conversation_id}/messages",
                                   json={"input": {"message": message}}) as resp:
                if resp.status_code >= 400:
                    raise _error_from_response(resp.status_code, resp.read())
                for line in resp.iter_lines():
                    delta = parser.feed(line)
                    if delta and on_delta:
                        on_delta(delta)
        except httpx.HTTPError as exc:
            raise PlaylabError(f"network/stream error sending message: {exc}") from exc
        return parser.finish()

    def list_messages(self, conversation_id: str) -> list[dict]:
        try:
            resp = self._http.get(f"/conversations/{conversation_id}/messages")
        except httpx.HTTPError as exc:
            raise PlaylabError(f"network error listing messages: {exc}") from exc
        if resp.status_code >= 400:
            raise _error_from_response(resp.status_code, resp.content)
        return resp.json().get("messages", [])


class AsyncPlaylabClient:
    """Async client used by the chat path. Create one per request (cheap)."""

    def __init__(self, api_key=None, project_id=None, base_url=None, timeout: float = 120.0,
                 transport: Optional[httpx.AsyncBaseTransport] = None):
        api_key, self.project_id, url = _settings(api_key, project_id, base_url)
        self._http = httpx.AsyncClient(base_url=url, headers={"Authorization": f"Bearer {api_key}"},
                                       timeout=timeout, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "AsyncPlaylabClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def create_conversation(self, instruction_variables: Optional[dict] = None) -> dict:
        try:
            resp = await self._http.post("/conversations", json=_create_payload(instruction_variables))
        except httpx.HTTPError as exc:
            raise PlaylabError(f"network error creating conversation: {exc}") from exc
        return _conversation_from(resp.status_code, resp.content)

    async def stream_message(self, conversation_id: str, message: str) -> AsyncIterator[str]:
        """Yield text deltas as they arrive. Raises PlaylabError on HTTP/stream failure."""
        parser = _SSEParser()
        try:
            async with self._http.stream("POST", f"/conversations/{conversation_id}/messages",
                                         json={"input": {"message": message}}) as resp:
                if resp.status_code >= 400:
                    raise _error_from_response(resp.status_code, await resp.aread())
                async for line in resp.aiter_lines():
                    delta = parser.feed(line)
                    if delta:
                        yield delta
        except httpx.HTTPError as exc:
            raise PlaylabError(f"network/stream error sending message: {exc}") from exc

    async def send_message(self, conversation_id: str, message: str) -> StreamResult:
        chunks = [d async for d in self.stream_message(conversation_id, message)]
        return StreamResult(text="".join(chunks))
