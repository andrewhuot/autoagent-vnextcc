"""Mode router — translates user-facing optimization modes to internal strategies.

Users think in terms of objectives, guardrails, and budgets.  The optimizer
thinks in terms of search strategies, bandit policies, and candidate counts.
This module bridges the two, keeping algorithm details out of the user-facing
configuration surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from optimizer.search import BanditPolicy, SearchStrategy


# ---------------------------------------------------------------------------
# User-facing enums
# ---------------------------------------------------------------------------


class OptimizationMode(str, Enum):
    """User-facing optimization intensity level."""

    STANDARD = "standard"
    ADVANCED = "advanced"
    RESEARCH = "research"


class AutonomyLevel(str, Enum):
    """How much latitude the optimizer has to apply changes."""

    SUPERVISED = "supervised"
    SEMI_AUTO = "semi-auto"
    AUTONOMOUS = "autonomous"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ModeConfig:
    """User-facing optimization configuration."""

    mode: OptimizationMode = OptimizationMode.STANDARD
    objective: str = ""
    guardrails: list[str] = field(default_factory=list)
    budget_per_cycle: float = 1.0
    budget_daily: float = 10.0
    autonomy: AutonomyLevel = AutonomyLevel.SUPERVISED
    allowed_surfaces: list[str] = field(
        default_factory=lambda: ["instructions", "examples", "tool_descriptions"]
    )


@dataclass
class ResolvedStrategy:
    """Internal strategy resolved from user-facing mode config."""

    search_strategy: SearchStrategy
    bandit_policy: BanditPolicy
    max_candidates: int
    max_eval_budget: int
    algorithm_overrides: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Mapping tables
# ---------------------------------------------------------------------------

_MODE_STRATEGY_MAP: dict[OptimizationMode, SearchStrategy] = {
    OptimizationMode.STANDARD: SearchStrategy.SIMPLE,
    OptimizationMode.ADVANCED: SearchStrategy.ADAPTIVE,
    OptimizationMode.RESEARCH: SearchStrategy.FULL,
}

# Legacy strategy name → mode mapping for backwards compatibility.
_LEGACY_STRATEGY_MAP: dict[str, OptimizationMode] = {
    "simple": OptimizationMode.STANDARD,
    "adaptive": OptimizationMode.ADVANCED,
    "full": OptimizationMode.RESEARCH,
    "pro": OptimizationMode.RESEARCH,
}


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class ModeRouter:
    """Translates user-facing mode configuration to internal optimizer strategy."""

    def resolve(self, config: ModeConfig) -> ResolvedStrategy:
        """Resolve a *ModeConfig* into the concrete strategy the optimizer needs."""
        strategy = _MODE_STRATEGY_MAP[config.mode]

        if config.mode == OptimizationMode.STANDARD:
            return ResolvedStrategy(
                search_strategy=strategy,
                bandit_policy=BanditPolicy.THOMPSON,
                max_candidates=3,
                max_eval_budget=2,
            )
        elif config.mode == OptimizationMode.ADVANCED:
            return ResolvedStrategy(
                search_strategy=strategy,
                bandit_policy=BanditPolicy.THOMPSON,
                max_candidates=10,
                max_eval_budget=5,
            )
        else:  # RESEARCH
            return ResolvedStrategy(
                search_strategy=strategy,
                bandit_policy=BanditPolicy.UCB,
                max_candidates=20,
                max_eval_budget=10,
                algorithm_overrides={
                    "enable_pareto": True,
                    "enable_gepa": True,
                    "enable_simba": True,
                },
            )

    @staticmethod
    def from_legacy_strategy(strategy_name: str) -> OptimizationMode:
        """Map an old-style strategy string to the new *OptimizationMode*."""
        return _LEGACY_STRATEGY_MAP.get(strategy_name, OptimizationMode.STANDARD)

    @staticmethod
    def parse_guardrails(guardrails: list[str]) -> list[dict[str, Any]]:
        """Parse natural-language guardrail strings into structured constraints.

        Each returned dict has:
        - ``raw``: the original string
        - ``metric``: resolved metric name (or ``None``)
        - ``threshold``: numeric threshold (or ``None``)
        - ``direction``: ``"gte"`` or ``"lte"`` (or ``None``)
        """
        parsed: list[dict[str, Any]] = []
        for g in guardrails:
            entry: dict[str, Any] = {
                "raw": g,
                "metric": None,
                "threshold": None,
                "direction": None,
            }
            g_lower = g.lower()

            if "safety" in g_lower:
                entry["metric"] = "safety_compliance"
                entry["direction"] = "gte"
                for token in g_lower.split():
                    try:
                        val = float(token)
                        entry["threshold"] = val
                        break
                    except ValueError:
                        continue
                if entry["threshold"] is None:
                    entry["threshold"] = 1.0

            elif "cost" in g_lower:
                entry["metric"] = "token_cost"
                entry["direction"] = "lte"
                for token in g_lower.replace("$", "").split():
                    try:
                        val = float(token)
                        entry["threshold"] = val
                        break
                    except ValueError:
                        continue

            elif "latency" in g_lower:
                entry["metric"] = "latency_p95"
                entry["direction"] = "lte"
                for token in g_lower.replace("ms", "").replace("s", "").split():
                    try:
                        val = float(token)
                        entry["threshold"] = val
                        break
                    except ValueError:
                        continue

            parsed.append(entry)
        return parsed

    def migrate_config(self, old_config: dict[str, Any]) -> dict[str, Any]:
        """Migrate old optimizer config format to the new ``optimization`` section.

        Old format::

            optimizer:
                search_strategy: adaptive
                bandit_policy: ucb1

        New format::

            optimization:
                mode: advanced
                objective: ""
                guardrails: []
                budget:
                    per_cycle: 1.0
                    daily: 10.0
                autonomy: supervised
        """
        new_config = dict(old_config)
        optimizer_section = old_config.get("optimizer", {})

        old_strategy = optimizer_section.get("search_strategy", "simple")
        mode = self.from_legacy_strategy(old_strategy)

        old_budget = old_config.get("budget", {})

        new_config["optimization"] = {
            "mode": mode.value,
            "objective": "",
            "guardrails": [],
            "budget": {
                "per_cycle": old_budget.get("per_cycle_dollars", 1.0),
                "daily": old_budget.get("daily_dollars", 10.0),
            },
            "autonomy": "supervised",
            "allowed_surfaces": ["instructions", "examples", "tool_descriptions"],
        }

        return new_config
