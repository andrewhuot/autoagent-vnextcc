"""Tool registry and built-in tools for the AgentLab workbench.

This package mirrors the shape of Claude Code's `src/tools/` — each tool is a
self-describing unit with a JSON input schema, a permission action string, a
preview renderer for the permission dialog, and a run method that returns a
structured result. The registry lets the workbench LLM loop route tool-use
blocks to a Python implementation.

Registered tools split along two axes:

* **Workspace tools** (``FileReadTool``, ``FileEditTool``, ``GlobTool``, ...) —
  scoped to the workspace root; useful against ``agent/`` and ``configs/``.
* **Agent-config tools** (``ConfigReadTool``, ``ConfigEditTool``) — schema-aware
  operations on ``agentlab.yaml`` and agent specs.

The registry is imported lazily by :mod:`cli.workbench_app.app` so that tests
that never exercise tool-calling keep their minimal import surface.
"""

from __future__ import annotations

from cli.tools.base import Tool, ToolResult, ToolContext, ToolError, PermissionDecision
from cli.tools.registry import ToolRegistry, default_registry

__all__ = [
    "Tool",
    "ToolResult",
    "ToolContext",
    "ToolError",
    "PermissionDecision",
    "ToolRegistry",
    "default_registry",
]
