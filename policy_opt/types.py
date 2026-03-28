"""Domain types for policy optimization artifacts and training jobs."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PolicyType(str, Enum):
    """Types of learned policies."""

    mutation_policy = "mutation_policy"
    routing_policy = "routing_policy"
    tool_policy = "tool_policy"
    handoff_policy = "handoff_policy"
    reasoning_budget_policy = "reasoning_budget_policy"
    preference_tuned_model = "preference_tuned_model"
    verifier_tuned_model = "verifier_tuned_model"


class TrainingMode(str, Enum):
    """Training algorithm modes."""

    control = "control"        # contextual bandits for optimizer decisions
    verifier = "verifier"      # RLVR for verifiable subtasks
    preference = "preference"  # DPO/preference optimization


class TrainingStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class TrainerBackend(str, Enum):
    openai_rft = "openai_rft"
    openai_dpo = "openai_dpo"
    vertex_sft = "vertex_sft"
    vertex_preference = "vertex_preference"
    vertex_continuous = "vertex_continuous"


# ---------------------------------------------------------------------------
# PolicyArtifact
# ---------------------------------------------------------------------------

@dataclass
class PolicyArtifact:
    """A versioned learned policy artifact."""

    policy_id: str = field(default_factory=_new_uuid)
    name: str = ""
    policy_type: PolicyType = PolicyType.mutation_policy
    training_mode: TrainingMode = TrainingMode.control
    training_dataset_version: str = ""
    reward_spec_version: str = ""
    trainer_backend: str = ""
    eval_report: dict[str, Any] = field(default_factory=dict)
    ope_report: dict[str, Any] = field(default_factory=dict)
    canary_report: dict[str, Any] = field(default_factory=dict)
    rollback_target: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now_iso)
    status: str = "candidate"  # candidate, canary, promoted, rolled_back
    version: int = 1
    model_reference: str = ""  # tuned model ID if applicable
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "name": self.name,
            "policy_type": self.policy_type.value,
            "training_mode": self.training_mode.value,
            "training_dataset_version": self.training_dataset_version,
            "reward_spec_version": self.reward_spec_version,
            "trainer_backend": self.trainer_backend,
            "eval_report": self.eval_report,
            "ope_report": self.ope_report,
            "canary_report": self.canary_report,
            "rollback_target": self.rollback_target,
            "provenance": self.provenance,
            "created_at": self.created_at,
            "status": self.status,
            "version": self.version,
            "model_reference": self.model_reference,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PolicyArtifact":
        return cls(
            policy_id=d.get("policy_id", _new_uuid()),
            name=d.get("name", ""),
            policy_type=PolicyType(d.get("policy_type", PolicyType.mutation_policy.value)),
            training_mode=TrainingMode(d.get("training_mode", TrainingMode.control.value)),
            training_dataset_version=d.get("training_dataset_version", ""),
            reward_spec_version=d.get("reward_spec_version", ""),
            trainer_backend=d.get("trainer_backend", ""),
            eval_report=d.get("eval_report", {}),
            ope_report=d.get("ope_report", {}),
            canary_report=d.get("canary_report", {}),
            rollback_target=d.get("rollback_target", ""),
            provenance=d.get("provenance", {}),
            created_at=d.get("created_at", _now_iso()),
            status=d.get("status", "candidate"),
            version=int(d.get("version", 1)),
            model_reference=d.get("model_reference", ""),
            metadata=d.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# TrainingJob
# ---------------------------------------------------------------------------

@dataclass
class TrainingJob:
    """Record of a training job execution."""

    job_id: str = field(default_factory=_new_uuid)
    mode: TrainingMode = TrainingMode.control
    backend: str = ""
    dataset_path: str = ""
    reward_spec: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    status: TrainingStatus = TrainingStatus.pending
    result: dict[str, Any] = field(default_factory=dict)
    policy_id: str = ""  # resulting policy artifact ID
    created_at: str = field(default_factory=_now_iso)
    completed_at: str = ""
    error_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "mode": self.mode.value,
            "backend": self.backend,
            "dataset_path": self.dataset_path,
            "reward_spec": self.reward_spec,
            "config": self.config,
            "status": self.status.value,
            "result": self.result,
            "policy_id": self.policy_id,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TrainingJob":
        return cls(
            job_id=d.get("job_id", _new_uuid()),
            mode=TrainingMode(d.get("mode", TrainingMode.control.value)),
            backend=d.get("backend", ""),
            dataset_path=d.get("dataset_path", ""),
            reward_spec=d.get("reward_spec", {}),
            config=d.get("config", {}),
            status=TrainingStatus(d.get("status", TrainingStatus.pending.value)),
            result=d.get("result", {}),
            policy_id=d.get("policy_id", ""),
            created_at=d.get("created_at", _now_iso()),
            completed_at=d.get("completed_at", ""),
            error_message=d.get("error_message", ""),
            metadata=d.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# OPEReport
# ---------------------------------------------------------------------------

@dataclass
class OPEReport:
    """Off-policy evaluation report for a candidate policy."""

    policy_id: str = ""
    baseline_replay_score: float = 0.0
    candidate_estimated_uplift: float = 0.0
    uncertainty_lower: float = 0.0
    uncertainty_upper: float = 0.0
    support_coverage: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "baseline_replay_score": self.baseline_replay_score,
            "candidate_estimated_uplift": self.candidate_estimated_uplift,
            "uncertainty_lower": self.uncertainty_lower,
            "uncertainty_upper": self.uncertainty_upper,
            "support_coverage": self.support_coverage,
            "diagnostics": self.diagnostics,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "OPEReport":
        return cls(
            policy_id=d.get("policy_id", ""),
            baseline_replay_score=float(d.get("baseline_replay_score", 0.0)),
            candidate_estimated_uplift=float(d.get("candidate_estimated_uplift", 0.0)),
            uncertainty_lower=float(d.get("uncertainty_lower", 0.0)),
            uncertainty_upper=float(d.get("uncertainty_upper", 0.0)),
            support_coverage=float(d.get("support_coverage", 0.0)),
            diagnostics=d.get("diagnostics", {}),
            created_at=d.get("created_at", _now_iso()),
        )
