"""Maps a CodingRabbit chat session to its Playlab conversation.

Playlab stores conversation history server-side, so each CodingRabbit chat
session (the extension's `session_id`) needs one Playlab conversation ID that
persists across turns and across Fargate tasks. Keyed by (user, session_id):
the session_id is client-supplied, so the user key stops one student from
attaching to another student's Playlab conversation.

Each row also records the assist mode and how many student turns have gone
into the conversation, so the backend can start a fresh conversation on a
mode switch or after a turn limit (Playlab has no history controls).

Backed by Aurora when a database URL is configured (table created on first
use), otherwise by an in-process dict (local dev / tests).
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Optional, Protocol

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS playlab_conversations (
    user_key text NOT NULL,
    session_id text NOT NULL,
    conversation_id text NOT NULL,
    variables_applied boolean NOT NULL DEFAULT false,
    mode text NOT NULL DEFAULT '',
    turn_count integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_key, session_id)
);
ALTER TABLE playlab_conversations ADD COLUMN IF NOT EXISTS mode text NOT NULL DEFAULT '';
ALTER TABLE playlab_conversations ADD COLUMN IF NOT EXISTS turn_count integer NOT NULL DEFAULT 0;
"""

_UPSERT = """
INSERT INTO playlab_conversations
    (user_key, session_id, conversation_id, variables_applied, mode, turn_count)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (user_key, session_id) DO UPDATE
SET conversation_id = EXCLUDED.conversation_id,
    variables_applied = EXCLUDED.variables_applied,
    mode = EXCLUDED.mode,
    turn_count = EXCLUDED.turn_count,
    updated_at = now();
"""

_SELECT = """
SELECT conversation_id, variables_applied, mode, turn_count
FROM playlab_conversations
WHERE user_key = %s AND session_id = %s;
"""


@dataclass(frozen=True)
class PlaylabConversationRef:
    conversation_id: str
    variables_applied: bool
    mode: str = ""        # assist mode the conversation was started in
    turn_count: int = 0   # student turns sent into this Playlab conversation


class PlaylabSessionStore(Protocol):
    def get(self, user_key: str, session_id: str) -> Optional[PlaylabConversationRef]: ...
    def put(self, user_key: str, session_id: str, ref: PlaylabConversationRef) -> None: ...


class InMemoryPlaylabSessionStore:
    def __init__(self) -> None:
        self._data: dict[tuple[str, str], PlaylabConversationRef] = {}
        self._lock = threading.Lock()

    def get(self, user_key: str, session_id: str) -> Optional[PlaylabConversationRef]:
        with self._lock:
            return self._data.get((user_key, session_id))

    def put(self, user_key: str, session_id: str, ref: PlaylabConversationRef) -> None:
        with self._lock:
            self._data[(user_key, session_id)] = ref


class PostgresPlaylabSessionStore:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._table_ready = False

    def _connect(self):
        from rag_eng.aurora_connect import connect_postgres_interactive

        return connect_postgres_interactive(self._database_url)

    def _ensure_table(self, cur) -> None:
        if not self._table_ready:
            cur.execute(_CREATE_TABLE)
            self._table_ready = True

    def get(self, user_key: str, session_id: str) -> Optional[PlaylabConversationRef]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._ensure_table(cur)
                cur.execute(_SELECT, (user_key, session_id))
                row = cur.fetchone()
            conn.commit()
        if not row:
            return None
        return PlaylabConversationRef(row[0], bool(row[1]), row[2] or "", int(row[3] or 0))

    def put(self, user_key: str, session_id: str, ref: PlaylabConversationRef) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._ensure_table(cur)
                cur.execute(
                    _UPSERT,
                    (user_key, session_id, ref.conversation_id, ref.variables_applied,
                     ref.mode, ref.turn_count),
                )
            conn.commit()


_store: Optional[PlaylabSessionStore] = None
_store_lock = threading.Lock()


def get_playlab_session_store() -> PlaylabSessionStore:
    global _store
    with _store_lock:
        if _store is None:
            url = os.getenv("COURSE_REGISTRY_DATABASE_URL") or os.getenv("DATABASE_URL")
            if url:
                _store = PostgresPlaylabSessionStore(url)
            else:
                logger.warning("No database URL; Playlab conversation map is in-memory only.")
                _store = InMemoryPlaylabSessionStore()
        return _store


def set_playlab_session_store(store: Optional[PlaylabSessionStore]) -> None:
    """Test hook: override (or reset with None) the process-wide store."""
    global _store
    with _store_lock:
        _store = store
