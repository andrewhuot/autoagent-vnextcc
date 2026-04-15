"""TodoWriteTool — persist the agent's working todo list.

Claude Code surfaces a live todo pane so users can see the LLM's plan and
how much of it is still outstanding. agentlab stores the same structure on
disk at ``.agentlab/todos.json`` so any UI layer (REPL, workbench, future
web UI) can read the state without a service call.

Design notes:

* Partial updates are first-class: if the caller includes an ``id`` that
  already exists, we update that entry in place; otherwise the item is
  appended with a new uuid4. This lets the LLM tick off a single todo
  without resending the entire list.
* We validate item shape defensively — the LLM will sometimes hallucinate
  extra fields or wrong status values, and dropping them at the tool
  boundary is cheaper than chasing downstream crashes.
* The file is written atomically (write tmp, rename) so a crash mid-write
  does not leave a half-valid JSON blob behind.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Mapping

from cli.tools.base import Tool, ToolContext, ToolResult


VALID_STATUSES = {"pending", "in_progress", "completed"}
TODO_RELPATH = Path(".agentlab") / "todos.json"


class TodoWriteTool(Tool):
    """Create or update the workspace todo list."""

    name = "TodoWrite"
    description = (
        "Persist the agent's working todo list to .agentlab/todos.json. "
        "Supports partial updates: items with a known id update in place, "
        "items without an id are appended with a generated uuid."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": sorted(VALID_STATUSES),
                        },
                        "id": {"type": "string"},
                    },
                    "required": ["content", "status"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["items"],
        "additionalProperties": False,
    }
    read_only = False

    def permission_action(self, tool_input: Mapping[str, Any]) -> str:
        return "tool:TodoWrite"

    def render_preview(self, tool_input: Mapping[str, Any]) -> str:
        items = tool_input.get("items") or []
        return f"TodoWrite ({len(items)} items)"

    def run(self, tool_input: Mapping[str, Any], context: ToolContext) -> ToolResult:
        items = tool_input.get("items")
        if not isinstance(items, list):
            return ToolResult.failure("TodoWrite requires 'items' to be a list.")

        normalised: list[dict[str, Any]] = []
        for idx, entry in enumerate(items):
            if not isinstance(entry, Mapping):
                return ToolResult.failure(
                    f"TodoWrite item #{idx} must be an object."
                )
            content = entry.get("content")
            status = entry.get("status")
            if not isinstance(content, str) or not content.strip():
                return ToolResult.failure(
                    f"TodoWrite item #{idx} missing non-empty 'content'."
                )
            if status not in VALID_STATUSES:
                return ToolResult.failure(
                    f"TodoWrite item #{idx} has invalid status {status!r}; "
                    f"expected one of {sorted(VALID_STATUSES)}."
                )
            item: dict[str, Any] = {
                "content": content.strip(),
                "status": status,
            }
            raw_id = entry.get("id")
            if raw_id is not None:
                if not isinstance(raw_id, str) or not raw_id.strip():
                    return ToolResult.failure(
                        f"TodoWrite item #{idx} has invalid 'id'."
                    )
                item["id"] = raw_id.strip()
            normalised.append(item)

        todo_path = context.workspace_root / TODO_RELPATH
        existing = _load_existing(todo_path)
        merged = _merge_items(existing, normalised)
        _atomic_write(todo_path, merged)

        by_status: dict[str, int] = {status: 0 for status in VALID_STATUSES}
        for item in merged:
            by_status[item["status"]] = by_status.get(item["status"], 0) + 1

        summary = _summarise(len(merged), by_status)
        return ToolResult(
            ok=True,
            content=summary,
            metadata={
                "count": len(merged),
                "by_status": by_status,
                "path": str(todo_path),
            },
        )


def _load_existing(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        if "content" not in entry or "status" not in entry:
            continue
        if entry["status"] not in VALID_STATUSES:
            continue
        cleaned.append(
            {
                "id": entry.get("id") or uuid.uuid4().hex,
                "content": entry["content"],
                "status": entry["status"],
            }
        )
    return cleaned


def _merge_items(
    existing: list[dict[str, Any]], incoming: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {item["id"]: dict(item) for item in existing}
    order: list[str] = [item["id"] for item in existing]
    for item in incoming:
        item_id = item.get("id")
        if item_id and item_id in by_id:
            by_id[item_id].update({
                "content": item["content"],
                "status": item["status"],
            })
            continue
        new_id = item_id or uuid.uuid4().hex
        by_id[new_id] = {
            "id": new_id,
            "content": item["content"],
            "status": item["status"],
        }
        order.append(new_id)
    return [by_id[ident] for ident in order]


def _atomic_write(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(items, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _summarise(total: int, by_status: Mapping[str, int]) -> str:
    parts = []
    completed = by_status.get("completed", 0)
    in_progress = by_status.get("in_progress", 0)
    pending = by_status.get("pending", 0)
    if completed:
        parts.append(f"{completed} completed")
    if in_progress:
        parts.append(f"{in_progress} in progress")
    if pending:
        parts.append(f"{pending} pending")
    suffix = ", ".join(parts) if parts else "empty list"
    return f"Updated {total} todo{'s' if total != 1 else ''} — {suffix}"
