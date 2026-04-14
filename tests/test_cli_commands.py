"""Tests for the enhanced CLI command structure."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from click.testing import CliRunner

import runner as runner_module
from runner import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def _env_without_api_keys() -> dict[str, str]:
    """Return a process environment with provider credentials stripped for deterministic CLI tests."""
    env = dict(os.environ)
    env["OPENAI_API_KEY"] = ""
    env["ANTHROPIC_API_KEY"] = ""
    env["GOOGLE_API_KEY"] = ""
    return env


class TestCLIStructure:
    """Verify the CLI has all expected commands and subcommands."""

    def test_root_group_exists(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "AgentLab VNextCC" in result.output

    def test_version_flag(self, runner):
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "1.0.0" in result.output

    def test_eval_group_exists(self, runner):
        result = runner.invoke(cli, ["eval", "--help"])
        assert result.exit_code == 0
        assert "run" in result.output
        assert "results" in result.output
        assert "list" in result.output

    def test_config_group_exists(self, runner):
        result = runner.invoke(cli, ["config", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "show" in result.output
        assert "diff" in result.output

    def test_instruction_group_exists(self, runner):
        result = runner.invoke(cli, ["instruction", "--help"])
        assert result.exit_code == 0
        for command_name in ["show", "edit", "validate", "generate", "migrate"]:
            assert command_name in result.output

    def test_top_level_commands(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        # Commands visible in help (primary + secondary)
        for cmd in ["build", "eval", "optimize", "config", "deploy", "status"]:
            assert cmd in result.output, f"Missing command: {cmd}"
        # Commands that exist but are hidden from help — verify via cli.commands dict
        for cmd in ["init", "loop", "logs", "server", "full-auto", "changes"]:
            assert cmd in cli.commands, f"Missing command in registry: {cmd}"

    def test_legacy_run_group_hidden(self, runner):
        """Legacy run group should exist but be hidden from help."""
        result = runner.invoke(cli, ["--help"])
        # 'run' should not appear as a visible command in help
        # (it's hidden=True)
        # But it should still work
        result2 = runner.invoke(cli, ["run", "--help"])
        assert result2.exit_code == 0

    def test_adk_status_reports_parse_errors_without_traceback(self, runner, tmp_path):
        """`adk status` should explain invalid ADK paths without a traceback."""
        empty_agent_dir = tmp_path / "not-an-adk-agent"
        empty_agent_dir.mkdir()

        result = runner.invoke(cli, ["adk", "status", str(empty_agent_dir)])

        assert result.exit_code != 0
        assert "ADK status failed" in result.output
        assert "agent.py not found" in result.output


class TestBrandedBanner:
    """Verify branded banner output on key startup surfaces."""

    def test_root_help_shows_branded_banner(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Experiment. Evaluate. Refine." in result.output
        assert "AgentLab" in result.output

    def test_root_help_suppresses_banner_with_no_banner_flag(self, runner):
        result = runner.invoke(cli, ["--no-banner", "--help"])
        assert result.exit_code == 0
        assert "Experiment. Evaluate. Refine." not in result.output

    def test_server_shows_banner_before_startup_message(self, runner, monkeypatch):
        captured: dict[str, object] = {}

        def fake_run(app: str, host: str, port: int, reload: bool) -> None:
            captured["app"] = app
            captured["host"] = host
            captured["port"] = port
            captured["reload"] = reload

        monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))

        result = runner.invoke(cli, ["server", "--host", "127.0.0.1", "--port", "8123", "--reload"])

        assert result.exit_code == 0
        assert "Experiment. Evaluate. Refine." in result.output
        assert "Starting AgentLab VNextCC server on 127.0.0.1:8123" in result.output
        assert captured == {
            "app": "api.server:app",
            "host": "127.0.0.1",
            "port": 8123,
            "reload": True,
        }

    def test_server_quiet_flag_suppresses_banner(self, runner, monkeypatch):
        def fake_run(app: str, host: str, port: int, reload: bool) -> None:
            del app, host, port, reload

        monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))

        result = runner.invoke(cli, ["server", "--quiet"])

        assert result.exit_code == 0
        assert "Experiment. Evaluate. Refine." not in result.output

    def test_server_accepts_explicit_workspace_path(self, runner, tmp_path, monkeypatch):
        workspace = tmp_path / "server-workspace"
        init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--no-synthetic-data"])
        assert init_result.exit_code == 0, init_result.output

        captured: dict[str, object] = {}

        def fake_run(app: str, host: str, port: int, reload: bool) -> None:
            captured["app"] = app
            captured["host"] = host
            captured["port"] = port
            captured["reload"] = reload

        monkeypatch.delenv("AGENTLAB_WORKSPACE", raising=False)
        monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))

        result = runner.invoke(cli, ["server", "--workspace", str(workspace), "--port", "8124"])

        try:
            assert result.exit_code == 0, result.output
            assert "Workspace:" in result.output
            assert str(workspace.resolve()) in result.output
            assert os.environ["AGENTLAB_WORKSPACE"] == str(workspace.resolve())
            assert captured == {
                "app": "api.server:app",
                "host": "0.0.0.0",
                "port": 8124,
                "reload": False,
            }
        finally:
            monkeypatch.delenv("AGENTLAB_WORKSPACE", raising=False)

    def test_server_rejects_missing_explicit_workspace_path(self, runner, tmp_path, monkeypatch):
        captured: dict[str, object] = {}

        def fake_run(app: str, host: str, port: int, reload: bool) -> None:
            captured["app"] = app
            del host, port, reload

        monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))

        result = runner.invoke(cli, ["server", "--workspace", str(tmp_path / "missing")])

        assert result.exit_code != 0
        assert "Workspace path does not exist" in result.output
        assert captured == {}


class TestInitCommand:
    def test_init_creates_structure(self, runner, tmp_dir):
        result = runner.invoke(cli, ["init", "--dir", tmp_dir])
        assert result.exit_code == 0
        assert "Initialized" in result.output
        assert (Path(tmp_dir) / "configs").is_dir()
        assert (Path(tmp_dir) / "evals" / "cases").is_dir()

    def test_init_copies_base_config(self, runner, tmp_dir):
        result = runner.invoke(cli, ["init", "--dir", tmp_dir])
        assert result.exit_code == 0
        assert (Path(tmp_dir) / "configs" / "v001_base.yaml").exists()

    def test_init_copies_eval_cases(self, runner, tmp_dir):
        result = runner.invoke(cli, ["init", "--dir", tmp_dir])
        assert result.exit_code == 0
        cases_dir = Path(tmp_dir) / "evals" / "cases"
        yaml_files = list(cases_dir.glob("*.yaml"))
        assert len(yaml_files) > 0


class TestInstructionCommands:
    def test_instruction_show_and_validate_use_active_workspace_instruction(self, runner, tmp_path, monkeypatch):
        workspace = tmp_path / "instruction-workspace"
        init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--no-synthetic-data"])
        assert init_result.exit_code == 0, init_result.output

        config_path = workspace / "configs" / "v001.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        config["prompts"]["root"] = """
