"""Context analysis engine — snapshot extraction, growth detection, and failure correlation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class ContextSnapshot:
    """A single point-in-time snapshot of context window usage."""

    turn_number: int
    tokens_used: int
    tokens_available: int
    event_type: str
    agent_path: str
    metadata: dict = field(default_factory=dict)

    @property
    def utilization(self) -> float:
        """Fraction of context window currently used (0.0–1.0)."""
        if self.tokens_available == 0:
            return 0.0
        return self.tokens_used / self.tokens_available


@dataclass
class GrowthPattern:
    """Classified growth behaviour of token usage over a trace."""

    pattern_type: str  # "linear" | "exponential" | "sawtooth" | "stable"
    slope: float
    compaction_events: int
    avg_tokens_per_turn: float


@dataclass
class ContextCorrelation:
    """Relationship between context utilization thresholds and failure rates."""

    threshold_tokens: int
    failure_rate_above: float
    failure_rate_below: float
    correlation_strength: float  # 0.0–1.0
    sample_size: int


@dataclass
class HandoffScore:
    """Score for a single agent-to-agent handoff event."""

    from_agent: str
    to_agent: str
    turn_number: int
    fidelity: float  # 0.0–1.0, information retention ratio


@dataclass
class ContextAnalysis:
    """Full analysis result for a single trace."""

    trace_id: str
    snapshots: list[ContextSnapshot]
    growth_pattern: GrowthPattern
    peak_utilization: float
    avg_utilization: float
    context_correlations: list[ContextCorrelation]
    recommendations: list[str]
    handoff_scores: list[HandoffScore] = field(default_factory=list)

    @property
    def avg_handoff_fidelity(self) -> float:
        """Average fidelity across all scored handoffs (0.0 if none)."""
        if not self.handoff_scores:
            return 0.0
        return sum(h.fidelity for h in self.handoff_scores) / len(self.handoff_scores)

    def to_dict(self) -> dict:
        """Serialize to a plain dict."""
        return {
            "trace_id": self.trace_id,
            "snapshot_count": len(self.snapshots),
            "growth_pattern": {
                "pattern_type": self.growth_pattern.pattern_type,
                "slope": self.growth_pattern.slope,
                "compaction_events": self.growth_pattern.compaction_events,
                "avg_tokens_per_turn": self.growth_pattern.avg_tokens_per_turn,
            },
            "peak_utilization": self.peak_utilization,
            "avg_utilization": self.avg_utilization,
            "correlations": [
                {
                    "threshold_tokens": c.threshold_tokens,
                    "failure_rate_above": c.failure_rate_above,
                    "failure_rate_below": c.failure_rate_below,
                    "correlation_strength": c.correlation_strength,
                    "sample_size": c.sample_size,
                }
                for c in self.context_correlations
            ],
            "handoff_scores": [
                {
                    "from_agent": h.from_agent,
                    "to_agent": h.to_agent,
                    "turn_number": h.turn_number,
                    "fidelity": round(h.fidelity, 4),
                }
                for h in self.handoff_scores
            ],
            "avg_handoff_fidelity": round(self.avg_handoff_fidelity, 4),
            "recommendations": self.recommendations,
        }


class ContextAnalyzer:
    """Analyses agent traces to extract context-window usage patterns."""

    def __init__(self, trace_store: object | None = None) -> None:
        self.trace_store = trace_store

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_trace(self, trace_events: list[dict]) -> ContextAnalysis:
        """Build a full context analysis from raw trace event dicts."""
        snapshots = self.measure_utilization(trace_events)
        growth = self.detect_growth_pattern(snapshots)
        correlations = self.find_failure_correlations(trace_events, snapshots)
        handoff_scores = self._score_handoffs(trace_events)

        peak = max((s.utilization for s in snapshots), default=0.0)
        avg = (
            sum(s.utilization for s in snapshots) / len(snapshots)
            if snapshots
            else 0.0
        )

        recommendations: list[str] = []
        if peak > 0.9:
            recommendations.append(
                "Peak utilization exceeded 90% — consider earlier compaction."
            )
        if growth.pattern_type == "exponential":
            recommendations.append(
                "Exponential token growth detected — review tool output sizes."
            )
        if growth.compaction_events == 0 and peak > 0.7:
            recommendations.append(
                "No compaction events despite high utilization — add a compaction strategy."
            )
        for corr in correlations:
            if corr.correlation_strength > 0.5:
                recommendations.append(
                    f"Failure rate spikes above {corr.threshold_tokens} tokens "
                    f"(strength {corr.correlation_strength:.2f})."
                )
        if handoff_scores:
            avg_fidelity = sum(h.fidelity for h in handoff_scores) / len(handoff_scores)
            if avg_fidelity < 0.5:
                recommendations.append(
                    f"Low handoff fidelity ({avg_fidelity:.0%}) — context may be lost during agent transitions."
                )

        trace_id = trace_events[0].get("trace_id", str(uuid.uuid4())) if trace_events else str(uuid.uuid4())

        return ContextAnalysis(
            trace_id=trace_id,
            snapshots=snapshots,
            growth_pattern=growth,
            peak_utilization=peak,
            avg_utilization=avg,
            context_correlations=correlations,
            recommendations=recommendations,
            handoff_scores=handoff_scores,
        )

    def measure_utilization(self, trace_events: list[dict]) -> list[ContextSnapshot]:
        """Extract per-turn context snapshots from trace event dicts."""
        snapshots: list[ContextSnapshot] = []
        cumulative_tokens = 0
        for i, evt in enumerate(trace_events):
            tokens_in = evt.get("tokens_in", 0)
            tokens_out = evt.get("tokens_out", 0)
            cumulative_tokens += tokens_in + tokens_out

            tokens_available = evt.get("metadata", {}).get("tokens_available", 128_000)

            snapshots.append(
                ContextSnapshot(
                    turn_number=i,
                    tokens_used=cumulative_tokens,
                    tokens_available=tokens_available,
                    event_type=evt.get("event_type", "unknown"),
                    agent_path=evt.get("agent_path", ""),
                    metadata=evt.get("metadata", {}),
                )
            )
        return snapshots

    def detect_growth_pattern(self, snapshots: list[ContextSnapshot]) -> GrowthPattern:
        """Classify token growth as linear, exponential, sawtooth, or stable."""
        if len(snapshots) < 2:
            avg = snapshots[0].tokens_used if snapshots else 0.0
            return GrowthPattern(
                pattern_type="stable",
                slope=0.0,
                compaction_events=0,
                avg_tokens_per_turn=avg,
            )

        tokens = [s.tokens_used for s in snapshots]
        avg_tokens = sum(tokens) / len(tokens)

        # Detect compaction drops (>30% decrease between consecutive turns).
        compaction_events = 0
        for j in range(1, len(tokens)):
            if tokens[j] < tokens[j - 1] * 0.7:
                compaction_events += 1

        # Overall slope via simple linear estimate.
        slope = (tokens[-1] - tokens[0]) / (len(tokens) - 1)

        if compaction_events > 0:
            pattern_type = "sawtooth"
        else:
            # Check for acceleration (exponential) — compare first-half slope to second-half slope.
            mid = len(tokens) // 2
            if mid > 0 and len(tokens) - mid > 1:
                first_half_slope = (tokens[mid] - tokens[0]) / mid
                second_half_slope = (tokens[-1] - tokens[mid]) / (len(tokens) - mid - 1)

                if second_half_slope > first_half_slope * 1.5 and first_half_slope > 0:
                    pattern_type = "exponential"
                elif abs(slope) < 10:
                    pattern_type = "stable"
                else:
                    pattern_type = "linear"
            elif abs(slope) < 10:
                pattern_type = "stable"
            else:
                pattern_type = "linear"

        return GrowthPattern(
            pattern_type=pattern_type,
            slope=slope,
            compaction_events=compaction_events,
            avg_tokens_per_turn=avg_tokens,
        )

    def find_failure_correlations(
        self,
        trace_events: list[dict],
        snapshots: list[ContextSnapshot],
    ) -> list[ContextCorrelation]:
        """Find token-count thresholds where failure rates change significantly."""
        if not snapshots:
            return []

        # Build list of (tokens_used, is_failure) pairs.
        pairs: list[tuple[int, bool]] = []
        for evt, snap in zip(trace_events, snapshots):
            is_failure = bool(evt.get("error_message"))
            pairs.append((snap.tokens_used, is_failure))

        if not pairs:
            return []

        # Test a set of thresholds at 25%, 50%, 75% of the max token count.
        max_tokens = max(t for t, _ in pairs)
        correlations: list[ContextCorrelation] = []
        for pct in (0.25, 0.50, 0.75):
            threshold = int(max_tokens * pct)
            above = [f for t, f in pairs if t >= threshold]
            below = [f for t, f in pairs if t < threshold]

            if not above or not below:
                continue

            rate_above = sum(above) / len(above)
            rate_below = sum(below) / len(below)

            diff = abs(rate_above - rate_below)
            strength = min(diff * 2.0, 1.0)

            correlations.append(
                ContextCorrelation(
                    threshold_tokens=threshold,
                    failure_rate_above=rate_above,
                    failure_rate_below=rate_below,
                    correlation_strength=strength,
                    sample_size=len(pairs),
                )
            )

        return correlations

    def _score_handoffs(self, trace_events: list[dict]) -> list[HandoffScore]:
        """Score all handoff events in a trace for information retention."""
        scores: list[HandoffScore] = []
        previous_context = ""
        previous_agent = ""

        for i, evt in enumerate(trace_events):
            current_agent = evt.get("agent_path", "")

            # Detect agent transition (handoff) by agent_path change
            if current_agent and previous_agent and current_agent != previous_agent:
                handoff_summary = evt.get("handoff_summary", "") or evt.get("context_summary", "")
                if handoff_summary and previous_context:
                    fidelity = self.score_handoff(handoff_summary, previous_context)
                    scores.append(HandoffScore(
                        from_agent=previous_agent,
                        to_agent=current_agent,
                        turn_number=i,
                        fidelity=fidelity,
                    ))

            # Accumulate context from this event for potential future handoff scoring
            content = evt.get("content", "") or evt.get("message", "")
            if content:
                previous_context = content
            previous_agent = current_agent

        return scores

    def score_handoff(self, handoff_summary: str, original_context: str) -> float:
        """Measure information retention as simple word overlap ratio."""
        if not original_context:
            return 0.0
        original_words = set(original_context.lower().split())
        if not original_words:
            return 0.0
        summary_words = set(handoff_summary.lower().split())
        overlap = original_words & summary_words
        return len(overlap) / len(original_words)
