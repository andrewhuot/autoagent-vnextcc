"""Hard-gate-aware reward scalarization.

Rule: hard gates are checked first (lexicographic). If any fails, the episode
is invalid for promotion. Soft objectives are optimized only when all gates pass.
"""

from __future__ import annotations

from typing import Any

from rewards.types import RewardDefinition, RewardVector


def hard_gates_pass(vector: RewardVector) -> bool:
    """Check if all hard gates in the reward vector passed."""
    if not vector.hard_gate_results:
        return True
    return all(vector.hard_gate_results.values())


def lexicographic_scalarize(
    vector: RewardVector,
    weights: dict[str, float] | None = None,
) -> float | None:
    """Scalarize reward vector with lexicographic hard-gate check.

    Returns None if any hard gate fails (episode invalid for promotion).
    Otherwise returns weighted sum of soft rewards.
    """
    if not hard_gates_pass(vector):
        return None  # episode invalid
    return weighted_scalarize(vector, weights)


def weighted_scalarize(
    vector: RewardVector,
    weights: dict[str, float] | None = None,
) -> float:
    """Weighted sum of reward values (ignores hard gates)."""
    if not vector.rewards:
        return 0.0
    if weights is None:
        # Equal weighting
        return sum(vector.rewards.values()) / max(len(vector.rewards), 1)
    total = 0.0
    weight_sum = 0.0
    for reward_id, value in vector.rewards.items():
        w = weights.get(reward_id, 1.0)
        total += value * w
        weight_sum += w
    return total / max(weight_sum, 1e-9)


def scalarize_with_registry(
    vector: RewardVector,
    definitions: list[RewardDefinition],
) -> float | None:
    """Scalarize using reward definitions from registry for weights and gate info.

    1. Check all hard gates (definitions where hard_gate=True)
    2. Weight soft rewards by definition.weight and trust_tier
    3. Return None if gates fail
    """
    # Build lookup
    def_by_id = {d.reward_id: d for d in definitions}
    def_by_name = {d.name: d for d in definitions}

    # Check hard gates
    for gate_id, passed in vector.hard_gate_results.items():
        defn = def_by_id.get(gate_id) or def_by_name.get(gate_id)
        if defn and defn.hard_gate and not passed:
            return None

    # Weighted scalarization using definition weights and trust tiers
    weights = {}
    for reward_id in vector.rewards:
        defn = def_by_id.get(reward_id) or def_by_name.get(reward_id)
        if defn:
            # Higher trust (lower tier number) gets more weight
            trust_multiplier = 1.0 / max(defn.trust_tier.value, 1)
            weights[reward_id] = defn.weight * trust_multiplier
        else:
            weights[reward_id] = 1.0

    return weighted_scalarize(vector, weights)


def build_reward_vector(
    rewards: dict[str, float],
    definitions: list[RewardDefinition],
) -> RewardVector:
    """Build a RewardVector from raw reward values and definitions.

    Automatically populates hard_gate_results based on which definitions
    are marked as hard_gate.
    """
    hard_gate_results = {}
    for defn in definitions:
        if defn.hard_gate and defn.reward_id in rewards:
            # For hard gates: value > 0 means pass
            hard_gate_results[defn.reward_id] = rewards[defn.reward_id] > 0

    return RewardVector(
        rewards=rewards,
        hard_gate_results=hard_gate_results,
    )
