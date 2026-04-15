"""Workbench-facing coordinator runtime.

This module adapts the shared Builder coordinator turn service to the terminal
session context: it pulls active project/session ids from ``SlashContext.meta``
and writes the latest plan/run ids back so slash commands such as ``/tasks``
can render current work without re-querying the user.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from builder.coordinator_runtime import CoordinatorWorkerRuntime
from builder.coordinator_turn import CoordinatorTurnResult
from builder.events import BuilderEvent, EventBroker
from builder.orchestrator import BuilderOrchestrator
from builder.store import BuilderStore
from builder.worker_mode import WorkerMode, resolve_effective_worker_mode
from cli.workbench_app.coordinator_session import CoordinatorSession


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
        configs_dir: str | Path | None = None,
        worker_mode: WorkerMode | None = None,
    ) -> None:
        self._store = store or BuilderStore(db_path=db_path or ".agentlab/builder.db")
        self._events = events or EventBroker()
        self._orchestrator = orchestrator or BuilderOrchestrator(store=self._store)
        self._coordinator_runtime = coordinator_runtime or CoordinatorWorkerRuntime(
            store=self._store,
            orchestrator=self._orchestrator,
            events=self._events,
            worker_mode=worker_mode,
            checkpoint_manager=_build_checkpoint_manager(configs_dir),
        )
        # Mirror the coordinator runtime's resolved mode so callers that only
        # hold a WorkbenchAgentRuntime reference can render the active mode
        # without reaching into internals.
        self._worker_mode = self._coordinator_runtime.worker_mode
        self._coordinator_session = CoordinatorSession(
            store=self._store,
            orchestrator=self._orchestrator,
            events=self._events,
            runtime=self._coordinator_runtime,
        )

    @property
    def worker_mode(self) -> WorkerMode:
        """Return the :class:`WorkerMode` driving worker execution."""
        return self._worker_mode

    @property
    def worker_mode_degraded_reason(self) -> str | None:
        """Return a one-line reason when workers are running deterministic stubs."""
        return self._coordinator_runtime.worker_mode_degraded_reason

    @property
    def coordinator_session(self) -> CoordinatorSession:
        """Return the in-process coordinator session backing the Workbench."""
        return self._coordinator_session

    def process_turn(
        self,
        message: str,
        *,
        ctx: Any | None = None,
        command_intent: str | None = None,
        dry_run: bool = False,
        stream: bool = False,
    ) -> CoordinatorTurnResult | Iterator[BuilderEvent]:
        """Run one terminal turn and synchronize context metadata.

        ``dry_run=True`` plans without executing — used by :class:`PlanGate`
        to render the proposed worker roster before asking the operator
        for approval.

        ``stream=True`` returns a generator that yields each
        :class:`BuilderEvent` as it becomes available and finally returns
        (via ``StopIteration.value``) the materialized
        :class:`CoordinatorTurnResult`. Callers use this to drive live
        progress rendering in the REPL. The batched default behaviour is
        unchanged so existing tests and API surfaces stay green.
        """
        project_id = _meta_get(ctx, "builder_project_id")
        session_id = _meta_get(ctx, "builder_session_id")
        permission_mode = _meta_get(ctx, "permission_mode")
        if stream and not dry_run:
            return self._stream_turn(
                message=message,
                ctx=ctx,
                project_id=project_id,
                session_id=session_id,
                command_intent=command_intent,
                permission_mode=permission_mode,
            )
        result = self._coordinator_session.process_turn(
            message,
            project_id=project_id,
            session_id=session_id,
            command_intent=command_intent,
            permission_mode=permission_mode,
            dry_run=dry_run,
        )
        if not dry_run:
            remember_turn_result(ctx, result)
        return result

    def _stream_turn(
        self,
        *,
        message: str,
        ctx: Any | None,
        project_id: str | None,
        session_id: str | None,
        command_intent: str | None,
        permission_mode: str | None,
    ) -> Iterator[BuilderEvent]:
        """Generator-driven coordinator turn for live REPL rendering.

        Yields :class:`BuilderEvent` values as the underlying session
        produces them; the final :class:`CoordinatorTurnResult` is delivered
        via ``StopIteration.value`` so callers can both echo events and
        update context metadata without double-running the turn.
        """
        from builder.coordinator_turn import detect_command_intent

        cleaned = " ".join(str(message or "").split())
        if not cleaned:
            raise ValueError("Coordinator turn message cannot be empty")
        intent = command_intent or detect_command_intent(cleaned)

        session = self._coordinator_session
        plan = session.plan(
            cleaned,
            verb=intent,
            context={
                "permission_mode": permission_mode or "default",
                "workbench_surface": "cli",
                "dry_run": False,
            },
        )
        plan_id = str(plan["plan_id"])

        collected: list[BuilderEvent] = []
        for event in session.execute_iter(plan_id):
            collected.append(event)
            yield event

        result = session.finalize(
            plan=plan,
            events=tuple(collected),
            intent=intent,
            message=cleaned,
        )
        remember_turn_result(ctx, result)
        return result


def build_default_agent_runtime(workspace: Any | None) -> WorkbenchAgentRuntime:
    """Create the default runtime rooted in the active workspace."""
    root = getattr(workspace, "root", None)
    if root is None:
        return WorkbenchAgentRuntime()
    db_path = str(Path(root) / ".agentlab" / "builder.db")
    return WorkbenchAgentRuntime(db_path=db_path, configs_dir=Path(root) / "configs")


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


def _build_checkpoint_manager(configs_dir: str | Path | None) -> Any | None:
    """Return a checkpoint manager when a workspace config directory is known."""
    if configs_dir is None:
        return None
    try:
        from cli.workbench_app.checkpoint import CheckpointManager

        return CheckpointManager(configs_dir=configs_dir)
    except Exception:
        return None


__all__ = [
    "WorkbenchAgentRuntime",
    "build_default_agent_runtime",
    "remember_turn_result",
]
