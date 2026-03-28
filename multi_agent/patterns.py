"""Multi-agent communication and topology patterns."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentPattern(str, Enum):
    """Supported multi-agent communication and execution patterns.

    - SEQUENTIAL: Agents execute one after another in a fixed chain.
    - PARALLEL: Agents execute concurrently and results are merged.
    - LOOP: A single agent (or chain) iterates until a stopping condition.
    - HIERARCHY: Orchestrator delegates to specialists in a tree structure.
    - PEER_TO_PEER: Agents communicate directly without a central coordinator.
    """

    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    LOOP = "loop"
    HIERARCHY = "hierarchy"
    PEER_TO_PEER = "peer_to_peer"


@dataclass
class PatternConfig:
    """Configuration for a chosen multi-agent pattern.

    Attributes:
        pattern: The :class:`AgentPattern` variant to use.
        agents: Ordered list of agent identifiers participating in the pattern.
        config: Pattern-specific configuration (e.g., max_iterations for LOOP,
            merge_strategy for PARALLEL).
    """

    pattern: AgentPattern
    agents: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dictionary."""
        return {
            "pattern": self.pattern.value,
            "agents": list(self.agents),
            "config": dict(self.config),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PatternConfig":
        """Deserialise from a plain dictionary."""
        return cls(
            pattern=AgentPattern(data.get("pattern", AgentPattern.SEQUENTIAL)),
            agents=list(data.get("agents", [])),
            config=dict(data.get("config", {})),
        )


class PatternOptimizer:
    """Selects and evaluates the best multi-agent topology for a given workload.

    The optimizer examines agent capability descriptions and runtime metrics to
    recommend the :class:`AgentPattern` that minimises latency and cost while
    maximising quality.
    """

    # Heuristic weights used during topology selection
    _LATENCY_WEIGHT = 0.4
    _QUALITY_WEIGHT = 0.4
    _COST_WEIGHT = 0.2

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def optimize_topology(
        self,
        agents: list[dict],
        metrics: dict,
    ) -> PatternConfig:
        """Recommend the best pattern for the given agents and observed metrics.

        Strategy:
        1. Inspect agent roles and dependencies to rule out invalid patterns.
        2. Score each candidate pattern against the latency / quality / cost
           metrics using simple weighted heuristics.
        3. Return a :class:`PatternConfig` for the highest-scoring pattern.

        Args:
            agents: List of agent description dicts, each with at minimum an
                ``id`` field and optionally ``role``, ``dependencies``, and
                ``capabilities`` fields.
            metrics: Observed runtime metrics dict with optional keys
                ``avg_latency_ms``, ``success_rate``, and ``avg_cost_usd``.

        Returns:
            :class:`PatternConfig` with the recommended pattern and sensible
            defaults for its configuration.
        """
        agent_ids = [a.get("id", a.get("name", f"agent_{i}")) for i, a in enumerate(agents)]
        n = len(agents)

        if n == 0:
            return PatternConfig(pattern=AgentPattern.SEQUENTIAL, agents=[], config={})

        scores = self._score_patterns(agents, metrics)
        best_pattern = max(scores, key=lambda p: scores[p])

        config = self._default_config(best_pattern, agents, metrics)

        return PatternConfig(
            pattern=best_pattern,
            agents=agent_ids,
            config=config,
        )

    def evaluate_pattern(
        self,
        pattern: PatternConfig,
        eval_cases: list[dict],
    ) -> dict:
        """Evaluate a pattern configuration against a set of eval cases.

        Simulates pattern execution over the provided eval cases and returns
        aggregate metrics. Actual execution is delegated to the caller via the
        eval cases' ``result`` field when pre-populated; otherwise synthetic
        estimates are used.

        Args:
            pattern: The :class:`PatternConfig` to evaluate.
            eval_cases: List of eval case dicts, each optionally containing
                ``latency_ms``, ``success``, and ``cost_usd`` fields from a
                prior run.

        Returns:
            Dictionary with keys ``pattern``, ``agents``, ``avg_latency_ms``,
            ``success_rate``, ``avg_cost_usd``, ``efficiency_score``, and
            ``recommendation``.
        """
        n_cases = len(eval_cases)

        if n_cases == 0:
            return {
                "pattern": pattern.pattern.value,
                "agents": pattern.agents,
                "avg_latency_ms": 0.0,
                "success_rate": 0.0,
                "avg_cost_usd": 0.0,
                "efficiency_score": 0.0,
                "recommendation": "insufficient_data",
            }

        latencies = [c.get("latency_ms", self._estimate_latency(pattern)) for c in eval_cases]
        successes = [c.get("success", True) for c in eval_cases]
        costs = [c.get("cost_usd", self._estimate_cost(pattern)) for c in eval_cases]

        avg_latency = sum(latencies) / n_cases
        success_rate = sum(1 for s in successes if s) / n_cases
        avg_cost = sum(costs) / n_cases

        # Efficiency: penalise high latency and cost, reward success
        efficiency = (
            success_rate * self._QUALITY_WEIGHT
            - min(avg_latency / 5000.0, 1.0) * self._LATENCY_WEIGHT
            - min(avg_cost / 0.1, 1.0) * self._COST_WEIGHT
        )
        efficiency = max(0.0, min(1.0, efficiency + 0.5))  # normalise to [0, 1]

        recommendation = "use" if efficiency >= 0.6 else "consider_alternative"

        return {
            "pattern": pattern.pattern.value,
            "agents": pattern.agents,
            "avg_latency_ms": round(avg_latency, 2),
            "success_rate": round(success_rate, 4),
            "avg_cost_usd": round(avg_cost, 6),
            "efficiency_score": round(efficiency, 4),
            "recommendation": recommendation,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _score_patterns(
        self, agents: list[dict], metrics: dict
    ) -> dict[AgentPattern, float]:
        """Assign a heuristic score to each candidate pattern."""
        n = len(agents)
        avg_latency = metrics.get("avg_latency_ms", 500.0)
        success_rate = metrics.get("success_rate", 0.9)

        # Check for explicit role hints
        roles = {a.get("role", "") for a in agents}
        has_orchestrator = "orchestrator" in roles
        has_deps = any(a.get("dependencies") for a in agents)

        scores: dict[AgentPattern, float] = {
            AgentPattern.SEQUENTIAL: 0.5,
            AgentPattern.PARALLEL: 0.5,
            AgentPattern.LOOP: 0.3,
            AgentPattern.HIERARCHY: 0.5,
            AgentPattern.PEER_TO_PEER: 0.3,
        }

        # Prefer HIERARCHY when there is an explicit orchestrator or deps
        if has_orchestrator or has_deps:
            scores[AgentPattern.HIERARCHY] += 0.3

        # Prefer PARALLEL when latency is the bottleneck and agents are independent
        if avg_latency > 1000 and not has_deps and n > 1:
            scores[AgentPattern.PARALLEL] += 0.3

        # Prefer LOOP for iterative / refinement workflows
        if metrics.get("iteration_hint", False) or success_rate < 0.75:
            scores[AgentPattern.LOOP] += 0.2

        # Prefer SEQUENTIAL for simple linear flows
        if n <= 2 and not has_orchestrator:
            scores[AgentPattern.SEQUENTIAL] += 0.2

        # PEER_TO_PEER suits collaborative tasks with many peer agents
        if n >= 4 and not has_orchestrator:
            scores[AgentPattern.PEER_TO_PEER] += 0.15

        return scores

    def _default_config(
        self, pattern: AgentPattern, agents: list[dict], metrics: dict
    ) -> dict[str, Any]:
        """Return sensible default configuration for the chosen pattern."""
        if pattern == AgentPattern.LOOP:
            return {
                "max_iterations": metrics.get("suggested_max_iterations", 5),
                "stop_condition": "success_or_max_iterations",
            }
        if pattern == AgentPattern.PARALLEL:
            return {
                "merge_strategy": "first_success",
                "timeout_ms": metrics.get("avg_latency_ms", 5000) * 3,
            }
        if pattern == AgentPattern.HIERARCHY:
            orchestrators = [
                a.get("id", a.get("name", "")) for a in agents
                if a.get("role") == "orchestrator"
            ]
            return {
                "root": orchestrators[0] if orchestrators else (agents[0].get("id", "") if agents else ""),
                "delegation_strategy": "capability_match",
            }
        if pattern == AgentPattern.PEER_TO_PEER:
            return {
                "communication": "broadcast",
                "consensus_threshold": 0.6,
            }
        # SEQUENTIAL default
        return {"chain": [a.get("id", a.get("name", "")) for a in agents]}

    def _estimate_latency(self, pattern: PatternConfig) -> float:
        """Estimate latency (ms) for a pattern based on agent count."""
        n = max(1, len(pattern.agents))
        base = 200.0
        multipliers = {
            AgentPattern.SEQUENTIAL: n,
            AgentPattern.PARALLEL: 1.2,
            AgentPattern.LOOP: pattern.config.get("max_iterations", 3),
            AgentPattern.HIERARCHY: n * 0.8,
            AgentPattern.PEER_TO_PEER: n * 0.6,
        }
        return base * multipliers.get(pattern.pattern, n)

    def _estimate_cost(self, pattern: PatternConfig) -> float:
        """Estimate cost (USD) for a pattern based on agent count."""
        n = max(1, len(pattern.agents))
        base_cost = 0.002
        multipliers = {
            AgentPattern.SEQUENTIAL: n,
            AgentPattern.PARALLEL: n,
            AgentPattern.LOOP: n * pattern.config.get("max_iterations", 3),
            AgentPattern.HIERARCHY: n * 1.1,
            AgentPattern.PEER_TO_PEER: n * 0.9,
        }
        return base_cost * multipliers.get(pattern.pattern, n)
