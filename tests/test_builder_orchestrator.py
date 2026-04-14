"""Tests for BuilderOrchestrator."""
from __future__ import annotations

import pytest

from builder.orchestrator import BuilderOrchestrator, HandoffRecord
from builder.store import BuilderStore
from builder.types import BuilderProject, BuilderSession, BuilderTask, ExecutionMode, SpecialistRole


@pytest.fixture
def store(tmp_path):
    return BuilderStore(db_path=str(tmp_path / "orchestrator.db"))


@pytest.fixture
def orchestrator(store):
    return BuilderOrchestrator(store=store)


@pytest.fixture
def session(store):
    session = BuilderSession(project_id="proj-1", title="Test session")
    store.save_session(session)
    return session


@pytest.fixture
def task(store, session):
    task = BuilderTask(session_id=session.session_id, project_id="proj-1", title="Test task")
    store.save_task(task)
    return task


class TestSessionInit:
    def test_start_session_sets_specialist(self, orchestrator, session):
        orchestrator.start_session(session)
        role = orchestrator.get_active_specialist(session.session_id)
        assert isinstance(role, SpecialistRole)

    def test_start_session_idempotent(self, orchestrator, session):
        orchestrator.start_session(session)
        orchestrator.start_session(session)
        role = orchestrator.get_active_specialist(session.session_id)
        assert isinstance(role, SpecialistRole)

    def test_unknown_session_returns_orchestrator(self, orchestrator):
        role = orchestrator.get_active_specialist("nonexistent")
        assert role == SpecialistRole.ORCHESTRATOR


class TestIntentDetection:
    def test_detect_build_intent(self, orchestrator):
        role = orchestrator.detect_specialist("implement the customer support agent build")
        assert role == SpecialistRole.BUILD_ENGINEER

    def test_detect_prompt_intent(self, orchestrator):
        role = orchestrator.detect_specialist("tighten the prompt instructions and examples")
        assert role == SpecialistRole.PROMPT_ENGINEER

    def test_detect_optimization_intent(self, orchestrator):
        role = orchestrator.detect_specialist("optimize the agent after eval failures")
        assert role == SpecialistRole.OPTIMIZATION_ENGINEER

    def test_detect_deployment_intent(self, orchestrator):
        role = orchestrator.detect_specialist("deploy the canary and prepare rollback")
        assert role == SpecialistRole.DEPLOYMENT_ENGINEER

    def test_detect_eval_intent(self, orchestrator):
        role = orchestrator.detect_specialist("write evaluation tests for the agent")
        assert role == SpecialistRole.EVAL_AUTHOR

    def test_detect_adk_intent(self, orchestrator):
        role = orchestrator.detect_specialist("design the ADK graph architecture")
        assert role == SpecialistRole.ADK_ARCHITECT

    def test_detect_release_intent(self, orchestrator):
        role = orchestrator.detect_specialist("release the agent to production")
        assert role == SpecialistRole.RELEASE_MANAGER

    def test_detect_unknown_falls_back(self, orchestrator):
        role = orchestrator.detect_specialist("xyz123 random nonsense")
        assert isinstance(role, SpecialistRole)


class TestRouting:
    def test_route_explicit_role(self, orchestrator, session, task):
        orchestrator.start_session(session)
        role = orchestrator.route_request(
            session_id=session.session_id,
            task_id=task.task_id,
            message="anything",
            explicit_role=SpecialistRole.TRACE_ANALYST,
        )
        assert role == SpecialistRole.TRACE_ANALYST

    def test_route_records_handoff_on_change(self, orchestrator, session, task):
        orchestrator.start_session(session)
        # Force a different starting specialist
        orchestrator._active_specialist_by_session[session.session_id] = SpecialistRole.ORCHESTRATOR
        orchestrator.route_request(
            session_id=session.session_id,
            task_id=task.task_id,
            message="",
            explicit_role=SpecialistRole.EVAL_AUTHOR,
        )
        handoffs = orchestrator.get_handoffs(session.session_id)
        assert len(handoffs) >= 1
        assert handoffs[-1].to_role == SpecialistRole.EVAL_AUTHOR

    def test_route_same_role_no_handoff(self, orchestrator, session, task):
        orchestrator.start_session(session)
        orchestrator._active_specialist_by_session[session.session_id] = SpecialistRole.EVAL_AUTHOR
        before = len(orchestrator.get_handoffs(session.session_id))
        orchestrator.route_request(
            session_id=session.session_id,
            task_id=task.task_id,
            message="",
            explicit_role=SpecialistRole.EVAL_AUTHOR,
        )
        after = len(orchestrator.get_handoffs(session.session_id))
        assert after == before


