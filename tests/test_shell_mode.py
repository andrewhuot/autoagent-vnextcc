"""Tests for :mod:`cli.workbench_app.shell_mode` (S3 — ``!`` shell input)."""

from __future__ import annotations

from pathlib import Path

import click

from cli.workbench_app.shell_mode import (
    ShellOutcome,
    is_shell_line,
    permission_allows_auto,
    run_shell_turn,
)


def _capture():
    lines: list[str] = []

    def echo(line: str = "") -> None:
        lines.append(click.unstyle(line))

    return lines, echo


def _fake_runner(command: str, cwd: Path | None) -> tuple[int, str]:
    return 0, f"ran:{command}|cwd={cwd}"


def test_is_shell_line_detects_bang_prefix() -> None:
    assert is_shell_line("!ls")
    assert is_shell_line("  !echo hi")
    assert not is_shell_line("ls")
    assert not is_shell_line("/build !hi")


def test_permission_allows_auto() -> None:
    assert permission_allows_auto("acceptEdits")
    assert permission_allows_auto("bypass")
    assert not permission_allows_auto("default")
    assert not permission_allows_auto("plan")


def test_run_shell_turn_blocked_in_plan_mode() -> None:
    lines, echo = _capture()
    outcome = run_shell_turn(
        "!echo hi",
        permission_mode="plan",
        echo=echo,
        runner=_fake_runner,
    )
    assert outcome.handled is True
    assert outcome.ran is False
    assert outcome.reason == "blocked_plan"
    joined = "\n".join(lines)
    assert "Shell mode is blocked" in joined


def test_run_shell_turn_confirm_declined_in_default_mode() -> None:
    lines, echo = _capture()
    outcome = run_shell_turn(
        "!rm -rf /",
        permission_mode="default",
        echo=echo,
        input_provider=lambda _prompt: "n",
        runner=_fake_runner,
    )
    assert outcome.handled is True
    assert outcome.ran is False
    assert outcome.reason == "declined"
    assert any("Skipped" in line for line in lines)


def test_run_shell_turn_confirm_accepted_in_default_mode(tmp_path: Path) -> None:
    lines, echo = _capture()
    outcome = run_shell_turn(
        "!ls",
        permission_mode="default",
        echo=echo,
        input_provider=lambda _prompt: "y",
        workspace_root=tmp_path,
        runner=_fake_runner,
    )
    assert outcome.ran is True
    assert outcome.returncode == 0
    assert "ran:ls" in outcome.stdout


def test_run_shell_turn_auto_runs_in_accept_edits(tmp_path: Path) -> None:
    lines, echo = _capture()
    outcome = run_shell_turn(
        "!pwd",
        permission_mode="acceptEdits",
        echo=echo,
        runner=_fake_runner,
        workspace_root=tmp_path,
    )
    assert outcome.ran is True
    assert str(tmp_path) in outcome.stdout


def test_run_shell_turn_empty_command_is_rejected() -> None:
    lines, echo = _capture()
    outcome = run_shell_turn(
        "!   ",
        permission_mode="bypass",
        echo=echo,
        runner=_fake_runner,
    )
    assert outcome.handled is True
    assert outcome.ran is False
    assert outcome.reason == "empty"


def test_run_shell_turn_passes_through_non_bang_lines_unhandled() -> None:
    lines, echo = _capture()
    outcome = run_shell_turn(
        "echo hi",
        permission_mode="default",
        echo=echo,
        runner=_fake_runner,
    )
    assert isinstance(outcome, ShellOutcome)
    assert outcome.handled is False


def test_run_shell_turn_surfaces_runner_errors_without_crashing() -> None:
    lines, echo = _capture()

    def _bad_runner(_cmd: str, _cwd: Path | None) -> tuple[int, str]:
        raise RuntimeError("boom")

    outcome = run_shell_turn(
        "!true",
        permission_mode="bypass",
        echo=echo,
        runner=_bad_runner,
    )
    assert outcome.reason == "runner_error"
    assert outcome.ran is False
    assert any("boom" in line for line in lines)
