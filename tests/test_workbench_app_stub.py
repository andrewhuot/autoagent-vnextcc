"""Tests for the T04 stub workbench_app loop + `workbench interactive` subcommand."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import click
from click.testing import CliRunner

from cli.sessions import SessionStore
from cli.workbench_app import (
    DEFAULT_PROMPT,
    StubAppResult,
    build_status_line,
    run_workbench_app,
)
from cli.workbench_app.app import (
    EXIT_TOKENS,
    RESUME_HINT_MAX_AGE_SECONDS,
    resume_hint,
)
from runner import cli as root_cli


# ---------------------------------------------------------------------------
# status line
# ---------------------------------------------------------------------------


def test_build_status_line_without_workspace_is_sentinel() -> None:
    line = build_status_line(None)
    assert "no workspace" in line
    assert "agentlab" in line


class _FakeActiveConfig:
    version = 7


class _FakeWorkspace:
    def __init__(self, label: str = "demo-ws", active: object | None = None) -> None:
        self.workspace_label = label
        self._active = active

    def resolve_active_config(self) -> object | None:
        return self._active


def test_build_status_line_with_workspace_shows_label_and_version() -> None:
    workspace = _FakeWorkspace(label="demo-ws", active=_FakeActiveConfig())
    line = build_status_line(workspace)
    assert "demo-ws" in line
    assert "v007" in line


def test_build_status_line_tolerates_active_config_exception() -> None:
    class _Raising:
        workspace_label = "ws"

        def resolve_active_config(self):
            raise RuntimeError("db locked")

    # Should not raise — this path runs in tight loops with flaky state.
    line = build_status_line(_Raising())
    assert "ws" in line


# ---------------------------------------------------------------------------
# stub loop
# ---------------------------------------------------------------------------


def _capture_echo():
    lines: list[str] = []

    def echo(text: str = "") -> None:
        lines.append(text)

    return lines, echo


def test_stub_loop_echoes_input_and_exits_on_exit_token() -> None:
    lines, echo = _capture_echo()
    result = run_workbench_app(
        workspace=None,
        input_provider=iter(["hello world", "/exit"]),
        echo=echo,
        show_banner=False,
    )
    assert isinstance(result, StubAppResult)
    assert result.lines_read == 2
    assert result.exited_via == "/exit"
    assert any("echo: hello world" in line for line in lines)
    assert any("Goodbye" in line for line in lines)


def test_stub_loop_skips_blank_lines() -> None:
    lines, echo = _capture_echo()
    result = run_workbench_app(
        workspace=None,
        input_provider=iter(["", "  ", "ping", "/exit"]),
        echo=echo,
        show_banner=False,
    )
    assert result.lines_read == 2  # "ping" + "/exit"
    echoed = [line for line in lines if "echo:" in line]
    assert echoed == ["  echo: ping"]


def test_stub_loop_exits_on_eof() -> None:
    def provider(_prompt: str) -> str:
        raise EOFError

    lines, echo = _capture_echo()
    result = run_workbench_app(
        workspace=None,
        input_provider=provider,
        echo=echo,
        show_banner=False,
    )
    assert result.exited_via == "eof"
    assert result.lines_read == 0


def test_stub_loop_handles_keyboard_interrupt() -> None:
    def provider(_prompt: str) -> str:
        raise KeyboardInterrupt

    lines, echo = _capture_echo()
    result = run_workbench_app(
        workspace=None,
        input_provider=provider,
        echo=echo,
        show_banner=False,
    )
    assert result.exited_via == "interrupt"
    assert any("interrupted" in line for line in lines)


def test_stub_loop_renders_banner_by_default() -> None:
    lines, echo = _capture_echo()
    run_workbench_app(
        workspace=None,
        input_provider=iter(["/exit"]),
        echo=echo,
        show_banner=True,
    )
    joined = "\n".join(lines)
    assert "AgentLab Workbench" in joined
    # The branded ASCII banner contains the "Experiment. Evaluate. Refine." tagline.
    assert "Experiment. Evaluate. Refine." in joined


def test_stub_loop_recognizes_all_exit_tokens() -> None:
    for token in EXIT_TOKENS:
        lines, echo = _capture_echo()
        result = run_workbench_app(
            workspace=None,
            input_provider=iter([token]),
            echo=echo,
            show_banner=False,
        )
        assert result.exited_via == "/exit", f"{token!r} should end via /exit"


def test_stub_loop_default_prompt_string() -> None:
    # Ensure the prompt token we'll later feed to prompt_toolkit is stable.
    assert DEFAULT_PROMPT.endswith("> ")


# ---------------------------------------------------------------------------
# Click subcommand wiring
# ---------------------------------------------------------------------------


def test_workbench_interactive_subcommand_is_registered() -> None:
    runner = CliRunner()
    result = runner.invoke(root_cli, ["workbench", "interactive", "--help"])
    assert result.exit_code == 0, result.output
    assert "interactive" in result.output.lower()


def test_workbench_interactive_subcommand_runs_stub_with_no_banner() -> None:
    runner = CliRunner()

    # The stub blocks on input() by default; redirect it via patch so the
    # command returns deterministically.
    with patch("cli.workbench_app.app._default_input_provider", side_effect=EOFError):
        result = runner.invoke(
            root_cli,
            ["workbench", "interactive", "--no-banner"],
            catch_exceptions=False,
        )

    assert result.exit_code == 0, result.output
    # With --no-banner there's no "Experiment. Evaluate. Refine." line.
    assert "Experiment. Evaluate. Refine." not in result.output


# ---------------------------------------------------------------------------
# T17 — /resume startup hint
# ---------------------------------------------------------------------------


def test_resume_hint_returns_none_without_store() -> None:
    assert resume_hint(None) is None


def test_resume_hint_returns_none_with_empty_store(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    assert resume_hint(store) is None


def test_resume_hint_offers_recent_session(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session = store.create(title="last-friday")
    # 2 hours ago.
    session.updated_at = time.time() - 2 * 3600
    store.save(session)

    hint = resume_hint(store)
    assert hint is not None
    assert "last-friday" in hint
    assert "2h ago" in hint
    assert "/resume" in hint


def test_resume_hint_skips_older_than_max_age(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session = store.create(title="ancient")
    session.updated_at = time.time() - (RESUME_HINT_MAX_AGE_SECONDS + 60)
    store.save(session)
    assert resume_hint(store) is None


def test_resume_hint_skips_when_current_matches_latest(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session = store.create(title="same")
    assert resume_hint(store, current=session) is None


def test_resume_hint_minutes_formatting(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session = store.create(title="fresh")
    session.updated_at = time.time() - 150  # 2m30s
    store.save(session)
    hint = resume_hint(store)
    assert hint is not None and "2m ago" in hint


def test_run_workbench_app_shows_resume_hint_in_banner(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session = store.create(title="prev")
    session.updated_at = time.time() - 3600
    store.save(session)

    lines: list[str] = []
    run_workbench_app(
        workspace=None,
        input_provider=iter(["/exit"]),
        echo=lines.append,
        show_banner=True,
        session_store=store,
    )
    joined = "\n".join(click.unstyle(line) for line in lines)
    assert "/resume to continue" in joined
    assert "prev" in joined


def test_run_workbench_app_suppresses_hint_without_banner(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session = store.create(title="prev")
    session.updated_at = time.time() - 3600
    store.save(session)

    lines: list[str] = []
    run_workbench_app(
        workspace=None,
        input_provider=iter(["/exit"]),
        echo=lines.append,
        show_banner=False,
        session_store=store,
    )
    joined = "\n".join(click.unstyle(line) for line in lines)
    assert "/resume to continue" not in joined
