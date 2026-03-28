"""Adaptive test curriculum generation targeting agent weaknesses.

Generates weighted test sets that focus on recent failure patterns,
with progressive difficulty scaling as the agent improves.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class CurriculumConfig:
    """Configuration for curriculum generation."""
    max_cases: int = 50
    difficulty_progression: bool = True
    weight_recent_failures: bool = True
    recency_window_days: int = 7
    min_diversity: float = 0.3  # Min fraction of distinct categories

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_cases": self.max_cases,
            "difficulty_progression": self.difficulty_progression,
            "weight_recent_failures": self.weight_recent_failures,
            "recency_window_days": self.recency_window_days,
            "min_diversity": self.min_diversity,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CurriculumConfig:
        return cls(
            max_cases=d.get("max_cases", 50),
            difficulty_progression=d.get("difficulty_progression", True),
            weight_recent_failures=d.get("weight_recent_failures", True),
            recency_window_days=d.get("recency_window_days", 7),
            min_diversity=d.get("min_diversity", 0.3),
        )


class AdaptiveCurriculum:
    """Generates adaptive test curricula that evolve with agent performance."""

    def generate(
        self,
        failure_history: list[dict[str, Any]],
        current_eval_results: dict[str, Any] | None = None,
        config: CurriculumConfig | None = None,
    ) -> list[dict[str, Any]]:
        """Generate an adaptive test curriculum.

        Args:
            failure_history: List of past failure dicts.  Recognised keys:
                - ``case_id`` (str, optional)
                - ``task`` / ``input_text`` / ``user_message`` (str) — the test input
                - ``category`` / ``failure_family`` (str, optional)
                - ``difficulty`` (float, optional, default 0.5)
                - ``weight`` (float, optional, default 1.0)
                - ``timestamp`` (float or ISO str, optional)
                - ``description`` (str, optional, fallback for task)
                - ``expected_fix`` / ``expected_behavior`` (str, optional)
                - ``severity`` (str, optional)
            current_eval_results: Optional dict with ``pass_rate`` (float) and
                ``per_family`` (dict[str, float]) keys.
            config: Curriculum configuration.

        Returns:
            List of eval case dicts, each with a ``curriculum_score`` key,
            sorted by descending score, capped at ``config.max_cases``.
        """
        if config is None:
            config = CurriculumConfig()

        if not failure_history:
            return []

        # Normalise all entries to a consistent shape
        normalised = [self._normalise(f) for f in failure_history]

        # Weight by recency
        if config.weight_recent_failures:
            weighted = self._weight_by_recency(normalised, config.recency_window_days)
        else:
            weighted = normalised

        # Boost per-family weights based on current eval results
        if current_eval_results:
            per_family = current_eval_results.get("per_family", {})
            for case in weighted:
                family = case.get("category", case.get("failure_family", ""))
                if family and family in per_family:
                    family_rate = float(per_family[family])
                    boost = max(0.5, 2.0 - family_rate * 2.0)
                    case["weight"] = float(case.get("weight", 1.0)) * boost

        # Adjust difficulty if eval results available
        if config.difficulty_progression and current_eval_results:
            pass_rate = float(current_eval_results.get("pass_rate", 0.5))
            weighted = self._adjust_difficulty(weighted, pass_rate)

        # Deduplicate
        cases = self._deduplicate(weighted)

        # Attach curriculum_score = weight * difficulty
        for case in cases:
            w = float(case.get("weight", 1.0))
            d = float(case.get("difficulty", 0.5))
            case["curriculum_score"] = round(w * d, 6)

        # Sort best-first and cap
        cases.sort(key=lambda c: c["curriculum_score"], reverse=True)
        return cases[: config.max_cases]

    @staticmethod
    def _normalise(failure: dict[str, Any]) -> dict[str, Any]:
        """Normalise a raw failure dict to a consistent shape."""
        case = dict(failure)
        # Resolve input text from multiple possible key names
        if "task" not in case:
            case["task"] = (
                case.get("input_text")
                or case.get("user_message")
                or case.get("description")
                or f"Test for {case.get('category', case.get('failure_family', 'unknown'))} failure"
            )
        case.setdefault("case_id", f"curr_{hashlib.md5(case['task'].encode()).hexdigest()[:8]}")
        case.setdefault("category", case.get("failure_family", "general"))
        case.setdefault("difficulty", 0.5)
        case.setdefault("weight", 1.0)
        case.setdefault("expected_behavior", case.get("expected_fix", "correct_behavior"))
        return case

    def _weight_by_recency(
        self, failures: list[dict[str, Any]], window_days: int
    ) -> list[dict[str, Any]]:
        """Weight failures by recency — recent failures get higher weight."""
        now = datetime.now(timezone.utc)
        weighted = []

        for failure in failures:
            ts = failure.get("timestamp", "")
            weight = 1.0
            if ts:
                try:
                    if isinstance(ts, (int, float)):
                        failure_time = datetime.fromtimestamp(ts, tz=timezone.utc)
                    else:
                        failure_time = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    age_days = (now - failure_time).total_seconds() / 86400
                    if age_days <= window_days:
                        weight = 2.0 - (age_days / window_days)  # 2.0 → 1.0 over window
                    else:
                        weight = 0.5  # Older failures still included but lower weight
                except (ValueError, TypeError):
                    pass

            entry = {**failure, "weight": weight}
            weighted.append(entry)

        # Sort by weight descending
        weighted.sort(key=lambda x: x.get("weight", 1.0), reverse=True)
        return weighted

    def _adjust_difficulty(
        self, cases: list[dict[str, Any]], current_pass_rate: float
    ) -> list[dict[str, Any]]:
        """Scale difficulty based on current agent performance.

        Higher pass rate → push difficulty up (agent needs harder tests).
        Lower pass rate  → ease difficulty slightly so agent can make progress.
        """
        # delta: range roughly [-0.15, +0.15]
        delta = (current_pass_rate - 0.5) * 0.3
        for case in cases:
            raw = float(case.get("difficulty", 0.5))
            adjusted = max(0.05, min(0.98, raw + delta))
            case["difficulty"] = round(adjusted, 4)
            # Also update metadata if present
            if "metadata" in case:
                case["metadata"]["difficulty"] = case["difficulty"]
                case["metadata"]["difficulty_adjusted"] = True
        return cases

    def _deduplicate(self, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove near-duplicate cases by task text.

        When two cases share the same normalised task string, the one with the
        higher ``weight`` is kept.
        """
        seen: dict[str, dict[str, Any]] = {}
        for case in cases:
            key = hashlib.md5(
                (case.get("task") or "")[:200].lower().strip().encode()
            ).hexdigest()
            existing = seen.get(key)
            if existing is None:
                seen[key] = case
            elif float(case.get("weight", 1.0)) > float(existing.get("weight", 1.0)):
                seen[key] = case
        return list(seen.values())
