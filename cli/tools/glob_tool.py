"""GlobTool — find files by glob pattern, newest first.

We deliberately do *not* shell out to ``find`` — ``pathlib.Path.rglob``
with a capped result set is portable and avoids the permission exposure a
full BashTool invocation would carry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from cli.tools._safe_path import PathOutsideWorkspace, resolve_within_workspace
from cli.tools.base import Tool, ToolContext, ToolResult


DEFAULT_LIMIT = 250


class GlobTool(Tool):
    """Return workspace paths matching a glob, ordered by most recent mtime."""

    name = "Glob"
    description = (
        "Find files matching a glob pattern (e.g. 'configs/*.yaml', "
        "'agent/**/*.py'). Returns up to 250 paths by default, sorted by "
        "modification time (newest first)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern interpreted relative to the workspace.",
            },
            "path": {
                "type": "string",
                "description": "Optional subdirectory to search under.",
            },
            "limit": {"type": "integer", "minimum": 1},
        },
        "required": ["pattern"],
        "additionalProperties": False,
    }
    read_only = True
    is_concurrency_safe = True

    def permission_action(self, tool_input: Mapping[str, Any]) -> str:
        return "tool:Glob"

    def render_preview(self, tool_input: Mapping[str, Any]) -> str:
        return f"Glob {tool_input.get('pattern', '?')}"

    def run(self, tool_input: Mapping[str, Any], context: ToolContext) -> ToolResult:
        pattern = str(tool_input.get("pattern") or "").strip()
        if not pattern:
            return ToolResult.failure("Glob requires a 'pattern'.")

        base_raw = str(tool_input.get("path") or "").strip()
        try:
            base = (
                resolve_within_workspace(base_raw, context.workspace_root)
                if base_raw
                else context.workspace_root.resolve()
            )
        except PathOutsideWorkspace as exc:
            return ToolResult.failure(str(exc))
        if not base.is_dir():
            return ToolResult.failure(f"Glob base path is not a directory: {base_raw or '.'}")

        limit = int(tool_input.get("limit") or DEFAULT_LIMIT)

        matches: list[Path] = []
        try:
            for match in base.glob(pattern):
                if match.is_file():
                    matches.append(match)
        except (OSError, ValueError) as exc:
            return ToolResult.failure(f"Glob failed: {exc}")

        matches.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        truncated = len(matches) > limit
        matches = matches[:limit]

        relative = [
            str(path.relative_to(context.workspace_root.resolve()))
            for path in matches
        ]
        body = "\n".join(relative) if relative else "(no matches)"
        if truncated:
            body += f"\n[... truncated at {limit} matches ...]"
        return ToolResult.success(
            body,
            metadata={"count": len(relative), "truncated": truncated},
        )
