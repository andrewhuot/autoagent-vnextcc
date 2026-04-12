"""Typed Workbench -> Eval -> Optimize bridge contracts.

WHY: Workbench completion should hand off a concrete candidate and machine
evidence to Eval/Optimize through explicit request shapes, not through UI prose
or the AutoFix proposal path.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any
from urllib.parse import urlencode

from pydantic import BaseModel, Field


class WorkbenchEvalRunRequest(BaseModel):
    """Eval API request payload produced from a Workbench candidate."""

    config_path: str | None = None
    category: str | None = None
    dataset_path: str | None = None
    generated_suite_id: str | None = None
    split: str = "all"


class WorkbenchOptimizeRequest(BaseModel):
    """Optimize API request payload produced after a Workbench-scoped eval run."""

    window: int = 100
    force: bool = True
    require_human_approval: bool = True
    config_path: str | None = None
    eval_run_id: str | None = None
    mode: str = "standard"
    objective: str = "Improve failures from the Workbench candidate eval run."
    guardrails: list[str] = Field(
        default_factory=lambda: ["Preserve Workbench validation and target compatibility."]
    )
    research_algorithm: str = ""
    budget_cycles: int = 10
    budget_dollars: float = 50.0


class WorkbenchBridgeCandidate(BaseModel):
    """Stable identity for the Workbench candidate being handed downstream."""

    project_id: str
    run_id: str
    turn_id: str | None = None
    version: int
    target: str
    environment: str
    agent_name: str
    validation_status: str
    review_gate_status: str
    active_artifact_id: str | None = None
    generated_config_hash: str
    config_path: str | None = None
    eval_cases_path: str | None = None
    export_targets: list[str] = Field(default_factory=list)


class WorkbenchBridgeEvaluationStep(BaseModel):
    """Eval readiness and request payload for a Workbench candidate."""

    status: str
    request: WorkbenchEvalRunRequest | None = None
    start_endpoint: str = "/api/eval/run"
    blocking_reasons: list[str] = Field(default_factory=list)
    readiness_state: str = "blocked"
    label: str = "Eval blocked"
    description: str = "Resolve the Workbench blockers before running Eval."
    primary_action_label: str | None = None
    primary_action_target: str | None = None
    prerequisite_step: str | None = None


class WorkbenchBridgeOptimizationStep(BaseModel):
    """Optimize readiness and request template for a completed eval run."""

    status: str
    requires_eval_run: bool = True
    request_template: WorkbenchOptimizeRequest | None = None
    start_endpoint: str = "/api/optimize/run"
    blocking_reasons: list[str] = Field(default_factory=list)
    readiness_state: str = "blocked"
    label: str = "Optimize blocked"
    description: str = "Resolve Eval prerequisites before starting Optimize."
    primary_action_label: str | None = None
    primary_action_target: str | None = None
    prerequisite_step: str | None = None


class WorkbenchImprovementHandoff(BaseModel):
    """Typed Workbench bridge object consumed by Eval and Optimize workflows."""

    kind: str = "workbench_eval_optimize"
    schema_version: int = 1
    candidate: WorkbenchBridgeCandidate
    evaluation: WorkbenchBridgeEvaluationStep
    optimization: WorkbenchBridgeOptimizationStep
    review_gate: dict[str, Any] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)
    created_from: str = "workbench"


def build_workbench_improvement_bridge(
    project: dict[str, Any],
    *,
    run: dict[str, Any],
    config_path: str | None = None,
    eval_cases_path: str | None = None,
    eval_run_id: str | None = None,
    category: str | None = None,
    dataset_path: str | None = None,
    generated_suite_id: str | None = None,
    split: str = "all",
) -> WorkbenchImprovementHandoff:
    """Build the typed bridge from persisted Workbench state.

    The bridge intentionally prepares an Optimize request only after a real eval
    run exists. Before that, Optimize is represented as an awaiting-eval template.
    """

    exports = project.get("exports") if isinstance(project.get("exports"), dict) else {}
    generated_config = exports.get("generated_config") if isinstance(exports.get("generated_config"), dict) else {}
    validation = _latest_validation(project, run)
    review_gate = run.get("review_gate") if isinstance(run.get("review_gate"), dict) else {}
    validation_status = str(validation.get("status") or "missing")
    review_gate_status = str(review_gate.get("status") or "unknown")
    machine_blockers = _machine_blocking_reasons(
        project,
        run,
        validation_status=validation_status,
        review_gate=review_gate,
        generated_config=generated_config,
    )

    candidate = WorkbenchBridgeCandidate(
        project_id=str(project.get("project_id") or ""),
        run_id=str(run.get("run_id") or ""),
        turn_id=str(run.get("turn_id")) if run.get("turn_id") else None,
        version=int(project.get("version") or run.get("completed_version") or 1),
        target=str(project.get("target") or run.get("target") or "portable"),
        environment=str(project.get("environment") or run.get("environment") or "draft"),
        agent_name=_agent_name(project, generated_config),
        validation_status=validation_status,
        review_gate_status=review_gate_status,
        active_artifact_id=_active_artifact_id(run),
        generated_config_hash=_hash_payload(generated_config),
        config_path=config_path,
        eval_cases_path=eval_cases_path,
        export_targets=_export_targets(exports),
    )

    evaluation = _build_evaluation_step(
        candidate,
        machine_blockers=machine_blockers,
        category=category,
        dataset_path=dataset_path,
        generated_suite_id=generated_suite_id,
        split=split,
    )
    optimization = _build_optimization_step(
        candidate,
        evaluation=evaluation,
        eval_run_id=eval_run_id,
    )

    return WorkbenchImprovementHandoff(
        candidate=candidate,
        evaluation=evaluation,
        optimization=optimization,
        review_gate=copy.deepcopy(review_gate),
        validation=copy.deepcopy(validation),
    )


def build_workbench_optimize_request(
    bridge: WorkbenchImprovementHandoff | dict[str, Any],
    *,
    eval_run_id: str,
) -> WorkbenchOptimizeRequest:
    """Create a concrete Optimize request from a bridge and completed eval run."""

    handoff = _coerce_bridge(bridge)
    if not eval_run_id.strip():
        raise ValueError("Optimize requires a completed eval run ID from the Workbench candidate.")
    if handoff.evaluation.status != "ready":
        raise ValueError("Workbench candidate is not ready for eval-scoped optimization.")
    if not handoff.candidate.config_path:
        raise ValueError("Workbench candidate must be materialized to a config path before optimization.")
    return WorkbenchOptimizeRequest(
        config_path=handoff.candidate.config_path,
        eval_run_id=eval_run_id,
    )


def _coerce_bridge(bridge: WorkbenchImprovementHandoff | dict[str, Any]) -> WorkbenchImprovementHandoff:
    """Normalize model or dict bridge inputs for helper reuse."""
    if isinstance(bridge, WorkbenchImprovementHandoff):
        return bridge
    return WorkbenchImprovementHandoff.model_validate(bridge)


def _latest_validation(project: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    """Return newest Workbench validation payload from run or project state."""
    validation = run.get("validation")
    if isinstance(validation, dict):
        return validation
    validation = project.get("last_test")
    return validation if isinstance(validation, dict) else {}


def _machine_blocking_reasons(
    project: dict[str, Any],
    run: dict[str, Any],
    *,
    validation_status: str,
    review_gate: dict[str, Any],
    generated_config: dict[str, Any],
) -> list[str]:
    """Return blockers that prevent a truthful Eval handoff."""
    reasons: list[str] = []
    if validation_status != "passed":
        reasons.append(f"Latest harness validation is {validation_status}.")
    invalid = [
        item
        for item in project.get("compatibility", [])
        if isinstance(item, dict) and item.get("status") == "invalid"
    ]
    if invalid:
        reasons.append(f"{len(invalid)} invalid target compatibility diagnostic(s).")
    if not generated_config:
        reasons.append("Workbench candidate has no generated config to evaluate.")
    if str(run.get("status") or "") not in {"completed", "presenting"}:
        reasons.append("Workbench run has not completed successfully.")
    for reason in list(review_gate.get("blocking_reasons") or []):
        text = str(reason)
        if text:
            reasons.append(text)
    return _dedupe(reasons)


def _build_evaluation_step(
    candidate: WorkbenchBridgeCandidate,
    *,
    machine_blockers: list[str],
    category: str | None,
    dataset_path: str | None,
    generated_suite_id: str | None,
    split: str,
) -> WorkbenchBridgeEvaluationStep:
    """Build Eval readiness from candidate materialization state."""
    if machine_blockers:
        draft_only = _is_draft_only_candidate(candidate, machine_blockers)
        return WorkbenchBridgeEvaluationStep(
            status="blocked",
            blocking_reasons=machine_blockers,
            readiness_state="draft_only" if draft_only else "blocked",
            label="Draft only" if draft_only else "Eval blocked",
            description=(
                "Finish a Workbench run that produces a generated config before opening Eval."
                if draft_only
                else "Resolve the Workbench blockers before running Eval for this candidate."
            ),
            primary_action_label="Return to Workbench",
            primary_action_target="/workbench",
            prerequisite_step="finish_workbench_candidate" if draft_only else "resolve_workbench_blockers",
        )
    if not candidate.config_path:
        return WorkbenchBridgeEvaluationStep(
            status="needs_saved_config",
            readiness_state="needs_materialization",
            label="Save candidate before Eval",
            description="The Workbench candidate passed validation, but Eval needs a saved config file first.",
            primary_action_label="Save candidate and open Eval",
            primary_action_target=_eval_handoff_target(candidate),
            prerequisite_step="materialize_candidate",
            blocking_reasons=["Materialize the Workbench candidate config before starting Eval."],
        )
    request = WorkbenchEvalRunRequest(
        config_path=candidate.config_path,
        category=category,
        dataset_path=dataset_path,
        generated_suite_id=generated_suite_id,
        split=split,
    )
    return WorkbenchBridgeEvaluationStep(
        status="ready",
        readiness_state="ready_for_eval",
        label="Ready for Eval",
        description="The Workbench candidate is saved and ready for an Eval run.",
        primary_action_label="Open Eval with this candidate",
        primary_action_target=_eval_handoff_target(candidate, request=request),
        prerequisite_step=None,
        request=request,
        blocking_reasons=[],
    )


def _build_optimization_step(
    candidate: WorkbenchBridgeCandidate,
    *,
    evaluation: WorkbenchBridgeEvaluationStep,
    eval_run_id: str | None,
) -> WorkbenchBridgeOptimizationStep:
    """Build Optimize readiness while preserving Eval as a required predecessor."""
    if evaluation.status == "blocked":
        draft_only = evaluation.readiness_state == "draft_only"
        return WorkbenchBridgeOptimizationStep(
            status="blocked",
            request_template=None,
            blocking_reasons=list(evaluation.blocking_reasons),
            readiness_state="draft_only" if draft_only else "blocked",
            label="Draft only" if draft_only else "Optimize blocked",
            description=(
                "Finish a Workbench run and create an Eval-ready candidate before starting Optimize."
                if draft_only
                else "Resolve Eval blockers before Optimize can use this Workbench candidate."
            ),
            primary_action_label=evaluation.primary_action_label,
            primary_action_target=evaluation.primary_action_target,
            prerequisite_step=evaluation.prerequisite_step,
        )
    if evaluation.status != "ready" or not candidate.config_path:
        return WorkbenchBridgeOptimizationStep(
            status="blocked",
            request_template=None,
            blocking_reasons=["Start Eval only after the Workbench candidate has a saved config path."],
            readiness_state="needs_eval_candidate",
            label="Eval candidate not ready",
            description="Save the Workbench candidate and run Eval before starting Optimize.",
            primary_action_label=evaluation.primary_action_label,
            primary_action_target=evaluation.primary_action_target,
            prerequisite_step=evaluation.prerequisite_step or "materialize_candidate",
        )
    template = WorkbenchOptimizeRequest(
        config_path=candidate.config_path,
        eval_run_id=eval_run_id,
    )
    if eval_run_id:
        return WorkbenchBridgeOptimizationStep(
            status="ready",
            request_template=template,
            blocking_reasons=[],
            readiness_state="ready_for_optimize",
            label="Ready for Optimize",
            description="Eval has run for this Workbench candidate, so Optimize can use that failure context.",
            primary_action_label="Start Optimize from Eval run",
            primary_action_target=_optimize_handoff_target(candidate, eval_run_id=eval_run_id),
            prerequisite_step=None,
        )
    return WorkbenchBridgeOptimizationStep(
        status="awaiting_eval_run",
        request_template=template,
        blocking_reasons=["Run Eval first; Optimize requires a completed eval run."],
        readiness_state="awaiting_eval_run",
        label="Run Eval before Optimize",
        description="Optimize is waiting for a completed Eval run for this saved Workbench candidate.",
        primary_action_label="Open Eval with this candidate",
        primary_action_target=evaluation.primary_action_target,
        prerequisite_step="complete_eval_run",
    )


def _agent_name(project: dict[str, Any], generated_config: dict[str, Any]) -> str:
    """Extract a human-readable agent name from generated or canonical state."""
    metadata = generated_config.get("metadata") if isinstance(generated_config.get("metadata"), dict) else {}
    if metadata.get("agent_name"):
        return str(metadata["agent_name"])
    model = project.get("model") if isinstance(project.get("model"), dict) else {}
    agents = model.get("agents") if isinstance(model.get("agents"), list) else []
    first = agents[0] if agents and isinstance(agents[0], dict) else {}
    return str(first.get("name") or project.get("name") or "Workbench Agent")


def _active_artifact_id(run: dict[str, Any]) -> str | None:
    """Read the active artifact pointer from a run presentation, if present."""
    presentation = run.get("presentation") if isinstance(run.get("presentation"), dict) else {}
    value = presentation.get("active_artifact_id")
    return str(value) if value else None


def _export_targets(exports: dict[str, Any]) -> list[str]:
    """Return generated export targets available for this Workbench candidate."""
    targets: list[str] = []
    for key, value in exports.items():
        if key == "generated_config" or not isinstance(value, dict):
            continue
        if value.get("files"):
            targets.append(str(key))
    return sorted(targets)


def _hash_payload(payload: dict[str, Any]) -> str:
    """Build a stable hash for generated config identity checks."""
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return f"sha256:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def _eval_handoff_target(
    candidate: WorkbenchBridgeCandidate,
    *,
    request: WorkbenchEvalRunRequest | None = None,
) -> str:
    """Build a product route that preserves the Workbench candidate context."""
    params: dict[str, str] = {
        "new": "1",
        "from": "workbench",
        "workbenchProjectId": candidate.project_id,
        "candidate": candidate.agent_name,
    }
    config_path = request.config_path if request else candidate.config_path
    if config_path:
        params["configPath"] = config_path
    if request and request.generated_suite_id:
        params["generatedSuiteId"] = request.generated_suite_id
    if request and request.dataset_path:
        params["datasetPath"] = request.dataset_path
    if request and request.category:
        params["category"] = request.category
    if request and request.split:
        params["split"] = request.split
    return f"/evals?{urlencode(params)}"


def _optimize_handoff_target(candidate: WorkbenchBridgeCandidate, *, eval_run_id: str) -> str:
    """Build an Optimize route scoped to a completed Workbench Eval run."""
    params: dict[str, str] = {
        "from": "workbench",
        "workbenchProjectId": candidate.project_id,
        "candidate": candidate.agent_name,
        "evalRunId": eval_run_id,
    }
    if candidate.config_path:
        params["configPath"] = candidate.config_path
    return f"/optimize?{urlencode(params)}"


def _is_draft_only_candidate(candidate: WorkbenchBridgeCandidate, reasons: list[str]) -> bool:
    """Return whether blockers describe a draft that has not produced a candidate yet."""
    validation_status = candidate.validation_status.lower()
    if validation_status not in {"missing", "not_run", "unknown"}:
        return False
    lowered = [reason.lower() for reason in reasons]
    return any("no generated config" in reason for reason in lowered) or any(
        "has not completed" in reason for reason in lowered
    )


def _dedupe(values: list[str]) -> list[str]:
    """Preserve first occurrence order while removing duplicate reason text."""
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
