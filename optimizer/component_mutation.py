"""Component-aware mutation proposals for canonical IR optimization.

Bridges the component credit analyzer to typed patch bundles. Given a
CanonicalAgent and failure analysis, produces concrete PatchBundle proposals
targeting the blamed components.

This module is the core "breadth expansion" — it enables the optimizer to
propose changes to guardrails, handoffs, routing rules, tool contracts,
policies, and callbacks, not just prompt text.

Layer: optimizer. Imports from shared/canonical_ir, component_patch,
component_credit.
"""

from __future__ import annotations

import copy
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

from .component_credit import (
    AttributionConfidence,
    ComponentBlameEntry,
    ComponentCreditAnalyzer,
)
from .component_patch import (
    ComponentPatch,
    ComponentRef,
    ComponentType,
    PatchBundle,
    PatchOperation,
)


def propose_component_patches(
    agent: CanonicalAgent,
    blame_entries: list[ComponentBlameEntry],
    *,
    past_bundle_surfaces: list[str] | None = None,
    max_patches: int = 5,
) -> PatchBundle:
    """Generate a PatchBundle from component-level blame analysis.

    Examines the top blame entries and produces targeted patches for each
    blamed component type. Avoids proposing patches for surfaces that were
    recently patched (via ``past_bundle_surfaces``).

    Args:
        agent: The current canonical agent to mutate.
        blame_entries: Sorted blame entries from ComponentCreditAnalyzer.
        past_bundle_surfaces: Component type values recently patched (to avoid repetition).
        max_patches: Maximum number of patches to include.

    Returns:
        A PatchBundle with concrete patches. May be empty if no actionable
        blame entries exist.
    """
    past = set(past_bundle_surfaces or [])
    patches: list[ComponentPatch] = []
    descriptions: list[str] = []
    max_risk = "low"

    for entry in blame_entries:
        if len(patches) >= max_patches:
            break
        if entry.component_type.value in past:
            continue
        if entry.impact_score < 0.01:
            continue

        new_patches = _patches_for_entry(agent, entry)
        for p in new_patches:
            if len(patches) >= max_patches:
                break
            patches.append(p)
            descriptions.append(p.reasoning)

        if entry.confidence in (AttributionConfidence.HIGH, AttributionConfidence.MEDIUM):
            if entry.impact_score > 0.3:
                max_risk = "medium"
        if any(ft == "safety_violation" for ft in entry.failure_types):
            max_risk = "high"

    if not patches:
        return PatchBundle(description="no actionable blame entries")

    return PatchBundle(
        patches=patches,
        description="; ".join(descriptions[:3]),
        risk_class=max_risk,
        metadata={"blame_entry_count": len(blame_entries)},
    )


def analyze_and_propose(
    agent: CanonicalAgent,
    traces: list[dict[str, Any]],
    *,
    past_bundle_surfaces: list[str] | None = None,
    max_patches: int = 5,
) -> tuple[list[ComponentBlameEntry], PatchBundle]:
    """End-to-end: analyze traces for component blame, then propose patches.

    Convenience function combining ComponentCreditAnalyzer + propose_component_patches.

    Returns:
        (blame_entries, patch_bundle) tuple.
    """
    component_names: dict[str, list[str]] = {
        "tool": agent.tool_names(),
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
    bundle: PatchBundle,
) -> tuple[CanonicalAgent, dict[str, Any]]:
    """Apply a patch bundle and convert the result to a flat config dict.

    Returns:
        (new_agent, config_dict) — the new agent and its flat config
        representation for the existing eval pipeline.
    """
    new_agent = bundle.apply(agent)
    config_dict = to_config_dict(new_agent)
    return new_agent, config_dict


# ---------------------------------------------------------------------------
# Per-component-type patch generators
# ---------------------------------------------------------------------------


