"""Tests for cli/workbench_app/screens (T08b)."""

from __future__ import annotations

import time

import click
import pytest

from cli.sessions import Session
from cli.workbench_app.commands import Screen as ScreenProtocol
from cli.workbench_app.screens import (
    ACTION_CANCEL,
    ACTION_EXIT,
    DoctorScreen,
    ResumeScreen,
    Screen,
    ScreenResult,
    SkillItem,
    SkillsScreen,
    iter_keys,
)
from cli.workbench_app.screens.resume import ACTION_FORK, ACTION_RESUME


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _EchoCapture:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, line: str) -> None:
        self.lines.append(line)

    def text(self) -> str:
        return "\n".join(self.lines)

    def plain(self) -> str:
        return click.unstyle(self.text())


class _Dummy(Screen):
    """Minimal Screen subclass used to exercise the base-class loop."""

    name = "dummy"
    title = "dummy title"

    def __init__(self, *, keys=None, echo=None) -> None:
        super().__init__(keys=keys, echo=echo)
        self.paints = 0
        self.seen: list[str] = []

    def render_lines(self) -> list[str]:
        self.paints += 1
        return [f"paint:{self.paints}"]

    def handle_key(self, key: str) -> ScreenResult | None:
        self.seen.append(key)
        if key == "q":
            return ScreenResult(action=ACTION_EXIT, value="bye", meta_messages=("done.",))
        return None


# ---------------------------------------------------------------------------
# base.Screen
# ---------------------------------------------------------------------------


def test_iter_keys_raises_eof_on_exhaustion():
    provider = iter_keys(["a", "b"])
    assert provider() == "a"
    assert provider() == "b"
    with pytest.raises(EOFError):
        provider()


def test_screen_paints_header_render_footer():
    echo = _EchoCapture()
    screen = _Dummy(keys=iter_keys(["q"]), echo=echo)
    result = screen.run()
    assert result == ScreenResult(action=ACTION_EXIT, value="bye", meta_messages=("done.",))
    # Header ("dummy title" + blank), render_lines, footer (empty by default).
    assert echo.plain().startswith("dummy title\n\npaint:1")


def test_screen_repaints_after_non_terminal_key():
    echo = _EchoCapture()
    screen = _Dummy(keys=iter_keys(["x", "q"]), echo=echo)
    screen.run()
    # One paint per non-terminal iteration plus the initial.
    assert screen.paints == 2
    assert screen.seen == ["x", "q"]


def test_screen_eof_returns_cancel():
    echo = _EchoCapture()
    screen = _Dummy(keys=iter_keys([]), echo=echo)
    result = screen.run()
    assert result == ScreenResult(action=ACTION_CANCEL)


def test_screen_keyboard_interrupt_returns_cancel():
    echo = _EchoCapture()

    def _boom() -> str:
        raise KeyboardInterrupt

    screen = _Dummy(keys=_boom, echo=echo)
    assert screen.run() == ScreenResult(action=ACTION_CANCEL)


def test_screen_normalizes_named_keys_lowercase():
    echo = _EchoCapture()
    screen = _Dummy(keys=iter_keys(["ENTER", "q"]), echo=echo)
    screen.run()
    assert screen.seen[0] == "enter"
    # Single-char keys are preserved as-is.
    assert screen.seen[1] == "q"


def test_screen_preserves_single_char_case():
    class _CaseSensitive(Screen):
        def __init__(self, *, keys=None, echo=None) -> None:
            super().__init__(keys=keys, echo=echo)
            self.got: list[str] = []

        def render_lines(self) -> list[str]:
            return []

        def handle_key(self, key: str) -> ScreenResult | None:
            self.got.append(key)
            if key == "Q":
                return ScreenResult(action=ACTION_EXIT)
            return None

    echo = _EchoCapture()
    screen = _CaseSensitive(keys=iter_keys(["k", "K", "Q"]), echo=echo)
    screen.run()
    assert screen.got == ["k", "K", "Q"]


def test_screen_satisfies_commands_screen_protocol():
    screen = _Dummy(keys=iter_keys(["q"]))
    assert isinstance(screen, ScreenProtocol)


