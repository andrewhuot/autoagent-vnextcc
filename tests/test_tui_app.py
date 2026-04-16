"""Textual pilot tests for the TUI workbench app (Phase 1).

Covers:
- Widget tree structure: all expected widgets are mounted
- Welcome card renders version and cwd
- Message list updates when store receives messages
- Status footer renders workspace and mode info
- Input area handles submit and exit
- Streaming indicator appears/disappears with streaming content
"""

from __future__ import annotations

import os
from dataclasses import replace

import pytest

from cli.workbench_app.store import (
    AppState,
    CoordinatorStatus,
    Store,
    append_message,
    get_default_app_state,
    set_streaming_content,
)
from cli.workbench_app.tui.app import WorkbenchTUIApp
from cli.workbench_app.tui.widgets.input_area import InputArea
from cli.workbench_app.tui.widgets.message_list import MessageList, StreamingIndicator
from cli.workbench_app.tui.widgets.message_widget import MessageWidget
from cli.workbench_app.tui.widgets.status_footer import StatusFooter
from cli.workbench_app.tui.widgets.welcome_card import WelcomeCard


def _make_app(state: AppState | None = None) -> WorkbenchTUIApp:
    """Create a test app with an optional pre-populated store."""
    s = state or get_default_app_state()
    store = Store(s)
    return WorkbenchTUIApp(store=store)


# ---------------------------------------------------------------------------
# Widget tree structure
# ---------------------------------------------------------------------------


class TestWidgetTree:
    """Verify the expected widget hierarchy is mounted."""

    @pytest.mark.asyncio
    async def test_all_widgets_present(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            assert app.query_one(WelcomeCard) is not None
            assert app.query_one(MessageList) is not None
            assert app.query_one(StatusFooter) is not None
            assert app.query_one(InputArea) is not None


# ---------------------------------------------------------------------------
# Welcome card
# ---------------------------------------------------------------------------


class TestWelcomeCard:
    """Welcome card renders version and cwd."""

    @pytest.mark.asyncio
    async def test_version_displayed(self) -> None:
        state = replace(get_default_app_state(), agentlab_version="1.2.3")
        app = _make_app(state)
        async with app.run_test():
            card = app.query_one(WelcomeCard)
            text = card.query("Static").first().renderable
            assert "1.2.3" in str(text)

    @pytest.mark.asyncio
    async def test_cwd_displayed(self) -> None:
        app = _make_app()
        async with app.run_test():
            card = app.query_one(WelcomeCard)
            # At least one Static should contain the cwd.
            statics = [str(s.renderable) for s in card.query("Static")]
            cwd = os.getcwd()
            assert any(cwd in text for text in statics)


# ---------------------------------------------------------------------------
# Message list
# ---------------------------------------------------------------------------


class TestMessageList:
    """Message list updates reactively from store."""

    @pytest.mark.asyncio
    async def test_empty_initially(self) -> None:
        app = _make_app()
        async with app.run_test():
            msg_list = app.query_one(MessageList)
            widgets = msg_list.query(MessageWidget)
            assert len(widgets) == 0

    @pytest.mark.asyncio
    async def test_messages_appear_on_store_update(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            app.store.set_state(append_message("user", "hello"))
            await pilot.pause()

            widgets = app.query_one(MessageList).query(MessageWidget)
            assert len(widgets) == 1
            assert widgets[0].entry.content == "hello"
            assert widgets[0].entry.role == "user"

    @pytest.mark.asyncio
    async def test_multiple_messages_append(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            app.store.set_state(append_message("user", "msg1"))
            app.store.set_state(append_message("assistant", "msg2"))
            app.store.set_state(append_message("error", "msg3"))
            await pilot.pause()

            widgets = app.query_one(MessageList).query(MessageWidget)
            assert len(widgets) == 3
            assert widgets[0].entry.role == "user"
            assert widgets[1].entry.role == "assistant"
            assert widgets[2].entry.role == "error"

    @pytest.mark.asyncio
    async def test_message_css_classes(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            app.store.set_state(append_message("user", "test"))
            await pilot.pause()

            widget = app.query_one(MessageList).query(MessageWidget).first()
            assert "role-user" in widget.classes

    @pytest.mark.asyncio
    async def test_streaming_indicator_appears(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            app.store.set_state(set_streaming_content("partial output"))
            await pilot.pause()

            indicators = app.query_one(MessageList).query(StreamingIndicator)
            assert len(indicators) == 1

    @pytest.mark.asyncio
    async def test_streaming_indicator_disappears(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            app.store.set_state(set_streaming_content("partial"))
            await pilot.pause()
            assert len(app.query_one(MessageList).query(StreamingIndicator)) == 1

            app.store.set_state(set_streaming_content(None))
            await pilot.pause()
            assert len(app.query_one(MessageList).query(StreamingIndicator)) == 0


# ---------------------------------------------------------------------------
# Status footer
# ---------------------------------------------------------------------------


class TestStatusFooter:
    """Status footer renders workspace and mode info."""

    @pytest.mark.asyncio
    async def test_workspace_label(self) -> None:
        state = replace(get_default_app_state(), workspace_label="my-agent")
        app = _make_app(state)
        async with app.run_test():
            footer = app.query_one(StatusFooter)
            statics = [str(s.renderable) for s in footer.query("Static")]
            assert any("my-agent" in t for t in statics)

    @pytest.mark.asyncio
    async def test_permission_mode(self) -> None:
        state = replace(get_default_app_state(), permission_mode="plan")
        app = _make_app(state)
        async with app.run_test():
            footer = app.query_one(StatusFooter)
            statics = [str(s.renderable) for s in footer.query("Static")]
            assert any("plan" in t for t in statics)

    @pytest.mark.asyncio
    async def test_reactive_update(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            app.store.set_state(lambda s: replace(s, workspace_label="updated"))
            await pilot.pause()

            footer = app.query_one(StatusFooter)
            statics = [str(s.renderable) for s in footer.query("Static")]
            assert any("updated" in t for t in statics)


# ---------------------------------------------------------------------------
# Input area
# ---------------------------------------------------------------------------


class TestInputArea:
    """Input area handles submission."""

    @pytest.mark.asyncio
    async def test_input_submit_adds_message(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            input_widget = app.query_one(InputArea).query_one("Input")
            input_widget.value = "hello world"
            await pilot.press("enter")
            await pilot.pause()

            msgs = app.store.get_state().messages
            assert len(msgs) == 1
            assert msgs[0].content == "hello world"
            assert msgs[0].role == "user"

    @pytest.mark.asyncio
    async def test_input_clears_after_submit(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            input_widget = app.query_one(InputArea).query_one("Input")
            input_widget.value = "some text"
            await pilot.press("enter")
            await pilot.pause()

            assert input_widget.value == ""

    @pytest.mark.asyncio
    async def test_empty_input_ignored(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()

            assert len(app.store.get_state().messages) == 0

    @pytest.mark.asyncio
    async def test_exit_command(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            input_widget = app.query_one(InputArea).query_one("Input")
            input_widget.value = "/exit"
            await pilot.press("enter")
            # App should have exited — run_test context handles this.
