"""Tests for the coordinator-worker execution runtime."""
from __future__ import annotations

import pytest

from builder.coordinator_runtime import CoordinatorRuntime
from builder.events import BuilderEventType, EventBroker
from builder.orchestrator import BuilderOrchestrator
from builder.store import BuilderStore
from builder.types import (
    BuilderProject,
    BuilderSession,
    BuilderTask,
    CoordinatorExecutionRun,
    ExecutionRunStatus,
    WorkerExecutionResult,
    WorkerNodePhase,
)


@pytest.fixture
def store(tmp_path):
    return BuilderStore(db_path=str(tmp_path / "runtime.db"))


@pytest.fixture
def events():
    return EventBroker()


@pytest.fixture
def orchestrator(store):
    return BuilderOrchestrator(store=store)


@pytest.fixture
def runtime(store, events):
    return CoordinatorRuntime(store=store, events=events)


@pytest.fixture
def project(store):
    project = BuilderProject(
        project_id="proj-rt",
        name="Runtime Test Project",
        buildtime_skills=["prompt_hardening"],
        runtime_skills=["faq_search"],
    )
    store.save_project(project)
    return project


@pytest.fixture
def session(store, project):
    session = BuilderSession(project_id=project.project_id, title="Runtime session")
    store.save_session(session)
    return session


@pytest.fixture
def task(store, session, project):
    task = BuilderTask(
        session_id=session.session_id,
        project_id=project.project_id,
        title="Build and eval an agent",
    )
    store.save_task(task)
    return task


@pytest.fixture
def plan(orchestrator, store, session, task):
    orchestrator.start_session(session)
    return orchestrator.plan_work(
        task=task,
        goal="Build an agent, add evals, and deploy a canary",
    )


class TestExecutePlan:
    def test_execute_plan_returns_completed_run(self, runtime, task, plan):
        run = runtime.execute_plan(task=task, plan=plan)

        assert isinstance(run, CoordinatorExecutionRun)
        assert run.status == ExecutionRunStatus.COMPLETED
        assert run.plan_id == plan["plan_id"]
        assert run.task_id == task.task_id
        assert run.started_at is not None
        assert run.completed_at is not None

    def test_execute_plan_creates_worker_states_for_each_non_coordinator_node(
        self, runtime, task, plan
    ):
        run = runtime.execute_plan(task=task, plan=plan)

        worker_nodes = [
            n for n in plan["tasks"] if n["worker_role"] != "orchestrator"
        ]
        assert len(run.worker_states) == len(worker_nodes)

        for node in worker_nodes:
            assert node["task_id"] in run.worker_states
            result = run.worker_states[node["task_id"]]
            assert isinstance(result, WorkerExecutionResult)

    def test_all_workers_complete_on_happy_path(self, runtime, task, plan):
        run = runtime.execute_plan(task=task, plan=plan)

        for result in run.worker_states.values():
            assert result.phase == WorkerNodePhase.COMPLETED
            assert result.summary
            assert result.started_at is not None
            assert result.completed_at is not None

    def test_worker_results_contain_role_specific_outputs(self, runtime, task, plan):
        run = runtime.execute_plan(task=task, plan=plan)

        for result in run.worker_states.values():
            assert result.worker_role
            assert result.outputs.get("role") == result.worker_role
            assert result.outputs.get("action_taken")
            assert result.outputs.get("summary")

    def test_worker_context_includes_predecessor_data(self, runtime, task, plan):
        run = runtime.execute_plan(task=task, plan=plan)

        for result in run.worker_states.values():
            assert result.context_summary


class TestSynthesis:
    def test_synthesis_summarizes_all_worker_outcomes(self, runtime, task, plan):
        run = runtime.execute_plan(task=task, plan=plan)

        synthesis = run.synthesis
        assert synthesis["total_workers"] == len(run.worker_states)
        assert synthesis["completed_count"] == len(run.worker_states)
        assert synthesis["failed_count"] == 0
        assert synthesis["blocked_count"] == 0
        assert "all workers completed" in synthesis["status"]
        assert synthesis["next_step"]

    def test_synthesis_collects_artifacts(self, runtime, task, plan):
        run = runtime.execute_plan(task=task, plan=plan)

        synthesis = run.synthesis
        assert "artifacts_collected" in synthesis
        assert len(synthesis["artifacts_collected"]) > 0


