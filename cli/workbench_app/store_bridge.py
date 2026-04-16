"""Bridge between coordinator events and the centralized state store.

Subscribes to ``EventBroker`` events and translates each ``BuilderEvent``
into a ``store.set_state()`` call, keeping the TUI reactive without any
polling. The adapter is framework-agnostic — it updates the ``Store``
directly and lets Textual (or any other subscriber) handle re-rendering.

Two adapters are provided:

``EventStoreAdapter``
    Wires ``EventBroker.publish`` events into store state updates. This
    is the long-term path — as more of the system emits ``BuilderEvent``
    instances, this adapter maps them to the appropriate ``AppState``
    fields.

``SlashContextSync``
    Temporary bridge that reads ``SlashContext.meta`` mutations and syncs
    them into the store. Will be removed once slash handlers move to
    direct store updates.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from builder.events import BuilderEvent, BuilderEventType, EventBroker
from cli.workbench_app.store import (
    AppState,
    CoordinatorStatus,
    Store,
    WorkerPhase,
    WorkerState,
    append_message,
    clear_coordinator,
    set_coordinator_status,
    set_streaming_content,
    update_worker,
)


logger = logging.getLogger(__name__)


__all__ = [
    "EventStoreAdapter",
    "SlashContextSync",
]


# ---------------------------------------------------------------------------
# Event type → store updater mapping
# ---------------------------------------------------------------------------


# Map BuilderEventType to WorkerPhase for worker lifecycle events.
_WORKER_PHASE_MAP: dict[BuilderEventType, WorkerPhase] = {
    BuilderEventType.WORKER_GATHERING_CONTEXT: WorkerPhase.GATHERING_CONTEXT,
    BuilderEventType.WORKER_ACTING: WorkerPhase.ACTING,
    BuilderEventType.WORKER_VERIFYING: WorkerPhase.VERIFYING,
    BuilderEventType.WORKER_COMPLETED: WorkerPhase.COMPLETED,
    BuilderEventType.WORKER_FAILED: WorkerPhase.FAILED,
    BuilderEventType.WORKER_BLOCKED: WorkerPhase.BLOCKED,
}


class EventStoreAdapter:
    """Map ``BuilderEvent`` instances to ``Store[AppState]`` updates.

    Typical usage::

        adapter = EventStoreAdapter(store)
        adapter.handle_event(event)   # called from the event broker loop

    Or wire it to an ``EventBroker`` via :meth:`bind_broker`.
    """

    def __init__(self, store: Store[AppState]) -> None:
        self._store = store

    # ------------------------------------------------------ public interface

    def handle_event(self, event: BuilderEvent) -> None:
        """Dispatch a single event to the appropriate store updater."""
        try:
            self._dispatch(event)
        except Exception:
            logger.warning(
                "EventStoreAdapter failed to handle %s",
                event.event_type.value,
                exc_info=True,
            )

    def bind_broker(self, broker: EventBroker) -> None:
        """Monkey-patch the broker's publish method to also update the store.

        This is a pragmatic bridge — the broker doesn't have a native
        subscription API beyond SSE polling. We wrap ``publish()`` so
        every event flows through the store adapter synchronously.
        """
        original_publish = broker.publish

        def _publishing_wrapper(
            event_type: BuilderEventType,
            session_id: str,
            task_id: str | None,
            payload: dict[str, Any],
        ) -> BuilderEvent:
            event = original_publish(event_type, session_id, task_id, payload)
            self.handle_event(event)
            return event

        broker.publish = _publishing_wrapper  # type: ignore[assignment]

    # ------------------------------------------------------- internal dispatch

    def _dispatch(self, event: BuilderEvent) -> None:
        etype = event.event_type
        payload = event.payload

        # --- Coordinator lifecycle ---
        if etype == BuilderEventType.COORDINATOR_EXECUTION_STARTED:
            self._on_coordinator_started(event)
        elif etype in (
            BuilderEventType.COORDINATOR_EXECUTION_COMPLETED,
            BuilderEventType.COORDINATOR_SYNTHESIS_COMPLETED,
        ):
            self._on_coordinator_completed(event)
        elif etype in (
            BuilderEventType.COORDINATOR_EXECUTION_FAILED,
            BuilderEventType.COORDINATOR_EXECUTION_BLOCKED,
        ):
            self._on_coordinator_failed(event)

        # --- Worker lifecycle ---
        elif etype in _WORKER_PHASE_MAP:
            self._on_worker_phase(event, _WORKER_PHASE_MAP[etype])

        # --- Message streaming ---
        elif etype == BuilderEventType.MESSAGE_DELTA:
            self._on_message_delta(event)
        elif etype == BuilderEventType.WORKER_MESSAGE_DELTA:
            self._on_message_delta(event)

        # --- Task lifecycle ---
        elif etype == BuilderEventType.TASK_STARTED:
            self._on_task_started(event)
        elif etype == BuilderEventType.TASK_COMPLETED:
            self._on_task_completed(event)
        elif etype == BuilderEventType.TASK_FAILED:
            self._on_task_failed(event)
        elif etype == BuilderEventType.TASK_PROGRESS:
            pass  # progress events are high-frequency; skip for now

        # --- Session lifecycle ---
        elif etype == BuilderEventType.SESSION_OPENED:
            self._store.set_state(
                lambda s: replace(s, coordinator_session_id=event.session_id)
            )
        elif etype == BuilderEventType.SESSION_CLOSED:
            self._store.set_state(clear_coordinator())

        # --- LLM events ---
        elif etype == BuilderEventType.LLM_FALLBACK:
            model = payload.get("fallback_model", "")
            self._store.set_state(append_message(
                "warning",
                f"LLM fallback to {model}",
            ))
        elif etype == BuilderEventType.LLM_RETRY:
            reason = payload.get("reason", "")
            self._store.set_state(append_message(
                "warning",
                f"LLM retry: {reason}",
            ))

        # --- Degraded mode ---
        elif etype == BuilderEventType.COORDINATOR_WORKER_MODE_DEGRADED:
            reason = payload.get("reason", "unknown")
            self._store.set_state(append_message(
                "warning",
                f"Worker mode degraded: {reason}",
            ))

    # ------------------------------------------------- coordinator handlers

    def _on_coordinator_started(self, event: BuilderEvent) -> None:
        payload = event.payload
        worker_roster = payload.get("worker_roster", [])
        workers = tuple(
            WorkerState(
                worker_id=w.get("worker_id", f"worker-{i}"),
                role=w.get("role", "worker"),
                phase=WorkerPhase.QUEUED,
            )
            for i, w in enumerate(worker_roster)
        )

        def _update(state: AppState) -> AppState:
            return replace(
                state,
                coordinator_status=CoordinatorStatus.RUNNING,
                coordinator_workers=workers,
                coordinator_session_id=event.session_id,
                coordinator_task_id=event.task_id,
            )

        self._store.set_state(_update)

    def _on_coordinator_completed(self, event: BuilderEvent) -> None:
        self._store.set_state(set_coordinator_status(CoordinatorStatus.IDLE))

    def _on_coordinator_failed(self, event: BuilderEvent) -> None:
        reason = event.payload.get("error", "")

        def _update(state: AppState) -> AppState:
            updated = replace(state, coordinator_status=CoordinatorStatus.FAILED)
            if reason:
                from cli.workbench_app.transcript import TranscriptEntry
                entry = TranscriptEntry(role="error", content=f"Coordinator: {reason}")
                updated = replace(updated, messages=updated.messages + (entry,))
            return updated

        self._store.set_state(_update)

    # ------------------------------------------------- worker handlers

    def _on_worker_phase(self, event: BuilderEvent, phase: WorkerPhase) -> None:
        payload = event.payload
        worker_id = payload.get("worker_id", "")
        role = payload.get("worker_role", "worker")
        detail = payload.get("detail") or payload.get("note") or None

        fields: dict[str, Any] = {"role": role, "phase": phase}
        if detail:
            fields["detail"] = detail
        if phase in (WorkerPhase.COMPLETED, WorkerPhase.FAILED, WorkerPhase.BLOCKED):
            import time
            fields["completed_at"] = time.time()

        self._store.set_state(update_worker(worker_id, **fields))

    # ------------------------------------------------- message handlers

    def _on_message_delta(self, event: BuilderEvent) -> None:
        delta = event.payload.get("delta", "")
        if not delta:
            return

        def _update(state: AppState) -> AppState:
            current = state.streaming_content or ""
            return replace(state, streaming_content=current + delta)

        self._store.set_state(_update)

    # ------------------------------------------------- task handlers

    def _on_task_started(self, event: BuilderEvent) -> None:
        def _update(state: AppState) -> AppState:
            return replace(
                state,
                active_tasks=state.active_tasks + 1,
                coordinator_task_id=event.task_id,
            )
        self._store.set_state(_update)

    def _on_task_completed(self, event: BuilderEvent) -> None:
        # Finalize streaming content into a message, reset streaming buffer
        def _update(state: AppState) -> AppState:
            messages = state.messages
            if state.streaming_content:
                from cli.workbench_app.transcript import TranscriptEntry
                entry = TranscriptEntry(
                    role=state.streaming_role,
                    content=state.streaming_content,
                )
                messages = messages + (entry,)
            return replace(
                state,
                active_tasks=max(0, state.active_tasks - 1),
                messages=messages,
                streaming_content=None,
            )
        self._store.set_state(_update)

    def _on_task_failed(self, event: BuilderEvent) -> None:
        error = event.payload.get("error", "Task failed")

        def _update(state: AppState) -> AppState:
            from cli.workbench_app.transcript import TranscriptEntry
            entry = TranscriptEntry(role="error", content=error)
            return replace(
                state,
                active_tasks=max(0, state.active_tasks - 1),
                streaming_content=None,
                messages=state.messages + (entry,),
            )

        self._store.set_state(_update)


# ---------------------------------------------------------------------------
# SlashContextSync — temporary bridge from SlashContext.meta to Store
# ---------------------------------------------------------------------------


class SlashContextSync:
    """Sync ``SlashContext.meta`` dict into the store.

    This is a stop-gap: existing slash handlers write to ``ctx.meta``
    (a plain dict) rather than the store. This adapter reads the dict
    and pushes relevant fields into ``AppState``. Once handlers are
    migrated to use the store directly, this class is deleted.
    """

    # Keys in SlashContext.meta that map to AppState fields.
    _KEY_MAP: dict[str, str] = {
        "active_shells": "active_shells",
        "active_tasks": "active_tasks",
        "builder_session_id": "coordinator_session_id",
        "latest_builder_task_id": "coordinator_task_id",
    }

    def __init__(self, store: Store[AppState]) -> None:
        self._store = store

    def sync(self, meta: dict[str, Any]) -> None:
        """Push relevant ``meta`` keys into the store."""
        updates: dict[str, Any] = {}
        for meta_key, state_field in self._KEY_MAP.items():
            if meta_key in meta:
                updates[state_field] = meta[meta_key]
        if not updates:
            return
        self._store.set_state(lambda s: replace(s, **updates))
