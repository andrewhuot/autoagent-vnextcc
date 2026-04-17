"""Helpers for user-facing tool result rendering.

This branch does not have a dedicated ``Tool.render_result`` protocol, so
rendering metadata travels on :class:`cli.tools.base.ToolResult.metadata`
while ``ToolResult.display`` remains the line-mode fallback.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Any, Iterable


STRUCTURED_DIFF_KIND = "structured_diff"
MAX_FILE_WRITE_RENDER_LINES = 1000
PERSISTED_RENDER_TEXT_MAX_CHARS = 16000


@dataclass(frozen=True)
class StructuredDiffRenderable:
    """Structured diff payload for TUI rendering and persisted tool history."""

    old: str
    new: str
    file_path: str
    language: str | None = None
    change_type: str = "edit"
    truncated: bool = False
    kind: str = STRUCTURED_DIFF_KIND

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "old": self.old,
            "new": self.new,
            "file_path": self.file_path,
            "language": self.language,
            "change_type": self.change_type,
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class ToolDisplayPayload:
    """User-facing display plus optional structured renderable for a tool."""

    tool_name: str
    display: str
    renderable: dict[str, Any] | None = None


def structured_diff_from_payload(payload: Any) -> StructuredDiffRenderable | None:
    """Return a structured diff renderable when ``payload`` matches the shape."""
    if not isinstance(payload, dict):
        return None
    if payload.get("kind") != STRUCTURED_DIFF_KIND:
        return None
    old = payload.get("old")
    new = payload.get("new")
    file_path = payload.get("file_path")
    language = payload.get("language")
    change_type = payload.get("change_type", "edit")
    truncated = bool(payload.get("truncated"))
    if not isinstance(old, str) or not isinstance(new, str) or not isinstance(file_path, str):
        return None
    if language is not None and not isinstance(language, str):
        language = None
    if not isinstance(change_type, str):
        change_type = "edit"
    return StructuredDiffRenderable(
        old=old,
        new=new,
        file_path=file_path,
        language=language,
        change_type=change_type,
        truncated=truncated,
    )


def structured_diff_from_metadata(metadata: dict[str, Any] | None) -> StructuredDiffRenderable | None:
    """Extract a structured diff renderable from tool-result metadata."""
    if not isinstance(metadata, dict):
        return None
    return structured_diff_from_payload(metadata.get("renderable"))


def persisted_renderable_payload(payload: Any) -> dict[str, Any] | None:
    """Return a persistence-safe renderable payload with bounded text fields."""
    renderable = structured_diff_from_payload(payload)
    if renderable is None:
        return None

    old, old_truncated = truncate_render_chars(
        renderable.old,
        max_chars=PERSISTED_RENDER_TEXT_MAX_CHARS,
    )
    new, new_truncated = truncate_render_chars(
        renderable.new,
        max_chars=PERSISTED_RENDER_TEXT_MAX_CHARS,
    )
    return StructuredDiffRenderable(
        old=old,
        new=new,
        file_path=renderable.file_path,
        language=renderable.language,
        change_type=renderable.change_type,
        truncated=renderable.truncated or old_truncated or new_truncated,
    ).to_payload()


def infer_language(file_path: str) -> str | None:
    """Infer a highlighting language from ``file_path``."""
    lowered = file_path.lower()
    if lowered.endswith(".py"):
        return "python"
    if lowered.endswith(".ts") or lowered.endswith(".tsx"):
        return "typescript"
    if lowered.endswith(".js") or lowered.endswith(".jsx"):
        return "javascript"
    if lowered.endswith(".yaml") or lowered.endswith(".yml"):
        return "yaml"
    if lowered.endswith(".md"):
        return "markdown"
    if lowered.endswith(".json"):
        return "json"
    if lowered.endswith(".txt"):
        return "text"
    return None


def truncate_render_text(text: str, *, max_lines: int) -> tuple[str, bool]:
    """Truncate ``text`` to at most ``max_lines`` logical lines."""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text, False
    truncated = "\n".join(lines[:max_lines]) + "\n"
    return truncated, True


def truncate_render_chars(text: str, *, max_chars: int) -> tuple[str, bool]:
    """Truncate ``text`` to at most ``max_chars`` characters."""
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def build_unified_diff_display(
    *,
    old: str,
    new: str,
    file_path: str,
    truncated: bool = False,
) -> str:
    """Build a readable unified diff fallback for line-mode consumers."""
    diff = difflib.unified_diff(
        old.splitlines(),
        new.splitlines(),
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
        lineterm="",
    )
    text = "\n".join(diff)
    if truncated:
        suffix = "\n[structured diff truncated for display]\n"
        return text + suffix if text else suffix
    return text


def iter_tool_display_payloads(executions: Iterable[Any]) -> list[ToolDisplayPayload]:
    """Collect user-visible tool displays from ``ToolExecution`` values."""
    payloads: list[ToolDisplayPayload] = []
    for execution in executions:
        result = getattr(execution, "result", None)
        display = getattr(result, "display", None)
        if not isinstance(display, str) or not display:
            continue
        metadata = getattr(result, "metadata", None)
        renderable = None
        if isinstance(metadata, dict):
            candidate = metadata.get("renderable")
            if isinstance(candidate, dict):
                renderable = candidate
        payloads.append(
            ToolDisplayPayload(
                tool_name=str(getattr(execution, "tool_name", "")),
                display=display,
                renderable=renderable,
            )
        )
    return payloads


__all__ = [
    "MAX_FILE_WRITE_RENDER_LINES",
    "PERSISTED_RENDER_TEXT_MAX_CHARS",
    "STRUCTURED_DIFF_KIND",
    "StructuredDiffRenderable",
    "ToolDisplayPayload",
    "build_unified_diff_display",
    "infer_language",
    "iter_tool_display_payloads",
    "persisted_renderable_payload",
    "structured_diff_from_metadata",
    "structured_diff_from_payload",
    "truncate_render_chars",
    "truncate_render_text",
]