def test_screen_requires_abstract_methods():
    with pytest.raises(TypeError):
        Screen()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# DoctorScreen
# ---------------------------------------------------------------------------


def test_doctor_screen_renders_runner_output_and_exits_on_q():
    echo = _EchoCapture()
    runner_calls: list[int] = []

    def _runner() -> str:
        runner_calls.append(1)
        return "checks: 3 passed\nnote: ok"

    screen = DoctorScreen(runner=_runner, keys=iter_keys(["q"]), echo=echo)
    result = screen.run()

    assert result == ScreenResult(action=ACTION_EXIT)
    assert "checks: 3 passed" in echo.plain()
    assert "note: ok" in echo.plain()
    # Runner only invoked once — cached across re-paints.
    assert runner_calls == [1]


def test_doctor_screen_enter_and_escape_also_exit():
    for key in ("enter", "escape"):
        echo = _EchoCapture()
        screen = DoctorScreen(
            runner=lambda: "ok", keys=iter_keys([key]), echo=echo
        )
        assert screen.run().action == ACTION_EXIT


def test_doctor_screen_handles_empty_runner_output():
    echo = _EchoCapture()
    screen = DoctorScreen(runner=lambda: "   ", keys=iter_keys(["q"]), echo=echo)
    screen.run()
    assert "(doctor produced no output)" in echo.plain()


def test_doctor_screen_renders_error_on_runner_exception():
    echo = _EchoCapture()

    def _bad() -> str:
        raise RuntimeError("boom")

    screen = DoctorScreen(runner=_bad, keys=iter_keys(["q"]), echo=echo)
    result = screen.run()
    assert result.action == ACTION_EXIT
    assert "Error running doctor: boom" in echo.plain()


def test_doctor_screen_ignores_unknown_keys():
    echo = _EchoCapture()
    screen = DoctorScreen(runner=lambda: "ok", keys=iter_keys(["x", "z", "q"]), echo=echo)
    screen.run()
    # "q" is the only exit key; the others should have caused re-paints.
    # The runner output appears at least twice (initial + after an ignored key).
    assert echo.plain().count("ok") >= 2


# ---------------------------------------------------------------------------
# ResumeScreen
# ---------------------------------------------------------------------------


def _make_session(sid: str, title: str, *, goal: str = "", offset: float = 0) -> Session:
    now = time.time() - offset
    return Session(
        session_id=sid,
        title=title,
        started_at=now,
        updated_at=now,
        active_goal=goal,
    )


def test_resume_screen_empty_list_paints_placeholder_and_cancels():
    echo = _EchoCapture()
    screen = ResumeScreen([], keys=iter_keys(["enter"]), echo=echo)
    result = screen.run()
    assert result.action == ACTION_CANCEL
    assert "No previous session to resume." in result.meta_messages
    assert "(no sessions found)" in echo.plain()


def test_resume_screen_enter_returns_selected_session_id():
    sessions = [
        _make_session("s1", "first", goal="goal-1"),
        _make_session("s2", "second", offset=60),
    ]
    echo = _EchoCapture()
    screen = ResumeScreen(sessions, keys=iter_keys(["down", "enter"]), echo=echo)
    result = screen.run()
    assert result.action == ACTION_RESUME
    assert result.value == "s2"
    assert any("Resumed session: second" in m for m in result.meta_messages)


def test_resume_screen_fork_key_returns_fork_action():
    sessions = [_make_session("s1", "only")]
    screen = ResumeScreen(sessions, keys=iter_keys(["f"]), echo=_EchoCapture())
    result = screen.run()
    assert result.action == ACTION_FORK
    assert result.value == "s1"


def test_resume_screen_q_cancels():
    sessions = [_make_session("s1", "only")]
    screen = ResumeScreen(sessions, keys=iter_keys(["q"]), echo=_EchoCapture())
    assert screen.run().action == ACTION_CANCEL


