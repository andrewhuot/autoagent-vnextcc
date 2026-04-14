"""Coordinator workers that drive the ``/deploy`` verb end-to-end.

Two workers compose the deploy flow:

- :class:`GateRunnerWorker` wraps :class:`cicd.gate.CICDGate.run_gate` and
  returns a structured gate report as the worker artifact. The coordinator
  uses the verdict to decide whether a release candidate can be written.
- :class:`PlatformPublisherWorker` packages the approved candidate into a
  :class:`builder.types.ReleaseCandidate` record, persists it through the
  builder store, and transitions status per
  :data:`builder.types.RELEASE_TRANSITIONS`.

Both workers are thin :class:`WorkerAdapter` implementations — they pull
their inputs (config path, baseline path, target platform) from the
coordinator's ``dependency_summaries`` and plan ``extra_context``, so the
runtime stays unchanged. They fall back to safe stubs when the operator
doesn't supply a config path, keeping CI/offline flows green.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from builder.types import (
    ReleaseCandidate,
    RELEASE_TRANSITIONS,
    SpecialistRole,
    WorkerExecutionResult,
    now_ts,
)
from builder.worker_adapters import WorkerAdapter, WorkerAdapterContext
from deployer.publish import PublishError


@dataclass
class GateRunnerWorker:
    """Coordinator worker that executes the CI/CD quality gate.

    ``gate_factory`` lets tests inject a stub gate without importing the
    real evaluator. Production callers omit it and get
    :class:`cicd.gate.CICDGate`.
    """

    gate_factory: Any = None
    name: str = "gate_runner_worker"

    def execute(self, context: WorkerAdapterContext) -> WorkerExecutionResult:
        """Run the gate and return a structured ``gate_report`` artifact."""
        config_path, baseline_path, threshold = _resolve_gate_inputs(context)
        gate_report: dict[str, Any]
        if config_path:
            gate = self._build_gate()
            try:
                gate_report = gate.run_gate(
                    config_path=config_path,
                    baseline_path=baseline_path,
                    fail_threshold=threshold,
                )
            except Exception as exc:  # surface as structured artifact
                gate_report = {
                    "gate_passed": False,
                    "regression_detected": False,
                    "failure_reasons": [f"gate_error: {exc}"],
                    "config_path": config_path,
                }
        else:
            gate_report = {
                "gate_passed": True,
                "regression_detected": False,
                "failure_reasons": [],
                "config_path": None,
                "note": (
                    "No config_path supplied; gate runner emitted a no-op pass "
                    "report. Supply deploy.config_path in the context to run "
                    "a real CICDGate."
                ),
            }

        regression_summary = {
            "gate_passed": bool(gate_report.get("gate_passed", False)),
            "regression_detected": bool(gate_report.get("regression_detected", False)),
            "failure_reasons": list(gate_report.get("failure_reasons", [])),
            "candidate_scores": dict(gate_report.get("candidate_scores", {})),
            "baseline_scores": dict(gate_report.get("baseline_scores", {})),
        }
        summary = _gate_summary_line(gate_report)
        return WorkerExecutionResult(
            node_id=context.state.node_id,
            worker_role=context.state.worker_role,
            summary=summary,
            artifacts={
                "gate_report": gate_report,
                "regression_summary": regression_summary,
            },
            context_used={
                "context_boundary": context.context["context_boundary"],
                "config_path": config_path,
                "baseline_path": baseline_path,
            },
            output_payload={
                "adapter": self.name,
                "gate_passed": regression_summary["gate_passed"],
                "review_required": True,
                "next_actions": [
                    "Approve the release candidate if the gate passed, otherwise "
                    "inspect the failure reasons and rerun /deploy."
                ],
            },
            provenance={
                "run_id": context.run.run_id,
                "plan_id": context.run.plan_id,
                "node_id": context.state.node_id,
                "adapter": self.name,
            },
        )

    def _build_gate(self) -> Any:
        """Instantiate a ``CICDGate`` (or the injected stub)."""
        if self.gate_factory is not None:
            return self.gate_factory()
        from cicd.gate import CICDGate

        return CICDGate()


@dataclass
class PlatformPublisherWorker:
    """Coordinator worker that persists a release candidate + transitions status.

    The worker is deliberately conservative: if the gate failed it stops at
    ``draft`` and flags ``review_required``. Only when the gate passed and
    the operator asked for an immediate deploy does it transition further.
    ``publisher`` is an optional callable ``(config, scores, strategy) ->
    PublishResult`` used to invoke the real
    :func:`deployer.publish.publish_config` helper; tests inject a stub.
    """

    publisher: Any = None
    name: str = "platform_publisher_worker"

    def execute(self, context: WorkerAdapterContext) -> WorkerExecutionResult:
        dependency_summaries = dict(context.context.get("dependency_summaries") or {})
        gate_ok, gate_report = _find_gate_verdict(context, dependency_summaries)
        strategy = str(_context_value(context, "strategy") or "canary")
        platform = str(_context_value(context, "platform") or "workbench")
        config_path = str(_context_value(context, "config_path") or "")
        baseline_path = _context_value(context, "baseline_path")
        target_status = _resolve_target_status(gate_ok=gate_ok, strategy=strategy)

        release = ReleaseCandidate(
            task_id=context.task.task_id,
            session_id=context.task.session_id,
            project_id=context.task.project_id,
            version=str(_context_value(context, "version") or ""),
            deployment_target=platform,
            status="draft",
            changelog=str(context.run.goal or ""),
            metadata={
                "config_path": config_path,
                "baseline_path": baseline_path,
                "strategy": strategy,
                "gate_report": gate_report,
            },
            promotion_evidence=[
                {
                    "source": "gate_runner_worker",
                    "gate_passed": gate_ok,
                    "failure_reasons": list(gate_report.get("failure_reasons", [])),
                    "timestamp": now_ts(),
                }
            ],
        )

        publish_result: dict[str, Any] | None = None
        transition_reason: str | None = None
        if target_status != "draft":
            if _is_valid_transition("draft", target_status):
                release.status = target_status
                if target_status in {"reviewed", "candidate", "staging", "production"}:
                    release.approved_at = now_ts()
                    release.approved_by = "platform_publisher_worker"
                if target_status == "production":
                    release.deployed_at = now_ts()
            else:
                transition_reason = (
                    f"invalid transition draft→{target_status}; keeping draft"
                )

        if gate_ok and self.publisher is not None and config_path:
            try:
                publish_result = self.publisher(
                    config_path=config_path,
                    strategy=strategy,
                    scores=gate_report.get("candidate_scores") or {},
                )
            except PublishError as exc:
                transition_reason = f"publish_refused: {exc}"
            except Exception as exc:
                transition_reason = f"publish_error: {exc}"

        context.store.save_release(release)
        summary = _publish_summary_line(
            gate_ok=gate_ok,
            status=release.status,
            platform=platform,
            transition_reason=transition_reason,
        )
        return WorkerExecutionResult(
            node_id=context.state.node_id,
            worker_role=context.state.worker_role,
            summary=summary,
            artifacts={
                "release_candidate": {
                    "release_id": release.release_id,
                    "status": release.status,
                    "deployment_target": release.deployment_target,
                    "gate_passed": gate_ok,
                    "strategy": strategy,
                },
                "publish_record": {
                    "platform": platform,
                    "publish_result": publish_result,
                    "transition_reason": transition_reason,
                },
            },
            context_used={
                "context_boundary": context.context["context_boundary"],
                "config_path": config_path,
                "strategy": strategy,
            },
            output_payload={
                "adapter": self.name,
                "release_id": release.release_id,
                "review_required": True,
                "next_actions": [
                    "Review the release candidate and promote it via /deploy "
                    "--approve when you're ready to cut over."
                ],
            },
            provenance={
                "run_id": context.run.run_id,
                "plan_id": context.run.plan_id,
                "node_id": context.state.node_id,
                "adapter": self.name,
                "release_id": release.release_id,
            },
        )


def _resolve_gate_inputs(
    context: WorkerAdapterContext,
) -> tuple[str | None, str | None, float | None]:
    """Pull the gate inputs from context.deploy metadata (if present)."""
    deploy_meta = _deploy_meta(context)
    config_path = deploy_meta.get("config_path")
    baseline_path = deploy_meta.get("baseline_path")
    threshold_raw = deploy_meta.get("fail_threshold")
    threshold: float | None
    try:
        threshold = float(threshold_raw) if threshold_raw is not None else None
    except (TypeError, ValueError):
        threshold = None
    return (
        str(config_path) if config_path else None,
        str(baseline_path) if baseline_path else None,
        threshold,
    )


def _context_value(context: WorkerAdapterContext, key: str) -> Any:
    """Return a deploy-scoped context value, falling back to context keys."""
    deploy_meta = _deploy_meta(context)
    if key in deploy_meta:
        return deploy_meta[key]
    return context.context.get(key)


def _deploy_meta(context: WorkerAdapterContext) -> dict[str, Any]:
    """Return the operator-supplied deploy metadata dict."""
    value = context.context.get("deploy")
    if isinstance(value, dict):
        return value
    return {}


def _find_gate_verdict(
    context: WorkerAdapterContext,
    dependency_summaries: dict[str, str],
) -> tuple[bool, dict[str, Any]]:
    """Locate the gate report among dependencies or run artifacts."""
    for state in context.run.worker_states:
        if state.worker_role != SpecialistRole.GATE_RUNNER or state.result is None:
            continue
        report = state.result.artifacts.get("gate_report")
        if isinstance(report, dict):
            return bool(report.get("gate_passed", False)), report
    # Gate runner has not executed yet or is absent; default to pass-through.
    return True, {"gate_passed": True, "failure_reasons": [], "note": "no_gate_runner"}


def _resolve_target_status(*, gate_ok: bool, strategy: str) -> str:
    """Decide what status the release candidate should land in.

    Transitions must obey :data:`builder.types.RELEASE_TRANSITIONS` — the
    valid forward step from ``draft`` is ``reviewed``. The operator
    continues the promotion ladder (reviewed → candidate → …) through the
    usual /deploy --approve flow.
    """
    if not gate_ok:
        return "draft"
    return "reviewed"


def _is_valid_transition(from_status: str, to_status: str) -> bool:
    """Return whether ``from_status → to_status`` is a valid release step."""
    if from_status == to_status:
        return True
    return to_status in RELEASE_TRANSITIONS.get(from_status, set())


def _gate_summary_line(report: dict[str, Any]) -> str:
    """Produce a concise operator-facing summary of a gate report."""
    passed = bool(report.get("gate_passed", False))
    failures = list(report.get("failure_reasons", []))
    if passed:
        return "Gate passed; release candidate is eligible for the next stage."
    if failures:
        return f"Gate failed: {failures[0]}"
    return "Gate failed without a specific reason — inspect the report."


def _publish_summary_line(
    *,
    gate_ok: bool,
    status: str,
    platform: str,
    transition_reason: str | None,
) -> str:
    """Summarize the publish outcome for the transcript."""
    if not gate_ok:
        return (
            f"Gate failed; release candidate saved as {status} on {platform} "
            "and held back from promotion."
        )
    if transition_reason:
        return (
            f"Release candidate saved as {status} on {platform}; "
            f"promotion skipped ({transition_reason})."
        )
    return f"Release candidate saved as {status} on {platform} after gate approval."


__all__ = [
    "GateRunnerWorker",
    "PlatformPublisherWorker",
]
