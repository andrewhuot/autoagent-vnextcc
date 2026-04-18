"""Tests for Phase 3: streaming, coordinator panel, and effort indicator.

Covers:
- CoordinatorPanel renders worker tree from store state
- CoordinatorPanel hides when idle
- StreamingMessage shows/hides based on streaming content
- EffortIndicatorWidget shows/hides based on coordinator status
- Full event sequence: coordinator start -> workers progress -> streaming -> complete
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from builder.events import BuilderEvent, BuilderEventType
from cli.workbench_app.store import (
    AppState,
    CoordinatorStatus,
    Store,
    WorkerPhase,
    WorkerState,
    get_default_app_state,
    set_coordinator_status,
    set_streaming_content,
    update_worker,
)
from cli.workbench_app.store_bridge import EventStoreAdapter
from cli.workbench_app.tui.app import WorkbenchTUIApp
from cli.workbench_app.tui.widgets.coordinator_panel import CoordinatorPanel
from cli.workbench_app.tui.widgets.effort_indicator_widget import EffortIndicatorWidget
from cli.workbench_app.tui.widgets.streaming_message import StreamingMessage


def _make_app(state: AppState | None = None) -> WorkbenchTUIApp:
    s = state or get_default_app_state()
    store = Store(s)
    return WorkbenchTUIApp(store=store)


def _event(
    event_type: BuilderEventType,
    *,
    session_id: str = "sess-1",
    task_id: str | None = "task-1",
    **payload_kw: object,
) -> BuilderEvent:
    return BuilderEvent(
        event_type=event_type,
        session_id=session_id,
        task_id=task_id,
        payload=dict(payload_kw),
    )


# ---------------------------------------------------------------------------
# CoordinatorPanel
# ---------------------------------------------------------------------------


class TestCoordinatorPanel:
    """Coordinator panel renders worker tree."""

    @pytest.mark.asyncio
    async def test_hidden_when_idle(self) -> None:
        app = _make_app()
        async with app.run_test():
            panel = app.query_one(CoordinatorPanel)
            assert panel.display is False

    @pytest.mark.asyncio
    async def test_visible_when_running(self) -> None:
        state = replace(
            get_default_app_state(),
            coordinator_status=CoordinatorStatus.RUNNING,
            coordinator_workers=(
                WorkerState(worker_id="w1", role="BUILD_ENGINEER", phase=WorkerPhase.ACTING),
                WorkerState(worker_id="w2", role="EVAL_AUTHOR", phase=WorkerPhase.QUEUED),
            ),
        )
        app = _make_app(state)
        async with app.run_test():
            panel = app.query_one(CoordinatorPanel)
            assert panel.display is True

    @pytest.mark.asyncio
    async def test_reactive_appearance(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            panel = app.query_one(CoordinatorPanel)
            assert panel.display is False

            # Start coordinator.
            app.store.set_state(lambda s: replace(
                s,
                coordinator_status=CoordinatorStatus.RUNNING,
                coordinator_workers=(
                    WorkerState(worker_id="w1", role="BUILD_ENGINEER", phase=WorkerPhase.ACTING),
                ),
            ))
            await pilot.pause()
            assert panel.display is True

            # Stop coordinator.
            app.store.set_state(lambda s: replace(
                s,
                coordinator_status=CoordinatorStatus.IDLE,
                coordinator_workers=(),
            ))
            await pilot.pause()
            assert panel.display is False

    @pytest.mark.asyncio
    async def test_worker_phase_updates(self) -> None:
        state = replace(
            get_default_app_state(),
            coordinator_status=CoordinatorStatus.RUNNING,
            coordinator_workers=(
                WorkerState(worker_id="w1", role="BUILD_ENGINEER", phase=WorkerPhase.QUEUED),
            ),
        )
        app = _make_app(state)
        async with app.run_test() as pilot:
            # Update worker phase.
            app.store.set_state(update_worker("w1", phase=WorkerPhase.COMPLETED))
            await pilot.pause()

            # Panel should still be visible and reflect the update.
            panel = app.query_one(CoordinatorPanel)
            assert panel.display is True


# ---------------------------------------------------------------------------
# StreamingMessage
# ---------------------------------------------------------------------------


class TestStreamingMessage:
    """Streaming message widget shows/hides with content."""

    @pytest.mark.asyncio
    async def test_hidden_when_no_content(self) -> None:
        app = _make_app()
        async with app.run_test():
            sm = app.query_one(StreamingMessage)
            assert sm.display is False

    @pytest.mark.asyncio
    async def test_visible_when_streaming(self) -> None:
        state = replace(get_default_app_state(), streaming_content="Hello")
        app = _make_app(state)
        async with app.run_test():
            sm = app.query_one(StreamingMessage)
            assert sm.display is True

    @pytest.mark.asyncio
    async def test_reactive_show_hide(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            sm = app.query_one(StreamingMessage)
            assert sm.display is False

            # Start streaming.
            app.store.set_state(set_streaming_content("partial output"))
            await pilot.pause()
            assert sm.display is True

            # More content.
            app.store.set_state(set_streaming_content("partial output extended"))
            await pilot.pause()
            assert sm.display is True

            # End streaming.
            app.store.set_state(set_streaming_content(None))
            await pilot.pause()
            assert sm.display is False


# ---------------------------------------------------------------------------
# EffortIndicatorWidget
# ---------------------------------------------------------------------------


class TestEffortIndicator:
    """Effort indicator shows/hides with coordinator status."""

    @pytest.mark.asyncio
    async def test_hidden_when_idle(self) -> None:
        app = _make_app()
        async with app.run_test():
            ei = app.query_one(EffortIndicatorWidget)
            assert ei.display is False

    @pytest.mark.asyncio
    async def test_visible_when_running(self) -> None:
        state = replace(
            get_default_app_state(),
            coordinator_status=CoordinatorStatus.RUNNING,
        )
        app = _make_app(state)
        async with app.run_test() as pilot:
            ei = app.query_one(EffortIndicatorWidget)
            # May need a tick for the timer to start.
            await pilot.pause()
            assert ei.display is True

    @pytest.mark.asyncio
    async def test_hides_when_completed(self) -> None:
        state = replace(
            get_default_app_state(),
            coordinator_status=CoordinatorStatus.RUNNING,
        )
        app = _make_app(state)
        async with app.run_test() as pilot:
            await pilot.pause()

            app.store.set_state(set_coordinator_status(CoordinatorStatus.IDLE))
            await pilot.pause()

            ei = app.query_one(EffortIndicatorWidget)
            assert ei.display is False


# ---------------------------------------------------------------------------
# Full event sequence via EventStoreAdapter
# ---------------------------------------------------------------------------


class TestFullStreamingSequence:
    """End-to-end: events -> store -> widgets."""

    @pytest.mark.asyncio
    async def test_coordinator_workflow_in_tui(self) -> None:
        app = _make_app()
        adapter = EventStoreAdapter(app.store)

        async with app.run_test() as pilot:
            panel = app.query_one(CoordinatorPanel)
            sm = app.query_one(StreamingMessage)

            # Initially hidden.
            assert panel.display is False
            assert sm.display is False

            # 1. Coordinator starts.
            adapter.handle_event(_event(
                BuilderEventType.COORDINATOR_EXECUTION_STARTED,
                worker_roster=[
                    {"worker_id": "w1", "role": "BUILD_ENGINEER"},
                    {"worker_id": "w2", "role": "EVAL_AUTHOR"},
                ],
            ))
            await pilot.pause()
            assert panel.display is True
            assert app.store.get_state().coordinator_status == CoordinatorStatus.RUNNING

            # 2. Worker progresses.
            adapter.handle_event(_event(
                BuilderEventType.WORKER_ACTING,
                worker_id="w1",
                worker_role="BUILD_ENGINEER",
                note="editing config",
            ))
            await pilot.pause()

            # 3. Streaming begins.
            adapter.handle_event(_event(
                BuilderEventType.MESSAGE_DELTA,
                delta="Here is the ",
            ))
            adapter.handle_event(_event(
                BuilderEventType.MESSAGE_DELTA,
                delta="result.",
            ))
            await pilot.pause()
            assert sm.display is True
            assert app.store.get_state().streaming_content == "Here is the result."

            # 4. Workers complete.
            adapter.handle_event(_event(
                BuilderEventType.WORKER_COMPLETED,
                worker_id="w1",
                worker_role="BUILD_ENGINEER",
            ))
            adapter.handle_event(_event(
                BuilderEventType.WORKER_COMPLETED,
                worker_id="w2",
                worker_role="EVAL_AUTHOR",
            ))
            await pilot.pause()

            # 5. Coordinator completes, leaving recent work visible.
            adapter.handle_event(_event(
                BuilderEventType.COORDINATOR_EXECUTION_COMPLETED,
            ))
            await pilot.pause()
            assert app.store.get_state().coordinator_status == CoordinatorStatus.IDLE
            assert panel.display is True
            assert "finished recently" in str(panel.renderable)


# ---------------------------------------------------------------------------
# Widget tree includes Phase 3 widgets
# ---------------------------------------------------------------------------


class TestPhase3WidgetTree:
    """All Phase 3 widgets are mounted in the app."""

    @pytest.mark.asyncio
    async def test_all_phase3_widgets_present(self) -> None:
        app = _make_app()
        async with app.run_test():
            assert app.query_one(CoordinatorPanel) is not None
            assert app.query_one(StreamingMessage) is not None
            assert app.query_one(EffortIndicatorWidget) is not None
