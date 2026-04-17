"""CLI contract tests for runner.py."""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from agent.config.runtime import RuntimeConfig
from evals.fixtures.mock_data import mock_agent_response
from logger import ConversationRecord, ConversationStore
from observer.traces import TraceEvent, TraceStore
from runner import _build_eval_runner
from runner import _build_runtime_components
from runner import cli


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


def test_eval_show_fails_closed_on_corrupt_latest_eval_state(tmp_path, monkeypatch) -> None:
    """Corrupt latest eval JSON should surface as an explicit CLI failure, not an empty-state no-op."""
    monkeypatch.chdir(tmp_path)
    agentlab_dir = tmp_path / ".agentlab"
    agentlab_dir.mkdir()
    (agentlab_dir / "eval_results_latest.json").write_text('{"status": "ok"', encoding="utf-8")

    result = CliRunner().invoke(cli, ["eval", "show", "latest"])

    assert result.exit_code != 0
    assert "corrupt latest eval state" in result.output.lower()


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


def test_build_runtime_components_honor_workspace_mock_preference(tmp_path, monkeypatch) -> None:
    """Optimizer runtime assembly should honor workspace mode preference before env-key live setup."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    (tmp_path / ".agentlab").mkdir()
    (tmp_path / ".agentlab" / "workspace.json").write_text(
        '{"mode": "mock", "updated_by": "test"}\n',
        encoding="utf-8",
    )
    (tmp_path / "agentlab.yaml").write_text(
        yaml.safe_dump(
            {
                "optimizer": {
                    "use_mock": False,
                    "models": [
                        {
                            "provider": "openai",
                            "model": "gpt-test",
                            "api_key_env": "OPENAI_API_KEY",
                        }
                    ],
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    runtime, _eval_runner, proposer, _skill_engine, _adv, _autolearner = _build_runtime_components()

    assert runtime.optimizer.use_mock is True
    assert proposer.use_mock is True


def test_context_analyze_command_reads_trace_events_from_store(tmp_path, monkeypatch) -> None:
    """`context analyze` should read events from the trace store and summarize them."""
    trace_dir = tmp_path / ".agentlab"
    trace_dir.mkdir()
    store = TraceStore(db_path=str(trace_dir / "traces.db"))
    store.log_event(
        TraceEvent(
            event_id="evt-1",
            trace_id="trace-ctx-1",
            event_type="model_call",
            timestamp=1.0,
            invocation_id="inv-1",
            session_id="sess-1",
            agent_path="root/support",
            branch="v001",
            tokens_in=120,
            tokens_out=80,
            metadata={"tokens_available": 4000},
        )
    )

    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["context", "analyze", "--trace", "trace-ctx-1"])

    assert result.exit_code == 0
    assert "Context Analysis for trace trace-ctx-1" in result.output
    assert "Peak utilization" in result.output


def test_context_profiles_command_lists_first_class_profiles() -> None:
    """`context profiles` should expose the reusable context-engineering presets."""
    runner = CliRunner()
    result = runner.invoke(cli, ["context", "profiles"])

    assert result.exit_code == 0
    assert "Context Engineering Profiles" in result.output
    assert "lean" in result.output
    assert "balanced" in result.output
    assert "deep" in result.output


def test_context_preview_command_reads_config_and_prints_diagnostics(tmp_path) -> None:
    """`context preview` should show the assembled context budget for a config."""
    config_path = tmp_path / "agent.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "model": "claude-sonnet-4-5",
                "prompts": {
                    "root": "<role>Support.</role>\n<examples>Example one.</examples>",
                    "orders": "Verify order ID.",
                },
                "tools": {"orders_db": {"enabled": True, "description": "Lookup orders."}},
                "compaction": {"enabled": False},
                "memory_policy": {"preload": True, "max_entries": 100},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["context", "preview", "--config", str(config_path), "--profile", "lean"],
    )

    assert result.exit_code == 0
    assert "Context Assembly Preview" in result.output
    assert "Profile: lean" in result.output
    assert "instructions" in result.output
    assert "Diagnostics" in result.output


def test_scorer_test_command_scores_a_trace_from_persisted_spec(tmp_path, monkeypatch) -> None:
    """`scorer test` should load the persisted scorer spec and evaluate the requested trace."""
    trace_dir = tmp_path / ".agentlab"
    trace_dir.mkdir()
    store = TraceStore(db_path=str(trace_dir / "traces.db"))
    store.log_event(
        TraceEvent(
            event_id="evt-score-1",
            trace_id="trace-score-1",
            event_type="model_response",
            timestamp=1.0,
            invocation_id="inv-score-1",
            session_id="sess-score-1",
            agent_path="root/support",
            branch="v001",
            tokens_in=80,
            tokens_out=120,
            latency_ms=900.0,
            metadata={"tokens_available": 4000},
        )
    )

    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    create_result = runner.invoke(
        cli,
        [
            "scorer",
            "create",
            "accurate and respond in under 3 seconds",
            "--name",
            "trace_scorer",
        ],
    )
    assert create_result.exit_code == 0

    test_result = runner.invoke(
        cli,
        ["scorer", "test", "trace_scorer", "--trace", "trace-score-1", "--db", ".agentlab/traces.db"],
    )

    assert test_result.exit_code == 0
    assert "aggregate_score" in test_result.output


def test_registry_add_tools_maps_cli_name_to_tool_contract_key(tmp_path, monkeypatch) -> None:
    """`registry add tools` should pass the CLI name as `tool_name` to the registry."""
    tool_contract_path = tmp_path / "tool-contract.yaml"
    tool_contract_path.write_text(
        yaml.safe_dump(
            {
                "input_schema": {
                    "type": "object",
                    "properties": {"order_id": {"type": "string"}},
                },
                "output_schema": {
                    "type": "object",
                    "properties": {"status": {"type": "string"}},
                },
                "side_effect_class": "pure",
                "replay_mode": "deterministic_stub",
                "description": "Look up an order.",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    add_result = runner.invoke(
        cli,
        [
            "registry",
            "add",
            "tools",
            "order_lookup",
            "--file",
            str(tool_contract_path),
            "--db",
            "registry.db",
        ],
    )

    assert add_result.exit_code == 0
    assert "Registered tools/order_lookup -> v1" in add_result.output

    show_result = runner.invoke(
        cli,
        ["registry", "show", "tools", "order_lookup", "--version", "1", "--db", "registry.db"],
    )

    assert show_result.exit_code == 0
    assert '"tool_name": "order_lookup"' in show_result.output


def test_curriculum_generate_uses_conversation_failures(tmp_path, monkeypatch) -> None:
    """`curriculum generate` should synthesize a batch from failed conversations."""
    store = ConversationStore(db_path=str(tmp_path / "conversations.db"))
    store.log(
        ConversationRecord(
            conversation_id="conv-fail-1",
            session_id="sess-fail-1",
            user_message="My refund never arrived and I need help tracking it.",
            agent_response="No update.",
            tool_calls=[{"name": "order_lookup", "status": "error", "error": "missing order context"}],
            outcome="fail",
            error_message="missing order context",
            specialist_used="support",
            config_version="v001",
        )
    )

    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "curriculum",
            "generate",
            "--limit",
            "3",
            "--prompts-per-cluster",
            "2",
            "--output-dir",
            ".agentlab/curriculum",
        ],
    )

    assert result.exit_code == 0
    assert "Generated" in result.output

    list_result = runner.invoke(
        cli,
        ["curriculum", "list", "--limit", "5", "--output-dir", ".agentlab/curriculum"],
    )

    assert list_result.exit_code == 0
    assert "Curriculum Batches" in list_result.output
