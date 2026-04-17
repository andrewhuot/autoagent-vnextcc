"""``EvalRunTool`` — model-callable adapter over ``run_eval_in_process`` (R7.B.2).

This wraps :func:`cli.commands.eval.run_eval_in_process` so the existing
:class:`cli.llm.orchestrator.LLMOrchestrator` can dispatch ``eval run`` as
part of its tool-use loop. The base :class:`AgentLabTool` handles the
plumbing (auto-injecting ``on_event`` / ``text_writer``, exception capture,
JSON-safe shaping); this module adds the model-facing metadata: the schema
the LLM consumes, the description it reads to decide whether to call, and
the late-bound import of the wrapped function.

The wrapped function reference is looked up fresh on every ``.run()`` call
(via :meth:`_in_process_fn`) so tests can monkeypatch
``cli.commands.eval.run_eval_in_process`` after the tool is constructed and
the patched callable still wins.
"""

from __future__ import annotations

from typing import Any, Callable

from cli.workbench_app.agentlab_tools._base import AgentLabTool


_EVAL_RUN_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "config_path": {
            "type": "string",
            "description": (
                "Absolute or workspace-relative path to the agent config "
                "YAML to evaluate. Omit to evaluate the active workspace "
                "config (resolved via the same logic as the `agentlab "
                "eval` CLI)."
            ),
        },
        "suite": {
            "type": "string",
            "description": (
                "Eval suite name (e.g. 'core', 'safety'). Defaults to the "
                "workspace's active suite."
            ),
        },
        "category": {
            "type": "string",
            "description": "Filter eval cases by category. Optional.",
        },
        "dataset": {
            "type": "string",
            "description": "Dataset name to evaluate against. Optional.",
        },
        "dataset_split": {
            "type": "string",
            "description": (
                "Dataset split selector — 'all' (default), 'train', "
                "'validation', or a custom slice the suite recognises."
            ),
            "default": "all",
        },
        "output_path": {
            "type": "string",
            "description": (
                "Write a JSON artifact of the run to this path. Useful "
                "when you want a durable record beyond the eval-run "
                "store. Optional."
            ),
        },
        "instruction_overrides_path": {
            "type": "string",
            "description": (
                "Path to an instruction-overrides YAML applied to the "
                "config before evaluation. Optional."
            ),
        },
        "real_agent": {
            "type": "boolean",
            "description": (
                "Force the real agent path even when mock fallback is "
                "available. Costs more tokens; use when you need a "
                "production-fidelity score."
            ),
            "default": False,
        },
        "force_mock": {
            "type": "boolean",
            "description": (
                "Force mock mode regardless of live provider "
                "availability. Cheap; use for smoke tests."
            ),
            "default": False,
        },
        "require_live": {
            "type": "boolean",
            "description": (
                "Abort with an error if live providers are unavailable "
                "(no silent mock fallback). Use when you need to "
                "guarantee a live score."
            ),
            "default": False,
        },
        "strict_live": {
            "type": "boolean",
            "description": (
                "Like require_live, plus reject the run if any warning "
                "indicates a partial mock fallback. The strictest mode."
            ),
            "default": False,
        },
    },
    "additionalProperties": False,
}


class EvalRunTool(AgentLabTool):
    """Run an eval suite in-process and return the composite verdict."""

    name = "EvalRun"
    description = (
        "Run an eval suite against the current or specified agent config "
        "and return the composite score, run mode, status, warnings, and "
        "produced artifacts. This is a 'run' operation: it costs LLM "
        "tokens, may take minutes for live suites, and writes a new entry "
        "to the eval-run store. Prefer the cheapest mode that answers the "
        "question — pass force_mock=True for smoke tests, leave defaults "
        "for normal runs, and only set require_live / strict_live when the "
        "user explicitly needs a guaranteed live score."
    )
    input_schema = _EVAL_RUN_INPUT_SCHEMA
    read_only = False

    def _in_process_fn(self) -> Callable[..., Any]:
        # Late-bound import: keeps cli.workbench_app.agentlab_tools cheap to
        # import (the eval module pulls in runner, yaml, click, etc.) and
        # lets tests monkeypatch ``cli.commands.eval.run_eval_in_process``
        # after construction.
        from cli.commands import eval as eval_module

        return eval_module.run_eval_in_process


__all__ = ["EvalRunTool"]
