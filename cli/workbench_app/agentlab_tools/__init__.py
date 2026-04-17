"""AgentLab in-process command tools (R7 Slice B).

This package wraps the existing ``run_*_in_process`` functions as
:class:`cli.tools.base.Tool` subclasses so the existing
:class:`cli.llm.orchestrator.LLMOrchestrator` can dispatch them as part of
the LLM tool-use loop.

Public exports are added in B.2+ as each adapter lands. Use
:func:`register_agentlab_tools` to install all available adapters into a
:class:`cli.tools.registry.ToolRegistry`.
"""

from __future__ import annotations

from cli.tools.registry import ToolRegistry
from cli.workbench_app.agentlab_tools.eval_tool import EvalRunTool


def register_agentlab_tools(registry: ToolRegistry) -> None:
    """Register every available AgentLab adapter on ``registry``.

    Adapters are added incrementally as each Slice-B task lands; today
    only :class:`EvalRunTool` is wired up. Subsequent slices append
    :class:`DeployTool`, the five ``Improve*`` tools, etc.
    """

    registry.register(EvalRunTool())


__all__ = ["EvalRunTool", "register_agentlab_tools"]
