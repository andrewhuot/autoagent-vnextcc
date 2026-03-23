"""Rolling health metrics computation for conversation monitoring."""

from dataclasses import dataclass, field

from logger.store import ConversationRecord


@dataclass
class HealthMetrics:
    success_rate: float = 0.0
    avg_latency_ms: float = 0.0
    error_rate: float = 0.0
    safety_violation_rate: float = 0.0
    avg_cost: float = 0.0  # approximated from token_count
    total_conversations: int = 0

    def to_dict(self) -> dict:
        return {
            "success_rate": self.success_rate,
            "avg_latency_ms": self.avg_latency_ms,
            "error_rate": self.error_rate,
            "safety_violation_rate": self.safety_violation_rate,
            "avg_cost": self.avg_cost,
            "total_conversations": self.total_conversations,
        }


@dataclass
class HealthReport:
    metrics: HealthMetrics
    anomalies: list[str] = field(default_factory=list)
    failure_buckets: dict[str, int] = field(default_factory=dict)
    needs_optimization: bool = False
    reason: str = ""


def compute_metrics(records: list[ConversationRecord]) -> HealthMetrics:
    """Compute health metrics from conversation records."""
    if not records:
        return HealthMetrics()

    total = len(records)
    success_count = sum(1 for r in records if r.outcome == "success")
    error_count = sum(1 for r in records if r.outcome in ("error", "fail", "abandon"))
    safety_count = sum(1 for r in records if r.safety_flags)
    total_latency = sum(r.latency_ms for r in records)
    total_tokens = sum(r.token_count for r in records)

    return HealthMetrics(
        success_rate=success_count / total,
        avg_latency_ms=total_latency / total,
        error_rate=error_count / total,
        safety_violation_rate=safety_count / total,
        avg_cost=(total_tokens / total) * 0.001,
        total_conversations=total,
    )
