"""Tests for RewardDefinition and RewardVector types in rewards/types.py."""

from __future__ import annotations

import pytest

from rewards.types import (
    RewardDefinition,
    RewardGranularity,
    RewardKind,
    RewardScope,
    RewardSource,
    RewardVector,
    TrustTier,
)


# ---------------------------------------------------------------------------
# Enum value tests
# ---------------------------------------------------------------------------

def test_reward_kind_values():
    assert RewardKind.verifiable.value == "verifiable"
    assert RewardKind.preference.value == "preference"
    assert RewardKind.business_outcome.value == "business_outcome"
    assert RewardKind.constitutional.value == "constitutional"


def test_trust_tier_ordering():
    assert TrustTier.tier_1.value < TrustTier.tier_5.value
    assert TrustTier.tier_1.value == 1
    assert TrustTier.tier_5.value == 5


# ---------------------------------------------------------------------------
# RewardDefinition serialization round-trip
# ---------------------------------------------------------------------------

def test_reward_definition_to_dict_from_dict_round_trip():
    defn = RewardDefinition(
        name="test_reward",
        kind=RewardKind.verifiable,
        scope=RewardScope.runtime,
        granularity=RewardGranularity.step,
        source=RewardSource.deterministic_checker,
        trust_tier=TrustTier.tier_1,
        weight=2.5,
        hard_gate=True,
        slices=["slice_a", "slice_b"],
        description="A test reward",
        checker_fn="my_module.check",
        version=3,
    )
    d = defn.to_dict()
    restored = RewardDefinition.from_dict(d)

    assert restored.name == defn.name
    assert restored.kind == defn.kind
    assert restored.scope == defn.scope
    assert restored.granularity == defn.granularity
    assert restored.source == defn.source
    assert restored.trust_tier == defn.trust_tier
    assert restored.weight == defn.weight
    assert restored.hard_gate == defn.hard_gate
    assert restored.slices == defn.slices
    assert restored.description == defn.description
    assert restored.checker_fn == defn.checker_fn
    assert restored.version == defn.version
    assert restored.reward_id == defn.reward_id


def test_reward_definition_defaults():
    defn = RewardDefinition(name="minimal")
    assert defn.hard_gate is False
    assert defn.weight == 1.0
    assert defn.slices == []
    assert defn.kind == RewardKind.verifiable
    assert defn.trust_tier == TrustTier.tier_1


def test_reward_definition_from_dict_handles_missing_fields():
    restored = RewardDefinition.from_dict({"name": "sparse"})
    assert restored.name == "sparse"
    assert restored.version == 1
    assert restored.hard_gate is False


# ---------------------------------------------------------------------------
# RewardVector serialization and all_hard_gates_passed
# ---------------------------------------------------------------------------

def test_reward_vector_round_trip():
    vec = RewardVector(
        episode_id="ep-001",
        rewards={"r1": 0.8, "r2": 0.5},
        hard_gate_results={"gate1": True, "gate2": True},
        metadata={"run": "test"},
    )
    restored = RewardVector.from_dict(vec.to_dict())

    assert restored.episode_id == vec.episode_id
    assert restored.rewards == vec.rewards
    assert restored.hard_gate_results == vec.hard_gate_results
    assert restored.metadata == vec.metadata


def test_reward_vector_all_hard_gates_passed_true():
    vec = RewardVector(hard_gate_results={"g1": True, "g2": True})
    assert vec.all_hard_gates_passed is True


def test_reward_vector_all_hard_gates_passed_false():
    vec = RewardVector(hard_gate_results={"g1": True, "g2": False})
    assert vec.all_hard_gates_passed is False


def test_reward_vector_no_hard_gates_is_passing():
    vec = RewardVector(hard_gate_results={})
    assert vec.all_hard_gates_passed is True
