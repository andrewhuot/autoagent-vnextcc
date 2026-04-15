"""Tests for CLI UX Refactor V2 Streams 1 and 2."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from optimizer.change_card import ChangeCardStore, ProposedChangeCard
from optimizer.cost_tracker import CostTracker
from runner import cli


@pytest.fixture
def runner() -> CliRunner:
    """Return a CLI runner for UX refactor tests."""
    return CliRunner()


def _write_transcript_file(path: Path) -> Path:
    """Create a minimal transcript archive input file."""
    path.write_text(
        json.dumps(
            [
                {
                    "conversation_id": "hist-001",
                    "session_id": "sess-001",
                    "user_message": "Where is my order?",
                    "agent_response": "I need the order number before I can look it up.",
                    "outcome": "transfer",
                }
            ]
        ),
        encoding="utf-8",
    )
    return path


def _seed_config_version(workspace: Path, *, model_name: str, status: str = "canary") -> int:
    """Persist a second config version for compare/rollback/deploy tests."""
    from deployer import Deployer
    from logger import ConversationStore

    store = ConversationStore(db_path=str(workspace / "conversations.db"))
    deployer = Deployer(configs_dir=str(workspace / "configs"), store=store)
    config = yaml.safe_load((workspace / "configs" / "v001.yaml").read_text(encoding="utf-8"))
    config["model"] = model_name
    saved = deployer.version_manager.save_version(config, scores={"composite": 0.88}, status=status)
    return saved.version


class TestBareAutoagentStatusHome:
    """Tests for the bare `agentlab` entry behavior."""

    def test_root_invokes_status_when_no_arguments_are_given(self, runner: CliRunner) -> None:
        """Running `agentlab` inside a workspace should render the status home screen."""
        with runner.isolated_filesystem():
            init_result = runner.invoke(cli, ["init", "--dir", "."])
            assert init_result.exit_code == 0, init_result.output

            result = runner.invoke(cli, [])

            assert result.exit_code == 0, result.output
            assert "AgentLab Status" in result.output
            assert "Next step:" in result.output


class TestGrammarStandardization:
    """Tests for `resource verb` command routing plus compatibility aliases."""

    def test_build_show_new_subcommand_works(self, runner: CliRunner) -> None:
        """`agentlab build show latest` should replace `build-show`."""
        with runner.isolated_filesystem():
            build_result = runner.invoke(
                cli,
                ["build", "Build a customer support agent for order tracking with Shopify integration"],
            )
            assert build_result.exit_code == 0, build_result.output

            result = runner.invoke(cli, ["build", "show", "latest"])

            assert result.exit_code == 0, result.output
            assert "Latest Build Artifact" in result.output

    def test_build_show_legacy_alias_warns_but_still_works(self, runner: CliRunner) -> None:
        """`build-show` should remain available as a hidden deprecated alias."""
        with runner.isolated_filesystem():
            build_result = runner.invoke(
                cli,
                ["build", "Build a customer support agent for order tracking with Shopify integration"],
            )
            assert build_result.exit_code == 0, build_result.output

            result = runner.invoke(cli, ["build-show", "latest"])

            assert result.exit_code == 0, result.output
            assert "Deprecated" in result.output
            assert "agentlab build show latest" in result.output
            assert "Latest Build Artifact" in result.output

    def test_intelligence_import_new_command_works(self, runner: CliRunner) -> None:
        """`agentlab intelligence import` should replace transcript upload aliases."""
        with runner.isolated_filesystem():
            transcript_file = _write_transcript_file(Path("transcripts.json"))

            result = runner.invoke(cli, ["intelligence", "import", str(transcript_file)])

            assert result.exit_code == 0, result.output
            assert "Report ID:" in result.output

    def test_import_transcript_legacy_alias_warns_but_still_works(self, runner: CliRunner) -> None:
        """`agentlab import transcript upload` should warn and route to the new syntax."""
        with runner.isolated_filesystem():
            transcript_file = _write_transcript_file(Path("transcripts.json"))

            result = runner.invoke(cli, ["import", "transcript", "upload", str(transcript_file)])

            assert result.exit_code == 0, result.output
            assert "Deprecated" in result.output
            assert "agentlab intelligence import" in result.output
            assert "Report ID:" in result.output

    def test_loop_pause_and_resume_new_subcommands_work(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """`agentlab loop pause|resume` should replace the global control commands."""
        control_path = tmp_path / "human_control.json"

        from optimizer.human_control import HumanControlStore

        monkeypatch.setattr("runner._control_store", lambda: HumanControlStore(path=str(control_path)))

        pause_result = runner.invoke(cli, ["loop", "pause"])
        resume_result = runner.invoke(cli, ["loop", "resume"])

        assert pause_result.exit_code == 0, pause_result.output
        assert "Optimizer paused" in pause_result.output
        assert resume_result.exit_code == 0, resume_result.output
        assert "Optimizer resumed" in resume_result.output

    def test_pause_legacy_alias_warns_but_still_works(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """`agentlab pause` should warn and delegate to `agentlab loop pause`."""
        control_path = tmp_path / "human_control.json"

        from optimizer.human_control import HumanControlStore

        monkeypatch.setattr("runner._control_store", lambda: HumanControlStore(path=str(control_path)))

        result = runner.invoke(cli, ["pause"])

        assert result.exit_code == 0, result.output
        assert "Deprecated" in result.output
        assert "agentlab loop pause" in result.output
        assert "Optimizer paused" in result.output


class TestOnboardingAndTemplates:
    """Tests for Stream 2 onboarding and template flows."""

    def test_template_list_shows_all_starter_templates(self, runner: CliRunner) -> None:
        """`agentlab template list` should expose the four starter templates."""
        result = runner.invoke(cli, ["template", "list"])

        assert result.exit_code == 0, result.output
        for template_name in (
            "customer-support",
            "it-helpdesk",
            "sales-qualification",
            "healthcare-intake",
        ):
            assert template_name in result.output

    def test_new_command_creates_workspace_from_template_and_demo_data(self, runner: CliRunner) -> None:
        """`agentlab new` should create a template-backed workspace and print guided next steps."""
        with runner.isolated_filesystem():
            result = runner.invoke(
                cli,
                ["new", "my-project", "--template", "customer-support", "--demo"],
            )

            workspace = Path("my-project")
            assert result.exit_code == 0, result.output
            assert workspace.is_dir()
            assert (workspace / ".agentlab" / "workspace.json").exists()
            assert (workspace / ".agentlab" / "change_cards.db").exists()
            assert (workspace / ".agentlab" / "autofix.db").exists()
            assert (workspace / "configs" / "v001.yaml").exists()
            assert (workspace / "evals" / "cases").is_dir()
            assert "Mode:" in result.output
            assert "Recommended loop:" in result.output
            assert "cd my-project" in result.output
            assert "agentlab status" in result.output
            assert "agentlab build" in result.output
            assert "agentlab eval run" in result.output
            assert "agentlab optimize --cycles 1" in result.output
            assert "agentlab deploy --auto-review --yes" in result.output
            assert "Demo data makes `agentlab eval run` and `agentlab deploy --auto-review --yes` ready now." in result.output

    def test_demo_workspace_review_card_can_be_applied_and_deployed(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Demo workspaces should seed a deployable review candidate, not just a decorative card."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            cli,
            ["new", "demo-workspace", "--template", "customer-support", "--demo"],
        )

        workspace = tmp_path / "demo-workspace"
        assert result.exit_code == 0, result.output

        monkeypatch.chdir(workspace)
        monkeypatch.setattr("cli.permissions.PermissionManager.require", lambda *args, **kwargs: None)

        apply_result = runner.invoke(cli, ["review", "apply", "pending"])
        assert apply_result.exit_code == 0, apply_result.output
        assert "Active config: v002" in apply_result.output

        deploy_result = runner.invoke(cli, ["deploy", "canary", "--yes"])
        assert deploy_result.exit_code == 0, deploy_result.output

        manifest = json.loads((workspace / "configs" / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["active_version"] == 1
        assert manifest["canary_version"] == 2

    def test_template_apply_overwrites_workspace_with_selected_template(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """`agentlab template apply` should rewrite starter assets for the selected template."""
        workspace = tmp_path / "workspace"
        init_result = runner.invoke(cli, ["init", "--dir", str(workspace)])
        assert init_result.exit_code == 0, init_result.output

        monkeypatch.chdir(workspace)
        result = runner.invoke(cli, ["template", "apply", "healthcare-intake"])

        assert result.exit_code == 0, result.output
        config_text = (workspace / "configs" / "v001.yaml").read_text(encoding="utf-8")
        assert "patient" in config_text.lower()
        assert any((workspace / ".agentlab" / "scorers").glob("*"))
        metadata = json.loads((workspace / ".agentlab" / "workspace.json").read_text(encoding="utf-8"))
        assert metadata["template"] == "healthcare-intake"

    def test_doctor_fix_repairs_missing_dirs_and_active_config(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """`doctor --fix` should repair fixable workspace structure issues."""
        workspace = tmp_path / "workspace"
        init_result = runner.invoke(cli, ["init", "--dir", str(workspace)])
        assert init_result.exit_code == 0, init_result.output

        metadata_path = workspace / ".agentlab" / "workspace.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["active_config_version"] = None
        metadata["active_config_file"] = None
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        eval_cases_dir = workspace / "evals" / "cases"
        for existing in eval_cases_dir.glob("*"):
            existing.unlink()
        eval_cases_dir.rmdir()

        monkeypatch.chdir(workspace)
        result = runner.invoke(cli, ["doctor", "--fix"])

        assert result.exit_code == 0, result.output
        assert "Fixed" in result.output
        assert (workspace / "evals" / "cases").is_dir()
        updated = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert updated["active_config_version"] == 1

    def test_provider_configure_list_and_test_flow(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Provider setup commands should persist configuration and validate credentials."""
        workspace = tmp_path / "workspace"
        init_result = runner.invoke(cli, ["init", "--dir", str(workspace)])
        assert init_result.exit_code == 0, init_result.output

        monkeypatch.chdir(workspace)
        configure_result = runner.invoke(
            cli,
            ["provider", "configure"],
            input="openai\ngpt-4o\nOPENAI_API_KEY\n",
        )

        assert configure_result.exit_code == 0, configure_result.output
        assert (workspace / ".agentlab" / "providers.json").exists()

        list_result = runner.invoke(cli, ["provider", "list"])
        assert list_result.exit_code == 0, list_result.output
        assert "openai" in list_result.output
        assert "gpt-4o" in list_result.output

        test_result = runner.invoke(
            cli,
            ["provider", "test"],
            env={"OPENAI_API_KEY": "sk-test"},
        )
        assert test_result.exit_code == 0, test_result.output
        assert "Provider check passed" in test_result.output


