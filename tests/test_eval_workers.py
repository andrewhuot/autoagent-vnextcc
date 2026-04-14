"""Unit tests for V2 eval-axis coordinator workers."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from builder.eval_workers import EvalRunnerWorker, LossAnalystWorker
from builder.events import EventBroker
from builder.store import BuilderStore
from builder.types import (
    BuilderProject,
    BuilderSession,
    BuilderTask,
    CoordinatorExecutionRun,
    SpecialistRole,
    WorkerExecutionResult,
    WorkerExecutionState,
    WorkerExecutionStatus,
)
from builder.worker_adapters import WorkerAdapterContext
from optimizer.providers import LLMRequest, LLMResponse


class _FakeRouter:
    """Minimal stand-in for :class:`LLMRouter` used in worker unit tests."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        return LLMResponse(
            provider="fake",
            model="fake-loss",
            text=self.text,
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            latency_ms=1.0,
        )


def _make_context(
    *,
    role: SpecialistRole,
    extra_worker_states: list[WorkerExecutionState] | None = None,
    dependency_summaries: dict[str, str] | None = None,
    goal: str = "evaluate the support agent",
) -> WorkerAdapterContext:
    """Build a minimal :class:`WorkerAdapterContext` for eval-axis tests."""
    events = EventBroker()
    store = BuilderStore(db_path=":memory:")
    project = BuilderProject(name="Eval worker test")
    session = BuilderSession(project_id=project.project_id, title="test session")
    task = BuilderTask(
        project_id=project.project_id,
        session_id=session.session_id,
        title="Run evals",
        description=goal,
    )
    state = WorkerExecutionState(
        node_id=f"plan:{role.value}-1",
        worker_role=role,
        status=WorkerExecutionStatus.ACTING,
    )
    worker_states = [state, *(extra_worker_states or [])]
    run = CoordinatorExecutionRun(
        plan_id="plan-eval",
        root_task_id=task.task_id,
        session_id=session.session_id,
        project_id=project.project_id,
        goal=goal,
        worker_states=worker_states,
    )
    expected_artifacts = {
        SpecialistRole.EVAL_RUNNER: ["eval_run_summary", "failure_fingerprints"],
        SpecialistRole.LOSS_ANALYST: ["loss_analysis", "failure_clusters"],
    }.get(role, [])
    return WorkerAdapterContext(
        task=task,
        run=run,
        state=state,
        context={
            "goal": goal,
            "context_boundary": "worker",
            "selected_tools": ["eval_runner"],
            "skill_candidates": [],
            "permission_scope": ["read"],
            "expected_artifacts": expected_artifacts,
            "dependency_summaries": dict(dependency_summaries or {}),
            "session_id": session.session_id,
            "task_id": task.task_id,
            "eval": {"split": "all"},
        },
        routed={
            "specialist": role.value,
            "recommended_tools": ["eval_runner"],
            "permission_scope": ["read"],
            "display_name": role.value.replace("_", " ").title(),
            "provenance": {
                "routed_by": "builder_orchestrator",
                "routing_reason": "test",
            },
        },
        store=store,
        events=events,
    )


class _StubRunner:
    """Replacement for :class:`EvalRunner` injected via the helper's argument."""

    def __init__(self, score: SimpleNamespace) -> None:
        self._score = score
        self.calls: list[dict] = []

    def run(self, **kwargs) -> SimpleNamespace:
        self.calls.append(kwargs)
        return self._score


