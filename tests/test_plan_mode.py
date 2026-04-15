"""Tests for the Phase-2 plan-mode workflow.

Covers three layers:

* :mod:`cli.workbench_app.plan_mode` — state machine + persistence.
* :mod:`cli.permissions` — integration: a drafting plan restricts the tool
  surface regardless of the user's saved permission mode.
* :mod:`cli.workbench_app.plan_slash` — slash-command handlers dispatch
  against an injected workflow and surface the expected user messages.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cli.permissions import PermissionManager
from cli.tools.base import Tool, ToolContext, ToolResult
from cli.tools.file_edit import FileEditTool
from cli.tools.file_read import FileReadTool
from cli.workbench_app.commands import CommandRegistry
from cli.workbench_app.plan_mode import (
    DRAFTING_ALLOWED_TOOLS,
    Plan,
    PlanState,
    PlanStateError,
    PlanStore,
    PlanWorkflow,
    decision_for_tool_with_workflow,
)
from cli.workbench_app.plan_slash import (
    PLAN_WORKFLOW_META_KEY,
    all_plan_commands,
    build_plan_command,
    build_plan_approve_command,
    build_plan_discard_command,
    build_plan_done_command,
    build_plan_list_command,
)
from cli.workbench_app.screens.plan import (
    render_plan_list,
    render_plan_summary,
    render_workflow_panel,
)
from cli.workbench_app.slash import SlashContext


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / ".agentlab").mkdir()
    return tmp_path


@pytest.fixture
def store(workspace: Path) -> PlanStore:
    return PlanStore(root=workspace)


@pytest.fixture
def workflow(store: PlanStore) -> PlanWorkflow:
    return PlanWorkflow(store=store, session_id="session-123")


# ---------------------------------------------------------------------------
# PlanStore / Plan persistence
# ---------------------------------------------------------------------------


def test_plan_to_and_from_markdown_roundtrip() -> None:
    plan = Plan(
        id="20260414-120000-demo-abcdef",
        title="Refactor evaluator",
        state=PlanState.DRAFTING,
        body="Step 1\nStep 2\n",
        created_at="2026-04-14T12:00:00+00:00",
        updated_at="2026-04-14T12:05:00+00:00",
        session_id="s-1",
    )
    text = plan.to_markdown()
    restored = Plan.from_markdown(text)
    assert restored == plan


def test_plan_from_markdown_requires_front_matter() -> None:
    with pytest.raises(ValueError):
        Plan.from_markdown("just a body")
    with pytest.raises(ValueError):
        Plan.from_markdown("---\nid: x\n")  # missing closing delimiter


def test_plan_store_save_creates_file_and_index(store: PlanStore) -> None:
    plan = Plan(
        id="p1",
        title="Demo",
        state=PlanState.DRAFTING,
        body="body",
        created_at="2026-04-14T10:00:00+00:00",
        updated_at="2026-04-14T10:00:00+00:00",
    )
    path = store.save(plan)
    assert path.exists()
    assert path.name == "p1.md"
    index = json.loads(store.index_path.read_text())
    assert index == [
        {
            "id": "p1",
            "title": "Demo",
            "state": "drafting",
            "created_at": "2026-04-14T10:00:00+00:00",
            "updated_at": "2026-04-14T10:00:00+00:00",
        }
    ]


def test_plan_store_list_sorts_newest_first(store: PlanStore) -> None:
    for idx, stamp in enumerate(["2026-04-10", "2026-04-12", "2026-04-11"]):
        store.save(
            Plan(
                id=f"p{idx}",
                title=f"Plan {idx}",
                state=PlanState.ARCHIVED,
                body="",
                created_at=f"{stamp}T00:00:00+00:00",
                updated_at=f"{stamp}T00:00:00+00:00",
            )
        )
    entries = store.list()
    assert [entry["updated_at"] for entry in entries] == [
        "2026-04-12T00:00:00+00:00",
        "2026-04-11T00:00:00+00:00",
        "2026-04-10T00:00:00+00:00",
    ]


def test_plan_store_latest_drafting_returns_first_active(store: PlanStore) -> None:
    store.save(
        Plan(
            id="archived",
            title="Old",
            state=PlanState.ARCHIVED,
            body="",
            created_at="2026-04-10T00:00:00+00:00",
            updated_at="2026-04-10T00:00:00+00:00",
        )
    )
    active = Plan(
        id="active",
        title="New",
        state=PlanState.DRAFTING,
        body="",
        created_at="2026-04-14T00:00:00+00:00",
        updated_at="2026-04-14T00:00:00+00:00",
    )
    store.save(active)
    latest = store.latest_drafting()
    assert latest is not None
    assert latest.id == "active"


# ---------------------------------------------------------------------------
# PlanWorkflow state machine
# ---------------------------------------------------------------------------


def test_workflow_begin_creates_drafting_plan(workflow: PlanWorkflow) -> None:
    plan = workflow.begin("Add retry logic")
    assert plan.state is PlanState.DRAFTING
    assert plan.title == "Add retry logic"
    assert plan.session_id == "session-123"
    assert workflow.state is PlanState.DRAFTING
    assert workflow.active is True


def test_workflow_rejects_concurrent_plans(workflow: PlanWorkflow) -> None:
    workflow.begin("First plan")
    with pytest.raises(PlanStateError):
        workflow.begin("Second plan")


def test_workflow_approve_transitions_state(workflow: PlanWorkflow) -> None:
    workflow.begin("Refactor")
    plan = workflow.approve()
    assert plan.state is PlanState.APPROVED
    assert workflow.state is PlanState.APPROVED
    assert workflow.active is True


def test_workflow_approve_requires_drafting(workflow: PlanWorkflow) -> None:
    with pytest.raises(PlanStateError):
        workflow.approve()


def test_workflow_discard_archives(workflow: PlanWorkflow) -> None:
    workflow.begin("Refactor")
    archived = workflow.discard()
    assert archived is not None
    assert archived.state is PlanState.ARCHIVED
    assert workflow.current is None
    assert workflow.state is PlanState.IDLE


def test_workflow_discard_idempotent_when_no_plan(workflow: PlanWorkflow) -> None:
    assert workflow.discard() is None


def test_workflow_complete_requires_approved(workflow: PlanWorkflow) -> None:
    workflow.begin("x")
    assert workflow.complete() is None  # still drafting → no-op
    workflow.approve()
    completed = workflow.complete()
    assert completed is not None
    assert completed.state is PlanState.ARCHIVED
    assert workflow.current is None


def test_workflow_update_body_persists(workflow: PlanWorkflow, store: PlanStore) -> None:
    plan = workflow.begin("Draft")
    workflow.update_body("1. Do the thing.\n")
    reloaded = store.load(plan.id)
    assert reloaded.body.strip() == "1. Do the thing."


def test_workflow_restores_in_flight_plan_from_disk(store: PlanStore) -> None:
    PlanWorkflow(store=store).begin("Interrupted")
    # Simulate a fresh workbench restart — the constructor scans the store.
    resumed = PlanWorkflow(store=store)
    assert resumed.current is not None
    assert resumed.current.title == "Interrupted"
    assert resumed.state is PlanState.DRAFTING


# ---------------------------------------------------------------------------
# Plan-aware permission decisions
# ---------------------------------------------------------------------------


def test_drafting_denies_mutating_tools(workspace: Path, workflow: PlanWorkflow) -> None:
    workflow.begin("Read only")
    manager = PermissionManager(root=workspace)
    manager.bind_plan_workflow(workflow)
    assert manager.decision_for_tool(FileEditTool(), {"path": "x"}) == "deny"


def test_drafting_allows_read_only_tools(workspace: Path, workflow: PlanWorkflow) -> None:
    workflow.begin("Read only")
    manager = PermissionManager(root=workspace)
    manager.bind_plan_workflow(workflow)
    assert manager.decision_for_tool(FileReadTool(), {"path": "x"}) == "allow"


def test_approved_plan_does_not_restrict(workspace: Path, workflow: PlanWorkflow) -> None:
    workflow.begin("Go live")
    workflow.approve()
    manager = PermissionManager(root=workspace)
    manager.bind_plan_workflow(workflow)
    # Back to normal default-mode behaviour once the plan is approved.
    assert manager.decision_for_tool(FileEditTool(), {"path": "x"}) == "ask"


def test_decision_for_tool_with_workflow_composes_fallback() -> None:
    class _Workflow:
        def active_restriction(self):
            return DRAFTING_ALLOWED_TOOLS

    assert (
        decision_for_tool_with_workflow(
            "FileEdit", False, _Workflow(), fallback_decision="allow"
        )
        == "deny"
    )
    assert (
        decision_for_tool_with_workflow(
            "FileRead", True, _Workflow(), fallback_decision="allow"
        )
        == "allow"
    )
    assert (
        decision_for_tool_with_workflow(
            "FileEdit", False, None, fallback_decision="ask"
        )
        == "ask"
    )


# ---------------------------------------------------------------------------
# Slash command handlers
# ---------------------------------------------------------------------------


def _make_ctx(workflow: PlanWorkflow | None) -> tuple[SlashContext, list[str]]:
    echoed: list[str] = []
    ctx = SlashContext(echo=echoed.append)
    ctx.meta = {PLAN_WORKFLOW_META_KEY: workflow} if workflow is not None else {}
    return ctx, echoed


def test_plan_handler_without_args_shows_panel(workflow: PlanWorkflow) -> None:
    ctx, _ = _make_ctx(workflow)
    command = build_plan_command()
    result = command.handler(ctx)
    assert "No active plan" in _as_text(result)


def test_plan_handler_starts_new_plan(workflow: PlanWorkflow) -> None:
    ctx, _ = _make_ctx(workflow)
    command = build_plan_command()
    result = command.handler(ctx, "Add", "retries")
    body = _as_text(result)
    assert "Plan started" in body
    assert "Add retries" in body
    assert workflow.state is PlanState.DRAFTING


def test_plan_approve_handler_transitions(workflow: PlanWorkflow) -> None:
    workflow.begin("Refactor")
    ctx, _ = _make_ctx(workflow)
    approve = build_plan_approve_command()
    result = approve.handler(ctx)
    assert "approved" in _as_text(result).lower()
    assert workflow.state is PlanState.APPROVED


def test_plan_approve_without_draft_warns(workflow: PlanWorkflow) -> None:
    ctx, _ = _make_ctx(workflow)
    approve = build_plan_approve_command()
    result = approve.handler(ctx)
    assert "No plan is active" in _as_text(result)


def test_plan_discard_handler(workflow: PlanWorkflow) -> None:
    workflow.begin("Scratch")
    ctx, _ = _make_ctx(workflow)
    discard = build_plan_discard_command()
    result = discard.handler(ctx)
    assert "discarded" in _as_text(result).lower()
    assert workflow.state is PlanState.IDLE


def test_plan_done_handler_requires_approved(workflow: PlanWorkflow) -> None:
    workflow.begin("Draft")
    ctx, _ = _make_ctx(workflow)
    done = build_plan_done_command()
    result = done.handler(ctx)
    assert "No approved plan" in _as_text(result)


def test_plan_done_handler_archives_approved(workflow: PlanWorkflow) -> None:
    workflow.begin("Draft")
    workflow.approve()
    ctx, _ = _make_ctx(workflow)
    done = build_plan_done_command()
    result = done.handler(ctx)
    assert "archived" in _as_text(result).lower()
    assert workflow.state is PlanState.IDLE


def test_plan_list_handler_shows_entries(workflow: PlanWorkflow) -> None:
    workflow.begin("Done earlier").title  # keep mypy happy
    workflow.discard()
    workflow.begin("In progress")
    ctx, _ = _make_ctx(workflow)
    listing = build_plan_list_command()
    result = listing.handler(ctx)
    text = _as_text(result)
    assert "In progress" in text
    assert "Done earlier" in text


def test_slash_handlers_without_workflow_emit_warning() -> None:
    ctx, _ = _make_ctx(None)
    for command in all_plan_commands():
        result = command.handler(ctx)
        assert "Plan mode is not configured" in _as_text(result)


# ---------------------------------------------------------------------------
# Screen renderers
# ---------------------------------------------------------------------------


def test_render_plan_summary_includes_state_badge() -> None:
    plan = Plan(
        id="pid",
        title="Cleanup",
        state=PlanState.DRAFTING,
        body="1. Step one.\n",
        created_at="2026-04-14T10:00:00+00:00",
        updated_at="2026-04-14T10:00:00+00:00",
    )
    lines = render_plan_summary(plan)
    joined = "\n".join(lines)
    assert "Cleanup" in joined
    assert "DRAFTING" in joined
    assert "1. Step one." in joined


def test_render_workflow_panel_hints_next_step(workflow: PlanWorkflow) -> None:
    workflow.begin("Prepare release")
    panel = "\n".join(render_workflow_panel(workflow))
    assert "/plan-approve" in panel
    workflow.approve()
    approved_panel = "\n".join(render_workflow_panel(workflow))
    assert "/plan-done" in approved_panel


def test_render_plan_list_empty() -> None:
    lines = render_plan_list([])
    assert any("No plans" in line for line in lines)


# ---------------------------------------------------------------------------
# Registry smoke
# ---------------------------------------------------------------------------


def test_all_plan_commands_register_cleanly() -> None:
    registry = CommandRegistry()
    for command in all_plan_commands():
        registry.register(command)
    assert set(registry.names()) >= {
        "plan",
        "plan-approve",
        "plan-discard",
        "plan-done",
        "plan-list",
    }


def _as_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if hasattr(result, "result"):
        return str(result.result or "")
    return str(result)