def _patches_for_entry(
    agent: CanonicalAgent,
    entry: ComponentBlameEntry,
) -> list[ComponentPatch]:
    """Dispatch to the appropriate patch generator for a blame entry."""
    generators: dict[ComponentType, Any] = {
        ComponentType.routing_rule: _patches_for_routing,
        ComponentType.tool: _patches_for_tool,
        ComponentType.guardrail: _patches_for_guardrail,
        ComponentType.instruction: _patches_for_instruction,
        ComponentType.handoff: _patches_for_handoff,
        ComponentType.policy: _patches_for_policy,
        ComponentType.environment: _patches_for_environment,
    }
    gen = generators.get(entry.component_type)
    if gen is None:
        return []
    return gen(agent, entry)


def _patches_for_routing(
    agent: CanonicalAgent,
    entry: ComponentBlameEntry,
) -> list[ComponentPatch]:
    """Generate patches for routing rule failures."""
    patches: list[ComponentPatch] = []

    if entry.component_name:
        for i, rule in enumerate(agent.routing_rules):
            if rule.target == entry.component_name:
                new_keywords = list(rule.keywords)
                target_lower = entry.component_name.lower().replace("_", " ").replace("-", " ")
                for word in target_lower.split():
                    if len(word) >= 3 and word not in new_keywords:
                        new_keywords.append(word)
                if new_keywords != list(rule.keywords):
                    patches.append(ComponentPatch(
                        operation=PatchOperation.modify,
                        ref=ComponentRef(ComponentType.routing_rule, index=i, name=rule.target),
                        old_value={"keywords": list(rule.keywords)},
                        new_value={"keywords": new_keywords},
                        reasoning=f"Expand keywords for routing target '{rule.target}' to reduce routing errors",
                    ))
                break
    else:
        if not agent.routing_rules:
            patches.append(ComponentPatch(
                operation=PatchOperation.add,
                ref=ComponentRef(ComponentType.routing_rule),
                new_value={
                    "target": "default",
                    "condition_type": ConditionType.ALWAYS.value,
                    "fallback": True,
                    "priority": -1,
                },
                reasoning="Add fallback routing rule to handle unmatched messages",
            ))
        else:
            has_fallback = any(r.fallback for r in agent.routing_rules)
            if not has_fallback:
                patches.append(ComponentPatch(
                    operation=PatchOperation.add,
                    ref=ComponentRef(ComponentType.routing_rule),
                    new_value={
                        "target": agent.routing_rules[0].target,
                        "condition_type": ConditionType.ALWAYS.value,
                        "fallback": True,
                        "priority": -1,
                    },
                    reasoning="Add fallback routing rule to prevent routing failures on unmatched messages",
                ))

    return patches


def _patches_for_tool(
    agent: CanonicalAgent,
    entry: ComponentBlameEntry,
) -> list[ComponentPatch]:
    """Generate patches for tool failures."""
    patches: list[ComponentPatch] = []

    if entry.component_name:
        for i, tool in enumerate(agent.tools):
            if tool.name == entry.component_name:
                current_timeout = tool.timeout_ms or 5000
                new_timeout = current_timeout + 2000
                patches.append(ComponentPatch(
                    operation=PatchOperation.modify,
                    ref=ComponentRef(ComponentType.tool, index=i, name=tool.name),
                    old_value={"timeout_ms": tool.timeout_ms},
                    new_value={"timeout_ms": new_timeout},
                    reasoning=f"Increase timeout for tool '{tool.name}' from {current_timeout}ms to {new_timeout}ms to reduce failures",
                ))

                if not tool.description:
                    patches.append(ComponentPatch(
                        operation=PatchOperation.modify,
                        ref=ComponentRef(ComponentType.tool, index=i, name=tool.name),
                        old_value={"description": ""},
                        new_value={"description": f"Tool for {tool.name.replace('_', ' ')} operations"},
                        reasoning=f"Add description to tool '{tool.name}' to improve tool selection accuracy",
                    ))
                break
    else:
        for i, tool in enumerate(agent.tools):
            if tool.timeout_ms and tool.timeout_ms < 5000:
                patches.append(ComponentPatch(
                    operation=PatchOperation.modify,
                    ref=ComponentRef(ComponentType.tool, index=i, name=tool.name),
                    old_value={"timeout_ms": tool.timeout_ms},
                    new_value={"timeout_ms": 5000},
                    reasoning=f"Increase low timeout for tool '{tool.name}' to minimum 5000ms",
                ))
                break

    return patches


