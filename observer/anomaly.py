"""2-sigma anomaly detection for health metrics."""

from dataclasses import dataclass

from .metrics import HealthMetrics


@dataclass
class Baseline:
    """Historical baseline for anomaly detection."""
    mean_success_rate: float = 0.85
    std_success_rate: float = 0.05
    mean_latency_ms: float = 150.0
    std_latency_ms: float = 50.0
    mean_error_rate: float = 0.1
    std_error_rate: float = 0.03
    mean_safety_rate: float = 0.01
    std_safety_rate: float = 0.005
    mean_cost: float = 0.15
    std_cost: float = 0.05


class AnomalyDetector:
    def __init__(self, baseline: Baseline | None = None):
        self.baseline = baseline or Baseline()

    def detect(self, metrics: HealthMetrics) -> list[str]:
        """Detect anomalies using 2-sigma rule. Returns list of anomaly descriptions."""
        anomalies: list[str] = []
        b = self.baseline

        # Success rate: anomaly if BELOW mean - 2*std
        lower_bound = b.mean_success_rate - 2 * b.std_success_rate
        if metrics.success_rate < lower_bound:
            anomalies.append(
                f"success_rate={metrics.success_rate:.3f} below threshold {lower_bound:.3f}"
            )

        # Latency: anomaly if ABOVE mean + 2*std
        upper_bound = b.mean_latency_ms + 2 * b.std_latency_ms
        if metrics.avg_latency_ms > upper_bound:
            anomalies.append(
                f"avg_latency_ms={metrics.avg_latency_ms:.1f} above threshold {upper_bound:.1f}"
            )

        # Error rate: anomaly if ABOVE mean + 2*std
        upper_bound = b.mean_error_rate + 2 * b.std_error_rate
        if metrics.error_rate > upper_bound:
            anomalies.append(
                f"error_rate={metrics.error_rate:.3f} above threshold {upper_bound:.3f}"
            )

        # Safety violation rate: anomaly if ABOVE mean + 2*std
        upper_bound = b.mean_safety_rate + 2 * b.std_safety_rate
        if metrics.safety_violation_rate > upper_bound:
            anomalies.append(
                f"safety_violation_rate={metrics.safety_violation_rate:.3f} above threshold {upper_bound:.3f}"
            )

        # Cost: anomaly if ABOVE mean + 2*std
        upper_bound = b.mean_cost + 2 * b.std_cost
        if metrics.avg_cost > upper_bound:
            anomalies.append(
                f"avg_cost={metrics.avg_cost:.3f} above threshold {upper_bound:.3f}"
            )

        return anomalies

    def update_baseline(self, metrics: HealthMetrics, alpha: float = 0.1):
        """Update baseline with exponential moving average."""
        b = self.baseline

        # Update means: new_mean = alpha * current + (1 - alpha) * old_mean
        b.mean_success_rate = alpha * metrics.success_rate + (1 - alpha) * b.mean_success_rate
        b.mean_latency_ms = alpha * metrics.avg_latency_ms + (1 - alpha) * b.mean_latency_ms
        b.mean_error_rate = alpha * metrics.error_rate + (1 - alpha) * b.mean_error_rate
        b.mean_safety_rate = alpha * metrics.safety_violation_rate + (1 - alpha) * b.mean_safety_rate
        b.mean_cost = alpha * metrics.avg_cost + (1 - alpha) * b.mean_cost

        # Update stds using EMA of absolute deviation as approximation
        b.std_success_rate = alpha * abs(metrics.success_rate - b.mean_success_rate) + (1 - alpha) * b.std_success_rate
        b.std_latency_ms = alpha * abs(metrics.avg_latency_ms - b.mean_latency_ms) + (1 - alpha) * b.std_latency_ms
        b.std_error_rate = alpha * abs(metrics.error_rate - b.mean_error_rate) + (1 - alpha) * b.std_error_rate
        b.std_safety_rate = alpha * abs(metrics.safety_violation_rate - b.mean_safety_rate) + (1 - alpha) * b.std_safety_rate
        b.std_cost = alpha * abs(metrics.avg_cost - b.mean_cost) + (1 - alpha) * b.std_cost
