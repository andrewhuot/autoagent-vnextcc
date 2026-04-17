"""ConfigReadTool — schema-aware read of agent configs.

Distinct from :class:`FileReadTool` because configs are small, structured,
and the LLM benefits from a normalised view: we parse the YAML, emit it
back as canonical JSON (sorted keys, stable float formatting), and return
any schema-validation warnings alongside the body. The result is suitable
for a subsequent :class:`ConfigEditTool` call.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from cli.tools._safe_path import PathOutsideWorkspace, resolve_within_workspace
from cli.tools.base import Tool, ToolContext, ToolResult


class ConfigReadTool(Tool):
    """Parse and return an agent config (YAML or JSON) as structured data."""

    name = "ConfigRead"
    description = (
        "Read and parse an agent configuration file (YAML or JSON). Returns "
        "the parsed data as JSON plus a validation summary against the "
        "AgentConfig / AgentLab schemas when the file matches one."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Workspace-relative or absolute path to the config.",
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    }
    read_only = True
    is_concurrency_safe = True

    def permission_action(self, tool_input: Mapping[str, Any]) -> str:
        return f"tool:ConfigRead:{tool_input.get('path', '')}"

    def render_preview(self, tool_input: Mapping[str, Any]) -> str:
        return f"ConfigRead {tool_input.get('path', '?')}"

    def run(self, tool_input: Mapping[str, Any], context: ToolContext) -> ToolResult:
        raw_path = str(tool_input.get("path") or "").strip()
        if not raw_path:
            return ToolResult.failure("ConfigRead requires a 'path'.")
        try:
            target = resolve_within_workspace(raw_path, context.workspace_root)
        except PathOutsideWorkspace as exc:
            return ToolResult.failure(str(exc))
        if not target.exists():
            return ToolResult.failure(f"Config not found: {raw_path}")
        if target.is_dir():
            return ToolResult.failure(f"Path is a directory: {raw_path}")

        try:
            raw = target.read_text(encoding="utf-8")
        except OSError as exc:
            return ToolResult.failure(f"Read failed: {exc}")

        parsed, parse_error = _parse_config(target, raw)
        if parse_error:
            return ToolResult.failure(f"Parse failed: {parse_error}")

        validation = _validate_against_schema(target, parsed)
        body = {
            "path": str(target.relative_to(context.workspace_root.resolve())),
            "format": "yaml" if target.suffix.lower() in {".yaml", ".yml"} else "json",
            "data": parsed,
            "validation": validation,
        }
        return ToolResult.success(
            json.dumps(body, indent=2, sort_keys=True, default=str),
            metadata={"path": str(target), "valid": validation.get("ok", True)},
        )


def _parse_config(path: Path, raw: str) -> tuple[Any, str | None]:
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError:
            return None, "PyYAML is not installed; cannot parse YAML."
        try:
            return yaml.safe_load(raw), None
        except yaml.YAMLError as exc:
            return None, str(exc)
    if suffix == ".json":
        try:
            return json.loads(raw), None
        except json.JSONDecodeError as exc:
            return None, str(exc)
    return None, f"Unsupported config suffix: {suffix or '(none)'}"


def _validate_against_schema(path: Path, parsed: Any) -> dict[str, Any]:
    """Best-effort validation against the agentlab schema.

    We try ``AgentConfig`` (from ``agent/config/schema.py``) when the file
    looks like an agent spec. On any failure we report a structured warning
    rather than refusing the read — the LLM still benefits from the parsed
    body, and the validation hint tells it what to fix.
    """
    if not isinstance(parsed, dict):
        return {"ok": True, "note": "top-level value is not a mapping; schema check skipped"}
    try:
        from agent.config.schema import AgentConfig  # type: ignore
    except Exception:
        return {"ok": True, "note": "AgentConfig schema unavailable"}
    try:
        AgentConfig.model_validate(parsed)
    except Exception as exc:  # pydantic ValidationError or missing deps
        return {"ok": False, "error": str(exc)}
    return {"ok": True}
