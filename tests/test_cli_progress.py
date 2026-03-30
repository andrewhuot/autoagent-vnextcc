"""Tests for the shared Stream B progress/event renderer."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from runner import cli


@pytest.fixture
def runner() -> CliRunner:
    """Return a CLI runner."""
    return CliRunner()


def test_progress_renderer_stream_json_emits_standard_event_shapes() -> None:
    """Every emitted event should share the same core schema."""
    from cli.progress import ProgressRenderer

    lines: list[str] = []
    renderer = ProgressRenderer(output_format="stream-json", writer=lines.append)
    renderer.phase_started("build", message="Starting build")
    renderer.artifact_written("config", path="configs/v001.yaml")
    renderer.phase_completed("build", message="Build complete")
    renderer.next_action("autoagent eval run")

    assert len(lines) == 4
    payloads = [json.loads(line) for line in lines]
    assert payloads[0]["event"] == "phase_started"
    assert payloads[0]["phase"] == "build"
    assert payloads[1]["event"] == "artifact_written"
    assert payloads[1]["artifact"] == "config"
    assert payloads[-1]["event"] == "next_action"
    assert payloads[-1]["message"] == "autoagent eval run"


def test_build_stream_json_emits_progress_events(runner: CliRunner) -> None:
    """Long-running commands should expose the shared progress stream."""
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            [
                "build",
                "Build a customer support bot for billing questions",
                "--output-format",
                "stream-json",
            ],
        )

        assert result.exit_code == 0, result.output
        payloads = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        events = [payload["event"] for payload in payloads]
        assert "phase_started" in events
        assert "artifact_written" in events
        assert events[-1] == "next_action"
