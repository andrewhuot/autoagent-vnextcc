"""Integration helpers for emitting notifications from other modules."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from notifications.manager import NotificationManager


def emit_health_drop(
    notification_manager: NotificationManager,
    metric: str,
    old_value: float,
    new_value: float,
    severity: str = "warning",
) -> None:
    """Emit health_drop notification."""
    notification_manager.send(
        "health_drop",
        {
            "message": f"Health metric '{metric}' dropped from {old_value:.2f} to {new_value:.2f}",
            "metric": metric,
            "old_value": old_value,
            "new_value": new_value,
            "severity": severity,
        },
    )


def emit_optimization_complete(
    notification_manager: NotificationManager,
    experiment_id: str,
    status: str,
    improvement: float | None = None,
) -> None:
    """Emit optimization_complete notification."""
    payload: dict[str, Any] = {
        "message": f"Optimization {status}: experiment {experiment_id}",
        "experiment_id": experiment_id,
        "status": status,
        "severity": "info",
    }
    if improvement is not None:
        payload["improvement"] = improvement

    notification_manager.send("optimization_complete", payload)


def emit_deployment(
    notification_manager: NotificationManager,
    config_sha: str,
    deployment_type: str,
    status: str,
) -> None:
    """Emit deployment notification."""
    notification_manager.send(
        "deployment",
        {
            "message": f"Deployment {status}: {deployment_type} of config {config_sha[:8]}",
            "config_sha": config_sha,
            "deployment_type": deployment_type,
            "status": status,
            "severity": "info",
        },
    )


def emit_safety_violation(
    notification_manager: NotificationManager,
    violation_type: str,
    details: str,
    conversation_id: str | None = None,
) -> None:
    """Emit safety_violation notification."""
    payload: dict[str, Any] = {
        "message": f"Safety violation detected: {violation_type}",
        "violation_type": violation_type,
        "details": details,
        "severity": "critical",
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id

    notification_manager.send("safety_violation", payload)


def emit_gate_failure(
    notification_manager: NotificationManager,
    gate_type: str,
    reason: str,
    experiment_id: str | None = None,
) -> None:
    """Emit gate_failure notification."""
    payload: dict[str, Any] = {
        "message": f"Gate failure: {gate_type} - {reason}",
        "gate_type": gate_type,
        "reason": reason,
        "severity": "error",
    }
    if experiment_id:
        payload["experiment_id"] = experiment_id

    notification_manager.send("gate_failure", payload)


def emit_new_opportunity(
    notification_manager: NotificationManager,
    opportunity_id: str,
    failure_family: str,
    priority_score: float,
) -> None:
    """Emit new_opportunity notification."""
    notification_manager.send(
        "new_opportunity",
        {
            "message": f"New optimization opportunity: {failure_family} (priority: {priority_score:.2f})",
            "opportunity_id": opportunity_id,
            "failure_family": failure_family,
            "priority_score": priority_score,
            "severity": "info",
        },
    )
