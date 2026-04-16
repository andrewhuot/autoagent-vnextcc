"""Centralized state store for the workbench TUI.

Port of Claude Code's ``Store<T>`` pattern: a single source of truth for all
session state with subscribe/notify semantics. Widgets subscribe via selectors
and re-render only when their selected slice changes.

The store is framework-agnostic — it uses no Textual imports so it can be
unit-tested in isolation and also used by the existing CLI path if desired.

State Flow
----------
::

    BuilderEvent (EventBroker)
      → store_bridge.EventStoreAdapter
        → store.set_state(updater)
          → listeners notified
            → Textual widgets re-render

Usage::

    store = Store(get_default_app_state())

    # Subscribe to changes
    unsub = store.subscribe(lambda: print(store.get_state().permission_mode))

    # Update state via pure function
    store.set_state(lambda s: replace(s, permission_mode="plan"))
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from enum import Enum
from threading import RLock
from typing import Any, Callable, Generic, Mapping, TypeVar

from cli.workbench_app.effort import EffortSnapshot
from cli.workbench_app.transcript import TranscriptEntry, TranscriptRole


__all__ = [
    "AppState",
    "CoordinatorStatus",
    "FooterSlice",
    "StatusBarSlice",
    "Store",
    "WorkerState",
    "WorkerPhase",
    "append_message",
    "clear_coordinator",
    "get_default_app_state",
    "select_footer",
    "select_messages",
    "select_status_bar",
    "set_coordinator_status",
    "set_streaming_content",
    "update_worker",
]


T = TypeVar("T")
Listener = Callable[[], None]
Updater = Callable[[T], T]


# ---------------------------------------------------------------------------
# Store — generic observable state container
# ---------------------------------------------------------------------------


class Store(Generic[T]):
    """Thread-safe observable state container.

    Mirrors Claude Code's ``createStore<T>``: holds state, exposes
    ``get_state()`` / ``set_state(updater)``, and notifies subscribers
    synchronously on change. Uses identity comparison (``is``) on frozen
    dataclasses to skip no-op updates.
    """

    def __init__(
        self,
        initial_state: T,
        *,
        on_change: Callable[[T, T], None] | None = None,
    ) -> None:
        self._state = initial_state
        self._listeners: list[Listener] = []
        self._lock = RLock()
        self._on_change = on_change

    def get_state(self) -> T:
        """Return the current state snapshot."""
        return self._state

    def set_state(self, updater: Updater[T]) -> None:
        """Update state via a pure function and notify subscribers.

        If the updater returns the same object (identity check), no
        listeners are called — this prevents cascading re-renders on
        no-op updates, matching Claude Code's ``Object.is`` guard.
        """
        with self._lock:
            prev = self._state
            next_state = updater(prev)
            if next_state is prev:
                return
            self._state = next_state
            listeners = list(self._listeners)

        if self._on_change is not None:
            self._on_change(prev, next_state)

        for listener in listeners:
            listener()

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        """Register a listener called on every state change.

        Returns an unsubscribe callable.
        """
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                try:
                    self._listeners.remove(listener)
                except ValueError:
                    pass  # already removed

        return unsubscribe


# ---------------------------------------------------------------------------
# AppState — the single state shape for the workbench session
# ---------------------------------------------------------------------------


class CoordinatorStatus(str, Enum):
    """Top-level coordinator lifecycle phase."""
    IDLE = "idle"
    RUNNING = "running"
    BLOCKED = "blocked"
    FAILED = "failed"


class WorkerPhase(str, Enum):
    """Per-worker execution phase."""
    QUEUED = "queued"
    GATHERING_CONTEXT = "gathering_context"
    ACTING = "acting"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class WorkerState:
    """Snapshot of a single coordinator worker."""
    worker_id: str = ""
    role: str = ""
    phase: WorkerPhase = WorkerPhase.QUEUED
    detail: str | None = None
    started_at: float = 0.0
    completed_at: float | None = None


@dataclass(frozen=True)
class AppState:
    """Immutable state for the workbench TUI.

    Consolidates state previously scattered across ``StatusSnapshot``,
    ``WorkbenchPromptState``, ``SlashContext.meta``, and ``Transcript``.
    All fields are immutable; use ``dataclasses.replace()`` to produce
    updated copies.
    """

    # --- Status bar fields (from StatusSnapshot) ---
    workspace_label: str | None = None
    config_version: int | None = None
    model: str | None = None
    provider: str | None = None
    provider_key_present: bool = True
    pending_reviews: int = 0
    best_score: str | None = None
    agentlab_version: str = ""
    session_title: str | None = None
    tokens_used: int | None = None
    context_limit: int | None = None

    # --- Permission / prompt state (from WorkbenchPromptState) ---
    permission_mode: str = "default"
    cycle_count: int = 0

    # --- Activity counters (from SlashContext.meta) ---
    active_shells: int = 0
    active_tasks: int = 0

    # --- Transcript (from Transcript._entries) ---
    messages: tuple[TranscriptEntry, ...] = ()

    # --- Streaming content (for in-progress LLM output) ---
    streaming_content: str | None = None
    streaming_role: TranscriptRole = "assistant"

    # --- Coordinator state (new, driven by BuilderEvent) ---
    coordinator_status: CoordinatorStatus = CoordinatorStatus.IDLE
    coordinator_workers: tuple[WorkerState, ...] = ()
    coordinator_session_id: str | None = None
    coordinator_task_id: str | None = None

    # --- Effort indicator ---
    effort: EffortSnapshot | None = None

    # --- Theme ---
    theme_name: str = "default"

    # --- Output style ---
    output_style: str = "text"

    # --- Background tasks ---
    background_tasks: tuple[Any, ...] = ()


def get_default_app_state() -> AppState:
    """Return a fresh ``AppState`` with all defaults."""
    return AppState()


# ---------------------------------------------------------------------------
# Selectors — pure functions that extract widget-specific slices
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StatusBarSlice:
    """The subset of state the StatusFooter widget cares about."""
    workspace_label: str | None
    config_version: int | None
    model: str | None
    provider: str | None
    provider_key_present: bool
    pending_reviews: int
    best_score: str | None
    agentlab_version: str
    session_title: str | None
    tokens_used: int | None
    context_limit: int | None


@dataclass(frozen=True)
class FooterSlice:
    """The subset of state the input footer cares about."""
    permission_mode: str
    active_shells: int
    active_tasks: int
    coordinator_status: CoordinatorStatus


def select_status_bar(state: AppState) -> StatusBarSlice:
    """Extract status bar fields from the full state."""
    return StatusBarSlice(
        workspace_label=state.workspace_label,
        config_version=state.config_version,
        model=state.model,
        provider=state.provider,
        provider_key_present=state.provider_key_present,
        pending_reviews=state.pending_reviews,
        best_score=state.best_score,
        agentlab_version=state.agentlab_version,
        session_title=state.session_title,
        tokens_used=state.tokens_used,
        context_limit=state.context_limit,
    )


def select_footer(state: AppState) -> FooterSlice:
    """Extract input footer fields from the full state."""
    return FooterSlice(
        permission_mode=state.permission_mode,
        active_shells=state.active_shells,
        active_tasks=state.active_tasks,
        coordinator_status=state.coordinator_status,
    )


def select_messages(state: AppState) -> tuple[TranscriptEntry, ...]:
    """Extract the message list from state.

    Returns the tuple directly — since ``AppState`` is frozen the tuple
    reference only changes when messages are actually appended, giving
    widgets a cheap identity check to skip re-renders.
    """
    return state.messages


# ---------------------------------------------------------------------------
# State update helpers — common mutations wrapped as updater functions
# ---------------------------------------------------------------------------


def append_message(
    role: TranscriptRole,
    content: str,
    *,
    event_name: str | None = None,
    data: Mapping[str, Any] | None = None,
) -> Updater[AppState]:
    """Return an updater that appends a transcript entry."""
    entry = TranscriptEntry(
        role=role,
        content=content,
        event_name=event_name,
        data=data,
    )

    def _update(state: AppState) -> AppState:
        return replace(state, messages=state.messages + (entry,))

    return _update


def set_streaming_content(content: str | None) -> Updater[AppState]:
    """Return an updater that sets the streaming content buffer."""
    def _update(state: AppState) -> AppState:
        return replace(state, streaming_content=content)
    return _update


def set_coordinator_status(status: CoordinatorStatus) -> Updater[AppState]:
    """Return an updater that sets the coordinator lifecycle phase."""
    def _update(state: AppState) -> AppState:
        return replace(state, coordinator_status=status)
    return _update


def update_worker(worker_id: str, **fields: Any) -> Updater[AppState]:
    """Return an updater that patches a single worker's state.

    If the worker doesn't exist yet, it's created with the given fields.
    """
    def _update(state: AppState) -> AppState:
        workers = list(state.coordinator_workers)
        for i, w in enumerate(workers):
            if w.worker_id == worker_id:
                workers[i] = replace(w, **fields)
                return replace(state, coordinator_workers=tuple(workers))
        # New worker
        workers.append(WorkerState(worker_id=worker_id, **fields))
        return replace(state, coordinator_workers=tuple(workers))
    return _update


def clear_coordinator(
) -> Updater[AppState]:
    """Return an updater that resets coordinator state to idle."""
    def _update(state: AppState) -> AppState:
        return replace(
            state,
            coordinator_status=CoordinatorStatus.IDLE,
            coordinator_workers=(),
            coordinator_session_id=None,
            coordinator_task_id=None,
            effort=None,
        )
    return _update
