"""Tests for tool contracts and replay mode mapping."""

from __future__ import annotations

import pytest

from core.types import ReplayMode, ToolContractVersion
from evals.side_effects import (
    SideEffectClass,
    ToolClassification,
    ToolClassificationRegistry,
    ToolContract,
    ToolContractRegistry,
    side_effect_to_replay_mode,
)


# ---------------------------------------------------------------------------
# side_effect_to_replay_mode tests
# ---------------------------------------------------------------------------


def test_side_effect_to_replay_mode_pure():
    mode = side_effect_to_replay_mode(SideEffectClass.pure)
    assert mode == ReplayMode.deterministic_stub


def test_side_effect_to_replay_mode_read_only():
    mode = side_effect_to_replay_mode(SideEffectClass.read_only_external)
    assert mode == ReplayMode.recorded_stub_with_freshness


def test_side_effect_to_replay_mode_write_reversible():
    mode = side_effect_to_replay_mode(SideEffectClass.write_external_reversible)
    assert mode == ReplayMode.live_sandbox_clone


def test_side_effect_to_replay_mode_write_irreversible():
    mode = side_effect_to_replay_mode(SideEffectClass.write_external_irreversible)
    assert mode == ReplayMode.forbidden


# ---------------------------------------------------------------------------
# ToolContract tests
# ---------------------------------------------------------------------------


def test_tool_contract_creation():
    contract = ToolContract(
        tool_name="catalog",
        side_effect=SideEffectClass.read_only_external,
        replay_mode=ReplayMode.recorded_stub_with_freshness,
        description="Read product catalog",
    )

    assert contract.tool_name == "catalog"
    assert contract.side_effect == SideEffectClass.read_only_external
    assert contract.replay_mode == ReplayMode.recorded_stub_with_freshness


def test_tool_contract_can_auto_replay_deterministic():
    contract = ToolContract(
        tool_name="faq",
        side_effect=SideEffectClass.pure,
        replay_mode=ReplayMode.deterministic_stub,
    )

    assert contract.can_auto_replay is True


def test_tool_contract_can_auto_replay_freshness():
    contract = ToolContract(
        tool_name="catalog",
        side_effect=SideEffectClass.read_only_external,
        replay_mode=ReplayMode.recorded_stub_with_freshness,
    )

    assert contract.can_auto_replay is True


def test_tool_contract_can_auto_replay_simulator():
    contract = ToolContract(
        tool_name="test_tool",
        side_effect=SideEffectClass.read_only_external,
        replay_mode=ReplayMode.simulator,
    )

    assert contract.can_auto_replay is True


def test_tool_contract_cannot_auto_replay_live():
    contract = ToolContract(
        tool_name="orders_db",
        side_effect=SideEffectClass.write_external_reversible,
        replay_mode=ReplayMode.live_sandbox_clone,
    )

    assert contract.can_auto_replay is False


def test_tool_contract_cannot_auto_replay_forbidden():
    contract = ToolContract(
        tool_name="payment",
        side_effect=SideEffectClass.write_external_irreversible,
        replay_mode=ReplayMode.forbidden,
    )

    assert contract.can_auto_replay is False


def test_tool_contract_to_contract_version():
    contract = ToolContract(
        tool_name="catalog",
        side_effect=SideEffectClass.read_only_external,
        replay_mode=ReplayMode.recorded_stub_with_freshness,
        validator="schema_v1",
        sandbox_policy={"isolated": True},
        freshness_window_seconds=3600,
        description="Product catalog",
    )

    version = contract.to_contract_version()

    assert isinstance(version, ToolContractVersion)
    assert version.tool_name == "catalog"
    assert version.side_effect_class == "read_only_external"
    assert version.replay_mode == ReplayMode.recorded_stub_with_freshness
    assert version.validator == "schema_v1"
    assert version.freshness_window_seconds == 3600


def test_tool_contract_to_contract_version_round_trip():
    contract = ToolContract(
        tool_name="test",
        side_effect=SideEffectClass.pure,
        replay_mode=ReplayMode.deterministic_stub,
        description="Test tool",
    )

    version = contract.to_contract_version()

    assert version.tool_name == contract.tool_name
    assert version.replay_mode == contract.replay_mode


# ---------------------------------------------------------------------------
# ToolContractRegistry tests
# ---------------------------------------------------------------------------


def test_tool_contract_registry_register_and_get():
    registry = ToolContractRegistry()
    contract = ToolContract(
        tool_name="catalog",
        side_effect=SideEffectClass.read_only_external,
        replay_mode=ReplayMode.recorded_stub_with_freshness,
    )

    registry.register_contract(contract)
    retrieved = registry.get_contract("catalog")

    assert retrieved is not None
    assert retrieved.tool_name == "catalog"


def test_tool_contract_registry_get_by_replay_mode():
    registry = ToolContractRegistry()
    registry.register_contract(
        ToolContract(
            tool_name="faq",
            side_effect=SideEffectClass.pure,
            replay_mode=ReplayMode.deterministic_stub,
        )
    )
    registry.register_contract(
        ToolContract(
            tool_name="catalog",
            side_effect=SideEffectClass.read_only_external,
            replay_mode=ReplayMode.recorded_stub_with_freshness,
        )
    )
    registry.register_contract(
        ToolContract(
            tool_name="orders_db",
            side_effect=SideEffectClass.write_external_reversible,
            replay_mode=ReplayMode.live_sandbox_clone,
        )
    )

    deterministic = registry.get_by_replay_mode(ReplayMode.deterministic_stub)
    freshness = registry.get_by_replay_mode(ReplayMode.recorded_stub_with_freshness)

    assert len(deterministic) == 1
    assert deterministic[0].tool_name == "faq"
    assert len(freshness) == 1
    assert freshness[0].tool_name == "catalog"


def test_tool_contract_registry_from_classification_registry():
    old_registry = ToolClassificationRegistry()
    old_registry.register(
        tool_name="faq",
        side_effect=SideEffectClass.pure,
        description="FAQ lookup",
    )
    old_registry.register(
        tool_name="catalog",
        side_effect=SideEffectClass.read_only_external,
        description="Product catalog",
    )

    new_registry = ToolContractRegistry.from_classification_registry(old_registry)

    faq = new_registry.get_contract("faq")
    catalog = new_registry.get_contract("catalog")

    assert faq is not None
    assert faq.replay_mode == ReplayMode.deterministic_stub
    assert catalog is not None
    assert catalog.replay_mode == ReplayMode.recorded_stub_with_freshness


def test_tool_contract_registry_backward_compat():
    registry = ToolContractRegistry()
    contract = ToolContract(
        tool_name="catalog",
        side_effect=SideEffectClass.read_only_external,
        replay_mode=ReplayMode.recorded_stub_with_freshness,
        description="Product catalog",
    )

    registry.register_contract(contract)

    # Should work with old ToolClassification API
    classification = registry.get("catalog")
    assert classification is not None
    assert classification.tool_name == "catalog"
    assert classification.can_auto_replay is True
