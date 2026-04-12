"""Tests for integrated component mutation and credit assignment.

Covers the ported Claude credit analyzer and mutation generators producing
Codex-authoritative TypedPatchBundle/ComponentPatchOperation types.
"""

from __future__ import annotations

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
)
from shared.canonical_ir_convert import from_config_dict, to_config_dict
from shared.canonical_patch import (
    TypedPatchBundle,
    apply_patch_bundle,
    iter_component_references,
    patch_bundle_to_config,
    validate_patch_bundle,
)
from optimizer.component_credit import (
    AttributionConfidence,
    ComponentBlameEntry,
    ComponentCreditAnalyzer,
    ComponentType,
)
from optimizer.component_mutation import (
    analyze_and_propose,
    apply_and_convert,
    propose_component_patches,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_agent(**overrides: object) -> CanonicalAgent:
    defaults: dict = {
        "name": "test_agent",
        "instructions": [
            Instruction(role=InstructionRole.SYSTEM, content="You are a helpful assistant.", priority=100, label="root"),
        ],
        "tools": [
            ToolContract(name="catalog", description="Search products", timeout_ms=5000),
            ToolContract(name="faq", description="Look up FAQ answers", timeout_ms=3000),
        ],
        "routing_rules": [
            RoutingRuleSpec(target="support", keywords=["help", "issue"], condition_type=ConditionType.KEYWORD),
            RoutingRuleSpec(target="orders", keywords=["order", "buy"], condition_type=ConditionType.KEYWORD),
        ],
        "guardrails": [
            GuardrailSpec(name="content_filter", type=GuardrailType.BOTH, enforcement=GuardrailEnforcement.WARN, description="Filter harmful content"),
        ],
        "policies": [
            PolicySpec(name="response_quality", type=PolicyType.BEHAVIORAL, enforcement=PolicyEnforcement.RECOMMENDED),
        ],
        "handoffs": [
            HandoffSpec(source="root", target="support", context_transfer=ContextTransfer.SUMMARY),
        ],
        "environment": EnvironmentConfig(model="gpt-4", temperature=0.7, max_tokens=4096),
    }
    defaults.update(overrides)
    return CanonicalAgent(**defaults)


def _make_failing_traces(
    failure_type: str,
    count: int = 5,
    total: int = 10,
    **extra: object,
) -> list[dict]:
    traces = []
    for i in range(count):
        trace: dict = {"success": False, "failure_type": failure_type}
        trace.update(extra)
        traces.append(trace)
    for i in range(total - count):
        traces.append({"success": True, "outcome": "success"})
    return traces


# ---------------------------------------------------------------------------
# ComponentCreditAnalyzer tests
# ---------------------------------------------------------------------------


class TestComponentCreditAnalyzer:

    def test_routing_error_blames_routing_rule(self) -> None:
        analyzer = ComponentCreditAnalyzer()
        traces = _make_failing_traces("routing_error", 3, 10)
        entries = analyzer.analyze(traces)
        assert len(entries) >= 1
        top = entries[0]
        assert top.component_type == ComponentType.routing_rule
        assert top.confidence == AttributionConfidence.HIGH
        assert top.failure_count == 3

    def test_tool_failure_blames_tool_contract(self) -> None:
        analyzer = ComponentCreditAnalyzer()
        traces = _make_failing_traces("tool_failure", 4, 10)
        entries = analyzer.analyze(traces)
        top = entries[0]
        assert top.component_type == ComponentType.tool_contract
        assert top.confidence == AttributionConfidence.HIGH

    def test_safety_violation_blames_guardrail_and_policy(self) -> None:
        analyzer = ComponentCreditAnalyzer()
        traces = _make_failing_traces("safety_violation", 5, 10)
        entries = analyzer.analyze(traces)
        types = {e.component_type for e in entries}
        assert ComponentType.guardrail in types
        assert ComponentType.policy in types

    def test_hallucination_blames_instruction(self) -> None:
        analyzer = ComponentCreditAnalyzer()
        traces = _make_failing_traces("hallucination", 2, 10)
        entries = analyzer.analyze(traces)
        top = entries[0]
        assert top.component_type == ComponentType.instruction
        assert top.confidence == AttributionConfidence.MEDIUM

    def test_explicit_failed_tool_annotation(self) -> None:
        analyzer = ComponentCreditAnalyzer()
        traces = [{"success": False, "failed_tool": "catalog"}]
        entries = analyzer.analyze(traces)
        assert len(entries) == 1
        assert entries[0].component_type == ComponentType.tool_contract
        assert entries[0].component_name == "catalog"
        assert entries[0].confidence == AttributionConfidence.HIGH

    def test_explicit_failed_guardrail_annotation(self) -> None:
        analyzer = ComponentCreditAnalyzer()
        traces = [{"success": False, "failed_guardrail": "content_filter"}]
        entries = analyzer.analyze(traces)
        assert len(entries) == 1
        assert entries[0].component_type == ComponentType.guardrail
        assert entries[0].component_name == "content_filter"

    def test_explicit_blamed_component(self) -> None:
        analyzer = ComponentCreditAnalyzer()
        traces = [{"success": False, "blamed_component": {"type": "routing_rule", "name": "support"}}]
        entries = analyzer.analyze(traces)
        assert entries[0].component_type == ComponentType.routing_rule
        assert entries[0].component_name == "support"

    def test_timeout_blames_environment_and_tool(self) -> None:
        analyzer = ComponentCreditAnalyzer()
        traces = _make_failing_traces("timeout", 3, 10)
        entries = analyzer.analyze(traces)
        types = {e.component_type for e in entries}
        assert ComponentType.environment in types
        assert ComponentType.tool_contract in types

    def test_infinite_loop_blames_routing_and_handoff(self) -> None:
        analyzer = ComponentCreditAnalyzer()
        traces = _make_failing_traces("infinite_loop", 2, 10)
        entries = analyzer.analyze(traces)
        types = {e.component_type for e in entries}
        assert ComponentType.routing_rule in types
        assert ComponentType.handoff in types

    def test_refine_tool_name_from_trace(self) -> None:
        analyzer = ComponentCreditAnalyzer()
        traces = [{"success": False, "failure_type": "tool_failure", "tool_call_name": "catalog"}]
        entries = analyzer.analyze(traces, {"tool_contract": ["catalog", "faq"]})
        tool_entry = next(e for e in entries if e.component_type == ComponentType.tool_contract)
        assert tool_entry.component_name == "catalog"

    def test_refine_routing_from_expected_specialist(self) -> None:
        analyzer = ComponentCreditAnalyzer()
        traces = [{"success": False, "failure_type": "routing_error", "expected_specialist": "orders"}]
        entries = analyzer.analyze(traces)
        assert entries[0].component_name == "orders"

    def test_severity_weighted_impact(self) -> None:
        analyzer = ComponentCreditAnalyzer()
        safety_traces = _make_failing_traces("safety_violation", 3, 10)
        entries = analyzer.analyze(safety_traces)
        guardrail = next(e for e in entries if e.component_type == ComponentType.guardrail)
        assert guardrail.impact_score > 0.3 * 1.0

    def test_empty_traces_returns_empty(self) -> None:
        analyzer = ComponentCreditAnalyzer()
        assert analyzer.analyze([]) == []

    def test_all_success_returns_empty(self) -> None:
        analyzer = ComponentCreditAnalyzer()
        traces = [{"success": True} for _ in range(5)]
        assert analyzer.analyze(traces) == []

    def test_serialization_round_trip(self) -> None:
        analyzer = ComponentCreditAnalyzer()
        traces = _make_failing_traces("routing_error", 2, 5)
        entries = analyzer.analyze(traces)
        for entry in entries:
            d = entry.to_dict()
            reconstructed = ComponentBlameEntry.from_dict(d)
            assert reconstructed.component_type == entry.component_type
            assert reconstructed.impact_score == entry.impact_score
            assert reconstructed.confidence == entry.confidence

    def test_keyword_classification(self) -> None:
        analyzer = ComponentCreditAnalyzer()
        traces = [{"success": False, "error": "request timed out waiting for tool"}]
        entries = analyzer.analyze(traces)
        assert len(entries) > 0

    def test_confidence_to_float_conversion(self) -> None:
        """Verify confidence enum converts to the float scale used by ComponentAttribution."""
        assert AttributionConfidence.HIGH.to_float() == 0.9
        assert AttributionConfidence.MEDIUM.to_float() == 0.7
        assert AttributionConfidence.LOW.to_float() == 0.4
        assert AttributionConfidence.HEURISTIC.to_float() == 0.2

    def test_component_type_values_match_codex_vocabulary(self) -> None:
        """Verify enum values are compatible with Codex's ComponentReference.component_type."""
        expected = {"instruction", "tool_contract", "routing_rule", "guardrail",
                    "policy", "callback", "handoff", "sub_agent", "mcp_server", "environment",
                    "flow", "state", "transition"}
        actual = {ct.value for ct in ComponentType}
        assert actual == expected


# ---------------------------------------------------------------------------
# Mutation proposal tests
# ---------------------------------------------------------------------------


class TestProposeComponentPatches:

    def test_routing_patches_expand_keywords(self) -> None:
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.routing_rule,
            component_name="support",
            failure_count=3, failure_rate=0.3, failure_types=["routing_error"],
            impact_score=0.33, confidence=AttributionConfidence.HIGH,
        )]
        bundle = propose_component_patches(agent, blame)
        assert len(bundle.operations) >= 1
        op = bundle.operations[0]
        assert op.component.component_type == "routing_rule"
        assert op.component.name == "support"
        assert "support" in op.value

    def test_tool_patches_increase_timeout(self) -> None:
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.tool_contract,
            component_name="catalog",
            failure_count=2, failure_rate=0.2, failure_types=["tool_failure"],
            impact_score=0.18, confidence=AttributionConfidence.HIGH,
        )]
        bundle = propose_component_patches(agent, blame)
        assert len(bundle.operations) >= 1
        timeout_op = bundle.operations[0]
        assert timeout_op.field_path == "timeout_ms"
        assert timeout_op.value == 7000

    def test_guardrail_patches_upgrade_enforcement(self) -> None:
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.guardrail,
            component_name="content_filter",
            failure_count=3, failure_rate=0.3, failure_types=["safety_violation"],
            impact_score=0.45, confidence=AttributionConfidence.MEDIUM,
        )]
        bundle = propose_component_patches(agent, blame)
        assert len(bundle.operations) >= 1
        assert bundle.operations[0].value == GuardrailEnforcement.BLOCK.value

    def test_instruction_hallucination_adds_constraint(self) -> None:
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.instruction,
            failure_count=4, failure_rate=0.4, failure_types=["hallucination"],
            impact_score=0.52, confidence=AttributionConfidence.MEDIUM,
        )]
        bundle = propose_component_patches(agent, blame)
        assert len(bundle.operations) >= 1
        op = bundle.operations[0]
        assert op.op == "add"
        assert "anti_hallucination" in str(op.value.get("label", ""))

    def test_instruction_quality_enhances_primary(self) -> None:
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.instruction,
            failure_count=2, failure_rate=0.2, failure_types=["invalid_output"],
            impact_score=0.16, confidence=AttributionConfidence.LOW,
        )]
        bundle = propose_component_patches(agent, blame)
        assert len(bundle.operations) >= 1
        assert "verify" in bundle.operations[0].value.lower()

    def test_handoff_patches_upgrade_context_transfer(self) -> None:
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.handoff,
            component_name="support",
            failure_count=2, failure_rate=0.2, failure_types=["infinite_loop"],
            impact_score=0.24, confidence=AttributionConfidence.MEDIUM,
        )]
        bundle = propose_component_patches(agent, blame)
        assert len(bundle.operations) >= 1
        assert any(op.value == ContextTransfer.FULL.value for op in bundle.operations)

    def test_policy_safety_adds_policy(self) -> None:
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.policy,
            failure_count=3, failure_rate=0.3, failure_types=["safety_violation"],
            impact_score=0.45, confidence=AttributionConfidence.MEDIUM,
        )]
        bundle = propose_component_patches(agent, blame)
        assert len(bundle.operations) >= 1
        op = bundle.operations[0]
        assert "safety" in str(op.value.get("name", "")).lower()

    def test_environment_timeout_reduces_tokens(self) -> None:
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.environment,
            failure_count=3, failure_rate=0.3, failure_types=["timeout"],
            impact_score=0.3, confidence=AttributionConfidence.LOW,
        )]
        bundle = propose_component_patches(agent, blame)
        assert len(bundle.operations) >= 1
        token_op = next(op for op in bundle.operations if op.field_path == "max_tokens")
        assert token_op.value == 3596

    def test_safety_violation_elevates_risk(self) -> None:
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.guardrail,
            failure_count=5, failure_rate=0.5, failure_types=["safety_violation"],
            impact_score=0.75, confidence=AttributionConfidence.HIGH,
        )]
        bundle = propose_component_patches(agent, blame)
        assert bundle.metadata.get("risk_class") == "high"

    def test_past_surfaces_skipped(self) -> None:
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.routing_rule,
            component_name="support",
            failure_count=3, failure_rate=0.3, failure_types=["routing_error"],
            impact_score=0.33, confidence=AttributionConfidence.HIGH,
        )]
        bundle = propose_component_patches(agent, blame, past_bundle_surfaces=["routing_rule"])
        assert len(bundle.operations) == 0

    def test_low_impact_skipped(self) -> None:
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.routing_rule,
            failure_count=0, failure_rate=0.0, failure_types=["routing_error"],
            impact_score=0.005, confidence=AttributionConfidence.HEURISTIC,
        )]
        bundle = propose_component_patches(agent, blame)
        assert len(bundle.operations) == 0

    def test_max_patches_limit(self) -> None:
        agent = _make_agent()
        blame = [
            ComponentBlameEntry(
                component_type=ComponentType.routing_rule, component_name="support",
                failure_count=3, failure_rate=0.3, failure_types=["routing_error"],
                impact_score=0.33, confidence=AttributionConfidence.HIGH,
            ),
            ComponentBlameEntry(
                component_type=ComponentType.tool_contract, component_name="catalog",
                failure_count=2, failure_rate=0.2, failure_types=["tool_failure"],
                impact_score=0.18, confidence=AttributionConfidence.HIGH,
            ),
            ComponentBlameEntry(
                component_type=ComponentType.guardrail, component_name="content_filter",
                failure_count=4, failure_rate=0.4, failure_types=["safety_violation"],
                impact_score=0.6, confidence=AttributionConfidence.MEDIUM,
            ),
        ]
        bundle = propose_component_patches(agent, blame, max_patches=2)
        assert len(bundle.operations) <= 2

    def test_empty_blame_produces_empty_bundle(self) -> None:
        agent = _make_agent()
        bundle = propose_component_patches(agent, [])
        assert len(bundle.operations) == 0

    def test_add_fallback_routing_when_no_rules(self) -> None:
        agent = _make_agent(routing_rules=[])
        blame = [ComponentBlameEntry(
            component_type=ComponentType.routing_rule,
            failure_count=5, failure_rate=0.5, failure_types=["routing_error"],
            impact_score=0.55, confidence=AttributionConfidence.HIGH,
        )]
        bundle = propose_component_patches(agent, blame)
        assert len(bundle.operations) >= 1
        assert bundle.operations[0].op == "add"

    def test_add_safety_guardrail_when_no_guardrails(self) -> None:
        agent = _make_agent(guardrails=[])
        blame = [ComponentBlameEntry(
            component_type=ComponentType.guardrail,
            failure_count=3, failure_rate=0.3, failure_types=["safety_violation"],
            impact_score=0.45, confidence=AttributionConfidence.MEDIUM,
        )]
        bundle = propose_component_patches(agent, blame)
        assert len(bundle.operations) >= 1
        assert "safety_gate" in str(bundle.operations[0].value)


