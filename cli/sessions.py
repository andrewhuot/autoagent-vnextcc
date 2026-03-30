"""Session persistence for the AutoAgent CLI."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


SESSIONS_DIR_NAME = "sessions"


@dataclass
class SessionEntry:
    """A single transcript entry within a CLI session."""

    role: str
    content: str
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize the session entry for persistence."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionEntry:
        """Rebuild a session entry from persisted JSON data."""
        return cls(
            role=str(data.get("role", "user")),
            content=str(data.get("content", "")),
            timestamp=float(data.get("timestamp", 0.0)),
        )


@dataclass
class Session:
    """A durable CLI session."""

    session_id: str
    title: str = ""
    started_at: float = 0.0
    updated_at: float = 0.0
    transcript: list[SessionEntry] = field(default_factory=list)
    command_history: list[str] = field(default_factory=list)
    active_goal: str = ""
    pending_next_actions: list[str] = field(default_factory=list)
    settings_overrides: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full session to a JSON-compatible structure."""
        return {
            "session_id": self.session_id,
            "title": self.title,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "transcript": [entry.to_dict() for entry in self.transcript],
            "command_history": self.command_history,
            "active_goal": self.active_goal,
            "pending_next_actions": self.pending_next_actions,
            "settings_overrides": self.settings_overrides,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Session:
        """Rebuild a persisted session object."""
        return cls(
            session_id=str(data.get("session_id", "")),
            title=str(data.get("title", "")),
            started_at=float(data.get("started_at", 0.0)),
            updated_at=float(data.get("updated_at", 0.0)),
            transcript=[
                SessionEntry.from_dict(entry) for entry in data.get("transcript", [])
            ],
            command_history=list(data.get("command_history", [])),
            active_goal=str(data.get("active_goal", "")),
            pending_next_actions=list(data.get("pending_next_actions", [])),
            settings_overrides=dict(data.get("settings_overrides", {})),
        )


class SessionStore:
    """Manage session files under ``.autoagent/sessions/``."""

    def __init__(self, workspace_dir: Path) -> None:
        self._dir = workspace_dir / ".autoagent" / SESSIONS_DIR_NAME
        self._dir.mkdir(parents=True, exist_ok=True)

    def create(self, title: str = "") -> Session:
        """Create and persist a new CLI session."""
        now = time.time()
        session = Session(
            session_id=uuid.uuid4().hex[:12],
            title=title or f"Session {time.strftime('%Y-%m-%d %H:%M')}",
            started_at=now,
            updated_at=now,
        )
        self._save(session)
        return session

    def get(self, session_id: str) -> Session | None:
        """Load a session by its ID."""
        path = self._path_for(session_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return Session.from_dict(data)

    def save(self, session: Session) -> Path:
        """Persist the current session state."""
        return self._save(session)

    def list_sessions(self, *, limit: int = 20) -> list[Session]:
        """Return recent sessions ordered newest-first."""
        sessions: list[Session] = []
        for path in self._dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            sessions.append(Session.from_dict(data))
        sessions.sort(key=lambda session: session.updated_at, reverse=True)
        return sessions[:limit]

    def delete(self, session_id: str) -> bool:
        """Delete a session file if it exists."""
        path = self._path_for(session_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def latest(self) -> Session | None:
        """Return the most recently updated session."""
        sessions = self.list_sessions(limit=1)
        return sessions[0] if sessions else None

    def append_entry(self, session: Session, role: str, content: str) -> None:
        """Append a transcript entry and persist the session."""
        entry = SessionEntry(role=role, content=content, timestamp=time.time())
        session.transcript.append(entry)
        session.updated_at = time.time()
        self._save(session)

    def append_command(self, session: Session, command: str) -> None:
        """Append a command to the session history and persist it."""
        session.command_history.append(command)
        session.updated_at = time.time()
        self._save(session)

    def _path_for(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.json"

    def _save(self, session: Session) -> Path:
        path = self._path_for(session.session_id)
        path.write_text(
            json.dumps(session.to_dict(), indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        return path
