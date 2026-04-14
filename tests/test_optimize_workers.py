"""Unit tests for V3 optimize-axis coordinator workers."""

from __future__ import annotations

import json

from builder.coordinator_runtime import CoordinatorWorkerRuntime
from builder.coordinator_turn import CoordinatorTurnService, roles_for_intent
from builder.events import EventBroker
from builder.llm_worker import LLMWorkerAdapter
from builder.orchestrator import BuilderOrchestrator
from builder.store import BuilderStore
from builder.types import (
    CoordinatorExecutionStatus,
    SpecialistRole,
    WorkerExecutionStatus,
)
from optimizer.loop import Optimizer
from optimizer.providers import LLMRequest, LLMResponse


_AXIS_ARTIFACTS = {
    SpecialistRole.INSTRUCTION_OPTIMIZER: "instructions_change_card",
    SpecialistRole.GUARDRAIL_OPTIMIZER: "guardrails_change_card",
    SpecialistRole.CALLBACK_OPTIMIZER: "callbacks_change_card",
}


_EXPECTED_ARTIFACTS_BY_ROLE: dict[SpecialistRole, list[str]] = {
    SpecialistRole.INSTRUCTION_OPTIMIZER: ["instructions_change_card"],
    SpecialistRole.GUARDRAIL_OPTIMIZER: ["guardrails_change_card"],
    SpecialistRole.CALLBACK_OPTIMIZER: ["callbacks_change_card"],
    SpecialistRole.OPTIMIZATION_ENGINEER: [
        "optimization_plan",
        "change_card",
        "experiment_summary",
    ],
    SpecialistRole.EVAL_AUTHOR: ["eval_bundle", "benchmark_plan"],
    SpecialistRole.TRACE_ANALYST: ["trace_evidence", "root_cause_summary"],
}


class _RoleAwareRouter:
    """Fake router that returns role-specific canned JSON envelopes."""

    def __init__(self, responses: dict[SpecialistRole, dict]) -> None:
        self._responses = responses
        self.calls: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        role_value = (request.metadata or {}).get("worker_role", "")
        try:
            role = SpecialistRole(role_value)
        except ValueError:
            role = SpecialistRole.ORCHESTRATOR
        envelope = self._responses.get(role) or self._default_envelope(role)
        return LLMResponse(
            provider="fake",
            model="fake-axis",
            text=json.dumps(envelope),
            prompt_tokens=5,
            completion_tokens=15,
            total_tokens=20,
            latency_ms=1.0,
        )

    @staticmethod
    def _default_envelope(role: SpecialistRole) -> dict:
        artifacts = {name: {"placeholder": True} for name in _EXPECTED_ARTIFACTS_BY_ROLE.get(role, [])}
        return {
            "summary": f"default {role.value} output",
            "artifacts": artifacts,
            "output_payload": {"review_required": False, "next_actions": []},
        }


def _axis_envelope(role: SpecialistRole) -> dict:
    """Return a valid axis-optimizer envelope for the given role."""
    artifact_name = _AXIS_ARTIFACTS[role]
    return {
        "summary": f"{role.value} drafted a single {artifact_name}.",
        "artifacts": {
            artifact_name: {
                "hypothesis": f"Hypothesis for {role.value}",
                "expected_delta": {"quality": 0.05},
                "verification_plan": "Run the verification eval after applying.",
                "before": "old",
                "after": "new",
            }
        },
        "output_payload": {
            "review_required": True,
            "next_actions": ["Review axis change card before apply."],
            "axis": artifact_name.split("_change_card")[0],
        },
    }


def _eval_author_envelope() -> dict:
    """Return a valid envelope for the verification eval author worker."""
    return {
        "summary": "Prepared verification eval plan for the three axis change cards.",
        "artifacts": {
            "eval_bundle": {
                "cases": ["c-axis-verify-1", "c-axis-verify-2"],
                "purpose": "verify axis-scoped optimizer changes",
            },
            "benchmark_plan": {
                "runs": 2,
                "baseline_required": True,
            },
        },
        "output_payload": {
            "review_required": False,
            "next_actions": ["Run /eval with this bundle after apply."],
        },
    }


