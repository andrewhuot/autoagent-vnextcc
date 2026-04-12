"""Component-level credit assignment for optimization traces.

Attributes failures to specific component types in the canonical IR with
explicit confidence levels.  Complements evals/component_attribution.py
(which works from eval results) by analyzing raw execution traces.

Ported from the Claude optimization-breadth branch and adapted to use
the Codex canonical_patch vocabulary (string component_type values).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ComponentType(str, Enum):
    """Component types matching shared.canonical_patch vocabulary."""

    instruction = "instruction"
    tool_contract = "tool_contract"
    routing_rule = "routing_rule"
    guardrail = "guardrail"
    policy = "policy"
    callback = "callback"
    handoff = "handoff"
    sub_agent = "sub_agent"
    mcp_server = "mcp_server"
    environment = "environment"
    flow = "flow"
    state = "state"
    transition = "transition"


class AttributionConfidence(str, Enum):
    """How trustworthy the component attribution is."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    HEURISTIC = "heuristic"

    def to_float(self) -> float:
        """Convert to the float confidence scale used by shared.canonical_patch.ComponentAttribution."""
        return _CONFIDENCE_FLOAT[self]


_CONFIDENCE_FLOAT: dict[AttributionConfidence, float] = {
    AttributionConfidence.HIGH: 0.9,
    AttributionConfidence.MEDIUM: 0.7,
    AttributionConfidence.LOW: 0.4,
    AttributionConfidence.HEURISTIC: 0.2,
}


@dataclass
class ComponentBlameEntry:
    """Failure attribution targeting a specific component type."""

    component_type: ComponentType
    component_name: str = ""
    failure_count: int = 0
    failure_rate: float = 0.0
    failure_types: list[str] = field(default_factory=list)
    impact_score: float = 0.0
    confidence: AttributionConfidence = AttributionConfidence.HEURISTIC
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_type": self.component_type.value,
            "component_name": self.component_name,
            "failure_count": self.failure_count,
            "failure_rate": round(self.failure_rate, 6),
            "failure_types": list(self.failure_types),
            "impact_score": round(self.impact_score, 6),
            "confidence": self.confidence.value,
            "evidence": list(self.evidence),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ComponentBlameEntry:
        return cls(
            component_type=ComponentType(d["component_type"]),
            component_name=d.get("component_name", ""),
            failure_count=d.get("failure_count", 0),
            failure_rate=d.get("failure_rate", 0.0),
            failure_types=list(d.get("failure_types", [])),
            impact_score=d.get("impact_score", 0.0),
            confidence=AttributionConfidence(d.get("confidence", "heuristic")),
            evidence=list(d.get("evidence", [])),
        )


_FAILURE_TYPE_TO_COMPONENT: dict[str, list[tuple[ComponentType, AttributionConfidence]]] = {
    "routing_error": [
        (ComponentType.routing_rule, AttributionConfidence.HIGH),
    ],
    "tool_failure": [
        (ComponentType.tool_contract, AttributionConfidence.HIGH),
    ],
    "safety_violation": [
        (ComponentType.guardrail, AttributionConfidence.MEDIUM),
        (ComponentType.policy, AttributionConfidence.MEDIUM),
    ],
    "hallucination": [
        (ComponentType.instruction, AttributionConfidence.MEDIUM),
    ],
    "timeout": [
        (ComponentType.environment, AttributionConfidence.LOW),
        (ComponentType.tool_contract, AttributionConfidence.LOW),
    ],
    "invalid_output": [
        (ComponentType.instruction, AttributionConfidence.LOW),
        (ComponentType.guardrail, AttributionConfidence.LOW),
    ],
    "no_response": [
        (ComponentType.routing_rule, AttributionConfidence.MEDIUM),
        (ComponentType.instruction, AttributionConfidence.LOW),
    ],
    "infinite_loop": [
        (ComponentType.routing_rule, AttributionConfidence.MEDIUM),
        (ComponentType.handoff, AttributionConfidence.MEDIUM),
        (ComponentType.transition, AttributionConfidence.MEDIUM),
    ],
    "error": [
        (ComponentType.tool_contract, AttributionConfidence.LOW),
        (ComponentType.instruction, AttributionConfidence.HEURISTIC),
    ],
    "flow_error": [
        (ComponentType.flow, AttributionConfidence.HIGH),
        (ComponentType.transition, AttributionConfidence.MEDIUM),
    ],
    "transition_error": [
        (ComponentType.transition, AttributionConfidence.HIGH),
    ],
    "state_error": [
        (ComponentType.state, AttributionConfidence.HIGH),
    ],
    "dead_end": [
        (ComponentType.state, AttributionConfidence.MEDIUM),
        (ComponentType.transition, AttributionConfidence.MEDIUM),
    ],
}

