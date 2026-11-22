"""Playlab as a chat generation provider (runtime.chat.provider == "playlab").

Differences from the Bedrock/OpenAI paths:
  * The system prompt lives in the Playlab app (see playlab/app_instructions.md),
    not in our request. get_system_prompt() is not sent.
  * Playlab stores conversation history and offers no way to trim it. We reuse
    one Playlab conversation per (student, chat, mode) and send only the
    current turn. We start a fresh conversation on a new chat, a mode switch,
    or after MAX_TURNS_PER_CONVERSATION turns; a fresh conversation's first
    message is seeded with our own recent history as [Conversation_History]
    (already cleaned by the extension, e.g. no past <analysis> in Study Assist).
    A fresh conversation costs ~4s extra to first token (measured 2026-11-02),
    which is why we don't start one every turn.
  * Per-turn retrieval context ([Vector_Database_Results]) has no system slot,
    so it is prepended to the student's message.
  * Session-fixed context (week, syllabus limits, style rules, teaching plan) is
    also offered as the `session_context` instruction variable at conversation
    creation. Playlab silently drops variables the app doesn't define, so we
    record whether it was applied (`instructionVariableValues` non-empty) and
    always keep the same blocks in the message so nothing is lost either way.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

from rag_eng.playlab_client import AsyncPlaylabClient, PlaylabError
from rag_eng.playlab_sessions import (
    PlaylabConversationRef,
    PlaylabSessionStore,
    get_playlab_session_store,
)

logger = logging.getLogger(__name__)

HISTORY_SEED_MESSAGES = 6


def max_turns_per_conversation() -> int:
    try:
        return max(1, int(os.getenv("PLAYLAB_MAX_TURNS_PER_CONVERSATION", "10")))
    except ValueError:
        return 10


@dataclass
class PlaylabTurn:
    """Per-turn inputs from run_chat, plus metadata filled in during generation."""

    user_key: str
    session_id: Optional[str]
    is_new_chat: bool
    session_context: str = ""
    mode: str = ""
    history: list[dict] = field(default_factory=list)  # prior user/assistant turns from the extension
    attempt: int = 0
    meta: dict[str, Any] = field(default_factory=dict)
    ref: Optional[PlaylabConversationRef] = None  # cached so retries reuse the conversation


def build_session_context(
    *,
    week: int | None,
    syllabus_block: str = "",
    style_guide: str | None = None,
    teaching_plan_block: str = "",
) -> str:
    parts = [f"Week: {week}"] if week is not None else []
    if syllabus_block.strip():
        parts.append(syllabus_block.strip())
    if style_guide and style_guide.strip():
        parts.append(f"[Style_Rules]\n{style_guide.strip()}")
    if teaching_plan_block.strip():
        parts.append(teaching_plan_block.strip())
    return "\n\n".join(parts)


def build_playlab_message(rag_context: str, latest_user_content: str) -> str:
    rag_context = (rag_context or "").strip()
    if not rag_context:
        return latest_user_content
    return f"[Vector_Database_Results]\n{rag_context}\n\n{latest_user_content}"


def build_history_block(history: list[dict]) -> str:
    """Render recent turns as text for the first message of a fresh conversation."""
    lines = []
    for msg in history[-HISTORY_SEED_MESSAGES:]:
        content = str(msg.get("content") or "").strip()
        if not content or msg.get("role") not in {"user", "assistant"}:
            continue
        speaker = "Student" if msg["role"] == "user" else "CodingRabbit"
        lines.append(f"{speaker}:\n{content}")
    if not lines:
        return ""
    return (
        "[Conversation_History]\n"
        "(Earlier turns of this chat, oldest first, for context only. "
        "The student's current message follows.)\n\n" + "\n\n".join(lines)
    )


def _ndjson(delta: str) -> bytes:
    return (json.dumps({"message": {"content": delta}}) + "\n").encode("utf-8")


async def _create(
    client: AsyncPlaylabClient,
    store: PlaylabSessionStore,
    turn: PlaylabTurn,
) -> PlaylabConversationRef:
    variables = {"session_context": turn.session_context} if turn.session_context else None
    conv = await client.create_conversation(variables)
    ref = PlaylabConversationRef(
        conversation_id=conv["id"],
        variables_applied=bool(conv.get("instructionVariableValues")),
        mode=turn.mode,
        turn_count=1,
    )
    turn.meta.update(
        new_conversation=True,
        playlab_model_name=conv.get("modelName"),
        playlab_provider=conv.get("provider"),
    )
    if turn.session_id:
        await _put(store, turn, ref)
    else:
        logger.warning("Playlab turn without session_id; history will not carry over.")
    turn.ref = ref
    return ref


async def _put(store: PlaylabSessionStore, turn: PlaylabTurn, ref: PlaylabConversationRef) -> None:
    try:
        await asyncio.to_thread(store.put, turn.user_key, turn.session_id, ref)
    except Exception as exc:  # never fail the student's turn on a bookkeeping write
        logger.warning("Playlab session store write failed: %s", exc)
        turn.meta["store_error"] = type(exc).__name__


async def _resolve(
    client: AsyncPlaylabClient,
    store: PlaylabSessionStore,
    turn: PlaylabTurn,
) -> tuple[PlaylabConversationRef, bool]:
    """Return (conversation, created_now). Reuses the stored conversation unless
    this is a new chat, the mode changed, or the turn limit was reached."""
    if turn.ref is not None:  # retry within the same student turn
        return turn.ref, False
    reason = "new_chat"
    if turn.session_id and not turn.is_new_chat:
        try:
            ref = await asyncio.to_thread(store.get, turn.user_key, turn.session_id)
        except Exception as exc:  # degrade to a fresh conversation rather than erroring
            logger.warning("Playlab session store read failed: %s", exc)
            turn.meta["store_error"] = type(exc).__name__
            ref, reason = None, "store_error"
        if ref is None:
            reason = reason if reason == "store_error" else "no_record"
        elif ref.mode != turn.mode:
            reason = "mode_switch"
        elif ref.turn_count >= max_turns_per_conversation():
            reason = "turn_limit"
        else:
            ref = PlaylabConversationRef(
                ref.conversation_id, ref.variables_applied, ref.mode, ref.turn_count + 1
            )
            await _put(store, turn, ref)
            turn.meta.update(new_conversation=False, turn_count=ref.turn_count)
            turn.ref = ref
            return ref, False
    elif not turn.session_id:
        reason = "no_session_id"
    turn.meta["new_conversation_reason"] = reason
    ref = await _create(client, store, turn)
    turn.meta["turn_count"] = ref.turn_count
    return ref, True


def _first_message(turn: PlaylabTurn, message: str) -> str:
    """Seed a fresh conversation with our recent history (none on a new chat)."""
    block = build_history_block(turn.history)
    turn.meta["history_seeded_messages"] = (
        min(len(turn.history), HISTORY_SEED_MESSAGES) if block else 0
    )
    return f"{block}\n\n{message}" if block else message


async def stream_playlab_reply(
    turn: PlaylabTurn,
    message: str,
    *,
    client: Optional[AsyncPlaylabClient] = None,
    store: Optional[PlaylabSessionStore] = None,
) -> AsyncIterator[bytes]:
    """Yield NDJSON chunks ({"message": {"content": ...}}) like the Bedrock stream.

    If a stored conversation has disappeared on Playlab's side (404 before any
    text arrived), start a fresh conversation and resend once.
    """
    store = store or get_playlab_session_store()
    owns_client = client is None
    client = client or AsyncPlaylabClient()
    try:
        ref, created = await _resolve(client, store, turn)
        for attempt in range(2):
            outgoing = _first_message(turn, message) if created else message
            turn.meta.update(
                conversation_id=ref.conversation_id,
                variables_applied=ref.variables_applied,
                message_chars=len(outgoing),
            )
            produced = False
            try:
                async for delta in client.stream_message(ref.conversation_id, outgoing):
                    produced = True
                    yield _ndjson(delta)
                return
            except PlaylabError as exc:
                if attempt == 0 and not produced and exc.conversation_not_found:
                    logger.warning("Playlab conversation %s not found; recreating.", ref.conversation_id)
                    turn.meta["new_conversation_reason"] = "not_found"
                    ref, created = await _create(client, store, turn), True
                    continue
                raise
    finally:
        if owns_client:
            await client.aclose()


async def generate_playlab_reply(turn: PlaylabTurn, message: str, **kwargs) -> str:
    chunks = []
    async for chunk in stream_playlab_reply(turn, message, **kwargs):
        chunks.append(json.loads(chunk)["message"]["content"])
    return "".join(chunks)
