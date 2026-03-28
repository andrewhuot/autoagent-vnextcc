"""Dataset domain types for the first-class dataset service."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


@dataclass
class DatasetRow:
    """A single labelled example in a dataset.

    Carries the full set of annotations needed for eval, fine-tuning, and
    safety analysis: trajectory expectations, tool constraints, safety labels,
    slice tags, cost/latency budgets, and business outcome labels.
    """

    input: str
    expected_response: str
    trajectory_expectations: list[dict[str, Any]] = field(default_factory=list)
    tool_constraints: dict[str, Any] = field(
        default_factory=lambda: {"must_call": [], "must_not_call": []}
    )
    safety_labels: list[str] = field(default_factory=list)
    slice_tags: dict[str, str] = field(default_factory=dict)
    cost_budget: Optional[float] = None
    latency_budget_ms: Optional[float] = None
    business_outcome_labels: dict[str, Any] = field(default_factory=dict)
    category: str = "general"
    split: str = "tuning"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input": self.input,
            "expected_response": self.expected_response,
            "trajectory_expectations": self.trajectory_expectations,
            "tool_constraints": self.tool_constraints,
            "safety_labels": self.safety_labels,
            "slice_tags": self.slice_tags,
            "cost_budget": self.cost_budget,
            "latency_budget_ms": self.latency_budget_ms,
            "business_outcome_labels": self.business_outcome_labels,
            "category": self.category,
            "split": self.split,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DatasetRow":
        return cls(
            input=d["input"],
            expected_response=d.get("expected_response", ""),
            trajectory_expectations=d.get("trajectory_expectations", []),
            tool_constraints=d.get(
                "tool_constraints", {"must_call": [], "must_not_call": []}
            ),
            safety_labels=d.get("safety_labels", []),
            slice_tags=d.get("slice_tags", {}),
            cost_budget=d.get("cost_budget"),
            latency_budget_ms=d.get("latency_budget_ms"),
            business_outcome_labels=d.get("business_outcome_labels", {}),
            category=d.get("category", "general"),
            split=d.get("split", "tuning"),
            metadata=d.get("metadata", {}),
        )


@dataclass
class DatasetVersion:
    """An immutable snapshot of a dataset at a point in time."""

    version_id: str = field(default_factory=_new_id)
    dataset_id: str = ""
    created_at: str = field(default_factory=_now_iso)
    row_count: int = 0
    content_hash: str = ""
    parent_version_id: Optional[str] = None
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "dataset_id": self.dataset_id,
            "created_at": self.created_at,
            "row_count": self.row_count,
            "content_hash": self.content_hash,
            "parent_version_id": self.parent_version_id,
            "description": self.description,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DatasetVersion":
        return cls(
            version_id=d["version_id"],
            dataset_id=d.get("dataset_id", ""),
            created_at=d.get("created_at", ""),
            row_count=d.get("row_count", 0),
            content_hash=d.get("content_hash", ""),
            parent_version_id=d.get("parent_version_id"),
            description=d.get("description", ""),
            metadata=d.get("metadata", {}),
        )


@dataclass
class DatasetSplit:
    """A named partition of a dataset (train / tuning / eval / test)."""

    split_name: str
    row_ids: list[str] = field(default_factory=list)
    percentage: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "split_name": self.split_name,
            "row_ids": self.row_ids,
            "percentage": self.percentage,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DatasetSplit":
        return cls(
            split_name=d["split_name"],
            row_ids=d.get("row_ids", []),
            percentage=d.get("percentage", 0.0),
        )


@dataclass
class DatasetQualityMetrics:
    """Computed quality signals for a dataset."""

    coverage: float = 0.0
    staleness_days: float = 0.0
    balance: dict[str, float] = field(default_factory=dict)
    total_rows: int = 0
    failure_mode_distribution: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "coverage": self.coverage,
            "staleness_days": self.staleness_days,
            "balance": self.balance,
            "total_rows": self.total_rows,
            "failure_mode_distribution": self.failure_mode_distribution,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DatasetQualityMetrics":
        return cls(
            coverage=d.get("coverage", 0.0),
            staleness_days=d.get("staleness_days", 0.0),
            balance=d.get("balance", {}),
            total_rows=d.get("total_rows", 0),
            failure_mode_distribution=d.get("failure_mode_distribution", {}),
        )


@dataclass
class DatasetInfo:
    """Summary view of a dataset with quality metrics and version list."""

    dataset_id: str
    name: str
    description: str = ""
    current_version: str = ""
    created_at: str = field(default_factory=_now_iso)
    versions: list[str] = field(default_factory=list)
    splits: list[str] = field(default_factory=list)
    quality_metrics: Optional[DatasetQualityMetrics] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "name": self.name,
            "description": self.description,
            "current_version": self.current_version,
            "created_at": self.created_at,
            "versions": self.versions,
            "splits": self.splits,
            "quality_metrics": (
                self.quality_metrics.to_dict() if self.quality_metrics else None
            ),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DatasetInfo":
        qm = d.get("quality_metrics")
        return cls(
            dataset_id=d["dataset_id"],
            name=d["name"],
            description=d.get("description", ""),
            current_version=d.get("current_version", ""),
            created_at=d.get("created_at", ""),
            versions=d.get("versions", []),
            splits=d.get("splits", []),
            quality_metrics=DatasetQualityMetrics.from_dict(qm) if qm else None,
        )
