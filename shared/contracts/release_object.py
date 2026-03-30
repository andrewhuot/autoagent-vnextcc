"""Shared release object contract."""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any


@dataclass(slots=True)
class ReleaseObject:
    """Describe a signed release candidate with provenance and rollout data."""

    release_id: str
    version: str
    status: str
    code_diff: dict[str, Any] = field(default_factory=dict)
    config_diff: dict[str, Any] = field(default_factory=dict)
    prompt_diff: dict[str, Any] = field(default_factory=dict)
    dataset_version: str = ""
    eval_results: dict[str, Any] = field(default_factory=dict)
    grader_versions: dict[str, str] = field(default_factory=dict)
    judge_versions: dict[str, str] = field(default_factory=dict)
    skill_versions: dict[str, str] = field(default_factory=dict)
    model_version: str = ""
    risk_class: str = ""
    approval_chain: list[dict[str, Any]] = field(default_factory=list)
    canary_plan: dict[str, Any] = field(default_factory=dict)
    rollback_instructions: str = ""
    business_outcomes: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    signed_at: str | None = None
    signature: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation for persistence and transport."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReleaseObject:
        """Rehydrate a release object from persisted data."""
        return cls(
            release_id=data["release_id"],
            version=data["version"],
            status=data["status"],
            code_diff=dict(data.get("code_diff", {})),
            config_diff=dict(data.get("config_diff", {})),
            prompt_diff=dict(data.get("prompt_diff", {})),
            dataset_version=data.get("dataset_version", ""),
            eval_results=dict(data.get("eval_results", {})),
            grader_versions=dict(data.get("grader_versions", {})),
            judge_versions=dict(data.get("judge_versions", {})),
            skill_versions=dict(data.get("skill_versions", {})),
            model_version=data.get("model_version", ""),
            risk_class=data.get("risk_class", ""),
            approval_chain=list(data.get("approval_chain", [])),
            canary_plan=dict(data.get("canary_plan", {})),
            rollback_instructions=data.get("rollback_instructions", ""),
            business_outcomes=dict(data.get("business_outcomes", {})),
            created_at=data.get("created_at", ""),
            signed_at=data.get("signed_at"),
            signature=data.get("signature"),
            metadata=dict(data.get("metadata", {})),
        )
