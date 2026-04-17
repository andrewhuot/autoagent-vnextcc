"""Pure data helpers for the resume picker."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cli.sessions.store import SessionStore


_PREVIEW_LIMIT = 80


@dataclass(frozen=True)
class ResumeRow:
    """One row in the resume picker."""

    session_id: str
    started_at: str
    last_modified: str
    summary: str
    last_user_preview: str


def build_picker_rows(store: SessionStore, workspace_root: Path) -> list[ResumeRow]:
    """Build ordered picker rows for one workspace."""
    rows: list[ResumeRow] = []
    for summary in store.list_for_workspace(workspace_root):
        records = store.load(summary.session_id)
        summary_text = _summary_from_records(records)
        rows.append(
            ResumeRow(
                session_id=summary.session_id,
                started_at=summary.started_at,
                last_modified=summary.last_modified,
                summary=summary_text,
                last_user_preview=_truncate(summary.last_user_preview),
            )
        )
    return rows


def _summary_from_records(records: list[object]) -> str:
    for record in records:
        metadata = getattr(record, "metadata", {}) or {}
        if "session_summary" in metadata:
            return _truncate(str(metadata["session_summary"]))

    for record in records:
        if getattr(record, "kind", None) == "turn" and getattr(record, "role", None) == "user":
            content = getattr(record, "content", "") or ""
            return _truncate(str(content))

    return ""


def _truncate(text: str) -> str:
    return text[:_PREVIEW_LIMIT]


__all__ = ["ResumeRow", "build_picker_rows"]
