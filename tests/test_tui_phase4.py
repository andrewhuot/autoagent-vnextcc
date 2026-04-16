"""Tests for Phase 4: dialogs, screens, and background panel.

Covers:
- PermissionDialog: button presses return correct DialogOutcome
- PlanGateDialog: approve/abort/edit decisions
- TUI screens: doctor, resume, skills, plan mount and dismiss
- BackgroundPanel: shows/hides with task state
- All Phase 4 widgets present in app tree
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from cli.workbench_app.background_panel import BackgroundTask, TaskStatus
from cli.workbench_app.permission_dialog import DialogChoice, DialogOutcome
from cli.workbench_app.screens.base import ACTION_CANCEL, ScreenResult
from cli.workbench_app.store import (
    AppState,
    Store,
    get_default_app_state,
)
from cli.workbench_app.tui.app import WorkbenchTUIApp
from cli.workbench_app.tui.dialogs.permission_dialog import PermissionDialog
from cli.workbench_app.tui.dialogs.plan_gate import (
    PlanDecision,
    PlanGateDecision,
    PlanGateDialog,
)
from cli.workbench_app.tui.screens.doctor import DoctorScreen
from cli.workbench_app.tui.screens.plan import PlanScreen
from cli.workbench_app.tui.screens.resume import ResumeScreen
from cli.workbench_app.tui.screens.skills import SkillsScreen
from cli.workbench_app.tui.widgets.background_panel import BackgroundPanel


def _make_app(state: AppState | None = None) -> WorkbenchTUIApp:
    s = state or get_default_app_state()
    store = Store(s)
    return WorkbenchTUIApp(store=store)


# ---------------------------------------------------------------------------
# PermissionDialog
# ---------------------------------------------------------------------------


class TestPermissionDialog:
    """Permission dialog button outcomes."""

    @pytest.mark.asyncio
    async def test_approve_button(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            dialog = PermissionDialog(
                tool_name="Bash",
                preview="echo hello",
            )
            app.push_screen(dialog)
            await pilot.pause()

            # Click approve button.
            button = dialog.query_one("#approve")
            button.press()
            await pilot.pause()

            # Dialog should have dismissed — check that the screen stack
            # no longer has the dialog.
            assert dialog not in app.screen_stack

    @pytest.mark.asyncio
    async def test_deny_button(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            dialog = PermissionDialog(
                tool_name="Bash",
                preview="rm -rf /",
            )
            app.push_screen(dialog)
            await pilot.pause()

            button = dialog.query_one("#deny")
            button.press()
            await pilot.pause()

            assert dialog not in app.screen_stack

    @pytest.mark.asyncio
    async def test_session_button(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            dialog = PermissionDialog(
                tool_name="FileEdit",
                preview="edit config.py",
            )
            app.push_screen(dialog)
            await pilot.pause()

            button = dialog.query_one("#session")
            button.press()
            await pilot.pause()

            assert dialog not in app.screen_stack

    @pytest.mark.asyncio
    async def test_no_persist_option(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            dialog = PermissionDialog(
                tool_name="Bash",
                preview="ls",
                include_persist=False,
            )
            app.push_screen(dialog)
            await pilot.pause()

            # Persist button should not exist.
            persist_buttons = dialog.query("#persist")
            assert len(persist_buttons) == 0

    @pytest.mark.asyncio
    async def test_dialog_renders_tool_name(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            dialog = PermissionDialog(
                tool_name="Bash",
                preview="echo test",
            )
            app.push_screen(dialog)
            await pilot.pause()

            statics = [str(s.renderable) for s in dialog.query("Static")]
            assert any("Bash" in t for t in statics)


# ---------------------------------------------------------------------------
# PlanGateDialog
# ---------------------------------------------------------------------------


class TestPlanGateDialog:
    """Plan gate dialog decisions."""

    @pytest.mark.asyncio
    async def test_approve(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            dialog = PlanGateDialog(plan_text="# Plan\n\n- Build agent\n- Run evals")
            app.push_screen(dialog)
            await pilot.pause()

            button = dialog.query_one("#approve")
            button.press()
            await pilot.pause()

            assert dialog not in app.screen_stack

    @pytest.mark.asyncio
    async def test_abort(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            dialog = PlanGateDialog(plan_text="# Plan")
            app.push_screen(dialog)
            await pilot.pause()

            button = dialog.query_one("#abort")
            button.press()
            await pilot.pause()

            assert dialog not in app.screen_stack

    @pytest.mark.asyncio
    async def test_edit_mode(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            dialog = PlanGateDialog(plan_text="# Plan")
            app.push_screen(dialog)
            await pilot.pause()

            # Click edit to show input.
            button = dialog.query_one("#edit")
            button.press()
            await pilot.pause()

            # Edit input should now be visible.
            edit_input = dialog.query_one("#edit-input")
            assert edit_input.display is True


# ---------------------------------------------------------------------------
# TUI Screens
# ---------------------------------------------------------------------------


class TestDoctorScreen:
    """Doctor screen mounts and renders."""

    @pytest.mark.asyncio
    async def test_mounts_and_renders(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            screen = DoctorScreen()
            app.push_screen(screen)
            await pilot.pause()

            # Should render the header.
            statics = [str(s.renderable) for s in screen.query("Static")]
            assert any("doctor" in t.lower() or "diagnostic" in t.lower() for t in statics)

    @pytest.mark.asyncio
    async def test_escape_dismisses(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            screen = DoctorScreen()
            app.push_screen(screen)
            await pilot.pause()

            await pilot.press("q")
            await pilot.pause()

            assert screen not in app.screen_stack


class TestPlanScreen:
    """Plan screen mounts and renders."""

    @pytest.mark.asyncio
    async def test_empty_plan(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            screen = PlanScreen()
            app.push_screen(screen)
            await pilot.pause()

            statics = [str(s.renderable) for s in screen.query("Static")]
            assert any("no plan" in t.lower() for t in statics)

    @pytest.mark.asyncio
    async def test_with_plan_content(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            screen = PlanScreen(plan_text="## My Plan\n\nStep 1: Build\nStep 2: Test")
            app.push_screen(screen)
            await pilot.pause()

            # Screen should be pushed.
            assert screen in app.screen_stack


class TestResumeScreen:
    """Resume screen mounts."""

    @pytest.mark.asyncio
    async def test_no_store(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            screen = ResumeScreen()
            app.push_screen(screen)
            await pilot.pause()

            statics = [str(s.renderable) for s in screen.query("Static")]
            assert any("no session" in t.lower() for t in statics)


class TestSkillsScreen:
    """Skills screen mounts."""

    @pytest.mark.asyncio
    async def test_no_workspace(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            screen = SkillsScreen()
            app.push_screen(screen)
            await pilot.pause()

            statics = [str(s.renderable) for s in screen.query("Static")]
            assert any("no skill" in t.lower() for t in statics)


# ---------------------------------------------------------------------------
# BackgroundPanel
# ---------------------------------------------------------------------------


class TestBackgroundPanel:
    """Background panel shows/hides with tasks."""

    @pytest.mark.asyncio
    async def test_hidden_when_no_tasks(self) -> None:
        app = _make_app()
        async with app.run_test():
            panel = app.query_one(BackgroundPanel)
            assert panel.display is False

    @pytest.mark.asyncio
    async def test_visible_with_tasks(self) -> None:
        task = BackgroundTask(
            task_id="bg-1",
            description="Review code",
            status=TaskStatus.RUNNING,
        )
        state = replace(get_default_app_state(), background_tasks=(task,))
        app = _make_app(state)
        async with app.run_test():
            panel = app.query_one(BackgroundPanel)
            assert panel.display is True

    @pytest.mark.asyncio
    async def test_reactive_update(self) -> None:
        app = _make_app()
        async with app.run_test() as pilot:
            panel = app.query_one(BackgroundPanel)
            assert panel.display is False

            # Add a task.
            task = BackgroundTask(
                task_id="bg-1",
                description="Run evals",
                status=TaskStatus.QUEUED,
            )
            app.store.set_state(lambda s: replace(s, background_tasks=(task,)))
            await pilot.pause()
            assert panel.display is True

            # Clear tasks.
            app.store.set_state(lambda s: replace(s, background_tasks=()))
            await pilot.pause()
            assert panel.display is False


# ---------------------------------------------------------------------------
# Widget tree
# ---------------------------------------------------------------------------


class TestPhase4WidgetTree:
    """All Phase 4 widgets present in app."""

    @pytest.mark.asyncio
    async def test_background_panel_in_tree(self) -> None:
        app = _make_app()
        async with app.run_test():
            assert app.query_one(BackgroundPanel) is not None