# ---------------------------------------------------------------------------
# Bundle validation and application tests
# ---------------------------------------------------------------------------


class TestBundleValidationAndApplication:

    def test_routing_bundle_validates_against_agent(self) -> None:
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.routing_rule,
            component_name="support",
            failure_count=3, failure_rate=0.3, failure_types=["routing_error"],
            impact_score=0.33, confidence=AttributionConfidence.HIGH,
        )]
        bundle = propose_component_patches(agent, blame)
        validation = validate_patch_bundle(agent, bundle)
        assert validation.valid, f"Validation errors: {validation.errors}"

    def test_tool_bundle_validates(self) -> None:
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.tool_contract,
            component_name="catalog",
            failure_count=2, failure_rate=0.2, failure_types=["tool_failure"],
            impact_score=0.18, confidence=AttributionConfidence.HIGH,
        )]
        bundle = propose_component_patches(agent, blame)
        validation = validate_patch_bundle(agent, bundle)
        assert validation.valid, f"Validation errors: {validation.errors}"

    def test_guardrail_bundle_validates(self) -> None:
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.guardrail,
            component_name="content_filter",
            failure_count=3, failure_rate=0.3, failure_types=["safety_violation"],
            impact_score=0.45, confidence=AttributionConfidence.MEDIUM,
        )]
        bundle = propose_component_patches(agent, blame)
        validation = validate_patch_bundle(agent, bundle)
        assert validation.valid, f"Validation errors: {validation.errors}"

    def test_instruction_bundle_validates(self) -> None:
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.instruction,
            failure_count=2, failure_rate=0.2, failure_types=["invalid_output"],
            impact_score=0.16, confidence=AttributionConfidence.LOW,
        )]
        bundle = propose_component_patches(agent, blame)
        validation = validate_patch_bundle(agent, bundle)
        assert validation.valid, f"Validation errors: {validation.errors}"

    def test_environment_bundle_validates(self) -> None:
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.environment,
            failure_count=3, failure_rate=0.3, failure_types=["timeout"],
            impact_score=0.3, confidence=AttributionConfidence.LOW,
        )]
        bundle = propose_component_patches(agent, blame)
        validation = validate_patch_bundle(agent, bundle)
        assert validation.valid, f"Validation errors: {validation.errors}"

    def test_routing_bundle_applies_to_agent(self) -> None:
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.routing_rule,
            component_name="support",
            failure_count=3, failure_rate=0.3, failure_types=["routing_error"],
            impact_score=0.33, confidence=AttributionConfidence.HIGH,
        )]
        bundle = propose_component_patches(agent, blame)
        new_agent = apply_patch_bundle(agent, bundle)
        support_rule = next(r for r in new_agent.routing_rules if r.target == "support")
        assert "support" in support_rule.keywords
        assert new_agent.name == agent.name

    def test_tool_bundle_applies_timeout_increase(self) -> None:
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.tool_contract,
            component_name="catalog",
            failure_count=2, failure_rate=0.2, failure_types=["tool_failure"],
            impact_score=0.18, confidence=AttributionConfidence.HIGH,
        )]
        bundle = propose_component_patches(agent, blame)
        new_agent = apply_patch_bundle(agent, bundle)
        catalog = next(t for t in new_agent.tools if t.name == "catalog")
        assert catalog.timeout_ms == 7000

    def test_guardrail_bundle_applies_enforcement_upgrade(self) -> None:
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.guardrail,
            component_name="content_filter",
            failure_count=3, failure_rate=0.3, failure_types=["safety_violation"],
            impact_score=0.45, confidence=AttributionConfidence.MEDIUM,
        )]
        bundle = propose_component_patches(agent, blame)
        new_agent = apply_patch_bundle(agent, bundle)
        guard = next(g for g in new_agent.guardrails if g.name == "content_filter")
        assert guard.enforcement == GuardrailEnforcement.BLOCK


