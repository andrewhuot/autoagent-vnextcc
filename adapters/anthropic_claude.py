"""Runtime adapter for Anthropic/Claude SDK projects."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from .base import AgentAdapter, ImportedAgentSpec


def _extract_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _extract_value(node: ast.AST, constants: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id, node.id)
    if isinstance(node, ast.List):
        return [_extract_value(item, constants) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return [_extract_value(item, constants) for item in node.elts]
    if isinstance(node, ast.Dict):
        result: dict[str, Any] = {}
        for key, value in zip(node.keys, node.values, strict=False):
            result[str(_extract_value(key, constants))] = _extract_value(value, constants)
        return result
    return _extract_name(node) or ""


def _module_constants(tree: ast.AST) -> dict[str, Any]:
    constants: dict[str, Any] = {}
    for node in getattr(tree, "body", []):
        if not isinstance(node, ast.Assign):
            continue
        value = _extract_value(node.value, constants)
        for target in node.targets:
            if isinstance(target, ast.Name):
                constants[target.id] = value
    return constants


class AnthropicClaudeAdapter(AgentAdapter):
    """Import system prompts, tools, MCP config, and session patterns from Claude SDK projects."""

    adapter_name = "anthropic"
    platform_name = "Anthropic Claude"

    def __init__(self, source: str) -> None:
        super().__init__(source)
        self.root = Path(source).resolve()
        self._cached_spec: ImportedAgentSpec | None = None

    def discover(self) -> ImportedAgentSpec:
        """Scan source files and MCP config for Anthropic runtime features."""

        if self._cached_spec is not None:
            return self._cached_spec

        tools: dict[str, dict[str, Any]] = {}
        guardrails: dict[str, dict[str, Any]] = {}
        system_prompts: list[str] = []
        session_patterns: set[str] = set()
        imported_any = False

        for path in sorted(self.root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            constants = _module_constants(tree)

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "anthropic":
                            imported_any = True
                elif isinstance(node, ast.ImportFrom):
                    if node.module == "anthropic":
                        imported_any = True

                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if not isinstance(target, ast.Name):
                            continue
                        target_name = target.id.lower()
                        value = _extract_value(node.value, constants)
                        if "prompt" in target_name or "system" in target_name:
                            if isinstance(value, str) and value.strip():
                                system_prompts.append(value.strip())
                        if "tool" in target_name and isinstance(value, list):
                            for item in value:
                                if isinstance(item, dict) and item.get("name"):
                                    tools[str(item["name"])] = {
                                        "name": str(item["name"]),
                                        "description": str(item.get("description", "")),
                                        "source_file": str(path),
                                    }
                        if "guardrail" in target_name:
                            guardrails[target.id] = {
                                "name": target.id,
                                "description": "Imported guardrail configuration",
                                "source_file": str(path),
                            }

                if isinstance(node, ast.FunctionDef):
                    decorator_names = [_extract_name(decorator) for decorator in node.decorator_list]
                    if node.name.startswith("tool_") or any(name == "tool" for name in decorator_names):
                        tools[node.name] = {
                            "name": node.name,
                            "description": ast.get_docstring(node) or "",
                            "source_file": str(path),
                        }
                    if "guardrail" in node.name.lower() or any("guardrail" in name.lower() for name in decorator_names):
                        guardrails[node.name] = {
                            "name": node.name,
                            "description": ast.get_docstring(node) or "",
                            "source_file": str(path),
                        }

                if isinstance(node, ast.Call):
                    chain = self._call_chain(node.func)
                    if chain.endswith("messages.create"):
                        session_patterns.add("messages.create")
                    for keyword in node.keywords:
                        if keyword.arg == "system":
                            value = _extract_value(keyword.value, constants)
                            if isinstance(value, str) and value.strip():
                                system_prompts.append(value.strip())

        if not imported_any:
            raise ValueError(f"No Anthropic SDK imports found in {self.root}")

        mcp_refs = self._discover_mcp_refs()
        agent_name = self.root.name or "anthropic-agent"
        spec = ImportedAgentSpec(
            adapter=self.adapter_name,
            source=str(self.root),
            agent_name=agent_name,
            platform=self.platform_name,
            system_prompts=system_prompts,
            tools=list(tools.values()),
            guardrails=list(guardrails.values()),
            mcp_refs=mcp_refs,
            session_patterns=sorted(session_patterns),
            metadata={"source_type": "anthropic_sdk"},
        )
        spec.ensure_defaults()
        self._cached_spec = spec
        return spec

    def import_traces(self) -> list[dict[str, Any]]:
        """Anthropic source imports do not include traces by default."""

        return list(self.discover().traces)

    def import_tools(self) -> list[dict[str, Any]]:
        """Return imported tool definitions."""

        return list(self.discover().tools)

    def import_guardrails(self) -> list[dict[str, Any]]:
        """Return imported guardrail definitions."""

        return list(self.discover().guardrails)

    def _discover_mcp_refs(self) -> list[dict[str, Any]]:
        """Load MCP server references from common config files."""

        refs: list[dict[str, Any]] = []
        for path in (self.root / ".mcp.json", self.root / "mcp.json"):
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            for name, config in dict(payload.get("mcpServers", {}) or {}).items():
                refs.append(
                    {
                        "name": name,
                        "config": config,
                        "source_file": str(path),
                    }
                )
        return refs

    @staticmethod
    def _call_chain(node: ast.AST) -> str:
        """Return a dotted call chain for a function node."""

        parts: list[str] = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))
