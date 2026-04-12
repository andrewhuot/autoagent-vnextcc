"""Component-aware credit assignment for eval failures."""

from __future__ import annotations

from typing import Any

from evals.scorer import EvalResult
from shared.canonical_ir import CanonicalAgent, PolicyType
from shared.canonical_ir_convert import from_config_dict
from shared.canonical_patch import (
    ComponentAttribution,
    ComponentReference,
    find_component_reference,
    iter_component_references,
)


def attribute_eval_failure(
    *,
    case: Any,
    agent_result: dict[str, Any],
    eval_result: EvalResult,
    config: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Link one eval failure to concrete canonical graph components.

    WHY: optimizer feedback based only on generic failure buckets cannot tell a
    reviewer whether the fix belongs in routing, a tool contract, a guardrail,
    a handoff, or a prompt.  These attributions create that reviewable bridge.
    """

    if eval_result.passed and not eval_result.failure_reasons:
        return []

    agent = from_config_dict(config or {}, name="root")
    attributions: list[ComponentAttribution] = []
    reasons = set(eval_result.failure_reasons or [])

    if "routing mismatch" in reasons:
        target = str(getattr(case, "expected_specialist", "") or "")
        ref = _routing_component(agent, target)
        if ref is not None:
            attributions.append(
                _attribution(
                    ref,
                    "routing mismatch",
                    {
                        "expected_specialist": target,
                        "actual_specialist": agent_result.get("specialist_used", ""),
                        "case_id": eval_result.case_id,
                    },
                    0.9,
                )
            )

    if "tool mismatch" in reasons:
        expected_tool = str(getattr(case, "expected_tool", "") or "").strip()
        ref = _tool_component(agent, expected_tool)
        if ref is not None:
            attributions.append(
                _attribution(
                    ref,
                    "tool mismatch",
                    {
                        "expected_tool": expected_tool,
                        "observed_tools": _observed_tools(agent_result),
                        "case_id": eval_result.case_id,
                    },
                    0.95,
                )
            )

    if "safety check failed" in reasons:
        ref = _safety_component(agent)
        if ref is not None:
            attributions.append(
                _attribution(
                    ref,
                    "safety check failed",
                    {
                        "safety_violation": bool(agent_result.get("safety_violation", False)),
                        "case_id": eval_result.case_id,
                    },
                    0.85,
                )
            )

    if not eval_result.handoff_context_preserved:
        ref = _handoff_component(agent, str(agent_result.get("specialist_used", "")))
        if ref is not None:
            attributions.append(
                _attribution(
                    ref,
                    "handoff context lost",
                    {
                        "pipeline_path": agent_result.get("pipeline_path", []),
                        "case_id": eval_result.case_id,
                    },
                    0.8,
                )
            )

    if {"behavior mismatch", "missing expected keywords"} & reasons and not attributions:
        ref = _instruction_component(agent)
        if ref is not None:
            attributions.append(
                _attribution(
                    ref,
                    next(iter({"behavior mismatch", "missing expected keywords"} & reasons)),
                    {
                        "details": eval_result.details,
                        "case_id": eval_result.case_id,
                    },
                    0.55,
                )
            )

    return [attribution.model_dump(mode="python") for attribution in attributions]


def _routing_component(agent: CanonicalAgent, target: str) -> ComponentReference | None:
    if target:
        ref = find_component_reference(agent, "routing_rule", target)
        if ref is not None:
            return ref
        ref = find_component_reference(agent, "sub_agent", target)
        if ref is not None:
            return ref
    return _instruction_component(agent)


def _tool_component(agent: CanonicalAgent, expected_tool: str) -> ComponentReference | None:
    if expected_tool:
        for ref in iter_component_references(agent):
            if ref.component_type == "tool_contract" and ref.name.lower() == expected_tool.lower():
                return ref
    return None


def _safety_component(agent: CanonicalAgent) -> ComponentReference | None:
    for ref in iter_component_references(agent):
        if ref.component_type == "guardrail":
            return ref
    for policy in agent.policies:
        if policy.type in {PolicyType.SAFETY, PolicyType.COMPLIANCE}:
            return find_component_reference(agent, "policy", policy.name)
    for ref in iter_component_references(agent):
        if ref.component_type == "callback":
            return ref
    return _instruction_component(agent)


def _handoff_component(agent: CanonicalAgent, target: str) -> ComponentReference | None:
    refs = [ref for ref in iter_component_references(agent) if ref.component_type == "handoff"]
    for ref in refs:
        if target and ref.name.endswith(f"->{target}"):
            return ref
    return refs[0] if refs else None


def _instruction_component(agent: CanonicalAgent) -> ComponentReference | None:
    refs = [ref for ref in iter_component_references(agent) if ref.component_type == "instruction"]
    return refs[0] if refs else None


def _observed_tools(agent_result: dict[str, Any]) -> list[str]:
    tool_calls = agent_result.get("tool_calls", [])
    if not isinstance(tool_calls, list):
        return []
    observed: list[str] = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        name = str(call.get("tool") or call.get("name") or "").strip()
        if name:
            observed.append(name)
    return observed


def _attribution(
    component: ComponentReference,
    failure_reason: str,
    evidence: dict[str, Any],
    confidence: float,
) -> ComponentAttribution:
    return ComponentAttribution(
        component=component,
        failure_reason=failure_reason,
        evidence=evidence,
        confidence=confidence,
        source="eval_result",
    )
