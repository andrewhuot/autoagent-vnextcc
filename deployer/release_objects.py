"""Immutable signed release objects with full lineage tracking.

Defines the canonical data structures for release artefacts: the
ReleaseObject that travels from DRAFT through SIGNED to DEPLOYED (or
ROLLED_BACK / SUPERSEDED), and the ReleaseLineage record that links a
requirement all the way to production traces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ReleaseStatus(str, Enum):
    """Lifecycle stages of a signed release object."""

    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    DEPLOYED = "DEPLOYED"
    ROLLED_BACK = "ROLLED_BACK"
    SUPERSEDED = "SUPERSEDED"


@dataclass
class ReleaseObject:
    """Immutable descriptor of a candidate release and all its provenance.

    Fields are intentionally broad so that different release types (code,
    config, prompt, model) can all be represented by the same structure.
    ``signature`` is set by :class:`~deployer.signing.ReleaseSigner` and
    should be treated as read-only once set.
    """

    release_id: str
    version: str
    status: ReleaseStatus
    code_diff: dict = field(default_factory=dict)
    config_diff: dict = field(default_factory=dict)
    prompt_diff: dict = field(default_factory=dict)
    dataset_version: str = ""
    eval_results: dict = field(default_factory=dict)
    grader_versions: dict[str, str] = field(default_factory=dict)
    judge_versions: dict[str, str] = field(default_factory=dict)
    skill_versions: dict[str, str] = field(default_factory=dict)
    model_version: str = ""
    risk_class: str = ""
    approval_chain: list[dict] = field(default_factory=list)
    canary_plan: dict = field(default_factory=dict)
    rollback_instructions: str = ""
    business_outcomes: dict = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    signed_at: str | None = None
    signature: str | None = None
    metadata: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe plain dict."""
        return {
            "release_id": self.release_id,
            "version": self.version,
            "status": self.status.value,
            "code_diff": self.code_diff,
            "config_diff": self.config_diff,
            "prompt_diff": self.prompt_diff,
            "dataset_version": self.dataset_version,
            "eval_results": self.eval_results,
            "grader_versions": self.grader_versions,
            "judge_versions": self.judge_versions,
            "skill_versions": self.skill_versions,
            "model_version": self.model_version,
            "risk_class": self.risk_class,
            "approval_chain": self.approval_chain,
            "canary_plan": self.canary_plan,
            "rollback_instructions": self.rollback_instructions,
            "business_outcomes": self.business_outcomes,
            "created_at": self.created_at,
            "signed_at": self.signed_at,
            "signature": self.signature,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReleaseObject:
        """Deserialise from a plain dict (e.g. loaded from JSON/SQLite)."""
        return cls(
            release_id=data["release_id"],
            version=data["version"],
            status=ReleaseStatus(data["status"]),
            code_diff=data.get("code_diff", {}),
            config_diff=data.get("config_diff", {}),
            prompt_diff=data.get("prompt_diff", {}),
            dataset_version=data.get("dataset_version", ""),
            eval_results=data.get("eval_results", {}),
            grader_versions=data.get("grader_versions", {}),
            judge_versions=data.get("judge_versions", {}),
            skill_versions=data.get("skill_versions", {}),
            model_version=data.get("model_version", ""),
            risk_class=data.get("risk_class", ""),
            approval_chain=data.get("approval_chain", []),
            canary_plan=data.get("canary_plan", {}),
            rollback_instructions=data.get("rollback_instructions", ""),
            business_outcomes=data.get("business_outcomes", {}),
            created_at=data.get("created_at", ""),
            signed_at=data.get("signed_at"),
            signature=data.get("signature"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ReleaseLineage:
    """End-to-end lineage record tying a requirement to production traces.

    One ``ReleaseLineage`` is created per deployment and links together
    the original business requirement, the builder skill that implemented
    the change, the eval results that justified it, and the production
    trace and outcome IDs that prove it delivered value.
    """

    lineage_id: str
    requirement_description: str
    builder_skill_used: str
    code_change_summary: str
    eval_results_summary: dict = field(default_factory=dict)
    deployment_id: str = ""
    production_trace_ids: list[str] = field(default_factory=list)
    business_outcome_ids: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe plain dict."""
        return {
            "lineage_id": self.lineage_id,
            "requirement_description": self.requirement_description,
            "builder_skill_used": self.builder_skill_used,
            "code_change_summary": self.code_change_summary,
            "eval_results_summary": self.eval_results_summary,
            "deployment_id": self.deployment_id,
            "production_trace_ids": self.production_trace_ids,
            "business_outcome_ids": self.business_outcome_ids,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReleaseLineage:
        """Deserialise from a plain dict."""
        return cls(
            lineage_id=data["lineage_id"],
            requirement_description=data["requirement_description"],
            builder_skill_used=data["builder_skill_used"],
            code_change_summary=data["code_change_summary"],
            eval_results_summary=data.get("eval_results_summary", {}),
            deployment_id=data.get("deployment_id", ""),
            production_trace_ids=data.get("production_trace_ids", []),
            business_outcome_ids=data.get("business_outcome_ids", []),
        )
