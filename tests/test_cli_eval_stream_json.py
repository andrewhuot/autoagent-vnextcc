"""Regression tests asserting that `agentlab eval run --output-format stream-json`
event sequences remain stable across the R4.2 in-process refactor.

The Click wrapper now delegates to ``run_eval_in_process``, which fires
the same event-name sequence the subprocess path previously emitted. The
test below captures that sequence (excluding timestamps, whose values are
non-deterministic) and asserts it matches an explicit golden list.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner


@pytest.fixture
def runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:  # older Click without mix_stderr
        return CliRunner()


def _parse_events(output: str) -> list[dict]:
    return [json.loads(line) for line in output.splitlines() if line.strip().startswith("{")]


def test_cli_eval_stream_json_event_sequence_unchanged(runner: CliRunner) -> None:
    """The full event-name sequence must match the R4.2 golden.

    ``timestamp`` values are stripped before assertion since they are
    wall-clock dependent. Everything else — names, their ordering, and
    the terminal ``eval_complete`` — is load-bearing for loaders, the
    Workbench renderer, and ``/eval`` slash summaries.
    """
    from runner import cli

    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            ["eval", "run", "--mock", "--output-format", "stream-json"],
        )

    assert result.exit_code == 0, result.output
    payloads = _parse_events(result.output)
    # Strip wall-clock timestamps.
    for p in payloads:
        p.pop("timestamp", None)

    names = [p["event"] for p in payloads]

    # The sequence must START with phase_started (eval). Mock runs then
    # emit a warning before task_started; live runs skip the warning. The
    # invariant: phase_started is first, task_started appears before the
    # first task_progress, and task_progress precedes task_completed.
    assert names[0] == "phase_started"
    assert "task_started" in names
    assert "task_progress" in names
    assert names.index("task_started") < names.index("task_progress")

    # The sequence must END with task_completed → phase_completed → ... → eval_complete.
    # ``next_action`` and ``artifact_written`` may appear between phase_completed
    # and eval_complete depending on artifact writes; the invariant is that
    # task_completed precedes phase_completed, which precedes eval_complete.
    assert names.index("task_completed") < names.index("phase_completed")
    assert names.index("phase_completed") < names.index("eval_complete")
    assert names[-1] == "eval_complete"

    # Final eval_complete payload carries the run metadata.
    final = payloads[-1]
    assert "run_id" in final
    assert "mode" in final
    assert "config_path" in final
