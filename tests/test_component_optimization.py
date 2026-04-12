"""Comprehensive tests for component-graph optimization breadth.

Covers:
  - Typed patch bundles (component_patch.py)
  - Component-aware credit assignment (component_credit.py)
  - Component-aware mutations (component_mutation.py)
"""

from __future__ import annotations

import json
import pytest

from shared.canonical_ir import (
    CanonicalAgent,
    ConditionType,
    ContextTransfer,
    EnvironmentConfig,
    GuardrailEnforcement,
    GuardrailSpec,
    GuardrailType,
    HandoffSpec,
    Instruction,
    InstructionRole,
    PolicyEnforcement,
    PolicySpec,
    PolicyType,
    RoutingRuleSpec,
    ToolContract,
    ToolParameter,
)
from optimizer.component_patch import (
    COMPONENT_TYPE_TO_AGENT_FIELD,
    ComponentPatch,
    ComponentRef,
    ComponentType,
    PatchBundle,
    PatchOperation,
    PatchValidationError,
)
from optimizer.component_credit import (
    AttributionConfidence,
    ComponentBlameEntry,
    ComponentCreditAnalyzer,
)
from optimizer.component_mutation import (
    analyze_and_propose,
    apply_and_convert,
    propose_component_patches,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_agent(**overrides) -> CanonicalAgent:
    """Build a minimal CanonicalAgent for testing."""
    defaults = {
        "name": "test_agent",
        "instructions": [
            Instruction(
                role=InstructionRole.SYSTEM,
                content="You are a helpful customer service agent.",
                priority=0,
                label="root",
            )
        ],
        "tools": [
            ToolContract(
                name="catalog",
                description="Search product catalog",
                parameters=[ToolParameter(name="query", type="string", required=True)],
                timeout_ms=5000,
            ),
            ToolContract(
                name="orders_db",
                description="Look up order status",
                timeout_ms=5000,
            ),
        ],
        "routing_rules": [
            RoutingRuleSpec(
                target="orders",
                condition_type=ConditionType.KEYWORD,
                keywords=["order", "shipping"],
            ),
            RoutingRuleSpec(
                target="support",
                condition_type=ConditionType.KEYWORD,
                keywords=["help", "issue"],
            ),
        ],
        "guardrails": [
            GuardrailSpec(
                name="content_filter",
                type=GuardrailType.OUTPUT,
                description="Filter inappropriate content",
                enforcement=GuardrailEnforcement.WARN,
            ),
        ],
        "handoffs": [
            HandoffSpec(
                source="root",
                target="orders",
                condition="order-related query",
                context_transfer=ContextTransfer.SUMMARY,
            ),
        ],
        "policies": [
            PolicySpec(
                name="be_polite",
                type=PolicyType.BEHAVIORAL,
                enforcement=PolicyEnforcement.RECOMMENDED,
            ),
        ],
        "environment": EnvironmentConfig(
            model="gemini-2.0-flash",
            temperature=0.7,
            max_tokens=4096,
        ),
    }
    defaults.update(overrides)
    return CanonicalAgent(**defaults)


def _make_failing_traces(
    failure_type: str = "routing_error",
    count: int = 5,
    total: int = 10,
    **extra,
) -> list[dict]:
    """Build a corpus of traces with a given failure type."""
    traces = []
    for i in range(count):
        trace = {
            "success": False,
            "failure_type": failure_type,
            "error_message": f"test error for {failure_type}",
            **extra,
        }
        traces.append(trace)
    for i in range(total - count):
        traces.append({"success": True})
    return traces


# ====================================================================
# PART 1: Typed Patch Bundles (component_patch.py)
# ====================================================================


class TestComponentRef:
    def test_display_path_with_index(self):
        ref = ComponentRef(ComponentType.tool, index=0)
        assert ref.display_path() == "tools[0]"

    def test_display_path_with_name(self):
        ref = ComponentRef(ComponentType.guardrail, name="safety")
        assert ref.display_path() == "guardrails.safety"

    def test_display_path_environment(self):
        ref = ComponentRef(ComponentType.environment)
        assert ref.display_path() == "environment"

    def test_display_path_with_sub_agent(self):
        ref = ComponentRef(ComponentType.tool, index=0, sub_agent_path=["agent_a"])
        assert ref.display_path() == "agent_a/tools[0]"

    def test_round_trip_serialization(self):
        ref = ComponentRef(ComponentType.routing_rule, index=1, name="orders", sub_agent_path=["x"])
        d = ref.to_dict()
        ref2 = ComponentRef.from_dict(d)
        assert ref2.component_type == ref.component_type
        assert ref2.index == ref.index
        assert ref2.name == ref.name
        assert ref2.sub_agent_path == ref.sub_agent_path


class TestComponentPatch:
    def test_round_trip_serialization(self):
        patch = ComponentPatch(
            operation=PatchOperation.modify,
            ref=ComponentRef(ComponentType.tool, name="catalog"),
            old_value={"timeout_ms": 5000},
            new_value={"timeout_ms": 7000},
            reasoning="increase timeout",
        )
        d = patch.to_dict()
        p2 = ComponentPatch.from_dict(d)
        assert p2.operation == PatchOperation.modify
        assert p2.ref.name == "catalog"
        assert p2.old_value == {"timeout_ms": 5000}
        assert p2.new_value == {"timeout_ms": 7000}


class TestPatchBundleValidation:
    def test_valid_bundle_passes(self):
        bundle = PatchBundle(patches=[
            ComponentPatch(
                operation=PatchOperation.modify,
                ref=ComponentRef(ComponentType.tool, name="catalog"),
                new_value={"timeout_ms": 7000},
            ),
        ])
        assert bundle.validate() == []

    def test_add_without_new_value_fails(self):
        bundle = PatchBundle(patches=[
            ComponentPatch(
                operation=PatchOperation.add,
                ref=ComponentRef(ComponentType.tool),
                new_value=None,
            ),
        ])
        errors = bundle.validate()
        assert len(errors) == 1
        assert "new_value" in errors[0].error

    def test_remove_environment_fails(self):
        bundle = PatchBundle(patches=[
            ComponentPatch(
                operation=PatchOperation.remove,
                ref=ComponentRef(ComponentType.environment),
            ),
        ])
        errors = bundle.validate()
        assert len(errors) == 1
        assert "environment" in errors[0].error

    def test_modify_without_new_value_fails(self):
        bundle = PatchBundle(patches=[
            ComponentPatch(
                operation=PatchOperation.modify,
                ref=ComponentRef(ComponentType.guardrail, name="x"),
                new_value=None,
            ),
        ])
        errors = bundle.validate()
        assert len(errors) == 1

    def test_non_add_list_component_without_index_or_name_fails(self):
        bundle = PatchBundle(patches=[
            ComponentPatch(
                operation=PatchOperation.modify,
                ref=ComponentRef(ComponentType.tool),
                new_value={"timeout_ms": 5000},
            ),
        ])
        errors = bundle.validate()
        assert len(errors) == 1
        assert "index or name" in errors[0].error


class TestPatchBundleApply:
    def test_modify_tool_by_name(self):
        agent = _make_agent()
        bundle = PatchBundle(patches=[
            ComponentPatch(
                operation=PatchOperation.modify,
                ref=ComponentRef(ComponentType.tool, name="catalog"),
                old_value={"timeout_ms": 5000},
                new_value={"timeout_ms": 7000},
            ),
        ])
        new_agent = bundle.apply(agent)
        assert new_agent.tools[0].timeout_ms == 7000
        assert agent.tools[0].timeout_ms == 5000  # original unchanged

    def test_modify_tool_by_index(self):
        agent = _make_agent()
        bundle = PatchBundle(patches=[
            ComponentPatch(
                operation=PatchOperation.modify,
                ref=ComponentRef(ComponentType.tool, index=1),
                new_value={"timeout_ms": 9000},
            ),
        ])
        new_agent = bundle.apply(agent)
        assert new_agent.tools[1].timeout_ms == 9000

    def test_add_guardrail(self):
        agent = _make_agent()
        bundle = PatchBundle(patches=[
            ComponentPatch(
                operation=PatchOperation.add,
                ref=ComponentRef(ComponentType.guardrail),
                new_value={
                    "name": "safety_gate",
                    "type": "both",
                    "enforcement": "block",
                },
            ),
        ])
        new_agent = bundle.apply(agent)
        assert len(new_agent.guardrails) == 2
        assert new_agent.guardrails[1].name == "safety_gate"

    def test_remove_routing_rule_by_index(self):
        agent = _make_agent()
        bundle = PatchBundle(patches=[
            ComponentPatch(
                operation=PatchOperation.remove,
                ref=ComponentRef(ComponentType.routing_rule, index=1),
            ),
        ])
        new_agent = bundle.apply(agent)
        assert len(new_agent.routing_rules) == 1
        assert new_agent.routing_rules[0].target == "orders"

    def test_remove_by_name(self):
        agent = _make_agent()
        bundle = PatchBundle(patches=[
            ComponentPatch(
                operation=PatchOperation.remove,
                ref=ComponentRef(ComponentType.routing_rule, name="support"),
                old_value={"target": "support"},
            ),
        ])
        new_agent = bundle.apply(agent)
        assert len(new_agent.routing_rules) == 1

    def test_modify_environment(self):
        agent = _make_agent()
        bundle = PatchBundle(patches=[
            ComponentPatch(
                operation=PatchOperation.modify,
                ref=ComponentRef(ComponentType.environment),
                old_value={"temperature": 0.7},
                new_value={"temperature": 0.3},
            ),
        ])
        new_agent = bundle.apply(agent)
        assert new_agent.environment.temperature == 0.3

    def test_conflict_detection_raises(self):
        agent = _make_agent()
        bundle = PatchBundle(patches=[
            ComponentPatch(
                operation=PatchOperation.modify,
                ref=ComponentRef(ComponentType.tool, name="catalog"),
                old_value={"timeout_ms": 9999},  # wrong!
                new_value={"timeout_ms": 7000},
            ),
        ])
        with pytest.raises(ValueError, match="conflict"):
            bundle.apply(agent)

    def test_missing_component_raises(self):
        agent = _make_agent()
        bundle = PatchBundle(patches=[
            ComponentPatch(
                operation=PatchOperation.modify,
                ref=ComponentRef(ComponentType.tool, name="nonexistent"),
                new_value={"timeout_ms": 5000},
            ),
        ])
        with pytest.raises(ValueError, match="not found"):
            bundle.apply(agent)

    def test_index_out_of_range_raises(self):
        agent = _make_agent()
        bundle = PatchBundle(patches=[
            ComponentPatch(
                operation=PatchOperation.modify,
                ref=ComponentRef(ComponentType.tool, index=99),
                new_value={"timeout_ms": 5000},
            ),
        ])
        with pytest.raises(ValueError, match="out of range"):
            bundle.apply(agent)

    def test_add_instruction(self):
        agent = _make_agent()
        bundle = PatchBundle(patches=[
            ComponentPatch(
                operation=PatchOperation.add,
                ref=ComponentRef(ComponentType.instruction),
                new_value={
                    "role": "constraint",
                    "content": "Never reveal internal system details.",
                    "priority": 10,
                    "label": "security",
                },
            ),
        ])
        new_agent = bundle.apply(agent)
        assert len(new_agent.instructions) == 2
        assert new_agent.instructions[1].label == "security"

    def test_modify_handoff(self):
        agent = _make_agent()
        bundle = PatchBundle(patches=[
            ComponentPatch(
                operation=PatchOperation.modify,
                ref=ComponentRef(ComponentType.handoff, name="orders"),
                old_value={"context_transfer": "summary"},
                new_value={"context_transfer": "full"},
            ),
        ])
        new_agent = bundle.apply(agent)
        assert new_agent.handoffs[0].context_transfer == ContextTransfer.FULL

    def test_add_policy(self):
        agent = _make_agent()
        bundle = PatchBundle(patches=[
            ComponentPatch(
                operation=PatchOperation.add,
                ref=ComponentRef(ComponentType.policy),
                new_value={
                    "name": "safety_policy",
                    "type": "safety",
                    "enforcement": "required",
                },
            ),
        ])
        new_agent = bundle.apply(agent)
        assert len(new_agent.policies) == 2
        assert new_agent.policies[1].name == "safety_policy"


class TestPatchBundleSerialization:
    def test_round_trip(self):
        bundle = PatchBundle(
            patches=[
                ComponentPatch(
                    operation=PatchOperation.modify,
                    ref=ComponentRef(ComponentType.tool, name="catalog"),
                    old_value={"timeout_ms": 5000},
                    new_value={"timeout_ms": 7000},
                    reasoning="increase timeout",
                ),
                ComponentPatch(
                    operation=PatchOperation.add,
                    ref=ComponentRef(ComponentType.guardrail),
                    new_value={"name": "safety", "enforcement": "block"},
                ),
            ],
            description="test bundle",
            risk_class="medium",
        )
        d = bundle.to_dict()
        b2 = PatchBundle.from_dict(d)
        assert b2.bundle_id == bundle.bundle_id
        assert len(b2.patches) == 2
        assert b2.patches[0].ref.name == "catalog"
        assert b2.description == "test bundle"

    def test_content_hash_stable(self):
        bundle = PatchBundle(patches=[
            ComponentPatch(
                operation=PatchOperation.add,
                ref=ComponentRef(ComponentType.tool),
                new_value={"name": "x"},
            ),
        ])
        h1 = bundle.content_hash
        h2 = bundle.content_hash
        assert h1 == h2

    def test_to_diff_hunks(self):
        bundle = PatchBundle(patches=[
            ComponentPatch(
                operation=PatchOperation.modify,
                ref=ComponentRef(ComponentType.tool, name="catalog"),
                old_value={"timeout_ms": 5000},
                new_value={"timeout_ms": 7000},
            ),
        ])
        hunks = bundle.to_diff_hunks()
        assert len(hunks) == 1
        assert hunks[0]["surface"] == "tools.catalog"
        assert "5000" in hunks[0]["old_value"]
        assert "7000" in hunks[0]["new_value"]

    def test_touched_surfaces(self):
        bundle = PatchBundle(patches=[
            ComponentPatch(
                operation=PatchOperation.modify,
                ref=ComponentRef(ComponentType.tool, name="x"),
                new_value={"timeout_ms": 5000},
            ),
            ComponentPatch(
                operation=PatchOperation.add,
                ref=ComponentRef(ComponentType.guardrail),
                new_value={"name": "y"},
            ),
        ])
        assert set(bundle.touched_surfaces) == {"tool", "guardrail"}

    def test_preview(self):
        bundle = PatchBundle(patches=[
            ComponentPatch(
                operation=PatchOperation.add,
                ref=ComponentRef(ComponentType.policy),
                new_value={"name": "safety"},
                reasoning="add safety policy",
            ),
        ])
        preview = bundle.preview()
        assert len(preview) == 1
        assert preview[0]["operation"] == "add"
        assert "add safety policy" in preview[0]["reasoning"]


# ====================================================================
# PART 2: Component Credit Assignment (component_credit.py)
# ====================================================================


class TestComponentCreditAnalyzer:
    def test_routing_error_blames_routing_rule(self):
        traces = _make_failing_traces("routing_error", count=3, total=10)
        analyzer = ComponentCreditAnalyzer()
        entries = analyzer.analyze(traces)
        assert len(entries) > 0
        assert entries[0].component_type == ComponentType.routing_rule

    def test_tool_failure_blames_tool(self):
        traces = _make_failing_traces("tool_failure", count=4, total=10)
        analyzer = ComponentCreditAnalyzer()
        entries = analyzer.analyze(traces)
        assert any(e.component_type == ComponentType.tool for e in entries)

    def test_safety_violation_blames_guardrail_and_policy(self):
        traces = _make_failing_traces("safety_violation", count=3, total=10)
        analyzer = ComponentCreditAnalyzer()
        entries = analyzer.analyze(traces)
        component_types = {e.component_type for e in entries}
        assert ComponentType.guardrail in component_types or ComponentType.policy in component_types

    def test_hallucination_blames_instruction(self):
        traces = _make_failing_traces("hallucination", count=2, total=10)
        analyzer = ComponentCreditAnalyzer()
        entries = analyzer.analyze(traces)
        assert any(e.component_type == ComponentType.instruction for e in entries)

    def test_explicit_failed_tool_annotation(self):
        traces = [
            {"success": False, "failure_type": "tool_failure", "failed_tool": "catalog"},
            {"success": True},
        ]
        analyzer = ComponentCreditAnalyzer()
        entries = analyzer.analyze(traces)
        assert len(entries) == 1
        assert entries[0].component_type == ComponentType.tool
        assert entries[0].component_name == "catalog"
        assert entries[0].confidence == AttributionConfidence.HIGH

    def test_explicit_failed_guardrail_annotation(self):
        traces = [
            {"success": False, "failure_type": "safety_violation", "failed_guardrail": "content_filter"},
            {"success": True},
        ]
        analyzer = ComponentCreditAnalyzer()
        entries = analyzer.analyze(traces)
        assert len(entries) == 1
        assert entries[0].component_type == ComponentType.guardrail
        assert entries[0].component_name == "content_filter"

    def test_explicit_blamed_component_annotation(self):
        traces = [
            {
                "success": False,
                "blamed_component": {"type": "routing_rule", "name": "orders"},
            },
            {"success": True},
        ]
        analyzer = ComponentCreditAnalyzer()
        entries = analyzer.analyze(traces)
        assert len(entries) == 1
        assert entries[0].component_type == ComponentType.routing_rule
        assert entries[0].component_name == "orders"
        assert entries[0].confidence == AttributionConfidence.HIGH

    def test_empty_traces_returns_empty(self):
        analyzer = ComponentCreditAnalyzer()
        assert analyzer.analyze([]) == []

    def test_all_success_returns_empty(self):
        traces = [{"success": True} for _ in range(5)]
        analyzer = ComponentCreditAnalyzer()
        assert analyzer.analyze(traces) == []

    def test_unknown_failure_type_falls_back_to_instruction(self):
        traces = [{"success": False, "failure_type": "unknown"}]
        analyzer = ComponentCreditAnalyzer()
        entries = analyzer.analyze(traces)
        assert len(entries) > 0
        assert entries[0].component_type == ComponentType.instruction
        assert entries[0].confidence == AttributionConfidence.HEURISTIC

    def test_timeout_blames_environment_and_tool(self):
        traces = _make_failing_traces("timeout", count=5, total=10)
        analyzer = ComponentCreditAnalyzer()
        entries = analyzer.analyze(traces)
        component_types = {e.component_type for e in entries}
        assert ComponentType.environment in component_types or ComponentType.tool in component_types

    def test_agent_components_refine_tool_name(self):
        traces = [
            {
                "success": False,
                "failure_type": "tool_failure",
                "tool_call_name": "orders_db",
            },
        ]
        analyzer = ComponentCreditAnalyzer()
        entries = analyzer.analyze(
            traces,
            agent_components={"tool": ["catalog", "orders_db"]},
        )
        tool_entries = [e for e in entries if e.component_type == ComponentType.tool]
        assert any(e.component_name == "orders_db" for e in tool_entries)

    def test_impact_score_reflects_severity(self):
        safety_traces = _make_failing_traces("safety_violation", count=5, total=10)
        routing_traces = _make_failing_traces("routing_error", count=5, total=10)
        analyzer = ComponentCreditAnalyzer()
        safety_entries = analyzer.analyze(safety_traces)
        routing_entries = analyzer.analyze(routing_traces)
        safety_max = max(e.impact_score for e in safety_entries)
        routing_max = max(e.impact_score for e in routing_entries)
        assert safety_max > routing_max

    def test_serialization_round_trip(self):
        entry = ComponentBlameEntry(
            component_type=ComponentType.tool,
            component_name="catalog",
            failure_count=3,
            failure_rate=0.3,
            failure_types=["tool_failure"],
            impact_score=0.27,
            confidence=AttributionConfidence.HIGH,
            evidence=["explicit failed_tool: catalog"],
        )
        d = entry.to_dict()
        e2 = ComponentBlameEntry.from_dict(d)
        assert e2.component_type == ComponentType.tool
        assert e2.component_name == "catalog"
        assert e2.confidence == AttributionConfidence.HIGH

    def test_infinite_loop_blames_routing_and_handoff(self):
        traces = _make_failing_traces("infinite_loop", count=3, total=10)
        analyzer = ComponentCreditAnalyzer()
        entries = analyzer.analyze(traces)
        types = {e.component_type for e in entries}
        assert ComponentType.routing_rule in types or ComponentType.handoff in types

    def test_expected_specialist_refines_routing(self):
        traces = [
            {
                "success": False,
                "failure_type": "routing_error",
                "expected_specialist": "orders",
            },
        ]
        analyzer = ComponentCreditAnalyzer()
        entries = analyzer.analyze(traces)
        routing_entries = [e for e in entries if e.component_type == ComponentType.routing_rule]
        assert any(e.component_name == "orders" for e in routing_entries)


# ====================================================================
# PART 3: Component-Aware Mutations (component_mutation.py)
# ====================================================================


class TestProposeComponentPatches:
    def test_routing_error_produces_routing_patches(self):
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.routing_rule,
            component_name="orders",
            failure_count=3,
            failure_rate=0.3,
            failure_types=["routing_error"],
            impact_score=0.33,
            confidence=AttributionConfidence.HIGH,
        )]
        bundle = propose_component_patches(agent, blame)
        assert len(bundle.patches) > 0
        assert any(p.ref.component_type == ComponentType.routing_rule for p in bundle.patches)

    def test_tool_failure_produces_tool_patches(self):
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.tool,
            component_name="catalog",
            failure_count=4,
            failure_rate=0.4,
            failure_types=["tool_failure"],
            impact_score=0.36,
            confidence=AttributionConfidence.HIGH,
        )]
        bundle = propose_component_patches(agent, blame)
        tool_patches = [p for p in bundle.patches if p.ref.component_type == ComponentType.tool]
        assert len(tool_patches) > 0
        assert any("timeout" in p.reasoning.lower() for p in tool_patches)

    def test_safety_violation_produces_guardrail_patches(self):
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.guardrail,
            component_name="content_filter",
            failure_count=3,
            failure_rate=0.3,
            failure_types=["safety_violation"],
            impact_score=0.45,
            confidence=AttributionConfidence.MEDIUM,
        )]
        bundle = propose_component_patches(agent, blame)
        guardrail_patches = [p for p in bundle.patches if p.ref.component_type == ComponentType.guardrail]
        assert len(guardrail_patches) > 0
        assert bundle.risk_class == "high"

    def test_hallucination_produces_instruction_patches(self):
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.instruction,
            failure_count=2,
            failure_rate=0.2,
            failure_types=["hallucination"],
            impact_score=0.26,
            confidence=AttributionConfidence.MEDIUM,
        )]
        bundle = propose_component_patches(agent, blame)
        instruction_patches = [p for p in bundle.patches if p.ref.component_type == ComponentType.instruction]
        assert len(instruction_patches) > 0
        assert any("hallucination" in p.reasoning.lower() for p in instruction_patches)

    def test_handoff_failure_produces_handoff_patches(self):
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.handoff,
            component_name="orders",
            failure_count=2,
            failure_rate=0.2,
            failure_types=["infinite_loop"],
            impact_score=0.24,
            confidence=AttributionConfidence.MEDIUM,
        )]
        bundle = propose_component_patches(agent, blame)
        handoff_patches = [p for p in bundle.patches if p.ref.component_type == ComponentType.handoff]
        assert len(handoff_patches) > 0

    def test_policy_safety_failure_adds_policy(self):
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.policy,
            failure_count=3,
            failure_rate=0.3,
            failure_types=["safety_violation"],
            impact_score=0.45,
            confidence=AttributionConfidence.MEDIUM,
        )]
        bundle = propose_component_patches(agent, blame)
        policy_patches = [p for p in bundle.patches if p.ref.component_type == ComponentType.policy]
        assert len(policy_patches) > 0

    def test_environment_timeout_produces_patches(self):
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.environment,
            failure_count=5,
            failure_rate=0.5,
            failure_types=["timeout"],
            impact_score=0.5,
            confidence=AttributionConfidence.LOW,
        )]
        bundle = propose_component_patches(agent, blame)
        env_patches = [p for p in bundle.patches if p.ref.component_type == ComponentType.environment]
        assert len(env_patches) > 0

    def test_past_surfaces_are_skipped(self):
        agent = _make_agent()
        blame = [
            ComponentBlameEntry(
                component_type=ComponentType.routing_rule,
                failure_count=3, failure_rate=0.3,
                failure_types=["routing_error"], impact_score=0.33,
            ),
            ComponentBlameEntry(
                component_type=ComponentType.tool,
                component_name="catalog",
                failure_count=2, failure_rate=0.2,
                failure_types=["tool_failure"], impact_score=0.18,
            ),
        ]
        bundle = propose_component_patches(
            agent, blame, past_bundle_surfaces=["routing_rule"]
        )
        assert not any(p.ref.component_type == ComponentType.routing_rule for p in bundle.patches)
        assert any(p.ref.component_type == ComponentType.tool for p in bundle.patches)

    def test_low_impact_entries_skipped(self):
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.tool,
            failure_count=0, failure_rate=0.0,
            failure_types=[], impact_score=0.0,
        )]
        bundle = propose_component_patches(agent, blame)
        assert len(bundle.patches) == 0

    def test_max_patches_respected(self):
        agent = _make_agent()
        blame = [
            ComponentBlameEntry(
                component_type=ComponentType.routing_rule,
                component_name="orders",
                failure_count=5, failure_rate=0.5,
                failure_types=["routing_error"], impact_score=0.55,
            ),
            ComponentBlameEntry(
                component_type=ComponentType.tool,
                component_name="catalog",
                failure_count=4, failure_rate=0.4,
                failure_types=["tool_failure"], impact_score=0.36,
            ),
            ComponentBlameEntry(
                component_type=ComponentType.guardrail,
                failure_count=3, failure_rate=0.3,
                failure_types=["safety_violation"], impact_score=0.45,
            ),
        ]
        bundle = propose_component_patches(agent, blame, max_patches=2)
        assert len(bundle.patches) <= 2

    def test_empty_blame_produces_empty_bundle(self):
        agent = _make_agent()
        bundle = propose_component_patches(agent, [])
        assert len(bundle.patches) == 0

    def test_no_routing_rules_adds_fallback(self):
        agent = _make_agent(routing_rules=[])
        blame = [ComponentBlameEntry(
            component_type=ComponentType.routing_rule,
            failure_count=3, failure_rate=0.3,
            failure_types=["routing_error"], impact_score=0.33,
        )]
        bundle = propose_component_patches(agent, blame)
        add_patches = [p for p in bundle.patches if p.operation == PatchOperation.add]
        assert len(add_patches) > 0
        assert any(p.new_value and p.new_value.get("fallback") for p in add_patches)

    def test_no_guardrails_adds_safety_gate(self):
        agent = _make_agent(guardrails=[])
        blame = [ComponentBlameEntry(
            component_type=ComponentType.guardrail,
            failure_count=3, failure_rate=0.3,
            failure_types=["safety_violation"], impact_score=0.45,
        )]
        bundle = propose_component_patches(agent, blame)
        add_patches = [p for p in bundle.patches if p.operation == PatchOperation.add]
        assert len(add_patches) > 0
        assert any(p.new_value and p.new_value.get("name") == "safety_gate" for p in add_patches)


