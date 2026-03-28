"""Domain types for the reward registry and reward signals."""

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

class RewardKind(str, Enum):
    """Kind of reward signal."""

    verifiable = "verifiable"
    preference = "preference"
    business_outcome = "business_outcome"
    constitutional = "constitutional"


class RewardScope(str, Enum):
    """Where the reward applies."""

    runtime = "runtime"
    buildtime = "buildtime"
    multi_agent = "multi_agent"


class RewardGranularity(str, Enum):
    """Granularity of reward measurement."""

    step = "step"
    trajectory = "trajectory"
    episode = "episode"
    delayed_outcome = "delayed_outcome"


class RewardSource(str, Enum):
    """Source of reward signal."""

    deterministic_checker = "deterministic_checker"
    environment_checker = "environment_checker"
    human_label = "human_label"
    llm_judge = "llm_judge"
    ai_preference = "ai_preference"


class TrustTier(int, Enum):
    """Trust ranking for reward sources (1 = highest trust)."""

    tier_1 = 1  # deterministic checker
    tier_2 = 2  # environment checker
    tier_3 = 3  # audited human label
    tier_4 = 4  # calibrated LLM judge
    tier_5 = 5  # AI preference / constitutional label


# ---------------------------------------------------------------------------
# RewardDefinition
# ---------------------------------------------------------------------------

@dataclass
class RewardDefinition:
    """A single reward definition in the registry."""

    reward_id: str = field(default_factory=_new_uuid)
    name: str = ""
    kind: RewardKind = RewardKind.verifiable
    scope: RewardScope = RewardScope.runtime
    granularity: RewardGranularity = RewardGranularity.step
    source: RewardSource = RewardSource.deterministic_checker
    trust_tier: TrustTier = TrustTier.tier_1
    weight: float = 1.0
    hard_gate: bool = False
    slices: list[str] = field(default_factory=list)
    freshness_window_hours: float = 0.0
    calibration_metadata: dict[str, Any] = field(default_factory=dict)
    anti_hack_tests: list[str] = field(default_factory=list)
    checker_fn: str = ""
    description: str = ""
    created_at: str = field(default_factory=_now_iso)
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "reward_id": self.reward_id,
            "name": self.name,
            "kind": self.kind.value,
            "scope": self.scope.value,
            "granularity": self.granularity.value,
            "source": self.source.value,
            "trust_tier": self.trust_tier.value,
            "weight": self.weight,
            "hard_gate": self.hard_gate,
            "slices": list(self.slices),
            "freshness_window_hours": self.freshness_window_hours,
            "calibration_metadata": self.calibration_metadata,
            "anti_hack_tests": list(self.anti_hack_tests),
            "checker_fn": self.checker_fn,
            "description": self.description,
            "created_at": self.created_at,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RewardDefinition":
        return cls(
            reward_id=d.get("reward_id", _new_uuid()),
            name=d.get("name", ""),
            kind=RewardKind(d.get("kind", RewardKind.verifiable.value)),
            scope=RewardScope(d.get("scope", RewardScope.runtime.value)),
            granularity=RewardGranularity(
                d.get("granularity", RewardGranularity.step.value)
            ),
            source=RewardSource(
                d.get("source", RewardSource.deterministic_checker.value)
            ),
            trust_tier=TrustTier(d.get("trust_tier", TrustTier.tier_1.value)),
            weight=float(d.get("weight", 1.0)),
            hard_gate=bool(d.get("hard_gate", False)),
            slices=list(d.get("slices", [])),
            freshness_window_hours=float(d.get("freshness_window_hours", 0.0)),
            calibration_metadata=d.get("calibration_metadata", {}),
            anti_hack_tests=list(d.get("anti_hack_tests", [])),
            checker_fn=d.get("checker_fn", ""),
            description=d.get("description", ""),
            created_at=d.get("created_at", _now_iso()),
            version=int(d.get("version", 1)),
        )


# ---------------------------------------------------------------------------
# RewardVector
# ---------------------------------------------------------------------------

@dataclass
class RewardVector:
    """Multi-dimensional reward signal. Scalarize only at training time."""

    episode_id: str = ""
    rewards: dict[str, float] = field(default_factory=dict)
    hard_gate_results: dict[str, bool] = field(default_factory=dict)
    timestamp: str = field(default_factory=_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def all_hard_gates_passed(self) -> bool:
        """Return True only when every hard-gate result is True."""
        return all(self.hard_gate_results.values()) if self.hard_gate_results else True

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "rewards": dict(self.rewards),
            "hard_gate_results": dict(self.hard_gate_results),
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RewardVector":
        return cls(
            episode_id=d.get("episode_id", ""),
            rewards={k: float(v) for k, v in d.get("rewards", {}).items()},
            hard_gate_results={
                k: bool(v) for k, v in d.get("hard_gate_results", {}).items()
            },
            timestamp=d.get("timestamp", _now_iso()),
            metadata=d.get("metadata", {}),
        )
