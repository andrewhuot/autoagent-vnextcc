"""Append-only JSONL session storage for workbench history."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus


logger = logging.getLogger(__name__)

_WORKSPACE_METADATA = "workspace.json"
_HISTORY_DIR_NAME = "history"
_SLUG_LIMIT = 200


def _utcnow() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _hash_suffix(value: str, *, length: int = 4) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _slug_base(workspace_root: Path) -> str:
    slug = quote_plus(str(workspace_root.resolve()), safe="")
    if len(slug) <= _SLUG_LIMIT:
        return slug
    suffix = _hash_suffix(slug)
    return f"{slug[:_SLUG_LIMIT - len(suffix) - 1]}-{suffix}"


@dataclass(frozen=True)
class TurnRecord:
    """One append-only JSONL record."""

    kind: str = "turn"
    role: str | None = None
    content: str | None = None
    created_at: str = field(default_factory=_utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TurnRecord":
        return cls(
            kind=str(data.get("kind", "turn")),
            role=str(data["role"]) if data.get("role") is not None else None,
            content=str(data["content"]) if data.get("content") is not None else None,
            created_at=str(data.get("created_at", _utcnow())),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class Session:
    """Persisted JSONL session metadata."""

    session_id: str
    workspace_root: str
    workspace_slug: str
    started_at: str


@dataclass(frozen=True)
class SessionSummary:
    """Summary row for one persisted session."""

    session_id: str
    started_at: str
    last_modified: str
    last_user_preview: str
    turn_count: int


class SessionStore:
    """Append-only JSONL store rooted at ``~/.agentlab/projects``-style paths."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root).expanduser()
        self._root.mkdir(parents=True, exist_ok=True)
        self._session_paths: dict[str, Path] = {}
        self._locks: dict[Path, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def create(self, workspace_root: Path) -> Session:
        resolved_root = Path(workspace_root).resolve()
        project_dir, workspace_slug = self._ensure_project_dir(resolved_root)
        history_dir = project_dir / _HISTORY_DIR_NAME
        history_dir.mkdir(parents=True, exist_ok=True)

        session_id = str(uuid.uuid4())
        started_at = _utcnow()
        session = Session(
            session_id=session_id,
            workspace_root=str(resolved_root),
            workspace_slug=workspace_slug,
            started_at=started_at,
        )
        self._session_paths[session_id] = history_dir / f"{session_id}.jsonl"
        self._write_line(
            self._session_paths[session_id],
            TurnRecord(
                kind="session_meta",
                created_at=started_at,
                metadata={
                    "session_id": session_id,
                    "workspace_root": str(resolved_root),
                    "workspace_slug": workspace_slug,
                },
            ),
        )
        return session

    def append(self, session_id: str, turn: TurnRecord) -> None:
        self._write_line(self._session_path(session_id), turn)

    def load(self, session_id: str) -> list[TurnRecord]:
        path = self._session_path(session_id)
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        records: list[TurnRecord] = []
        for index, raw_line in enumerate(lines):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                is_last_line = index == len(lines) - 1
                if is_last_line and not raw_line.endswith("\n"):
                    logger.warning("dropping partial final line for %s", session_id)
                    break
                raise ValueError(f"Corrupt session file {path}") from exc
            records.append(TurnRecord.from_dict(payload))
        return records

    def list_for_workspace(self, workspace_root: Path) -> list[SessionSummary]:
        project_dir = self._project_dir_for_workspace(Path(workspace_root).resolve())
        if project_dir is None:
            return []

        summaries: list[SessionSummary] = []
        history_dir = project_dir / _HISTORY_DIR_NAME
        if not history_dir.exists():
            return []

        for session_file in history_dir.glob("*.jsonl"):
            records = self.load(session_file.stem)
            started_at = records[0].created_at if records else ""
            turn_records = [record for record in records if record.kind == "turn"]
            last_user = next(
                (
                    record.content or ""
                    for record in reversed(turn_records)
                    if record.role == "user"
                ),
                "",
            )
            summaries.append(
                SessionSummary(
                    session_id=session_file.stem,
                    started_at=started_at,
                    last_modified=datetime.fromtimestamp(
                        session_file.stat().st_mtime,
                        tz=timezone.utc,
                    ).isoformat(),
                    last_user_preview=last_user[:80],
                    turn_count=len(turn_records),
                )
            )

        summaries.sort(key=lambda summary: summary.last_modified, reverse=True)
        return summaries

    def _ensure_project_dir(self, workspace_root: Path) -> tuple[Path, str]:
        base_slug = _slug_base(workspace_root)
        candidate = self._root / base_slug
        metadata = self._read_workspace_metadata(candidate)
        if metadata == str(workspace_root):
            return candidate, base_slug
        if metadata is None:
            self._write_workspace_metadata(candidate, workspace_root, base_slug)
            return candidate, base_slug

        suffix = _hash_suffix(str(workspace_root))
        slug = f"{base_slug}-{suffix}"
        candidate = self._root / slug
        metadata = self._read_workspace_metadata(candidate)
        if metadata in {None, str(workspace_root)}:
            self._write_workspace_metadata(candidate, workspace_root, slug)
            return candidate, slug
        raise ValueError(f"Workspace slug collision for {workspace_root}")

    def _project_dir_for_workspace(self, workspace_root: Path) -> Path | None:
        for candidate in self._root.iterdir():
            if not candidate.is_dir():
                continue
            if self._read_workspace_metadata(candidate) == str(workspace_root):
                return candidate
        return None

    def _read_workspace_metadata(self, project_dir: Path) -> str | None:
        metadata_path = project_dir / _WORKSPACE_METADATA
        if not metadata_path.exists():
            return None
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        return str(payload.get("workspace_root", ""))

    def _write_workspace_metadata(
        self,
        project_dir: Path,
        workspace_root: Path,
        workspace_slug: str,
    ) -> None:
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / _WORKSPACE_METADATA).write_text(
            json.dumps(
                {
                    "workspace_root": str(workspace_root),
                    "workspace_slug": workspace_slug,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def _session_path(self, session_id: str) -> Path:
        cached = self._session_paths.get(session_id)
        if cached is not None:
            return cached

        matches = list(self._root.glob(f"*/{_HISTORY_DIR_NAME}/{session_id}.jsonl"))
        if not matches:
            raise KeyError(f"Unknown session: {session_id}")
        if len(matches) > 1:
            raise ValueError(f"Ambiguous session id: {session_id}")
        self._session_paths[session_id] = matches[0]
        return matches[0]

    def _write_line(self, path: Path, record: TurnRecord) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.to_dict(), sort_keys=True) + "\n"
        lock = self._lock_for(path)
        with lock, path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def _lock_for(self, path: Path) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.get(path)
            if lock is None:
                lock = threading.Lock()
                self._locks[path] = lock
            return lock


__all__ = [
    "Session",
    "SessionStore",
    "SessionSummary",
    "TurnRecord",
]
