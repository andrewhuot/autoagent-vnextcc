"""Tests for the event-to-store bridge (cli.workbench_app.store_bridge).

Covers:
- EventStoreAdapter: each BuilderEventType maps to the correct AppState update
- SlashContextSync: meta dict keys sync to store fields
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from builder.events import BuilderEvent, BuilderEventType, EventBroker
from cli.workbench_app.store import (
    AppState,
    CoordinatorStatus,
    Store,
    WorkerPhase,
    get_default_app_state,
)
from cli.workbench_app.store_bridge import EventStoreAdapter, SlashContextSync


def _event(
    event_type: BuilderEventType,
    *,
    session_id: str = "sess-1",
    task_id: str | None = "task-1",
    **payload_kw: object,
) -> BuilderEvent:
    """Factory for test events with sensible defaults."""
    return BuilderEvent(
        event_type=event_type,
        session_id=session_id,
        task_id=task_id,
        payload=dict(payload_kw),
    )


# ---------------------------------------------------------------------------
# EventStoreAdapter — coordinator lifecycle
# ---------------------------------------------------------------------------


class TestCoordinatorLifecycle:
    """Coordinator start / complete / fail events."""

    def test_coordinator_started(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        adapter = EventStoreAdapter(store)

        adapter.handle_event(_event(
            BuilderEventType.COORDINATOR_EXECUTION_STARTED,
            worker_roster=[
                {"worker_id": "w1", "role": "BUILD_ENGINEER"},
                {"worker_id": "w2", "role": "EVAL_AUTHOR"},
            ],
        ))

        state = store.get_state()
        assert state.coordinator_status == CoordinatorStatus.RUNNING
        assert len(state.coordinator_workers) == 2
        assert state.coordinator_workers[0].worker_id == "w1"
        assert state.coordinator_workers[0].role == "BUILD_ENGINEER"
        assert state.coordinator_workers[0].phase == WorkerPhase.QUEUED
        assert state.coordinator_workers[1].worker_id == "w2"
        assert state.coordinator_session_id == "sess-1"
        assert state.coordinator_task_id == "task-1"

    def test_coordinator_completed(self) -> None:
        store: Store[AppState] = Store(replace(
            get_default_app_state(),
            coordinator_status=CoordinatorStatus.RUNNING,
        ))
        adapter = EventStoreAdapter(store)

        adapter.handle_event(_event(BuilderEventType.COORDINATOR_EXECUTION_COMPLETED))

        assert store.get_state().coordinator_status == CoordinatorStatus.IDLE

    def test_coordinator_synthesis_completed(self) -> None:
        store: Store[AppState] = Store(replace(
            get_default_app_state(),
            coordinator_status=CoordinatorStatus.RUNNING,
        ))
        adapter = EventStoreAdapter(store)

        adapter.handle_event(_event(BuilderEventType.COORDINATOR_SYNTHESIS_COMPLETED))

        assert store.get_state().coordinator_status == CoordinatorStatus.IDLE

    def test_coordinator_failed(self) -> None:
        store: Store[AppState] = Store(replace(
            get_default_app_state(),
            coordinator_status=CoordinatorStatus.RUNNING,
        ))
        adapter = EventStoreAdapter(store)

        adapter.handle_event(_event(
            BuilderEventType.COORDINATOR_EXECUTION_FAILED,
            error="out of tokens",
        ))

        state = store.get_state()
        assert state.coordinator_status == CoordinatorStatus.FAILED
        # Error message appended
        assert any("out of tokens" in m.content for m in state.messages)

    def test_coordinator_blocked(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        adapter = EventStoreAdapter(store)

        adapter.handle_event(_event(BuilderEventType.COORDINATOR_EXECUTION_BLOCKED))

        assert store.get_state().coordinator_status == CoordinatorStatus.FAILED


# ---------------------------------------------------------------------------
# EventStoreAdapter — worker lifecycle
# ---------------------------------------------------------------------------


class TestWorkerLifecycle:
    """Worker phase transition events."""

    def test_worker_gathering_context(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        adapter = EventStoreAdapter(store)

        adapter.handle_event(_event(
            BuilderEventType.WORKER_GATHERING_CONTEXT,
            worker_id="w1",
            worker_role="BUILD_ENGINEER",
        ))

        workers = store.get_state().coordinator_workers
        assert len(workers) == 1
        assert workers[0].phase == WorkerPhase.GATHERING_CONTEXT

    def test_worker_acting(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        adapter = EventStoreAdapter(store)

        adapter.handle_event(_event(
            BuilderEventType.WORKER_ACTING,
            worker_id="w1",
            worker_role="PROMPT_ENGINEER",
            note="editing system prompt",
        ))

        w = store.get_state().coordinator_workers[0]
        assert w.phase == WorkerPhase.ACTING
        assert w.detail == "editing system prompt"

    def test_worker_completed(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        adapter = EventStoreAdapter(store)

        adapter.handle_event(_event(
            BuilderEventType.WORKER_ACTING,
            worker_id="w1",
            worker_role="BUILD_ENGINEER",
        ))
        adapter.handle_event(_event(
            BuilderEventType.WORKER_COMPLETED,
            worker_id="w1",
            worker_role="BUILD_ENGINEER",
        ))

        w = store.get_state().coordinator_workers[0]
        assert w.phase == WorkerPhase.COMPLETED
        assert w.completed_at is not None
        assert w.completed_at > 0

    def test_worker_failed(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        adapter = EventStoreAdapter(store)

        adapter.handle_event(_event(
            BuilderEventType.WORKER_FAILED,
            worker_id="w1",
            worker_role="EVAL_AUTHOR",
        ))

        w = store.get_state().coordinator_workers[0]
        assert w.phase == WorkerPhase.FAILED

    def test_worker_blocked(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        adapter = EventStoreAdapter(store)

        adapter.handle_event(_event(
            BuilderEventType.WORKER_BLOCKED,
            worker_id="w1",
            worker_role="DEPLOYMENT_ENGINEER",
        ))

        w = store.get_state().coordinator_workers[0]
        assert w.phase == WorkerPhase.BLOCKED


# ---------------------------------------------------------------------------
# EventStoreAdapter — message streaming
# ---------------------------------------------------------------------------


class TestMessageStreaming:
    """MESSAGE_DELTA accumulates streaming content."""

    def test_message_delta_accumulates(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        adapter = EventStoreAdapter(store)

        adapter.handle_event(_event(BuilderEventType.MESSAGE_DELTA, delta="Hello"))
        adapter.handle_event(_event(BuilderEventType.MESSAGE_DELTA, delta=" world"))

        assert store.get_state().streaming_content == "Hello world"

    def test_empty_delta_ignored(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        adapter = EventStoreAdapter(store)

        adapter.handle_event(_event(BuilderEventType.MESSAGE_DELTA, delta=""))

        assert store.get_state().streaming_content is None

    def test_worker_message_delta(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        adapter = EventStoreAdapter(store)

        adapter.handle_event(_event(BuilderEventType.WORKER_MESSAGE_DELTA, delta="chunk"))

        assert store.get_state().streaming_content == "chunk"


# ---------------------------------------------------------------------------
# EventStoreAdapter — task lifecycle
# ---------------------------------------------------------------------------


class TestTaskLifecycle:
    """Task start / complete / fail events."""

    def test_task_started(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        adapter = EventStoreAdapter(store)

        adapter.handle_event(_event(BuilderEventType.TASK_STARTED))

        assert store.get_state().active_tasks == 1
        assert store.get_state().coordinator_task_id == "task-1"

    def test_task_completed_finalizes_streaming(self) -> None:
        store: Store[AppState] = Store(replace(
            get_default_app_state(),
            active_tasks=1,
            streaming_content="final output",
        ))
        adapter = EventStoreAdapter(store)

        adapter.handle_event(_event(BuilderEventType.TASK_COMPLETED))

        state = store.get_state()
        assert state.active_tasks == 0
        assert state.streaming_content is None
        # Streaming content should be finalized as a message
        assert len(state.messages) == 1
        assert state.messages[0].content == "final output"

    def test_task_completed_no_streaming(self) -> None:
        store: Store[AppState] = Store(replace(
            get_default_app_state(),
            active_tasks=1,
        ))
        adapter = EventStoreAdapter(store)

        adapter.handle_event(_event(BuilderEventType.TASK_COMPLETED))

        state = store.get_state()
        assert state.active_tasks == 0
        assert len(state.messages) == 0  # no streaming to finalize

    def test_task_failed(self) -> None:
        store: Store[AppState] = Store(replace(
            get_default_app_state(),
            active_tasks=2,
        ))
        adapter = EventStoreAdapter(store)

        adapter.handle_event(_event(
            BuilderEventType.TASK_FAILED,
            error="timeout",
        ))

        state = store.get_state()
        assert state.active_tasks == 1  # decremented
        assert any("timeout" in m.content for m in state.messages)

    def test_task_count_never_negative(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        adapter = EventStoreAdapter(store)

        adapter.handle_event(_event(BuilderEventType.TASK_COMPLETED))

        assert store.get_state().active_tasks == 0  # not -1


# ---------------------------------------------------------------------------
# EventStoreAdapter — session and LLM events
# ---------------------------------------------------------------------------


class TestSessionAndLLMEvents:
    """Session open/close, LLM fallback/retry, degraded mode."""

    def test_session_opened(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        adapter = EventStoreAdapter(store)

        adapter.handle_event(_event(
            BuilderEventType.SESSION_OPENED,
            session_id="new-sess",
        ))

        assert store.get_state().coordinator_session_id == "new-sess"

    def test_session_closed(self) -> None:
        store: Store[AppState] = Store(replace(
            get_default_app_state(),
            coordinator_status=CoordinatorStatus.RUNNING,
            coordinator_session_id="sess-1",
        ))
        adapter = EventStoreAdapter(store)

        adapter.handle_event(_event(BuilderEventType.SESSION_CLOSED))

        state = store.get_state()
        assert state.coordinator_status == CoordinatorStatus.IDLE
        assert state.coordinator_session_id is None

    def test_llm_fallback(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        adapter = EventStoreAdapter(store)

        adapter.handle_event(_event(
            BuilderEventType.LLM_FALLBACK,
            fallback_model="gemini-1.5-flash",
        ))

        assert any("gemini-1.5-flash" in m.content for m in store.get_state().messages)

    def test_llm_retry(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        adapter = EventStoreAdapter(store)

        adapter.handle_event(_event(
            BuilderEventType.LLM_RETRY,
            reason="rate limited",
        ))

        assert any("rate limited" in m.content for m in store.get_state().messages)

    def test_degraded_mode(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        adapter = EventStoreAdapter(store)

        adapter.handle_event(_event(
            BuilderEventType.COORDINATOR_WORKER_MODE_DEGRADED,
            reason="no API key",
        ))

        assert any("no API key" in m.content for m in store.get_state().messages)


# ---------------------------------------------------------------------------
# EventStoreAdapter — error resilience
# ---------------------------------------------------------------------------


class TestAdapterResilience:
    """Adapter handles malformed events gracefully."""

    def test_missing_payload_keys(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        adapter = EventStoreAdapter(store)

        # Worker event with no worker_id — should not crash
        adapter.handle_event(_event(BuilderEventType.WORKER_ACTING))

        workers = store.get_state().coordinator_workers
        assert len(workers) == 1
        assert workers[0].worker_id == ""

    def test_unknown_event_type_passes(self) -> None:
        """Events not handled by the adapter are silently ignored."""
        store: Store[AppState] = Store(get_default_app_state())
        adapter = EventStoreAdapter(store)

        # PLAN_READY, ARTIFACT_UPDATED, EVAL_* etc. are not handled yet
        adapter.handle_event(_event(BuilderEventType.PLAN_READY))
        adapter.handle_event(_event(BuilderEventType.ARTIFACT_UPDATED))
        adapter.handle_event(_event(BuilderEventType.EVAL_STARTED))
        adapter.handle_event(_event(BuilderEventType.EVAL_COMPLETED))
        adapter.handle_event(_event(BuilderEventType.APPROVAL_REQUESTED))

        # Should not crash or change state in unexpected ways
        assert store.get_state().coordinator_status == CoordinatorStatus.IDLE


# ---------------------------------------------------------------------------
# EventStoreAdapter — bind_broker
# ---------------------------------------------------------------------------


class TestBindBroker:
    """Broker binding wraps publish to also update the store."""

    def test_bind_broker(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        adapter = EventStoreAdapter(store)
        broker = EventBroker(max_events=100)

        adapter.bind_broker(broker)

        # Publishing through the broker should update the store
        broker.publish(
            BuilderEventType.TASK_STARTED,
            session_id="sess-1",
            task_id="task-1",
            payload={},
        )

        assert store.get_state().active_tasks == 1


# ---------------------------------------------------------------------------
# SlashContextSync
# ---------------------------------------------------------------------------


class TestSlashContextSync:
    """Temporary bridge from SlashContext.meta to Store."""

    def test_sync_known_keys(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        sync = SlashContextSync(store)

        sync.sync({
            "active_shells": 3,
            "active_tasks": 2,
            "builder_session_id": "sess-42",
            "latest_builder_task_id": "task-99",
        })

        state = store.get_state()
        assert state.active_shells == 3
        assert state.active_tasks == 2
        assert state.coordinator_session_id == "sess-42"
        assert state.coordinator_task_id == "task-99"

    def test_sync_unknown_keys_ignored(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        sync = SlashContextSync(store)

        sync.sync({
            "unknown_key": "value",
            "another": 42,
        })

        # State should be unchanged (identity)
        assert store.get_state() == get_default_app_state()

    def test_sync_empty_meta(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        sync = SlashContextSync(store)

        sync.sync({})

        # No crash, no state change
        assert store.get_state() == get_default_app_state()

    def test_sync_partial_keys(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        sync = SlashContextSync(store)

        sync.sync({"active_shells": 1})

        assert store.get_state().active_shells == 1
        assert store.get_state().active_tasks == 0  # untouched


# ---------------------------------------------------------------------------
# Full event sequence integration test
# ---------------------------------------------------------------------------


class TestFullEventSequence:
    """End-to-end sequence simulating a coordinator turn."""

    def test_build_workflow_sequence(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        adapter = EventStoreAdapter(store)

        # 1. Coordinator starts with 2 workers
        adapter.handle_event(_event(
            BuilderEventType.COORDINATOR_EXECUTION_STARTED,
            worker_roster=[
                {"worker_id": "w1", "role": "BUILD_ENGINEER"},
                {"worker_id": "w2", "role": "EVAL_AUTHOR"},
            ],
        ))
        assert store.get_state().coordinator_status == CoordinatorStatus.RUNNING
        assert len(store.get_state().coordinator_workers) == 2

        # 2. Worker 1 starts gathering context
        adapter.handle_event(_event(
            BuilderEventType.WORKER_GATHERING_CONTEXT,
            worker_id="w1",
            worker_role="BUILD_ENGINEER",
        ))
        assert store.get_state().coordinator_workers[0].phase == WorkerPhase.GATHERING_CONTEXT

        # 3. Worker 1 starts acting
        adapter.handle_event(_event(
            BuilderEventType.WORKER_ACTING,
            worker_id="w1",
            worker_role="BUILD_ENGINEER",
            note="editing agent config",
        ))
        w1 = store.get_state().coordinator_workers[0]
        assert w1.phase == WorkerPhase.ACTING
        assert w1.detail == "editing agent config"

        # 4. Worker 2 starts
        adapter.handle_event(_event(
            BuilderEventType.WORKER_GATHERING_CONTEXT,
            worker_id="w2",
            worker_role="EVAL_AUTHOR",
        ))

        # 5. Streaming output
        adapter.handle_event(_event(BuilderEventType.MESSAGE_DELTA, delta="Here is "))
        adapter.handle_event(_event(BuilderEventType.MESSAGE_DELTA, delta="the result"))
        assert store.get_state().streaming_content == "Here is the result"

        # 6. Worker 1 completes
        adapter.handle_event(_event(
            BuilderEventType.WORKER_COMPLETED,
            worker_id="w1",
            worker_role="BUILD_ENGINEER",
        ))
        assert store.get_state().coordinator_workers[0].phase == WorkerPhase.COMPLETED

        # 7. Worker 2 completes
        adapter.handle_event(_event(
            BuilderEventType.WORKER_COMPLETED,
            worker_id="w2",
            worker_role="EVAL_AUTHOR",
        ))

        # 8. Coordinator completes
        adapter.handle_event(_event(BuilderEventType.COORDINATOR_EXECUTION_COMPLETED))
        assert store.get_state().coordinator_status == CoordinatorStatus.IDLE
