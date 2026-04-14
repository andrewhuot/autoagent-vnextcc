"""Tests for harness-oriented CLI status and recovery surfaces."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from optimizer.human_control import HumanControlStore
from optimizer.reliability import DeadLetterQueue, LoopCheckpoint, LoopCheckpointStore
from runner import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _seed_harness_attention_state(workspace: Path) -> None:
    """Create paused, recoverable, and failed-loop state for harness status assertions."""
    LoopCheckpointStore(str(workspace / ".agentlab" / "loop_checkpoint.json")).save(
        LoopCheckpoint(
            next_cycle=8,
            completed_cycles=7,
            plateau_count=2,
            last_status="running",
            last_cycle_started_at=1713060000.0,
            last_cycle_finished_at=1713060300.0,
        )
    )
    DeadLetterQueue(str(workspace / ".agentlab" / "dead_letters.db")).push(
        kind="loop_cycle",
        payload={"cycle": 7},
        error="timeout while evaluating candidate",
    )
    HumanControlStore(path=str(workspace / ".agentlab" / "human_control.json")).pause()


def test_harness_status_json_summarizes_recovery_state(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`agentlab harness status --json` should expose lifecycle, evidence, and recovery hints."""
    workspace = tmp_path / "harness-workspace"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--no-synthetic-data"])
    assert init_result.exit_code == 0, init_result.output
    _seed_harness_attention_state(workspace)

    monkeypatch.chdir(workspace)
    result = runner.invoke(cli, ["harness", "status", "--json"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    data = envelope["data"]
    assert data["health"] == "attention"
    assert data["loop"]["status"] == "recoverable"
    assert data["loop"]["next_cycle"] == 8
    assert data["control"]["paused"] is True
    assert data["dead_letters"]["count"] == 1
    assert data["evidence"]["checkpoint_path"].endswith(".agentlab/loop_checkpoint.json")
    assert "agentlab loop resume" in data["next_actions"]
    assert "agentlab loop --resume" in data["next_actions"]
    assert envelope["next"] == "agentlab loop resume"


def test_harness_status_text_gives_operator_next_steps(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "harness-text-workspace"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--no-synthetic-data"])
    assert init_result.exit_code == 0, init_result.output
    _seed_harness_attention_state(workspace)

    monkeypatch.chdir(workspace)
    result = runner.invoke(cli, ["harness", "status"])

    assert result.exit_code == 0, result.output
    assert "Harness Status" in result.output
    assert "Health:     attention" in result.output
    assert "Loop:       recoverable" in result.output
    assert "Dead letters: 1 pending" in result.output
    assert "Controls:   paused" in result.output
    assert "Resume:     agentlab loop --resume" in result.output
    assert "Next step:  agentlab loop resume" in result.output


def test_harness_status_text_reports_no_recovery_when_ready(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "ready-harness-workspace"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--no-synthetic-data"])
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)
    result = runner.invoke(cli, ["harness", "status"])

    assert result.exit_code == 0, result.output
    assert "Health:     ready" in result.output
    assert "Recovery:" in result.output
    assert "None needed" in result.output
    assert "Next step:  agentlab optimize --continuous" in result.output


def test_fresh_running_checkpoint_avoids_unsafe_resume_guidance(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "fresh-running-workspace"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--no-synthetic-data"])
    assert init_result.exit_code == 0, init_result.output
    now = time.time()
    LoopCheckpointStore(str(workspace / ".agentlab" / "loop_checkpoint.json")).save(
        LoopCheckpoint(
            next_cycle=3,
            completed_cycles=2,
            last_status="running",
            last_cycle_started_at=now,
            last_cycle_finished_at=now,
        )
    )

    monkeypatch.chdir(workspace)
    result = runner.invoke(cli, ["harness", "status", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)["data"]
    assert data["health"] == "attention"
    assert data["loop"]["status"] == "running_or_recoverable"
    assert "agentlab loop --resume" not in data["next_actions"]
    assert data["next_actions"][0] == "agentlab harness status --json"


def test_stale_running_checkpoint_allows_resume_guidance(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "stale-running-workspace"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--no-synthetic-data"])
    assert init_result.exit_code == 0, init_result.output
    stale = time.time() - 3600
    LoopCheckpointStore(str(workspace / ".agentlab" / "loop_checkpoint.json")).save(
        LoopCheckpoint(
            next_cycle=4,
            completed_cycles=3,
            last_status="running",
            last_cycle_started_at=stale,
            last_cycle_finished_at=stale,
        )
    )

    monkeypatch.chdir(workspace)
    result = runner.invoke(cli, ["harness", "status", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)["data"]
    assert data["loop"]["status"] == "recoverable"
    assert "agentlab loop --resume" in data["next_actions"]


def test_status_verbose_includes_harness_summary(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "status-harness-workspace"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--no-synthetic-data"])
    assert init_result.exit_code == 0, init_result.output
    _seed_harness_attention_state(workspace)

    monkeypatch.chdir(workspace)
    result = runner.invoke(cli, ["status", "--verbose"])

    assert result.exit_code == 0, result.output
    assert "Harness:" in result.output
    assert "attention" in result.output
    assert "Recovery:" in result.output
    assert "agentlab loop resume" in result.output


def test_doctor_json_includes_harness_readiness(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "doctor-harness-workspace"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--no-synthetic-data"])
    assert init_result.exit_code == 0, init_result.output
    _seed_harness_attention_state(workspace)

    monkeypatch.chdir(workspace)
    result = runner.invoke(cli, ["doctor", "--json"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    harness = envelope["data"]["harness"]
    assert harness["health"] == "attention"
    assert harness["control"]["paused"] is True
    assert harness["dead_letters"]["count"] == 1


def test_loop_stream_json_outputs_only_parseable_events(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "loop-stream-workspace"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--mode", "mock"])
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)
    result = runner.invoke(
        cli,
        [
            "loop",
            "--max-cycles",
            "1",
            "--delay",
            "0",
            "--no-resume",
            "--output-format",
            "stream-json",
        ],
    )

    assert result.exit_code == 0, result.output
    payloads = [json.loads(line) for line in result.output.splitlines() if line.strip()]
    events = [payload["event"] for payload in payloads]
    assert "checkpoint" in events
    assert events[-1] == "next_action"


def test_loop_budget_rejection_stream_json_is_parseable(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "loop-budget-stream-workspace"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--mode", "mock"])
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)
    result = runner.invoke(
        cli,
        [
            "loop",
            "--max-budget-usd",
            "0",
            "--output-format",
            "stream-json",
        ],
    )

    assert result.exit_code == 0, result.output
    payloads = [json.loads(line) for line in result.output.splitlines() if line.strip()]
    assert payloads[-1]["event"] == "warning"
    assert "Budget guard reached" in payloads[-1]["message"]


def test_loop_budget_rejection_json_uses_standard_envelope(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "loop-budget-json-workspace"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--mode", "mock"])
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)
    result = runner.invoke(
        cli,
        [
            "loop",
            "--max-budget-usd",
            "0",
            "--output-format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["status"] == "error"
    assert "Budget guard reached" in envelope["data"]["message"]
    assert envelope["next"] == "agentlab usage"


def test_loop_resume_updates_root_control_from_nested_workspace(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "nested-control-workspace"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--no-synthetic-data"])
    assert init_result.exit_code == 0, init_result.output
    root_control_path = workspace / ".agentlab" / "human_control.json"
    HumanControlStore(path=str(root_control_path)).pause()
    nested = workspace / "src" / "deep"
    nested.mkdir(parents=True)

    monkeypatch.chdir(nested)
    status_result = runner.invoke(cli, ["harness", "status", "--json"])
    resume_result = runner.invoke(cli, ["loop", "resume"])

    assert status_result.exit_code == 0, status_result.output
    assert json.loads(status_result.output)["data"]["control"]["paused"] is True
    assert resume_result.exit_code == 0, resume_result.output
    root_state = json.loads(root_control_path.read_text(encoding="utf-8"))
    assert root_state["paused"] is False
    assert not (nested / ".agentlab" / "human_control.json").exists()
