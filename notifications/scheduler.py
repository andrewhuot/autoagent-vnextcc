"""Scheduled notification system — daily/weekly summaries."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from notifications.manager import NotificationManager


@dataclass
class ScheduledTask:
    """A scheduled notification task."""

    task_id: str
    event_type: str
    interval_seconds: float
    payload_generator: Callable[[], dict[str, Any]]
    last_run: float = 0.0
    enabled: bool = True


class NotificationScheduler:
    """Schedules periodic notifications like daily/weekly summaries."""

    def __init__(self, notification_manager: NotificationManager):
        self.notification_manager = notification_manager
        self.tasks: dict[str, ScheduledTask] = {}

    def schedule_daily_summary(
        self, payload_generator: Callable[[], dict[str, Any]]
    ) -> str:
        """Schedule a daily summary notification."""
        task_id = f"daily_summary_{int(time.time())}"
        task = ScheduledTask(
            task_id=task_id,
            event_type="daily_summary",
            interval_seconds=86400,  # 24 hours
            payload_generator=payload_generator,
        )
        self.tasks[task_id] = task
        return task_id

    def schedule_weekly_summary(
        self, payload_generator: Callable[[], dict[str, Any]]
    ) -> str:
        """Schedule a weekly summary notification."""
        task_id = f"weekly_summary_{int(time.time())}"
        task = ScheduledTask(
            task_id=task_id,
            event_type="weekly_summary",
            interval_seconds=604800,  # 7 days
            payload_generator=payload_generator,
        )
        self.tasks[task_id] = task
        return task_id

    def schedule_custom(
        self,
        event_type: str,
        interval_seconds: float,
        payload_generator: Callable[[], dict[str, Any]],
    ) -> str:
        """Schedule a custom periodic notification."""
        task_id = f"custom_{event_type}_{int(time.time())}"
        task = ScheduledTask(
            task_id=task_id,
            event_type=event_type,
            interval_seconds=interval_seconds,
            payload_generator=payload_generator,
        )
        self.tasks[task_id] = task
        return task_id

    def run_due_tasks(self) -> list[str]:
        """Run all tasks that are due and return list of task IDs that ran."""
        now = time.time()
        ran_tasks = []

        for task in self.tasks.values():
            if not task.enabled:
                continue

            if now - task.last_run >= task.interval_seconds:
                try:
                    payload = task.payload_generator()
                    self.notification_manager.send(task.event_type, payload)
                    task.last_run = now
                    ran_tasks.append(task.task_id)
                except Exception:
                    # Log error but continue with other tasks
                    pass

        return ran_tasks

    def enable_task(self, task_id: str) -> bool:
        """Enable a scheduled task."""
        if task_id in self.tasks:
            self.tasks[task_id].enabled = True
            return True
        return False

    def disable_task(self, task_id: str) -> bool:
        """Disable a scheduled task."""
        if task_id in self.tasks:
            self.tasks[task_id].enabled = False
            return True
        return False

    def delete_task(self, task_id: str) -> bool:
        """Delete a scheduled task."""
        if task_id in self.tasks:
            del self.tasks[task_id]
            return True
        return False

    def list_tasks(self) -> list[ScheduledTask]:
        """List all scheduled tasks."""
        return list(self.tasks.values())
