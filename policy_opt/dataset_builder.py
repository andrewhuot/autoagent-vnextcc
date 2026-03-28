"""Reward Dataset Builder — builds training datasets from episodes and rewards."""

from __future__ import annotations

import json
import os
import statistics
import uuid
from typing import Any

from data.episode_types import Episode
from rewards.types import RewardDefinition


class RewardDatasetBuilder:
    """Builds training datasets from the episode store for different training modes.

    Produces four dataset formats:
    1. verifiable_train.jsonl — for RLVR training (episodes with verifier rewards)
    2. preference_pairs.jsonl — for DPO/preference training
    3. episode_export.jsonl — full episodes in RLDS format
    4. reward_audit_set.jsonl — for reward auditing and anti-hacking tests
    """

    def __init__(self, output_dir: str = ".autoagent") -> None:
        self._output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Public builders
    # ------------------------------------------------------------------

    def build_verifiable_dataset(
        self,
        episodes: list[Episode],
        reward_definitions: list[RewardDefinition] | None = None,
    ) -> str:
        """Build JSONL dataset for verifier-based training.

        Each record contains:
        - messages: conversation turns from episode steps
        - reward: scalarized verifiable reward
        - hard_gates_passed: bool
        - reward_breakdown: per-reward-id values

        Only includes episodes where hard_gates_passed=True.
        Returns output file path.
        """
        def_by_id: dict[str, RewardDefinition] = (
            {d.reward_id: d for d in reward_definitions}
            if reward_definitions
            else {}
        )

        records: list[dict[str, Any]] = []
        for episode in episodes:
            if not episode.hard_gates_passed:
                continue

            messages = self._steps_to_messages(episode)
            reward_breakdown = dict(episode.total_reward)

            # Scalarize: weighted sum using definition weights where available,
            # otherwise equal weighting.
            scalar_reward = self._scalarize(reward_breakdown, def_by_id)

            record: dict[str, Any] = {
                "episode_id": episode.episode_id,
                "messages": messages,
                "reward": scalar_reward,
                "hard_gates_passed": episode.hard_gates_passed,
                "reward_breakdown": reward_breakdown,
                "agent_version": episode.agent_version,
                "experiment_id": episode.experiment_id,
                "created_at": episode.created_at,
            }
            records.append(record)

        return self._write_jsonl(records, "verifiable_train.jsonl")

    def build_preference_pairs(self, episodes: list[Episode]) -> str:
        """Build pairwise preference dataset from episodes with preference labels.

        Each record contains:
        - input_text: the prompt/observation
        - chosen: preferred response
        - rejected: dispreferred response
        - source: label source
        - metadata: confidence, reason codes

        Returns output file path.
        """
        records: list[dict[str, Any]] = []
        for episode in episodes:
            if not episode.preference_labels:
                continue

            for label in episode.preference_labels:
                # Each preference label must contain the pair fields; skip
                # incomplete entries rather than producing corrupt records.
                input_text = (
                    label.get("input_text")
                    or label.get("prompt")
                    or label.get("observation")
                    or ""
                )
                chosen = label.get("chosen") or label.get("preferred") or ""
                rejected = label.get("rejected") or label.get("dispreferred") or ""

                if not (input_text and chosen and rejected):
                    continue

                metadata: dict[str, Any] = {
                    "episode_id": episode.episode_id,
                    "agent_version": episode.agent_version,
                    "experiment_id": episode.experiment_id,
                }
                # Carry over annotator-provided metadata fields.
                for key in ("confidence", "reason_codes", "annotator_id", "label_id"):
                    if key in label:
                        metadata[key] = label[key]

                record: dict[str, Any] = {
                    "input_text": input_text,
                    "chosen": chosen,
                    "rejected": rejected,
                    "source": label.get("source", "episode_label"),
                    "metadata": metadata,
                }
                records.append(record)

        return self._write_jsonl(records, "preference_pairs.jsonl")

    def build_episode_export(self, episodes: list[Episode]) -> str:
        """Export full episodes in RLDS-inspired JSONL format.

        Each line is a complete episode dict with all steps, rewards, and metadata.
        Returns output file path.
        """
        records: list[dict[str, Any]] = [ep.to_dict() for ep in episodes]
        return self._write_jsonl(records, "episode_export.jsonl")

    def build_audit_set(
        self,
        episodes: list[Episode],
        reward_definitions: list[RewardDefinition] | None = None,
    ) -> str:
        """Build reward audit dataset for anti-hacking and quality checks.

        Includes:
        - Episodes with borderline rewards (near decision boundaries)
        - Episodes where hard gates disagreed with soft rewards
        - High-reward episodes (potential reward hacking)
        - Low-reward episodes (potential false negatives)

        Returns output file path.
        """
        def_by_id: dict[str, RewardDefinition] = (
            {d.reward_id: d for d in reward_definitions}
            if reward_definitions
            else {}
        )

        # Compute scalar rewards for all episodes so we can reason about
        # the population distribution.
        scored: list[tuple[Episode, float]] = []
        for episode in episodes:
            scalar = self._scalarize(episode.total_reward, def_by_id)
            scored.append((episode, scalar))

        reward_values = [s for _, s in scored]
        audit_records: list[dict[str, Any]] = []

        if reward_values:
            mean_r = statistics.mean(reward_values)
            stdev_r = statistics.pstdev(reward_values) if len(reward_values) > 1 else 0.0
            high_threshold = mean_r + 2.0 * stdev_r
            low_threshold = mean_r - 2.0 * stdev_r
            # Borderline: within 0.5 stdev of the mean (ambiguous quality zone).
            border_half = max(0.5 * stdev_r, 0.05)
            border_lo = mean_r - border_half
            border_hi = mean_r + border_half
        else:
            mean_r = 0.0
            stdev_r = 0.0
            high_threshold = 1.0
            low_threshold = 0.0
            border_lo = -0.1
            border_hi = 0.1

        for episode, scalar in scored:
            reasons: list[str] = []

            # Borderline reward.
            if border_lo <= scalar <= border_hi:
                reasons.append("borderline_reward")

            # Hard-gate / soft-reward disagreement: hard gate passed but scalar
            # reward is very low, or gate failed but scalar is high.
            if episode.hard_gates_passed and scalar < low_threshold:
                reasons.append("gate_passed_low_soft_reward")
            if not episode.hard_gates_passed and scalar > high_threshold:
                reasons.append("gate_failed_high_soft_reward")

            # Potential reward hacking: unusually high scalar.
            if scalar > high_threshold:
                reasons.append("high_reward_outlier")

            # Potential false negatives: unusually low scalar.
            if scalar < low_threshold:
                reasons.append("low_reward_outlier")

            if not reasons:
                continue

            record: dict[str, Any] = {
                "episode_id": episode.episode_id,
                "agent_version": episode.agent_version,
                "experiment_id": episode.experiment_id,
                "scalar_reward": scalar,
                "hard_gates_passed": episode.hard_gates_passed,
                "reward_breakdown": dict(episode.total_reward),
                "audit_reasons": reasons,
                "population_mean": mean_r,
                "population_stdev": stdev_r,
                "messages": self._steps_to_messages(episode),
                "tool_calls": episode.tool_calls,
                "business_outcomes": episode.business_outcomes,
                "created_at": episode.created_at,
            }
            audit_records.append(record)

        return self._write_jsonl(audit_records, "reward_audit_set.jsonl")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _steps_to_messages(self, episode: Episode) -> list[dict[str, Any]]:
        """Convert episode steps into a flat list of conversation-style messages."""
        messages: list[dict[str, Any]] = []
        for step in episode.steps:
            obs = step.observation
            act = step.action

            # Observation becomes a "user" turn if it contains text content.
            obs_text = (
                obs.get("text")
                or obs.get("content")
                or obs.get("message")
                or (json.dumps(obs) if obs else "")
            )
            if obs_text:
                messages.append({"role": "user", "content": obs_text})

            # Action becomes an "assistant" turn.
            act_text = (
                act.get("text")
                or act.get("content")
                or act.get("response")
                or act.get("output")
                or (json.dumps(act) if act else "")
            )
            if act_text:
                msg: dict[str, Any] = {"role": "assistant", "content": act_text}
                if step.action_type:
                    msg["action_type"] = step.action_type
                messages.append(msg)

        return messages

    def _scalarize(
        self,
        reward_breakdown: dict[str, float],
        def_by_id: dict[str, RewardDefinition],
    ) -> float:
        """Weighted-average scalarization using definition weights where available."""
        if not reward_breakdown:
            return 0.0

        total_weighted = 0.0
        total_weight = 0.0
        for reward_id, value in reward_breakdown.items():
            defn = def_by_id.get(reward_id)
            weight = defn.weight if defn else 1.0
            total_weighted += value * weight
            total_weight += weight

        return total_weighted / max(total_weight, 1e-9)

    def _write_jsonl(self, records: list[dict], filename: str) -> str:
        """Write records to JSONL file. Returns full path."""
        path = os.path.join(self._output_dir, filename)
        with open(path, "w") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")
        return path
