"""Benchmark-based training and evaluation slices.

Manages slicing episode data by category, agent, outcome type, etc.
for focused training and evaluation.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from data.episode_types import Episode


@dataclass
class TrainingSlice:
    """A named slice of episodes for training or evaluation."""
    slice_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    filter_criteria: dict[str, Any] = field(default_factory=dict)
    episode_ids: list[str] = field(default_factory=list)
    train_ids: list[str] = field(default_factory=list)
    eval_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "slice_id": self.slice_id,
            "name": self.name,
            "description": self.description,
            "filter_criteria": self.filter_criteria,
            "episode_ids": self.episode_ids,
            "train_ids": self.train_ids,
            "eval_ids": self.eval_ids,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TrainingSlice":
        return cls(
            slice_id=d.get("slice_id", str(uuid.uuid4())),
            name=d.get("name", ""),
            description=d.get("description", ""),
            filter_criteria=d.get("filter_criteria", {}),
            episode_ids=d.get("episode_ids", []),
            train_ids=d.get("train_ids", []),
            eval_ids=d.get("eval_ids", []),
            created_at=d.get("created_at", datetime.now(timezone.utc).isoformat()),
            metadata=d.get("metadata", {}),
        )


class SliceManager:
    """Creates and manages training/eval slices from episodes."""

    def create_slice(
        self,
        name: str,
        episodes: list[Episode],
        criteria: dict[str, Any] | None = None,
        description: str = "",
    ) -> TrainingSlice:
        """Create a slice by filtering episodes according to criteria.

        Args:
            name: Human-readable name for the slice.
            episodes: Full pool of episodes to filter from.
            criteria: Key/value filter criteria (see _apply_filters for supported keys).
            description: Optional human-readable description of the slice purpose.

        Returns:
            A new TrainingSlice with matching episode IDs populated.
        """
        effective_criteria = criteria or {}
        filtered = self._apply_filters(episodes, effective_criteria)
        episode_ids = [ep.episode_id for ep in filtered]
        return TrainingSlice(
            name=name,
            description=description,
            filter_criteria=effective_criteria,
            episode_ids=episode_ids,
            metadata={"total_episodes": len(episode_ids)},
        )

    def split_train_eval(
        self,
        slice_obj: TrainingSlice,
        train_ratio: float = 0.8,
        seed: int | None = None,
    ) -> TrainingSlice:
        """Split a slice into train and eval sets by shuffling episode IDs.

        Args:
            slice_obj: The slice to split (mutated in place and returned).
            train_ratio: Fraction of episodes assigned to train. Must be in (0, 1).
            seed: Optional RNG seed for reproducible splits.

        Returns:
            The same slice object with train_ids and eval_ids populated.
        """
        if not (0.0 < train_ratio < 1.0):
            raise ValueError(f"train_ratio must be in (0, 1), got {train_ratio}")

        rng = random.Random(seed)
        ids = list(slice_obj.episode_ids)
        rng.shuffle(ids)
        split_point = int(len(ids) * train_ratio)
        slice_obj.train_ids = ids[:split_point]
        slice_obj.eval_ids = ids[split_point:]
        slice_obj.metadata["train_count"] = len(slice_obj.train_ids)
        slice_obj.metadata["eval_count"] = len(slice_obj.eval_ids)
        slice_obj.metadata["train_ratio"] = train_ratio
        return slice_obj

    def create_standard_slices(
        self,
        episodes: list[Episode],
        train_ratio: float = 0.8,
        seed: int | None = None,
    ) -> list[TrainingSlice]:
        """Create a standard set of benchmark slices covering common split dimensions.

        Produces slices for:
        - Each distinct action type found in the episode pool
        - Hard-gate pass/fail status
        - High-reward vs low-reward episodes (median split)
        - Each distinct agent version present

        Each non-empty slice is automatically split into train/eval sets.

        Args:
            episodes: Full episode pool.
            train_ratio: Train fraction for all splits.
            seed: Optional RNG seed for reproducible splits.

        Returns:
            List of non-empty TrainingSlice objects.
        """
        slices: list[TrainingSlice] = []

        # By action type
        for action_type in ["routing_decision", "tool_call", "escalation", "handoff"]:
            s = self.create_slice(
                f"action_{action_type}",
                episodes,
                criteria={"action_type": action_type},
                description=f"Episodes containing at least one {action_type} step",
            )
            if s.episode_ids:
                slices.append(self.split_train_eval(s, train_ratio=train_ratio, seed=seed))

        # By hard gate status
        passed = self.create_slice(
            "hard_gates_passed",
            episodes,
            criteria={"hard_gates_passed": True},
            description="Episodes where all hard gates passed",
        )
        if passed.episode_ids:
            slices.append(self.split_train_eval(passed, train_ratio=train_ratio, seed=seed))

        failed = self.create_slice(
            "hard_gates_failed",
            episodes,
            criteria={"hard_gates_passed": False},
            description="Episodes where one or more hard gates failed",
        )
        if failed.episode_ids:
            slices.append(self.split_train_eval(failed, train_ratio=train_ratio, seed=seed))

        # Median reward split: high vs low
        scalar_rewards = self._compute_scalar_rewards(episodes)
        if scalar_rewards:
            sorted_values = sorted(scalar_rewards.values())
            median_reward = sorted_values[len(sorted_values) // 2]

            high = self.create_slice(
                "high_reward",
                episodes,
                criteria={"min_reward": median_reward},
                description=f"Episodes with scalar reward >= median ({median_reward:.3f})",
            )
            if high.episode_ids:
                slices.append(self.split_train_eval(high, train_ratio=train_ratio, seed=seed))

            low = self.create_slice(
                "low_reward",
                episodes,
                criteria={"max_reward": median_reward},
                description=f"Episodes with scalar reward < median ({median_reward:.3f})",
            )
            if low.episode_ids:
                slices.append(self.split_train_eval(low, train_ratio=train_ratio, seed=seed))

        # By agent version
        agent_versions = {ep.agent_version for ep in episodes if ep.agent_version}
        for version in sorted(agent_versions):
            s = self.create_slice(
                f"agent_version_{version}",
                episodes,
                criteria={"agent_version": version},
                description=f"Episodes from agent version {version}",
            )
            if s.episode_ids:
                slices.append(self.split_train_eval(s, train_ratio=train_ratio, seed=seed))

        return slices

    def merge_slices(
        self,
        slices: list[TrainingSlice],
        name: str,
        description: str = "",
        deduplicate: bool = True,
    ) -> TrainingSlice:
        """Merge multiple slices into a single combined slice.

        Train and eval IDs are merged from their respective sets. If a
        split has not been performed on some slices, their episode_ids are
        treated as additional train candidates.

        Args:
            slices: Slices to merge.
            name: Name for the merged slice.
            description: Optional description.
            deduplicate: If True, remove duplicate episode IDs (default True).

        Returns:
            A new TrainingSlice with merged IDs (not yet re-split).
        """
        all_episode_ids: list[str] = []
        all_train_ids: list[str] = []
        all_eval_ids: list[str] = []

        for s in slices:
            all_episode_ids.extend(s.episode_ids)
            all_train_ids.extend(s.train_ids)
            all_eval_ids.extend(s.eval_ids)

        if deduplicate:
            # Preserve ordering while deduplicating via dict key insertion order.
            all_episode_ids = list(dict.fromkeys(all_episode_ids))
            all_train_ids = list(dict.fromkeys(all_train_ids))
            all_eval_ids = list(dict.fromkeys(all_eval_ids))

        merged = TrainingSlice(
            name=name,
            description=description,
            filter_criteria={"merged_from": [s.name for s in slices]},
            episode_ids=all_episode_ids,
            train_ids=all_train_ids,
            eval_ids=all_eval_ids,
            metadata={
                "total_episodes": len(all_episode_ids),
                "train_count": len(all_train_ids),
                "eval_count": len(all_eval_ids),
                "source_slices": [s.name for s in slices],
            },
        )
        return merged

    def get_slice_stats(self, slice_obj: TrainingSlice) -> dict[str, Any]:
        """Return a summary statistics dict for a slice.

        Args:
            slice_obj: The slice to summarize.

        Returns:
            Dict with counts, split ratio, and metadata.
        """
        total = len(slice_obj.episode_ids)
        train_n = len(slice_obj.train_ids)
        eval_n = len(slice_obj.eval_ids)
        actual_ratio = train_n / max(total, 1)

        return {
            "slice_id": slice_obj.slice_id,
            "name": slice_obj.name,
            "description": slice_obj.description,
            "total_episodes": total,
            "train_count": train_n,
            "eval_count": eval_n,
            "actual_train_ratio": round(actual_ratio, 4),
            "is_split": train_n > 0 or eval_n > 0,
            "filter_criteria": slice_obj.filter_criteria,
            "created_at": slice_obj.created_at,
            "metadata": slice_obj.metadata,
        }

    def filter_by_experiment(
        self,
        episodes: list[Episode],
        experiment_id: str,
        name: str | None = None,
    ) -> TrainingSlice:
        """Convenience method: create a slice for a specific experiment.

        Args:
            episodes: Full episode pool.
            experiment_id: Experiment ID to filter on.
            name: Optional slice name; defaults to 'experiment_<id>'.

        Returns:
            A new (unsplit) TrainingSlice.
        """
        slice_name = name or f"experiment_{experiment_id}"
        return self.create_slice(
            slice_name,
            episodes,
            criteria={"experiment_id": experiment_id},
            description=f"Episodes from experiment {experiment_id}",
        )

    def filter_by_adk_project(
        self,
        episodes: list[Episode],
        adk_project: str,
        name: str | None = None,
    ) -> TrainingSlice:
        """Convenience method: create a slice for a specific ADK project.

        Args:
            episodes: Full episode pool.
            adk_project: ADK project name to filter on.
            name: Optional slice name; defaults to 'adk_<project>'.

        Returns:
            A new (unsplit) TrainingSlice.
        """
        slice_name = name or f"adk_{adk_project}"
        return self.create_slice(
            slice_name,
            episodes,
            criteria={"adk_project": adk_project},
            description=f"Episodes from ADK project {adk_project}",
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _apply_filters(self, episodes: list[Episode], criteria: dict[str, Any]) -> list[Episode]:
        """Filter episodes based on a criteria dict.

        Supported keys:
            action_type (str): Keep episodes with at least one step of this action_type.
            hard_gates_passed (bool): Exact match on episode.hard_gates_passed.
            agent_version (str): Exact match on episode.agent_version.
            adk_project (str): Exact match on episode.adk_project.
            experiment_id (str): Exact match on episode.experiment_id.
            min_reward (float): Keep episodes whose mean scalar reward >= threshold.
            max_reward (float): Keep episodes whose mean scalar reward < threshold.
            eval_run_id (str): Exact match on episode.eval_run_id.
            trace_id (str): Exact match on episode.trace_id.
            has_tool_calls (bool): Keep/exclude episodes that have tool calls.
            has_preference_labels (bool): Keep/exclude episodes with preference labels.
        """
        result = list(episodes)

        if "action_type" in criteria:
            target = criteria["action_type"]
            result = [
                ep for ep in result
                if any(s.action_type == target for s in ep.steps)
            ]

        if "hard_gates_passed" in criteria:
            val = bool(criteria["hard_gates_passed"])
            result = [ep for ep in result if ep.hard_gates_passed == val]

        if "agent_version" in criteria:
            result = [ep for ep in result if ep.agent_version == criteria["agent_version"]]

        if "adk_project" in criteria:
            result = [ep for ep in result if ep.adk_project == criteria["adk_project"]]

        if "experiment_id" in criteria:
            result = [ep for ep in result if ep.experiment_id == criteria["experiment_id"]]

        if "eval_run_id" in criteria:
            result = [ep for ep in result if ep.eval_run_id == criteria["eval_run_id"]]

        if "trace_id" in criteria:
            result = [ep for ep in result if ep.trace_id == criteria["trace_id"]]

        if "min_reward" in criteria:
            threshold = float(criteria["min_reward"])
            result = [
                ep for ep in result
                if ep.total_reward
                and sum(ep.total_reward.values()) / max(len(ep.total_reward), 1) >= threshold
            ]

        if "max_reward" in criteria:
            ceiling = float(criteria["max_reward"])
            result = [
                ep for ep in result
                if ep.total_reward
                and sum(ep.total_reward.values()) / max(len(ep.total_reward), 1) < ceiling
            ]

        if "has_tool_calls" in criteria:
            want = bool(criteria["has_tool_calls"])
            result = [ep for ep in result if bool(ep.tool_calls) == want]

        if "has_preference_labels" in criteria:
            want = bool(criteria["has_preference_labels"])
            result = [ep for ep in result if bool(ep.preference_labels) == want]

        return result

    def _compute_scalar_rewards(self, episodes: list[Episode]) -> dict[str, float]:
        """Compute a simple mean scalar reward for each episode that has reward data.

        Returns:
            Dict mapping episode_id -> scalar reward for episodes with non-empty
            total_reward vectors. Episodes without reward data are omitted.
        """
        result: dict[str, float] = {}
        for ep in episodes:
            if not ep.total_reward:
                continue
            values = list(ep.total_reward.values())
            result[ep.episode_id] = sum(values) / max(len(values), 1)
        return result
