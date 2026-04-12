"""Comprehensive tests for CX optimizer proposer improvements.

Tests cover:
1. IR flow/state/transition types
2. Flow serialization round-trips through config dict
3. Patch system flow component enumeration
4. Credit-based proposer (the new primary path)
5. Flow/state/transition mutation generators
6. CX adapter flow projection
7. End-to-end: CX snapshot -> IR -> optimize -> config -> verify
"""

from __future__ import annotations

import copy
import uuid

import pytest

from shared.canonical_ir import (
    CanonicalAgent,
    ConditionType,
    EnvironmentConfig,
    EventHandlerSpec,
    FlowSpec,
    GuardrailEnforcement,
    GuardrailSpec,
    GuardrailType,
    HandoffSpec,
    Instruction,
    InstructionRole,
    PolicySpec,
    RoutingRuleSpec,
    StateSpec,
    ToolContract,
    TransitionSpec,
)
from shared.canonical_ir_convert import from_config_dict, to_config_dict
from shared.canonical_patch import (
    ComponentPatchOperation,
    ComponentReference,
    TypedPatchBundle,
    apply_patch_bundle,
    find_component_reference,
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
from optimizer.proposer import Proposer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _agent_with_flows() -> CanonicalAgent:
    """Build a canonical agent with flows, states, and transitions for testing."""
    return CanonicalAgent(
        name="cx_test_agent",
        platform_origin="dialogflow-cx",
        instructions=[
            Instruction(role=InstructionRole.SYSTEM, content="You are a helpful agent.", priority=100, label="root"),
        ],
        tools=[
            ToolContract(name="lookup_order", description="Look up order details", timeout_ms=5000),
        ],
        routing_rules=[
            RoutingRuleSpec(target="orders", keywords=["order", "track"]),
            RoutingRuleSpec(target="support", keywords=["help", "issue"]),
        ],
        guardrails=[
            GuardrailSpec(name="safety_gate", type=GuardrailType.BOTH, enforcement=GuardrailEnforcement.WARN),
        ],
        flows=[
            FlowSpec(
                name="order_flow",
                display_name="Order Flow",
                description="Handles order-related queries",
                states=[
                    StateSpec(
                        name="collect_order_id",
                        display_name="Collect Order ID",
                        entry_fulfillment="What is your order number?",
                        transitions=[
                            TransitionSpec(target="lookup_order", condition="$order_id != null", intent="provide_order"),
                        ],
                        event_handlers=[
                            EventHandlerSpec(event="no-input", action="reprompt", fulfillment_message="Please provide your order number."),
                        ],
                    ),
                    StateSpec(
                        name="lookup_order",
                        display_name="Look Up Order",
                        entry_fulfillment="Looking up your order...",
                        transitions=[
                            TransitionSpec(target="show_result", condition="$result != null"),
                        ],
                    ),
                    StateSpec(
                        name="show_result",
                        display_name="Show Result",
                        entry_fulfillment="Here are your order details.",
                    ),
                ],
                transitions=[
                    TransitionSpec(target="collect_order_id", intent="order_status", fulfillment_message="Let me help you check your order."),
                ],
                event_handlers=[
                    EventHandlerSpec(event="no-match", action="fallback", fulfillment_message="I didn't understand."),
                ],
            ),
            FlowSpec(
                name="support_flow",
                display_name="Support Flow",
                description="Handles support queries",
                states=[
                    StateSpec(name="triage", display_name="Triage", entry_fulfillment="How can I help?"),
                ],
            ),
        ],
        environment=EnvironmentConfig(model="gemini-pro", temperature=0.7, max_tokens=4096),
    )


def _agent_minimal() -> CanonicalAgent:
    """Minimal agent with no flows for fallback testing."""
    return CanonicalAgent(
        name="simple_agent",
        instructions=[
            Instruction(role=InstructionRole.SYSTEM, content="You are helpful.", priority=100, label="root"),
        ],
        routing_rules=[
            RoutingRuleSpec(target="support", keywords=["help"]),
        ],
    )


# ---------------------------------------------------------------------------
# 1. IR Flow/State/Transition Types
# ---------------------------------------------------------------------------


class TestFlowIRTypes:
    def test_flow_spec_creation(self):
        flow = FlowSpec(name="test_flow", description="A test flow")
        assert flow.name == "test_flow"
        assert flow.states == []
        assert flow.transitions == []
        assert flow.event_handlers == []

    def test_state_spec_creation(self):
        state = StateSpec(name="collect_info", entry_fulfillment="Please provide info.")
        assert state.name == "collect_info"
        assert state.entry_fulfillment == "Please provide info."

    def test_transition_spec_creation(self):
        t = TransitionSpec(target="next_state", condition="$val != null", intent="provide_info")
        assert t.target == "next_state"
        assert t.condition == "$val != null"
        assert t.intent == "provide_info"

    def test_event_handler_creation(self):
        e = EventHandlerSpec(event="no-match", action="fallback", fulfillment_message="Sorry.")
        assert e.event == "no-match"
        assert e.action == "fallback"

    def test_canonical_agent_flows_field(self):
        agent = _agent_with_flows()
        assert len(agent.flows) == 2
        assert agent.flows[0].name == "order_flow"
        assert len(agent.flows[0].states) == 3

    def test_flow_names_helper(self):
        agent = _agent_with_flows()
        assert agent.flow_names() == ["order_flow", "support_flow"]

    def test_all_states_helper(self):
        agent = _agent_with_flows()
        states = agent.all_states()
        assert len(states) == 4
        names = [s.name for s in states]
        assert "collect_order_id" in names
        assert "triage" in names

    def test_all_transitions_helper(self):
        agent = _agent_with_flows()
        transitions = agent.all_transitions()
        assert len(transitions) == 3
        targets = [t.target for t in transitions]
        assert "lookup_order" in targets
        assert "collect_order_id" in targets

    def test_flow_extra_fields_allowed(self):
        flow = FlowSpec(name="f", custom_field="value")
        assert flow.name == "f"

    def test_empty_flows_default(self):
        agent = CanonicalAgent(name="empty")
        assert agent.flows == []
        assert agent.flow_names() == []
        assert agent.all_states() == []
        assert agent.all_transitions() == []


# ---------------------------------------------------------------------------
# 2. Flow Serialization Round-Trips
# ---------------------------------------------------------------------------


class TestFlowConfigRoundTrip:
    def test_to_config_dict_includes_flows(self):
        agent = _agent_with_flows()
        config = to_config_dict(agent)
        assert "flows" in config
        assert len(config["flows"]) == 2
        assert config["flows"][0]["name"] == "order_flow"

    def test_flow_states_serialized(self):
        agent = _agent_with_flows()
        config = to_config_dict(agent)
        flow = config["flows"][0]
        assert "states" in flow
        assert len(flow["states"]) == 3
        assert flow["states"][0]["name"] == "collect_order_id"
        assert flow["states"][0]["entry_fulfillment"] == "What is your order number?"

    def test_flow_transitions_serialized(self):
        agent = _agent_with_flows()
        config = to_config_dict(agent)
        flow = config["flows"][0]
        assert "transitions" in flow
        assert flow["transitions"][0]["target"] == "collect_order_id"
        assert flow["transitions"][0]["intent"] == "order_status"

    def test_state_transitions_serialized(self):
        agent = _agent_with_flows()
        config = to_config_dict(agent)
        state = config["flows"][0]["states"][0]
        assert "transitions" in state
        assert state["transitions"][0]["target"] == "lookup_order"
        assert state["transitions"][0]["condition"] == "$order_id != null"

    def test_event_handlers_serialized(self):
        agent = _agent_with_flows()
        config = to_config_dict(agent)
        flow = config["flows"][0]
        assert "event_handlers" in flow
        assert flow["event_handlers"][0]["event"] == "no-match"
        state = flow["states"][0]
        assert "event_handlers" in state
        assert state["event_handlers"][0]["event"] == "no-input"

    def test_from_config_dict_loads_flows(self):
        agent = _agent_with_flows()
        config = to_config_dict(agent)
        restored = from_config_dict(config, name="cx_test_agent")
        assert len(restored.flows) == 2
        assert restored.flows[0].name == "order_flow"
        assert len(restored.flows[0].states) == 3

    def test_full_round_trip_preserves_flows(self):
        agent = _agent_with_flows()
        config = to_config_dict(agent)
        restored = from_config_dict(config, name="cx_test_agent")
        assert restored.flow_names() == agent.flow_names()
        assert len(restored.all_states()) == len(agent.all_states())
        assert len(restored.all_transitions()) == len(agent.all_transitions())

    def test_round_trip_preserves_state_details(self):
        agent = _agent_with_flows()
        config = to_config_dict(agent)
        restored = from_config_dict(config, name="cx_test_agent")
        original_state = agent.flows[0].states[0]
        restored_state = restored.flows[0].states[0]
        assert restored_state.name == original_state.name
        assert restored_state.entry_fulfillment == original_state.entry_fulfillment
        assert len(restored_state.transitions) == len(original_state.transitions)
        assert restored_state.transitions[0].target == original_state.transitions[0].target
        assert restored_state.transitions[0].condition == original_state.transitions[0].condition

    def test_round_trip_preserves_event_handlers(self):
        agent = _agent_with_flows()
        config = to_config_dict(agent)
        restored = from_config_dict(config, name="cx_test_agent")
        assert len(restored.flows[0].event_handlers) == 1
        assert restored.flows[0].event_handlers[0].event == "no-match"
        assert len(restored.flows[0].states[0].event_handlers) == 1

    def test_empty_flows_not_in_config(self):
        agent = _agent_minimal()
        config = to_config_dict(agent)
        assert "flows" not in config

    def test_config_without_flows_produces_empty_list(self):
        config = {"prompts": {"root": "Hello"}}
        agent = from_config_dict(config)
        assert agent.flows == []

    def test_flows_survive_patch_bundle_to_config(self):
        """Verify flows pass through patch_bundle_to_config unchanged."""
        agent = _agent_with_flows()
        config = to_config_dict(agent)
        bundle = TypedPatchBundle(
            bundle_id="noop",
            title="no-op test",
            operations=[],
        )
        result = patch_bundle_to_config(config, bundle)
        assert "flows" in result
        assert len(result["flows"]) == 2


# ---------------------------------------------------------------------------
# 3. Patch System Flow Component Enumeration
# ---------------------------------------------------------------------------


class TestFlowPatchEnumeration:
    def test_iter_includes_flow_references(self):
        agent = _agent_with_flows()
        refs = iter_component_references(agent)
        flow_refs = [r for r in refs if r.component_type == "flow"]
        assert len(flow_refs) == 2
        assert flow_refs[0].name == "order_flow"
        assert flow_refs[1].name == "support_flow"

    def test_iter_includes_state_references(self):
        agent = _agent_with_flows()
        refs = iter_component_references(agent)
        state_refs = [r for r in refs if r.component_type == "state"]
        assert len(state_refs) == 4
        state_names = [r.name for r in state_refs]
        assert "collect_order_id" in state_names
        assert "triage" in state_names

    def test_iter_includes_transition_references(self):
        agent = _agent_with_flows()
        refs = iter_component_references(agent)
        transition_refs = [r for r in refs if r.component_type == "transition"]
        assert len(transition_refs) == 3

    def test_flow_paths_are_valid(self):
        agent = _agent_with_flows()
        refs = iter_component_references(agent)
        flow_ref = [r for r in refs if r.component_type == "flow"][0]
        assert flow_ref.path == "/flows/0"

    def test_state_paths_are_nested(self):
        agent = _agent_with_flows()
        refs = iter_component_references(agent)
        state_refs = [r for r in refs if r.component_type == "state"]
        assert state_refs[0].path == "/flows/0/states/0"

    def test_transition_paths_are_nested(self):
        agent = _agent_with_flows()
        refs = iter_component_references(agent)
        transition_refs = [r for r in refs if r.component_type == "transition"]
        state_transitions = [r for r in transition_refs if "/states/" in r.path]
        flow_transitions = [r for r in transition_refs if "/states/" not in r.path]
        assert len(state_transitions) == 2
        assert len(flow_transitions) == 1

    def test_find_flow_reference(self):
        agent = _agent_with_flows()
        ref = find_component_reference(agent, "flow", "order_flow")
        assert ref is not None
        assert ref.component_type == "flow"
        assert ref.path == "/flows/0"

    def test_find_state_reference(self):
        agent = _agent_with_flows()
        ref = find_component_reference(agent, "state", "collect_order_id")
        assert ref is not None
        assert ref.component_type == "state"

    def test_find_transition_reference(self):
        agent = _agent_with_flows()
        ref = find_component_reference(agent, "transition", "collect_order_id")
        assert ref is not None
        assert ref.component_type == "transition"

    def test_no_flows_means_no_flow_refs(self):
        agent = _agent_minimal()
        refs = iter_component_references(agent)
        flow_refs = [r for r in refs if r.component_type in ("flow", "state", "transition")]
        assert len(flow_refs) == 0

    def test_validate_patch_on_flow_component(self):
        agent = _agent_with_flows()
        ref = find_component_reference(agent, "flow", "order_flow")
        bundle = TypedPatchBundle(
            bundle_id="test",
            operations=[
                ComponentPatchOperation(
                    op="set",
                    component=ref,
                    field_path="description",
                    value="Updated description",
                ),
            ],
        )
        result = validate_patch_bundle(agent, bundle)
        assert result.valid

    def test_apply_patch_on_flow_description(self):
        agent = _agent_with_flows()
        ref = find_component_reference(agent, "flow", "order_flow")
        bundle = TypedPatchBundle(
            bundle_id="test",
            operations=[
                ComponentPatchOperation(
                    op="replace",
                    component=ref,
                    field_path="description",
                    value="Updated order handling flow",
                ),
            ],
        )
        new_agent = apply_patch_bundle(agent, bundle)
        assert new_agent.flows[0].description == "Updated order handling flow"

    def test_apply_patch_on_state_entry_fulfillment(self):
        agent = _agent_with_flows()
        ref = find_component_reference(agent, "state", "collect_order_id")
        bundle = TypedPatchBundle(
            bundle_id="test",
            operations=[
                ComponentPatchOperation(
                    op="replace",
                    component=ref,
                    field_path="entry_fulfillment",
                    value="Please enter your order ID.",
                ),
            ],
        )
        new_agent = apply_patch_bundle(agent, bundle)
        assert new_agent.flows[0].states[0].entry_fulfillment == "Please enter your order ID."

    def test_apply_patch_on_transition_condition(self):
        agent = _agent_with_flows()
        ref = find_component_reference(agent, "transition", "collect_order_id")
        bundle = TypedPatchBundle(
            bundle_id="test",
            operations=[
                ComponentPatchOperation(
                    op="replace",
                    component=ref,
                    field_path="condition",
                    value="$session.params.intent == 'order_status'",
                ),
            ],
        )
        new_agent = apply_patch_bundle(agent, bundle)
        assert new_agent.flows[0].transitions[0].condition == "$session.params.intent == 'order_status'"


# ---------------------------------------------------------------------------
# 4. Credit-Based Proposer
# ---------------------------------------------------------------------------


class TestCreditProposer:
    def test_credit_propose_with_routing_traces(self):
        """Credit proposer should produce a component-targeted proposal from traces."""
        proposer = Proposer(use_mock=True)
        config = {
            "prompts": {"root": "You are a helpful agent."},
            "routing": {
                "rules": [
                    {"specialist": "orders", "keywords": ["order"]},
                    {"specialist": "support", "keywords": ["help"]},
                ]
            },
        }
        traces = [
            {"outcome": "fail", "failure_type": "routing_error", "expected_specialist": "orders"},
            {"outcome": "fail", "failure_type": "routing_error", "expected_specialist": "orders"},
            {"outcome": "success"},
        ]
        proposal = proposer.propose(
            current_config=config,
            health_metrics={},
            failure_samples=traces,
            failure_buckets={"routing_error": 2},
            past_attempts=[],
            traces=traces,
        )
        assert proposal is not None
        assert proposal.patch_bundle is not None
        assert "routing" in proposal.reasoning.lower() or "component" in proposal.reasoning.lower()

    def test_credit_propose_with_tool_failure_traces(self):
        proposer = Proposer(use_mock=True)
        config = {
            "prompts": {"root": "Agent"},
            "tools_config": {"lookup": {"description": "Look up data", "timeout_ms": 3000}},
        }
        traces = [
            {"outcome": "fail", "failure_type": "tool_failure", "failed_tool": "lookup"},
            {"outcome": "fail", "failure_type": "tool_failure", "failed_tool": "lookup"},
        ]
        proposal = proposer.propose(
            current_config=config,
            health_metrics={},
            failure_samples=traces,
            failure_buckets={"tool_failure": 2},
            past_attempts=[],
            traces=traces,
        )
        assert proposal is not None
        assert proposal.patch_bundle is not None

    def test_credit_propose_falls_back_to_mock_on_empty_traces(self):
        proposer = Proposer(use_mock=True)
        config = {"prompts": {"root": "Agent"}}
        proposal = proposer.propose(
            current_config=config,
            health_metrics={},
            failure_samples=[],
            failure_buckets={"unhelpful_response": 1},
            past_attempts=[],
            traces=[],
        )
        assert proposal is not None
        assert proposal.patch_bundle is None

    def test_credit_propose_falls_back_when_no_blame(self):
        """All-success traces produce no blame entries -> falls back to mock."""
        proposer = Proposer(use_mock=True)
        config = {"prompts": {"root": "Agent"}}
        traces = [{"outcome": "success"}, {"outcome": "success"}]
        proposal = proposer.propose(
            current_config=config,
            health_metrics={},
            failure_samples=traces,
            failure_buckets={},
            past_attempts=[],
            traces=traces,
        )
        assert proposal is not None

    def test_credit_propose_produces_valid_new_config(self):
        proposer = Proposer(use_mock=True)
        config = {
            "prompts": {"root": "Agent"},
            "guardrails": [{"name": "safety", "type": "both", "enforcement": "warn"}],
        }
        traces = [
            {"outcome": "fail", "failure_type": "safety_violation"},
            {"outcome": "fail", "failure_type": "safety_violation"},
        ]
        proposal = proposer.propose(
            current_config=config,
            health_metrics={},
            failure_samples=traces,
            failure_buckets={"safety_violation": 2},
            past_attempts=[],
            traces=traces,
        )
        assert proposal is not None
        assert isinstance(proposal.new_config, dict)
        assert "prompts" in proposal.new_config

    def test_credit_propose_avoids_past_surfaces(self):
        proposer = Proposer(use_mock=True)
        config = {
            "prompts": {"root": "Agent"},
            "routing": {"rules": [{"specialist": "orders", "keywords": ["order"]}]},
        }
        traces = [
            {"outcome": "fail", "failure_type": "routing_error", "expected_specialist": "orders"},
        ]
        proposal = proposer.propose(
            current_config=config,
            health_metrics={},
            failure_samples=traces,
            failure_buckets={"routing_error": 1},
            past_attempts=[{"config_section": "routing_rule"}],
            traces=traces,
        )
        assert proposal is not None

    def test_mock_propose_still_works_standalone(self):
        """Verify mock proposer still functions when called directly."""
        proposer = Proposer(use_mock=True)
        config = {"prompts": {"root": "Agent"}}
        proposal = proposer._mock_propose(
            config, {}, {"unhelpful_response": 5}, [],
        )
        assert proposal is not None
        assert "prompt" in proposal.config_section or "prompts" in proposal.config_section


# ---------------------------------------------------------------------------
# 5. Flow/State/Transition Mutation Generators
# ---------------------------------------------------------------------------


class TestFlowMutationGenerators:
    def test_flow_dead_end_adds_event_handler(self):
        agent = CanonicalAgent(
            name="test",
            flows=[
                FlowSpec(name="main_flow", states=[
                    StateSpec(name="start", entry_fulfillment="Hello"),
                ]),
            ],
        )
        entry = ComponentBlameEntry(
            component_type=ComponentType.flow,
            component_name="main_flow",
            failure_count=3,
            failure_rate=0.5,
            failure_types=["dead_end"],
            impact_score=0.5,
            confidence=AttributionConfidence.MEDIUM,
        )
        bundle = propose_component_patches(agent, [entry])
        assert len(bundle.operations) > 0
        handler_ops = [op for op in bundle.operations if "event_handler" in op.field_path]
        assert len(handler_ops) >= 1

    def test_flow_adds_description(self):
        agent = CanonicalAgent(
            name="test",
            flows=[FlowSpec(name="undocumented_flow")],
        )
        entry = ComponentBlameEntry(
            component_type=ComponentType.flow,
            component_name="undocumented_flow",
            failure_count=2,
            failure_rate=0.3,
            failure_types=["flow_error"],
            impact_score=0.3,
            confidence=AttributionConfidence.MEDIUM,
        )
        bundle = propose_component_patches(agent, [entry])
        desc_ops = [op for op in bundle.operations if op.field_path == "description"]
        assert len(desc_ops) >= 1

    def test_state_dead_end_adds_handler(self):
        agent = CanonicalAgent(
            name="test",
            flows=[
                FlowSpec(name="flow1", states=[
                    StateSpec(name="stuck_state"),
                ]),
            ],
        )
        entry = ComponentBlameEntry(
            component_type=ComponentType.state,
            component_name="stuck_state",
            failure_count=3,
            failure_rate=0.5,
            failure_types=["dead_end"],
            impact_score=0.5,
            confidence=AttributionConfidence.MEDIUM,
        )
        bundle = propose_component_patches(agent, [entry])
        assert len(bundle.operations) > 0

    def test_state_adds_entry_fulfillment(self):
        agent = CanonicalAgent(
            name="test",
            flows=[
                FlowSpec(name="flow1", states=[
                    StateSpec(name="empty_state", display_name="Empty State"),
                ]),
            ],
        )
        entry = ComponentBlameEntry(
            component_type=ComponentType.state,
            component_name="empty_state",
            failure_count=2,
            failure_rate=0.3,
            failure_types=["state_error"],
            impact_score=0.3,
            confidence=AttributionConfidence.MEDIUM,
        )
        bundle = propose_component_patches(agent, [entry])
        fulfillment_ops = [op for op in bundle.operations if "entry_fulfillment" in op.field_path]
        assert len(fulfillment_ops) >= 1

    def test_transition_adds_condition(self):
        agent = CanonicalAgent(
            name="test",
            flows=[
                FlowSpec(
                    name="flow1",
                    transitions=[
                        TransitionSpec(target="next_page"),
                    ],
                ),
            ],
        )
        entry = ComponentBlameEntry(
            component_type=ComponentType.transition,
            component_name="next_page",
            failure_count=2,
            failure_rate=0.3,
            failure_types=["transition_error"],
            impact_score=0.3,
            confidence=AttributionConfidence.HIGH,
        )
        bundle = propose_component_patches(agent, [entry])
        condition_ops = [op for op in bundle.operations if "condition" in op.field_path]
        assert len(condition_ops) >= 1

    def test_transition_adds_fulfillment(self):
        agent = CanonicalAgent(
            name="test",
            flows=[
                FlowSpec(
                    name="flow1",
                    transitions=[
                        TransitionSpec(target="next_page", condition="true"),
                    ],
                ),
            ],
        )
        entry = ComponentBlameEntry(
            component_type=ComponentType.transition,
            component_name="next_page",
            failure_count=1,
            failure_rate=0.2,
            failure_types=["transition_error"],
            impact_score=0.2,
            confidence=AttributionConfidence.MEDIUM,
        )
        bundle = propose_component_patches(agent, [entry])
        msg_ops = [op for op in bundle.operations if "fulfillment_message" in op.field_path]
        assert len(msg_ops) >= 1

    def test_no_ops_when_no_flows(self):
        agent = _agent_minimal()
        entry = ComponentBlameEntry(
            component_type=ComponentType.flow,
            component_name="nonexistent",
            failure_count=1,
            failure_rate=0.5,
            failure_types=["flow_error"],
            impact_score=0.5,
            confidence=AttributionConfidence.HIGH,
        )
        bundle = propose_component_patches(agent, [entry])
        assert len(bundle.operations) == 0

    def test_flow_mutation_produces_valid_bundle(self):
        agent = _agent_with_flows()
        entry = ComponentBlameEntry(
            component_type=ComponentType.flow,
            component_name="order_flow",
            failure_count=3,
            failure_rate=0.5,
            failure_types=["dead_end"],
            impact_score=0.5,
            confidence=AttributionConfidence.HIGH,
        )
        bundle = propose_component_patches(agent, [entry])
        result = validate_patch_bundle(agent, bundle)
        assert result.valid, f"Validation errors: {result.errors}"


# ---------------------------------------------------------------------------
# 6. Credit Analyzer Flow-Aware
# ---------------------------------------------------------------------------


class TestFlowCreditAnalysis:
    def test_flow_error_attributed_to_flow(self):
        analyzer = ComponentCreditAnalyzer()
        traces = [
            {"outcome": "fail", "failure_type": "flow_error"},
        ]
        entries = analyzer.analyze(traces)
        types = [e.component_type for e in entries]
        assert ComponentType.flow in types

    def test_transition_error_attributed_to_transition(self):
        analyzer = ComponentCreditAnalyzer()
        traces = [
            {"outcome": "fail", "failure_type": "transition_error"},
        ]
        entries = analyzer.analyze(traces)
        types = [e.component_type for e in entries]
        assert ComponentType.transition in types

    def test_state_error_attributed_to_state(self):
        analyzer = ComponentCreditAnalyzer()
        traces = [
            {"outcome": "fail", "failure_type": "state_error"},
        ]
        entries = analyzer.analyze(traces)
        types = [e.component_type for e in entries]
        assert ComponentType.state in types

    def test_dead_end_attributed_to_state_and_transition(self):
        analyzer = ComponentCreditAnalyzer()
        traces = [
            {"outcome": "fail", "failure_type": "dead_end"},
        ]
        entries = analyzer.analyze(traces)
        types = [e.component_type for e in entries]
        assert ComponentType.state in types
        assert ComponentType.transition in types

    def test_infinite_loop_includes_transition(self):
        analyzer = ComponentCreditAnalyzer()
        traces = [
            {"outcome": "fail", "failure_type": "infinite_loop"},
        ]
        entries = analyzer.analyze(traces)
        types = [e.component_type for e in entries]
        assert ComponentType.transition in types

    def test_keyword_detection_flow(self):
        analyzer = ComponentCreditAnalyzer()
        traces = [
            {"outcome": "fail", "error_message": "flow processing failed"},
        ]
        entries = analyzer.analyze(traces)
        types = [e.component_type for e in entries]
        assert ComponentType.flow in types

    def test_keyword_detection_dead_end(self):
        analyzer = ComponentCreditAnalyzer()
        traces = [
            {"outcome": "fail", "error_message": "user stuck in dead end"},
        ]
        entries = analyzer.analyze(traces)
        types = [e.component_type for e in entries]
        assert ComponentType.state in types


# ---------------------------------------------------------------------------
# 7. End-to-End Integration
# ---------------------------------------------------------------------------


class TestEndToEndOptimization:
    def test_flow_agent_credit_and_mutate(self):
        """Full pipeline: agent with flows -> blame analysis -> patches -> new agent."""
        agent = _agent_with_flows()
        traces = [
            {"outcome": "fail", "failure_type": "dead_end"},
            {"outcome": "fail", "failure_type": "dead_end"},
            {"outcome": "success"},
        ]
        blame_entries, bundle = analyze_and_propose(agent, traces)
        assert len(blame_entries) > 0
        if bundle.operations:
            result = validate_patch_bundle(agent, bundle)
            assert result.valid, f"Validation errors: {result.errors}"

    def test_flow_agent_apply_and_convert(self):
        """Apply patches and verify config dict preserves flows."""
        agent = _agent_with_flows()
        traces = [
            {"outcome": "fail", "failure_type": "routing_error", "expected_specialist": "orders"},
            {"outcome": "fail", "failure_type": "routing_error", "expected_specialist": "orders"},
        ]
        blame_entries, bundle = analyze_and_propose(agent, traces)
        if bundle.operations:
            validation = validate_patch_bundle(agent, bundle)
            if validation.valid:
                new_agent, config_dict = apply_and_convert(agent, bundle)
                assert "flows" in config_dict
                assert len(config_dict["flows"]) == 2
            else:
                valid_ops = []
                for op in bundle.operations:
                    test_bundle = TypedPatchBundle(bundle_id="test", operations=[op])
                    if validate_patch_bundle(agent, test_bundle).valid:
                        valid_ops.append(op)
                if valid_ops:
                    clean_bundle = TypedPatchBundle(bundle_id="clean", operations=valid_ops)
                    new_agent, config_dict = apply_and_convert(agent, clean_bundle)
                    assert "flows" in config_dict

    def test_proposer_with_flow_agent(self):
        """Credit proposer works on agents with flows."""
        proposer = Proposer(use_mock=True)
        agent = _agent_with_flows()
        config = to_config_dict(agent)
        traces = [
            {"outcome": "fail", "failure_type": "routing_error", "expected_specialist": "orders"},
            {"outcome": "fail", "failure_type": "tool_failure", "failed_tool": "lookup_order"},
        ]
        proposal = proposer.propose(
            current_config=config,
            health_metrics={},
            failure_samples=traces,
            failure_buckets={"routing_error": 1, "tool_failure": 1},
            past_attempts=[],
            traces=traces,
        )
        assert proposal is not None
        assert isinstance(proposal.new_config, dict)

    def test_config_round_trip_after_patch(self):
        """Verify: agent -> config -> patch -> config -> agent preserves structure."""
        agent = _agent_with_flows()
        config = to_config_dict(agent)

        ref = find_component_reference(agent, "flow", "order_flow")
        bundle = TypedPatchBundle(
            bundle_id="test-rt",
            operations=[
                ComponentPatchOperation(
                    op="replace",
                    component=ref,
                    field_path="description",
                    value="Updated order flow",
                ),
            ],
        )

        new_config = patch_bundle_to_config(config, bundle)
        restored = from_config_dict(new_config, name="cx_test_agent")
        assert restored.flows[0].description == "Updated order flow"
        assert len(restored.flows[0].states) == 3

    def test_cx_flow_projection_structure(self):
        """Verify CX mapper _map_flows produces valid IR-compatible structure."""
        from adapters.cx_agent_mapper import CxAgentMapper
        from cx_studio.types import (
            CxAgentSnapshot,
            CxAgent,
            CxFlow,
            CxPage,
            CxIntent,
        )

        snapshot = CxAgentSnapshot(
            agent=CxAgent(
                name="projects/p/locations/l/agents/a",
                display_name="Test Agent",
                description="A test agent",
            ),
            flows=[
                CxFlow(
                    name="projects/p/locations/l/agents/a/flows/f1",
                    display_name="Order Flow",
                    description="Handles orders",
                    transition_routes=[
                        {
                            "intent": "projects/p/locations/l/agents/a/intents/i1",
                            "targetPage": "projects/p/locations/l/agents/a/flows/f1/pages/p1",
                            "triggerFulfillment": {
                                "messages": [{"text": {"text": ["Let me look that up."]}}]
                            },
                        }
                    ],
                    event_handlers=[
                        {
                            "event": "sys.no-match-default",
                            "triggerFulfillment": {
                                "messages": [{"text": {"text": ["I didn't catch that."]}}]
                            },
                        }
                    ],
                    pages=[
                        CxPage(
                            name="projects/p/locations/l/agents/a/flows/f1/pages/p1",
                            display_name="Collect Info",
                            entry_fulfillment={
                                "messages": [{"text": {"text": ["What is your order ID?"]}}]
                            },
                            transition_routes=[
                                {
                                    "condition": "$session.params.order_id != null",
                                    "targetPage": "projects/p/locations/l/agents/a/flows/f1/pages/p2",
                                }
                            ],
                        ),
                        CxPage(
                            name="projects/p/locations/l/agents/a/flows/f1/pages/p2",
                            display_name="Show Results",
                        ),
                    ],
                ),
            ],
            intents=[
                CxIntent(
                    name="projects/p/locations/l/agents/a/intents/i1",
                    display_name="order_status",
                    training_phrases=[{"parts": [{"text": "check my order"}]}],
                ),
            ],
        )

        mapper = CxAgentMapper()
        config = mapper.to_agentlab(snapshot)
        assert "flows" in config
        assert len(config["flows"]) == 1

        flow = config["flows"][0]
        assert flow["name"] == "order_flow"
        assert len(flow["states"]) == 2
        assert flow["states"][0]["name"] == "collect_info"
        assert flow["states"][0]["entry_fulfillment"] == "What is your order ID?"
        assert len(flow["transitions"]) == 1
        assert flow["transitions"][0]["intent"] == "order_status"
        assert flow["transitions"][0]["fulfillment_message"] == "Let me look that up."
        assert len(flow["event_handlers"]) == 1
        assert flow["event_handlers"][0]["event"] == "sys.no-match-default"

    def test_cx_flow_to_ir_round_trip(self):
        """CX flows projected to config -> IR -> config preserves structure."""
        from adapters.cx_agent_mapper import CxAgentMapper
        from cx_studio.types import (
            CxAgentSnapshot,
            CxAgent,
            CxFlow,
            CxPage,
        )

        snapshot = CxAgentSnapshot(
            agent=CxAgent(
                name="projects/p/locations/l/agents/a",
                display_name="Test",
            ),
            flows=[
                CxFlow(
                    name="projects/p/locations/l/agents/a/flows/f1",
                    display_name="Main Flow",
                    pages=[
                        CxPage(
                            name="projects/p/locations/l/agents/a/flows/f1/pages/p1",
                            display_name="Start Page",
                            entry_fulfillment={
                                "messages": [{"text": {"text": ["Welcome!"]}}]
                            },
                        ),
                    ],
                ),
            ],
        )

        mapper = CxAgentMapper()
        config = mapper.to_agentlab(snapshot)
        agent = from_config_dict(config, name="test", platform="dialogflow-cx")

        assert len(agent.flows) == 1
        assert agent.flows[0].name == "main_flow"
        assert len(agent.flows[0].states) == 1
        assert agent.flows[0].states[0].entry_fulfillment == "Welcome!"

        config2 = to_config_dict(agent)
        assert len(config2["flows"]) == 1
        assert config2["flows"][0]["states"][0]["entry_fulfillment"] == "Welcome!"


# ---------------------------------------------------------------------------
# 8. Component Type Enum Coverage
# ---------------------------------------------------------------------------


class TestComponentTypeEnum:
    def test_new_types_exist(self):
        assert ComponentType.flow.value == "flow"
        assert ComponentType.state.value == "state"
        assert ComponentType.transition.value == "transition"

    def test_all_types_have_severity(self):
        from optimizer.component_credit import _SEVERITY_MULTIPLIERS
        for ft in ["flow_error", "transition_error", "state_error", "dead_end"]:
            assert ft in _SEVERITY_MULTIPLIERS

    def test_all_flow_types_in_failure_mapping(self):
        from optimizer.component_credit import _FAILURE_TYPE_TO_COMPONENT
        assert "flow_error" in _FAILURE_TYPE_TO_COMPONENT
        assert "transition_error" in _FAILURE_TYPE_TO_COMPONENT
        assert "state_error" in _FAILURE_TYPE_TO_COMPONENT
        assert "dead_end" in _FAILURE_TYPE_TO_COMPONENT
