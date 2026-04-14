"""Tests for coordinator worker adapter dispatch."""

from __future__ import annotations

from pathlib import Path

import pytest

from builder.coordinator_runtime import CoordinatorWorkerRuntime
from builder.events import EventBroker
from builder.orchestrator import BuilderOrchestrator
from builder.store import BuilderStore
from builder.types import (
    BuilderProject,
    BuilderSession,
    BuilderTask,
    SpecialistRole,
    WorkerExecutionResult,
)


@pytest.fixture
def store(tmp_path: Path) -> BuilderStore:
    return BuilderStore(db_path=str(tmp_path / "builder.db"))


def _planned_task(
    store: BuilderStore,
    orchestrator: BuilderOrchestrator,
    *,
    goal: str = "Build an agent and generate evals",
) -> tuple[BuilderTask, dict]:
    project = BuilderProject(name="Adapter project")
    session = BuilderSession(project_id=project.project_id, title="Adapter session")
    task = BuilderTask(
        project_id=project.project_id,
        session_id=session.session_id,
        title="Adapter task",
        description=goal,
    )
    store.save_project(project)
    store.save_session(session)
    store.save_task(task)
    orchestrator.start_session(session)
    return task, orchestrator.plan_work(task=task, goal=goal)


class _RecordingEvalAdapter:
    def __init__(self) -> None:
        self.contexts: list[dict] = []

    def execute(self, context):
        self.contexts.append(context.context)
        return WorkerExecutionResult(
            node_id=context.state.node_id,
            worker_role=context.state.worker_role,
            summary="Eval adapter ran the current candidate against generated evals.",
            artifacts={
                "eval_bundle": {"source": "adapter"},
                "benchmark_plan": {"source": "adapter"},
            },
            context_used={
                "context_boundary": context.context["context_boundary"],
                "selected_tools": context.context["selected_tools"],
            },
            output_payload={"adapter": "recording_eval"},
            provenance={"adapter": "recording_eval"},
        )


def test_runtime_dispatches_registered_worker_adapter(store: BuilderStore) -> None:
    """Coordinator execution should use role adapters instead of placeholder _act."""
    orchestrator = BuilderOrchestrator(store=store)
    adapter = _RecordingEvalAdapter()
    runtime = CoordinatorWorkerRuntime(
        store=store,
        orchestrator=orchestrator,
        events=EventBroker(),
        worker_adapters={SpecialistRole.EVAL_AUTHOR: adapter},
    )
    task, plan = _planned_task(store, orchestrator, goal="Build an agent and generate evals")

    run = runtime.execute_plan(task_id=task.task_id, plan_id=plan["plan_id"])

    eval_state = next(
        state for state in run.worker_states if state.worker_role == SpecialistRole.EVAL_AUTHOR
    )
    assert adapter.contexts
    assert eval_state.result is not None
    assert eval_state.result.output_payload["adapter"] == "recording_eval"
    assert eval_state.result.artifacts["eval_bundle"]["source"] == "adapter"


def test_default_worker_adapter_returns_role_specific_reviewable_artifacts(
    store: BuilderStore,
) -> None:
    """Default offline execution should still produce useful role-specific outputs."""
    orchestrator = BuilderOrchestrator(store=store)
    runtime = CoordinatorWorkerRuntime(
        store=store,
        orchestrator=orchestrator,
        events=EventBroker(),
    )
    task, plan = _planned_task(
        store,
        orchestrator,
        goal="Optimize the agent from eval failures and prepare deploy",
    )

    run = runtime.execute_plan(task_id=task.task_id, plan_id=plan["plan_id"])

    optimize_state = next(
        state
        for state in run.worker_states
        if state.worker_role == SpecialistRole.OPTIMIZATION_ENGINEER
    )
    assert optimize_state.result is not None
    assert optimize_state.result.output_payload["adapter"] == "deterministic_worker_adapter"
    assert "review_required" in optimize_state.result.output_payload
    assert "optimization_plan" in optimize_state.result.artifacts
