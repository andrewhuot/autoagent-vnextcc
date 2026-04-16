"""Tests for the centralized state store (cli.workbench_app.store).

Covers:
- Store[T] subscribe / set_state / unsubscribe / identity-skip semantics
- AppState defaults and immutability
- Selector functions (select_status_bar, select_footer, select_messages)
- State updater helpers (append_message, set_coordinator_status, etc.)
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from cli.workbench_app.store import (
    AppState,
    CoordinatorStatus,
    FooterSlice,
    StatusBarSlice,
    Store,
    WorkerPhase,
    WorkerState,
    append_message,
    clear_coordinator,
    get_default_app_state,
    select_footer,
    select_messages,
    select_status_bar,
    set_coordinator_status,
    set_streaming_content,
    update_worker,
)
from cli.workbench_app.transcript import TranscriptEntry


# ---------------------------------------------------------------------------
# Store[T] core behavior
# ---------------------------------------------------------------------------


class TestStoreBasics:
    """Core Store[T] behavior."""

    def test_initial_state(self) -> None:
        store: Store[int] = Store(42)
        assert store.get_state() == 42

    def test_set_state_updates(self) -> None:
        store: Store[int] = Store(0)
        store.set_state(lambda s: s + 1)
        assert store.get_state() == 1

    def test_set_state_notifies_subscribers(self) -> None:
        store: Store[int] = Store(0)
        calls: list[int] = []
        store.subscribe(lambda: calls.append(store.get_state()))

        store.set_state(lambda s: s + 1)
        store.set_state(lambda s: s + 10)

        assert calls == [1, 11]

    def test_set_state_skips_identity_noop(self) -> None:
        """If the updater returns the same object, no listeners fire."""
        state = AppState()
        store: Store[AppState] = Store(state)
        calls: list[bool] = []
        store.subscribe(lambda: calls.append(True))

        # Return the same object — should be a no-op.
        store.set_state(lambda s: s)

        assert calls == []
        assert store.get_state() is state

    def test_unsubscribe(self) -> None:
        store: Store[int] = Store(0)
        calls: list[int] = []
        unsub = store.subscribe(lambda: calls.append(store.get_state()))

        store.set_state(lambda s: s + 1)
        assert calls == [1]

        unsub()
        store.set_state(lambda s: s + 1)
        assert calls == [1]  # no new call

    def test_double_unsubscribe_is_safe(self) -> None:
        store: Store[int] = Store(0)
        unsub = store.subscribe(lambda: None)
        unsub()
        unsub()  # should not raise

    def test_multiple_subscribers(self) -> None:
        store: Store[int] = Store(0)
        a_calls: list[int] = []
        b_calls: list[int] = []
        store.subscribe(lambda: a_calls.append(store.get_state()))
        store.subscribe(lambda: b_calls.append(store.get_state()))

        store.set_state(lambda s: s + 1)

        assert a_calls == [1]
        assert b_calls == [1]

    def test_on_change_callback(self) -> None:
        changes: list[tuple[int, int]] = []
        store: Store[int] = Store(0, on_change=lambda prev, nxt: changes.append((prev, nxt)))

        store.set_state(lambda s: s + 5)
        store.set_state(lambda s: s + 3)

        assert changes == [(0, 5), (5, 8)]

    def test_on_change_not_called_on_identity(self) -> None:
        changes: list[tuple[int, int]] = []
        store: Store[int] = Store(0, on_change=lambda prev, nxt: changes.append((prev, nxt)))

        store.set_state(lambda s: s)  # identity

        assert changes == []


# ---------------------------------------------------------------------------
# AppState defaults
# ---------------------------------------------------------------------------


class TestAppState:
    """AppState shape and defaults."""

    def test_default_state(self) -> None:
        state = get_default_app_state()
        assert state.workspace_label is None
        assert state.model is None
        assert state.permission_mode == "default"
        assert state.active_tasks == 0
        assert state.messages == ()
        assert state.coordinator_status == CoordinatorStatus.IDLE
        assert state.coordinator_workers == ()
        assert state.streaming_content is None
        assert state.effort is None
        assert state.theme_name == "default"

    def test_state_is_frozen(self) -> None:
        state = get_default_app_state()
        with pytest.raises(AttributeError):
            state.model = "test"  # type: ignore[misc]

    def test_replace_produces_new_instance(self) -> None:
        state = get_default_app_state()
        new_state = replace(state, model="gemini-2.5")
        assert new_state.model == "gemini-2.5"
        assert state.model is None
        assert new_state is not state


# ---------------------------------------------------------------------------
# Selectors
# ---------------------------------------------------------------------------


class TestSelectors:
    """Selector functions extract the right slice."""

    def test_select_status_bar(self) -> None:
        state = replace(
            get_default_app_state(),
            workspace_label="my-agent",
            model="gemini-2.5",
            provider="google",
            pending_reviews=3,
        )
        sb = select_status_bar(state)
        assert isinstance(sb, StatusBarSlice)
        assert sb.workspace_label == "my-agent"
        assert sb.model == "gemini-2.5"
        assert sb.provider == "google"
        assert sb.pending_reviews == 3

    def test_select_footer(self) -> None:
        state = replace(
            get_default_app_state(),
            permission_mode="plan",
            active_shells=2,
            active_tasks=1,
            coordinator_status=CoordinatorStatus.RUNNING,
        )
        footer = select_footer(state)
        assert isinstance(footer, FooterSlice)
        assert footer.permission_mode == "plan"
        assert footer.active_shells == 2
        assert footer.active_tasks == 1
        assert footer.coordinator_status == CoordinatorStatus.RUNNING

    def test_select_messages_returns_tuple_reference(self) -> None:
        """Selector returns the same tuple object for identity checks."""
        msgs = (TranscriptEntry(role="user", content="hello"),)
        state = replace(get_default_app_state(), messages=msgs)
        assert select_messages(state) is msgs


# ---------------------------------------------------------------------------
# State updater helpers
# ---------------------------------------------------------------------------


class TestUpdaterHelpers:
    """Updater factory functions."""

    def test_append_message(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        store.set_state(append_message("user", "hello"))
        store.set_state(append_message("assistant", "hi there"))

        msgs = store.get_state().messages
        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert msgs[0].content == "hello"
        assert msgs[1].role == "assistant"
        assert msgs[1].content == "hi there"

    def test_append_message_with_event_data(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        store.set_state(append_message(
            "tool",
            "ran bash",
            event_name="tool.bash",
            data={"exit_code": 0},
        ))
        entry = store.get_state().messages[0]
        assert entry.event_name == "tool.bash"
        assert entry.data == {"exit_code": 0}

    def test_set_streaming_content(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        store.set_state(set_streaming_content("partial output"))
        assert store.get_state().streaming_content == "partial output"

        store.set_state(set_streaming_content(None))
        assert store.get_state().streaming_content is None

    def test_set_coordinator_status(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        store.set_state(set_coordinator_status(CoordinatorStatus.RUNNING))
        assert store.get_state().coordinator_status == CoordinatorStatus.RUNNING

    def test_update_worker_creates_new(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        store.set_state(update_worker(
            "w1",
            role="BUILD_ENGINEER",
            phase=WorkerPhase.ACTING,
        ))
        workers = store.get_state().coordinator_workers
        assert len(workers) == 1
        assert workers[0].worker_id == "w1"
        assert workers[0].role == "BUILD_ENGINEER"
        assert workers[0].phase == WorkerPhase.ACTING

    def test_update_worker_patches_existing(self) -> None:
        store: Store[AppState] = Store(replace(
            get_default_app_state(),
            coordinator_workers=(
                WorkerState(worker_id="w1", role="BUILD_ENGINEER", phase=WorkerPhase.QUEUED),
            ),
        ))
        store.set_state(update_worker("w1", phase=WorkerPhase.COMPLETED, detail="done"))
        w = store.get_state().coordinator_workers[0]
        assert w.phase == WorkerPhase.COMPLETED
        assert w.detail == "done"
        assert w.role == "BUILD_ENGINEER"  # preserved

    def test_clear_coordinator(self) -> None:
        store: Store[AppState] = Store(replace(
            get_default_app_state(),
            coordinator_status=CoordinatorStatus.RUNNING,
            coordinator_workers=(WorkerState(worker_id="w1"),),
            coordinator_session_id="sess-1",
            coordinator_task_id="task-1",
        ))
        store.set_state(clear_coordinator())
        state = store.get_state()
        assert state.coordinator_status == CoordinatorStatus.IDLE
        assert state.coordinator_workers == ()
        assert state.coordinator_session_id is None
        assert state.coordinator_task_id is None
        assert state.effort is None