def _patches_for_guardrail(
    agent: CanonicalAgent,
    entry: ComponentBlameEntry,
) -> list[ComponentPatch]:
    """Generate patches for guardrail-related failures (typically safety violations)."""
    patches: list[ComponentPatch] = []
    has_safety = any("safety" in ft for ft in entry.failure_types)

    if entry.component_name:
        for i, g in enumerate(agent.guardrails):
            if g.name == entry.component_name:
                if g.enforcement != GuardrailEnforcement.BLOCK and has_safety:
                    patches.append(ComponentPatch(
                        operation=PatchOperation.modify,
                        ref=ComponentRef(ComponentType.guardrail, index=i, name=g.name),
                        old_value={"enforcement": g.enforcement.value},
                        new_value={"enforcement": GuardrailEnforcement.BLOCK.value},
                        reasoning=f"Upgrade guardrail '{g.name}' enforcement to BLOCK due to safety violations",
                    ))
                break
    else:
        if has_safety and not agent.guardrails:
            patches.append(ComponentPatch(
                operation=PatchOperation.add,
                ref=ComponentRef(ComponentType.guardrail),
                new_value={
                    "name": "safety_gate",
                    "type": GuardrailType.BOTH.value,
                    "description": "Block harmful, illegal, or dangerous requests and responses",
                    "enforcement": GuardrailEnforcement.BLOCK.value,
                    "condition": "content contains harmful or dangerous material",
                },
                reasoning="Add safety guardrail to address safety violations",
            ))
        elif has_safety:
            for i, g in enumerate(agent.guardrails):
                if g.enforcement != GuardrailEnforcement.BLOCK:
                    patches.append(ComponentPatch(
                        operation=PatchOperation.modify,
                        ref=ComponentRef(ComponentType.guardrail, index=i, name=g.name),
                        old_value={"enforcement": g.enforcement.value},
                        new_value={"enforcement": GuardrailEnforcement.BLOCK.value},
                        reasoning=f"Upgrade guardrail '{g.name}' to BLOCK enforcement for safety",
                    ))
                    break

    return patches


def _patches_for_instruction(
    agent: CanonicalAgent,
    entry: ComponentBlameEntry,
) -> list[ComponentPatch]:
    """Generate patches for instruction-related failures (hallucination, quality)."""
    patches: list[ComponentPatch] = []
    has_hallucination = "hallucination" in entry.failure_types

    if has_hallucination:
        constraint_exists = any(
            i.role == InstructionRole.CONSTRAINT for i in agent.instructions
        )
        if not constraint_exists:
            patches.append(ComponentPatch(
                operation=PatchOperation.add,
                ref=ComponentRef(ComponentType.instruction),
                new_value={
                    "role": InstructionRole.CONSTRAINT.value,
                    "content": "Always verify factual claims before stating them. If unsure, say so explicitly.",
                    "priority": 10,
                    "label": "anti_hallucination",
                },
                reasoning="Add anti-hallucination constraint instruction to reduce hallucination rate",
            ))
    else:
        if agent.instructions:
            primary = max(agent.instructions, key=lambda i: i.priority)
            idx = agent.instructions.index(primary)
            suffix = " Be thorough and verify your answer before responding."
            if suffix not in primary.content:
                patches.append(ComponentPatch(
                    operation=PatchOperation.modify,
                    ref=ComponentRef(ComponentType.instruction, index=idx, name=primary.label),
                    old_value={"content": primary.content},
                    new_value={"content": primary.content + suffix},
                    reasoning="Enhance primary instruction with verification requirement",
                ))
        else:
            patches.append(ComponentPatch(
                operation=PatchOperation.add,
                ref=ComponentRef(ComponentType.instruction),
                new_value={
                    "role": InstructionRole.SYSTEM.value,
                    "content": "You are a helpful assistant. Be thorough and verify your answer before responding.",
                    "priority": 0,
                    "label": "root",
                },
                reasoning="Add root system instruction to improve response quality",
            ))

    return patches