class TestAnalyzeAndPropose:
    def test_end_to_end_routing_error(self):
        agent = _make_agent()
        traces = _make_failing_traces(
            "routing_error", count=3, total=10,
            expected_specialist="orders",
        )
        blame, bundle = analyze_and_propose(agent, traces)
        assert len(blame) > 0
        assert blame[0].component_type == ComponentType.routing_rule
        assert len(bundle.patches) > 0

    def test_end_to_end_tool_failure(self):
        agent = _make_agent()
        traces = _make_failing_traces(
            "tool_failure", count=4, total=10,
            failed_tool="catalog",
        )
        blame, bundle = analyze_and_propose(agent, traces)
        tool_blame = [e for e in blame if e.component_type == ComponentType.tool]
        assert any(e.component_name == "catalog" for e in tool_blame)
        assert len(bundle.patches) > 0

    def test_end_to_end_safety_violation(self):
        agent = _make_agent()
        traces = _make_failing_traces("safety_violation", count=5, total=10)
        blame, bundle = analyze_and_propose(agent, traces)
        assert len(blame) > 0
        assert len(bundle.patches) > 0

    def test_end_to_end_with_all_success(self):
        agent = _make_agent()
        traces = [{"success": True} for _ in range(10)]
        blame, bundle = analyze_and_propose(agent, traces)
        assert len(blame) == 0
        assert len(bundle.patches) == 0


