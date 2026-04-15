"""FileEditTool — exact-string replacement in an existing file.

Matches Claude Code's surgical edit contract: the model provides
``old_string`` plus ``new_string``, and the edit only applies when
``old_string`` occurs exactly once in the file (unless ``replace_all`` is
set). This forces the LLM to ground each edit in enough surrounding context
to be unambiguous — the same discipline Claude Code relies on to keep edits
safe.
"""

from __future__ import annotations

from typing import Any, Mapping

from cli.tools._safe_path import PathOutsideWorkspace, resolve_within_workspace
from cli.tools.base import Tool, ToolContext, ToolResult


class FileEditTool(Tool):
    """Perform an exact-string replacement in a workspace file."""

    name = "FileEdit"
    description = (
        "Perform an exact string replacement in a file. Fails when "
        "'old_string' is not unique unless 'replace_all' is true. Use this "
        "instead of FileWrite for precise edits to existing files."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_string": {
                "type": "string",
                "description": "The exact text to replace.",
            },
            "new_string": {
                "type": "string",
                "description": "Replacement text (must differ from old_string).",
            },
            "replace_all": {
                "type": "boolean",
                "description": "Replace every occurrence instead of failing on ambiguity.",
            },
        },
        "required": ["path", "old_string", "new_string"],
        "additionalProperties": False,
    }

    def permission_action(self, tool_input: Mapping[str, Any]) -> str:
        return f"tool:FileEdit:{tool_input.get('path', '')}"

    def render_preview(self, tool_input: Mapping[str, Any]) -> str:
        path = tool_input.get("path", "?")
        return f"Edit {path}"

    def run(self, tool_input: Mapping[str, Any], context: ToolContext) -> ToolResult:
        raw_path = str(tool_input.get("path") or "").strip()
        old_string = tool_input.get("old_string")
        new_string = tool_input.get("new_string")
        replace_all = bool(tool_input.get("replace_all"))

        if not raw_path:
            return ToolResult.failure("FileEdit requires a 'path'.")
        if not isinstance(old_string, str) or not isinstance(new_string, str):
            return ToolResult.failure(
                "FileEdit requires string 'old_string' and 'new_string'."
            )
        if old_string == new_string:
            return ToolResult.failure(
                "FileEdit 'old_string' and 'new_string' are identical."
            )

        try:
            target = resolve_within_workspace(raw_path, context.workspace_root)
        except PathOutsideWorkspace as exc:
            return ToolResult.failure(str(exc))

        if not target.exists():
            return ToolResult.failure(f"File not found: {raw_path}")
        if target.is_dir():
            return ToolResult.failure(f"Path is a directory: {raw_path}")

        try:
            original = target.read_text(encoding="utf-8")
        except OSError as exc:
            return ToolResult.failure(f"Read failed: {exc}")

        occurrences = original.count(old_string)
        if occurrences == 0:
            return ToolResult.failure(
                "FileEdit 'old_string' not found. Provide more surrounding "
                "context or check for whitespace differences."
            )
        if occurrences > 1 and not replace_all:
            return ToolResult.failure(
                f"FileEdit 'old_string' matches {occurrences} locations. "
                "Expand the context to make it unique, or set replace_all=true."
            )

        updated = (
            original.replace(old_string, new_string)
            if replace_all
            else original.replace(old_string, new_string, 1)
        )

        try:
            target.write_text(updated, encoding="utf-8")
        except OSError as exc:
            return ToolResult.failure(f"Write failed: {exc}")

        replacements = occurrences if replace_all else 1
        return ToolResult.success(
            f"Applied {replacements} replacement(s) to "
            f"{target.relative_to(context.workspace_root)}.",
            metadata={
                "path": str(target),
                "replacements": replacements,
                "replace_all": replace_all,
            },
        )
