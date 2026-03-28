"""Tests for reward scalarization functions in rewards/scalarizer.py."""

from __future__ import annotations

import pytest

from rewards.scalarizer import (
    build_reward_vector,
    hard_gates_pass,
    lexicographic_scalarize,
    scalarize_with_registry,
    weighted_scalarize,
)
from rewards.types import RewardDefinition, RewardKind, RewardVector, TrustTier


def _vec(rewards: dict, gate_results: dict | None = None) -> RewardVector:
    return RewardVector(
        episode_id="ep-test",
        rewards=rewards,
        hard_gate_results=gate_results or {},
    )


# ---------------------------------------------------------------------------
# hard_gates_pass
# ---------------------------------------------------------------------------

def test_hard_gates_pass_all_true():
    vec = _vec({}, {"gate1": True, "gate2": True})
    assert hard_gates_pass(vec) is True


def test_hard_gates_pass_one_false():
    vec = _vec({}, {"gate1": True, "gate2": False})
    assert hard_gates_pass(vec) is False


def test_hard_gates_pass_empty_gates():
    vec = _vec({"r1": 0.5})
    assert hard_gates_pass(vec) is True


# ---------------------------------------------------------------------------
# lexicographic_scalarize
# ---------------------------------------------------------------------------

def test_lexicographic_scalarize_returns_none_on_gate_failure():
    vec = _vec({"r1": 0.9}, {"gate": False})
    result = lexicographic_scalarize(vec)
    assert result is None


def test_lexicographic_scalarize_returns_float_on_gate_pass():
    vec = _vec({"r1": 0.8, "r2": 0.6}, {"gate": True})
    result = lexicographic_scalarize(vec)
    assert result is not None
    assert isinstance(result, float)


def test_lexicographic_scalarize_no_gates():
    vec = _vec({"r1": 1.0})
    result = lexicographic_scalarize(vec)
    assert result == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# weighted_scalarize
# ---------------------------------------------------------------------------

def test_weighted_scalarize_equal_weights():
    vec = _vec({"r1": 0.8, "r2": 0.4})
    result = weighted_scalarize(vec)
    assert result == pytest.approx(0.6)


def test_weighted_scalarize_custom_weights():
    vec = _vec({"r1": 1.0, "r2": 0.0})
    result = weighted_scalarize(vec, weights={"r1": 2.0, "r2": 1.0})
    # (1.0*2 + 0.0*1) / 3 = 0.6667
    assert result == pytest.approx(2.0 / 3.0, rel=1e-4)


def test_weighted_scalarize_empty_rewards():
    vec = _vec({})
    assert weighted_scalarize(vec) == 0.0


# ---------------------------------------------------------------------------
# scalarize_with_registry
# ---------------------------------------------------------------------------

def test_scalarize_with_registry_uses_definition_weights():
    defn = RewardDefinition(
        reward_id="r1",
        name="acc",
        kind=RewardKind.verifiable,
        weight=3.0,
        hard_gate=False,
        trust_tier=TrustTier.tier_1,
    )
    vec = _vec({"r1": 0.6})
    result = scalarize_with_registry(vec, [defn])
    assert result is not None
    assert isinstance(result, float)


def test_scalarize_with_registry_gate_failure_returns_none():
    defn = RewardDefinition(
        reward_id="gate1",
        name="hard_gate",
        hard_gate=True,
        trust_tier=TrustTier.tier_1,
    )
    vec = RewardVector(
        rewards={"gate1": 0.0},
        hard_gate_results={"gate1": False},
    )
    result = scalarize_with_registry(vec, [defn])
    assert result is None


# ---------------------------------------------------------------------------
# build_reward_vector
# ---------------------------------------------------------------------------

def test_build_reward_vector_populates_hard_gate_results():
    defn = RewardDefinition(
        reward_id="g1",
        name="gate",
        hard_gate=True,
        trust_tier=TrustTier.tier_1,
    )
    vec = build_reward_vector({"g1": 1.0, "soft": 0.5}, [defn])
    assert "g1" in vec.hard_gate_results
    assert vec.hard_gate_results["g1"] is True
    assert "soft" not in vec.hard_gate_results


def test_build_reward_vector_gate_fails_when_value_zero():
    defn = RewardDefinition(reward_id="g1", name="gate", hard_gate=True, trust_tier=TrustTier.tier_1)
    vec = build_reward_vector({"g1": 0.0}, [defn])
    assert vec.hard_gate_results["g1"] is False
