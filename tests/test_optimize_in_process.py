"""Tests for cli.commands.optimize.run_optimize_in_process (R4.4).

Exercises the extracted pure business-logic function shared by the Click
wrapper (``agentlab optimize``) and the ``/optimize`` slash handler. The
subprocess path is replaced by an in-process call that fires an
``on_event`` callback for every stream-json event the optimize run
would normally emit.
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


def test_run_optimize_in_process_emits_expected_events(cli_runner: CliRunner) -> None:
    """force_mock=True; the stream must contain phase/task/optimize_complete."""
    from cli.commands.optimize import run_optimize_in_process

    events: list[dict[str, Any]] = []
    with cli_runner.isolated_filesystem():
        run_optimize_in_process(
            cycles=1,
            force_mock=True,
            on_event=events.append,
        )

    names = [e.get("event") for e in events]
    assert "phase_started" in names
    assert "optimize_complete" in names


def test_run_optimize_in_process_emits_optimize_complete_terminal_event(
    cli_runner: CliRunner,
) -> None:
    """The last event is ``optimize_complete`` carrying the run metadata."""
    from cli.commands.optimize import run_optimize_in_process

    events: list[dict[str, Any]] = []
    with cli_runner.isolated_filesystem():
        run_optimize_in_process(
            cycles=1,
            force_mock=True,
            on_event=events.append,
        )

    assert events, "expected at least one event"
    final = events[-1]
    assert final.get("event") == "optimize_complete"
    # Keys must exist (values may be None depending on the path).
    for key in ("eval_run_id", "attempt_id", "config_path", "status"):
        assert key in final, f"expected {key!r} in terminal event: {final!r}"
    assert final["status"] in {"ok", "failed", "cancelled"}


def test_run_optimize_in_process_returns_result_dataclass(cli_runner: CliRunner) -> None:
    from cli.commands.optimize import run_optimize_in_process, OptimizeRunResult

    with cli_runner.isolated_filesystem():
        result = run_optimize_in_process(
            cycles=1,
            force_mock=True,
            on_event=lambda _: None,
        )

    assert isinstance(result, OptimizeRunResult)
    assert result.status in {"ok", "failed", "cancelled"}
    assert isinstance(result.warnings, tuple)
    assert isinstance(result.artifacts, tuple)


def test_run_optimize_in_process_raises_mock_fallback_error_on_strict_live(
    cli_runner: CliRunner,
) -> None:
    """strict_live + mock proposer must raise ``MockFallbackError``."""
    from cli.commands.optimize import run_optimize_in_process
    from cli.strict_live import MockFallbackError

    with cli_runner.isolated_filesystem():
        with pytest.raises(MockFallbackError):
            run_optimize_in_process(
                cycles=1,
                force_mock=True,
                strict_live=True,
                on_event=lambda _: None,
            )


def test_run_optimize_in_process_never_calls_subprocess_popen(
    cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The in-process path must NOT spawn any subprocess."""
    from cli.commands.optimize import run_optimize_in_process

    sentinel = MagicMock(side_effect=AssertionError("subprocess spawned!"))
    monkeypatch.setattr(subprocess, "Popen", sentinel)

    with cli_runner.isolated_filesystem():
        run_optimize_in_process(
            cycles=1,
            force_mock=True,
            on_event=lambda _: None,
        )

    sentinel.assert_not_called()
