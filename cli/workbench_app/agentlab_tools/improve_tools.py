"""Improve* tools — model-callable adapters over ``run_improve_*_in_process`` (R7.B.4).

This module wraps the five in-process improve commands as
:class:`AgentLabTool` subclasses so the existing
:class:`cli.llm.orchestrator.LLMOrchestrator` can dispatch the optimization
lifecycle (run / list / show / diff / accept) as part of its tool-use loop.

Each tool follows the same pattern as :class:`EvalRunTool` / :class:`DeployTool`:

* The wrapped function is looked up fresh on every ``.run()`` call (via
  :meth:`_in_process_fn`) so tests can monkeypatch the ``cli.commands.improve``
  symbol after the tool is constructed and the patched callable still wins.
* The model-facing ``input_schema`` lists *only* the model-visible domain args.
  Plumbing kwargs (``on_event``, ``text_writer``) are auto-injected by the
  base class. ``ImproveAcceptTool`` additionally hides ``deploy_invoker`` —
  it stays on the wrapped function's signature with its default of ``None``
  but never appears in the schema, so the model cannot invoke a custom
  deploy path.
* ``read_only`` is ``True`` for the inspection tools (List / Show / Diff)
  and ``False`` for the mutating tools (Run / Accept).

The default :meth:`Tool.permission_action` of ``f"tool:{name}"`` applies to
every tool here; per-attempt or per-strategy permission scoping is left to
later slices.
"""

from __future__ import annotations

from typing import Any, Callable

from cli.workbench_app.agentlab_tools._base import AgentLabTool


# --------------------------------------------------------------------------
# ImproveRun
# --------------------------------------------------------------------------


_IMPROVE_RUN_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "config_path": {
            "type": "string",
            "description": (
                "Absolute or workspace-relative path to the agent config "
                "YAML to improve. Required — the in-process path raises if "
                "this is omitted."
            ),
        },
        "cycles": {
            "type": "integer",
            "description": (
                "Number of optimize cycles to run. Each cycle costs LLM "
                "tokens and writes one or more attempt rows. Defaults to 1."
            ),
            "default": 1,
        },
        "mode": {
            "type": "string",
            "description": (
                "Optimizer mode selector. Optional — leave unset to use the "
                "workspace default."
            ),
        },
        "strict_live": {
            "type": "boolean",
            "description": (
                "Reject the run if any warning indicates a partial mock "
                "fallback occurred. Use when you need a guaranteed live "
                "score for every cycle."
            ),
            "default": False,
        },
        "auto": {
            "type": "boolean",
            "description": (
                "Run non-interactively, auto-accepting prompts the optimizer "
                "would otherwise raise. Use cautiously — bypasses human "
                "review of intermediate decisions."
            ),
            "default": False,
        },
    },
    "required": ["config_path"],
    "additionalProperties": False,
}


class ImproveRunTool(AgentLabTool):
    """Run one or more eval → optimize cycles for a config."""

    name = "ImproveRun"
    description = (
        "Run the improve loop (eval → optimize) for a config. MUTATING: "
        "writes new attempt rows to the optimization memory and costs LLM "
        "tokens per cycle. Requires an explicit config_path; the legacy "
        "zero-arg autofix path is unreachable from in-process. Returns the "
        "attempt_id of the produced optimization, the eval_run_id of the "
        "preflight eval, and the terminal status."
    )
    input_schema = _IMPROVE_RUN_INPUT_SCHEMA
    read_only = False

    def _in_process_fn(self) -> Callable[..., Any]:
        from cli.commands import improve as improve_module

        return improve_module.run_improve_run_in_process


# --------------------------------------------------------------------------
# ImproveList
# --------------------------------------------------------------------------


_IMPROVE_LIST_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "description": (
                "Filter attempts by classified status (e.g. 'proposed', "
                "'accepted', 'rejected', 'deployed_canary', 'promoted', "
                "'measured', 'rolled_back'). Optional."
            ),
        },
        "reason": {
            "type": "string",
            "description": (
                "Filter rejected attempts by rejection reason (one of the "
                "RejectionReason enum values). Optional."
            ),
        },
        "limit": {
            "type": "integer",
            "description": (
                "Maximum number of attempts to return. Defaults to 20."
            ),
            "default": 20,
        },
        "memory_db": {
            "type": "string",
            "description": (
                "Override the optimization-memory DB path. Optional — "
                "defaults to the workspace's standard memory DB."
            ),
        },
        "lineage_db": {
            "type": "string",
            "description": (
                "Override the improvement-lineage DB path. Optional — "
                "defaults to the workspace's standard lineage DB."
            ),
        },
    },
    "required": [],
    "additionalProperties": False,
}


