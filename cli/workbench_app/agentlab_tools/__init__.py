"""AgentLab in-process command tools (R7 Slice B).

This package wraps the existing ``run_*_in_process`` functions as
:class:`cli.tools.base.Tool` subclasses so the existing
:class:`cli.llm.orchestrator.LLMOrchestrator` can dispatch them as part of
the LLM tool-use loop.

Public exports are added in B.2+ as each adapter lands.
"""
