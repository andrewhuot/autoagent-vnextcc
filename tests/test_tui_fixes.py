"""Tests for TUI fixes: markdown rendering, shell commands, background panel, chat routing.

Covers:
- Issue 1: MessageWidget renders Markdown instead of Static
- Issue 2: Shell commands execute via app.suspend() or show fallback warning
- Issue 3: Background task panel wired to registry and store
- Issue 4: Chat input routes through LLM orchestrator when available
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from cli.tools.base import PermissionDecision, ToolResult
from cli.tools.executor import ToolExecution
from cli.workbench_app.background_panel import (
    BackgroundTask,
    BackgroundTaskRegistry,
    TaskStatus,
)
from cli.workbench_app.input_router import InputKind
from cli.workbench_app.store import (
    AppState,
    Store,
    append_message,
    get_default_app_state,
    set_background_tasks,
)
from cli.workbench_app.tui.app import WorkbenchTUIApp
from cli.workbench_app.tui.slash_adapter import TUISlashAdapter
from cli.workbench_app.tui.widgets.message_widget import MessageWidget
from cli.workbench_app.tui.widgets.structured_diff import StructuredDiff
from cli.workbench_app.transcript import TranscriptEntry
from cli.tools.rendering import StructuredDiffRenderable


# ---------------------------------------------------------------------------
# Issue 1: MessageWidget renders Markdown
# ---------------------------------------------------------------------------


class TestMessageWidgetMarkdown:
    """Verify MessageWidget uses Markdown rendering instead of Static."""

    def test_message_widget_is_widget_not_static(self) -> None:
        """MessageWidget should extend Widget, not Static."""
        from textual.widget import Widget
        from textual.widgets import Static

        entry = TranscriptEntry(role="assistant", content="**bold** text")
        widget = MessageWidget(entry)
        assert isinstance(widget, Widget)
        # Should not be a direct Static instance (Markdown extends Widget).
        assert type(widget).__name__ == "MessageWidget"

    def test_message_widget_stores_entry(self) -> None:
        entry = TranscriptEntry(role="user", content="hello")
        widget = MessageWidget(entry)
        assert widget.entry is entry

    def test_message_widget_applies_role_css_class(self) -> None:
        entry = TranscriptEntry(role="error", content="oops")
        widget = MessageWidget(entry)
        assert "role-error" in widget.classes

    def test_message_widget_applies_user_css_class(self) -> None:
        entry = TranscriptEntry(role="user", content="hi")
        widget = MessageWidget(entry)
        assert "role-user" in widget.classes

    @pytest.mark.asyncio
    async def test_message_widget_composes_markdown(self) -> None:
        """When mounted, MessageWidget should contain a Markdown child."""
        from textual.widgets import Markdown

        store = Store(get_default_app_state())
        app = WorkbenchTUIApp(store=store)
        async with app.run_test() as pilot:
            # Add a message with markdown formatting.
            store.set_state(append_message("assistant", "**bold** and `code`"))
            await pilot.pause()

            # Find the MessageWidget that was mounted.
            from cli.workbench_app.tui.widgets.message_list import MessageList
            widgets = list(app.query_one(MessageList).query(MessageWidget))
            assert len(widgets) >= 1
            msg_widget = widgets[-1]

            # It should have a Markdown child.
            md_children = list(msg_widget.query(Markdown))
            assert len(md_children) >= 1

    @pytest.mark.asyncio
    async def test_message_widget_mounts_structured_diff_for_renderable_data(self) -> None:
        store = Store(get_default_app_state())
        app = WorkbenchTUIApp(store=store)
        renderable = StructuredDiffRenderable(
            old="hello\n",
            new="world\n",
            file_path="demo.py",
            language="python",
        )
        async with app.run_test() as pilot:
            store.set_state(
                append_message(
                    "tool",
                    "--- a/demo.py\n+++ b/demo.py\n-hello\n+world\n",
                    data={"renderable": renderable.to_payload()},
                )
            )
            await pilot.pause()

            from cli.workbench_app.tui.widgets.message_list import MessageList

            widgets = list(app.query_one(MessageList).query(MessageWidget))
            assert len(widgets) >= 1
            msg_widget = widgets[-1]
            assert msg_widget.query_one(StructuredDiff) is not None


# ---------------------------------------------------------------------------
# Issue 2: Shell command execution
# ---------------------------------------------------------------------------


class TestShellCommandExecution:
    """Verify shell commands route through app.suspend() or show fallback."""

    def test_shell_without_app_shows_warning(self) -> None:
        """No app reference → falls back to warning message."""
        store: Store[AppState] = Store(get_default_app_state())
        adapter = TUISlashAdapter(store)

        route = adapter.handle_input("!ls -la")
        assert route.kind == InputKind.SHELL
        msgs = store.get_state().messages
        # User echo + warning.
        assert msgs[0].role == "user"
        assert msgs[1].role == "warning"
        assert "terminal" in msgs[1].content.lower()

    def test_shell_echoes_user_message(self) -> None:
        """Shell commands should echo the user input first."""
        store: Store[AppState] = Store(get_default_app_state())
        adapter = TUISlashAdapter(store)

        adapter.handle_input("!echo hello")
        msgs = store.get_state().messages
        assert msgs[0].role == "user"
        assert msgs[0].content == "!echo hello"

    def test_shell_with_mock_app_suspend(self) -> None:
        """With an app that supports suspend, shell should execute."""
        store: Store[AppState] = Store(get_default_app_state())
        mock_app = MagicMock()

        # Make suspend() a context manager that yields.
        from contextlib import contextmanager

        @contextmanager
        def mock_suspend():
            yield

        mock_app.suspend = mock_suspend

        adapter = TUISlashAdapter(store, app=mock_app)

        with patch("cli.workbench_app.shell_mode.run_shell_turn") as mock_run:
            mock_run.return_value = MagicMock()
            # Patch input() so it doesn't block.
            with patch("builtins.input", return_value=""):
                adapter.handle_input("!echo test")

        msgs = store.get_state().messages
        assert msgs[0].role == "user"
        # No warning — command was executed.
        assert not any(m.role == "warning" for m in msgs)


# ---------------------------------------------------------------------------
# Issue 3: Background task panel wiring
# ---------------------------------------------------------------------------


class TestBackgroundPanelWiring:
    """Verify background task registry syncs to the store."""

    def test_registry_on_change_callback_fires_on_register(self) -> None:
        """Registering a task fires the on_change callback."""
        calls: list[bool] = []
        registry = BackgroundTaskRegistry()
        registry.set_on_change(lambda: calls.append(True))

        registry.register("test task", owner="user")
        assert len(calls) == 1

    def test_registry_on_change_callback_fires_on_update(self) -> None:
        registry = BackgroundTaskRegistry()
        task = registry.register("test task")

        calls: list[bool] = []
        registry.set_on_change(lambda: calls.append(True))
        registry.update(task.task_id, status=TaskStatus.RUNNING)
        assert len(calls) == 1

    def test_registry_on_change_callback_fires_on_clear(self) -> None:
        registry = BackgroundTaskRegistry()
        task = registry.register("test task")
        task.touch(status=TaskStatus.COMPLETED)

        calls: list[bool] = []
        registry.set_on_change(lambda: calls.append(True))
        registry.clear()
        assert len(calls) == 1

    def test_registry_clear_no_change_callback_when_nothing_removed(self) -> None:
        registry = BackgroundTaskRegistry()
        calls: list[bool] = []
        registry.set_on_change(lambda: calls.append(True))
        registry.clear()
        assert len(calls) == 0

    def test_set_background_tasks_updater(self) -> None:
        """set_background_tasks should replace the background_tasks tuple."""
        store = Store(get_default_app_state())
        task = BackgroundTask(
            task_id="bg-1",
            description="test",
            status=TaskStatus.RUNNING,
        )
        store.set_state(set_background_tasks((task,)))
        assert len(store.get_state().background_tasks) == 1
        assert store.get_state().background_tasks[0].task_id == "bg-1"

    def test_registry_syncs_to_store_via_on_change(self) -> None:
        """End-to-end: registry mutation → on_change → store update."""
        store = Store(get_default_app_state())
        registry = BackgroundTaskRegistry()

        def sync() -> None:
            snapshot = tuple(registry.list())
            store.set_state(set_background_tasks(snapshot))

        registry.set_on_change(sync)

        task = registry.register("my task", owner="user")
        assert len(store.get_state().background_tasks) == 1

        registry.update(task.task_id, status=TaskStatus.RUNNING, detail="working...")
        tasks = store.get_state().background_tasks
        assert tasks[0].status == TaskStatus.RUNNING

    def test_background_command_without_orchestrator(self) -> None:
        """&command without orchestrator shows helpful message."""
        store = Store(get_default_app_state())
        adapter = TUISlashAdapter(store)

        route = adapter.handle_input("&summarize docs")
        assert route.kind == InputKind.BACKGROUND
        msgs = store.get_state().messages
        assert msgs[0].role == "user"
        assert any("requires a configured model" in m.content for m in msgs)

    def test_background_command_with_orchestrator_starts_task(self) -> None:
        """&command with orchestrator registers a background task."""
        store = Store(get_default_app_state())
        registry = BackgroundTaskRegistry()

        # Wire registry → store.
        def sync() -> None:
            snapshot = tuple(registry.list())
            store.set_state(set_background_tasks(snapshot))

        registry.set_on_change(sync)

        # Mock orchestrator so run_turn is fast.
        mock_orchestrator = MagicMock()
        mock_orchestrator.run_turn = MagicMock(return_value=MagicMock(
            assistant_text="done",
            stop_reason="end_turn",
        ))
        mock_orchestrator.echo = print

        adapter = TUISlashAdapter(
            store,
            orchestrator=mock_orchestrator,
            background_registry=registry,
        )

        route = adapter.handle_input("&summarize docs")
        assert route.kind == InputKind.BACKGROUND

        # Give the background thread time to start and finish.
        time.sleep(0.5)

        msgs = store.get_state().messages
        assert msgs[0].role == "user"
        # Should have registered a task.
        assert any("Background task" in m.content and "started" in m.content for m in msgs)

        # Registry should have the task.
        tasks = registry.list()
        assert len(tasks) >= 1


# ---------------------------------------------------------------------------
# Issue 4: Chat orchestrator routing
# ---------------------------------------------------------------------------


class TestChatOrchestratorRouting:
    """Verify plain text routes to the LLM orchestrator when available."""

    def test_chat_without_orchestrator_shows_meta_message(self) -> None:
        """No orchestrator → shows 'requires a configured model' message."""
        store = Store(get_default_app_state())
        adapter = TUISlashAdapter(store)

        route = adapter.handle_input("hello world")
        assert route.kind == InputKind.CHAT
        msgs = store.get_state().messages
        assert msgs[0].role == "user"
        assert msgs[0].content == "hello world"
        assert any("configured model" in m.content for m in msgs)

    def test_chat_with_orchestrator_calls_run_turn(self) -> None:
        """With orchestrator, plain text triggers run_turn in background."""
        store = Store(get_default_app_state())

        @dataclass
        class FakeResult:
            assistant_text: str = "I'm an AI assistant."
            stop_reason: str = "end_turn"
            tool_executions: list = None

            def __post_init__(self):
                if self.tool_executions is None:
                    self.tool_executions = []

        mock_orchestrator = MagicMock()
        mock_orchestrator.echo = print
        mock_orchestrator.run_turn = MagicMock(return_value=FakeResult())

        adapter = TUISlashAdapter(store, orchestrator=mock_orchestrator)

        route = adapter.handle_input("hello world")
        assert route.kind == InputKind.CHAT

        # Give the background thread time to execute.
        time.sleep(0.5)

        # Verify run_turn was called.
        mock_orchestrator.run_turn.assert_called_once_with("hello world")

        # Verify assistant response was appended.
        msgs = store.get_state().messages
        assert msgs[0].role == "user"
        assert any(m.role == "assistant" and "AI assistant" in m.content for m in msgs)

    def test_chat_with_orchestrator_appends_tool_display_messages(self) -> None:
        """Tool displays should surface as transcript entries with renderables."""
        store = Store(get_default_app_state())

        renderable = StructuredDiffRenderable(
            old="before\n",
            new="after\n",
            file_path="demo.py",
            language="python",
        )

        @dataclass
        class FakeResult:
            assistant_text: str = "done"
            stop_reason: str = "end_turn"
            tool_executions: list = None

            def __post_init__(self):
                if self.tool_executions is None:
                    self.tool_executions = [
                        ToolExecution(
                            tool_name="FileEdit",
                            decision=PermissionDecision.ALLOW,
                            result=ToolResult(
                                ok=True,
                                content="ok",
                                display="--- a/demo.py\n+++ b/demo.py\n-before\n+after\n",
                                metadata={"renderable": renderable.to_payload()},
                            ),
                        )
                    ]

        mock_orchestrator = MagicMock()
        mock_orchestrator.echo = print
        mock_orchestrator.run_turn = MagicMock(return_value=FakeResult())

        adapter = TUISlashAdapter(store, orchestrator=mock_orchestrator)
        adapter.handle_input("hello world")
        time.sleep(0.5)

        tool_messages = [message for message in store.get_state().messages if message.role == "tool"]
        assert len(tool_messages) == 1
        assert tool_messages[0].data is not None
        assert tool_messages[0].data["renderable"]["kind"] == "structured_diff"
        assert tool_messages[0].data["tool_name"] == "FileEdit"

    def test_chat_with_orchestrator_threads_adapter_cancellation_token(self) -> None:
        """The TUI adapter should expose its shared cancel token during a turn."""
        store = Store(get_default_app_state())
        observed: dict[str, object] = {}
        done = threading.Event()

        @dataclass
        class FakeResult:
            assistant_text: str = "done"
            stop_reason: str = "end_turn"
            tool_executions: list = None

            def __post_init__(self):
                if self.tool_executions is None:
                    self.tool_executions = []

        mock_orchestrator = MagicMock()
        mock_orchestrator.echo = print
        mock_orchestrator.tool_cancellation = object()

        def _run_turn(_prompt: str) -> FakeResult:
            observed["during"] = mock_orchestrator.tool_cancellation
            done.set()
            return FakeResult()

        mock_orchestrator.run_turn = _run_turn

        adapter = TUISlashAdapter(store, orchestrator=mock_orchestrator)
        prior = mock_orchestrator.tool_cancellation

        adapter.handle_input("hello world")
        assert done.wait(timeout=1)

        assert observed["during"] is adapter.context.cancellation
        assert mock_orchestrator.tool_cancellation is prior

    def test_chat_resets_adapter_cancellation_between_turns(self) -> None:
        """A cancelled TUI turn must not poison the next orchestrator-backed turn."""
        store = Store(get_default_app_state())
        seen: list[bool] = []
        done = threading.Event()

        @dataclass
        class FakeResult:
            assistant_text: str = "done"
            stop_reason: str = "end_turn"
            tool_executions: list = None

            def __post_init__(self):
                if self.tool_executions is None:
                    self.tool_executions = []

        mock_orchestrator = MagicMock()
        mock_orchestrator.echo = print

        def _run_turn(_prompt: str) -> FakeResult:
            token = mock_orchestrator.tool_cancellation
            seen.append(bool(token.cancelled))
            if len(seen) == 1:
                token.cancel()
            done.set()
            return FakeResult()

        mock_orchestrator.run_turn = _run_turn

        adapter = TUISlashAdapter(store, orchestrator=mock_orchestrator)

        adapter.handle_input("first")
        assert done.wait(timeout=1)
        done.clear()
        adapter.handle_input("second")
        assert done.wait(timeout=1)

        assert seen == [False, False]

    def test_chat_orchestrator_failure_shows_error(self) -> None:
        """If run_turn raises, an error message appears in the transcript."""
        store = Store(get_default_app_state())

        mock_orchestrator = MagicMock()
        mock_orchestrator.echo = print
        mock_orchestrator.run_turn = MagicMock(side_effect=RuntimeError("API timeout"))

        adapter = TUISlashAdapter(store, orchestrator=mock_orchestrator)

        adapter.handle_input("test prompt")
        time.sleep(0.5)

        msgs = store.get_state().messages
        assert any(m.role == "error" and "API timeout" in m.content for m in msgs)

    def test_chat_streaming_content_clears_after_turn(self) -> None:
        """streaming_content should be None after the orchestrator turn completes."""
        store = Store(get_default_app_state())

        mock_orchestrator = MagicMock()
        mock_orchestrator.echo = print
        mock_orchestrator.run_turn = MagicMock(return_value=MagicMock(
            assistant_text="response",
            stop_reason="end_turn",
        ))

        adapter = TUISlashAdapter(store, orchestrator=mock_orchestrator)
        adapter.handle_input("hello")
        time.sleep(0.5)

        assert store.get_state().streaming_content is None

    def test_concurrent_turns_blocked(self) -> None:
        """Second chat input while first is running shows warning."""
        store = Store(get_default_app_state())

        # Orchestrator that blocks for a bit.
        slow_orchestrator = MagicMock()
        slow_orchestrator.echo = print

        def slow_turn(prompt: str):
            time.sleep(1.0)
            return MagicMock(assistant_text="done", stop_reason="end_turn")

        slow_orchestrator.run_turn = slow_turn

        adapter = TUISlashAdapter(store, orchestrator=slow_orchestrator)

        # Start first turn.
        adapter.handle_input("first")
        time.sleep(0.1)

        # Try second turn while first is running.
        adapter.handle_input("second")
        time.sleep(0.1)

        msgs = store.get_state().messages
        # Should have "already in progress" warning.
        assert any("already in progress" in m.content for m in msgs)

    def test_chat_stop_reason_non_end_turn_shows_meta(self) -> None:
        """Non-standard stop reasons should appear as meta messages."""
        store = Store(get_default_app_state())

        mock_orchestrator = MagicMock()
        mock_orchestrator.echo = print
        mock_orchestrator.run_turn = MagicMock(return_value=MagicMock(
            assistant_text="partial",
            stop_reason="max_tool_loops",
        ))

        adapter = TUISlashAdapter(store, orchestrator=mock_orchestrator)
        adapter.handle_input("test")
        time.sleep(0.5)

        msgs = store.get_state().messages
        assert any("max_tool_loops" in m.content for m in msgs)


# ---------------------------------------------------------------------------
# Integration: MessageList with Markdown widgets
# ---------------------------------------------------------------------------


class TestMessageListIntegration:
    """Verify MessageList mounts MessageWidget (Markdown-based) correctly."""

    @pytest.mark.asyncio
    async def test_multiple_messages_render_as_markdown_widgets(self) -> None:
        from cli.workbench_app.tui.widgets.message_list import MessageList

        store = Store(get_default_app_state())
        app = WorkbenchTUIApp(store=store)
        async with app.run_test() as pilot:
            store.set_state(append_message("user", "Hello **world**"))
            store.set_state(append_message("assistant", "# Heading\n\nParagraph"))
            store.set_state(append_message("error", "Something went wrong"))
            await pilot.pause()

            widgets = app.query_one(MessageList).query(MessageWidget)
            assert len(widgets) == 3
            assert "role-user" in widgets[0].classes
            assert "role-assistant" in widgets[1].classes
            assert "role-error" in widgets[2].classes