def _patches_for_handoff(
    agent: CanonicalAgent,
    entry: ComponentBlameEntry,
) -> list[ComponentPatch]:
    """Generate patches for handoff-related failures."""
    patches: list[ComponentPatch] = []

    if entry.component_name:
        for i, h in enumerate(agent.handoffs):
            if h.target == entry.component_name:
                if h.context_transfer != ContextTransfer.FULL:
                    patches.append(ComponentPatch(
                        operation=PatchOperation.modify,
                        ref=ComponentRef(ComponentType.handoff, index=i, name=h.target),
                        old_value={"context_transfer": h.context_transfer.value},
                        new_value={"context_transfer": ContextTransfer.FULL.value},
                        reasoning=f"Upgrade handoff to '{h.target}' to FULL context transfer to prevent information loss",
                    ))
                if not h.condition:
                    patches.append(ComponentPatch(
                        operation=PatchOperation.modify,
                        ref=ComponentRef(ComponentType.handoff, index=i, name=h.target),
                        old_value={"condition": ""},
                        new_value={"condition": "when specialized assistance is needed"},
                        reasoning=f"Add condition to handoff to '{h.target}' to prevent spurious transfers",
                    ))
                break

    return patches


def _patches_for_policy(
    agent: CanonicalAgent,
    entry: ComponentBlameEntry,
) -> list[ComponentPatch]:
    """Generate patches for policy-related failures."""
    patches: list[ComponentPatch] = []

    if "safety_violation" in entry.failure_types:
        has_safety_policy = any(
            p.type == PolicyType.SAFETY for p in agent.policies
        )
        if not has_safety_policy:
            patches.append(ComponentPatch(
                operation=PatchOperation.add,
                ref=ComponentRef(ComponentType.policy),
                new_value={
                    "name": "safety_compliance",
                    "type": PolicyType.SAFETY.value,
                    "description": "Refuse harmful, illegal, or dangerous requests",
                    "enforcement": PolicyEnforcement.REQUIRED.value,
                },
                reasoning="Add required safety policy to address safety violations",
            ))
        else:
            for i, p in enumerate(agent.policies):
                if p.type == PolicyType.SAFETY and p.enforcement != PolicyEnforcement.REQUIRED:
                    patches.append(ComponentPatch(
                        operation=PatchOperation.modify,
                        ref=ComponentRef(ComponentType.policy, index=i, name=p.name),
                        old_value={"enforcement": p.enforcement.value},
                        new_value={"enforcement": PolicyEnforcement.REQUIRED.value},
                        reasoning=f"Upgrade safety policy '{p.name}' enforcement to REQUIRED",
                    ))
                    break

    return patches


def _patches_for_environment(
    agent: CanonicalAgent,
    entry: ComponentBlameEntry,
) -> list[ComponentPatch]:
    """Generate patches for environment-related failures (timeouts)."""
    patches: list[ComponentPatch] = []

    if "timeout" in entry.failure_types:
        current_max = agent.environment.max_tokens
        if current_max and current_max > 2000:
            new_max = max(1000, current_max - 500)
            patches.append(ComponentPatch(
                operation=PatchOperation.modify,
                ref=ComponentRef(ComponentType.environment),
                old_value={"max_tokens": current_max},
                new_value={"max_tokens": new_max},
                reasoning=f"Reduce max_tokens from {current_max} to {new_max} to prevent timeouts",
            ))

        current_temp = agent.environment.temperature
        if current_temp is not None and current_temp > 0.5:
            new_temp = round(current_temp - 0.2, 2)
            patches.append(ComponentPatch(
                operation=PatchOperation.modify,
                ref=ComponentRef(ComponentType.environment),
                old_value={"temperature": current_temp},
                new_value={"temperature": new_temp},
                reasoning=f"Lower temperature from {current_temp} to {new_temp} for more deterministic responses",
            ))

    return patches