# ---------------------------------------------------------------------------
# End-to-end integration tests
# ---------------------------------------------------------------------------


class TestEndToEnd:

    def test_routing_fix_pipeline(self) -> None:
        agent = _make_agent()
        traces = _make_failing_traces(
            "routing_error", 5, 10,
            expected_specialist="support",
        )
        blame_entries, bundle = analyze_and_propose(agent, traces)
        assert len(blame_entries) >= 1
        assert bundle.operations
        validation = validate_patch_bundle(agent, bundle)
        assert validation.valid

    def test_safety_fix_pipeline(self) -> None:
        agent = _make_agent()
        traces = _make_failing_traces("safety_violation", 5, 10)
        blame_entries, bundle = analyze_and_propose(agent, traces)
        types = {e.component_type for e in blame_entries}
        assert ComponentType.guardrail in types
        assert bundle.operations
        assert bundle.metadata.get("risk_class") == "high"

    def test_apply_and_convert_produces_config(self) -> None:
        agent = _make_agent()
        traces = _make_failing_traces("routing_error", 5, 10, expected_specialist="support")
        _, bundle = analyze_and_propose(agent, traces)
        new_agent, config = apply_and_convert(agent, bundle)
        assert isinstance(config, dict)
        assert "routing" in config or "prompts" in config
        assert new_agent.name == agent.name

    def test_config_bridge_roundtrip(self) -> None:
        """Verify mutation bundles work through the Codex patch_bundle_to_config bridge."""
        current_config = {
            "model": "gpt-4",
            "prompts": {"root": "You are a helpful assistant."},
            "routing": {"rules": [
                {"specialist": "support", "keywords": ["help", "issue"], "patterns": []},
                {"specialist": "orders", "keywords": ["order", "buy"], "patterns": []},
            ]},
            "tools_config": {"catalog": {"description": "Search products", "parameters": []}},
            "thresholds": {"max_turns": 12},
        }
        agent = from_config_dict(current_config, name="root")
        traces = _make_failing_traces("routing_error", 5, 10, expected_specialist="support")
        _, bundle = analyze_and_propose(agent, traces)

        updated_config = patch_bundle_to_config(current_config, bundle, agent_name="root")
        assert updated_config["thresholds"] == {"max_turns": 12}
        assert updated_config["model"] == "gpt-4"

    def test_diverse_failures_produce_diverse_patches(self) -> None:
        agent = _make_agent()
        traces = (
            _make_failing_traces("routing_error", 3, 3, expected_specialist="support")
            + _make_failing_traces("tool_failure", 2, 2, tool_call_name="catalog")
            + _make_failing_traces("safety_violation", 2, 2)
            + [{"success": True} for _ in range(3)]
        )
        blame_entries, bundle = analyze_and_propose(agent, traces, max_patches=10)
        op_types = {op.component.component_type for op in bundle.operations}
        assert len(op_types) >= 2

    def test_all_success_produces_empty_bundle(self) -> None:
        agent = _make_agent()
        traces = [{"success": True} for _ in range(10)]
        blame_entries, bundle = analyze_and_propose(agent, traces)
        assert len(blame_entries) == 0
        assert len(bundle.operations) == 0

    def test_bundle_serialization_round_trip(self) -> None:
        agent = _make_agent()
        traces = _make_failing_traces("routing_error", 3, 10, expected_specialist="support")
        _, bundle = analyze_and_propose(agent, traces)
        d = bundle.model_dump(mode="python")
        reconstructed = TypedPatchBundle.model_validate(d)
        assert len(reconstructed.operations) == len(bundle.operations)
        assert reconstructed.bundle_id == bundle.bundle_id