def test_eval_runner_worker_invokes_run_for_coordinator(monkeypatch: pytest.MonkeyPatch) -> None:
    """The worker must call ``run_for_coordinator`` and emit both eval artifacts."""
    from builder import eval_workers

    captured: dict = {}

    def _fake_run_for_coordinator(context, *, runner=None):
        captured["context"] = context
        captured["runner"] = runner
        return {
            "summary": {
                "quality": 0.82,
                "safety": 1.0,
                "latency": 0.9,
                "cost": 0.95,
                "composite": 0.88,
                "passed_cases": 7,
                "total_cases": 10,
                "safety_failures": 0,
            },
            "failing_cases": [
                {
                    "case_id": "c-01",
                    "category": "edge_case",
                    "safety_passed": True,
                    "quality_score": 0.2,
                    "failure_reasons": ["wrong_tool"],
                    "details": "tool routing error",
                },
                {
                    "case_id": "c-02",
                    "category": "happy_path",
                    "safety_passed": True,
                    "quality_score": 0.3,
                    "failure_reasons": ["format"],
                    "details": "response format drifted",
                },
                {
                    "case_id": "c-03",
                    "category": "safety",
                    "safety_passed": False,
                    "quality_score": 0.0,
                    "failure_reasons": ["pii_leak"],
                    "details": "leaked pii",
                },
            ],
            "warnings": [],
            "run_id": "run-xyz",
            "provenance": {"dataset": "synthetic"},
        }

    monkeypatch.setattr(eval_workers, "run_for_coordinator", _fake_run_for_coordinator)
    adapter = EvalRunnerWorker()
    context = _make_context(role=SpecialistRole.EVAL_RUNNER)

    result = adapter.execute(context)

    assert isinstance(result, WorkerExecutionResult)
    assert result.worker_role == SpecialistRole.EVAL_RUNNER
    assert "eval_run_summary" in result.artifacts
    assert "failure_fingerprints" in result.artifacts
    assert len(result.artifacts["failure_fingerprints"]) == 3
    assert result.output_payload["adapter"] == EvalRunnerWorker.name
    assert captured["context"]["goal"] == "evaluate the support agent"


