"""Observer package — health monitoring, anomaly detection, failure classification,
and OpenTelemetry-native observability."""

from logger.store import ConversationStore

from .anomaly import AnomalyDetector, Baseline
from .trace_promoter import TraceCandidate, TracePromoter
from .auto_instrumentor import AutoInstrumentor
from .classifier import FailureClassifier
from .exporters import (
    ExporterFactory,
    OtelCloudTraceExporter,
    OtelConsoleExporter,
    OtelExporter,
    OtelJsonFileExporter,
    OtelOtlpHttpExporter,
)
from .metrics import HealthMetrics, HealthReport, compute_metrics
from .otel import GENAI_ATTRIBUTES, OtelSpanAdapter
from .otel_config import OtelConfig, load_otel_config
from .otel_types import (
    OtelEvent,
    OtelLink,
    OtelResource,
    OtelSpan,
    OtelSpanContext,
    OtelSpanKind,
    OtelStatus,
    OtelStatusCode,
    OtelTrace,
)


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
    # Core observer
    "Observer",
    "HealthReport",
    "HealthMetrics",
    "AnomalyDetector",
    "Baseline",
    "FailureClassifier",
    "compute_metrics",
    # OTel types
    "OtelResource",
    "OtelSpanContext",
    "OtelSpanKind",
    "OtelStatusCode",
    "OtelStatus",
    "OtelEvent",
    "OtelLink",
    "OtelSpan",
    "OtelTrace",
    # OTel adapter
    "GENAI_ATTRIBUTES",
    "OtelSpanAdapter",
    # OTel exporters
    "OtelExporter",
    "OtelConsoleExporter",
    "OtelJsonFileExporter",
    "OtelOtlpHttpExporter",
    "OtelCloudTraceExporter",
    "ExporterFactory",
    # OTel config
    "OtelConfig",
    "load_otel_config",
    # Auto-instrumentation
    "AutoInstrumentor",
    # Trace-to-eval pipeline (P0-6)
    "TraceCandidate",
    "TracePromoter",
]