def test_optimize_intent_roster_includes_three_axis_roles() -> None:
    """The V3 optimize roster must request all three axis workers plus verification."""
    roles = roles_for_intent("optimize", "optimize from loss patterns")

    for axis_role in _AXIS_ARTIFACTS:
        assert axis_role in roles, f"missing axis role {axis_role.value}"
    assert SpecialistRole.OPTIMIZATION_ENGINEER in roles
    assert SpecialistRole.EVAL_AUTHOR in roles  # verification


def test_optimize_turn_produces_three_axis_change_cards(tmp_path) -> None:
    """Driving an optimize turn must persist 3 axis change cards + verification eval."""
    store = BuilderStore(db_path=str(tmp_path / "coord.db"))
    orchestrator = BuilderOrchestrator(store=store)
    events = EventBroker()

    axis_responses = {role: _axis_envelope(role) for role in _AXIS_ARTIFACTS}
    axis_responses[SpecialistRole.EVAL_AUTHOR] = _eval_author_envelope()
    router = _RoleAwareRouter(axis_responses)

    runtime = CoordinatorWorkerRuntime(
        store=store,
        orchestrator=orchestrator,
        events=events,
        default_worker_adapter=LLMWorkerAdapter(router=router),  # type: ignore[arg-type]
    )
    service = CoordinatorTurnService(
        store=store,
        orchestrator=orchestrator,
        events=events,
        runtime=runtime,
    )

    result = service.process_turn(
        "optimize from loss patterns",
        command_intent="optimize",
    )

    assert result.status == CoordinatorExecutionStatus.COMPLETED.value
    role_values = set(result.worker_roles)
    assert {
        SpecialistRole.INSTRUCTION_OPTIMIZER.value,
        SpecialistRole.GUARDRAIL_OPTIMIZER.value,
        SpecialistRole.CALLBACK_OPTIMIZER.value,
    }.issubset(role_values)
    assert SpecialistRole.EVAL_AUTHOR.value in role_values  # verification

    run = store.get_coordinator_run(result.run_id)
    assert run is not None

    axis_cards_seen: set[str] = set()
    eval_verification_seen = False
    for state in run.worker_states:
        if state.status != WorkerExecutionStatus.COMPLETED:
            continue
        if state.result is None:
            continue
        if state.worker_role in _AXIS_ARTIFACTS:
            expected_key = _AXIS_ARTIFACTS[state.worker_role]
            assert expected_key in state.result.artifacts
            axis_cards_seen.add(expected_key)
        if state.worker_role == SpecialistRole.EVAL_AUTHOR:
            assert "eval_bundle" in state.result.artifacts
            eval_verification_seen = True

    assert axis_cards_seen == set(_AXIS_ARTIFACTS.values())
    assert eval_verification_seen


def test_run_axis_cycle_rejects_unsupported_axis() -> None:
    """Invalid axis labels must return a REJECTED status without calling optimize()."""
    from evals.runner import EvalRunner

    optimizer = Optimizer(eval_runner=EvalRunner())

    candidate, status, axis = optimizer.run_axis_cycle(
        "magic",
        health_report=_null_health_report(),
        current_config={},
    )

    assert candidate is None
    assert status.startswith("REJECTED")
    assert axis == "magic"


def test_run_axis_cycle_delegates_to_optimize(monkeypatch) -> None:
    """A supported axis must delegate to :meth:`optimize` and preserve its result."""
    from evals.runner import EvalRunner

    optimizer = Optimizer(eval_runner=EvalRunner())
    called: dict = {}

    def _fake_optimize(**kwargs):
        called.update(kwargs)
        return ({"updated": True}, "OK")

    monkeypatch.setattr(optimizer, "optimize", _fake_optimize)

    candidate, status, axis = optimizer.run_axis_cycle(
        "instructions",
        health_report=_null_health_report(),
        current_config={"key": "value"},
    )

    assert candidate == {"updated": True}
    assert status == "OK"
    assert axis == "instructions"
    assert called["current_config"] == {"key": "value"}


def _null_health_report():
    """Return a minimal :class:`HealthReport` for axis-cycle smoke tests."""
    from observer.metrics import HealthMetrics, HealthReport

    return HealthReport(metrics=HealthMetrics(), failure_buckets={})
