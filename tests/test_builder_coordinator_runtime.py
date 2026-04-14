"""Tests for the Builder coordinator-worker execution runtime."""
from __future__ import annotations

import pytest

from builder.coordinator_runtime import CoordinatorWorkerRuntime
from builder.events import BuilderEventType, EventBroker
from builder.orchestrator import BuilderOrchestrator
from builder.store import BuilderStore
from builder.types import (
    BuilderProject,
    BuilderSession,
    BuilderTask,
    CoordinatorExecutionStatus,
    SpecialistRole,
    WorkerExecutionStatus,
)


@pytest.fixture
def store(tmp_path):
    return BuilderStore(db_path=str(tmp_path / "coordinator_runtime.db"))


@pytest.fixture
def events():
    return EventBroker()


@pytest.fixture
def orchestrator(store):
    return BuilderOrchestrator(store=store)


@pytest.fixture
def runtime(store, orchestrator, events):
    return CoordinatorWorkerRuntime(store=store, orchestrator=orchestrator, events=events)


def _planned_task(
    store: BuilderStore,
    orchestrator: BuilderOrchestrator,
    *,
    goal: str = "Build, evaluate, optimize, and deploy a support agent",
) -> tuple[BuilderTask, dict]:
    project = BuilderProject(
        project_id="proj-runtime",
        name="Runtime project",
        buildtime_skills=["prompt_hardening", "eval_failure_clustering"],
        runtime_skills=["faq_search"],
    )
    session = BuilderSession(project_id=project.project_id, title="Runtime session")
    task = BuilderTask(
        session_id=session.session_id,
        project_id=project.project_id,
        title="Runtime task",
        description=goal,
    )
    store.save_project(project)
    store.save_session(session)
    store.save_task(task)
    orchestrator.start_session(session)
    plan = orchestrator.plan_work(task=task, goal=goal, materialize_tasks=True)
    return task, plan


class TestCoordinatorWorkerRuntime:
    def test_execute_plan_records_worker_lifecycle_outputs_and_synthesis(
        self,
        store,
        orchestrator,
        runtime,
        events,
    ):
        task, plan = _planned_task(store, orchestrator)

        run = runtime.execute_plan(task_id=task.task_id, plan_id=plan["plan_id"])

        assert run.status == CoordinatorExecutionStatus.COMPLETED
        assert run.plan_id == plan["plan_id"]
        assert run.worker_states
        assert run.coordinator_synthesis["status"] == "completed"
        assert run.coordinator_synthesis["worker_count"] == len(run.worker_states)

        eval_worker = next(
            worker for worker in run.worker_states if worker.worker_role == SpecialistRole.EVAL_AUTHOR
        )
        assert eval_worker.status == WorkerExecutionStatus.COMPLETED
        assert eval_worker.context_snapshot["context_boundary"] == "fresh_worker_context"
        assert eval_worker.context_snapshot["worker_role"] == "eval_author"
        assert "eval_bundle" in eval_worker.result.artifacts
        assert eval_worker.result.verification["verified"] is True
        assert eval_worker.result.provenance["run_id"] == run.run_id

        phases = [entry["status"] for entry in eval_worker.phase_history]
        assert phases == [
            "gathering_context",
            "acting",
            "verifying",
            "completed",
        ]

        reloaded = store.get_coordinator_run(run.run_id)
        assert reloaded is not None
        assert reloaded.run_id == run.run_id
        assert reloaded.worker_states[0].result.summary

        event_types = [event.event_type for event in events.list_events(session_id=task.session_id)]
        assert BuilderEventType.COORDINATOR_EXECUTION_STARTED in event_types
        assert BuilderEventType.WORKER_GATHERING_CONTEXT in event_types
        assert BuilderEventType.WORKER_ACTING in event_types
        assert BuilderEventType.WORKER_VERIFYING in event_types
        assert BuilderEventType.WORKER_COMPLETED in event_types
        assert BuilderEventType.COORDINATOR_SYNTHESIS_COMPLETED in event_types

    def test_execute_plan_blocks_worker_with_unsatisfied_dependency(
        self,
        store,
        orchestrator,
        runtime,
        events,
    ):
        task, plan = _planned_task(store, orchestrator, goal="Build an agent and add evals")
        worker = next(entry for entry in plan["tasks"] if entry["worker_role"] != "orchestrator")
        worker["depends_on"] = ["missing-node"]
        stored_task = store.get_task(task.task_id)
        stored_task.metadata["coordinator_plan"] = plan
        store.save_task(stored_task)

        run = runtime.execute_plan(task_id=task.task_id, plan_id=plan["plan_id"])

        assert run.status == CoordinatorExecutionStatus.BLOCKED
        blocked_worker = next(state for state in run.worker_states if state.node_id == worker["task_id"])
        assert blocked_worker.status == WorkerExecutionStatus.BLOCKED
        assert "missing-node" in blocked_worker.blocker_reason
        assert run.coordinator_synthesis["status"] == "blocked"

        event_types = [event.event_type for event in events.list_events(session_id=task.session_id)]
        assert BuilderEventType.WORKER_BLOCKED in event_types
        assert BuilderEventType.COORDINATOR_EXECUTION_BLOCKED in event_types

    def test_execute_plan_requires_existing_persisted_plan(self, runtime, store):
        task = BuilderTask(session_id="session-missing-plan", project_id="project-missing-plan")
        store.save_task(task)

        with pytest.raises(ValueError, match="coordinator plan"):
            runtime.execute_plan(task_id=task.task_id)

    def test_list_runs_filters_by_plan_and_task(self, store, orchestrator, runtime):
        task, plan = _planned_task(store, orchestrator)
        run = runtime.execute_plan(task_id=task.task_id, plan_id=plan["plan_id"])

        by_plan = store.list_coordinator_runs(plan_id=plan["plan_id"])
        by_task = store.list_coordinator_runs(root_task_id=task.task_id)

        assert [entry.run_id for entry in by_plan] == [run.run_id]
        assert [entry.run_id for entry in by_task] == [run.run_id]