# ---------------------------------------------------------------------------
# Type compatibility tests
# ---------------------------------------------------------------------------


class TestTypeCompatibility:

    def test_bundle_is_typed_patch_bundle(self) -> None:
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.routing_rule,
            component_name="support",
            failure_count=3, failure_rate=0.3, failure_types=["routing_error"],
            impact_score=0.33, confidence=AttributionConfidence.HIGH,
        )]
        bundle = propose_component_patches(agent, blame)
        assert isinstance(bundle, TypedPatchBundle)

    def test_operations_are_component_patch_operations(self) -> None:
        from shared.canonical_patch import ComponentPatchOperation as CPO
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.routing_rule,
            component_name="support",
            failure_count=3, failure_rate=0.3, failure_types=["routing_error"],
            impact_score=0.33, confidence=AttributionConfidence.HIGH,
        )]
        bundle = propose_component_patches(agent, blame)
        for op in bundle.operations:
            assert isinstance(op, CPO)

    def test_component_refs_are_component_references(self) -> None:
        from shared.canonical_patch import ComponentReference as CR
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.tool_contract,
            component_name="catalog",
            failure_count=2, failure_rate=0.2, failure_types=["tool_failure"],
            impact_score=0.18, confidence=AttributionConfidence.HIGH,
        )]
        bundle = propose_component_patches(agent, blame)
        for op in bundle.operations:
            assert isinstance(op.component, CR)

    def test_credit_component_type_values_align_with_patch_references(self) -> None:
        """Ensure credit analyzer's ComponentType values match what iter_component_references produces."""
        agent = _make_agent()
        ref_types = {ref.component_type for ref in iter_component_references(agent)}
        credit_types = {ct.value for ct in ComponentType}
        assert ref_types.issubset(credit_types), f"Unrecognized ref types: {ref_types - credit_types}"


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestEdgeCases:

    def test_empty_agent_instruction_adds_root(self) -> None:
        agent = CanonicalAgent(name="empty")
        blame = [ComponentBlameEntry(
            component_type=ComponentType.instruction,
            failure_count=5, failure_rate=1.0, failure_types=["invalid_output"],
            impact_score=0.8, confidence=AttributionConfidence.MEDIUM,
        )]
        bundle = propose_component_patches(agent, blame)
        assert len(bundle.operations) >= 1
        assert bundle.operations[0].op == "add"

    def test_handoff_without_name_produces_no_ops(self) -> None:
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.handoff,
            failure_count=2, failure_rate=0.2, failure_types=["infinite_loop"],
            impact_score=0.24, confidence=AttributionConfidence.MEDIUM,
        )]
        bundle = propose_component_patches(agent, blame)
        assert len(bundle.operations) == 0

    def test_tool_with_low_timeout_gets_normalized(self) -> None:
        agent = _make_agent()
        blame = [ComponentBlameEntry(
            component_type=ComponentType.tool_contract,
            failure_count=2, failure_rate=0.2, failure_types=["tool_failure"],
            impact_score=0.18, confidence=AttributionConfidence.HIGH,
        )]
        bundle = propose_component_patches(agent, blame)
        timeout_ops = [op for op in bundle.operations if op.field_path == "timeout_ms"]
        if timeout_ops:
            assert timeout_ops[0].value == 5000

    def test_guardrail_already_blocking_produces_no_ops(self) -> None:
        agent = _make_agent(guardrails=[
            GuardrailSpec(name="strict", type=GuardrailType.BOTH, enforcement=GuardrailEnforcement.BLOCK),
        ])
        blame = [ComponentBlameEntry(
            component_type=ComponentType.guardrail,
            component_name="strict",
            failure_count=2, failure_rate=0.2, failure_types=["safety_violation"],
            impact_score=0.3, confidence=AttributionConfidence.MEDIUM,
        )]
        bundle = propose_component_patches(agent, blame)
        assert len(bundle.operations) == 0
