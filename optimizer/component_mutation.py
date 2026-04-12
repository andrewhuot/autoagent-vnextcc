"""Component-aware mutation proposals for canonical IR optimization.

Bridges component credit analysis to typed patch bundles targeting the
Codex-authoritative shared/canonical_patch.py types.  Given a CanonicalAgent
and trace-based failure analysis, produces concrete TypedPatchBundle proposals
targeting the blamed components.

Ported from the Claude optimization-breadth branch and adapted to produce
Codex TypedPatchBundle/ComponentPatchOperation/ComponentReference types
instead of the parallel Claude PatchBundle/ComponentPatch/ComponentRef types.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

from shared.canonical_ir import (
    CanonicalAgent,
    ConditionType,
    ContextTransfer,
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
from shared.canonical_ir_convert import to_config_dict
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

from .component_credit import (
    AttributionConfidence,
    ComponentBlameEntry,
    ComponentCreditAnalyzer,
    ComponentType,
)


def propose_component_patches(
    agent: CanonicalAgent,
    blame_entries: list[ComponentBlameEntry],
    *,
    past_bundle_surfaces: list[str] | None = None,
    max_patches: int = 5,
) -> TypedPatchBundle:
    """Generate a TypedPatchBundle from component-level blame analysis.

    Examines the top blame entries and produces targeted patches for each
    blamed component type.  Avoids proposing patches for surfaces that were
    recently patched (via ``past_bundle_surfaces``).
    """
    past = set(past_bundle_surfaces or [])
    operations: list[ComponentPatchOperation] = []
    descriptions: list[str] = []
    max_risk = "low"

    for entry in blame_entries:
        if len(operations) >= max_patches:
            break
        if entry.component_type.value in past:
            continue
        if entry.impact_score < 0.01:
            continue

        new_ops = _ops_for_entry(agent, entry)
        for op in new_ops:
            if len(operations) >= max_patches:
                break
            operations.append(op)
            descriptions.append(op.rationale)

        if entry.confidence in (AttributionConfidence.HIGH, AttributionConfidence.MEDIUM):
            if entry.impact_score > 0.3:
                max_risk = "medium"
        if any(ft == "safety_violation" for ft in entry.failure_types):
            max_risk = "high"

    if not operations:
        return TypedPatchBundle(
            bundle_id=f"empty-{uuid.uuid4().hex[:8]}",
            title="no actionable blame entries",
        )

    return TypedPatchBundle(
        bundle_id=f"mutation-{uuid.uuid4().hex[:8]}",
        title="; ".join(descriptions[:3]),
        operations=operations,
        source="component_mutation",
        metadata={
            "blame_entry_count": len(blame_entries),
            "risk_class": max_risk,
        },
    )


def analyze_and_propose(
    agent: CanonicalAgent,
    traces: list[dict[str, Any]],
    *,
    past_bundle_surfaces: list[str] | None = None,
    max_patches: int = 5,
) -> tuple[list[ComponentBlameEntry], TypedPatchBundle]:
    """End-to-end: analyze traces for component blame, then propose patches.

    Returns (blame_entries, patch_bundle) tuple.
    """
    component_names: dict[str, list[str]] = {
        "tool_contract": agent.tool_names(),
        "guardrail": agent.guardrail_names(),
        "routing_rule": [r.target for r in agent.routing_rules],
        "handoff": agent.handoff_targets(),
        "sub_agent": agent.sub_agent_names(),
    }

    analyzer = ComponentCreditAnalyzer()
    blame_entries = analyzer.analyze(traces, component_names)

    bundle = propose_component_patches(
        agent,
        blame_entries,
        past_bundle_surfaces=past_bundle_surfaces,
        max_patches=max_patches,
    )

    return blame_entries, bundle


def apply_and_convert(
    agent: CanonicalAgent,
    bundle: TypedPatchBundle,
) -> tuple[CanonicalAgent, dict[str, Any]]:
    """Apply a patch bundle and convert the result to a flat config dict.

    Returns (new_agent, config_dict).
    """
    new_agent = apply_patch_bundle(agent, bundle)
    config_dict = to_config_dict(new_agent)
    return new_agent, config_dict


# ---------------------------------------------------------------------------
# Per-component-type operation generators
# ---------------------------------------------------------------------------


def _ops_for_entry(
    agent: CanonicalAgent,
    entry: ComponentBlameEntry,
) -> list[ComponentPatchOperation]:
    """Dispatch to the appropriate operation generator for a blame entry.

    callback, sub_agent, and mcp_server are intentionally unhandled in v1 —
    they need richer context (sub-agent graph, MCP config) to mutate safely.
    """
    generators = {
        ComponentType.routing_rule: _ops_for_routing,
        ComponentType.tool_contract: _ops_for_tool,
        ComponentType.guardrail: _ops_for_guardrail,
        ComponentType.instruction: _ops_for_instruction,
        ComponentType.handoff: _ops_for_handoff,
        ComponentType.policy: _ops_for_policy,
        ComponentType.environment: _ops_for_environment,
    }
    gen = generators.get(entry.component_type)
    if gen is None:
        return []
    return gen(agent, entry)


def _find_ref(agent: CanonicalAgent, component_type: str, name: str) -> ComponentReference | None:
    """Find a component reference by type and name."""
    return find_component_reference(agent, component_type, name)


def _ref_by_index(agent: CanonicalAgent, component_type: str, index: int) -> ComponentReference | None:
    """Find a component reference by type and list position."""
    refs = [r for r in iter_component_references(agent) if r.component_type == component_type]
    if 0 <= index < len(refs):
        return refs[index]
    return None


def _ops_for_routing(
    agent: CanonicalAgent,
    entry: ComponentBlameEntry,
) -> list[ComponentPatchOperation]:
    ops: list[ComponentPatchOperation] = []

    if entry.component_name:
        ref = _find_ref(agent, "routing_rule", entry.component_name)
        if ref is not None:
            for i, rule in enumerate(agent.routing_rules):
                if rule.target == entry.component_name:
                    new_keywords = list(rule.keywords)
                    target_lower = entry.component_name.lower().replace("_", " ").replace("-", " ")
                    for word in target_lower.split():
                        if len(word) >= 3 and word not in new_keywords:
                            new_keywords.append(word)
                    if new_keywords != list(rule.keywords):
                        ops.append(ComponentPatchOperation(
                            op="replace",
                            component=ref,
                            field_path="keywords",
                            value=new_keywords,
                            rationale=f"Expand keywords for routing target '{rule.target}' to reduce routing errors",
                        ))
                    break
    else:
        if not agent.routing_rules:
            env_ref = _find_ref(agent, "environment", "environment")
            if env_ref is not None:
                ops.append(ComponentPatchOperation(
                    op="add",
                    component=ComponentReference(
                        component_id="root:routing_rule:default",
                        component_type="routing_rule",
                        name="default",
                        path="/routing_rules/0",
                    ),
                    value={
                        "target": "default",
                        "condition_type": ConditionType.ALWAYS.value,
                        "fallback": True,
                        "priority": -1,
                    },
                    rationale="Add fallback routing rule to handle unmatched messages",
                ))
        else:
            has_fallback = any(r.fallback for r in agent.routing_rules)
            if not has_fallback:
                insert_path = f"/routing_rules/{len(agent.routing_rules)}"
                ops.append(ComponentPatchOperation(
                    op="add",
                    component=ComponentReference(
                        component_id=f"root:routing_rule:{agent.routing_rules[0].target}",
                        component_type="routing_rule",
                        name=agent.routing_rules[0].target,
                        path=insert_path,
                    ),
                    value={
                        "target": agent.routing_rules[0].target,
                        "condition_type": ConditionType.ALWAYS.value,
                        "fallback": True,
                        "priority": -1,
                    },
                    rationale="Add fallback routing rule to prevent routing failures on unmatched messages",
                ))

    return ops


def _ops_for_tool(
    agent: CanonicalAgent,
    entry: ComponentBlameEntry,
) -> list[ComponentPatchOperation]:
    ops: list[ComponentPatchOperation] = []

    if entry.component_name:
        ref = _find_ref(agent, "tool_contract", entry.component_name)
        if ref is not None:
            for tool in agent.tools:
                if tool.name == entry.component_name:
                    current_timeout = tool.timeout_ms or 5000
                    new_timeout = current_timeout + 2000
                    ops.append(ComponentPatchOperation(
                        op="replace",
                        component=ref,
                        field_path="timeout_ms",
                        value=new_timeout,
                        rationale=f"Increase timeout for tool '{tool.name}' from {current_timeout}ms to {new_timeout}ms to reduce failures",
                    ))
                    if not tool.description:
                        ops.append(ComponentPatchOperation(
                            op="set",
                            component=ref,
                            field_path="description",
                            value=f"Tool for {tool.name.replace('_', ' ')} operations",
                            rationale=f"Add description to tool '{tool.name}' to improve tool selection accuracy",
                        ))
                    break
    else:
        for i, tool in enumerate(agent.tools):
            if tool.timeout_ms and tool.timeout_ms < 5000:
                ref = _ref_by_index(agent, "tool_contract", i)
                if ref is not None:
                    ops.append(ComponentPatchOperation(
                        op="replace",
                        component=ref,
                        field_path="timeout_ms",
                        value=5000,
                        rationale=f"Increase low timeout for tool '{tool.name}' to minimum 5000ms",
                    ))
                break

    return ops


def _ops_for_guardrail(
    agent: CanonicalAgent,
    entry: ComponentBlameEntry,
) -> list[ComponentPatchOperation]:
    ops: list[ComponentPatchOperation] = []
    has_safety = any("safety" in ft for ft in entry.failure_types)

    if entry.component_name:
        ref = _find_ref(agent, "guardrail", entry.component_name)
        if ref is not None:
            for g in agent.guardrails:
                if g.name == entry.component_name:
                    if g.enforcement != GuardrailEnforcement.BLOCK and has_safety:
                        ops.append(ComponentPatchOperation(
                            op="replace",
                            component=ref,
                            field_path="enforcement",
                            value=GuardrailEnforcement.BLOCK.value,
                            rationale=f"Upgrade guardrail '{g.name}' enforcement to BLOCK due to safety violations",
                        ))
                    break
    else:
        if has_safety and not agent.guardrails:
            ops.append(ComponentPatchOperation(
                op="add",
                component=ComponentReference(
                    component_id="root:guardrail:safety_gate",
                    component_type="guardrail",
                    name="safety_gate",
                    path="/guardrails/0",
                ),
                value={
                    "name": "safety_gate",
                    "type": GuardrailType.BOTH.value,
                    "description": "Block harmful, illegal, or dangerous requests and responses",
                    "enforcement": GuardrailEnforcement.BLOCK.value,
                    "condition": "content contains harmful or dangerous material",
                },
                rationale="Add safety guardrail to address safety violations",
            ))
        elif has_safety:
            for i, g in enumerate(agent.guardrails):
                if g.enforcement != GuardrailEnforcement.BLOCK:
                    ref = _ref_by_index(agent, "guardrail", i)
                    if ref is not None:
                        ops.append(ComponentPatchOperation(
                            op="replace",
                            component=ref,
                            field_path="enforcement",
                            value=GuardrailEnforcement.BLOCK.value,
                            rationale=f"Upgrade guardrail '{g.name}' to BLOCK enforcement for safety",
                        ))
                    break

    return ops


def _ops_for_instruction(
    agent: CanonicalAgent,
    entry: ComponentBlameEntry,
) -> list[ComponentPatchOperation]:
    ops: list[ComponentPatchOperation] = []
    has_hallucination = "hallucination" in entry.failure_types

    if has_hallucination:
        constraint_exists = any(
            i.role == InstructionRole.CONSTRAINT for i in agent.instructions
        )
        if not constraint_exists:
            ops.append(ComponentPatchOperation(
                op="add",
                component=ComponentReference(
                    component_id="root:instruction:anti_hallucination",
                    component_type="instruction",
                    name="anti_hallucination",
                    path=f"/instructions/{len(agent.instructions)}",
                ),
                value={
                    "role": InstructionRole.CONSTRAINT.value,
                    "content": "Always verify factual claims before stating them. If unsure, say so explicitly.",
                    "priority": 10,
                    "label": "anti_hallucination",
                },
                rationale="Add anti-hallucination constraint instruction to reduce hallucination rate",
            ))
    else:
        if agent.instructions:
            primary = max(agent.instructions, key=lambda i: i.priority)
            ref = _find_ref(agent, "instruction", primary.label or "")
            if ref is None:
                idx = agent.instructions.index(primary)
                ref = _ref_by_index(agent, "instruction", idx)
            if ref is not None:
                suffix = " Be thorough and verify your answer before responding."
                if suffix not in primary.content:
                    ops.append(ComponentPatchOperation(
                        op="replace",
                        component=ref,
                        field_path="content",
                        value=primary.content + suffix,
                        rationale="Enhance primary instruction with verification requirement",
                    ))
        else:
            ops.append(ComponentPatchOperation(
                op="add",
                component=ComponentReference(
                    component_id="root:instruction:root",
                    component_type="instruction",
                    name="root",
                    path="/instructions/0",
                ),
                value={
                    "role": InstructionRole.SYSTEM.value,
                    "content": "You are a helpful assistant. Be thorough and verify your answer before responding.",
                    "priority": 0,
                    "label": "root",
                },
                rationale="Add root system instruction to improve response quality",
            ))

    return ops


def _ops_for_handoff(
    agent: CanonicalAgent,
    entry: ComponentBlameEntry,
) -> list[ComponentPatchOperation]:
    ops: list[ComponentPatchOperation] = []

    if entry.component_name:
        for h in agent.handoffs:
            if h.target == entry.component_name:
                handoff_name = f"{h.source}->{h.target}" if h.source else h.target
                ref = _find_ref(agent, "handoff", handoff_name)
                if ref is not None:
                    if h.context_transfer != ContextTransfer.FULL:
                        ops.append(ComponentPatchOperation(
                            op="replace",
                            component=ref,
                            field_path="context_transfer",
                            value=ContextTransfer.FULL.value,
                            rationale=f"Upgrade handoff to '{h.target}' to FULL context transfer to prevent information loss",
                        ))
                    if not h.condition:
                        ops.append(ComponentPatchOperation(
                            op="set",
                            component=ref,
                            field_path="condition",
                            value="when specialized assistance is needed",
                            rationale=f"Add condition to handoff to '{h.target}' to prevent spurious transfers",
                        ))
                break

    return ops


def _ops_for_policy(
    agent: CanonicalAgent,
    entry: ComponentBlameEntry,
) -> list[ComponentPatchOperation]:
    ops: list[ComponentPatchOperation] = []

    if "safety_violation" in entry.failure_types:
        has_safety_policy = any(
            p.type == PolicyType.SAFETY for p in agent.policies
        )
        if not has_safety_policy:
            ops.append(ComponentPatchOperation(
                op="add",
                component=ComponentReference(
                    component_id="root:policy:safety_compliance",
                    component_type="policy",
                    name="safety_compliance",
                    path=f"/policies/{len(agent.policies)}",
                ),
                value={
                    "name": "safety_compliance",
                    "type": PolicyType.SAFETY.value,
                    "description": "Refuse harmful, illegal, or dangerous requests",
                    "enforcement": PolicyEnforcement.REQUIRED.value,
                },
                rationale="Add required safety policy to address safety violations",
            ))
        else:
            for i, p in enumerate(agent.policies):
                if p.type == PolicyType.SAFETY and p.enforcement != PolicyEnforcement.REQUIRED:
                    ref = _find_ref(agent, "policy", p.name)
                    if ref is not None:
                        ops.append(ComponentPatchOperation(
                            op="replace",
                            component=ref,
                            field_path="enforcement",
                            value=PolicyEnforcement.REQUIRED.value,
                            rationale=f"Upgrade safety policy '{p.name}' enforcement to REQUIRED",
                        ))
                    break

    return ops


def _ops_for_environment(
    agent: CanonicalAgent,
    entry: ComponentBlameEntry,
) -> list[ComponentPatchOperation]:
    ops: list[ComponentPatchOperation] = []

    if "timeout" in entry.failure_types:
        ref = _find_ref(agent, "environment", "environment")
        if ref is not None:
            current_max = agent.environment.max_tokens
            if current_max and current_max > 2000:
                new_max = max(1000, current_max - 500)
                ops.append(ComponentPatchOperation(
                    op="replace",
                    component=ref,
                    field_path="max_tokens",
                    value=new_max,
                    rationale=f"Reduce max_tokens from {current_max} to {new_max} to prevent timeouts",
                ))

            current_temp = agent.environment.temperature
            if current_temp is not None and current_temp > 0.5:
                new_temp = round(current_temp - 0.2, 2)
                ops.append(ComponentPatchOperation(
                    op="replace",
                    component=ref,
                    field_path="temperature",
                    value=new_temp,
                    rationale=f"Lower temperature from {current_temp} to {new_temp} for more deterministic responses",
                ))

    return ops
