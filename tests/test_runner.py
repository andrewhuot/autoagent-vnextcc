"""CLI contract tests for runner.py."""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from agent.config.runtime import RuntimeConfig
from observer.traces import TraceStore
from runner import cli
from runner import _build_eval_runner


def test_cli_exposes_run_group_with_expected_subcommands() -> None:
    """CLI should expose `run` group with all required workflow commands."""
    run_group = cli.commands.get("run")
    assert run_group is not None
    expected = {"agent", "observe", "optimize", "loop", "eval", "status"}
    assert expected.issubset(set(run_group.commands.keys()))


def test_run_status_command_executes_with_empty_state(tmp_path) -> None:
    """`run status` should succeed even with fresh DB/config/memory files."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run",
            "status",
            "--db",
            str(tmp_path / "conversations.db"),
            "--configs-dir",
            str(tmp_path / "configs"),
            "--memory-db",
            str(tmp_path / "memory.db"),
        ],
    )
    assert result.exit_code == 0
    assert "Conversations:" in result.output


def test_build_eval_runner_records_trace_events(tmp_path) -> None:
    """The runner-built eval harness should persist trace events for executed cases."""
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    (cases_dir / "smoke.yaml").write_text(
        yaml.safe_dump(
            {
                "cases": [
                    {
                        "id": "trace_smoke_001",
                        "category": "smoke",
                        "user_message": "Track my order please",
                        "expected_specialist": "orders",
                        "expected_behavior": "answer",
                        "expected_keywords": ["order"],
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    trace_db = tmp_path / "traces.db"

    runtime = RuntimeConfig()
    runtime.eval.cache_enabled = False

    eval_runner = _build_eval_runner(
        runtime,
        cases_dir=str(cases_dir),
        trace_db_path=str(trace_db),
    )

    score = eval_runner.run()
    assert score.total_cases == 1

    trace_store = TraceStore(db_path=str(trace_db))
    events = trace_store.get_recent_events(limit=20)
    event_types = {event.event_type for event in events}
    assert "state_delta" in event_types
    assert "model_call" in event_types
    assert "model_response" in event_types