def test_resume_screen_cursor_clamps_to_bounds():
    sessions = [_make_session("s1", "a"), _make_session("s2", "b")]
    # Press up 3 times then enter — cursor stays at 0 → picks s1.
    screen = ResumeScreen(
        sessions, keys=iter_keys(["up", "up", "up", "enter"]), echo=_EchoCapture()
    )
    result = screen.run()
    assert result.value == "s1"

    # Press down 5 times then enter — cursor stays at last idx → picks s2.
    screen = ResumeScreen(
        sessions,
        keys=iter_keys(["down", "down", "down", "down", "down", "enter"]),
        echo=_EchoCapture(),
    )
    assert screen.run().value == "s2"


def test_resume_screen_renders_selected_marker():
    sessions = [_make_session("s1", "first"), _make_session("s2", "second")]
    echo = _EchoCapture()
    screen = ResumeScreen(sessions, keys=iter_keys(["q"]), echo=echo)
    screen.run()
    plain = echo.plain()
    # First session should be selected by default — marker is "▶".
    assert "▶" in plain
    assert "first" in plain
    assert "second" in plain


def test_resume_screen_accepts_store_instead_of_list(tmp_path):
    from cli.sessions import SessionStore

    store = SessionStore(tmp_path / "sessions")
    first = store.create(title="alpha")
    store.append_entry(first, role="user", content="hi")
    second = store.create(title="beta")
    store.append_entry(second, role="user", content="hello")

    screen = ResumeScreen(store=store, keys=iter_keys(["enter"]), echo=_EchoCapture())
    result = screen.run()
    assert result.action == ACTION_RESUME
    # ``second`` was appended most recently → it sits at the top of the picker.
    assert result.value == second.session_id


# ---------------------------------------------------------------------------
# SkillsScreen
# ---------------------------------------------------------------------------


def test_skills_screen_empty_placeholder_and_exit_on_q():
    echo = _EchoCapture()
    screen = SkillsScreen([], keys=iter_keys(["q"]), echo=echo)
    result = screen.run()
    assert result.action == ACTION_EXIT
    assert "(no skills installed)" in echo.plain()


def test_skills_screen_navigate_and_show_returns_selected_id():
    items = [
        SkillItem(skill_id="alpha", name="Alpha Skill", kind="python"),
        SkillItem(skill_id="beta", name="Beta Skill", description="Second."),
    ]
    screen = SkillsScreen(items, keys=iter_keys(["down", "s"]), echo=_EchoCapture())
    result = screen.run()
    assert result.action == "show"
    assert result.value == "beta"


def test_skills_screen_add_has_no_selection_payload():
    items = [SkillItem(skill_id="alpha", name="Alpha")]
    screen = SkillsScreen(items, keys=iter_keys(["a"]), echo=_EchoCapture())
    result = screen.run()
    assert result.action == "add"
    assert result.value is None


def test_skills_screen_remove_uses_selection():
    items = [SkillItem(skill_id="a"), SkillItem(skill_id="b")]
    screen = SkillsScreen(items, keys=iter_keys(["j", "r"]), echo=_EchoCapture())
    result = screen.run()
    assert result.action == "remove"
    assert result.value == "b"


def test_skills_screen_unknown_keys_ignored():
    items = [SkillItem(skill_id="only", name="Only")]
    screen = SkillsScreen(items, keys=iter_keys(["x", "z", "q"]), echo=_EchoCapture())
    result = screen.run()
    assert result.action == ACTION_EXIT


def test_skills_screen_cursor_clamps():
    items = [SkillItem(skill_id="a"), SkillItem(skill_id="b")]
    screen = SkillsScreen(
        items, keys=iter_keys(["up", "up", "up", "s"]), echo=_EchoCapture()
    )
    result = screen.run()
    assert result.value == "a"


def test_skills_screen_renders_kind_and_description():
    items = [
        SkillItem(skill_id="alpha", name="Alpha", kind="python", description="First."),
    ]
    echo = _EchoCapture()
    screen = SkillsScreen(items, keys=iter_keys(["q"]), echo=echo)
    screen.run()
    plain = echo.plain()
    assert "[python]" in plain
    assert "Alpha" in plain
    assert "First." in plain
