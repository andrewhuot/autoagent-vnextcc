"""Trace promoter — auto-flag interesting traces as eval candidates.

Scans production traces and surfaces the ones most worth converting into
eval cases: failures, edge cases, high-latency runs, and near-miss scenarios.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class TraceCandidate:
    """A production trace flagged as an eval candidate.

    Args:
        trace_id: ID of the source trace.
        reason: Human-readable explanation for why the trace was flagged.
        confidence: How confident the promoter is (0–1).
        suggested_category: Suggested eval category, e.g. ``"edge_case"``.
        auto_generated_case: An EvalCase-compatible dict, or ``None`` if not
            yet promoted.
        flagged_at: ISO 8601 timestamp of when the trace was flagged.
    """

    trace_id: str
    reason: str
    confidence: float
    suggested_category: str
    auto_generated_case: dict[str, Any] | None = None
    flagged_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "reason": self.reason,
            "confidence": self.confidence,
            "suggested_category": self.suggested_category,
            "auto_generated_case": self.auto_generated_case,
            "flagged_at": self.flagged_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TraceCandidate":
        return cls(
            trace_id=str(d["trace_id"]),
            reason=str(d.get("reason", "")),
            confidence=float(d.get("confidence", 0.0)),
            suggested_category=str(d.get("suggested_category", "general")),
            auto_generated_case=d.get("auto_generated_case"),
            flagged_at=str(
                d.get("flagged_at", datetime.now(timezone.utc).isoformat())
            ),
        )


# ---------------------------------------------------------------------------
# Promoter
# ---------------------------------------------------------------------------

# Default latency threshold for high-latency detection (milliseconds)
_DEFAULT_LATENCY_THRESHOLD_MS = 5000.0

# Near-miss detection: score within this fraction of the failure threshold
_NEAR_MISS_MARGIN = 0.1


class TracePromoter:
    """Identify production traces that are worth converting into eval cases.

    The promoter inspects each trace dict and returns a list of
    :class:`TraceCandidate` objects — one per interesting trace.

    Traces are flagged for four reasons (in priority order):
    1. Failure — the trace ended in an error or explicit failure.
    2. Edge case — unusual tool usage, rare routing, or anomalous parameters.
    3. High latency — total duration exceeded *threshold_ms*.
    4. Near miss — outcome score / success metric was close to the failure
       boundary.

    Args:
        anomaly_threshold: Minimum confidence required to emit a candidate.
    """

    def __init__(self, anomaly_threshold: float = 0.7) -> None:
        self.anomaly_threshold = max(0.0, min(1.0, float(anomaly_threshold)))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def flag_interesting_traces(
        self, traces: list[dict[str, Any]]
    ) -> list[TraceCandidate]:
        """Scan *traces* and return one candidate per interesting trace.

        A trace may only appear once (the highest-priority reason wins).
        """
        candidates: list[TraceCandidate] = []
        seen: set[str] = set()

        for trace in traces:
            trace_id = str(trace.get("trace_id") or trace.get("id") or uuid.uuid4().hex[:12])
            if trace_id in seen:
                continue

            candidate = self._evaluate_trace(trace, trace_id)
            if candidate is not None and candidate.confidence >= self.anomaly_threshold:
                candidates.append(candidate)
                seen.add(trace_id)

        return candidates

    def promote_to_eval_case(self, candidate: TraceCandidate) -> dict[str, Any]:
        """Convert a :class:`TraceCandidate` into an EvalCase-compatible dict.

        The returned dict follows the :class:`~core.types.EvalCase` schema so
        it can be loaded directly by the eval runner.
        """
        if candidate.auto_generated_case is not None:
            return candidate.auto_generated_case

        case_id = f"promoted_{candidate.trace_id}"
        return {
            "case_id": case_id,
            "task": f"Trace {candidate.trace_id} promoted: {candidate.reason}",
            "category": candidate.suggested_category,
            "suite_type": "discovery",
            "metadata": {
                "source_trace_id": candidate.trace_id,
                "promotion_reason": candidate.reason,
                "promotion_confidence": candidate.confidence,
                "flagged_at": candidate.flagged_at,
            },
        }

    def promote_batch(
        self, candidates: list[TraceCandidate]
    ) -> list[dict[str, Any]]:
        """Promote a list of candidates and return EvalCase-compatible dicts."""
        return [self.promote_to_eval_case(c) for c in candidates]

    # ------------------------------------------------------------------
    # Detection predicates
    # ------------------------------------------------------------------

    def _is_failure(self, trace: dict[str, Any]) -> bool:
        """Return True when the trace ended in an error or explicit failure."""
        # Explicit status fields
        status = str(trace.get("status") or trace.get("outcome") or "").lower()
        if status in ("error", "fail", "failure", "failed", "exception", "abandon"):
            return True

        # Error events present in the trace
        events = trace.get("events") or []
        if any(
            str(e.get("event_type", "")).lower() == "error"
            or e.get("error_message")
            for e in events
            if isinstance(e, dict)
        ):
            return True

        # Top-level error field
        if trace.get("error") or trace.get("error_message"):
            return True

        return False

    def _is_edge_case(self, trace: dict[str, Any]) -> bool:
        """Return True when the trace exhibits unusual behaviour.

        Heuristics:
        - Unusually high tool call count (> 10 calls).
        - Agent transfers to an unexpected / rare specialist.
        - Tool retry or fallback patterns detected.
        - Safety flag events present.
        """
        events = trace.get("events") or []

        if not isinstance(events, list):
            return False

        tool_calls = [
            e for e in events
            if isinstance(e, dict)
            and str(e.get("event_type", "")).lower() in ("tool_call", "tool_response")
        ]
        if len(tool_calls) > 10:
            return True

        safety_flags = [
            e for e in events
            if isinstance(e, dict)
            and str(e.get("event_type", "")).lower() == "safety_flag"
        ]
        if safety_flags:
            return True

        agent_transfers = [
            e for e in events
            if isinstance(e, dict)
            and str(e.get("event_type", "")).lower() == "agent_transfer"
        ]
        if len(agent_transfers) > 2:
            return True

        # Retry pattern: same tool called multiple times in a row
        tool_names = [
            e.get("tool_name")
            for e in tool_calls
            if e.get("tool_name")
        ]
        for i in range(1, len(tool_names)):
            if tool_names[i] == tool_names[i - 1]:
                return True

        return False

    def _is_high_latency(
        self,
        trace: dict[str, Any],
        threshold_ms: float = _DEFAULT_LATENCY_THRESHOLD_MS,
    ) -> bool:
        """Return True when total trace latency exceeds *threshold_ms*."""
        # Direct latency field
        latency = trace.get("latency_ms") or trace.get("total_latency_ms")
        if latency is not None:
            return float(latency) > threshold_ms

        # Sum latency from events
        events = trace.get("events") or []
        if isinstance(events, list) and events:
            total = sum(
                float(e.get("latency_ms", 0.0))
                for e in events
                if isinstance(e, dict)
            )
            if total > threshold_ms:
                return True

        # Derive from start/end timestamps
        start = trace.get("start_time") or trace.get("started_at")
        end = trace.get("end_time") or trace.get("ended_at")
        if start is not None and end is not None:
            try:
                duration_ms = (float(end) - float(start)) * 1000.0
                return duration_ms > threshold_ms
            except (TypeError, ValueError):
                pass

        return False

    def _is_near_miss(self, trace: dict[str, Any]) -> bool:
        """Return True when the trace came close to failing.

        A trace is a near miss if its ``score`` or ``quality_score`` is in
        the range ``[failure_threshold, failure_threshold + margin]``.
        The default failure threshold is 0.5 (matching the eval runner).
        """
        failure_threshold = float(
            trace.get("failure_threshold", 0.5)
        )
        score = trace.get("score") or trace.get("quality_score")
        if score is None:
            return False

        score_f = float(score)
        near_miss_upper = failure_threshold + _NEAR_MISS_MARGIN
        # Above failure threshold but within margin
        return failure_threshold <= score_f <= near_miss_upper

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _evaluate_trace(
        self, trace: dict[str, Any], trace_id: str
    ) -> TraceCandidate | None:
        """Return the highest-priority candidate for a single trace, or None."""

        if self._is_failure(trace):
            return TraceCandidate(
                trace_id=trace_id,
                reason="trace ended in an error or explicit failure",
                confidence=0.95,
                suggested_category="regression",
            )

        if self._is_edge_case(trace):
            return TraceCandidate(
                trace_id=trace_id,
                reason="unusual tool usage, safety flag, or excessive agent transfers",
                confidence=0.80,
                suggested_category="edge_case",
            )

        if self._is_high_latency(trace):
            return TraceCandidate(
                trace_id=trace_id,
                reason=f"latency exceeded {_DEFAULT_LATENCY_THRESHOLD_MS:.0f} ms threshold",
                confidence=0.75,
                suggested_category="performance",
            )

        if self._is_near_miss(trace):
            return TraceCandidate(
                trace_id=trace_id,
                reason="score was within the near-miss margin of the failure threshold",
                confidence=0.70,
                suggested_category="edge_case",
            )

        return None
