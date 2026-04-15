"""Plan-screen rendering helpers.

The plan screen is a read-only panel that summarises the current
:class:`~cli.workbench_app.plan_mode.PlanWorkflow` state. We keep the logic
here pure — :func:`render_plan_summary` builds a list of lines from a
:class:`Plan`, :func:`render_workflow_panel` wraps it with state-aware
header/footer chrome — so tests can assert the output directly without
spinning up a :class:`~cli.workbench_app.screens.base.Screen`.

A future prompt_toolkit full-screen takeover can reuse these helpers to
paint inside its :class:`Application`; for Phase 2 we embed the same output
into slash-command responses so the user sees the plan inline.
"""

from __future__ import annotations

from typing import Iterable

from cli.workbench_app import theme
from cli.workbench_app.plan_mode import Plan, PlanState, PlanWorkflow


def render_plan_summary(plan: Plan) -> list[str]:
    """Return the inline summary for a single plan.

    Output mirrors Claude Code's plan card: title + state badge, then the
    markdown body indented two spaces so it reads as a quoted block inside
    the surrounding transcript."""
    state_label = _state_label(plan.state)
    header = f"Plan: {plan.title}  [{state_label}]"
    lines: list[str] = [theme.workspace(header), _dim_meta(plan)]
    body = plan.body.rstrip()
    if body:
        lines.append("")
        for line in body.splitlines():
            lines.append(f"  {line}")
    else:
        lines.append("")
        lines.append("  (no plan body yet — drafting in progress)")
    return lines


def render_workflow_panel(workflow: PlanWorkflow) -> list[str]:
    """Return the panel shown by ``/plan`` with no arguments.

    Highlights the current state plus the next legal slash command so the
    user is never left wondering how to advance the flow."""
    if workflow.current is None:
        return [
            theme.meta("No active plan."),
            theme.meta("Start one with: /plan <goal>"),
        ]

    lines = render_plan_summary(workflow.current)
    hint = _next_hint(workflow.state)
    if hint:
        lines.append("")
        lines.append(theme.meta(hint))
    return lines


def render_plan_list(entries: Iterable[dict]) -> list[str]:
    """Return the compact list shown by ``/plan list``.

    Expects the dict shape produced by :meth:`PlanStore.list` so tests can
    feed synthetic entries without touching disk."""
    rows = list(entries)
    if not rows:
        return [theme.meta("No plans recorded yet.")]

    lines = [theme.workspace("Plans (most recent first)")]
    for entry in rows:
        state = entry.get("state", "?")
        title = entry.get("title", "?")
        updated = entry.get("updated_at", "")
        lines.append(f"  [{_state_label(PlanState(state))}] {title}  — updated {updated}")
    return lines


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state_label(state: PlanState) -> str:
    """Short state tag. Uppercase so it reads as a badge."""
    return state.value.upper()


def _dim_meta(plan: Plan) -> str:
    """Render the muted ``created → updated`` line under the title."""
    pieces = [f"id {plan.id}", f"created {plan.created_at}"]
    if plan.updated_at != plan.created_at:
        pieces.append(f"updated {plan.updated_at}")
    if plan.session_id:
        pieces.append(f"session {plan.session_id}")
    return theme.meta("  " + "  •  ".join(pieces))


def _next_hint(state: PlanState) -> str | None:
    """Return a one-line nudge pointing at the next legal slash command.

    Keeps the ``/plan`` UX discoverable without duplicating the full
    shortcut reference from ``help_text.py``."""
    if state is PlanState.DRAFTING:
        return "Next: /plan-approve to accept, /plan-discard to cancel"
    if state is PlanState.APPROVED:
        return "Next: run the plan's steps, then /plan-done to archive"
    return None