class TestInvokeSpecialist:
    def test_invoke_returns_dict_with_specialist(self, orchestrator, session, task):
        orchestrator.start_session(session)
        result = orchestrator.invoke_specialist(
            task=task,
            message="evaluate my agent",
            explicit_role=SpecialistRole.EVAL_AUTHOR,
        )
        assert result["specialist"] == SpecialistRole.EVAL_AUTHOR.value
        assert "display_name" in result
        assert "tools" in result
        assert "context" in result

    def test_invoke_returns_worker_capability_and_provenance(self, orchestrator, session, task):
        orchestrator.start_session(session)
        result = orchestrator.invoke_specialist(
            task=task,
            message="optimize prompt quality from eval failures",
            explicit_role=SpecialistRole.OPTIMIZATION_ENGINEER,
        )

        assert result["specialist"] == "optimization_engineer"
        assert result["worker_capability"]["role"] == "optimization_engineer"
        assert result["worker_capability"]["skill_layer"] == "build"
        assert "skill_engine" in result["recommended_tools"]
        assert result["provenance"]["routed_by"] == "builder_orchestrator"
        assert result["provenance"]["routing_reason"] == "explicit"

    def test_invoke_updates_task_specialist(self, orchestrator, store, session, task):
        orchestrator.start_session(session)
        orchestrator.invoke_specialist(
            task=task,
            message="release to prod",
            explicit_role=SpecialistRole.RELEASE_MANAGER,
        )
        updated = store.get_task(task.task_id)
        assert updated.active_specialist == SpecialistRole.RELEASE_MANAGER


class TestRoster:
    def test_list_roster_returns_all_specialists(self, orchestrator, session):
        orchestrator.start_session(session)
        roster = orchestrator.list_roster(session.session_id)
        assert len(roster) == len(SpecialistRole)
        roles = {entry["role"] for entry in roster}
        assert "build_engineer" in roles
        assert "optimization_engineer" in roles
        assert "eval_author" in roles
        assert "deployment_engineer" in roles

    def test_roster_marks_active(self, orchestrator, session):
        orchestrator.start_session(session)
        orchestrator._active_specialist_by_session[session.session_id] = SpecialistRole.TRACE_ANALYST
        roster = orchestrator.list_roster(session.session_id)
        active_entries = [e for e in roster if e["status"] == "active"]
        assert len(active_entries) == 1
        assert active_entries[0]["role"] == SpecialistRole.TRACE_ANALYST.value


class TestHandoffHistory:
    def test_get_handoffs_empty_initially(self, orchestrator, session):
        orchestrator.start_session(session)
        assert orchestrator.get_handoffs(session.session_id) == []

    def test_get_handoffs_dict_serializable(self, orchestrator, session, task):
        orchestrator.start_session(session)
        orchestrator._active_specialist_by_session[session.session_id] = SpecialistRole.ORCHESTRATOR
        orchestrator.route_request(
            session_id=session.session_id,
            task_id=task.task_id,
            message="",
            explicit_role=SpecialistRole.SKILL_AUTHOR,
        )
        handoffs_dict = orchestrator.get_handoffs_dict(session.session_id)
        assert len(handoffs_dict) == 1
        h = handoffs_dict[0]
        assert isinstance(h["from_role"], str)
        assert isinstance(h["to_role"], str)
        assert isinstance(h["timestamp"], float)


class TestWorkerCapabilityRegistry:
    def test_list_worker_capabilities_includes_product_roles_and_boundaries(self, orchestrator):
        capabilities = orchestrator.list_worker_capabilities()
        by_role = {entry["role"]: entry for entry in capabilities}

        assert by_role["build_engineer"]["skill_layer"] == "build"
        assert "source_diff" in by_role["build_engineer"]["expected_artifacts"]
        assert "eval" in by_role["eval_author"]["trigger_keywords"]
        assert "deployment" in by_role["deployment_engineer"]["permission_scope"]
        assert by_role["optimization_engineer"]["can_call_skills"] is True