class TestPersistence:
    def test_execution_persisted_to_task_metadata(self, runtime, store, task, plan):
        runtime.execute_plan(task=task, plan=plan)

        reloaded = store.get_task(task.task_id)
        assert "coordinator_execution" in reloaded.metadata
        exec_data = reloaded.metadata["coordinator_execution"]
        assert exec_data["status"] == "completed"
        assert exec_data["plan_id"] == plan["plan_id"]

    def test_get_execution_hydrates_from_metadata(self, runtime, store, task, plan):
        runtime.execute_plan(task=task, plan=plan)

        reloaded = store.get_task(task.task_id)
        run = runtime.get_execution(reloaded)
        assert run is not None
        assert isinstance(run, CoordinatorExecutionRun)
        assert run.status == ExecutionRunStatus.COMPLETED
        assert len(run.worker_states) > 0

        for result in run.worker_states.values():
            assert isinstance(result, WorkerExecutionResult)
            assert result.phase == WorkerNodePhase.COMPLETED

    def test_get_execution_returns_none_without_execution(self, runtime, task):
        assert runtime.get_execution(task) is None


class TestEvents:
    def test_execution_emits_lifecycle_events(self, runtime, events, task, plan):
        runtime.execute_plan(task=task, plan=plan)

        all_events = events.list_events(session_id=task.session_id, limit=500)
        event_types = [e.event_type for e in all_events]

        assert BuilderEventType.EXECUTION_STARTED in event_types
        assert BuilderEventType.EXECUTION_COMPLETED in event_types

    def test_execution_emits_worker_phase_events(self, runtime, events, task, plan):
        runtime.execute_plan(task=task, plan=plan)

        all_events = events.list_events(session_id=task.session_id, limit=500)
        phase_events = [
            e for e in all_events
            if e.event_type == BuilderEventType.WORKER_PHASE_CHANGED
        ]

        assert len(phase_events) > 0

        phases_seen = {e.payload.get("phase") for e in phase_events}
        assert "gathering_context" in phases_seen
        assert "acting" in phases_seen
        assert "verifying" in phases_seen
        assert "completed" in phases_seen

    def test_event_payloads_contain_run_and_node_ids(self, runtime, events, task, plan):
        run = runtime.execute_plan(task=task, plan=plan)

        all_events = events.list_events(session_id=task.session_id, limit=500)
        started = [
            e for e in all_events
            if e.event_type == BuilderEventType.EXECUTION_STARTED
        ]
        assert len(started) == 1
        assert started[0].payload["run_id"] == run.run_id

        phase_events = [
            e for e in all_events
            if e.event_type == BuilderEventType.WORKER_PHASE_CHANGED
        ]
        for pe in phase_events:
            assert pe.payload.get("run_id") == run.run_id
            assert pe.payload.get("node_id")
            assert pe.payload.get("worker_role")


class TestDependencyOrder:
    def test_topological_order_preserves_dependency_chain(self, runtime):
        nodes = [
            {"task_id": "c", "depends_on": ["b"], "worker_role": "eval_author"},
            {"task_id": "a", "depends_on": [], "worker_role": "orchestrator"},
            {"task_id": "b", "depends_on": ["a"], "worker_role": "build_engineer"},
        ]
        ordered = runtime._topological_order(nodes)
        ids = [n["task_id"] for n in ordered]
        assert ids.index("a") < ids.index("b")
        assert ids.index("b") < ids.index("c")


class TestFailureSemantics:
    def test_blocked_worker_when_dependency_fails(self, runtime, store, events, task):
        plan = {
            "plan_id": "test-plan-fail",
            "goal": "test failure propagation",
            "tasks": [
                {
                    "task_id": "root",
                    "worker_role": "orchestrator",
                    "depends_on": [],
                    "title": "Coordinator",
                },
                {
                    "task_id": "w1",
                    "worker_role": "invalid_role_xyz",
                    "depends_on": ["root"],
                    "title": "Bad worker",
                    "selected_tools": [],
                    "permission_scope": [],
                    "skill_candidates": [],
                    "expected_artifacts": ["nonexistent"],
                    "provenance": {},
                },
                {
                    "task_id": "w2",
                    "worker_role": "build_engineer",
                    "depends_on": ["w1"],
                    "title": "Blocked worker",
                    "selected_tools": [],
                    "permission_scope": [],
                    "skill_candidates": [],
                    "expected_artifacts": [],
                    "provenance": {},
                },
            ],
        }
        task.metadata["coordinator_plan"] = plan
        store.save_task(task)

        run = runtime.execute_plan(task=task, plan=plan)

        assert run.status == ExecutionRunStatus.FAILED
        assert run.worker_states["w1"].phase == WorkerNodePhase.FAILED
        assert run.worker_states["w2"].phase == WorkerNodePhase.BLOCKED

        assert run.synthesis["failed_count"] == 1
        assert run.synthesis["blocked_count"] == 1
