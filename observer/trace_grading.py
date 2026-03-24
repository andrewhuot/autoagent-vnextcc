"""Span-level grading for agent traces.

Each grader evaluates a specific aspect of agent behavior within a trace span
(routing, tool selection, tool arguments, retrieval quality, handoff quality,
memory use, final outcome).  The ``TraceGrader`` orchestrates all graders
across every span in a trace.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from observer.traces import TraceEvent, TraceEventType, TraceSpan, TraceStore


# ---------------------------------------------------------------------------
# SpanGrade
# ---------------------------------------------------------------------------

@dataclass
class SpanGrade:
    """Grade for a single span within a trace."""

    span_id: str
    grader_name: str
    score: float  # 0-1
    passed: bool
    evidence: str
    failure_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "grader_name": self.grader_name,
            "score": self.score,
            "passed": self.passed,
            "evidence": self.evidence,
            "failure_reason": self.failure_reason,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# SpanGrader base
# ---------------------------------------------------------------------------

class SpanGrader:
    """Base class for span graders."""

    name: str = "base"

    def grade(self, span: TraceSpan, events: list[TraceEvent], context: dict[str, Any]) -> SpanGrade:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Concrete graders
# ---------------------------------------------------------------------------

class RoutingGrader(SpanGrader):
    """Did the agent route to the correct specialist?"""

    name = "routing"

    def grade(self, span: TraceSpan, events: list[TraceEvent], context: dict[str, Any]) -> SpanGrade:
        transfer_events = [e for e in events if e.event_type == TraceEventType.agent_transfer.value]
        if not transfer_events:
            return SpanGrade(
                span_id=span.span_id,
                grader_name=self.name,
                score=1.0,
                passed=True,
                evidence="No agent transfers in span.",
            )

        expected = context.get("expected_specialist")
        if expected is None:
            return SpanGrade(
                span_id=span.span_id,
                grader_name=self.name,
                score=1.0,
                passed=True,
                evidence="No expected specialist provided; cannot evaluate routing.",
            )

        for evt in transfer_events:
            to_agent = evt.metadata.get("to_agent", "")
            if to_agent == expected:
                return SpanGrade(
                    span_id=span.span_id,
                    grader_name=self.name,
                    score=1.0,
                    passed=True,
                    evidence=f"Routed to expected specialist '{expected}'.",
                )

        actual_targets = [evt.metadata.get("to_agent", "") for evt in transfer_events]
        return SpanGrade(
            span_id=span.span_id,
            grader_name=self.name,
            score=0.0,
            passed=False,
            evidence=f"Routed to {actual_targets}, expected '{expected}'.",
            failure_reason=f"Wrong routing: expected '{expected}', got {actual_targets}",
        )


class ToolSelectionGrader(SpanGrader):
    """Did the agent pick the right tool? Was it necessary?"""

    name = "tool_selection"

    def grade(self, span: TraceSpan, events: list[TraceEvent], context: dict[str, Any]) -> SpanGrade:
        tool_calls = [e for e in events if e.event_type == TraceEventType.tool_call.value]
        if not tool_calls:
            return SpanGrade(
                span_id=span.span_id,
                grader_name=self.name,
                score=1.0,
                passed=True,
                evidence="No tool calls in span.",
            )

        expected_tool = context.get("expected_tool")
        if expected_tool is None:
            return SpanGrade(
                span_id=span.span_id,
                grader_name=self.name,
                score=1.0,
                passed=True,
                evidence=f"No expected tool; found calls to: {[e.tool_name for e in tool_calls]}.",
            )

        actual_tools = [e.tool_name for e in tool_calls]
        if expected_tool in actual_tools:
            return SpanGrade(
                span_id=span.span_id,
                grader_name=self.name,
                score=1.0,
                passed=True,
                evidence=f"Expected tool '{expected_tool}' was called.",
            )

        return SpanGrade(
            span_id=span.span_id,
            grader_name=self.name,
            score=0.0,
            passed=False,
            evidence=f"Expected tool '{expected_tool}', got {actual_tools}.",
            failure_reason=f"Wrong tool: expected '{expected_tool}', got {actual_tools}",
        )


class ToolArgumentGrader(SpanGrader):
    """Were the tool arguments correct/complete?"""

    name = "tool_argument"

    def grade(self, span: TraceSpan, events: list[TraceEvent], context: dict[str, Any]) -> SpanGrade:
        tool_calls = [e for e in events if e.event_type == TraceEventType.tool_call.value]
        if not tool_calls:
            return SpanGrade(
                span_id=span.span_id,
                grader_name=self.name,
                score=1.0,
                passed=True,
                evidence="No tool calls in span.",
            )

        # Check for error responses that indicate bad arguments
        error_events = [
            e for e in events
            if e.event_type == TraceEventType.error.value
            or (e.event_type == TraceEventType.tool_response.value and e.error_message)
        ]

        # Check for empty or malformed tool_input
        issues: list[str] = []
        for tc in tool_calls:
            if not tc.tool_input:
                issues.append(f"Tool '{tc.tool_name}' called with empty input")
                continue
            try:
                parsed = json.loads(tc.tool_input) if isinstance(tc.tool_input, str) else tc.tool_input
                if isinstance(parsed, dict) and not parsed:
                    issues.append(f"Tool '{tc.tool_name}' called with empty arguments")
            except (json.JSONDecodeError, TypeError):
                issues.append(f"Tool '{tc.tool_name}' has malformed input")

        # Check expected_args in context
        expected_args = context.get("expected_tool_args")
        if expected_args and isinstance(expected_args, dict):
            for tc in tool_calls:
                if tc.tool_input:
                    try:
                        parsed = json.loads(tc.tool_input) if isinstance(tc.tool_input, str) else tc.tool_input
                        if isinstance(parsed, dict):
                            for key, val in expected_args.items():
                                if key not in parsed:
                                    issues.append(f"Missing required arg '{key}' in '{tc.tool_name}'")
                                elif parsed[key] != val:
                                    issues.append(f"Arg '{key}' mismatch in '{tc.tool_name}'")
                    except (json.JSONDecodeError, TypeError):
                        pass

        if error_events:
            issues.append(f"{len(error_events)} error(s) after tool call(s)")

        if issues:
            score = max(0.0, 1.0 - len(issues) * 0.25)
            return SpanGrade(
                span_id=span.span_id,
                grader_name=self.name,
                score=score,
                passed=score >= 0.5,
                evidence="; ".join(issues),
                failure_reason=issues[0] if score < 0.5 else None,
            )

        return SpanGrade(
            span_id=span.span_id,
            grader_name=self.name,
            score=1.0,
            passed=True,
            evidence=f"Tool arguments look correct for {len(tool_calls)} call(s).",
        )


class RetrievalQualityGrader(SpanGrader):
    """Was retrieved context relevant and sufficient?"""

    name = "retrieval_quality"

    def grade(self, span: TraceSpan, events: list[TraceEvent], context: dict[str, Any]) -> SpanGrade:
        tool_responses = [
            e for e in events
            if e.event_type == TraceEventType.tool_response.value and e.tool_output
        ]

        if not tool_responses:
            return SpanGrade(
                span_id=span.span_id,
                grader_name=self.name,
                score=1.0,
                passed=True,
                evidence="No tool responses with output in span.",
            )

        # Check if retrieval returned empty results
        empty_retrievals = 0
        total = 0
        for resp in tool_responses:
            try:
                output = json.loads(resp.tool_output) if isinstance(resp.tool_output, str) else resp.tool_output
                if isinstance(output, dict) and "results" in output:
                    total += 1
                    results = output["results"]
                    if not results or (isinstance(results, list) and len(results) == 0):
                        empty_retrievals += 1
            except (json.JSONDecodeError, TypeError):
                continue

        if total == 0:
            return SpanGrade(
                span_id=span.span_id,
                grader_name=self.name,
                score=1.0,
                passed=True,
                evidence="No retrieval-like responses detected.",
            )

        score = 1.0 - (empty_retrievals / total)
        return SpanGrade(
            span_id=span.span_id,
            grader_name=self.name,
            score=score,
            passed=score >= 0.5,
            evidence=f"{empty_retrievals}/{total} retrieval(s) returned empty results.",
            failure_reason=f"Empty retrievals: {empty_retrievals}/{total}" if score < 0.5 else None,
        )


class HandoffQualityGrader(SpanGrader):
    """Did the handoff preserve necessary context?"""

    name = "handoff_quality"

    def grade(self, span: TraceSpan, events: list[TraceEvent], context: dict[str, Any]) -> SpanGrade:
        transfers = [e for e in events if e.event_type == TraceEventType.agent_transfer.value]
        if not transfers:
            return SpanGrade(
                span_id=span.span_id,
                grader_name=self.name,
                score=1.0,
                passed=True,
                evidence="No agent transfers in span.",
            )

        # Check transfer metadata for context preservation signals
        issues: list[str] = []
        for evt in transfers:
            meta = evt.metadata
            if not meta.get("to_agent"):
                issues.append("Transfer missing target agent")
            # If handoff_artifact is provided in context, score against it
            if "handoff_artifact" in meta:
                artifact = meta["handoff_artifact"]
                if isinstance(artifact, dict):
                    if not artifact.get("goal"):
                        issues.append("Handoff artifact missing goal")
                    if not artifact.get("known_facts"):
                        issues.append("Handoff artifact missing known_facts")

        score = max(0.0, 1.0 - len(issues) * 0.25)
        if issues:
            return SpanGrade(
                span_id=span.span_id,
                grader_name=self.name,
                score=score,
                passed=score >= 0.5,
                evidence="; ".join(issues),
                failure_reason=issues[0] if score < 0.5 else None,
            )

        return SpanGrade(
            span_id=span.span_id,
            grader_name=self.name,
            score=1.0,
            passed=True,
            evidence=f"{len(transfers)} handoff(s) with context preserved.",
        )


class MemoryUseGrader(SpanGrader):
    """Was memory stale? Was relevant memory retrieved?"""

    name = "memory_use"

    def grade(self, span: TraceSpan, events: list[TraceEvent], context: dict[str, Any]) -> SpanGrade:
        state_deltas = [e for e in events if e.event_type == TraceEventType.state_delta.value]
        if not state_deltas:
            return SpanGrade(
                span_id=span.span_id,
                grader_name=self.name,
                score=1.0,
                passed=True,
                evidence="No state delta events in span.",
            )

        # Check for staleness signals in metadata
        stale_count = 0
        for evt in state_deltas:
            meta = evt.metadata
            if meta.get("stale") or meta.get("memory_stale"):
                stale_count += 1

        total = len(state_deltas)
        score = 1.0 - (stale_count / total) if total > 0 else 1.0
        if stale_count > 0:
            return SpanGrade(
                span_id=span.span_id,
                grader_name=self.name,
                score=score,
                passed=score >= 0.5,
                evidence=f"{stale_count}/{total} state delta(s) flagged as stale.",
                failure_reason=f"Stale memory: {stale_count}/{total}" if score < 0.5 else None,
            )

        return SpanGrade(
            span_id=span.span_id,
            grader_name=self.name,
            score=1.0,
            passed=True,
            evidence=f"{total} state delta(s), none stale.",
        )


class FinalOutcomeGrader(SpanGrader):
    """Did the agent achieve the goal?"""

    name = "final_outcome"

    def grade(self, span: TraceSpan, events: list[TraceEvent], context: dict[str, Any]) -> SpanGrade:
        error_events = [e for e in events if e.event_type == TraceEventType.error.value]
        if error_events:
            messages = [e.error_message or "unknown error" for e in error_events]
            return SpanGrade(
                span_id=span.span_id,
                grader_name=self.name,
                score=0.0,
                passed=False,
                evidence=f"Error(s) in span: {messages}",
                failure_reason=messages[0],
            )

        if span.status == "error":
            return SpanGrade(
                span_id=span.span_id,
                grader_name=self.name,
                score=0.0,
                passed=False,
                evidence=f"Span status is 'error'.",
                failure_reason="Span ended with error status",
            )

        # Check for successful model or tool responses
        responses = [
            e for e in events
            if e.event_type in (TraceEventType.model_response.value, TraceEventType.tool_response.value)
        ]

        if responses:
            return SpanGrade(
                span_id=span.span_id,
                grader_name=self.name,
                score=1.0,
                passed=True,
                evidence=f"Span completed with {len(responses)} response(s), status='{span.status}'.",
            )

        return SpanGrade(
            span_id=span.span_id,
            grader_name=self.name,
            score=0.5,
            passed=True,
            evidence=f"Span status='{span.status}' but no response events found.",
        )


# ---------------------------------------------------------------------------
# TraceGrader orchestrator
# ---------------------------------------------------------------------------

_EVENT_TYPE_TO_GRADERS: dict[str, set[str]] = {
    TraceEventType.agent_transfer.value: {"routing", "handoff_quality"},
    TraceEventType.tool_call.value: {"tool_selection", "tool_argument"},
    TraceEventType.tool_response.value: {"retrieval_quality", "tool_argument"},
    TraceEventType.state_delta.value: {"memory_use"},
    TraceEventType.error.value: {"final_outcome"},
    TraceEventType.model_response.value: {"final_outcome"},
}


class TraceGrader:
    """Grades all spans in a trace using pluggable graders."""

    DEFAULT_GRADERS: list[SpanGrader] = [
        RoutingGrader(),
        ToolSelectionGrader(),
        ToolArgumentGrader(),
        RetrievalQualityGrader(),
        HandoffQualityGrader(),
        MemoryUseGrader(),
        FinalOutcomeGrader(),
    ]

    def __init__(self, graders: list[SpanGrader] | None = None) -> None:
        self.graders = graders or list(self.DEFAULT_GRADERS)

    def grade_trace(
        self,
        trace_id: str,
        store: TraceStore,
        context: dict[str, Any] | None = None,
    ) -> list[SpanGrade]:
        """Grade all spans in a trace. Returns list of SpanGrades."""
        spans = store.get_spans(trace_id)
        events = store.get_trace(trace_id)
        context = context or {}
        grades: list[SpanGrade] = []

        for span in spans:
            span_events = [
                e for e in events
                if e.timestamp >= span.start_time and e.timestamp <= span.end_time
            ]
            for grader in self.graders:
                if self._grader_applies(grader, span, span_events):
                    grade = grader.grade(span, span_events, context)
                    grades.append(grade)

        return grades

    @staticmethod
    def _grader_applies(grader: SpanGrader, span: TraceSpan, events: list[TraceEvent]) -> bool:
        """Check if a grader is relevant for this span based on events present."""
        grader_name = grader.name

        # final_outcome applies to root spans (no parent) or leaf spans
        if grader_name == "final_outcome":
            return span.parent_span_id is None or span.status == "error"

        # Other graders: apply if any event in the span maps to this grader
        event_types_present = {e.event_type for e in events}
        for evt_type, grader_names in _EVENT_TYPE_TO_GRADERS.items():
            if grader_name in grader_names and evt_type in event_types_present:
                return True

        return False
