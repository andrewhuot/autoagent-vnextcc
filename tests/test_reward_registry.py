"""Tests for RewardRegistry CRUD operations in rewards/registry.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from rewards.registry import RewardRegistry
from rewards.types import RewardDefinition, RewardKind


@pytest.fixture
def registry(tmp_path: Path) -> RewardRegistry:
    db = tmp_path / "rewards_test.db"
    reg = RewardRegistry(str(db))
    yield reg
    reg.close()


def _make_defn(name: str, kind: RewardKind = RewardKind.verifiable, hard_gate: bool = False) -> RewardDefinition:
    return RewardDefinition(name=name, kind=kind, hard_gate=hard_gate, description=f"desc-{name}")


# ---------------------------------------------------------------------------
# Register and get
# ---------------------------------------------------------------------------

def test_register_and_get_latest(registry: RewardRegistry):
    defn = _make_defn("accuracy")
    name, version = registry.register(defn)
    assert name == "accuracy"
    assert version == 1

    fetched = registry.get("accuracy")
    assert fetched is not None
    assert fetched.name == "accuracy"
    assert fetched.version == 1


def test_register_increments_version(registry: RewardRegistry):
    registry.register(_make_defn("metric"))
    _, v2 = registry.register(_make_defn("metric"))
    assert v2 == 2

    fetched = registry.get("metric")
    assert fetched.version == 2


def test_get_specific_version(registry: RewardRegistry):
    registry.register(_make_defn("metric"))
    registry.register(_make_defn("metric"))
    v1 = registry.get("metric", version=1)
    assert v1 is not None
    assert v1.version == 1


def test_get_missing_returns_none(registry: RewardRegistry):
    assert registry.get("nonexistent") is None


# ---------------------------------------------------------------------------
# List operations
# ---------------------------------------------------------------------------

def test_list_all(registry: RewardRegistry):
    registry.register(_make_defn("r1"))
    registry.register(_make_defn("r2"))
    all_rewards = registry.list_all()
    names = {r.name for r in all_rewards}
    assert "r1" in names
    assert "r2" in names


def test_list_by_kind(registry: RewardRegistry):
    registry.register(_make_defn("verif", RewardKind.verifiable))
    registry.register(_make_defn("pref", RewardKind.preference))
    verifiable = registry.list_by_kind("verifiable")
    assert all(r.kind == RewardKind.verifiable for r in verifiable)
    assert any(r.name == "verif" for r in verifiable)


def test_list_hard_gates(registry: RewardRegistry):
    registry.register(_make_defn("soft_metric", hard_gate=False))
    registry.register(_make_defn("hard_gate_metric", hard_gate=True))
    gates = registry.list_hard_gates()
    assert all(r.hard_gate for r in gates)
    assert any(r.name == "hard_gate_metric" for r in gates)


# ---------------------------------------------------------------------------
# Deprecate and search
# ---------------------------------------------------------------------------

def test_deprecate_hides_from_list(registry: RewardRegistry):
    registry.register(_make_defn("old_metric"))
    registry.deprecate("old_metric", 1)
    all_rewards = registry.list_all()
    assert not any(r.name == "old_metric" for r in all_rewards)


def test_search_finds_by_name(registry: RewardRegistry):
    registry.register(_make_defn("latency_p99"))
    registry.register(_make_defn("accuracy_top1"))
    results = registry.search("latency")
    assert len(results) >= 1
    assert any("latency" in r.name for r in results)


def test_search_no_match_returns_empty(registry: RewardRegistry):
    registry.register(_make_defn("something"))
    results = registry.search("zzznomatch")
    assert results == []
