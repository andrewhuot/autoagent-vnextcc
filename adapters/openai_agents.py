"""Runtime adapter for OpenAI Agents-style Python projects."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from .base import AgentAdapter, ImportedAgentSpec, keyword_candidates


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


def _extract_function_parameters(node: ast.FunctionDef) -> list[dict[str, Any]]:
    """Extract typed parameter info from a function definition's AST."""
    params: list[dict[str, Any]] = []
    args = node.args

    num_defaults = len(args.defaults)
    num_args = len(args.args)
    for i, arg in enumerate(args.args):
        if arg.arg == "self":
            continue
        param: dict[str, Any] = {"name": arg.arg, "type": "string", "required": True}
        if arg.annotation:
            param["type"] = _annotation_to_str(arg.annotation)
        default_index = i - (num_args - num_defaults)
        if default_index >= 0:
            param["required"] = False
            default_val = _extract_value(args.defaults[default_index], {})
            if default_val is not None:
                param["default"] = default_val
        params.append(param)
    return params


def _annotation_to_str(node: ast.AST) -> str:
    """Convert an AST annotation node to a type string."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant):
        return str(node.value)
    if isinstance(node, ast.Attribute):
        return f"{_annotation_to_str(node.value)}.{node.attr}"
    if isinstance(node, ast.Subscript):
        return f"{_annotation_to_str(node.value)}[{_annotation_to_str(node.slice)}]"
    return "string"


class OpenAIAgentsAdapter(AgentAdapter):
    """Import agent topology from projects built with OpenAI Agents."""

    adapter_name = "openai-agents"
    platform_name = "OpenAI Agents"

    def __init__(self, source: str) -> None:
        super().__init__(source)
        self.root = Path(source).resolve()
        self._cached_spec: ImportedAgentSpec | None = None

    def discover(self) -> ImportedAgentSpec:
        """Scan Python files for Agent definitions, tools, and handoffs."""

        if self._cached_spec is not None:
            return self._cached_spec

        tools: dict[str, dict[str, Any]] = {}
        guardrails: dict[str, dict[str, Any]] = {}
        agents: list[dict[str, Any]] = []
        mcp_refs: dict[str, dict[str, Any]] = {}
        imported_any = False

        for path in sorted(self.root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            constants = _module_constants(tree)
            parsed_assignments: set[int] = set()

            for node in getattr(tree, "body", []):
                if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                    continue
                if _extract_name(node.value.func) != "Agent":
                    continue

                agent_name = ""
                instructions = ""
                handoffs: list[str] = []
                declared_tools: list[str] = []
                for keyword in node.value.keywords:
                    if keyword.arg == "name":
                        agent_name = str(_extract_value(keyword.value, constants))
                    elif keyword.arg in {"instructions", "system", "prompt"}:
                        instructions = str(_extract_value(keyword.value, constants))
                    elif keyword.arg == "tools":
                        raw_tools = _extract_value(keyword.value, constants)
                        if isinstance(raw_tools, list):
                            declared_tools = [str(item) for item in raw_tools if item]
                    elif keyword.arg == "handoffs":
                        raw_handoffs = _extract_value(keyword.value, constants)
                        if isinstance(raw_handoffs, list):
                            handoffs = [str(item) for item in raw_handoffs if item]

                for target in node.targets:
                    if isinstance(target, ast.Name) and agent_name:
                        constants[target.id] = agent_name

                for tool_name in declared_tools:
                    tools.setdefault(
                        tool_name,
                        {"name": tool_name, "description": "", "source_file": str(path)},
                    )
                agents.append(
                    {
                        "name": agent_name or path.stem,
                        "instructions": instructions,
                        "tools": declared_tools,
                        "handoffs": handoffs,
                        "source_file": str(path),
                    }
                )
                parsed_assignments.add(id(node.value))

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in {"agents", "openai_agents"}:
                            imported_any = True
                elif isinstance(node, ast.ImportFrom):
                    if node.module in {"agents", "openai_agents"}:
                        imported_any = True

                if isinstance(node, ast.FunctionDef):
                    decorator_names = [_extract_name(decorator) for decorator in node.decorator_list]
                    if "function_tool" in decorator_names:
                        tool_entry: dict[str, Any] = {
                            "name": node.name,
                            "description": ast.get_docstring(node) or "",
                            "source_file": str(path),
                        }
                        fn_params = _extract_function_parameters(node)
                        if fn_params:
                            tool_entry["parameters"] = fn_params
                        tools[node.name] = tool_entry
                    if "guardrail" in node.name.lower() or any("guardrail" in name.lower() for name in decorator_names):
                        guardrails[node.name] = {
                            "name": node.name,
                            "description": ast.get_docstring(node) or "",
                            "source_file": str(path),
                        }

                if isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and "guardrail" in target.id.lower()
                    for target in node.targets
                ):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            guardrails[target.id] = {
                                "name": target.id,
                                "description": "Imported guardrail configuration",
                                "source_file": str(path),
                            }

                if isinstance(node, ast.Call) and _extract_name(node.func) == "Agent" and id(node) not in parsed_assignments:
                    agent_name = ""
                    instructions = ""
                    handoffs: list[str] = []
                    declared_tools: list[str] = []
                    for keyword in node.keywords:
                        if keyword.arg == "name":
                            agent_name = str(_extract_value(keyword.value, constants))
                        elif keyword.arg in {"instructions", "system", "prompt"}:
                            instructions = str(_extract_value(keyword.value, constants))
                        elif keyword.arg == "tools":
                            raw_tools = _extract_value(keyword.value, constants)
                            if isinstance(raw_tools, list):
                                declared_tools = [str(item) for item in raw_tools if item]
                        elif keyword.arg == "handoffs":
                            raw_handoffs = _extract_value(keyword.value, constants)
                            if isinstance(raw_handoffs, list):
                                handoffs = [str(item) for item in raw_handoffs if item]
                        elif keyword.arg and "mcp" in keyword.arg.lower():
                            mcp_name = str(_extract_value(keyword.value, constants))
                            if mcp_name:
                                mcp_refs[mcp_name] = {"name": mcp_name, "source_file": str(path)}

                    for tool_name in declared_tools:
                        tools.setdefault(
                            tool_name,
                            {"name": tool_name, "description": "", "source_file": str(path)},
                        )
                    agents.append(
                        {
                            "name": agent_name or path.stem,
                            "instructions": instructions,
                            "tools": declared_tools,
                            "handoffs": handoffs,
                            "source_file": str(path),
                        }
                    )

                if isinstance(node, ast.Name) and node.id.startswith("MCP"):
                    mcp_refs.setdefault(node.id, {"name": node.id, "source_file": str(path)})

        if not imported_any:
            raise ValueError(f"No OpenAI Agents imports found in {self.root}")

        primary_agent = max(
            agents or [{"name": self.root.name, "instructions": "", "tools": [], "handoffs": []}],
            key=lambda item: (
                len(item.get("tools", [])) + len(item.get("handoffs", [])),
                len(item.get("instructions", "")),
                len(item.get("name", "")),
            ),
        )
        handoff_edges = [
            {
                "source": primary_agent["name"],
                "target": handoff,
            }
            for handoff in primary_agent.get("handoffs", [])
        ]
        system_prompts: list[str] = []
        if primary_agent.get("instructions"):
            system_prompts.append(primary_agent["instructions"])
        for item in agents:
            instructions = item.get("instructions")
            if instructions and instructions not in system_prompts:
                system_prompts.append(instructions)
        spec = ImportedAgentSpec(
            adapter=self.adapter_name,
            source=str(self.root),
            agent_name=primary_agent["name"],
            platform=self.platform_name,
            system_prompts=system_prompts,
            tools=list(tools.values()),
            guardrails=list(guardrails.values()),
            handoffs=handoff_edges,
            mcp_refs=list(mcp_refs.values()),
            metadata={
                "detected_agents": [item["name"] for item in agents],
                "keywords": keyword_candidates(primary_agent.get("instructions", "")),
            },
        )
        spec.ensure_defaults()
        self._cached_spec = spec
        return spec

    def import_traces(self) -> list[dict[str, Any]]:
        """OpenAI source import does not provide transcript data by default."""

        return list(self.discover().traces)

    def import_tools(self) -> list[dict[str, Any]]:
        """Return tools inferred from source code."""

        return list(self.discover().tools)

    def import_guardrails(self) -> list[dict[str, Any]]:
        """Return guardrails inferred from source code."""

        return list(self.discover().guardrails)
