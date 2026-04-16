"""Tests for TUI slash command dispatch and key bindings (Phase 2).

Covers:
- TUISlashAdapter routes slash commands through existing dispatch
- Input routing: SLASH, CHAT, EXIT, SHORTCUTS
- Mode cycling via shift+tab
- Double-interrupt exit semantics
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from cli.workbench_app.commands import CommandRegistry, LocalCommand
from cli.workbench_app.input_router import InputKind
from cli.workbench_app.store import (
    AppState,
    Store,
    append_message,
    get_default_app_state,
)
from cli.workbench_app.tui.app import WorkbenchTUIApp
from cli.workbench_app.tui.slash_adapter import TUISlashAdapter
from cli.workbench_app.tui.widgets.input_area import InputArea
from cli.workbench_app.tui.widgets.message_list import MessageList
from cli.workbench_app.tui.widgets.message_widget import MessageWidget


def _test_handler(ctx, *args):
    """Simple handler that returns a string."""
    return "test output: " + " ".join(args) if args else "test output"


def _make_registry() -> CommandRegistry:
    """Build a minimal command registry for testing."""
    registry = CommandRegistry()
    registry.register(LocalCommand(
        name="test",
        description="A test command",
        handler=_test_handler,
    ))
    registry.register(LocalCommand(
        name="echo",
        description="Echo arguments",
        handler=lambda ctx, *args: "echo: " + " ".join(args),
    ))
    return registry


def _make_app_with_adapter(
    state: AppState | None = None,
) -> WorkbenchTUIApp:
    """Create a test app with a slash adapter and test registry."""
    s = state or get_default_app_state()
    store = Store(s)
    registry = _make_registry()
    adapter = TUISlashAdapter(store, registry=registry)
    return WorkbenchTUIApp(store=store, slash_adapter=adapter)


# ---------------------------------------------------------------------------
# TUISlashAdapter unit tests
# ---------------------------------------------------------------------------


class TestSlashAdapterRouting:
    """TUISlashAdapter routes input correctly."""

    def test_slash_command_dispatches(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        registry = _make_registry()
        adapter = TUISlashAdapter(store, registry=registry)

        route = adapter.handle_input("/test")
        assert route.kind == InputKind.SLASH

        # Should have user echo + handler output in messages
        msgs = store.get_state().messages
        assert len(msgs) >= 2
        assert msgs[0].role == "user"
        assert msgs[0].content == "/test"

    def test_slash_with_args(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        registry = _make_registry()
        adapter = TUISlashAdapter(store, registry=registry)

        adapter.handle_input("/echo hello world")
        msgs = store.get_state().messages
        # Should contain the echo output
        assert any("echo: hello world" in m.content for m in msgs)

    def test_exit_command(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        adapter = TUISlashAdapter(store)

        route = adapter.handle_input("/exit")
        assert route.kind == InputKind.EXIT

    def test_shortcuts_command(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        adapter = TUISlashAdapter(store)

        route = adapter.handle_input("?")
        assert route.kind == InputKind.SHORTCUTS
        # Should have added a system message with help text
        msgs = store.get_state().messages
        assert len(msgs) >= 1
        assert msgs[0].role == "system"

    def test_chat_without_model(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        adapter = TUISlashAdapter(store)

        route = adapter.handle_input("hello there")
        assert route.kind == InputKind.CHAT
        msgs = store.get_state().messages
        assert msgs[0].role == "user"
        assert msgs[0].content == "hello there"

    def test_empty_input(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        adapter = TUISlashAdapter(store)

        route = adapter.handle_input("")
        assert route.kind == InputKind.EMPTY
        assert len(store.get_state().messages) == 0

    def test_shell_command_echoes_and_warns_without_app(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        adapter = TUISlashAdapter(store)

        route = adapter.handle_input("!ls")
        assert route.kind == InputKind.SHELL
        msgs = store.get_state().messages
        assert len(msgs) >= 2
        # First message is the user echo, second is warning (no app ref).
        assert msgs[0].role == "user"
        assert msgs[1].role == "warning"

    def test_unknown_slash_command(self) -> None:
        store: Store[AppState] = Store(get_default_app_state())
        registry = _make_registry()
        adapter = TUISlashAdapter(store, registry=registry)

        adapter.handle_input("/nonexistent")
        msgs = store.get_state().messages
        # Should contain unknown command message
        assert any("Unknown command" in m.content for m in msgs)


# ---------------------------------------------------------------------------
# TUI pilot tests — input area with adapter
# ---------------------------------------------------------------------------


class TestInputAreaWithAdapter:
    """Input area routes through slash adapter."""

    @pytest.mark.asyncio
    async def test_slash_command_in_tui(self) -> None:
        app = _make_app_with_adapter()
        async with app.run_test() as pilot:
            input_widget = app.query_one(InputArea).query_one("Input")
            input_widget.value = "/test"
            await pilot.press("enter")
            await pilot.pause()

            msgs = app.store.get_state().messages
            assert any("/test" in m.content for m in msgs)

    @pytest.mark.asyncio
    async def test_exit_via_adapter(self) -> None:
        app = _make_app_with_adapter()
        async with app.run_test() as pilot:
            input_widget = app.query_one(InputArea).query_one("Input")
            input_widget.value = "/exit"
            await pilot.press("enter")
            # App should have exited


# ---------------------------------------------------------------------------
# Key bindings
# ---------------------------------------------------------------------------


class TestKeyBindings:
    """Key bindings work correctly."""

    @pytest.mark.asyncio
    async def test_mode_cycling(self) -> None:
        state = replace(get_default_app_state(), permission_mode="default")
        store = Store(state)
        app = WorkbenchTUIApp(store=store)

        async with app.run_test() as pilot:
            # Initial mode
            assert app.store.get_state().permission_mode == "default"

            # Cycle to next
            await app.run_action("cycle_mode")
            await pilot.pause()
            assert app.store.get_state().permission_mode == "acceptEdits"

            # Cycle again
            await app.run_action("cycle_mode")
            await pilot.pause()
            assert app.store.get_state().permission_mode == "plan"

            # Cycle again
            await app.run_action("cycle_mode")
            await pilot.pause()
            assert app.store.get_state().permission_mode == "bypass"

            # Wraps around
            await app.run_action("cycle_mode")
            await pilot.pause()
            assert app.store.get_state().permission_mode == "default"

    @pytest.mark.asyncio
    async def test_single_interrupt_warns(self) -> None:
        app = _make_app_with_adapter()
        async with app.run_test() as pilot:
            await app.run_action("interrupt")
            await pilot.pause()

            msgs = app.store.get_state().messages
            assert any("ctrl+c" in m.content for m in msgs)