<role>Customer support specialist.</role>
<persona>
  <primary_goal>Resolve support issues.</primary_goal>
  Be concise and helpful.
</persona>
<constraints>
  1. Verify account details before sensitive actions.
</constraints>
<taskflow>
  <subtask name="Support">
    <step name="Answer">
      <trigger>User requests support.</trigger>
      <action>Respond with the next best step.</action>
    </step>
  </subtask>
</taskflow>
<examples>
</examples>
""".strip()
        config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

        monkeypatch.chdir(workspace)

        show_result = runner.invoke(cli, ["instruction", "show"])
        assert show_result.exit_code == 0, show_result.output
        assert "<role>Customer support specialist.</role>" in show_result.output

        validate_result = runner.invoke(cli, ["instruction", "validate"])
        assert validate_result.exit_code == 0, validate_result.output
        assert "valid" in validate_result.output.lower()

    def test_instruction_migrate_rewrites_plain_text_instruction_as_xml(self, runner, tmp_path, monkeypatch):
        workspace = tmp_path / "migrate-workspace"
        init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--no-synthetic-data"])
        assert init_result.exit_code == 0, init_result.output

        config_path = workspace / "configs" / "v001.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        config["prompts"]["root"] = (
            "You are a customer support assistant. "
            "Help with refunds and tracking. "
            "Verify identity before changing an order."
        )
        config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

        monkeypatch.chdir(workspace)
        result = runner.invoke(cli, ["instruction", "migrate"])

        assert result.exit_code == 0, result.output
        migrated = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert "<role>" in migrated["prompts"]["root"]
        assert "<taskflow>" in migrated["prompts"]["root"]

    def test_instruction_generate_can_apply_generated_xml_to_workspace(self, runner, tmp_path, monkeypatch):
        workspace = tmp_path / "generate-workspace"
        init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--no-synthetic-data"])
        assert init_result.exit_code == 0, init_result.output

        monkeypatch.chdir(workspace)
        result = runner.invoke(
            cli,
            [
                "instruction",
                "generate",
                "--brief",
                "Create a customer support agent for order tracking and refunds.",
                "--apply",
            ],
        )

        assert result.exit_code == 0, result.output
        config_path = workspace / "configs" / "v001.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert "<role>" in config["prompts"]["root"]
        assert "<constraints>" in config["prompts"]["root"]
        assert "<examples>" in config["prompts"]["root"]


class TestJourneyCommands:
    """Tests for CLI commands required by the end-to-end user journey."""

    def test_build_json_includes_required_artifact_sections(self, runner):
        with runner.isolated_filesystem():
            result = runner.invoke(
                cli,
                [
                    "build",
                    "Build a customer service agent for order tracking with Shopify integration",
                    "--json",
                ],
            )
            assert result.exit_code == 0, result.output
            payload = json.loads(result.output)
            for key in ["intents", "tools", "guardrails", "skills", "integration_templates"]:
                assert key in payload

    def test_build_generates_config_and_eval_handoff_files(self, runner):
        with runner.isolated_filesystem():
            result = runner.invoke(
                cli,
                ["build", "Build a customer service agent for order tracking with Shopify integration"],
            )
            assert result.exit_code == 0, result.output
            assert Path("configs").is_dir()
            assert list(Path("configs").glob("v*_built_*.yaml"))
            assert Path("evals/cases/generated_build.yaml").exists()

    def test_build_billing_prompt_generates_billing_config_and_evals(self, runner):
        with runner.isolated_filesystem():
            result = runner.invoke(
                cli,
                [
                    "build",
                    (
                        "Build a Verizon-like phone-company billing support agent that explains "
                        "bills, plan charges, fees, surcharges, device payments, promo credits, "
                        "roaming charges, and autopay discounts."
                    ),
                ],
            )

            assert result.exit_code == 0, result.output
            config_path = next(Path("configs").glob("v*_built_*.yaml"))
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            root_prompt = config["prompts"]["root"].lower()
            support_rule = next(
                rule for rule in config["routing"]["rules"] if rule["specialist"] == "support"
            )
            order_rule = next(
                rule for rule in config["routing"]["rules"] if rule["specialist"] == "orders"
            )
            assert "billing" in root_prompt
            assert "autopay" in root_prompt
            assert "billing" in support_rule["keywords"]
            assert "autopay" in support_rule["keywords"]
            assert "billing" not in order_rule["keywords"]
            generated_cases = yaml.safe_load(Path("evals/cases/generated_build.yaml").read_text(encoding="utf-8"))
            messages = " ".join(case["user_message"].lower() for case in generated_cases["cases"])
            assert "wireless bill" in messages
            assert "promo credit" in messages

    def test_changes_group_exists_and_lists_cards(self, runner):
        result_help = runner.invoke(cli, ["changes", "--help"])
        assert result_help.exit_code == 0
        assert "list" in result_help.output
        assert "approve" in result_help.output

        with runner.isolated_filesystem():
            result_list = runner.invoke(cli, ["changes", "list"])
            assert result_list.exit_code == 0, result_list.output
            assert "No pending change cards." in result_list.output

    def test_deploy_supports_cx_target_without_remote_credentials(self, runner):
        with runner.isolated_filesystem():
            init_result = runner.invoke(cli, ["init", "--dir", "."])
            assert init_result.exit_code == 0, init_result.output

            result = runner.invoke(cli, ["deploy", "--target", "cx-studio"])
            assert result.exit_code == 0, result.output
            assert "CX export package" in result.output
            assert list(Path(".agentlab").glob("cx_export_v*.json"))


class TestEvalCommands:
    def test_eval_run_default(self, runner):
        result = runner.invoke(cli, ["eval", "run"], env=_env_without_api_keys())
        assert result.exit_code == 0
        assert "Composite:" in result.output

    def test_eval_run_with_category(self, runner):
        result = runner.invoke(cli, ["eval", "run", "--category", "happy_path"], env=_env_without_api_keys())
        assert result.exit_code == 0
        assert "Category: happy_path" in result.output

    def test_eval_run_with_output(self, runner, tmp_dir):
        output_file = os.path.join(tmp_dir, "results.json")
        result = runner.invoke(cli, ["eval", "run", "--output", output_file], env=_env_without_api_keys())
        assert result.exit_code == 0
        assert Path(output_file).exists()
        data = json.loads(Path(output_file).read_text())
        assert "scores" in data
        assert "results" in data

    def test_eval_list_reads_workspace_latest_snapshot(self, runner, tmp_path, monkeypatch):
        """`eval list` should include the canonical workspace latest snapshot under `.agentlab/`."""
        workspace = tmp_path / "eval-list-workspace"
        init_result = runner.invoke(cli, ["init", "--dir", str(workspace)])
        assert init_result.exit_code == 0, init_result.output

        monkeypatch.chdir(workspace)
        latest_path = workspace / ".agentlab" / "eval_results_latest.json"
        latest_path.write_text(
            json.dumps(
                {
                    "timestamp": "2026-03-31T14:30:00+00:00",
                    "scores": {"composite": 0.8123},
                    "passed": 2,
                    "total": 3,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        result = runner.invoke(cli, ["eval", "list"])

        assert result.exit_code == 0, result.output
        assert "eval_results_latest.json" in result.output
        assert "0.8123" in result.output
        assert "2/3 passed" in result.output

    def test_eval_results_from_file(self, runner, tmp_dir):
        # First create a results file
        output_file = os.path.join(tmp_dir, "results.json")
        runner.invoke(cli, ["eval", "run", "--output", output_file], env=_env_without_api_keys())
        # Then read it
        result = runner.invoke(cli, ["eval", "results", "--file", output_file])
        assert result.exit_code == 0
        assert "Composite:" in result.output

    def test_eval_compare_help_mentions_pairwise_summary(self, runner):
        """`eval compare --help` should call out the pairwise winner summary it renders."""
        result = runner.invoke(cli, ["eval", "compare", "--help"])

        assert result.exit_code == 0, result.output
        assert "pairwise" in result.output.lower()
        assert "winner" in result.output.lower()

    def test_eval_results_help_mentions_results_explorer(self, runner):
        """`eval results --help` should connect the CLI view to the Results Explorer surface."""
        result = runner.invoke(cli, ["eval", "results", "--help"])

        assert result.exit_code == 0, result.output
        assert "Results Explorer" in result.output

    def test_eval_list_empty(self, runner, tmp_dir):
        result = runner.invoke(cli, ["eval", "list"])
        # May or may not find files depending on cwd
        assert result.exit_code == 0

    def test_eval_run_real_agent_flag_passes_override_to_builder(self, runner, monkeypatch):
        """`eval run --real-agent` should request the real-agent eval harness path."""
        captured: dict[str, bool] = {}

        fake_score = SimpleNamespace(
            quality=0.8,
            safety=1.0,
            latency=0.9,
            cost=0.95,
            composite=0.87,
            confidence_intervals={},
            safety_failures=0,
            total_cases=1,
            passed_cases=1,
            total_tokens=0,
            estimated_cost_usd=0.0,
            warnings=[],
            provenance={},
            run_id="run-test",
            results=[],
        )

        class _FakeEvalRunner:
            mock_mode_messages: list[str] = []

            def run(self, config=None, dataset_path=None, split="all"):
                return fake_score

        def fake_build_eval_runner(
            runtime,
            *,
            cases_dir=None,
            trace_db_path=None,
            use_real_agent=False,
            default_agent_config=None,
        ):
            del runtime, cases_dir, trace_db_path, default_agent_config
            captured["use_real_agent"] = use_real_agent
            return _FakeEvalRunner()

        monkeypatch.setattr(runner_module, "_build_eval_runner", fake_build_eval_runner)

        result = runner.invoke(cli, ["eval", "run", "--real-agent", "--json"])

        assert result.exit_code == 0
        assert captured["use_real_agent"] is True

    def test_eval_run_json_points_to_optimize_next(self, runner, monkeypatch):
        """JSON output should guide operators to the supported Optimize command."""
        fake_score = SimpleNamespace(
            quality=0.8,
            safety=1.0,
            latency=0.9,
            cost=0.95,
            composite=0.87,
            confidence_intervals={},
            safety_failures=0,
            total_cases=1,
            passed_cases=1,
            total_tokens=0,
            estimated_cost_usd=0.0,
            warnings=[],
            provenance={},
            run_id="run-next-optimize",
            results=[],
        )

        class _FakeEvalRunner:
            mock_mode_messages: list[str] = []

            def run(self, config=None, dataset_path=None, split="all"):
                del config, dataset_path, split
                return fake_score

        monkeypatch.setattr(
            runner_module,
            "_build_eval_runner",
            lambda *args, **kwargs: _FakeEvalRunner(),
        )
        monkeypatch.setattr(runner_module, "_warn_mock_modes", lambda **kwargs: None)

        result = runner.invoke(cli, ["eval", "run", "--json"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["next"] == "agentlab optimize --cycles 3"
        assert "improve" not in payload["next"]

    def test_eval_run_prefers_workspace_mock_mode_over_live_runtime_config(
        self,
        runner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Workspace mode preference should force evals into mock mode before live-provider detection."""
        workspace = tmp_path / "workspace"
        init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--mode", "live"])
        assert init_result.exit_code == 0, init_result.output

        monkeypatch.chdir(workspace)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        mode_result = runner.invoke(cli, ["mode", "set", "mock"])
        assert mode_result.exit_code == 0, mode_result.output

        captured: dict[str, bool] = {}

        fake_score = SimpleNamespace(
            quality=0.8,
            safety=1.0,
            latency=0.9,
            cost=0.95,
            composite=0.87,
            confidence_intervals={},
            safety_failures=0,
            total_cases=1,
            passed_cases=1,
            total_tokens=0,
            estimated_cost_usd=0.0,
            warnings=[],
            provenance={},
            run_id="run-mode-preference",
            results=[],
        )

        class _FakeEvalRunner:
            mock_mode_messages: list[str] = []

            def run(self, config=None, dataset_path=None, split="all"):
                del config, dataset_path, split
                return fake_score

        def fake_build_eval_runner(
            runtime,
            *,
            cases_dir=None,
            trace_db_path=None,
            use_real_agent=False,
            default_agent_config=None,
        ):
            del cases_dir, trace_db_path, use_real_agent, default_agent_config
            captured["use_mock"] = runtime.optimizer.use_mock
            return _FakeEvalRunner()

        monkeypatch.setattr(runner_module, "_build_eval_runner", fake_build_eval_runner)
        monkeypatch.setattr(runner_module, "_warn_mock_modes", lambda **kwargs: None)

        result = runner.invoke(cli, ["eval", "run"])

        assert result.exit_code == 0, result.output
        assert captured["use_mock"] is True

    def test_eval_run_accepts_instruction_override_file(self, runner, tmp_path, monkeypatch):
        """`eval run --instruction-overrides` should pass XML section overrides into the agent config."""
        workspace = tmp_path / "eval-override-workspace"
        init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--no-synthetic-data"])
        assert init_result.exit_code == 0, init_result.output

        override_path = workspace / "instruction_override.yaml"
        override_path.write_text(
            yaml.safe_dump(
                {
                    "constraints": [
                        "Always confirm the cancellation reason before taking action.",
                    ]
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        monkeypatch.chdir(workspace)
        captured: dict[str, object] = {}

        fake_score = SimpleNamespace(
            quality=0.8,
            safety=1.0,
            latency=0.9,
            cost=0.95,
            composite=0.87,
            confidence_intervals={},
            safety_failures=0,
            total_cases=1,
            passed_cases=1,
            total_tokens=0,
            estimated_cost_usd=0.0,
            warnings=[],
            provenance={},
            run_id="run-override",
            results=[],
        )

        class _FakeEvalRunner:
            mock_mode_messages: list[str] = []

            def run(self, config=None, dataset_path=None, split="all"):
                del dataset_path, split
                captured["config"] = config
                return fake_score

        monkeypatch.setattr(
            runner_module,
            "_build_eval_runner",
            lambda *args, **kwargs: _FakeEvalRunner(),
        )
        monkeypatch.setattr(runner_module, "_warn_mock_modes", lambda **kwargs: None)

        result = runner.invoke(
            cli,
            ["eval", "run", "--instruction-overrides", str(override_path), "--json"],
        )

        assert result.exit_code == 0, result.output
        assert isinstance(captured["config"], dict)
        assert captured["config"]["_instruction_overrides"]["constraints"] == [
            "Always confirm the cancellation reason before taking action.",
        ]


class TestStatusCommand:
    def test_status_with_empty_db(self, runner, tmp_dir):
        db_path = os.path.join(tmp_dir, "test.db")
        configs_dir = os.path.join(tmp_dir, "configs")
        memory_db = os.path.join(tmp_dir, "memory.db")
        os.makedirs(configs_dir, exist_ok=True)

        result = runner.invoke(cli, [
            "status",
            "--db", db_path,
            "--configs-dir", configs_dir,
            "--memory-db", memory_db,
        ])
        assert result.exit_code == 0
        assert "AgentLab Status" in result.output


class TestLogsCommand:
    def test_logs_empty_db(self, runner, tmp_dir):
        db_path = os.path.join(tmp_dir, "test.db")
        result = runner.invoke(cli, ["logs", "--db", db_path])
        assert result.exit_code == 0
        assert "No conversations found" in result.output


class TestConfigCommands:
    def test_config_list_empty(self, runner, tmp_dir):
        configs_dir = os.path.join(tmp_dir, "configs")
        os.makedirs(configs_dir, exist_ok=True)
        result = runner.invoke(cli, ["config", "list", "--configs-dir", configs_dir])
        assert result.exit_code == 0
        assert "No config versions" in result.output


class TestDoctorCommand:
    def test_doctor_runs_without_error(self, runner):
        """doctor command exits cleanly and prints the header."""
        result = runner.invoke(cli, ["doctor"])
        assert result.exit_code == 0
        assert "AgentLab Doctor" in result.output
        assert "API Keys" in result.output
        assert "Data Stores" in result.output

    def test_doctor_shows_mock_warning_when_use_mock_true(self, runner, tmp_dir):
        """doctor reports mock-mode warning when use_mock: true."""
        config_file = os.path.join(tmp_dir, "agentlab_mock.yaml")
        Path(config_file).write_text("optimizer:\n  use_mock: true\n", encoding="utf-8")
        result = runner.invoke(cli, ["doctor", "--config", config_file])
        assert result.exit_code == 0
        assert "Enabled" in result.output
        assert "use_mock" in result.output

    def test_doctor_no_mock_warning_when_use_mock_false(self, runner, tmp_dir):
        """doctor does not warn about mock mode when use_mock: false."""
        config_file = os.path.join(tmp_dir, "agentlab_real.yaml")
        Path(config_file).write_text("optimizer:\n  use_mock: false\n", encoding="utf-8")
        result = runner.invoke(cli, ["doctor", "--config", config_file])
        assert result.exit_code == 0
        assert "Disabled" in result.output

    def test_doctor_shows_api_key_set(self, runner, tmp_dir):
        """doctor shows OPENAI_API_KEY as Set when the env var is present."""
        config_file = os.path.join(tmp_dir, "agentlab.yaml")
        Path(config_file).write_text("optimizer:\n  use_mock: false\n", encoding="utf-8")
        env = {**os.environ, "OPENAI_API_KEY": "sk-test-key"}
        result = runner.invoke(cli, ["doctor", "--config", config_file], env=env)
        assert result.exit_code == 0
        assert "OPENAI_API_KEY" in result.output
        assert "Set" in result.output

    def test_doctor_shows_api_key_not_set(self, runner, tmp_dir):
        """doctor shows OPENAI_API_KEY as Not set when the env var is absent."""
        config_file = os.path.join(tmp_dir, "agentlab.yaml")
        Path(config_file).write_text("optimizer:\n  use_mock: false\n", encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
        result = runner.invoke(cli, ["doctor", "--config", config_file], env=env)
        assert result.exit_code == 0
        assert "OPENAI_API_KEY" in result.output
        assert "Not set" in result.output

    def test_doctor_reports_runtime_provider_ready_without_provider_registry(self, runner, tmp_dir):
        """doctor should treat runtime-configured providers as ready even before registry setup."""
        config_file = os.path.join(tmp_dir, "agentlab.yaml")
        Path(config_file).write_text("optimizer:\n  use_mock: false\n", encoding="utf-8")
        env = {
            **os.environ,
            "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "GOOGLE_API_KEY": "g-test-key",
        }

        result = runner.invoke(cli, ["doctor", "--config", config_file], env=env)

        assert result.exit_code == 0
        assert "google:" in result.output.lower()
        assert "gemini-2.5-pro configured" in result.output
        assert "live probe not run" in result.output

    def test_doctor_status_line_reports_ready_workspace(self, runner, tmp_dir, monkeypatch):
        """Mock-mode workspaces should still report a healthy doctor summary."""
        workspace = Path(tmp_dir) / "doctor-workspace"
        init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--mode", "mock"])
        assert init_result.exit_code == 0, init_result.output
        monkeypatch.chdir(workspace)

        config_file = workspace / "agentlab.yaml"
        env = {
            k: v for k, v in os.environ.items()
            if k not in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")
        }
        result = runner.invoke(cli, ["doctor", "--config", str(config_file)], env=env)
        assert result.exit_code == 0
        assert "Status: All checks passed" in result.output

    def test_doctor_reports_coordinator_section(self, runner, tmp_dir):
        """doctor prints the new Coordinator section with worker mode + model rows."""
        config_file = os.path.join(tmp_dir, "agentlab.yaml")
        Path(config_file).write_text("optimizer:\n  use_mock: false\n", encoding="utf-8")
        result = runner.invoke(cli, ["doctor", "--config", config_file])
        assert result.exit_code == 0
        assert "Coordinator" in result.output
        assert "Worker mode:" in result.output
        assert "Coordinator model:" in result.output
        assert "Worker model:" in result.output
        assert "Credentials:" in result.output

    def test_doctor_coordinator_section_shows_resolved_models(self, runner, tmp_dir, monkeypatch):
        """doctor surfaces the configured harness.models so operators see live mode routing."""
        workspace = Path(tmp_dir) / "coord-workspace"
        init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--mode", "mock"])
        assert init_result.exit_code == 0, init_result.output
        monkeypatch.chdir(workspace)

        config_file = workspace / "agentlab.yaml"
        existing = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
        existing.setdefault("harness", {}).setdefault("models", {})
        existing["harness"]["models"]["coordinator"] = {
            "provider": "anthropic",
            "model": "claude-opus-4-6",
            "api_key_env": "ANTHROPIC_API_KEY",
        }
        existing["harness"]["models"]["worker"] = {
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
            "api_key_env": "ANTHROPIC_API_KEY",
        }
        config_file.write_text(yaml.safe_dump(existing), encoding="utf-8")

        env = {
            **os.environ,
            "ANTHROPIC_API_KEY": "sk-ant-test",
        }
        result = runner.invoke(cli, ["doctor", "--config", str(config_file)], env=env)
        assert result.exit_code == 0, result.output
        assert "claude-opus-4-6" in result.output
        assert "claude-sonnet-4-6" in result.output
        assert "harness.models.coordinator" in result.output
        assert "harness.models.worker" in result.output

    def test_eval_run_prints_mock_warning(self, runner):
        """eval run warns when the harness falls back to mock mode."""
        result = runner.invoke(cli, ["eval", "run"], env=_env_without_api_keys())
        assert result.exit_code == 0
        assert "mock mode" in result.output.lower() or "simulated" in result.output.lower()


class TestFullAutoCommand:
    def test_full_auto_requires_ack(self, runner):
        result = runner.invoke(cli, ["full-auto"])
        assert result.exit_code != 0
        assert "--yes" in result.output
