"""Workbench-facing coordinator runtime.

This module adapts the shared Builder coordinator turn service to the terminal
session context: it pulls active project/session ids from ``SlashContext.meta``
and writes the latest plan/run ids back so slash commands such as ``/tasks``
can render current work without re-querying the user.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from builder.coordinator_runtime import CoordinatorWorkerRuntime
from builder.coordinator_turn import CoordinatorTurnResult, CoordinatorTurnService
from builder.events import EventBroker
from builder.orchestrator import BuilderOrchestrator
from builder.store import BuilderStore


class WorkbenchAgentRuntime:
    """Process Workbench user turns through the Builder coordinator."""

    def __init__(
        self,
        *,
        store: BuilderStore | None = None,
        orchestrator: BuilderOrchestrator | None = None,
        events: EventBroker | None = None,
        coordinator_runtime: CoordinatorWorkerRuntime | None = None,
        db_path: str | None = None,
    ) -> None:
        self._store = store or BuilderStore(db_path=db_path or ".agentlab/builder.db")
        self._events = events or EventBroker()
        self._orchestrator = orchestrator or BuilderOrchestrator(store=self._store)
        self._coordinator_runtime = coordinator_runtime or CoordinatorWorkerRuntime(
            store=self._store,
            orchestrator=self._orchestrator,
            events=self._events,
        )
        self._service = CoordinatorTurnService(
            store=self._store,
            orchestrator=self._orchestrator,
            events=self._events,
            runtime=self._coordinator_runtime,
        )

    def process_turn(
        self,
        message: str,
        *,
        ctx: Any | None = None,
        command_intent: str | None = None,
    ) -> CoordinatorTurnResult:
        """Run one terminal turn and synchronize context metadata."""
        project_id = _meta_get(ctx, "builder_project_id")
        session_id = _meta_get(ctx, "builder_session_id")
        permission_mode = _meta_get(ctx, "permission_mode")
        result = self._service.process_turn(
            message,
            project_id=project_id,
            session_id=session_id,
            command_intent=command_intent,
            permission_mode=permission_mode,
        )
        remember_turn_result(ctx, result)
        return result


def build_default_agent_runtime(workspace: Any | None) -> WorkbenchAgentRuntime:
    """Create the default runtime rooted in the active workspace."""
    root = getattr(workspace, "root", None)
    if root is None:
        return WorkbenchAgentRuntime()
    db_path = str(Path(root) / ".agentlab" / "builder.db")
    return WorkbenchAgentRuntime(db_path=db_path)


def remember_turn_result(ctx: Any | None, result: Any) -> None:
    """Persist the latest coordinator turn details into slash context metadata."""
    if ctx is None:
        return
    meta = getattr(ctx, "meta", None)
    if not isinstance(meta, dict):
        return
    meta["latest_coordinator_turn"] = result
    meta["builder_project_id"] = getattr(result, "project_id", None)
    meta["builder_session_id"] = getattr(result, "session_id", None)
    meta["latest_builder_task_id"] = getattr(result, "task_id", None)
    meta["latest_coordinator_plan_id"] = getattr(result, "plan_id", None)
    meta["latest_coordinator_run_id"] = getattr(result, "run_id", None)
    meta["active_tasks"] = int(getattr(result, "active_tasks", 0) or 0)
    review_cards = getattr(result, "review_cards", ())
    if review_cards:
        meta["review_cards"] = list(review_cards)


def _meta_get(ctx: Any | None, key: str) -> str | None:
    """Return a string metadata value from a slash context."""
    meta = getattr(ctx, "meta", None)
    if not isinstance(meta, dict):
        return None
    value = meta.get(key)
    return str(value) if value else None


__all__ = [
    "WorkbenchAgentRuntime",
    "build_default_agent_runtime",
    "remember_turn_result",
]
