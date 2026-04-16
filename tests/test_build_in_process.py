"""Tests for cli.workbench.run_build_in_process (R4.3).

Exercises the extracted pure business-logic function that both the Click
wrapper (``workbench build``) and the ``/build`` slash handler now share.
The subprocess path is replaced by an in-process call that fires an
``on_event`` callback for every stream-json event the build run would
normally emit.
"""

from __future__ import annotations

import subprocess
from typing import Any
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner


@pytest.fixture
def cli_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


def _with_workspace(cli_runner: CliRunner):
    """Return a context manager that yields an isolated filesystem + workspace."""
    return cli_runner.isolated_filesystem()


def _bootstrap_workspace(cli_runner: CliRunner) -> None:
    """Create a minimal AgentLab workspace at cwd so ``_require_workspace`` succeeds."""
    from runner import cli

    result = cli_runner.invoke(cli, ["new", "--name", "test-ws", "--force"])
    # Some CLIs may not support --force; fallback is to just ensure .agentlab exists
    if result.exit_code != 0:
        import os
        os.makedirs(".agentlab", exist_ok=True)
        with open("agentlab.yaml", "w") as fh:
            fh.write("version: 1\n")


def test_run_build_in_process_emits_stream_events(cli_runner: CliRunner) -> None:
    from cli.workbench import run_build_in_process

    events: list[dict[str, Any]] = []
    with _with_workspace(cli_runner):
        _bootstrap_workspace(cli_runner)
        result = run_build_in_process(
            brief="Build a simple support agent",
            mock=True,
            on_event=events.append,
        )

    assert events, "expected at least one event"
    names = [e.get("event") for e in events]
    # Terminal event is always present.
    assert "build_complete" in names
    # The workbench emits run.* lifecycle events.
    assert any(n in {"run.completed", "run.failed"} for n in names)
    assert result.status in {"ok", "failed"}


def test_run_build_in_process_emits_build_complete_terminal_event(
    cli_runner: CliRunner,
) -> None:
    from cli.workbench import run_build_in_process

    events: list[dict[str, Any]] = []
    with _with_workspace(cli_runner):
        _bootstrap_workspace(cli_runner)
        run_build_in_process(
            brief="Build a tiny agent",
            mock=True,
            on_event=events.append,
        )

    final = events[-1]
    assert final.get("event") == "build_complete"
    assert "project_id" in final
    assert "config_path" in final
    assert "status" in final


def test_run_build_in_process_returns_result_dataclass(cli_runner: CliRunner) -> None:
    from cli.workbench import run_build_in_process, BuildRunResult

    with _with_workspace(cli_runner):
        _bootstrap_workspace(cli_runner)
        result = run_build_in_process(
            brief="Build a minimal agent",
            mock=True,
            on_event=lambda _e: None,
        )

    assert isinstance(result, BuildRunResult)
    assert result.status in {"ok", "failed"}
    assert result.events  # event trail populated
    # project_id may be None only in pathological cases; for mock builds it is set.
    assert result.project_id is not None


def test_run_build_in_process_raises_on_require_live_failure(cli_runner: CliRunner) -> None:
    """When ``require_live=True`` and no live router is configured, the function
    must raise a domain error (not a click.ClickException)."""
    from cli.workbench import run_build_in_process, BuildCommandError

    with _with_workspace(cli_runner):
        _bootstrap_workspace(cli_runner)
        # ``mock=True`` guarantees no live router; combined with require_live=True
        # this should raise BuildCommandError at the domain boundary.
        with pytest.raises(BuildCommandError):
            run_build_in_process(
                brief="Force live build",
                mock=True,
                require_live=True,
                on_event=lambda _e: None,
            )


def test_run_build_in_process_never_calls_subprocess_popen(
    cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The in-process path must NOT spawn any subprocess."""
    from cli.workbench import run_build_in_process

    sentinel = MagicMock(side_effect=AssertionError("subprocess spawned!"))
    monkeypatch.setattr(subprocess, "Popen", sentinel)

    with _with_workspace(cli_runner):
        _bootstrap_workspace(cli_runner)
        run_build_in_process(
            brief="Build w/o subprocess",
            mock=True,
            on_event=lambda _e: None,
        )

    sentinel.assert_not_called()
