"""Slash commands that drive :class:`PlanWorkflow`.

Commands:

* ``/plan [goal]``   — no args: show the current plan (or nudge to start
                         one); with args: begin a new plan in ``drafting``.
* ``/plan-approve``    — transition ``drafting → approved`` (unlocks edits).
* ``/plan-discard``    — archive the current plan and return to ``idle``.
* ``/plan-done``       — mark an approved plan as complete (``archived``).
* ``/plan-list``       — show recent plans from :class:`PlanStore`.

Handlers pull the :class:`PlanWorkflow` off ``SlashContext.meta['plan_workflow']``
so the workbench loop owns lifecycle (workflow is created once per session,
shared across commands). When the workflow is absent — e.g. in a test harness
that hasn't opted into plan mode — handlers fail gracefully with an
instructive message rather than crashing."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cli.workbench_app import theme
from cli.workbench_app.commands import LocalCommand, OnDoneResult, on_done
from cli.workbench_app.plan_mode import PlanStateError, PlanWorkflow
from cli.workbench_app.screens.plan import (
    render_plan_list,
    render_plan_summary,
    render_workflow_panel,
)

if TYPE_CHECKING:
    from cli.workbench_app.slash import SlashContext


PLAN_WORKFLOW_META_KEY = "plan_workflow"
"""Key used on :class:`SlashContext.meta` so the REPL loop can publish the
workflow without expanding the dataclass shape. Tests inject via
``ctx.meta[PLAN_WORKFLOW_META_KEY] = workflow``."""


# ---------------------------------------------------------------------------
# Command factories
# ---------------------------------------------------------------------------


def build_plan_command() -> LocalCommand:
    return LocalCommand(
        name="plan",
        description="Start or inspect a plan-mode draft",
        handler=_handle_plan,
        source="builtin",
        argument_hint="[goal]",
        when_to_use=(
            "Use before a multi-step change to draft a plan under read-only "
            "restrictions, then /plan-approve to unlock edits."
        ),
        sensitive=False,
    )


def build_plan_approve_command() -> LocalCommand:
    return LocalCommand(
        name="plan-approve",
        description="Approve the current plan and unlock normal tool permissions",
        handler=_handle_plan_approve,
        source="builtin",
        sensitive=True,
    )


def build_plan_discard_command() -> LocalCommand:
    return LocalCommand(
        name="plan-discard",
        description="Discard the current plan and return to idle",
        handler=_handle_plan_discard,
        source="builtin",
        sensitive=False,
    )


def build_plan_done_command() -> LocalCommand:
    return LocalCommand(
        name="plan-done",
        description="Archive the approved plan once its steps are complete",
        handler=_handle_plan_done,
        source="builtin",
        sensitive=False,
    )


def build_plan_list_command() -> LocalCommand:
    return LocalCommand(
        name="plan-list",
        description="Show recent plans from .agentlab/plans",
        handler=_handle_plan_list,
        source="builtin",
        sensitive=False,
    )


def all_plan_commands() -> tuple[LocalCommand, ...]:
    """Convenience bundle for ``build_builtin_registry`` and tests."""
    return (
        build_plan_command(),
        build_plan_approve_command(),
        build_plan_discard_command(),
        build_plan_done_command(),
        build_plan_list_command(),
    )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _handle_plan(ctx: "SlashContext", *args: str) -> OnDoneResult:
    workflow = _workflow_or_error(ctx)
    if workflow is None:
        return _workflow_missing()

    if not args:
        lines = render_workflow_panel(workflow)
        return on_done(display="user", result="\n".join(lines))

    goal = " ".join(args).strip()
    try:
        plan = workflow.begin(title=goal)
    except PlanStateError as exc:
        return on_done(display="system", result=theme.warning(str(exc)))
    lines = [
        theme.success(f"Plan started: {plan.title}"),
        theme.meta(
            "Drafting — only FileRead / Glob / Grep / ConfigRead are allowed "
            "until /plan-approve."
        ),
        *render_plan_summary(plan),
    ]
    return on_done(display="user", result="\n".join(lines))


def _handle_plan_approve(ctx: "SlashContext", *_: str) -> OnDoneResult:
    workflow = _workflow_or_error(ctx)
    if workflow is None:
        return _workflow_missing()
    try:
        plan = workflow.approve()
    except PlanStateError as exc:
        return on_done(display="system", result=theme.warning(str(exc)))
    lines = [
        theme.success(f"Plan approved: {plan.title}"),
        theme.meta(
            "Normal permission mode is active again. Run the plan's steps, "
            "then /plan-done to archive."
        ),
    ]
    return on_done(display="user", result="\n".join(lines))


def _handle_plan_discard(ctx: "SlashContext", *_: str) -> OnDoneResult:
    workflow = _workflow_or_error(ctx)
    if workflow is None:
        return _workflow_missing()
    archived = workflow.discard()
    if archived is None:
        return on_done(display="system", result=theme.meta("No active plan to discard."))
    return on_done(
        display="user",
        result=theme.warning(f"Plan discarded: {archived.title}"),
    )


def _handle_plan_done(ctx: "SlashContext", *_: str) -> OnDoneResult:
    workflow = _workflow_or_error(ctx)
    if workflow is None:
        return _workflow_missing()
    completed = workflow.complete()
    if completed is None:
        return on_done(
            display="system",
            result=theme.meta(
                "No approved plan to archive. Use /plan-approve first, or "
                "/plan-discard to cancel a draft."
            ),
        )
    return on_done(
        display="user",
        result=theme.success(f"Plan archived: {completed.title}"),
    )


def _handle_plan_list(ctx: "SlashContext", *_: str) -> OnDoneResult:
    workflow = _workflow_or_error(ctx)
    if workflow is None:
        return _workflow_missing()
    lines = render_plan_list(workflow.store.list())
    return on_done(display="user", result="\n".join(lines))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _workflow_or_error(ctx: "SlashContext") -> PlanWorkflow | None:
    workflow = ctx.meta.get(PLAN_WORKFLOW_META_KEY) if ctx.meta else None
    if not isinstance(workflow, PlanWorkflow):
        return None
    return workflow


def _workflow_missing() -> OnDoneResult:
    """Returned when the REPL didn't publish a workflow to the context.

    Emits a muted system message so the user understands the feature is
    off in their environment rather than seeing a raw ``KeyError``."""
    return on_done(
        display="system",
        result=theme.warning(
            "Plan mode is not configured for this session. "
            "Re-launch the workbench or file a bug if this is unexpected."
        ),
    )
