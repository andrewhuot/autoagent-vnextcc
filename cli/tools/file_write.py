"""FileWriteTool — create or overwrite a text file in the workspace.

Separate from :class:`FileEditTool` because overwriting is a distinct
permission concept: the LLM declares up front that it intends to replace
the whole file, and the permission dialog can show a size delta rather than
a surgical diff.
"""

from __future__ import annotations

from typing import Any, Mapping

from cli.tools._safe_path import PathOutsideWorkspace, resolve_within_workspace
from cli.tools.base import Tool, ToolContext, ToolResult


class FileWriteTool(Tool):
    """Create a new file or overwrite an existing one."""

    name = "FileWrite"
    description = (
        "Create a new file or overwrite an existing file with the given "
        "content. Prefer FileEdit for surgical changes to existing files — "
        "FileWrite replaces the file wholesale."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Workspace-relative or absolute path.",
            },
            "content": {
                "type": "string",
                "description": "Full file contents to write.",
            },
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }

    def permission_action(self, tool_input: Mapping[str, Any]) -> str:
        return f"tool:FileWrite:{tool_input.get('path', '')}"

    def render_preview(self, tool_input: Mapping[str, Any]) -> str:
        path = tool_input.get("path", "?")
        size = len(str(tool_input.get("content", "")))
        return f"Write {path} ({size} bytes)"

    def run(self, tool_input: Mapping[str, Any], context: ToolContext) -> ToolResult:
        raw_path = str(tool_input.get("path") or "").strip()
        if not raw_path:
            return ToolResult.failure("FileWrite requires a 'path'.")
        content = tool_input.get("content")
        if content is None:
            return ToolResult.failure("FileWrite requires 'content'.")
        if not isinstance(content, str):
            return ToolResult.failure("FileWrite 'content' must be a string.")

        try:
            target = resolve_within_workspace(raw_path, context.workspace_root)
        except PathOutsideWorkspace as exc:
            return ToolResult.failure(str(exc))

        existed = target.exists()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            return ToolResult.failure(f"Write failed: {exc}")

        verb = "Overwrote" if existed else "Created"
        return ToolResult.success(
            f"{verb} {target.relative_to(context.workspace_root)} "
            f"({len(content)} bytes).",
            metadata={
                "path": str(target),
                "bytes": len(content),
                "created": not existed,
            },
        )