_SEVERITY_MULTIPLIERS: dict[str, float] = {
    "safety_violation": 1.5,
    "hallucination": 1.3,
    "infinite_loop": 1.2,
    "routing_error": 1.1,
    "flow_error": 1.1,
    "transition_error": 1.1,
    "dead_end": 1.0,
    "state_error": 1.0,
    "timeout": 1.0,
    "error": 1.0,
    "tool_failure": 0.9,
    "invalid_output": 0.8,
    "no_response": 0.7,
    "unknown": 0.5,
}


class ComponentCreditAnalyzer:
    """Attributes failures to specific component types from execution traces.

    Complements evals/component_attribution.py (eval-result-based) with a
    trace-based multi-tier strategy: explicit annotations > failure-type
    heuristics > trace structure refinement > fallback.
    """

    _FAILURE_KEYWORDS: dict[str, str] = {
        "timeout": "timeout",
        "timed out": "timeout",
        "error": "error",
        "exception": "error",
        "invalid": "invalid_output",
        "hallucination": "hallucination",
        "safety": "safety_violation",
        "refused": "safety_violation",
        "loop": "infinite_loop",
        "no response": "no_response",
        "empty": "no_response",
        "tool": "tool_failure",
        "routing": "routing_error",
        "flow": "flow_error",
        "transition": "transition_error",
        "dead end": "dead_end",
        "stuck": "dead_end",
        "state": "state_error",
        "page": "state_error",
    }

    def analyze(
        self,
        traces: list[dict[str, Any]],
        agent_components: dict[str, list[str]] | None = None,
    ) -> list[ComponentBlameEntry]:
        """Analyze traces and produce component-level blame entries.

        Returns entries sorted by impact_score descending.
        """
        total = len(traces)
        if total == 0:
            return []

        components = agent_components or {}
        blame_counts: dict[tuple[str, str], int] = defaultdict(int)
        blame_types: dict[tuple[str, str], list[str]] = defaultdict(list)
        blame_confidence: dict[tuple[str, str], AttributionConfidence] = {}
        blame_evidence: dict[tuple[str, str], list[str]] = defaultdict(list)

        failing = [t for t in traces if self._is_failure(t)]

        for trace in failing:
            attributions = self._attribute_to_components(trace, components)
            for comp_type, comp_name, confidence, evidence_str in attributions:
                key = (comp_type.value, comp_name)
                blame_counts[key] += 1
                ftype = self._classify_failure_type(trace)
                if ftype not in blame_types[key]:
                    blame_types[key].append(ftype)
                if key not in blame_confidence or _confidence_rank(confidence) > _confidence_rank(blame_confidence[key]):
                    blame_confidence[key] = confidence
                if evidence_str and evidence_str not in blame_evidence[key]:
                    blame_evidence[key].append(evidence_str)

        entries: list[ComponentBlameEntry] = []
        for (ct_val, cn), count in blame_counts.items():
            failure_rate = count / total
            ftypes = blame_types[(ct_val, cn)]
            severity = max((_SEVERITY_MULTIPLIERS.get(ft, 0.5) for ft in ftypes), default=0.5)
            impact = min(1.0, failure_rate * severity)

            entries.append(ComponentBlameEntry(
                component_type=ComponentType(ct_val),
                component_name=cn,
                failure_count=count,
                failure_rate=round(failure_rate, 6),
                failure_types=ftypes,
                impact_score=round(impact, 6),
                confidence=blame_confidence.get((ct_val, cn), AttributionConfidence.HEURISTIC),
                evidence=blame_evidence.get((ct_val, cn), []),
            ))

        entries.sort(key=lambda e: e.impact_score, reverse=True)
        return entries

    def _attribute_to_components(
        self,
        trace: dict[str, Any],
        components: dict[str, list[str]],
    ) -> list[tuple[ComponentType, str, AttributionConfidence, str]]:
        result: list[tuple[ComponentType, str, AttributionConfidence, str]] = []

        if trace.get("blamed_component"):
            bc = trace["blamed_component"]
            try:
                ct = ComponentType(bc.get("type", "instruction"))
            except ValueError:
                ct = ComponentType.instruction
            result.append((
                ct,
                bc.get("name", ""),
                AttributionConfidence.HIGH,
                f"explicit blamed_component: {bc}",
            ))
            return result

        if trace.get("failed_tool"):
            result.append((
                ComponentType.tool_contract,
                str(trace["failed_tool"]),
                AttributionConfidence.HIGH,
                f"explicit failed_tool: {trace['failed_tool']}",
            ))
            return result

        if trace.get("failed_guardrail"):
            result.append((
                ComponentType.guardrail,
                str(trace["failed_guardrail"]),
                AttributionConfidence.HIGH,
                f"explicit failed_guardrail: {trace['failed_guardrail']}",
            ))
            return result

        failure_type = self._classify_failure_type(trace)
        mappings = _FAILURE_TYPE_TO_COMPONENT.get(failure_type, [])

        if not mappings:
            result.append((
                ComponentType.instruction,
                "",
                AttributionConfidence.HEURISTIC,
                f"fallback for unknown failure type: {failure_type}",
            ))
            return result

        for comp_type, confidence in mappings:
            comp_name = self._refine_component_name(trace, comp_type, components)
            evidence = f"failure_type={failure_type} -> {comp_type.value}"
            if comp_name:
                evidence += f" (name={comp_name})"
            result.append((comp_type, comp_name, confidence, evidence))

        return result

    def _refine_component_name(
        self,
        trace: dict[str, Any],
        comp_type: ComponentType,
        components: dict[str, list[str]],
    ) -> str:
        if comp_type == ComponentType.tool_contract:
            tool_name = trace.get("tool_call_name") or trace.get("failed_tool_name", "")
            if tool_name:
                return str(tool_name)
            tool_names = components.get("tool_contract", [])
            error_text = str(trace.get("error", "")) + str(trace.get("error_message", ""))
            for tn in tool_names:
                if tn.lower() in error_text.lower():
                    return tn

        if comp_type == ComponentType.routing_rule:
            expected = trace.get("expected_specialist", "")
            if expected:
                return str(expected)

        if comp_type == ComponentType.guardrail:
            guardrail_name = trace.get("triggered_guardrail", "")
            if guardrail_name:
                return str(guardrail_name)

        return ""

    def _is_failure(self, trace: dict[str, Any]) -> bool:
        outcome = trace.get("outcome", "")
        success = trace.get("success")
        if success is not None:
            return not bool(success)
        return outcome in {"fail", "error", "abandon", "failure", "failed"}

    def _classify_failure_type(self, trace: dict[str, Any]) -> str:
        if trace.get("failure_type"):
            return str(trace["failure_type"])

        text = " ".join([
            str(trace.get("error", "")),
            str(trace.get("error_message", "")),
            str(trace.get("status", "")),
            str(trace.get("outcome", "")),
        ]).lower()

        for keyword, ftype in self._FAILURE_KEYWORDS.items():
            if keyword in text:
                return ftype

        return "unknown"


def _confidence_rank(conf: AttributionConfidence) -> int:
    return {
        AttributionConfidence.HIGH: 3,
        AttributionConfidence.MEDIUM: 2,
        AttributionConfidence.LOW: 1,
        AttributionConfidence.HEURISTIC: 0,
    }.get(conf, 0)
