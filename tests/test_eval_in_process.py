"""Tests for cli.commands.eval.run_eval_in_process (R4.2 pilot).

Exercises the extracted pure business-logic function that both the Click
wrapper and the `/eval` slash handler now share. The subprocess path is
replaced by an in-process call that fires an `on_event` callback for every
stream-json event the eval run would normally emit.
"""

from __future__ import annotations

import subprocess
from typing import Any
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture(autouse=True)
def _register_eval_commands_once():
    """Make sure ``cli.commands.eval.run_eval_in_process`` is importable.

    ``cli.commands.eval.register_eval_commands(cli)`` is what wires the
    Click callbacks, but the pure function we're testing is module-level
    and doesn't need the CLI to be registered. No-op here — just a seam
    for future setup.
    """
    return None


def test_run_eval_in_process_emits_phase_events(tmp_path) -> None:
    from cli.commands.eval import run_eval_in_process

    events: list[dict[str, Any]] = []
    run_eval_in_process(
        config_path=None,
        suite=None,
        category=None,
        dataset=None,
        dataset_split="all",
        output_path=None,
        instruction_overrides_path=None,
        real_agent=False,
        force_mock=True,
        require_live=False,
        strict_live=False,
        on_event=events.append,
    )

    names = [e.get("event") for e in events]
    # Must contain the canonical phase / task lifecycle events:
    assert "phase_started" in names
    assert "task_started" in names
    assert any(n == "task_progress" for n in names)
    assert "task_completed" in names
    assert "phase_completed" in names
    assert "eval_complete" in names


def test_run_eval_in_process_returns_run_id_and_config_path(tmp_path) -> None:
    from cli.commands.eval import run_eval_in_process, EvalRunResult

    result = run_eval_in_process(
        config_path=None,
        suite=None,
        category=None,
        dataset=None,
        dataset_split="all",
        output_path=None,
        instruction_overrides_path=None,
        real_agent=False,
        force_mock=True,
        require_live=False,
        strict_live=False,
        on_event=lambda _: None,
    )

    assert isinstance(result, EvalRunResult)
    # run_id may be None for older/edge code paths; but the mock runner does
    # produce a run_id in the default Score payload. Ensure either a truthy
    # run_id or at least a string type.
    assert result.run_id is None or isinstance(result.run_id, str)
    assert result.status == "ok"
    assert result.mode in {"mock", "mixed", "live"}


def test_run_eval_in_process_emits_eval_complete_with_run_id(tmp_path) -> None:
    from cli.commands.eval import run_eval_in_process

    events: list[dict[str, Any]] = []
    run_eval_in_process(
        config_path=None,
        suite=None,
        category=None,
        dataset=None,
        dataset_split="all",
        output_path=None,
        instruction_overrides_path=None,
        real_agent=False,
        force_mock=True,
        require_live=False,
        strict_live=False,
        on_event=events.append,
    )

    assert events, "expected at least one event"
    final = events[-1]
    assert final.get("event") == "eval_complete"
    # run_id key must exist (may be None in pathological mocks but key present)
    assert "run_id" in final
    assert "config_path" in final
    assert "mode" in final


def test_run_eval_in_process_raises_on_strict_live_mock_fallback(tmp_path) -> None:
    from cli.commands.eval import run_eval_in_process
    from cli.strict_live import MockFallbackError

    # Force mock but require strict-live: the post-hoc gate must raise.
    with pytest.raises(MockFallbackError):
        run_eval_in_process(
            config_path=None,
            suite=None,
            category=None,
            dataset=None,
            dataset_split="all",
            output_path=None,
            instruction_overrides_path=None,
            real_agent=False,
            force_mock=True,
            require_live=True,
            strict_live=True,
            on_event=lambda _: None,
        )


def test_run_eval_in_process_never_calls_subprocess_popen(tmp_path, monkeypatch) -> None:
    """The in-process path must NOT spawn any subprocess."""
    from cli.commands.eval import run_eval_in_process

    sentinel = MagicMock(side_effect=AssertionError("subprocess spawned!"))
    monkeypatch.setattr(subprocess, "Popen", sentinel)

    run_eval_in_process(
        config_path=None,
        suite=None,
        category=None,
        dataset=None,
        dataset_split="all",
        output_path=None,
        instruction_overrides_path=None,
        real_agent=False,
        force_mock=True,
        require_live=False,
        strict_live=False,
        on_event=lambda _: None,
    )

    sentinel.assert_not_called()
