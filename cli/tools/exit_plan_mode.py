"""ExitPlanModeTool — LLM-driven plan approval.

Claude Code's plan workflow ends when the model emits an
``ExitPlanMode`` tool call with the drafted plan payload; the user sees
a confirmation dialog, approves (or rejects), and normal tools unlock.

Our port stays close to that shape. The tool:

1. Reads the active :class:`~cli.workbench_app.plan_mode.PlanWorkflow`
   from :class:`ToolContext.extra`.
2. Updates the plan body with whatever the model finalised.
3. Fires the standard permission dialog so the user is the one who
   approves (or denies) the transition — the model cannot self-approve.
4. On approval, transitions the workflow to ``approved``, which
   automatically unlocks the full permission mode for the next tool
   call in the outer turn.

The tool intentionally uses ``permission_action="tool:ExitPlanMode"``
so a blanket ``tool:*`` allow rule does *not* auto-approve it — plan
exits should always prompt, even for users who have otherwise
auto-approved everything.
"""

from __future__ import annotations

from typing import Any, Mapping

from cli.tools.base import Tool, ToolContext, ToolResult


PLAN_WORKFLOW_KEY = "plan_workflow"
"""Key used on :class:`ToolContext.extra` to publish the active
:class:`~cli.workbench_app.plan_mode.PlanWorkflow`. The orchestrator
populates this before each tool call so ExitPlanMode doesn't need a
module-level singleton."""


class ExitPlanModeTool(Tool):
    """Mark the drafted plan approved, unlocking the full tool surface."""

    name = "ExitPlanMode"
    description = (
        "Finalise the drafted plan and request user approval to exit plan "
        "mode. Supply the plan content — the user sees it in the "
        "confirmation dialog. On approval, the next tool call runs with "
        "the normal permission mode; on denial, the plan stays drafting."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "plan": {
                "type": "string",
                "description": "Final plan markdown to present to the user.",
            },
        },
        "required": ["plan"],
        "additionalProperties": False,
    }

    def permission_action(self, tool_input: Mapping[str, Any]) -> str:
        # Distinct permission action so wildcard allow rules don't auto-
        # approve plan exits — the user always sees the confirmation.
        return "tool:ExitPlanMode"

    def render_preview(self, tool_input: Mapping[str, Any]) -> str:
        plan_text = str(tool_input.get("plan") or "")
        preview = plan_text.strip().splitlines()[:6]
        if len(plan_text.strip().splitlines()) > 6:
            preview.append("…")
        body = "\n    ".join(preview) if preview else "(empty plan)"
        return f"Exit plan mode with plan:\n    {body}"

    def run(self, tool_input: Mapping[str, Any], context: ToolContext) -> ToolResult:
        plan_text = str(tool_input.get("plan") or "").strip()
        if not plan_text:
            return ToolResult.failure("ExitPlanMode requires 'plan' content.")

        workflow = context.extra.get(PLAN_WORKFLOW_KEY)
        if workflow is None:
            return ToolResult.failure(
                "ExitPlanMode: no PlanWorkflow bound to this session. "
                "Start a plan with /plan first."
            )

        # Local import keeps ExitPlanMode loadable without the workbench
        # tree imported at module boot.
        from cli.workbench_app.plan_mode import PlanState, PlanStateError

        if workflow.state is not PlanState.DRAFTING:
            return ToolResult.failure(
                f"ExitPlanMode expects a drafting plan; current state is "
                f"{workflow.state.value}."
            )

        # Persist the model's finalised plan body so the audit trail
        # matches what the user approved.
        workflow.update_body(plan_text)

        try:
            plan = workflow.approve()
        except PlanStateError as exc:
            return ToolResult.failure(str(exc))

        return ToolResult.success(
            f"Plan '{plan.title}' approved. Permissions unlocked for the "
            "next tool call; use /plan-done when the work is complete.",
            plan_id=plan.id,
            plan_title=plan.title,
            state=plan.state.value,
        )


__all__ = ["ExitPlanModeTool", "PLAN_WORKFLOW_KEY"]
