"""Observer package — health monitoring, anomaly detection, and failure classification."""

from logger.store import ConversationStore

from .anomaly import AnomalyDetector, Baseline
from .classifier import FailureClassifier
from .metrics import HealthMetrics, HealthReport, compute_metrics


class Observer:
    """Top-level observer that ties metrics, anomaly detection, and failure classification together."""

    def __init__(self, store: ConversationStore):
        self.store = store
        self.anomaly_detector = AnomalyDetector()
        self.classifier = FailureClassifier()

    def observe(self, window: int = 100) -> HealthReport:
        """Run full observation: compute metrics, detect anomalies, classify failures."""
        records = self.store.get_recent(limit=window)
        metrics = compute_metrics(records)
        anomalies = self.anomaly_detector.detect(metrics)
        failures = [record for record in records if record.outcome in {"fail", "error", "abandon"}]
        failure_buckets = self.classifier.classify_batch(failures)

        # Keep baseline adaptive so anomaly sensitivity tracks evolving traffic.
        self.anomaly_detector.update_baseline(metrics)

        needs_optimization = (
            len(anomalies) > 0
            or metrics.success_rate < 0.8
            or metrics.error_rate > 0.15
            or metrics.safety_violation_rate > 0.02
        )
        reason = "; ".join(anomalies) if anomalies else ""
        if not reason and needs_optimization:
            reason = f"success_rate={metrics.success_rate:.2f}, error_rate={metrics.error_rate:.2f}"

        return HealthReport(
            metrics=metrics,
            anomalies=anomalies,
            failure_buckets=failure_buckets,
            needs_optimization=needs_optimization,
            reason=reason,
        )


__all__ = [
    "Observer",
    "HealthReport",
    "HealthMetrics",
    "AnomalyDetector",
    "Baseline",
    "FailureClassifier",
    "compute_metrics",
]
