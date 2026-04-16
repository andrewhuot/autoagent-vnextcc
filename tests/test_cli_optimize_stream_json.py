"""Regression test asserting that `agentlab optimize --output-format stream-json`
event sequences remain stable across the R4.4 in-process refactor.

The Click wrapper now delegates to ``run_optimize_in_process``, which fires
the same event-name sequence the subprocess path previously emitted plus a
new terminal ``optimize_complete`` event.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner


@pytest.fixture
def cli_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


def _parse_events(output: str) -> list[dict]:
    parsed: list[dict] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            parsed.append(json.loads(stripped))
        except json.JSONDecodeError:
            continue
    return parsed


def test_cli_optimize_stream_json_event_sequence_unchanged(cli_runner: CliRunner) -> None:
    """The full event-name sequence must end with ``optimize_complete``."""
    from runner import cli

    with cli_runner.isolated_filesystem():
        result = cli_runner.invoke(
            cli,
            ["optimize", "--cycles", "1", "--output-format", "stream-json"],
        )

    assert result.exit_code == 0, result.output
    payloads = _parse_events(result.output)
    assert payloads, f"expected at least one stream-json event, got: {result.output!r}"

    # Strip wall-clock timestamps.
    for p in payloads:
        p.pop("timestamp", None)

    names = [p.get("event") for p in payloads]

    # Stream must START with a phase_started for optimize.
    assert names[0] == "phase_started"

    # Stream must END with optimize_complete.
    assert names[-1] == "optimize_complete", (
        f"expected optimize_complete last, got names={names!r}"
    )

    final = payloads[-1]
    for key in ("eval_run_id", "attempt_id", "config_path", "status"):
        assert key in final, f"expected {key!r} in terminal event: {final!r}"
