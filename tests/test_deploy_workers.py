"""Coverage for the V4 coordinator-backed /deploy flow.

The coordinator must turn a /deploy turn into:
- a CICDGate run that produces a structured gate_report
- a ReleaseCandidate persisted in the builder store
- a RELEASE_TRANSITIONS-compliant status for that candidate
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from builder.coordinator_runtime import CoordinatorWorkerRuntime
from builder.events import EventBroker
from builder.orchestrator import BuilderOrchestrator
from builder.store import BuilderStore
from builder.types import (
    BuilderProject,
    BuilderSession,
    BuilderTask,
    CoordinatorExecutionStatus,
    RELEASE_TRANSITIONS,
    SpecialistRole,
)
from cli.workbench_app.coordinator_session import CoordinatorSession
from deployer.coordinator_workers import GateRunnerWorker, PlatformPublisherWorker


@dataclass
class _StubGate:
    """Records run_gate invocations and returns a canned report."""

    report: dict[str, Any]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def run_gate(
        self,
        config_path: str,
        baseline_path: str | None = None,
        fail_threshold: float | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "config_path": config_path,
                "baseline_path": baseline_path,
                "fail_threshold": fail_threshold,
            }
        )
        return dict(self.report)


@pytest.fixture
def store(tmp_path: Path) -> BuilderStore:
    return BuilderStore(db_path=str(tmp_path / "builder.db"))


def _plan_deploy_turn(
    *,
    store: BuilderStore,
    gate_report: dict[str, Any],
    strategy: str = "canary",
    config_path: str = "/tmp/candidate.yaml",
    publisher: Any = None,
) -> tuple[CoordinatorSession, _StubGate, Any]:
    orchestrator = BuilderOrchestrator(store=store)
    gate = _StubGate(report=gate_report)
    gate_worker = GateRunnerWorker(gate_factory=lambda: gate)
    publisher_worker = PlatformPublisherWorker(publisher=publisher)
    runtime = CoordinatorWorkerRuntime(
        store=store,
        orchestrator=orchestrator,
        events=EventBroker(),
        worker_adapters={
            SpecialistRole.GATE_RUNNER: gate_worker,
            SpecialistRole.PLATFORM_PUBLISHER: publisher_worker,
        },
    )
    session = CoordinatorSession(
        store=store,
        orchestrator=orchestrator,
        events=EventBroker(),
        runtime=runtime,
    )
    result = session.process_turn(
        "Deploy the agent with a canary rollout",
        command_intent="deploy",
        context={
            "permission_mode": "default",
            "deploy": {
                "config_path": config_path,
                "baseline_path": None,
                "fail_threshold": 0.05,
                "strategy": strategy,
                "platform": "workbench",
                "version": "v042",
            },
        },
    )
    return session, gate, result


def test_deploy_runs_gate_and_writes_candidate_release(store: BuilderStore) -> None:
    session, gate, result = _plan_deploy_turn(
        store=store,
        gate_report={
            "gate_passed": True,
            "regression_detected": False,
            "failure_reasons": [],
            "candidate_scores": {"composite": 0.82},
            "baseline_scores": {"composite": 0.80},
        },
        strategy="canary",
    )

    assert result.status == CoordinatorExecutionStatus.COMPLETED.value
    assert gate.calls, "gate runner worker should have invoked CICDGate.run_gate"
    assert gate.calls[0]["config_path"] == "/tmp/candidate.yaml"

    releases = store.list_releases(project_id=result.project_id)
    assert len(releases) == 1
    release = releases[0]
    assert release.deployment_target == "workbench"
    # With gate_passed=True, publisher promotes draft → reviewed per
    # RELEASE_TRANSITIONS; further promotion (candidate → …) is operator-gated.
    assert release.status == "reviewed"
    assert "reviewed" in RELEASE_TRANSITIONS["draft"]

    # The release candidate carries gate evidence so reviewers can audit it.
    assert release.metadata["gate_report"]["gate_passed"] is True
    assert release.metadata["strategy"] == "canary"
    assert release.promotion_evidence[0]["gate_passed"] is True

    # Worker roster in the run must include both new specialist roles.
    assert SpecialistRole.GATE_RUNNER.value in result.worker_roles
    assert SpecialistRole.PLATFORM_PUBLISHER.value in result.worker_roles


def test_deploy_holds_release_when_gate_fails(store: BuilderStore) -> None:
    session, gate, result = _plan_deploy_turn(
        store=store,
        gate_report={
            "gate_passed": False,
            "regression_detected": True,
            "failure_reasons": ["Quality regression detected: -0.12 < -0.05"],
            "candidate_scores": {"composite": 0.68},
            "baseline_scores": {"composite": 0.80},
        },
        strategy="canary",
    )

    assert result.status == CoordinatorExecutionStatus.COMPLETED.value
    releases = store.list_releases(project_id=result.project_id)
    assert len(releases) == 1
    # Gate failed → publisher must keep the candidate at draft (no forward transition).
    assert releases[0].status == "draft"
    assert releases[0].promotion_evidence[0]["gate_passed"] is False


def test_deploy_invokes_publish_helper_when_gate_passes(store: BuilderStore) -> None:
    calls: list[dict[str, Any]] = []

    def stub_publisher(
        *, config_path: str, strategy: str, scores: dict[str, Any]
    ) -> dict[str, Any]:
        calls.append({"config_path": config_path, "strategy": strategy, "scores": scores})
        return {"message": f"Published {config_path} as {strategy}", "status": "ok"}

    _, gate, result = _plan_deploy_turn(
        store=store,
        gate_report={
            "gate_passed": True,
            "regression_detected": False,
            "failure_reasons": [],
            "candidate_scores": {"composite": 0.9},
        },
        strategy="immediate",
        publisher=stub_publisher,
    )

    assert calls, "publisher should run when gate passes and publisher is provided"
    assert calls[0]["strategy"] == "immediate"
    assert calls[0]["scores"]["composite"] == 0.9
    releases = store.list_releases(project_id=result.project_id)
    # Gate passed → draft → reviewed; operator still owns the next step.
    assert releases[0].status == "reviewed"


def test_deploy_gate_runner_with_no_config_emits_noop_report(store: BuilderStore) -> None:
    """Offline/CI callers without a config path still get a structured report."""
    orchestrator = BuilderOrchestrator(store=store)
    runtime = CoordinatorWorkerRuntime(
        store=store,
        orchestrator=orchestrator,
        events=EventBroker(),
    )
    session = CoordinatorSession(
        store=store,
        orchestrator=orchestrator,
        events=EventBroker(),
        runtime=runtime,
    )
    result = session.process_turn(
        "Deploy without a config path",
        command_intent="deploy",
        context={"permission_mode": "default", "deploy": {"strategy": "canary"}},
    )

    assert result.status == CoordinatorExecutionStatus.COMPLETED.value
    # Even without a gate run, a release candidate is persisted.
    releases = store.list_releases(project_id=result.project_id)
    assert len(releases) == 1
    # No config → noop gate → gate_passed=True → draft → reviewed.
    assert releases[0].status == "reviewed"
    assert releases[0].metadata["gate_report"].get("note") == "no_gate_runner" or \
        "No config_path" in str(releases[0].metadata["gate_report"].get("note", ""))