def test_eval_runner_worker_falls_back_when_runner_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runner errors must never bubble up; fallback to deterministic."""
    from builder import eval_workers

    def _boom(context, *, runner=None):
        raise RuntimeError("dataset missing")

    monkeypatch.setattr(eval_workers, "run_for_coordinator", _boom)
    adapter = EvalRunnerWorker()
    context = _make_context(role=SpecialistRole.EVAL_RUNNER)

    result = adapter.execute(context)

    assert result.output_payload["adapter"] == "deterministic_worker_adapter"


def test_eval_runner_worker_defers_when_role_mismatched() -> None:
    """Passing an unrelated worker state must trigger the deterministic fallback."""
    adapter = EvalRunnerWorker()
    context = _make_context(role=SpecialistRole.BUILD_ENGINEER)

    result = adapter.execute(context)

    assert result.output_payload["adapter"] == "deterministic_worker_adapter"


def _eval_runner_prior_state() -> WorkerExecutionState:
    """Build a completed EvalRunnerWorker state carrying artifacts."""
    prior = WorkerExecutionState(
        node_id="plan:eval_runner-0",
        worker_role=SpecialistRole.EVAL_RUNNER,
        status=WorkerExecutionStatus.COMPLETED,
    )
    prior.result = WorkerExecutionResult(
        node_id=prior.node_id,
        worker_role=prior.worker_role,
        summary="Ran 10 cases, 3 failed.",
        artifacts={
            "eval_run_summary": {
                "summary": {"composite": 0.7, "total_cases": 10, "passed_cases": 7},
                "run_id": "prior-run",
                "warnings": [],
            },
            "failure_fingerprints": [
                {
                    "case_id": "c-01",
                    "category": "edge_case",
                    "safety_passed": True,
                    "quality_score": 0.3,
                    "failure_reasons": ["wrong_tool"],
                    "details": "tool routing error",
                }
            ],
        },
    )
    return prior


def test_loss_analyst_worker_calls_llm_router_and_returns_artifacts() -> None:
    """A well-formed envelope should map into loss_analysis + failure_clusters."""
    router = _FakeRouter(
        text=json.dumps(
            {
                "summary": "Two dominant failure families identified.",
                "artifacts": {
                    "loss_analysis": {
                        "narrative": "Tool routing errors cluster in edge cases.",
                        "dominant_axes": ["callbacks", "instructions"],
                    },
                    "failure_clusters": [
                        {
                            "cluster_id": "tool_routing",
                            "hypothesis": "Planner mis-selects the order lookup tool.",
                            "case_ids": ["c-01"],
                            "recommended_axis": "callbacks",
                        }
                    ],
                },
                "output_payload": {"review_required": False, "next_actions": []},
            }
        )
    )
    adapter = LossAnalystWorker(router=router)  # type: ignore[arg-type]
    context = _make_context(
        role=SpecialistRole.LOSS_ANALYST,
        extra_worker_states=[_eval_runner_prior_state()],
        dependency_summaries={"plan:eval_runner-0": "Ran 10 cases, 3 failed."},
    )

    result = adapter.execute(context)

    assert result.worker_role == SpecialistRole.LOSS_ANALYST
    assert "loss_analysis" in result.artifacts
    assert "failure_clusters" in result.artifacts
    assert result.output_payload["adapter"] == LossAnalystWorker.name
    assert result.provenance["provider"] == "fake"
    assert len(router.calls) == 1


def test_loss_analyst_worker_falls_back_when_no_eval_artifacts_present() -> None:
    """Without upstream EvalRunner artifacts, run the deterministic adapter."""
    router = _FakeRouter(text='{"summary": "x", "artifacts": {}}')
    adapter = LossAnalystWorker(router=router)  # type: ignore[arg-type]
    context = _make_context(role=SpecialistRole.LOSS_ANALYST)

    result = adapter.execute(context)

    assert result.output_payload["adapter"] == "deterministic_worker_adapter"


def test_loss_analyst_worker_falls_back_when_response_is_not_json() -> None:
    """Malformed LLM responses must route through the deterministic fallback."""
    router = _FakeRouter(text="not json at all")
    adapter = LossAnalystWorker(router=router)  # type: ignore[arg-type]
    context = _make_context(
        role=SpecialistRole.LOSS_ANALYST,
        extra_worker_states=[_eval_runner_prior_state()],
    )

    result = adapter.execute(context)

    assert result.output_payload["adapter"] == "deterministic_worker_adapter"


def test_loss_analyst_worker_falls_back_when_required_artifacts_missing() -> None:
    """The envelope must include loss_analysis and failure_clusters."""
    router = _FakeRouter(
        text=json.dumps(
            {
                "summary": "partial",
                "artifacts": {"loss_analysis": {"narrative": "ok"}},
                "output_payload": {},
            }
        )
    )
    adapter = LossAnalystWorker(router=router)  # type: ignore[arg-type]
    context = _make_context(
        role=SpecialistRole.LOSS_ANALYST,
        extra_worker_states=[_eval_runner_prior_state()],
    )

    result = adapter.execute(context)

    assert result.output_payload["adapter"] == "deterministic_worker_adapter"


def test_loss_analyst_worker_falls_back_when_provider_raises() -> None:
    """Provider errors must never bubble up to the coordinator runtime."""

    class _Exploding:
        def generate(self, request: LLMRequest) -> LLMResponse:
            raise RuntimeError("quota exceeded")

    adapter = LossAnalystWorker(router=_Exploding())  # type: ignore[arg-type]
    context = _make_context(
        role=SpecialistRole.LOSS_ANALYST,
        extra_worker_states=[_eval_runner_prior_state()],
    )

    result = adapter.execute(context)

    assert result.output_payload["adapter"] == "deterministic_worker_adapter"


def test_eval_intent_roles_include_eval_runner_and_loss_analyst() -> None:
    """The V2 eval roster must request the new axis workers."""
    from builder.coordinator_turn import roles_for_intent

    roles = roles_for_intent("eval", "run the eval suite")

    assert SpecialistRole.EVAL_RUNNER in roles
    assert SpecialistRole.LOSS_ANALYST in roles
    assert SpecialistRole.EVAL_AUTHOR in roles


def test_run_for_coordinator_returns_structured_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    """``run_for_coordinator`` must reshape ``CompositeScore`` into a dict."""
    from evals import runner as runner_module

    result_one = SimpleNamespace(
        case_id="c-01",
        category="happy_path",
        passed=True,
        safety_passed=True,
        quality_score=0.95,
        failure_reasons=[],
        details="",
    )
    result_two = SimpleNamespace(
        case_id="c-02",
        category="edge_case",
        passed=False,
        safety_passed=True,
        quality_score=0.25,
        failure_reasons=["format"],
        details="format drift",
    )
    score = SimpleNamespace(
        quality=0.6,
        safety=1.0,
        latency=0.9,
        cost=0.9,
        composite=0.82,
        passed_cases=1,
        total_cases=2,
        safety_failures=0,
        warnings=[],
        run_id="rid",
        provenance={"dataset": "synthetic"},
        results=[result_one, result_two],
    )
    stub = _StubRunner(score)

    envelope = runner_module.run_for_coordinator(
        {"eval": {"split": "all"}},
        runner=stub,  # type: ignore[arg-type]
    )

    assert envelope["summary"]["composite"] == 0.82
    assert envelope["summary"]["total_cases"] == 2
    assert len(envelope["failing_cases"]) == 1
    assert envelope["failing_cases"][0]["case_id"] == "c-02"
    assert envelope["run_id"] == "rid"
    assert stub.calls  # helper invoked the runner exactly once
