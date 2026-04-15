"""GrepTool — regex search across workspace files.

Uses Python's ``re`` module rather than shelling out to ``rg``/``grep`` so
the tool works the same on every platform and never hits the permission
surface of :class:`BashTool`. Results are capped to keep tool_result
payloads bounded.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from cli.tools._safe_path import PathOutsideWorkspace, resolve_within_workspace
from cli.tools.base import Tool, ToolContext, ToolResult


DEFAULT_MATCH_LIMIT = 200
DEFAULT_FILE_LIMIT = 500


class GrepTool(Tool):
    """Return regex matches across workspace files."""

    name = "Grep"
    description = (
        "Search workspace files for a regex pattern. Returns matching lines "
        "with 'path:line: content' prefixes. Supply 'glob' to narrow the "
        "search or 'path' to restrict it to a subtree."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Python regex."},
            "glob": {
                "type": "string",
                "description": "Glob filter applied before matching (e.g. '*.py').",
            },
            "path": {
                "type": "string",
                "description": "Subdirectory to scan (defaults to workspace root).",
            },
            "case_insensitive": {"type": "boolean"},
            "limit": {"type": "integer", "minimum": 1},
        },
        "required": ["pattern"],
        "additionalProperties": False,
    }
    read_only = True

    def permission_action(self, tool_input: Mapping[str, Any]) -> str:
        return "tool:Grep"

    def render_preview(self, tool_input: Mapping[str, Any]) -> str:
        return f"Grep /{tool_input.get('pattern', '?')}/"

    def run(self, tool_input: Mapping[str, Any], context: ToolContext) -> ToolResult:
        pattern_str = str(tool_input.get("pattern") or "").strip()
        if not pattern_str:
            return ToolResult.failure("Grep requires a 'pattern'.")

        flags = re.IGNORECASE if tool_input.get("case_insensitive") else 0
        try:
            pattern = re.compile(pattern_str, flags)
        except re.error as exc:
            return ToolResult.failure(f"Invalid regex: {exc}")

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
            return ToolResult.failure(f"Grep path is not a directory: {base_raw or '.'}")

        glob_filter = str(tool_input.get("glob") or "").strip() or "**/*"
        limit = int(tool_input.get("limit") or DEFAULT_MATCH_LIMIT)

        matches: list[str] = []
        files_scanned = 0
        truncated = False

        for candidate in base.glob(glob_filter):
            if not candidate.is_file():
                continue
            if _is_noisy(candidate):
                continue
            files_scanned += 1
            if files_scanned > DEFAULT_FILE_LIMIT:
                truncated = True
                break
            try:
                text = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    rel = candidate.relative_to(context.workspace_root.resolve())
                    matches.append(f"{rel}:{line_no}:{line}")
                    if len(matches) >= limit:
                        truncated = True
                        break
            if truncated:
                break

        if not matches:
            body = "(no matches)"
        else:
            body = "\n".join(matches)
            if truncated:
                body += f"\n[... truncated at {limit} matches ...]"

        return ToolResult.success(
            body,
            metadata={
                "matches": len(matches),
                "files_scanned": files_scanned,
                "truncated": truncated,
            },
        )


_NOISE_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".tmp",
    ".agentlab",
}


def _is_noisy(path: Path) -> bool:
    """Skip directories that pollute results without carrying signal.

    These mirror the ``.gitignore`` pattern most agentlab workspaces use;
    excluding them here avoids the LLM wasting tokens paging through build
    artifacts or cache files."""
    return any(part in _NOISE_DIRS for part in path.parts)
