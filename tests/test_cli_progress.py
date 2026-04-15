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
    renderer.next_action("agentlab eval run")

    assert len(lines) == 4
    payloads = [json.loads(line) for line in lines]
    assert payloads[0]["event"] == "phase_started"
    assert payloads[0]["phase"] == "build"
    assert payloads[1]["event"] == "artifact_written"
    assert payloads[1]["artifact"] == "config"
    assert payloads[-1]["event"] == "next_action"
    assert payloads[-1]["message"] == "agentlab eval run"


def test_progress_renderer_emits_harness_lifecycle_events() -> None:
    """Long-running commands should be able to stream checkpoints and recovery hints."""
    from cli.progress import ProgressRenderer

    lines: list[str] = []
    renderer = ProgressRenderer(output_format="stream-json", writer=lines.append)
    renderer.checkpoint("loop", path=".agentlab/loop_checkpoint.json", next_cycle=4)
    renderer.recovery_hint("loop", message="Resume from checkpoint", command="agentlab loop --resume")

    payloads = [json.loads(line) for line in lines]
    assert payloads[0]["event"] == "checkpoint"
    assert payloads[0]["phase"] == "loop"
    assert payloads[0]["path"] == ".agentlab/loop_checkpoint.json"
    assert payloads[0]["next_cycle"] == 4
    assert payloads[1]["event"] == "recovery_hint"
    assert payloads[1]["command"] == "agentlab loop --resume"


def test_progress_renderer_emits_task_lifecycle_events() -> None:
    """Task events should carry stable ids and structured progress values."""
    from cli.progress import ProgressRenderer

    lines: list[str] = []
    renderer = ProgressRenderer(output_format="stream-json", writer=lines.append)
    renderer.task_started("eval-cases", "Eval cases", total=4)
    renderer.task_progress("eval-cases", "Eval cases", "2/4 cases", current=2, total=4)
    renderer.task_completed("eval-cases", "Eval cases", current=4, total=4)

    payloads = [json.loads(line) for line in lines]
    assert [payload["event"] for payload in payloads] == [
        "task_started",
        "task_progress",
        "task_completed",
    ]
    assert payloads[0]["task_id"] == "eval-cases"
    assert payloads[1]["current"] == 2
    assert payloads[1]["total"] == 4
    assert payloads[1]["progress"] == 0.5
    assert payloads[2]["progress"] == 1.0


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


def test_eval_stream_json_emits_only_json_lines_and_warning_events(runner: CliRunner) -> None:
    """`eval run --stream-json` should not leak plain warning text into the stream."""
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["eval", "run", "--output-format", "stream-json"])

        assert result.exit_code == 0, result.output
        payloads = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        events = [payload["event"] for payload in payloads]
        assert "warning" in events
        assert any("mock" in payload.get("message", "").lower() for payload in payloads)


def test_eval_stream_json_emits_per_case_progress(runner: CliRunner) -> None:
    """Eval streams should expose per-case progress for loaders and workbench `/eval`."""
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["eval", "run", "--output-format", "stream-json"])

        assert result.exit_code == 0, result.output
        payloads = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        progress_events = [payload for payload in payloads if payload["event"] == "task_progress"]
        assert progress_events
        first = progress_events[0]
        last = progress_events[-1]
        assert first["task_id"] == "eval-cases"
        assert first["current"] >= 1
        assert first["total"] >= first["current"]
        assert 0 < first["progress"] <= 1
        assert last["current"] == last["total"]
        assert last["progress"] == 1.0
