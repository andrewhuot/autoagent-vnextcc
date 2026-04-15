"""Tool registry.

The registry is a thin in-memory dict keyed by tool name. We keep it simple
on purpose: Claude Code's registry layers plugin/MCP/bundled sources, but
agentlab starts with bundled Python tools only and will grow to the MCP layer
once :mod:`cli.mcp_runtime` exposes an executor.

The ``default_registry()`` factory returns a singleton populated with the
Phase-1 workspace and agent-config tools. Tests instantiate an empty
:class:`ToolRegistry` so they can register fakes without leaking state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from cli.tools.base import Tool, ToolError


@dataclass
class ToolRegistry:
    """Mutable collection of :class:`Tool` instances keyed by tool name.

    The registry is intentionally not a module-level singleton; callers that
    want the shared instance use :func:`default_registry`. Tests construct
    their own instance and register stubs so they do not inherit the built-in
    set.
    """

    tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        """Register ``tool``; raises :class:`ToolError` on a name collision so
        we never silently shadow a bundled tool."""
        if tool.name in self.tools:
            raise ToolError(f"Tool already registered: {tool.name}")
        self.tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        """Return the registered tool or raise :class:`ToolError`."""
        try:
            return self.tools[name]
        except KeyError as exc:
            raise ToolError(f"Unknown tool: {name}") from exc

    def has(self, name: str) -> bool:
        return name in self.tools

    def list(self) -> list[Tool]:
        """Return tools sorted by name for stable display."""
        return [self.tools[name] for name in sorted(self.tools)]

    def to_schema(self) -> list[dict]:
        """Return Anthropic-shape tool definitions suitable for a model call."""
        return [tool.to_schema_entry() for tool in self.list()]

    def extend(self, tools: Iterable[Tool]) -> None:
        for tool in tools:
            self.register(tool)


_DEFAULT: ToolRegistry | None = None


def default_registry() -> ToolRegistry:
    """Return the process-wide registry, lazily populated with built-ins.

    Lazy population matters because importing every tool eagerly would drag
    in ``subprocess`` (BashTool) and ``yaml`` (ConfigTool) at workbench boot,
    breaking the fast-path startup we share with Claude Code's design.
    """
    global _DEFAULT
    if _DEFAULT is None:
        registry = ToolRegistry()
        _register_builtins(registry)
        _DEFAULT = registry
    return _DEFAULT


def _register_builtins(registry: ToolRegistry) -> None:
    """Register the Phase-1 bundled tools. Imports are local so optional
    dependencies (yaml) never block a test that only exercises FileRead."""
    from cli.tools.file_read import FileReadTool
    from cli.tools.file_edit import FileEditTool
    from cli.tools.file_write import FileWriteTool
    from cli.tools.glob_tool import GlobTool
    from cli.tools.grep_tool import GrepTool
    from cli.tools.bash_tool import BashTool
    from cli.tools.config_read import ConfigReadTool
    from cli.tools.config_edit import ConfigEditTool
    from cli.tools.agent_spawn import AgentSpawnTool
    from cli.tools.web_fetch import WebFetchTool
    from cli.tools.web_search import WebSearchTool
    from cli.tools.todo_write import TodoWriteTool
    from cli.tools.skill_tool import SkillTool
    from cli.tools.exit_plan_mode import ExitPlanModeTool

    registry.extend(
        [
            FileReadTool(),
            FileEditTool(),
            FileWriteTool(),
            GlobTool(),
            GrepTool(),
            BashTool(),
            ConfigReadTool(),
            ConfigEditTool(),
            AgentSpawnTool(),
            WebFetchTool(),
            WebSearchTool(),
            TodoWriteTool(),
            SkillTool(),
            ExitPlanModeTool(),
        ]
    )


def reset_default_registry() -> None:
    """Drop the cached default registry. Tests use this to force re-population
    after monkey-patching a built-in tool."""
    global _DEFAULT
    _DEFAULT = None
