"""Unit tests for the mutation registry and operators."""

from __future__ import annotations

import copy

from optimizer.mutations import (
    MutationRegistry,
    MutationSurface,
    RiskClass,
    create_default_registry,
)
from optimizer.mutations_google import register_google_operators
from optimizer.mutations_topology import register_topology_operators


def test_create_default_registry_has_13_operators() -> None:
    """Default registry ships with exactly 13 first-party operators."""
    registry = create_default_registry()
    assert len(registry.list_all()) == 13


def test_list_by_surface_filters_correctly() -> None:
    """list_by_surface should return only operators targeting the instruction surface."""
    registry = create_default_registry()
    instruction_ops = registry.list_by_surface(MutationSurface.instruction)
    assert len(instruction_ops) >= 1
    assert all(op.surface == MutationSurface.instruction for op in instruction_ops)
    # Verify the instruction_rewrite operator is in the filtered list
    names = [op.name for op in instruction_ops]
    assert "instruction_rewrite" in names


def test_list_by_risk_filters_correctly() -> None:
    """list_by_risk with max_risk=medium should exclude high and critical operators."""
    registry = create_default_registry()
    filtered = registry.list_by_risk(RiskClass.medium)
    assert len(filtered) > 0
    for op in filtered:
        assert op.risk_class <= RiskClass.medium
    # model_swap is high risk — should be excluded
    names = [op.name for op in filtered]
    assert "model_swap" not in names
    assert "callback_patch" not in names


def test_list_autodeploy_excludes_high_risk() -> None:
    """list_autodeploy should only return operators with supports_autodeploy=True."""
    registry = create_default_registry()
    autodeploy_ops = registry.list_autodeploy()
    assert len(autodeploy_ops) > 0
    for op in autodeploy_ops:
        assert op.supports_autodeploy is True
    names = [op.name for op in autodeploy_ops]
    # High-risk operators should not support autodeploy
    assert "model_swap" not in names
    assert "callback_patch" not in names
    assert "tool_description_edit" not in names


def test_operator_apply_creates_new_config() -> None:
    """instruction_rewrite apply should produce a config with the new prompt text."""
    registry = create_default_registry()
    op = registry.get("instruction_rewrite")
    assert op is not None

    original = {"prompts": {"root": "Be helpful."}}
    result = op.apply(original, {"target": "root", "text": "Be very helpful and concise."})

    assert result["prompts"]["root"] == "Be very helpful and concise."
    # Original should be unchanged
    assert original["prompts"]["root"] == "Be helpful."


def test_operator_apply_does_not_mutate_input() -> None:
    """Apply functions should deepcopy — the input config must remain unchanged."""
    registry = create_default_registry()
    op = registry.get("few_shot_edit")
    assert op is not None

    original = {"few_shot": {"root": [{"q": "hi", "a": "hello"}]}}
    original_copy = copy.deepcopy(original)

    op.apply(original, {"target": "root", "examples": [{"q": "bye", "a": "goodbye"}]})

    assert original == original_copy


def test_get_unknown_operator_returns_none() -> None:
    """Getting a non-existent operator should return None."""
    registry = create_default_registry()
    assert registry.get("nonexistent_operator") is None


def test_register_duplicate_overwrites() -> None:
    """Registering an operator with the same name should replace the existing one."""
    registry = create_default_registry()
    original_op = registry.get("instruction_rewrite")
    assert original_op is not None
    original_desc = original_op.description

    from optimizer.mutations import MutationOperator

    replacement = MutationOperator(
        name="instruction_rewrite",
        surface=MutationSurface.instruction,
        risk_class=RiskClass.low,
        description="Replacement operator for testing.",
    )
    registry.register(replacement)

    updated = registry.get("instruction_rewrite")
    assert updated is not None
    assert updated.description == "Replacement operator for testing."
    assert updated.description != original_desc
    # Total count should remain 13 (replaced, not added)
    assert len(registry.list_all()) == 13


def test_routing_edit_operator_adds_keywords() -> None:
    """routing_edit operator with action='add' should append a rule to routing.rules."""
    registry = create_default_registry()
    op = registry.get("routing_edit")
    assert op is not None

    original = {"routing": {"rules": [{"keyword": "order", "agent": "orders"}]}}
    new_rule = {"keyword": "billing", "agent": "billing"}
    result = op.apply(original, {"action": "add", "rule": new_rule})

    assert len(result["routing"]["rules"]) == 2
    assert result["routing"]["rules"][1] == new_rule
    # Original unchanged
    assert len(original["routing"]["rules"]) == 1


def test_default_registry_contains_only_ready_operators() -> None:
    """create_default_registry() must only register operators with ready=True."""
    registry = create_default_registry()
    for op in registry.list_all():
        assert op.ready is True, f"Operator '{op.name}' in default registry has ready=False"


def test_google_and_topology_operators_are_not_ready() -> None:
    """Google and topology stub operators must have ready=False."""
    registry = create_default_registry()
    register_google_operators(registry)
    register_topology_operators(registry)

    google_names = {"google_zero_shot_optimize", "google_few_shot_optimize", "google_data_driven_optimize"}
    topology_names = {"detect_transfer_loops", "reduce_unnecessary_parallelism", "add_deterministic_steps"}
    stub_names = google_names | topology_names

    for name in stub_names:
        op = registry.get(name)
        assert op is not None, f"Expected operator '{name}' to be registered"
        assert op.ready is False, f"Stub operator '{name}' should have ready=False"
