"""ConfigEditTool — schema-validated edits to agent configs.

Unlike :class:`FileEditTool`, this tool takes *structured* changes (a dotted
key path plus a new value) and validates the resulting document against
``AgentConfig`` before writing. If validation fails, the file is not
touched and the error is returned to the LLM so it can try again.

This is the "safety rail" tool for the optimization loop — the surface area
where agentlab's UX diverges most from Claude Code's generic-repo story.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from cli.tools._safe_path import PathOutsideWorkspace, resolve_within_workspace
from cli.tools.base import Tool, ToolContext, ToolResult


class ConfigEditTool(Tool):
    """Apply a validated change to an agent config file."""

    name = "ConfigEdit"
    description = (
        "Set a dotted key in an agent configuration file. Parses the file, "
        "applies the change, re-validates against the AgentConfig schema, "
        "and only writes when validation passes. Use this instead of "
        "FileEdit for structured config changes."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "key": {
                "type": "string",
                "description": "Dotted path, e.g. 'optimizer.search_max_candidates'.",
            },
            "value": {
                "description": "New value. Strings, numbers, booleans, arrays, and objects are supported.",
            },
            "delete": {
                "type": "boolean",
                "description": "When true, remove the key instead of setting it.",
            },
        },
        "required": ["path", "key"],
        "additionalProperties": False,
    }

    def permission_action(self, tool_input: Mapping[str, Any]) -> str:
        return f"tool:ConfigEdit:{tool_input.get('path', '')}"

    def render_preview(self, tool_input: Mapping[str, Any]) -> str:
        path = tool_input.get("path", "?")
        key = tool_input.get("key", "?")
        if tool_input.get("delete"):
            return f"ConfigEdit {path}: delete {key}"
        value = tool_input.get("value")
        return f"ConfigEdit {path}: {key} = {value!r}"

    def run(self, tool_input: Mapping[str, Any], context: ToolContext) -> ToolResult:
        raw_path = str(tool_input.get("path") or "").strip()
        key = str(tool_input.get("key") or "").strip()
        delete = bool(tool_input.get("delete"))
        if not raw_path:
            return ToolResult.failure("ConfigEdit requires a 'path'.")
        if not key:
            return ToolResult.failure("ConfigEdit requires a 'key'.")
        if not delete and "value" not in tool_input:
            return ToolResult.failure("ConfigEdit requires 'value' unless delete=true.")

        try:
            target = resolve_within_workspace(raw_path, context.workspace_root)
        except PathOutsideWorkspace as exc:
            return ToolResult.failure(str(exc))
        if not target.exists():
            return ToolResult.failure(f"Config not found: {raw_path}")
        if target.is_dir():
            return ToolResult.failure(f"Path is a directory: {raw_path}")

        suffix = target.suffix.lower()
        try:
            raw = target.read_text(encoding="utf-8")
        except OSError as exc:
            return ToolResult.failure(f"Read failed: {exc}")

        parsed, parse_error = _load(raw, suffix)
        if parse_error:
            return ToolResult.failure(f"Parse failed: {parse_error}")
        if not isinstance(parsed, dict):
            return ToolResult.failure("ConfigEdit only supports mapping top-level configs.")

        updated, mutation_error = _apply_change(
            parsed, key.split("."), tool_input.get("value"), delete
        )
        if mutation_error:
            return ToolResult.failure(mutation_error)

        validation = _validate(updated)
        if validation and not validation.get("ok", True):
            return ToolResult.failure(
                f"ConfigEdit rejected: schema validation failed.\n{validation.get('error')}"
            )

        try:
            target.write_text(_dump(updated, suffix), encoding="utf-8")
        except OSError as exc:
            return ToolResult.failure(f"Write failed: {exc}")

        verb = "removed" if delete else "updated"
        return ToolResult.success(
            f"ConfigEdit: {verb} {key} in "
            f"{target.relative_to(context.workspace_root.resolve())}.",
            metadata={
                "path": str(target),
                "key": key,
                "operation": "delete" if delete else "set",
            },
        )


def _load(raw: str, suffix: str) -> tuple[Any, str | None]:
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError:
            return None, "PyYAML is not installed."
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


def _dump(data: Any, suffix: str) -> str:
    if suffix in {".yaml", ".yml"}:
        import yaml

        return yaml.safe_dump(data, sort_keys=False, default_flow_style=False)
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def _apply_change(
    root: dict[str, Any],
    path_parts: list[str],
    value: Any,
    delete: bool,
) -> tuple[dict[str, Any], str | None]:
    """Set or delete a nested key. Returns a fresh dict — callers should use
    the returned value rather than relying on in-place mutation, so a failed
    ``_validate`` does not leave the original object half-mutated."""
    if not path_parts:
        return root, "ConfigEdit 'key' is empty after splitting."

    # Shallow copy chain so we can unwind cleanly on validation failure.
    working: dict[str, Any] = dict(root)
    cursor = working
    for part in path_parts[:-1]:
        node = cursor.get(part)
        if node is None:
            if delete:
                return root, f"ConfigEdit cannot delete non-existent key '{'.'.join(path_parts)}'."
            node = {}
        elif not isinstance(node, dict):
            return root, (
                f"ConfigEdit cannot descend into '{part}': value is "
                f"{type(node).__name__}, not a mapping."
            )
        new_node = dict(node)
        cursor[part] = new_node
        cursor = new_node

    leaf = path_parts[-1]
    if delete:
        if leaf not in cursor:
            return root, f"ConfigEdit cannot delete missing key '{'.'.join(path_parts)}'."
        cursor.pop(leaf)
    else:
        cursor[leaf] = value
    return working, None


def _validate(parsed: dict[str, Any]) -> dict[str, Any] | None:
    """Validate against AgentConfig when available. Return ``None`` when the
    file is not an agent spec (optimizer-only ``agentlab.yaml`` etc.)."""
    try:
        from agent.config.schema import AgentConfig  # type: ignore
    except Exception:
        return None
    # Heuristic: only full agent configs declare the ``agent_id`` or ``prompts``
    # keys. Optimizer-only files (agentlab.yaml) skip schema validation.
    if not any(key in parsed for key in ("agent_id", "prompts", "tools", "policy")):
        return None
    try:
        AgentConfig.model_validate(parsed)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True}
