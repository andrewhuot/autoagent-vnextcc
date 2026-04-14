"""Tests for the Workbench coordinator session facade."""

from __future__ import annotations

from pathlib import Path

from builder.events import BuilderEventType, EventBroker
from builder.coordinator_runtime import CoordinatorWorkerRuntime
from builder.orchestrator import BuilderOrchestrator
from builder.store import BuilderStore
from builder.types import SpecialistRole
from cli.workbench_app.checkpoint import CheckpointManager
from cli.workbench_app.coordinator_session import CoordinatorSession
from cli.workbench_app.runtime import WorkbenchAgentRuntime
from cli.workbench_app.slash import SlashContext
from deployer.versioning import ConfigVersionManager


def test_coordinator_session_plans_and_executes_worker_events(tmp_path: Path) -> None:
    """CoordinatorSession should own plan ids, execution events, and synthesis."""
    store = BuilderStore(db_path=str(tmp_path / "builder.db"))
    events = EventBroker()
    session = CoordinatorSession(
        store=store,
        orchestrator=BuilderOrchestrator(store=store),
        events=events,
    )

    plan = session.plan(
        "Build a support agent with a PII guardrail",
        verb="build",
        context={"permission_mode": "default"},
    )
    emitted = tuple(session.execute(str(plan["plan_id"])))

    assert session.active_run_count == 0
    assert session.latest_synthesis()["status"] == "completed"
    assert any(event.event_type == BuilderEventType.WORKER_COMPLETED for event in emitted)
    assert any(event.event_type == BuilderEventType.COORDINATOR_EXECUTION_COMPLETED for event in emitted)
    assert store.get_coordinator_run(session.latest_run_id or "") is not None


def test_coordinator_session_dry_run_returns_plan_result(tmp_path: Path) -> None:
    """Plan-mode callers need a result that has no run id and no worker execution."""
    store = BuilderStore(db_path=str(tmp_path / "builder.db"))
    session = CoordinatorSession(
        store=store,
        orchestrator=BuilderOrchestrator(store=store),
        events=EventBroker(),
    )

    result = session.process_turn(
        "Evaluate the current agent",
        command_intent="eval",
        dry_run=True,
    )

    assert result.status == "planned"
    assert result.run_id == ""
    assert SpecialistRole.EVAL_AUTHOR.value in result.worker_roles
    assert any("Approve with y" in line for line in result.transcript_lines)


def test_workbench_agent_runtime_delegates_to_coordinator_session(tmp_path: Path) -> None:
    """WorkbenchAgentRuntime should be a thin context adapter over CoordinatorSession."""
    store = BuilderStore(db_path=str(tmp_path / "builder.db"))
    runtime = WorkbenchAgentRuntime(
        store=store,
        orchestrator=BuilderOrchestrator(store=store),
        events=EventBroker(),
    )
    ctx = SlashContext()

    result = runtime.process_turn("I want to build my agent", ctx=ctx)

    assert runtime.coordinator_session.latest_run_id == result.run_id
    assert ctx.meta["latest_coordinator_run_id"] == result.run_id
    assert result.command_intent == "build"


def test_coordinator_runtime_snapshots_active_config_before_execution(tmp_path: Path) -> None:
    """Coordinator execution should leave a rewind point before workers mutate config."""
    configs_dir = tmp_path / "configs"
    versions = ConfigVersionManager(configs_dir=str(configs_dir))
    versions.save_version(
        {
            "model": "mock-model",
            "prompts": {"root": "Baseline prompt."},
        },
        scores={"composite": 0.0},
        status="active",
    )
    store = BuilderStore(db_path=str(tmp_path / "builder.db"))
    events = EventBroker()
    orchestrator = BuilderOrchestrator(store=store)
    runtime = CoordinatorWorkerRuntime(
        store=store,
        orchestrator=orchestrator,
        events=events,
        checkpoint_manager=CheckpointManager(configs_dir=configs_dir),
    )
    session = CoordinatorSession(
        store=store,
        orchestrator=orchestrator,
        events=events,
        runtime=runtime,
    )

    plan = session.plan("Build a better support agent", verb="build")
    tuple(session.execute(str(plan["plan_id"])))

    versions.reload()
    checkpoint_entries = [
        entry
        for entry in versions.manifest["versions"]
        if entry.get("status") == "checkpoint"
    ]
    assert len(checkpoint_entries) == 1
    assert str(checkpoint_entries[0]["scores"]["_reason"]).startswith("pre_execution:")


def test_coordinator_session_tasks_snapshot_lists_tasks_and_runs(tmp_path: Path) -> None:
    """The session should expose persisted task/run state for /tasks."""
    store = BuilderStore(db_path=str(tmp_path / "builder.db"))
    session = CoordinatorSession(
        store=store,
        orchestrator=BuilderOrchestrator(store=store),
        events=EventBroker(),
    )

    first = session.process_turn("Build a support agent", command_intent="build")
    second = session.process_turn("Evaluate the support agent", command_intent="eval")
    snapshot = session.tasks_snapshot(limit=5)

    assert snapshot["active_run_count"] == 0
    assert [item["task_id"] for item in snapshot["tasks"]][:2] == [
        second.task_id,
        first.task_id,
    ]
    assert {run["run_id"] for run in snapshot["runs"]} == {first.run_id, second.run_id}
