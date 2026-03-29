"""CLI contract tests for runner.py."""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from agent.config.runtime import RuntimeConfig
from evals.fixtures.mock_data import mock_agent_response
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
    runtime.optimizer.use_mock = True
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


def test_build_eval_runner_uses_real_agent_when_provider_credentials_exist(tmp_path, monkeypatch) -> None:
    """The eval helper should wire a configured real agent when mock mode is disabled and keys exist."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    runtime = RuntimeConfig.model_validate(
        {
            "optimizer": {
                "use_mock": False,
                "strategy": "single",
                "models": [
                    {
                        "provider": "openai",
                        "model": "gpt-test",
                        "api_key_env": "OPENAI_API_KEY",
                    }
                ],
            },
            "eval": {
                "cache_enabled": False,
            },
        }
    )

    eval_runner = _build_eval_runner(
        runtime,
        trace_db_path=str(tmp_path / "traces.db"),
    )

    wrapped_agent = getattr(eval_runner.agent_fn, "__wrapped__", eval_runner.agent_fn)
    assert wrapped_agent is not mock_agent_response
    assert getattr(wrapped_agent, "__self__", None) is not None
    assert getattr(getattr(wrapped_agent, "__self__", None), "mock_mode", True) is False
    assert getattr(eval_runner, "mock_mode_messages", []) == []


def test_build_eval_runner_can_force_real_agent_even_when_runtime_requests_mock(tmp_path, monkeypatch) -> None:
    """A CLI override should allow real-agent eval wiring even if the runtime requests mock mode."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    runtime = RuntimeConfig.model_validate(
        {
            "optimizer": {
                "use_mock": True,
                "strategy": "single",
                "models": [
                    {
                        "provider": "openai",
                        "model": "gpt-test",
                        "api_key_env": "OPENAI_API_KEY",
                    }
                ],
            },
            "eval": {
                "cache_enabled": False,
            },
        }
    )

    eval_runner = _build_eval_runner(
        runtime,
        trace_db_path=str(tmp_path / "traces.db"),
        use_real_agent=True,
    )

    wrapped_agent = getattr(eval_runner.agent_fn, "__wrapped__", eval_runner.agent_fn)
    assert wrapped_agent is not mock_agent_response
    assert getattr(getattr(wrapped_agent, "__self__", None), "mock_mode", True) is False
    assert getattr(eval_runner, "mock_mode_messages", []) == []


def test_build_eval_runner_surfaces_mock_fallback_when_real_agent_cannot_start(tmp_path, monkeypatch) -> None:
    """Requesting the real agent without usable credentials should keep evals honest about mock fallback."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    runtime = RuntimeConfig.model_validate(
        {
            "optimizer": {
                "use_mock": False,
                "strategy": "single",
                "models": [
                    {
                        "provider": "openai",
                        "model": "gpt-test",
                        "api_key_env": "OPENAI_API_KEY",
                    }
                ],
            },
            "eval": {
                "cache_enabled": False,
            },
        }
    )

    eval_runner = _build_eval_runner(
        runtime,
        trace_db_path=str(tmp_path / "traces.db"),
        use_real_agent=True,
    )

    assert any("falling back to mock mode" in message.lower() for message in eval_runner.mock_mode_messages)
