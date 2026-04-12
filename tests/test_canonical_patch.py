"""Tests for canonical component patch bundles."""

from __future__ import annotations

from shared.canonical_ir import (
    CanonicalAgent,
    GuardrailSpec,
    HandoffSpec,
    Instruction,
    PolicySpec,
    PolicyType,
    RoutingRuleSpec,
    ToolContract,
)
from shared.canonical_ir_convert import from_config_dict
from shared.canonical_patch import (
    ComponentPatchOperation,
    ComponentReference,
    TypedPatchBundle,
    iter_component_references,
    patch_bundle_to_config,
    validate_patch_bundle,
)


def test_component_reference_inventory_includes_nominal_surfaces_and_callbacks() -> None:
    """The optimizer needs addressable components beyond generic config buckets."""
    agent = CanonicalAgent(
        name="root",
        instructions=[Instruction(content="Route and answer.", label="root", priority=100)],
        tools=[ToolContract(name="catalog", description="Search products")],
        routing_rules=[RoutingRuleSpec(target="support", keywords=["help"])],
        guardrails=[GuardrailSpec(name="harm_guard", description="Block harmful requests")],
        policies=[
            PolicySpec(
                name="before_tool_callback",
                type=PolicyType.OPERATIONAL,
                description="Inspect tool calls before execution.",
                metadata={"callback_type": "before_tool"},
            )
        ],
        handoffs=[HandoffSpec(source="root", target="support", condition="Needs help")],
        sub_agents=[CanonicalAgent(name="support", instructions=[Instruction(content="Help users.")])],
    )

    refs = list(iter_component_references(agent))
    by_surface = {(ref.component_type, ref.name) for ref in refs}

    assert ("instruction", "root") in by_surface
    assert ("tool_contract", "catalog") in by_surface
    assert ("routing_rule", "support") in by_surface
    assert ("guardrail", "harm_guard") in by_surface
    assert ("callback", "before_tool_callback") in by_surface
    assert ("handoff", "root->support") in by_surface
    assert ("sub_agent", "support") in by_surface


def test_patch_bundle_updates_routing_rule_through_config_bridge_without_losing_config() -> None:
    """Typed patch application should target canonical components and preserve legacy config."""
    current_config = {
        "model": "gpt-4",
        "prompts": {"root": "You are helpful."},
        "routing": {"rules": [{"specialist": "support", "keywords": ["help"], "patterns": []}]},
        "thresholds": {"max_turns": 12},
    }
    agent = from_config_dict(current_config, name="root")
    support_rule = next(
        ref
        for ref in iter_component_references(agent)
        if ref.component_type == "routing_rule" and ref.name == "support"
    )
    bundle = TypedPatchBundle(
        bundle_id="bundle-routing-support",
        title="Teach support routing about refunds",
        operations=[
            ComponentPatchOperation(
                op="append",
                component=support_rule,
                field_path="keywords",
                value=["refund", "checkout"],
                rationale="Refund failures were routed away from support.",
            )
        ],
        source="unit-test",
    )

    updated = patch_bundle_to_config(current_config, bundle, agent_name="root")

    assert updated["routing"]["rules"][0]["keywords"] == ["help", "refund", "checkout"]
    assert updated["thresholds"] == {"max_turns": 12}
    assert updated["model"] == "gpt-4"


def test_patch_bundle_validation_reports_missing_component() -> None:
    """Bundle validation should fail before a proposal can mutate an unknown component."""
    agent = CanonicalAgent(name="root", routing_rules=[RoutingRuleSpec(target="support")])
    missing_component = ComponentReference(
        component_id="root:routing_rule:missing",
        component_type="routing_rule",
        name="missing",
        path="/routing_rules/99",
    )
    bundle = TypedPatchBundle(
        bundle_id="bundle-invalid",
        title="Invalid route update",
        operations=[
            ComponentPatchOperation(
                op="update",
                component=missing_component,
                field_path="keywords",
                value=["refund"],
            )
        ],
    )

    validation = validate_patch_bundle(agent, bundle)

    assert not validation.valid
    assert validation.errors
    assert "missing" in validation.errors[0].lower()
