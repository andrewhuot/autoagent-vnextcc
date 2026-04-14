"""Tests for the build-time skill registry and skill invocation worker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from builder.events import EventBroker
from builder.orchestrator import BuilderOrchestrator
from builder.skill_invocation_worker import SkillInvocationWorker
from builder.skill_runtime import BuildtimeSkillRegistry
from builder.store import BuilderStore
from builder.types import (
    BuilderProject,
    BuilderSession,
    BuilderTask,
    CoordinatorExecutionRun,
    SpecialistRole,
    WorkerExecutionState,
)
from builder.worker_adapters import WorkerAdapterContext
from core.skills.store import SkillStore
from core.skills.types import (
    EvalCriterion,
    MutationOperator,
    Skill,
    SkillKind,
    TriggerCondition,
)


_INVOKE_LOG: list[dict[str, Any]] = []


def _record_invocation(context: dict[str, Any]) -> dict[str, Any]:
    """Test helper used as a python_callable for the registry."""
    _INVOKE_LOG.append(dict(context))
    return {
        "summary": "test callable produced a deterministic mutation",
        "artifacts": {"mutation_diff": "+ tightened guardrail"},
        "result": {"applied": True},
    }


@pytest.fixture
def skill_store(tmp_path) -> SkillStore:
    """Provide an isolated unified skill store."""
    store = SkillStore(db_path=str(tmp_path / "skills.db"))
    yield store
    store.close()


@pytest.fixture
def registry(skill_store: SkillStore) -> BuildtimeSkillRegistry:
    """Build a registry around the isolated store and seed common skills."""
    skill_store.create(
        Skill(
            id="prompt_hardening",
            name="prompt_hardening",
            kind=SkillKind.BUILD,
            version="1.0.0",
            description="Tighten prompt instructions to reduce hallucination and refusal noise.",
            capabilities=["prompt_safety", "instruction_clarity"],
            mutations=[
                MutationOperator(
                    name="tighten_instruction",
                    description="Append safety-focused instructions",
                    target_surface="instruction",
                    operator_type="append",
                )
            ],
            triggers=[
                TriggerCondition(
                    failure_family="hallucination",
                    metric_name="hallucination_rate",
                    threshold=0.1,
                )
            ],
            eval_criteria=[
                EvalCriterion(metric="hallucination_rate", target=0.05, operator="lt")
            ],
            tags=["prompt", "safety"],
            domain="customer-support",
            instructions="Append a refusal policy and a fact-grounding clause.",
            metadata={"python_callable": "tests.test_builder_skill_runtime._record_invocation"},
        )
    )
    skill_store.create(
        Skill(
            id="eval_failure_clustering",
            name="eval_failure_clustering",
            kind=SkillKind.BUILD,
            version="1.0.0",
            description="Cluster eval failures into actionable optimization themes.",
            capabilities=["eval_analysis", "loss_pattern_grouping"],
            instructions="Group failure examples by blame target and emit a top-3 list.",
            tags=["eval", "loss"],
            domain="general",
        )
    )
    # Runtime skill should never be returned by the build registry.
    skill_store.create(
        Skill(
            id="order_lookup",
            name="order_lookup",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Look up customer orders by id.",
            domain="customer-support",
        )
    )
    return BuildtimeSkillRegistry(store=skill_store)


class TestBuildtimeSkillRegistry:
    def test_list_returns_only_build_kind(self, registry: BuildtimeSkillRegistry) -> None:
        skills = registry.list()
        names = {skill.name for skill in skills}
        assert names == {"prompt_hardening", "eval_failure_clustering"}
        assert all(skill.kind == SkillKind.BUILD for skill in skills)

    def test_get_returns_none_for_runtime_skill(self, registry: BuildtimeSkillRegistry) -> None:
        assert registry.get("order_lookup") is None
        assert registry.get("prompt_hardening") is not None

    def test_match_ranks_overlapping_keywords_and_excludes_others(
        self,
        registry: BuildtimeSkillRegistry,
    ) -> None:
        results = registry.match("Tighten the prompt to reduce hallucination in the support agent")
        names = [skill.name for skill in results]
        assert names, "expected at least one match"
        assert names[0] == "prompt_hardening"
        assert "order_lookup" not in names

    def test_match_returns_empty_for_unrelated_goal(
        self,
        registry: BuildtimeSkillRegistry,
    ) -> None:
        assert registry.match("zzzzz qqqqq xxxxx") == []

    def test_descriptors_for_goal_returns_compact_payload(
        self,
        registry: BuildtimeSkillRegistry,
    ) -> None:
        descriptors = registry.descriptors_for_goal("Cluster eval failures into themes")
        assert descriptors, "expected at least one descriptor"
        first = descriptors[0]
        assert first["name"] == "eval_failure_clustering"
        assert first["invocation_mode"] in {"callable", "playbook"}
        assert "capabilities" in first

    def test_invoke_callable_runs_python_function(
        self,
        registry: BuildtimeSkillRegistry,
    ) -> None:
        _INVOKE_LOG.clear()
        result = registry.invoke("prompt_hardening", {"goal": "harden it", "node_id": "n1"})
        assert result.mode == "callable"
        assert "mutation_diff" in result.artifacts
        assert result.output_payload["callable_ref"].endswith("_record_invocation")
        assert _INVOKE_LOG and _INVOKE_LOG[0]["goal"] == "harden it"

    def test_invoke_playbook_returns_descriptor_when_no_callable(
        self,
        registry: BuildtimeSkillRegistry,
    ) -> None:
        result = registry.invoke("eval_failure_clustering", {"goal": "cluster failures"})
        assert result.mode == "playbook"
        assert "playbook" in result.artifacts
        assert result.output_payload["playbook_instructions"].startswith("Group failure")

    def test_invoke_unknown_skill_raises(self, registry: BuildtimeSkillRegistry) -> None:
        with pytest.raises(ValueError):
            registry.invoke("does_not_exist", {})


class TestPlanWorkRegistryIntegration:
    def test_plan_work_includes_registry_descriptors_and_candidates(
        self,
        tmp_path,
        registry: BuildtimeSkillRegistry,
    ) -> None:
        builder_store = BuilderStore(db_path=str(tmp_path / "builder.db"))
        orchestrator = BuilderOrchestrator(store=builder_store, skill_registry=registry)

        project = BuilderProject(name="Integration project", buildtime_skills=["existing_skill"])
        builder_store.save_project(project)
        session = BuilderSession(project_id=project.project_id, title="s1")
        builder_store.save_session(session)
        task = BuilderTask(
            session_id=session.session_id,
            project_id=project.project_id,
            title="Plan work task",
            description="harden the prompt to reduce hallucination",
        )
        builder_store.save_task(task)

        plan = orchestrator.plan_work(
            task=task,
            goal="Tighten prompt for hallucination in the support agent",
        )

        skill_context = plan["skill_context"]
        assert "prompt_hardening" in skill_context["buildtime_registry_matches"]
        assert any(
            descriptor["name"] == "prompt_hardening"
            for descriptor in skill_context["buildtime_registry_descriptors"]
        )
        build_layer_nodes = [
            node
            for node in plan["tasks"]
            if node["worker_role"] != "orchestrator" and node["skill_layer"] == "build"
        ]
        assert build_layer_nodes, "expected at least one build-layer worker node"
        for node in build_layer_nodes:
            assert "existing_skill" in node["skill_candidates"]
            assert "prompt_hardening" in node["skill_candidates"]


def _make_worker_context(
    *,
    registry: BuildtimeSkillRegistry,
    skill_id: str,
    extra_candidates: list[str] | None = None,
) -> WorkerAdapterContext:
    """Compose a minimal :class:`WorkerAdapterContext` for the worker tests."""
    role = SpecialistRole.PROMPT_ENGINEER
    state = WorkerExecutionState(node_id="node-1", worker_role=role, title="prompt work")
    run = CoordinatorExecutionRun(
        plan_id="plan-1",
        root_task_id="task-1",
        session_id="sess-1",
        project_id="proj-1",
        goal="Harden the prompt to reduce hallucination",
    )
    task = BuilderTask(
        task_id="task-1",
        session_id="sess-1",
        project_id="proj-1",
        title="Test",
        description="test",
    )
    context = {
        "context_boundary": "fresh_worker_context",
        "selected_tools": ["code_edit"],
        "skill_candidates": list(extra_candidates or []),
        "skill_id": skill_id,
        "expected_artifacts": ["prompt_diff"],
        "goal": run.goal,
        "dependency_summaries": {},
    }
    routed = {
        "specialist": role.value,
        "recommended_tools": ["code_edit"],
        "permission_scope": ["read"],
        "provenance": {"routed_by": "test", "routing_reason": "test"},
        "context": {"skill_id": skill_id},
    }
    return WorkerAdapterContext(
        task=task,
        run=run,
        state=state,
        context=context,
        routed=routed,
        store=None,  # type: ignore[arg-type]
        events=EventBroker(),
    )


class TestSkillInvocationWorker:
    def test_executes_callable_skill_and_returns_result(
        self,
        registry: BuildtimeSkillRegistry,
    ) -> None:
        worker = SkillInvocationWorker(registry)
        context = _make_worker_context(registry=registry, skill_id="prompt_hardening")
        result = worker.execute(context)

        assert result.summary
        assert "mutation_diff" in result.artifacts
        assert result.output_payload["skill_id"] == "prompt_hardening"
        assert result.output_payload["adapter"] == SkillInvocationWorker.name
        assert result.output_payload["skill_invocation_mode"] == "callable"

    def test_falls_back_to_default_when_no_skill_id(
        self,
        registry: BuildtimeSkillRegistry,
    ) -> None:
        worker = SkillInvocationWorker(registry)
        context = _make_worker_context(registry=registry, skill_id="")
        # Strip explicit skill_id so the worker exercises the fallback path.
        context.context["skill_id"] = ""
        context.routed["context"]["skill_id"] = ""

        result = worker.execute(context)
        # Deterministic adapter path produces the expected artifact key.
        assert "prompt_diff" in result.artifacts

    def test_playbook_without_router_returns_descriptor_artifacts(
        self,
        registry: BuildtimeSkillRegistry,
    ) -> None:
        worker = SkillInvocationWorker(registry)
        context = _make_worker_context(
            registry=registry, skill_id="eval_failure_clustering"
        )
        result = worker.execute(context)

        assert result.output_payload["skill_invocation_mode"] == "playbook"
        assert "playbook" in result.artifacts
        assert result.provenance["provider"] == "playbook_no_router"

    def test_playbook_with_router_parses_envelope(
        self,
        registry: BuildtimeSkillRegistry,
    ) -> None:
        @dataclass
        class _Response:
            text: str
            provider: str = "mock"
            model: str = "mock-model"
            total_tokens: int = 10

        class _Router:
            strategy = "single"

            def generate(self, request):  # type: ignore[no-untyped-def]
                return _Response(
                    text='{"summary": "router worked", "artifacts": {"new_artifact": "ok"}, "output_payload": {"router_used": true}}'
                )

        worker = SkillInvocationWorker(registry, router=_Router())  # type: ignore[arg-type]
        context = _make_worker_context(
            registry=registry, skill_id="eval_failure_clustering"
        )
        result = worker.execute(context)
        assert result.summary == "router worked"
        assert result.artifacts.get("new_artifact") == "ok"
        assert result.output_payload.get("router_used") is True
        assert result.output_payload.get("provider") == "mock"
