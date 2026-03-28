"""RLDS-inspired episode types for offline RL dataset storage."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# EpisodeStep
# ---------------------------------------------------------------------------

@dataclass
class EpisodeStep:
    """A single step in an RL episode (observation, action, reward, etc.)."""

    step_id: str = field(default_factory=_new_uuid)
    step_index: int = 0
    observation: dict[str, Any] = field(default_factory=dict)  # state observed by agent
    action: dict[str, Any] = field(default_factory=dict)       # action taken (tool call, route, etc.)
    action_type: str = ""  # tool_call, routing_decision, handoff, escalation, model_call
    reward_vector: dict[str, float] = field(default_factory=dict)  # reward_id -> value
    discount: float = 1.0
    terminal: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "step_index": self.step_index,
            "observation": self.observation,
            "action": self.action,
            "action_type": self.action_type,
            "reward_vector": self.reward_vector,
            "discount": self.discount,
            "terminal": self.terminal,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EpisodeStep":
        return cls(
            step_id=d.get("step_id", _new_uuid()),
            step_index=int(d.get("step_index", 0)),
            observation=d.get("observation", {}),
            action=d.get("action", {}),
            action_type=d.get("action_type", ""),
            reward_vector=d.get("reward_vector", {}),
            discount=float(d.get("discount", 1.0)),
            terminal=bool(d.get("terminal", False)),
            metadata=d.get("metadata", {}),
            timestamp=d.get("timestamp", _now_iso()),
        )


# ---------------------------------------------------------------------------
# Episode
# ---------------------------------------------------------------------------

@dataclass
class Episode:
    """A complete episode joining trace, eval, rewards, and outcomes."""

    episode_id: str = field(default_factory=_new_uuid)
    trace_id: str = ""
    eval_run_id: str = ""
    experiment_id: str = ""
    agent_version: str = ""
    adk_project: str = ""
    steps: list[EpisodeStep] = field(default_factory=list)
    total_reward: dict[str, float] = field(default_factory=dict)  # aggregated reward vector
    hard_gates_passed: bool = True
    environment_results: dict[str, Any] = field(default_factory=dict)
    business_outcomes: list[dict[str, Any]] = field(default_factory=list)
    preference_labels: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "trace_id": self.trace_id,
            "eval_run_id": self.eval_run_id,
            "experiment_id": self.experiment_id,
            "agent_version": self.agent_version,
            "adk_project": self.adk_project,
            "steps": [step.to_dict() for step in self.steps],
            "total_reward": self.total_reward,
            "hard_gates_passed": self.hard_gates_passed,
            "environment_results": self.environment_results,
            "business_outcomes": self.business_outcomes,
            "preference_labels": self.preference_labels,
            "tool_calls": self.tool_calls,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Episode":
        return cls(
            episode_id=d.get("episode_id", _new_uuid()),
            trace_id=d.get("trace_id", ""),
            eval_run_id=d.get("eval_run_id", ""),
            experiment_id=d.get("experiment_id", ""),
            agent_version=d.get("agent_version", ""),
            adk_project=d.get("adk_project", ""),
            steps=[EpisodeStep.from_dict(s) for s in d.get("steps", [])],
            total_reward=d.get("total_reward", {}),
            hard_gates_passed=bool(d.get("hard_gates_passed", True)),
            environment_results=d.get("environment_results", {}),
            business_outcomes=d.get("business_outcomes", []),
            preference_labels=d.get("preference_labels", []),
            tool_calls=d.get("tool_calls", []),
            created_at=d.get("created_at", _now_iso()),
            metadata=d.get("metadata", {}),
        )
