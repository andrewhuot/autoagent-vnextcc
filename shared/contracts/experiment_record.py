"""Shared experiment record contract."""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any


@dataclass(slots=True)
class ExperimentRecord:
    """Describe one optimization experiment and its outcome."""

    experiment_id: str
    created_at: float
    hypothesis: str
    touched_surfaces: list[str] = field(default_factory=list)
    touched_agents: list[str] = field(default_factory=list)
    diff_summary: str = ""
    eval_set_versions: dict[str, str] = field(default_factory=dict)
    replay_set_hash: str = ""
    baseline_sha: str = ""
    candidate_sha: str = ""
    risk_class: str = ""
    deployment_policy: str = "pr_only"
    rollback_handle: str = ""
    total_experiment_cost: float = 0.0
    status: str = "pending"
    result_summary: str = ""
    operator_name: str = ""
    baseline_scores: dict[str, float] = field(default_factory=dict)
    candidate_scores: dict[str, float] = field(default_factory=dict)
    significance_p_value: float = 1.0
    significance_delta: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation for storage and API responses."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperimentRecord:
        """Rehydrate an experiment record from persisted data."""
        return cls(
            experiment_id=data["experiment_id"],
            created_at=float(data["created_at"]),
            hypothesis=data["hypothesis"],
            touched_surfaces=list(data.get("touched_surfaces", [])),
            touched_agents=list(data.get("touched_agents", [])),
            diff_summary=data.get("diff_summary", ""),
            eval_set_versions=dict(data.get("eval_set_versions", {})),
            replay_set_hash=data.get("replay_set_hash", ""),
            baseline_sha=data.get("baseline_sha", ""),
            candidate_sha=data.get("candidate_sha", ""),
            risk_class=data.get("risk_class", ""),
            deployment_policy=data.get("deployment_policy", "pr_only"),
            rollback_handle=data.get("rollback_handle", ""),
            total_experiment_cost=float(data.get("total_experiment_cost", 0.0)),
            status=data.get("status", "pending"),
            result_summary=data.get("result_summary", ""),
            operator_name=data.get("operator_name", ""),
            baseline_scores=dict(data.get("baseline_scores", {})),
            candidate_scores=dict(data.get("candidate_scores", {})),
            significance_p_value=float(data.get("significance_p_value", 1.0)),
            significance_delta=float(data.get("significance_delta", 0.0)),
        )
