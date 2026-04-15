"""BashTool — run a shell command in the workspace.

This is the permission-heaviest workspace tool. We scope it tightly:

* CWD is always the workspace root; the LLM can ``cd`` inside a single
  command but the process does not inherit arbitrary directories.
* A configurable timeout (default 120 s) prevents runaway commands from
  hanging the workbench.
* Output is captured and truncated so multi-megabyte logs don't flood the
  tool_result.

The tool intentionally *does not* try to sandbox destructive actions —
that's the permission dialog's job (see
:class:`cli.workbench_app.permission_dialog`). Plan mode denies this tool
by default (``read_only`` is False and plan mode's allow-list excludes it).
"""

from __future__ import annotations

import subprocess
from typing import Any, Mapping

from cli.tools.base import Tool, ToolContext, ToolResult


DEFAULT_TIMEOUT_SECONDS = 120
OUTPUT_TRUNCATION_LIMIT = 30_000


class BashTool(Tool):
    """Execute a shell command in the workspace root."""

    name = "Bash"
    description = (
        "Execute a shell command (bash) from the workspace root. Captures "
        "stdout and stderr, truncates very long output. Command is subject "
        "to the active permission mode — plan mode blocks it."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command line (executed via bash -c).",
            },
            "timeout_seconds": {
                "type": "integer",
                "minimum": 1,
                "maximum": 600,
                "description": "Override the default 120-second timeout.",
            },
        },
        "required": ["command"],
        "additionalProperties": False,
    }

    def permission_action(self, tool_input: Mapping[str, Any]) -> str:
        return f"tool:Bash:{tool_input.get('command', '')}"

    def render_preview(self, tool_input: Mapping[str, Any]) -> str:
        command = str(tool_input.get("command", ""))
        return f"Bash> {command[:200]}"

    def run(self, tool_input: Mapping[str, Any], context: ToolContext) -> ToolResult:
        command = str(tool_input.get("command") or "").strip()
        if not command:
            return ToolResult.failure("Bash requires a 'command'.")
        timeout = int(tool_input.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)

        try:
            completed = subprocess.run(
                ["bash", "-c", command],
                cwd=str(context.workspace_root.resolve()),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError:
            return ToolResult.failure("bash is not available on this system.")
        except subprocess.TimeoutExpired as exc:
            partial = (exc.stdout or "") + (exc.stderr or "")
            return ToolResult.failure(
                f"Command timed out after {timeout}s.\n{_truncate(partial)}"
            )

        stdout = _truncate(completed.stdout or "")
        stderr = _truncate(completed.stderr or "")
        body_sections = []
        if stdout:
            body_sections.append(stdout)
        if stderr:
            body_sections.append(f"[stderr]\n{stderr}")
        body = "\n".join(body_sections) or "(no output)"
        body += f"\n[exit code {completed.returncode}]"

        return ToolResult(
            ok=completed.returncode == 0,
            content=body,
            metadata={
                "exit_code": completed.returncode,
                "command": command,
            },
        )


def _truncate(text: str) -> str:
    if len(text) <= OUTPUT_TRUNCATION_LIMIT:
        return text
    head = text[: OUTPUT_TRUNCATION_LIMIT]
    return head + f"\n[... truncated after {OUTPUT_TRUNCATION_LIMIT} chars ...]"
