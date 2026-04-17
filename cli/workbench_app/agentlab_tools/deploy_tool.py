"""``DeployTool`` — model-callable adapter over ``run_deploy_in_process`` (R7.B.3).

This wraps :func:`cli.commands.deploy.run_deploy_in_process` so the existing
:class:`cli.llm.orchestrator.LLMOrchestrator` can dispatch ``deploy`` as part
of its tool-use loop. The base :class:`AgentLabTool` handles plumbing
(auto-injecting ``on_event`` / ``text_writer``, exception capture, JSON-safe
shaping); this module adds the model-facing metadata and a strategy-aware
permission action so settings.json rules can target individual deploy
strategies (e.g. ``allow tool:Deploy:canary`` while still asking for
``tool:Deploy:immediate``).

The wrapped function reference is looked up fresh on every ``.run()`` call
(via :meth:`_in_process_fn`) so tests can monkeypatch
``cli.commands.deploy.run_deploy_in_process`` after construction.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from cli.workbench_app.agentlab_tools._base import AgentLabTool


_DEPLOY_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "workflow": {
            "type": "string",
            "enum": ["canary", "immediate", "release", "rollback", "status"],
            "description": (
                "Optional positional workflow selector. Use 'status' for a "
                "read-only check, 'rollback' to revert to the previously "
                "active config, or 'canary'/'immediate'/'release' to invoke "
                "the matching deploy strategy without setting --strategy "
                "explicitly."
            ),
        },
        "config_version": {
            "type": "integer",
            "description": (
                "Specific config version to deploy. Defaults to the latest "
                "accepted version when omitted."
            ),
        },
        "strategy": {
            "type": "string",
            "enum": ["canary", "immediate"],
            "description": (
                "Deployment strategy. 'canary' rolls out gradually with "
                "automatic verification; 'immediate' promotes to full "
                "production traffic in one step. Defaults to 'canary'."
            ),
            "default": "canary",
        },
        "configs_dir": {
            "type": "string",
            "description": (
                "Override the configs directory. Optional — defaults to the "
                "workspace's configs directory."
            ),
        },
        "db": {
            "type": "string",
            "description": (
                "Override the conversation-store database path. Optional — "
                "defaults to the workspace's standard DB."
            ),
        },
        "target": {
            "type": "string",
            "enum": ["agentlab", "cx-studio"],
            "description": (
                "Deployment target. 'agentlab' deploys to the AgentLab "
                "runtime (default); 'cx-studio' packages a CX Studio export. "
                "Most callers want 'agentlab'."
            ),
            "default": "agentlab",
        },
        "dry_run": {
            "type": "boolean",
            "description": (
                "Preview the deployment plan without mutating production "
                "state. Use this first when unsure."
            ),
            "default": False,
        },
        "acknowledge": {
            "type": "boolean",
            "description": (
                "Skip the interactive deployment confirmation prompt "
                "(equivalent to the CLI's `-y`/`--yes` flag). Required when "
                "called from a non-interactive flow."
            ),
            "default": False,
        },
        "auto_review": {
            "type": "boolean",
            "description": (
                "Approve all pending change-card reviews before deploying "
                "(replicates `ship` behavior). Use cautiously — it bypasses "
                "human review of pending changes."
            ),
            "default": False,
        },
        "force_deploy_degraded": {
            "type": "boolean",
            "description": (
                "Override the R1.9 degraded-eval gate that blocks deploys "
                "when the eval verdict is failing. REQUIRES `force_reason` "
                "with a justification of at least 10 characters; the "
                "in-process function will raise without it."
            ),
            "default": False,
        },
        "force_reason": {
            "type": "string",
            "description": (
                "Justification (>= 10 characters) for using "
                "`force_deploy_degraded`. Recorded with the deploy for audit. "
                "Required whenever `force_deploy_degraded` is true."
            ),
        },
        "attempt_id": {
            "type": "string",
            "description": (
                "Link this deployment to a specific improve attempt for "
                "lineage tracking. Optional but strongly recommended when "
                "deploying the output of an improve cycle."
            ),
        },
        "release_experiment_id": {
            "type": "string",
            "description": (
                "Internal release-experiment identifier. Most callers should "
                "leave this unset."
            ),
        },
        "strict_live": {
            "type": "boolean",
            "description": (
                "Reject the deploy if any warning indicates a partial mock "
                "fallback occurred during preflight. Use when you need a "
                "guaranteed live verification path."
            ),
            "default": False,
        },
    },
    "additionalProperties": False,
}


class DeployTool(AgentLabTool):
    """Deploy a config version to production via the in-process deploy flow.

    MUTATES PRODUCTION STATE. The permission action embeds the chosen
    ``strategy`` so workspace rules can allow ``tool:Deploy:canary`` while
    still prompting on ``tool:Deploy:immediate``.
    """

    name = "Deploy"
    description = (
        "Deploy a config version to production. This MUTATES production "
        "state: it promotes a new active config, writes deployment lineage, "
        "and (for `immediate`) shifts traffic in one step. Prefer "
        "`strategy='canary'` for gradual rollout with automatic verification, "
        "or `dry_run=true` to preview the plan first. The R1.9 degraded-eval "
        "gate blocks deploys when the eval verdict is failing; "
        "`force_deploy_degraded=true` overrides the gate but REQUIRES "
        "`force_reason` >= 10 characters and the in-process function will "
        "raise without it. Use `workflow='status'` for a read-only check or "
        "`workflow='rollback'` to revert."
    )
    input_schema = _DEPLOY_INPUT_SCHEMA
    read_only = False

    def _in_process_fn(self) -> Callable[..., Any]:
        # Late-bound import: keeps cli.workbench_app.agentlab_tools cheap to
        # import (the deploy module pulls in runner, yaml, click, etc.) and
        # lets tests monkeypatch ``cli.commands.deploy.run_deploy_in_process``
        # after construction.
        from cli.commands import deploy as deploy_module

        return deploy_module.run_deploy_in_process

    def permission_action(self, tool_input: Mapping[str, Any]) -> str:
        """Return ``tool:Deploy:<strategy>`` so workspace rules can be granular.

        A user can allow ``tool:Deploy:canary`` for routine canary rollouts
        and still get prompted for ``tool:Deploy:immediate``.
        """

        strategy = tool_input.get("strategy", "canary")
        return f"tool:Deploy:{strategy}"


__all__ = ["DeployTool"]
