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
from cli.workbench_app.agentlab_tools.improve_tools import (
    ImproveAcceptTool,
    ImproveDiffTool,
    ImproveListTool,
    ImproveRunTool,
    ImproveShowTool,
)


def register_agentlab_tools(registry: ToolRegistry) -> None:
    """Register every available AgentLab adapter on ``registry``.

    Today the seven adapters cover the full eval / deploy / improve surface:
    :class:`EvalRunTool` (B.2), :class:`DeployTool` (B.3) and the five
    Improve* tools (B.4). Future slices add the conversation bridge but no
    further raw command adapters.
    """

    registry.register(EvalRunTool())
    registry.register(DeployTool())
    registry.register(ImproveRunTool())
    registry.register(ImproveListTool())
    registry.register(ImproveShowTool())
    registry.register(ImproveDiffTool())
    registry.register(ImproveAcceptTool())


__all__ = [
    "DeployTool",
    "EvalRunTool",
    "ImproveAcceptTool",
    "ImproveDiffTool",
    "ImproveListTool",
    "ImproveRunTool",
    "ImproveShowTool",
    "register_agentlab_tools",
]
