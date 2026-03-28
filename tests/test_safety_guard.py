"""Tests for OnlineExplorationGuard in policy_opt/safety.py."""

from __future__ import annotations

import pytest

from policy_opt.safety import OnlineExplorationGuard


# ---------------------------------------------------------------------------
# validate_training_config
# ---------------------------------------------------------------------------

def test_valid_offline_config_produces_no_violations():
    config = {
        "online": False,
        "on_policy": False,
        "exploration_strategy": "greedy",
    }
    violations = OnlineExplorationGuard.validate_training_config(config)
    assert violations == []


def test_online_flag_is_blocked():
    config = {"online": True}
    violations = OnlineExplorationGuard.validate_training_config(config)
    assert len(violations) >= 1
    assert any("online" in v.lower() for v in violations)


def test_epsilon_greedy_strategy_is_blocked():
    config = {"exploration_strategy": "epsilon_greedy"}
    violations = OnlineExplorationGuard.validate_training_config(config)
    assert any("epsilon_greedy" in v for v in violations)


def test_on_policy_flag_is_blocked():
    config = {"on_policy": True}
    violations = OnlineExplorationGuard.validate_training_config(config)
    assert any("on_policy" in v.lower() or "on-policy" in v.lower() for v in violations)


def test_blocked_config_key_detected():
    config = {"online_exploration": True}
    violations = OnlineExplorationGuard.validate_training_config(config)
    assert any("online_exploration" in v for v in violations)


def test_multiple_violations_returned():
    config = {"online": True, "on_policy": True, "exploration_strategy": "epsilon_greedy"}
    violations = OnlineExplorationGuard.validate_training_config(config)
    assert len(violations) >= 2


# ---------------------------------------------------------------------------
# validate_policy_application
# ---------------------------------------------------------------------------

def test_valid_deterministic_context_produces_no_violations():
    context = {"explore": False, "epsilon": 0.0}
    violations = OnlineExplorationGuard.validate_policy_application(context)
    assert violations == []


def test_explore_flag_is_blocked():
    context = {"explore": True}
    violations = OnlineExplorationGuard.validate_policy_application(context)
    assert len(violations) >= 1
    assert any("exploration" in v.lower() for v in violations)


def test_nonzero_epsilon_is_blocked():
    context = {"epsilon": 0.1}
    violations = OnlineExplorationGuard.validate_policy_application(context)
    assert any("epsilon" in v.lower() for v in violations)


def test_zero_epsilon_is_allowed():
    context = {"epsilon": 0.0}
    violations = OnlineExplorationGuard.validate_policy_application(context)
    assert violations == []


# ---------------------------------------------------------------------------
# enforce
# ---------------------------------------------------------------------------

def test_enforce_raises_for_online_config():
    config = {"online": True}
    with pytest.raises(ValueError, match="Online exploration guard"):
        OnlineExplorationGuard.enforce(config)


def test_enforce_does_not_raise_for_safe_config():
    config = {"online": False, "on_policy": False}
    # Should not raise
    OnlineExplorationGuard.enforce(config)


def test_enforce_raises_for_on_policy():
    config = {"on_policy": True}
    with pytest.raises(ValueError):
        OnlineExplorationGuard.enforce(config)