class TestCoordinatorPlan:
    def test_plan_work_build_eval_optimize_deploy_goal_creates_worker_graph(
        self,
        orchestrator,
        store,
        session,
        task,
    ):
        project = BuilderProject(
            project_id="proj-1",
            name="Customer FAQ agent",
            buildtime_skills=["prompt_hardening", "eval_failure_clustering"],
            runtime_skills=["faq_search"],
        )
        store.save_project(project)
        orchestrator.start_session(session)

        plan = orchestrator.plan_work(
            task=task,
            goal=(
                "Build a support agent, tune the prompt, add evals, optimize failures, "
                "and deploy a canary"
            ),
        )

        roles = [entry["worker_role"] for entry in plan["tasks"]]
        assert roles[0] == "orchestrator"
        assert "build_engineer" in roles
        assert "prompt_engineer" in roles
        assert "eval_author" in roles
        assert "optimization_engineer" in roles
        assert "deployment_engineer" in roles

        worker_tasks = [entry for entry in plan["tasks"] if entry["worker_role"] != "orchestrator"]
        assert all(entry["depends_on"] for entry in worker_tasks)
        assert all(entry["provenance"]["routed_by"] == "builder_orchestrator" for entry in worker_tasks)
        assert "prompt_hardening" in plan["skill_context"]["buildtime_skills"]
        assert "faq_search" in plan["skill_context"]["runtime_skills"]
        assert plan["synthesis"]["next_step"] == "Start with the first planned worker task."

        reloaded = store.get_task(task.task_id)
        assert reloaded.metadata["coordinator_plan"]["plan_id"] == plan["plan_id"]

    def test_plan_work_can_materialize_child_worker_tasks(
        self,
        orchestrator,
        store,
        session,
        task,
    ):
        orchestrator.start_session(session)

        plan = orchestrator.plan_work(
            task=task,
            goal="Build an agent and add evals",
            materialize_tasks=True,
        )

        materialized = [entry for entry in plan["tasks"] if entry.get("materialized_task_id")]
        assert materialized
        for entry in materialized:
            child = store.get_task(entry["materialized_task_id"])
            assert child is not None
            assert child.parent_task_id == task.task_id
            assert child.active_specialist.value == entry["worker_role"]
            assert child.metadata["coordinator_plan_id"] == plan["plan_id"]

        updated_session = store.get_session(session.session_id)
        assert all(entry["materialized_task_id"] in updated_session.task_ids for entry in materialized)

    def test_plan_work_preserves_prior_turns_on_coordinator_node(
        self,
        orchestrator,
        store,
        session,
        task,
    ):
        """plan_work should attach prior-turn history to the root coordinator node."""
        orchestrator.start_session(session)
        prior_turns = [
            {
                "intent": "build",
                "goal": "Build support agent",
                "plan_id": "coord-prev",
                "run_id": "run-prev",
                "status": "completed",
                "worker_summaries": [
                    {"worker_role": "build_engineer", "status": "completed", "summary": "done"}
                ],
                "next_step": "Evaluate",
                "created_at": 1.0,
            }
        ]
        latest_synthesis = {"status": "completed", "next_step": "Evaluate"}

        plan = orchestrator.plan_work(
            task=task,
            goal="Evaluate the support agent",
            extra_context={
                "command_intent": "eval",
                "prior_turns": prior_turns,
                "latest_synthesis": latest_synthesis,
            },
        )

        root = next(entry for entry in plan["tasks"] if entry["worker_role"] == "orchestrator")
        assert root["provenance"]["prior_turns"] == prior_turns
        assert root["provenance"]["latest_synthesis"] == latest_synthesis

        reloaded = store.get_task(task.task_id)
        persisted_plan = reloaded.metadata["coordinator_plan"]
        persisted_root = next(
            entry for entry in persisted_plan["tasks"] if entry["worker_role"] == "orchestrator"
        )
        assert persisted_root["provenance"]["prior_turns"] == prior_turns
