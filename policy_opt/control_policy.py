"""Control-policy learning — contextual bandits for optimizer decisions.

Learns policies for discrete choices:
- Which mutation operator to try
- Which buildtime skill to invoke
- Which model to use for diagnose vs propose vs judge
- Which benchmark slice to expand next
- Which sub-agent to route to
- Whether to escalate or retry

Uses contextual bandits (Thompson sampling) on logged outcomes.
This is Mode A from the spec — the safest form of RL for AutoAgent.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field
from typing import Any

from data.episode_types import Episode
from policy_opt.types import PolicyArtifact, PolicyType, TrainingMode


@dataclass
class ContextualArmStats:
    """Statistics for a context-action pair."""

    action: str = ""
    context_key: str = ""  # e.g. "failure_family:routing"
    attempts: int = 0
    successes: int = 0
    total_reward: float = 0.0
    mean_reward: float = 0.0

    def update(self, reward: float, success: bool) -> None:
        self.attempts += 1
        if success:
            self.successes += 1
        self.total_reward += reward
        self.mean_reward = self.total_reward / max(self.attempts, 1)


class ControlPolicyLearner:
    """Learn policies for discrete optimizer decisions from logged outcomes.

    Supports learning:
    - mutation_policy: which mutation operator to select given failure context
    - model_selection: which model to use for each optimizer phase
    - skill_selection: which buildtime skill to apply
    - slice_expansion: which benchmark slice to expand
    """

    def __init__(self) -> None:
        self._arm_stats: dict[str, dict[str, ContextualArmStats]] = {}
        # key: context_key -> {action -> stats}

    def build_training_data(self, episodes: list[Episode]) -> list[dict[str, Any]]:
        """Convert episodes into (context, action, reward) tuples for training.

        Extracts from episode metadata and step actions:
        - Context features: failure_family, agent_version, complexity, etc.
        - Actions: operator chosen, model used, skill applied
        - Rewards: episode total_reward, hard_gates_passed
        """
        training_data = []
        for ep in episodes:
            context = self._extract_context(ep)
            for step in ep.steps:
                if step.action_type in (
                    "mutation_selection",
                    "model_selection",
                    "skill_selection",
                    "routing_decision",
                ):
                    action = step.action.get(
                        "selected", step.action.get("action", "")
                    )
                    reward = (
                        sum(step.reward_vector.values())
                        / max(len(step.reward_vector), 1)
                        if step.reward_vector
                        else 0.0
                    )
                    if not reward and ep.total_reward:
                        reward = sum(ep.total_reward.values()) / max(
                            len(ep.total_reward), 1
                        )
                    training_data.append(
                        {
                            "context": context,
                            "action": action,
                            "action_type": step.action_type,
                            "reward": reward,
                            "success": ep.hard_gates_passed and reward > 0,
                            "episode_id": ep.episode_id,
                        }
                    )
        return training_data

    def train(self, training_data: list[dict[str, Any]]) -> PolicyArtifact:
        """Train a control policy from (context, action, reward) tuples.

        Uses Thompson sampling with learned priors from the data.
        """
        self._arm_stats.clear()

        for record in training_data:
            ctx_key = self._context_to_key(record["context"])
            action = record["action"]
            reward = record["reward"]
            success = record["success"]

            if ctx_key not in self._arm_stats:
                self._arm_stats[ctx_key] = {}
            if action not in self._arm_stats[ctx_key]:
                self._arm_stats[ctx_key][action] = ContextualArmStats(
                    action=action, context_key=ctx_key
                )
            self._arm_stats[ctx_key][action].update(reward, success)

        # Build policy artifact with learned stats
        policy_data: dict[str, Any] = {}
        for ctx_key, actions in self._arm_stats.items():
            policy_data[ctx_key] = {
                action: {
                    "attempts": stats.attempts,
                    "successes": stats.successes,
                    "mean_reward": stats.mean_reward,
                }
                for action, stats in actions.items()
            }

        artifact = PolicyArtifact(
            name="control_policy_bandits",
            policy_type=PolicyType.mutation_policy,
            training_mode=TrainingMode.control,
            provenance={
                "algorithm": "thompson_sampling",
                "n_records": len(training_data),
            },
            metadata={"arm_stats": policy_data},
        )
        return artifact

    def predict(self, policy: PolicyArtifact, context: dict[str, Any]) -> str:
        """Select best action for given context using learned policy.

        Uses Thompson sampling from posterior.
        """
        scores = self.get_action_scores(policy, context)
        if not scores:
            return ""
        return max(scores, key=scores.__getitem__)

    def get_action_scores(
        self, policy: PolicyArtifact, context: dict[str, Any]
    ) -> dict[str, float]:
        """Get Thompson-sampled scores for all actions in context."""
        arm_stats = policy.metadata.get("arm_stats", {})
        ctx_key = self._context_to_key(context)

        actions = arm_stats.get(ctx_key, {})
        if not actions:
            # Try partial context match
            for key in arm_stats:
                if self._context_matches(ctx_key, key):
                    actions = arm_stats[key]
                    break

        if not actions:
            return {}

        scores: dict[str, float] = {}
        for action, stats in actions.items():
            alpha = stats.get("successes", 0) + 1
            beta_val = stats.get("attempts", 0) - stats.get("successes", 0) + 1
            # Thompson sample from Beta(alpha, beta)
            scores[action] = random.betavariate(max(alpha, 1), max(beta_val, 1))

        return scores

    def _extract_context(self, episode: Episode) -> dict[str, Any]:
        """Extract context features from an episode."""
        return {
            "agent_version": episode.agent_version,
            "adk_project": episode.adk_project,
            "failure_family": episode.metadata.get("failure_family", ""),
            "complexity": episode.metadata.get("complexity", ""),
            "n_steps": len(episode.steps),
        }

    def _context_to_key(self, context: dict[str, Any]) -> str:
        """Convert context dict to a stable string key."""
        parts = []
        for key in sorted(context.keys()):
            val = context[key]
            if val:  # skip empty values
                parts.append(f"{key}:{val}")
        return "|".join(parts) if parts else "default"

    def _context_matches(self, query_key: str, stored_key: str) -> bool:
        """Check partial context match."""
        query_parts = set(query_key.split("|"))
        stored_parts = set(stored_key.split("|"))
        if not stored_parts:
            return False
        overlap = len(query_parts & stored_parts)
        return overlap / len(stored_parts) > 0.5
