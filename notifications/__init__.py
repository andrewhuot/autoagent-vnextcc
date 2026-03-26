"""Notifications system for AutoAgent — webhooks, Slack, email alerts."""

from __future__ import annotations

from notifications.manager import NotificationManager, Subscription

__all__ = ["NotificationManager", "Subscription"]