class TestApplyAndConvert:
    def test_produces_valid_config_dict(self):
        agent = _make_agent()
        bundle = PatchBundle(patches=[
            ComponentPatch(
                operation=PatchOperation.modify,
                ref=ComponentRef(ComponentType.tool, name="catalog"),
                old_value={"timeout_ms": 5000},
                new_value={"timeout_ms": 7000},
            ),
        ])
        new_agent, config_dict = apply_and_convert(agent, bundle)
        assert new_agent.tools[0].timeout_ms == 7000
        assert isinstance(config_dict, dict)
        assert "tools_config" in config_dict or "prompts" in config_dict

    def test_applied_bundle_round_trips_through_config(self):
        agent = _make_agent()
        bundle = PatchBundle(patches=[
            ComponentPatch(
                operation=PatchOperation.add,
                ref=ComponentRef(ComponentType.guardrail),
                new_value={
                    "name": "new_guard",
                    "type": "output",
                    "enforcement": "block",
                    "description": "Block bad content",
                },
            ),
        ])
        new_agent, config_dict = apply_and_convert(agent, bundle)
        assert len(new_agent.guardrails) == 2
        guardrails_in_config = config_dict.get("guardrails", [])
        assert len(guardrails_in_config) == 2


# ====================================================================
# PART 4: Integration / Edge Cases
# ====================================================================