class TestStreamBQuickWins:
    """Tests for Stream B home-screen and interactive prompt improvements."""

    def test_status_home_screen_surfaces_usage_rollups(self, runner: CliRunner) -> None:
        """Status should show last eval tokens and last optimize spend."""
        with runner.isolated_filesystem():
            init_result = runner.invoke(cli, ["init", "--dir", "."])
            assert init_result.exit_code == 0, init_result.output

            Path(".agentlab/eval_results_latest.json").write_text(
                json.dumps(
                    {
                        "api_version": "1",
                        "status": "ok",
                        "data": {
                            "quality": 0.8,
                            "safety": 1.0,
                            "latency": 0.9,
                            "cost": 0.7,
                            "composite": 0.85,
                            "total_tokens": 250,
                            "estimated_cost_usd": 0.11,
                        },
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            tracker = CostTracker(db_path=".agentlab/cost_tracker.db")
            tracker.record_cycle("cycle-001", spent_dollars=0.42, improvement_delta=0.05)

            result = runner.invoke(cli, ["status", "--verbose"])

            assert result.exit_code == 0, result.output
            assert "Last eval:" in result.output
            assert "Last optimize:" in result.output

    def test_edit_interactive_shows_workspace_help_and_quit_hints(self, runner: CliRunner) -> None:
        """Interactive edit should introduce workspace context and help affordances."""
        with runner.isolated_filesystem():
            init_result = runner.invoke(cli, ["init", "--dir", "."])
            assert init_result.exit_code == 0, init_result.output

            result = runner.invoke(cli, ["edit", "--interactive"], input="quit\n")

            assert result.exit_code == 0, result.output
            assert "AgentLab Edit" in result.output
            assert "Workspace:" in result.output
            assert "help" in result.output.lower()
            assert "quit" in result.output.lower()

    def test_diagnose_interactive_shows_workspace_help_and_quit_hints(self, runner: CliRunner) -> None:
        """Interactive diagnose should surface help and quit hints up front."""
        with runner.isolated_filesystem():
            init_result = runner.invoke(cli, ["init", "--dir", "."])
            assert init_result.exit_code == 0, init_result.output

            result = runner.invoke(cli, ["diagnose", "--interactive"], input="quit\n")

            assert result.exit_code == 0, result.output
            assert "AgentLab Diagnosis" in result.output
            assert "Workspace:" in result.output
            assert "help" in result.output.lower()
            assert "quit" in result.output.lower()


class TestWorkflowCommands:
    """Tests for Stream 1 workflow wrappers and mutation safety controls."""

    def test_improve_json_runs_eval_and_diagnosis_pipeline(self, runner: CliRunner) -> None:
        """`agentlab improve --json` should return a structured improvement payload."""
        no_api_keys = {
            **{k: v for k, v in __import__("os").environ.items()},
            "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "GOOGLE_API_KEY": "",
        }
        with runner.isolated_filesystem():
            init_result = runner.invoke(cli, ["init", "--dir", "."])
            assert init_result.exit_code == 0, init_result.output

            result = runner.invoke(cli, ["improve", "--json"], env=no_api_keys)

            assert result.exit_code == 0, result.output
            # The improve command prints a deprecation tip before JSON output; strip non-JSON prefix.
            json_start = result.output.index("{")
            payload = json.loads(result.output[json_start:])
            assert payload["api_version"] == "1"
            assert payload["status"] == "ok"
            assert "eval" in payload["data"]
            assert "diagnosis" in payload["data"]
            assert "proposal_count" in payload["data"]

    def test_compare_configs_reports_both_versions(self, runner: CliRunner) -> None:
        """`agentlab compare configs` should compare two stored config versions."""
        with runner.isolated_filesystem():
            init_result = runner.invoke(cli, ["init", "--dir", "."])
            assert init_result.exit_code == 0, init_result.output
            version = _seed_config_version(Path("."), model_name="compare-model-v2")
            assert version == 2

            result = runner.invoke(cli, ["compare", "configs", "1", "2", "--json"])

            assert result.exit_code == 0, result.output
            payload = json.loads(result.output)
            assert payload["status"] == "ok"
            assert payload["data"]["left"]["version"] == 1
            assert payload["data"]["right"]["version"] == 2
            assert "compare-model-v2" in payload["data"]["diff"]

    def test_compare_evals_picks_higher_scoring_run(self, runner: CliRunner) -> None:
        """`agentlab compare evals` should identify the stronger run."""
        with runner.isolated_filesystem():
            left = Path("left.json")
            right = Path("right.json")
            left.write_text(json.dumps({"scores": {"composite": 0.71, "quality": 0.70}}), encoding="utf-8")
            right.write_text(json.dumps({"scores": {"composite": 0.83, "quality": 0.82}}), encoding="utf-8")

            result = runner.invoke(cli, ["compare", "evals", str(left), str(right), "--json"])

            assert result.exit_code == 0, result.output
            payload = json.loads(result.output)
            assert payload["status"] == "ok"
            assert payload["data"]["winner"] == "right"
            assert payload["data"]["delta_composite"] > 0

    def test_eval_compare_renders_metric_delta_table(self, runner: CliRunner) -> None:
        """`agentlab eval compare` should show side-by-side metrics and deltas."""
        with runner.isolated_filesystem():
            left = Path("left.json")
            right = Path("right.json")
            left.write_text(
                json.dumps(
                    {
                        "scores": {
                            "quality": 0.70,
                            "safety": 1.0,
                            "latency": 0.80,
                            "cost": 0.90,
                            "composite": 0.76,
                        }
                    }
                ),
                encoding="utf-8",
            )
            right.write_text(
                json.dumps(
                    {
                        "scores": {
                            "quality": 0.82,
                            "safety": 1.0,
                            "latency": 0.78,
                            "cost": 0.88,
                            "composite": 0.84,
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = runner.invoke(
                cli,
                ["eval", "compare", "--left-run", str(left), "--right-run", str(right)],
            )

            assert result.exit_code == 0, result.output
            assert "Metric" in result.output
            assert "Run 1" in result.output
            assert "Run 2" in result.output
            assert "Delta" in result.output
            assert "composite" in result.output
            assert "0.8400" in result.output

    def test_eval_breakdown_shows_failure_clusters_for_latest_result(self, runner: CliRunner) -> None:
        """`agentlab eval breakdown` should summarize scores and cluster failures."""
        with runner.isolated_filesystem():
            Path("eval_results_latest.json").write_text(
                json.dumps(
                    {
                        "scores": {
                            "quality": 0.82,
                            "safety": 0.95,
                            "latency": 0.74,
                            "cost": 0.91,
                            "composite": 0.84,
                        },
                        "results": [
                            {
                                "case_id": "case-1",
                                "category": "safety",
                                "passed": False,
                                "details": {"failure_bucket": "timeout"},
                            },
                            {
                                "case_id": "case-2",
                                "category": "quality",
                                "passed": False,
                                "details": {"failure_bucket": "timeout"},
                            },
                            {
                                "case_id": "case-3",
                                "category": "quality",
                                "passed": False,
                                "details": {"failure_bucket": "tool_failure"},
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = runner.invoke(cli, ["eval", "breakdown"])

            assert result.exit_code == 0, result.output
            assert "Eval Breakdown" in result.output
            assert "quality" in result.output
            assert "composite" in result.output
            assert "Failure Clusters" in result.output
            assert "timeout" in result.output
            assert "tool_failure" in result.output
            assert "█" in result.output

    def test_compare_candidates_lists_non_active_versions(self, runner: CliRunner) -> None:
        """`agentlab compare candidates` should show candidate or canary configs with scores."""
        with runner.isolated_filesystem():
            init_result = runner.invoke(cli, ["init", "--dir", "."])
            assert init_result.exit_code == 0, init_result.output
            _seed_config_version(Path("."), model_name="candidate-model-v2", status="canary")

            result = runner.invoke(cli, ["compare", "candidates", "--json"])

            assert result.exit_code == 0, result.output
            payload = json.loads(result.output)
            assert payload["status"] == "ok"
            assert any(entry["version"] == 2 for entry in payload["data"])

    def test_ship_reuses_auto_review_deploy_path(self, runner: CliRunner) -> None:
        """`agentlab ship --yes` should auto-approve review cards, release, and canary deploy."""
        with runner.isolated_filesystem():
            init_result = runner.invoke(cli, ["init", "--dir", "."])
            assert init_result.exit_code == 0, init_result.output
            _seed_config_version(Path("."), model_name="ship-model-v2", status="candidate")
            card_store = ChangeCardStore(db_path=".agentlab/change_cards.db")
            card_store.save(
                ProposedChangeCard(
                    title="Ship candidate",
                    why="Exercise the ship auto-review path.",
                    candidate_config_version=2,
                    candidate_config_path="configs/v002.yaml",
                )
            )

            result = runner.invoke(cli, ["ship", "--yes", "--config-version", "2", "--json"])

            assert result.exit_code == 0, result.output
            payload = json.loads(result.output)
            manifest = json.loads(Path("configs/manifest.json").read_text(encoding="utf-8"))
            releases = list((Path(".agentlab") / "releases").glob("rel-*.json"))
            assert payload["status"] == "ok"
            assert payload["data"]["version"] == 2
            assert payload["data"]["strategy"] == "canary"
            assert payload["data"]["release"]["config_version"] == 2
            assert manifest["canary_version"] == 2
            assert ChangeCardStore(db_path=".agentlab/change_cards.db").list_pending() == []
            assert releases

    def test_config_import_dry_run_does_not_write_new_version(self, runner: CliRunner) -> None:
        """`config import --dry-run` should preview the import without writing files."""
        with runner.isolated_filesystem():
            init_result = runner.invoke(cli, ["init", "--dir", "."])
            assert init_result.exit_code == 0, init_result.output
            import_file = Path("incoming.yaml")
            import_file.write_text("model: imported-model\n", encoding="utf-8")

            result = runner.invoke(cli, ["config", "import", str(import_file), "--dry-run"])

            assert result.exit_code == 0, result.output
            assert "Dry run" in result.output
            assert not any(Path("configs").glob("v002_imported.yaml"))

    def test_release_create_dry_run_does_not_persist_release(self, runner: CliRunner) -> None:
        """`release create --dry-run` should not write a release artifact."""
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["release", "create", "--experiment-id", "exp-preview", "--dry-run"])

            assert result.exit_code == 0, result.output
            assert "Dry run" in result.output
            assert not (Path(".agentlab") / "releases").exists()

    def test_deploy_rollback_marks_canary_rolled_back(self, runner: CliRunner) -> None:
        """`deploy rollback` should clear the canary and mark the version rolled back."""
        with runner.isolated_filesystem():
            init_result = runner.invoke(cli, ["init", "--dir", "."])
            assert init_result.exit_code == 0, init_result.output
            _seed_config_version(Path("."), model_name="rollback-model-v2", status="canary")

            result = runner.invoke(cli, ["deploy", "rollback", "--config-version", "2"])

            assert result.exit_code == 0, result.output
            manifest = json.loads(Path("configs/manifest.json").read_text(encoding="utf-8"))
            version_two = next(entry for entry in manifest["versions"] if entry["version"] == 2)
            assert manifest["canary_version"] is None
            assert version_two["status"] == "rolled_back"

    def test_deploy_status_reports_active_and_canary_versions(self, runner: CliRunner) -> None:
        """`deploy status` should surface the current deployment state for the workspace."""
        with runner.isolated_filesystem():
            init_result = runner.invoke(cli, ["init", "--dir", "."])
            assert init_result.exit_code == 0, init_result.output
            _seed_config_version(Path("."), model_name="status-model-v2", status="canary")

            result = runner.invoke(cli, ["deploy", "status"])

            assert result.exit_code == 0, result.output
            assert "Deployment status" in result.output
            assert "v001" in result.output
            assert "v002" in result.output

    def test_config_rollback_promotes_requested_version(self, runner: CliRunner) -> None:
        """`config rollback` should promote the requested prior version to active."""
        with runner.isolated_filesystem():
            init_result = runner.invoke(cli, ["init", "--dir", "."])
            assert init_result.exit_code == 0, init_result.output
            _seed_config_version(Path("."), model_name="rollback-active-v2")
            promote_result = runner.invoke(cli, ["config", "set-active", "2"])
            assert promote_result.exit_code == 0, promote_result.output

            result = runner.invoke(cli, ["config", "rollback", "1"])

            assert result.exit_code == 0, result.output
            manifest = json.loads(Path("configs/manifest.json").read_text(encoding="utf-8"))
            workspace = json.loads((Path(".agentlab") / "workspace.json").read_text(encoding="utf-8"))
            assert manifest["active_version"] == 1
            assert workspace["active_config_version"] == 1

    def test_autofix_revert_marks_proposal_reverted(self, runner: CliRunner) -> None:
        """`autofix revert` should update the stored proposal status."""
        with runner.isolated_filesystem():
            init_result = runner.invoke(cli, ["init", "--dir", ".", "--demo"])
            assert init_result.exit_code == 0, init_result.output

            result = runner.invoke(cli, ["autofix", "revert", "demoaf1"])

            assert result.exit_code == 0, result.output
            from optimizer.autofix import AutoFixStore

            proposal = AutoFixStore().get("demoaf1")
            assert proposal is not None
            assert proposal.status == "reverted"

    def test_helper_backed_json_commands_include_api_version(self, runner: CliRunner) -> None:
        """Commands that already use the shared JSON helper should expose the versioned envelope."""
        with runner.isolated_filesystem():
            init_result = runner.invoke(cli, ["init", "--dir", "."])
            assert init_result.exit_code == 0, init_result.output

            result = runner.invoke(cli, ["config", "list", "--json"])

            assert result.exit_code == 0, result.output
            payload = json.loads(result.output)
            assert payload["api_version"] == "1"
            assert payload["status"] == "ok"

    def test_build_show_supports_id_only_and_path_only(self, runner: CliRunner) -> None:
        """Core show commands should expose compact identifier and path forms."""
        with runner.isolated_filesystem():
            build_result = runner.invoke(
                cli,
                ["build", "Build a customer support agent for order tracking with Shopify integration"],
            )
            assert build_result.exit_code == 0, build_result.output

            id_result = runner.invoke(cli, ["build", "show", "latest", "--id-only"])
            path_result = runner.invoke(cli, ["build", "show", "latest", "--path-only"])

            assert id_result.exit_code == 0, id_result.output
            assert id_result.output.strip()
            assert path_result.exit_code == 0, path_result.output
            assert path_result.output.strip().endswith(".agentlab/build_artifact_latest.json")

    def test_config_show_and_list_support_compact_output_flags(self, runner: CliRunner) -> None:
        """Config show/list should provide identifier-only and path-only output forms."""
        with runner.isolated_filesystem():
            init_result = runner.invoke(cli, ["init", "--dir", "."])
            assert init_result.exit_code == 0, init_result.output
            _seed_config_version(Path("."), model_name="compact-output-v2")

            list_ids = runner.invoke(cli, ["config", "list", "--id-only"])
            list_paths = runner.invoke(cli, ["config", "list", "--path-only"])
            show_id = runner.invoke(cli, ["config", "show", "2", "--id-only"])
            show_path = runner.invoke(cli, ["config", "show", "2", "--path-only"])

            assert list_ids.exit_code == 0, list_ids.output
            assert "v001" in list_ids.output
            assert "v002" in list_ids.output
            assert list_paths.exit_code == 0, list_paths.output
            assert "configs/v001.yaml" in list_paths.output
            assert "configs/v002.yaml" in list_paths.output
            assert show_id.exit_code == 0, show_id.output
            assert show_id.output.strip() == "v002"
            assert show_path.exit_code == 0, show_path.output
            assert show_path.output.strip().endswith("configs/v002.yaml")
