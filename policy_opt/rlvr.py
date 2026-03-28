"""Runtime RLVR — verifiable reward training for runtime decisions.

Mode B from the spec. Trains runtime policies or tuned models for:
- Routing decisions (given user message + state, choose route)
- Tool selection (given tool menu, choose correct tool)
- Tool argument correctness (generate args that pass schema + checker)
- Task completion detection (decide if task is done)
- Latency/cost budget decisions

Uses deterministic checkers and environment checkers as primary reward.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

from data.episode_types import Episode, EpisodeStep
from policy_opt.types import PolicyArtifact, PolicyType, TrainingMode


class RuntimeRLVR:
    """Build datasets and train runtime policies for verifiable subtasks."""

    def __init__(self, output_dir: str = ".autoagent") -> None:
        self._output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def build_routing_dataset(self, episodes: list[Episode]) -> str:
        """Build training dataset for routing decisions.

        Each record: {input: user_message + state, action: route_chosen,
                       reward: 1.0 if correct route, 0.0 otherwise}
        Filters to steps with action_type="routing_decision".
        Returns output JSONL path.
        """
        records = []
        for ep in episodes:
            for step in ep.steps:
                if step.action_type == "routing_decision":
                    reward = step.reward_vector.get("routing_accuracy", 0.0)
                    if not reward and ep.total_reward:
                        reward = ep.total_reward.get("routing_accuracy", 0.0)
                    records.append(
                        {
                            "input": step.observation,
                            "action": step.action.get(
                                "route", step.action.get("selected", "")
                            ),
                            "reward": reward,
                            "correct": reward > 0.5,
                            "episode_id": ep.episode_id,
                            "step_id": step.step_id,
                        }
                    )
        return self._write_jsonl(
            records, f"routing_train_{uuid.uuid4().hex[:8]}.jsonl"
        )

    def build_tool_choice_dataset(self, episodes: list[Episode]) -> str:
        """Build training dataset for tool selection decisions.

        Each record: {input: context + available_tools, action: tool_chosen,
                       reward: 1.0 if correct tool, 0.0 otherwise}
        """
        records = []
        for ep in episodes:
            for step in ep.steps:
                if step.action_type == "tool_call":
                    reward = step.reward_vector.get("tool_selection", 0.0)
                    if not reward and ep.total_reward:
                        reward = ep.total_reward.get("tool_correctness", 0.0)
                    records.append(
                        {
                            "input": step.observation,
                            "action": step.action.get(
                                "tool_name", step.action.get("selected", "")
                            ),
                            "arguments": step.action.get("arguments", {}),
                            "reward": reward,
                            "correct": reward > 0.5,
                            "episode_id": ep.episode_id,
                            "step_id": step.step_id,
                        }
                    )
        return self._write_jsonl(
            records, f"tool_choice_train_{uuid.uuid4().hex[:8]}.jsonl"
        )

    def build_escalation_dataset(self, episodes: list[Episode]) -> str:
        """Build training dataset for escalation/handoff decisions.

        Each record: {input: state + context, action: escalate/continue,
                       reward: based on outcome of decision}
        """
        records = []
        for ep in episodes:
            for step in ep.steps:
                if step.action_type in ("escalation", "handoff"):
                    reward = step.reward_vector.get("handoff_quality", 0.0)
                    if not reward and ep.total_reward:
                        reward = ep.total_reward.get("handoff_fidelity", 0.0)
                    records.append(
                        {
                            "input": step.observation,
                            "action": step.action.get("decision", "escalate"),
                            "target": step.action.get("target", ""),
                            "reward": reward,
                            "correct": reward > 0.5,
                            "episode_id": ep.episode_id,
                            "step_id": step.step_id,
                        }
                    )
        return self._write_jsonl(
            records, f"escalation_train_{uuid.uuid4().hex[:8]}.jsonl"
        )

    def build_combined_dataset(self, episodes: list[Episode]) -> dict[str, str]:
        """Build all three datasets at once. Returns {name: path} dict."""
        return {
            "routing": self.build_routing_dataset(episodes),
            "tool_choice": self.build_tool_choice_dataset(episodes),
            "escalation": self.build_escalation_dataset(episodes),
        }

    def apply_routing_policy(
        self, policy: PolicyArtifact, context: dict[str, Any]
    ) -> str:
        """Apply a learned routing policy to make a routing decision.

        Returns the recommended route.
        V1: Uses policy metadata with simple scoring.
        """
        stats = policy.metadata.get(
            "arm_stats", policy.metadata.get("routing_stats", {})
        )
        if not stats:
            return ""
        # Find best route for context
        best_route = ""
        best_score = -1.0
        for route, route_stats in stats.items():
            score = route_stats.get("mean_reward", 0.0)
            if score > best_score:
                best_score = score
                best_route = route
        return best_route

    def apply_tool_policy(
        self, policy: PolicyArtifact, context: dict[str, Any]
    ) -> str:
        """Apply a learned tool selection policy.

        Returns the recommended tool name.
        """
        stats = policy.metadata.get("tool_stats", {})
        if not stats:
            return ""
        best_tool = ""
        best_score = -1.0
        for tool, tool_stats in stats.items():
            score = tool_stats.get("mean_reward", 0.0)
            if score > best_score:
                best_score = score
                best_tool = tool
        return best_tool

    def apply_escalation_policy(
        self, policy: PolicyArtifact, context: dict[str, Any]
    ) -> bool:
        """Apply a learned escalation policy. Returns True if should escalate."""
        stats = policy.metadata.get("escalation_stats", {})
        escalate_reward = stats.get("escalate", {}).get("mean_reward", 0.0)
        continue_reward = stats.get("continue", {}).get("mean_reward", 0.0)
        return escalate_reward > continue_reward

    def _write_jsonl(self, records: list[dict], filename: str) -> str:
        path = os.path.join(self._output_dir, filename)
        with open(path, "w") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")
        return path