class ImproveListTool(AgentLabTool):
    """List recent optimization attempts. Read-only."""

    name = "ImproveList"
    description = (
        "List recent optimization attempts. Read-only — returns id, status, "
        "reason, change description, section, before/after scores, deployed "
        "version, and lineage event types for each recent attempt. Filter "
        "by classified status or rejection reason; cap result count via limit."
    )
    input_schema = _IMPROVE_LIST_INPUT_SCHEMA
    read_only = True

    def _in_process_fn(self) -> Callable[..., Any]:
        from cli.commands import improve as improve_module

        return improve_module.run_improve_list_in_process


# --------------------------------------------------------------------------
# ImproveShow
# --------------------------------------------------------------------------


_IMPROVE_SHOW_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "attempt_id": {
            "type": "string",
            "description": (
                "Full or unique-prefix attempt id to show. Ambiguous "
                "prefixes raise an error."
            ),
        },
        "memory_db": {
            "type": "string",
            "description": (
                "Override the optimization-memory DB path. Optional."
            ),
        },
        "lineage_db": {
            "type": "string",
            "description": (
                "Override the improvement-lineage DB path. Optional."
            ),
        },
    },
    "required": ["attempt_id"],
    "additionalProperties": False,
}


class ImproveShowTool(AgentLabTool):
    """Show one attempt's summary plus its lineage. Read-only."""

    name = "ImproveShow"
    description = (
        "Show a single optimization attempt's summary and full lineage. "
        "Read-only — returns the attempt's change description, status, "
        "config section, scores, timestamp, and the chronological list of "
        "lineage events (proposal, deploy, promote, rollback, measurement)."
    )
    input_schema = _IMPROVE_SHOW_INPUT_SCHEMA
    read_only = True

    def _in_process_fn(self) -> Callable[..., Any]:
        from cli.commands import improve as improve_module

        return improve_module.run_improve_show_in_process


# --------------------------------------------------------------------------
# ImproveDiff
# --------------------------------------------------------------------------


_IMPROVE_DIFF_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "attempt_id": {
            "type": "string",
            "description": (
                "Full or unique-prefix attempt id whose diff to render."
            ),
        },
        "memory_db": {
            "type": "string",
            "description": (
                "Override the optimization-memory DB path. Optional."
            ),
        },
    },
    "required": ["attempt_id"],
    "additionalProperties": False,
}


class ImproveDiffTool(AgentLabTool):
    """Show the rationale and config diff for an attempt. Read-only."""

    name = "ImproveDiff"
    description = (
        "Render the rationale and config diff for an optimization attempt. "
        "Read-only — returns the change description, config section, unified "
        "config diff, before/after scores, raw status, and (when available) "
        "the parsed patch_bundle JSON."
    )
    input_schema = _IMPROVE_DIFF_INPUT_SCHEMA
    read_only = True

    def _in_process_fn(self) -> Callable[..., Any]:
        from cli.commands import improve as improve_module

        return improve_module.run_improve_diff_in_process


# --------------------------------------------------------------------------
# ImproveAccept
# --------------------------------------------------------------------------


_IMPROVE_ACCEPT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "attempt_id": {
            "type": "string",
            "description": (
                "Full or unique-prefix attempt id to deploy. Ambiguous "
                "prefixes raise an error."
            ),
        },
        "strategy": {
            "type": "string",
            "enum": ["canary", "immediate"],
            "description": (
                "Deployment strategy. 'canary' rolls out gradually with "
                "automatic verification (recommended); 'immediate' promotes "
                "to full production traffic in one step. Defaults to 'canary'."
            ),
            "default": "canary",
        },
        "memory_db": {
            "type": "string",
            "description": (
                "Override the optimization-memory DB path. Optional."
            ),
        },
        "lineage_db": {
            "type": "string",
            "description": (
                "Override the improvement-lineage DB path. Optional."
            ),
        },
    },
    "required": ["attempt_id"],
    "additionalProperties": False,
}


class ImproveAcceptTool(AgentLabTool):
    """Deploy an accepted improvement and schedule a post-deploy measurement.

    The wrapped function also accepts a ``deploy_invoker`` callable used by
    the Click wrapper to thread its ctx-aware deploy path. That argument is
    intentionally absent from :attr:`input_schema` so the model cannot
    inject a custom invoker; the wrapped function falls back to the default
    in-process deploy path when ``deploy_invoker is None``.
    """

    name = "ImproveAccept"
    description = (
        "Deploy an accepted improvement to production and schedule a "
        "post-deploy measurement. MUTATES production state: it promotes the "
        "improvement's config, records lineage, and (for `immediate`) shifts "
        "traffic in one step. Prefer `strategy='canary'` for gradual rollout. "
        "Returns the deployment_id, deployed_version, whether the attempt was "
        "already deployed, and whether the measurement was scheduled."
    )
    input_schema = _IMPROVE_ACCEPT_INPUT_SCHEMA
    read_only = False

    def _in_process_fn(self) -> Callable[..., Any]:
        from cli.commands import improve as improve_module

        return improve_module.run_improve_accept_in_process


__all__ = [
    "ImproveAcceptTool",
    "ImproveDiffTool",
    "ImproveListTool",
    "ImproveRunTool",
    "ImproveShowTool",
]
