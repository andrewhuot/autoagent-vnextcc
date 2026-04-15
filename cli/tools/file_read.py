"""FileReadTool — read text files inside the workspace.

Claude Code parity notes:
* Returns the contents with ``cat -n`` style 1-indexed line numbers because
  the LLM needs them to target later :class:`FileEditTool` calls precisely.
* Enforces a line cap to keep tool_result payloads bounded (a runaway
  ``find . -name '*.log' | xargs cat`` equivalent would otherwise blow the
  context window).
* Read-only so it's safe to auto-allow in plan mode.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from cli.tools._safe_path import PathOutsideWorkspace, resolve_within_workspace
from cli.tools.base import Tool, ToolContext, ToolResult


DEFAULT_READ_LIMIT = 2000
"""Maximum lines returned per call — mirrors Claude Code's default so tool
outputs stay bounded without forcing callers to paginate."""


class FileReadTool(Tool):
    """Return file contents with 1-indexed line prefixes."""

    name = "FileRead"
    description = (
        "Read a text file from the workspace. Returns contents prefixed with "
        "1-indexed line numbers so subsequent FileEdit calls can reference "
        "them. Pass ``offset`` / ``limit`` to read a slice of a large file."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Workspace-relative or absolute path (must "
                "resolve inside the workspace root).",
            },
            "offset": {
                "type": "integer",
                "minimum": 0,
                "description": "Zero-based line number to start reading at.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "description": "Maximum lines to return. Defaults to 2000.",
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    }
    read_only = True

    def permission_action(self, tool_input: Mapping[str, Any]) -> str:
        return f"tool:FileRead:{tool_input.get('path', '')}"

    def render_preview(self, tool_input: Mapping[str, Any]) -> str:
        return f"Read {tool_input.get('path', '?')}"

    def run(self, tool_input: Mapping[str, Any], context: ToolContext) -> ToolResult:
        raw_path = str(tool_input.get("path") or "").strip()
        if not raw_path:
            return ToolResult.failure("FileRead requires a 'path'.")
        try:
            target = resolve_within_workspace(raw_path, context.workspace_root)
        except PathOutsideWorkspace as exc:
            return ToolResult.failure(str(exc))

        if not target.exists():
            return ToolResult.failure(f"File not found: {raw_path}")
        if target.is_dir():
            return ToolResult.failure(f"Path is a directory: {raw_path}")

        offset = int(tool_input.get("offset") or 0)
        limit = int(tool_input.get("limit") or DEFAULT_READ_LIMIT)

        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return ToolResult.failure(f"Read failed: {exc}")

        lines = text.splitlines()
        total_lines = len(lines)
        slice_end = min(offset + limit, total_lines)
        window = lines[offset:slice_end]
        numbered = "\n".join(
            f"{idx + 1:>6}\t{line}" for idx, line in enumerate(window, start=offset)
        )
        truncated = slice_end < total_lines
        if truncated:
            numbered += f"\n[... truncated at line {slice_end} of {total_lines} ...]"
        return ToolResult.success(
            numbered,
            metadata={
                "path": str(target),
                "total_lines": total_lines,
                "returned_lines": slice_end - offset,
                "truncated": truncated,
            },
        )
