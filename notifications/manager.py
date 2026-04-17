"""Notification manager for webhooks, Slack, and email alerts."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from notifications.channels import EmailChannel, SlackChannel, WebhookChannel

logger = logging.getLogger(__name__)

# Event types that can trigger notifications
VALID_EVENT_TYPES = {
    "health_drop",
    "optimization_complete",
    "deployment",
    "safety_violation",
    "daily_summary",
    "weekly_summary",
    "new_opportunity",
    "gate_failure",
    # R6.4 / R6.5 — continuous-loop alerts.
    "regression_detected",
    "improvement_queued",
    "continuous_cycle_failed",
    # R6.6 (C10) — drift detector. Registered here so C10 does not touch
    # this file again.
    "drift_detected",
}

# Dedupe window for notification emissions that pass a ``signature`` —
# collapses repeated alerts so the continuous loop cannot spam.
DEFAULT_DEDUPE_WINDOW_SECONDS = 3600


@dataclass
class Subscription:
    """A notification subscription."""

    id: str
    channel_type: str  # webhook, slack, email
    config: dict[str, Any]  # channel-specific config
    events: list[str]  # event types to subscribe to
    filters: dict[str, Any] = field(default_factory=dict)  # severity, agent, time window
    enabled: bool = True
    created_at: float = field(default_factory=time.time)


class NotificationManager:
    """Manages notification subscriptions and dispatches events to channels."""

    def __init__(
        self,
        db_path: str | Path = ".agentlab/notifications.db",
        *,
        dedupe_store: Any | None = None,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

        # Channel implementations
        self.webhook_channel = WebhookChannel()
        self.slack_channel = SlackChannel()
        self.email_channel = EmailChannel()

        # Optional dedupe store — set by callers that care about collapsing
        # repeated emissions (R6.4). Left as None for back-compat.
        self.dedupe_store: Any | None = dedupe_store

    def _init_db(self) -> None:
        """Initialize SQLite database for subscriptions."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id TEXT PRIMARY KEY,
                    channel_type TEXT NOT NULL,
                    config TEXT NOT NULL,
                    events TEXT NOT NULL,
                    filters TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    created_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS notification_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subscription_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    sent_at REAL NOT NULL,
                    success INTEGER NOT NULL,
                    error TEXT
                )
            """)
            conn.commit()

    def register_webhook(
        self, url: str, events: list[str], filters: dict[str, Any] | None = None
    ) -> str:
        """Register a webhook endpoint."""
        subscription_id = f"webhook_{int(time.time() * 1000)}"
        subscription = Subscription(
            id=subscription_id,
            channel_type="webhook",
            config={"url": url},
            events=events,
            filters=filters or {},
        )
        self._save_subscription(subscription)
        return subscription_id

    def register_slack(
        self, webhook_url: str, events: list[str], filters: dict[str, Any] | None = None
    ) -> str:
        """Register a Slack webhook."""
        subscription_id = f"slack_{int(time.time() * 1000)}"
        subscription = Subscription(
            id=subscription_id,
            channel_type="slack",
            config={"webhook_url": webhook_url},
            events=events,
            filters=filters or {},
        )
        self._save_subscription(subscription)
        return subscription_id

    def register_email(
        self,
        address: str,
        events: list[str],
        filters: dict[str, Any] | None = None,
        smtp_config: dict[str, Any] | None = None,
    ) -> str:
        """Register an email notification."""
        subscription_id = f"email_{int(time.time() * 1000)}"
        config = {"address": address}
        if smtp_config:
            config.update(smtp_config)
        subscription = Subscription(
            id=subscription_id,
            channel_type="email",
            config=config,
            events=events,
            filters=filters or {},
        )
        self._save_subscription(subscription)
        return subscription_id

    def _save_subscription(self, subscription: Subscription) -> None:
        """Save subscription to database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO subscriptions
                (id, channel_type, config, events, filters, enabled, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    subscription.id,
                    subscription.channel_type,
                    json.dumps(subscription.config),
                    json.dumps(subscription.events),
                    json.dumps(subscription.filters),
                    1 if subscription.enabled else 0,
                    subscription.created_at,
                ),
            )
            conn.commit()

    def list_subscriptions(self) -> list[Subscription]:
        """List all subscriptions."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT * FROM subscriptions ORDER BY created_at DESC").fetchall()

        subscriptions = []
        for row in rows:
            subscriptions.append(
                Subscription(
                    id=row[0],
                    channel_type=row[1],
                    config=json.loads(row[2]),
                    events=json.loads(row[3]),
                    filters=json.loads(row[4]),
                    enabled=bool(row[5]),
                    created_at=row[6],
                )
            )
        return subscriptions

    def get_subscription(self, subscription_id: str) -> Subscription | None:
        """Get a specific subscription."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM subscriptions WHERE id = ?", (subscription_id,)
            ).fetchone()

        if not row:
            return None

        return Subscription(
            id=row[0],
            channel_type=row[1],
            config=json.loads(row[2]),
            events=json.loads(row[3]),
            filters=json.loads(row[4]),
            enabled=bool(row[5]),
            created_at=row[6],
        )

    def delete_subscription(self, subscription_id: str) -> bool:
        """Delete a subscription."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM subscriptions WHERE id = ?", (subscription_id,))
            conn.commit()
            return cursor.rowcount > 0

    def send(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        workspace: str | None = None,
        signature: str | None = None,
        clock: Callable[[], datetime] | None = None,
        window_seconds: int = DEFAULT_DEDUPE_WINDOW_SECONDS,
    ) -> bool:
        """Send notification to all matching subscriptions.

        Returns True if the event was dispatched, False if suppressed by the
        dedupe store. When ``signature`` is None dedupe is skipped and the
        return value is always True (legacy behavior).
        """
        if event_type not in VALID_EVENT_TYPES:
            raise ValueError(f"Invalid event type: {event_type}. Must be one of {VALID_EVENT_TYPES}")

        # Dedupe gate — only engaged when caller supplies a signature AND a
        # dedupe store has been attached. ``workspace`` must also be set for
        # the dedupe key to make sense; fall back to "" if missing.
        dedupe_workspace = workspace or ""
        now_fn = clock or datetime.utcnow
        if signature is not None and self.dedupe_store is not None:
            try:
                now = now_fn()
                if self.dedupe_store.was_sent_within(
                    event_type,
                    dedupe_workspace,
                    signature,
                    window_seconds=window_seconds,
                    now=now,
                ):
                    return False
            except Exception:
                # Dedupe must never block a legitimate alert — log and fall
                # through so the send still happens.
                logger.exception("dedupe lookup failed; proceeding with send")

        subscriptions = self.list_subscriptions()
        for subscription in subscriptions:
            if not subscription.enabled:
                continue

            if event_type not in subscription.events:
                continue

            # Apply filters
            if not self._matches_filters(payload, subscription.filters):
                continue

            # Dispatch to appropriate channel
            success = False
            error = None
            try:
                if subscription.channel_type == "webhook":
                    self.webhook_channel.send(subscription.config, event_type, payload)
                    success = True
                elif subscription.channel_type == "slack":
                    self.slack_channel.send(subscription.config, event_type, payload)
                    success = True
                elif subscription.channel_type == "email":
                    self.email_channel.send(subscription.config, event_type, payload)
                    success = True
            except Exception as e:
                error = str(e)

            # Log the notification attempt
            self._log_notification(subscription.id, event_type, payload, success, error)

        # Record the dedupe marker after fan-out so repeat emissions in the
        # window are suppressed. Only when caller opted in via ``signature``.
        if signature is not None and self.dedupe_store is not None:
            try:
                self.dedupe_store.record_sent(
                    event_type,
                    dedupe_workspace,
                    signature,
                    sent_at=now_fn(),
                )
            except Exception:
                logger.exception("dedupe record_sent failed")

        return True

    def _matches_filters(self, payload: dict[str, Any], filters: dict[str, Any]) -> bool:
        """Check if payload matches subscription filters."""
        if not filters:
            return True

        # Severity threshold
        if "severity" in filters and "severity" in payload:
            severity_order = ["info", "warning", "error", "critical"]
            filter_level = severity_order.index(filters["severity"])
            payload_level = severity_order.index(payload.get("severity", "info"))
            if payload_level < filter_level:
                return False

        # Agent filter
        if "agent" in filters and "agent" in payload:
            if payload["agent"] != filters["agent"]:
                return False

        # Time window (future enhancement)
        return True

    def _log_notification(
        self,
        subscription_id: str,
        event_type: str,
        payload: dict[str, Any],
        success: bool,
        error: str | None,
    ) -> None:
        """Log notification attempt."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO notification_log
                (subscription_id, event_type, payload, sent_at, success, error)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    subscription_id,
                    event_type,
                    json.dumps(payload),
                    time.time(),
                    1 if success else 0,
                    error,
                ),
            )
            conn.commit()

    def get_notification_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get notification history."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT subscription_id, event_type, payload, sent_at, success, error
                FROM notification_log
                ORDER BY sent_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        history = []
        for row in rows:
            history.append(
                {
                    "subscription_id": row[0],
                    "event_type": row[1],
                    "payload": json.loads(row[2]),
                    "sent_at": row[3],
                    "success": bool(row[4]),
                    "error": row[5],
                }
            )
        return history

    def test_subscription(self, subscription_id: str) -> tuple[bool, str | None]:
        """Send a test notification to a subscription."""
        subscription = self.get_subscription(subscription_id)
        if not subscription:
            return False, "Subscription not found"

        test_payload = {
            "message": "This is a test notification from AgentLab",
            "timestamp": time.time(),
            "test": True,
        }

        try:
            if subscription.channel_type == "webhook":
                self.webhook_channel.send(subscription.config, "test", test_payload)
            elif subscription.channel_type == "slack":
                self.slack_channel.send(subscription.config, "test", test_payload)
            elif subscription.channel_type == "email":
                self.email_channel.send(subscription.config, "test", test_payload)
            return True, None
        except Exception as e:
            return False, str(e)
