"""Worker adapter contracts for coordinator-owned execution.

The orchestrator decides which specialist roles should work on a goal. This
module defines the bounded execution seam each worker uses so the coordinator
runtime can call role-specific services without baking product behavior into
the lifecycle engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from builder.events import EventBroker
from builder.store import BuilderStore
from builder.types import (
    BuilderTask,
    CoordinatorExecutionRun,
    SpecialistRole,
    WorkerExecutionResult,
    WorkerExecutionState,
)


@dataclass(frozen=True)
class WorkerAdapterContext:
    """Context handed to a worker adapter for one coordinator node."""

    task: BuilderTask
    run: CoordinatorExecutionRun
    state: WorkerExecutionState
    context: dict[str, Any]
    routed: dict[str, Any]
    store: BuilderStore
    events: EventBroker


class WorkerAdapter(Protocol):
    """Execution contract for a bounded specialist worker."""

    def execute(self, context: WorkerAdapterContext) -> WorkerExecutionResult:
        """Run worker-specific behavior and return structured artifacts."""


class DeterministicWorkerAdapter:
    """Offline-safe worker implementation used when no live adapter is bound."""

    name = "deterministic_worker_adapter"

    def execute(self, context: WorkerAdapterContext) -> WorkerExecutionResult:
        """Produce role-aware artifacts and review metadata without side effects."""
        state = context.state
        expected = list(context.context.get("expected_artifacts", []))
        artifacts = {
            artifact: self._artifact_payload(context, artifact)
            for artifact in expected
        }
        review_required = self._requires_review(context)
        summary = self._summary(context, artifact_count=len(artifacts))
        next_actions = self._next_actions(context, review_required=review_required)
        return WorkerExecutionResult(
            node_id=state.node_id,
            worker_role=state.worker_role,
            summary=summary,
            artifacts=artifacts,
            context_used={
                "context_boundary": context.context["context_boundary"],
                "selected_tools": list(context.context["selected_tools"]),
                "skill_candidates": list(context.context["skill_candidates"]),
                "dependency_summaries": dict(context.context["dependency_summaries"]),
            },
            output_payload={
                "adapter": self.name,
                "specialist": context.routed["specialist"],
                "recommended_tools": list(context.routed.get("recommended_tools", [])),
                "permission_scope": list(context.routed.get("permission_scope", [])),
                "review_required": review_required,
                "next_actions": next_actions,
            },
            provenance={
                "run_id": context.run.run_id,
                "plan_id": context.run.plan_id,
                "node_id": state.node_id,
                "routed_by": context.routed.get("provenance", {}).get("routed_by"),
                "routing_reason": context.routed.get("provenance", {}).get("routing_reason"),
                "adapter": self.name,
            },
        )

    def _artifact_payload(
        self,
        context: WorkerAdapterContext,
        artifact_type: str,
    ) -> dict[str, Any]:
        """Build one reviewable artifact payload for a worker role."""
        role = context.state.worker_role
        goal = str(context.context.get("goal") or context.run.goal)
        base = {
            "artifact_type": artifact_type,
            "worker_role": role.value,
            "source_node_id": context.state.node_id,
            "goal": goal,
            "source": self.name,
        }
        role_payloads = {
            SpecialistRole.BUILD_ENGINEER: {
                "summary": "Drafted the agent change as a saveable configuration candidate.",
                "config_candidate": True,
                "review_required": True,
            },
            SpecialistRole.EVAL_AUTHOR: {
                "summary": "Prepared eval coverage and benchmark guidance for the active candidate.",
                "eval_ready": True,
                "suggests_generated_cases": True,
            },
            SpecialistRole.OPTIMIZATION_ENGINEER: {
                "summary": "Prepared reviewable optimization changes from eval evidence.",
                "change_card": True,
                "review_required": True,
            },
            SpecialistRole.SKILL_AUTHOR: {
                "summary": "Identified build-time skill candidates to attach after approval.",
                "skill_candidates": list(context.context.get("skill_candidates", [])),
                "review_required": True,
            },
            SpecialistRole.GUARDRAIL_AUTHOR: {
                "summary": "Drafted guardrail policy updates and safety cases.",
                "review_required": True,
            },
            SpecialistRole.DEPLOYMENT_ENGINEER: {
                "summary": "Prepared canary-first deployment and rollback evidence.",
                "deployment_gate": "approval_required",
                "review_required": True,
            },
            SpecialistRole.RELEASE_MANAGER: {
                "summary": "Packaged release-candidate evidence for promotion review.",
                "promotion_gate": "approval_required",
                "review_required": True,
            },
        }
        base.update(role_payloads.get(role, {
            "summary": f"{role.value} prepared {artifact_type} for review.",
            "review_required": False,
        }))
        return base

    def _requires_review(self, context: WorkerAdapterContext) -> bool:
        """Return whether this worker output should be applied only after review."""
        privileged = {"source_write", "deployment", "benchmark_spend", "secret_access"}
        scope = {str(item) for item in context.context.get("permission_scope", [])}
        review_roles = {
            SpecialistRole.BUILD_ENGINEER,
            SpecialistRole.TOOL_ENGINEER,
            SpecialistRole.SKILL_AUTHOR,
            SpecialistRole.GUARDRAIL_AUTHOR,
            SpecialistRole.OPTIMIZATION_ENGINEER,
            SpecialistRole.DEPLOYMENT_ENGINEER,
            SpecialistRole.RELEASE_MANAGER,
        }
        return bool(scope & privileged) or context.state.worker_role in review_roles

    def _summary(self, context: WorkerAdapterContext, *, artifact_count: int) -> str:
        """Create a concise role-aware worker summary."""
        role_name = context.routed.get("display_name") or context.state.worker_role.value
        noun = "artifact" if artifact_count == 1 else "artifacts"
        return f"{role_name} produced {artifact_count} reviewable {noun} for the coordinator."

    def _next_actions(
        self,
        context: WorkerAdapterContext,
        *,
        review_required: bool,
    ) -> list[str]:
        """Suggest the next operator action for a worker result."""
        role = context.state.worker_role
        if role == SpecialistRole.EVAL_AUTHOR:
            return ["Run /eval to execute the generated suite or inspect loss patterns."]
        if role == SpecialistRole.OPTIMIZATION_ENGINEER:
            return ["Use /review to inspect optimization cards before applying changes."]
        if role in {SpecialistRole.DEPLOYMENT_ENGINEER, SpecialistRole.RELEASE_MANAGER}:
            return ["Approve the canary gate before promoting deployment changes."]
        if review_required:
            return ["Review the proposed changes before saving or applying them."]
        return ["Continue with the next coordinator step."]


def normalize_worker_adapters(
    adapters: Mapping[SpecialistRole, WorkerAdapter] | None,
) -> dict[SpecialistRole, WorkerAdapter]:
    """Return a mutable role-to-adapter map with enum keys."""
    if not adapters:
        return {}
    return {SpecialistRole(role): adapter for role, adapter in adapters.items()}


__all__ = [
    "DeterministicWorkerAdapter",
    "WorkerAdapter",
    "WorkerAdapterContext",
    "normalize_worker_adapters",
]
