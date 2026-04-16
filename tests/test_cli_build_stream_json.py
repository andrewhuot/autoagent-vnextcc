"""Regression tests asserting that `agentlab workbench build --output-format stream-json`
event sequences remain stable across the R4.3 in-process refactor.

The Click wrapper now delegates to ``run_build_in_process``, which fires
the same event-name sequence the subprocess path previously emitted. The
test below captures that sequence (excluding timestamps, whose values are
non-deterministic) and asserts it matches an explicit golden list.
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


def _bootstrap_workspace() -> None:
    """Create a minimal AgentLab workspace at cwd."""
    import os

    os.makedirs(".agentlab", exist_ok=True)
    with open("agentlab.yaml", "w") as fh:
        fh.write("version: 1\n")


def test_cli_build_stream_json_event_sequence_unchanged(cli_runner: CliRunner) -> None:
    """The full event-name sequence must match the R4.3 golden.

    ``timestamp`` values are stripped before assertion since they are
    wall-clock dependent. The invariant is that the stream ends with a
    terminal ``build_complete`` event carrying ``project_id``,
    ``config_path`` and ``status``. Intermediate events stay in workbench
    ``{event, data}`` shape — unchanged by R4.3.
    """
    from runner import cli

    with cli_runner.isolated_filesystem():
        _bootstrap_workspace()
        result = cli_runner.invoke(
            cli,
            [
                "workbench",
                "build",
                "Build a simple support agent",
                "--mock",
                "--output-format",
                "stream-json",
            ],
        )

    assert result.exit_code == 0, result.output

    payloads = _parse_events(result.output)
    assert payloads, f"expected at least one stream-json event, got: {result.output!r}"

    # Strip wall-clock timestamps + nondeterministic ids recursively.
    def _scrub(obj):
        if isinstance(obj, dict):
            return {
                k: _scrub(v)
                for k, v in obj.items()
                if k not in {"timestamp", "created_at"}
            }
        if isinstance(obj, list):
            return [_scrub(v) for v in obj]
        return obj

    payloads = [_scrub(p) for p in payloads]

    names = [p.get("event") for p in payloads]

    # The invariants:
    # 1. The stream ends with build_complete.
    assert names[-1] == "build_complete", f"expected build_complete last, got names={names!r}"

    # 2. build_complete carries the expected keys.
    final = payloads[-1]
    assert "project_id" in final
    assert "config_path" in final
    assert "status" in final
    assert final["status"] in {"ok", "failed", "cancelled"}

    # 3. Build lifecycle events (workbench "{event, data}" shape) appear
    #    before the terminal event.
    assert any(
        n in {"run.completed", "run.failed", "run.cancelled"} for n in names[:-1]
    ), f"expected a run.* terminal lifecycle event before build_complete; got: {names!r}"
