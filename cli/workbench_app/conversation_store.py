"""SQLite-backed conversation persistence.

Schema (one DB per workspace at ``.agentlab/conversations.db``):

- ``conversation`` — id, created_at, updated_at, workspace_root, model.
- ``message`` — id, conversation_id, role (user/assistant/system/tool),
  content, position (monotonically increasing per conversation),
  created_at.
- ``tool_call`` — id, message_id, tool_name, arguments_json, status
  (pending/succeeded/failed/interrupted), result_json, started_at,
  finished_at.

Crash safety: on load, any tool_call still in ``pending`` is flipped
to ``interrupted`` so resuming Workbench can't pretend a killed
deploy succeeded. The in-flight LLM message (assistant turn that
hadn't finished streaming) is preserved as-is — it's the conversation
loop's responsibility to decide whether to retry it or surface it as
a partial.

The store is intentionally thin. Conversation-level operations
(append message, mark tool call done) take individual fields, not a
full dataclass — keeps the API mockable and the SQL trivial.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = 1


@dataclass
class Message:
    id: str
    conversation_id: str
    role: str  # "user" | "assistant" | "system" | "tool"
    content: str
    position: int
    created_at: str
    tool_calls: list["ToolCall"] = field(default_factory=list)


@dataclass
class ToolCall:
    id: str
    message_id: str
    tool_name: str
    arguments: dict[str, Any]
    status: str  # "pending" | "succeeded" | "failed" | "interrupted"
    result: dict[str, Any] | None
    started_at: str
    finished_at: str | None


@dataclass
class Conversation:
    id: str
    created_at: str
    updated_at: str
    workspace_root: str | None
    model: str | None
    messages: list[Message] = field(default_factory=list)


def _utcnow() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class ConversationStore:
    """Thin wrapper around SQLite for conversation persistence."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            self._migrate(conn)
            self._mark_in_flight_interrupted(conn)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _migrate(self, conn: sqlite3.Connection) -> None:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversation (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                workspace_root TEXT,
                model TEXT
            );
            CREATE TABLE IF NOT EXISTS message (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversation(id),
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                position INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_message_conversation
                ON message(conversation_id, position);
            CREATE TABLE IF NOT EXISTS tool_call (
                id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL REFERENCES message(id),
                tool_name TEXT NOT NULL,
                arguments_json TEXT NOT NULL,
                status TEXT NOT NULL,
                result_json TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT
            );
        """)

    def _mark_in_flight_interrupted(self, conn: sqlite3.Connection) -> None:
        """Crash-safety: any tool_call still ``pending`` is from a
        previous Workbench process that was killed. Mark interrupted
        so the resume UI surfaces it instead of silently succeeding."""
        conn.execute(
            "UPDATE tool_call SET status = 'interrupted', finished_at = ? "
            "WHERE status = 'pending'",
            (_utcnow(),),
        )

    def create_conversation(
        self, *, workspace_root: str | None = None, model: str | None = None
    ) -> Conversation:
        cid = _new_id("conv")
        now = _utcnow()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO conversation(id, created_at, updated_at, workspace_root, model) "
                "VALUES (?, ?, ?, ?, ?)",
                (cid, now, now, workspace_root, model),
            )
        return Conversation(
            id=cid, created_at=now, updated_at=now,
            workspace_root=workspace_root, model=model,
        )

    def append_message(
        self, *, conversation_id: str, role: str, content: str
    ) -> Message:
        mid = _new_id("msg")
        now = _utcnow()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS next_pos "
                "FROM message WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            position = int(row["next_pos"])
            conn.execute(
                "INSERT INTO message(id, conversation_id, role, content, position, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (mid, conversation_id, role, content, position, now),
            )
            conn.execute(
                "UPDATE conversation SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
        return Message(
            id=mid, conversation_id=conversation_id, role=role,
            content=content, position=position, created_at=now,
        )

    def start_tool_call(
        self, *, message_id: str, tool_name: str, arguments: dict[str, Any]
    ) -> ToolCall:
        tid = _new_id("tc")
        now = _utcnow()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO tool_call(id, message_id, tool_name, arguments_json, "
                "status, result_json, started_at, finished_at) "
                "VALUES (?, ?, ?, ?, 'pending', NULL, ?, NULL)",
                (tid, message_id, tool_name, json.dumps(arguments), now),
            )
        return ToolCall(
            id=tid, message_id=message_id, tool_name=tool_name,
            arguments=arguments, status="pending", result=None,
            started_at=now, finished_at=None,
        )

    def finish_tool_call(
        self,
        *,
        tool_call_id: str,
        status: str,
        result: dict[str, Any] | None,
    ) -> None:
        if status not in {"succeeded", "failed", "interrupted"}:
            raise ValueError(f"Invalid terminal status: {status}")
        with self._connect() as conn:
            conn.execute(
                "UPDATE tool_call SET status = ?, result_json = ?, finished_at = ? "
                "WHERE id = ?",
                (status, json.dumps(result) if result is not None else None,
                 _utcnow(), tool_call_id),
            )

    def get_conversation(self, conversation_id: str) -> Conversation:
        with self._connect() as conn:
            crow = conn.execute(
                "SELECT * FROM conversation WHERE id = ?", (conversation_id,),
            ).fetchone()
            if crow is None:
                raise KeyError(f"Unknown conversation: {conversation_id}")

            mrows = conn.execute(
                "SELECT * FROM message WHERE conversation_id = ? ORDER BY position",
                (conversation_id,),
            ).fetchall()
            messages = []
            for mrow in mrows:
                trows = conn.execute(
                    "SELECT * FROM tool_call WHERE message_id = ? ORDER BY started_at",
                    (mrow["id"],),
                ).fetchall()
                tool_calls = [
                    ToolCall(
                        id=t["id"], message_id=t["message_id"],
                        tool_name=t["tool_name"],
                        arguments=json.loads(t["arguments_json"]),
                        status=t["status"],
                        result=json.loads(t["result_json"]) if t["result_json"] else None,
                        started_at=t["started_at"], finished_at=t["finished_at"],
                    )
                    for t in trows
                ]
                messages.append(Message(
                    id=mrow["id"], conversation_id=mrow["conversation_id"],
                    role=mrow["role"], content=mrow["content"],
                    position=mrow["position"], created_at=mrow["created_at"],
                    tool_calls=tool_calls,
                ))

        return Conversation(
            id=crow["id"], created_at=crow["created_at"],
            updated_at=crow["updated_at"],
            workspace_root=crow["workspace_root"], model=crow["model"],
            messages=messages,
        )

    def list_recent(self, limit: int = 20) -> list[Conversation]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM conversation ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            Conversation(
                id=r["id"], created_at=r["created_at"],
                updated_at=r["updated_at"],
                workspace_root=r["workspace_root"], model=r["model"],
            )
            for r in rows
        ]
