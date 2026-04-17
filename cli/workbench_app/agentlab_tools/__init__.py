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
from cli.workbench_app.agentlab_tools.deploy_tool import DeployTool
from cli.workbench_app.agentlab_tools.eval_tool import EvalRunTool


def register_agentlab_tools(registry: ToolRegistry) -> None:
    """Register every available AgentLab adapter on ``registry``.

    Adapters are added incrementally as each Slice-B task lands. Today
    :class:`EvalRunTool` (B.2) and :class:`DeployTool` (B.3) are wired up;
    subsequent slices append the five ``Improve*`` tools.
    """

    registry.register(EvalRunTool())
    registry.register(DeployTool())


__all__ = ["DeployTool", "EvalRunTool", "register_agentlab_tools"]