class TestIntegration:
    def test_full_pipeline_routing_fix(self):
        """Full pipeline: traces -> blame -> patches -> apply -> config."""
        agent = _make_agent()
        traces = _make_failing_traces(
            "routing_error", count=4, total=10,
            expected_specialist="orders",
        )
        blame, bundle = analyze_and_propose(agent, traces)

        assert len(bundle.validate()) == 0

        new_agent, config = apply_and_convert(agent, bundle)
        assert new_agent.name == agent.name
        assert isinstance(config, dict)

    def test_full_pipeline_safety_fix(self):
        """Safety violations produce guardrail+policy changes."""
        agent = _make_agent(guardrails=[], policies=[])
        traces = _make_failing_traces("safety_violation", count=6, total=10)
        blame, bundle = analyze_and_propose(agent, traces)

        assert len(bundle.patches) > 0
        new_agent = bundle.apply(agent)
        assert len(new_agent.guardrails) > 0 or len(new_agent.policies) > 0

    def test_external_agent_serialization(self):
        """PatchBundle serializes for external coding agent consumption."""
        agent = _make_agent()
        traces = _make_failing_traces("tool_failure", count=3, total=10)
        blame, bundle = analyze_and_propose(agent, traces)

        serialized = json.dumps(bundle.to_dict())
        deserialized = PatchBundle.from_dict(json.loads(serialized))
        assert deserialized.bundle_id == bundle.bundle_id
        assert len(deserialized.patches) == len(bundle.patches)

        if bundle.patches:
            new_agent = deserialized.apply(agent)
            assert new_agent.name == agent.name

    def test_multiple_failure_types_produce_diverse_patches(self):
        """Mixed failures produce patches across multiple component types."""
        agent = _make_agent()
        traces = (
            _make_failing_traces("routing_error", count=2, total=0)
            + _make_failing_traces("tool_failure", count=2, total=0)
            + _make_failing_traces("safety_violation", count=2, total=0)
            + [{"success": True} for _ in range(4)]
        )
        blame, bundle = analyze_and_propose(agent, traces)
        surfaces = set(bundle.touched_surfaces)
        assert len(surfaces) >= 2

    def test_sub_agent_path_traversal(self):
        """Patches can target components inside sub-agents."""
        agent = _make_agent(sub_agents=[
            CanonicalAgent(
                name="specialist_a",
                tools=[ToolContract(name="internal_tool", timeout_ms=3000)],
            ),
        ])
        bundle = PatchBundle(patches=[
            ComponentPatch(
                operation=PatchOperation.modify,
                ref=ComponentRef(
                    ComponentType.tool,
                    name="internal_tool",
                    sub_agent_path=["specialist_a"],
                ),
                old_value={"timeout_ms": 3000},
                new_value={"timeout_ms": 6000},
            ),
        ])
        new_agent = bundle.apply(agent)
        assert new_agent.sub_agents[0].tools[0].timeout_ms == 6000
        assert agent.sub_agents[0].tools[0].timeout_ms == 3000

    def test_empty_agent_handles_gracefully(self):
        """Empty agent + no traces = empty result."""
        agent = CanonicalAgent()
        traces: list[dict] = []
        blame, bundle = analyze_and_propose(agent, traces)
        assert blame == []
        assert len(bundle.patches) == 0
