"""Tests for the Stream 1 workspace-oriented CLI UX."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from click.testing import CliRunner

import runner as runner_module
from deployer import Deployer
from logger import ConversationStore
from runner import cli


@pytest.fixture
def runner() -> CliRunner:
    """Return a CLI runner for workspace command tests."""
    return CliRunner()


@pytest.fixture(autouse=True)
def clear_provider_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep provider state deterministic for CLI workspace tests."""
    for env_name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(env_name, raising=False)


def _workspace_metadata(workspace: Path) -> dict:
    """Load workspace metadata JSON for assertions."""
    return json.loads((workspace / ".autoagent" / "workspace.json").read_text(encoding="utf-8"))


def _workspace_runtime(workspace: Path) -> dict:
    """Load the workspace runtime YAML for assertions."""
    return yaml.safe_load((workspace / "autoagent.yaml").read_text(encoding="utf-8"))


def _seed_second_config(workspace: Path) -> None:
    """Add a second saved config version for active-config command tests."""
    store = ConversationStore(db_path=str(workspace / "conversations.db"))
    deployer = Deployer(configs_dir=str(workspace / "configs"), store=store)
    config = yaml.safe_load((workspace / "configs" / "v001.yaml").read_text(encoding="utf-8"))
    config["model"] = "demo-model-v2"
    deployer.version_manager.save_version(config, scores={"composite": 0.88}, status="canary")


def test_init_name_creates_project_directory_and_workspace_metadata(
    runner: CliRunner,
    tmp_path: Path,
) -> None:
    """`init --name` should create a new project folder with tracked workspace metadata."""
    result = runner.invoke(cli, ["init", "--dir", str(tmp_path), "--name", "my-project"])

    project_dir = tmp_path / "my-project"

    assert result.exit_code == 0, result.output
    assert project_dir.is_dir()
    assert (project_dir / ".autoagent" / "workspace.json").exists()
    assert (project_dir / "configs" / "v001.yaml").exists()
    assert (project_dir / "configs" / "v001_base.yaml").exists()
    metadata = _workspace_metadata(project_dir)
    assert metadata["name"] == "my-project"
    assert metadata["active_config_version"] == 1
    assert "Next step:" in result.output


def test_init_demo_seeds_workspace_state(runner: CliRunner, tmp_path: Path) -> None:
    """`init --demo` should create a reviewable seeded workspace without extra scripts."""
    workspace = tmp_path / "demo-workspace"

    result = runner.invoke(cli, ["init", "--dir", str(workspace), "--demo"])

    assert result.exit_code == 0, result.output
    assert (workspace / "conversations.db").exists()
    assert (workspace / ".autoagent" / "traces.db").exists()
    assert (workspace / ".autoagent" / "change_cards.db").exists()
    assert (workspace / ".autoagent" / "autofix.db").exists()
    assert (workspace / "evals" / "cases").is_dir()
    assert "demo" in result.output.lower()


def test_init_defaults_to_mock_mode_even_when_api_keys_exist(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fresh workspaces should stay in mock mode until live mode is explicitly requested."""
    workspace = tmp_path / "mock-default"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    result = runner.invoke(cli, ["init", "--dir", str(workspace)])

    assert result.exit_code == 0, result.output
    assert _workspace_runtime(workspace)["optimizer"]["use_mock"] is True


def test_new_mode_auto_uses_api_key_detection_when_explicitly_requested(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--mode auto` should opt back into API-key-based live detection."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    result = runner.invoke(cli, ["new", "auto-live", "--mode", "auto"])

    workspace = tmp_path / "auto-live"
    assert result.exit_code == 0, result.output
    assert _workspace_runtime(workspace)["optimizer"]["use_mock"] is False


def test_mode_set_auto_restores_credential_detection(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`mode set auto` should restore provider-based mode detection for the workspace."""
    workspace = tmp_path / "mode-auto"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--mode", "mock"])
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)

    set_result = runner.invoke(cli, ["mode", "set", "auto"])
    assert set_result.exit_code == 0, set_result.output
    assert _workspace_metadata(workspace)["mode"] == "auto"

    show_result = runner.invoke(cli, ["mode", "show"])
    assert show_result.exit_code == 0, show_result.output
    assert "Preferred mode: AUTO" in show_result.output
    assert "Current mode: LIVE" in show_result.output


def test_init_mode_live_writes_live_runtime_config(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--mode live` should preserve live mode in the generated runtime config."""
    workspace = tmp_path / "live-mode"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    result = runner.invoke(cli, ["init", "--dir", str(workspace), "--mode", "live"])

    assert result.exit_code == 0, result.output
    assert _workspace_runtime(workspace)["optimizer"]["use_mock"] is False


def test_demo_seed_command_works_after_plain_init(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`demo seed` should seed the current workspace without manual file creation."""
    workspace = tmp_path / "workspace"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--no-synthetic-data"])
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)
    result = runner.invoke(cli, ["demo", "seed"])

    assert result.exit_code == 0, result.output
    assert (workspace / ".autoagent" / "change_cards.db").exists()
    assert (workspace / ".autoagent" / "autofix.db").exists()
    review_result = runner.invoke(cli, ["review", "list"])
    assert review_result.exit_code == 0, review_result.output
    assert "Pending change cards" in review_result.output


def test_status_errors_clearly_when_workspace_is_missing(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Commands that require a workspace should fail with the new discovery hint."""
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli, ["status"])

    assert result.exit_code != 0
    assert "No AutoAgent workspace found. Run autoagent init" in result.output


def test_workspace_discovery_walks_up_from_nested_directory(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Commands should discover the nearest workspace root by walking upward from cwd."""
    workspace = tmp_path / "nested-demo"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace)])
    assert init_result.exit_code == 0, init_result.output

    nested_dir = workspace / "src" / "deeper"
    nested_dir.mkdir(parents=True)
    monkeypatch.chdir(nested_dir)

    result = runner.invoke(cli, ["status"])

    assert result.exit_code == 0, result.output
    assert "Workspace:" in result.output
    assert str(workspace) in result.output


def test_deploy_auto_review_skips_confirmation_prompt(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`deploy --auto-review` should bypass the interactive permission prompt."""
    workspace = tmp_path / "deploy-auto-review"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace)])
    assert init_result.exit_code == 0, init_result.output
    _seed_second_config(workspace)

    monkeypatch.chdir(workspace)

    def _unexpected_prompt(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("deploy should not prompt when --auto-review is set")

    monkeypatch.setattr("cli.permissions.PermissionManager.require", _unexpected_prompt)

    result = runner.invoke(cli, ["deploy", "--auto-review"])

    assert result.exit_code == 0, result.output


def test_deploy_auto_review_creates_release_and_marks_canary(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`deploy --auto-review` should mirror ship by creating a release before deploy."""
    workspace = tmp_path / "deploy-auto-review-release"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace)])
    assert init_result.exit_code == 0, init_result.output
    _seed_second_config(workspace)

    monkeypatch.chdir(workspace)

    result = runner.invoke(cli, ["deploy", "--auto-review", "--config-version", "2", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    manifest = json.loads((workspace / "configs" / "manifest.json").read_text(encoding="utf-8"))
    releases = list((workspace / ".autoagent" / "releases").glob("rel-*.json"))
    assert payload["status"] == "ok"
    assert payload["data"]["version"] == 2
    assert payload["data"]["release"]["config_version"] == 2
    assert manifest["canary_version"] == 2
    assert releases


def test_deploy_short_yes_flag_skips_confirmation_prompt(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`deploy -y` should be accepted as the short automation-friendly prompt bypass."""
    workspace = tmp_path / "deploy-short-yes"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace)])
    assert init_result.exit_code == 0, init_result.output
    _seed_second_config(workspace)

    monkeypatch.chdir(workspace)

    def _unexpected_prompt(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("deploy should not prompt when -y is set")

    monkeypatch.setattr("cli.permissions.PermissionManager.require", _unexpected_prompt)

    result = runner.invoke(cli, ["deploy", "-y"])

    assert result.exit_code == 0, result.output


def test_config_set_active_updates_workspace_metadata_and_default_show(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`config set-active` should update workspace metadata and become the default config."""
    workspace = tmp_path / "active-config"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace)])
    assert init_result.exit_code == 0, init_result.output
    _seed_second_config(workspace)

    monkeypatch.chdir(workspace)
    result = runner.invoke(cli, ["config", "set-active", "2"])

    assert result.exit_code == 0, result.output
    assert _workspace_metadata(workspace)["active_config_version"] == 2

    show_result = runner.invoke(cli, ["config", "show"])
    assert show_result.exit_code == 0, show_result.output
    assert "# Active config: v002" in show_result.output
    assert "demo-model-v2" in show_result.output


def test_config_show_active_selector_and_list_json_follow_workspace_metadata(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`config show active` and `config list --json` should respect workspace-selected active config."""
    workspace = tmp_path / "active-selector"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace)])
    assert init_result.exit_code == 0, init_result.output
    _seed_second_config(workspace)

    monkeypatch.chdir(workspace)
    set_active_result = runner.invoke(cli, ["config", "set-active", "2"])
    assert set_active_result.exit_code == 0, set_active_result.output

    show_result = runner.invoke(cli, ["config", "show", "active"])
    assert show_result.exit_code == 0, show_result.output
    assert "# Config: v002" in show_result.output or "# Active config: v002" in show_result.output
    assert "demo-model-v2" in show_result.output

    list_result = runner.invoke(cli, ["config", "list", "--json"])
    assert list_result.exit_code == 0, list_result.output
    payload = json.loads(list_result.output)
    active_versions = [entry["version"] for entry in payload["data"] if entry.get("is_active")]
    assert active_versions == [2]


def test_eval_run_uses_active_config_by_default(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`eval run` should load the workspace active config when `--config` is omitted."""
    workspace = tmp_path / "eval-active-config"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace)])
    assert init_result.exit_code == 0, init_result.output
    _seed_second_config(workspace)

    monkeypatch.chdir(workspace)
    set_active_result = runner.invoke(cli, ["config", "set-active", "2"], catch_exceptions=False)
    assert set_active_result.exit_code == 0, set_active_result.output

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
        run_id="run-active-config",
        results=[],
    )

    class _FakeEvalRunner:
        """Capture the config passed through the CLI eval path."""

        def run(self, config=None, dataset_path=None, split="all"):
            del dataset_path, split
            captured["config"] = config
            return fake_score

    monkeypatch.setattr(runner_module, "_build_eval_runner", lambda runtime, **kwargs: _FakeEvalRunner())
    monkeypatch.setattr(runner_module, "_warn_mock_modes", lambda **kwargs: None)

    result = runner.invoke(cli, ["eval", "run"])

    assert result.exit_code == 0, result.output
    assert captured["config"]["model"] == "demo-model-v2"


def test_build_inside_workspace_registers_generated_config_without_promoting_it(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`build` should stage its generated config for the workspace without auto-deploying it."""
    workspace = tmp_path / "build-workspace"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace)])
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)
    result = runner.invoke(
        cli,
        ["build", "Build a support agent for order tracking and refunds"],
    )

    assert result.exit_code == 0, result.output
    metadata = _workspace_metadata(workspace)
    manifest = json.loads((workspace / "configs" / "manifest.json").read_text(encoding="utf-8"))
    assert metadata["active_config_version"] == 2
    assert manifest["active_version"] == 1
    version_two = next(entry for entry in manifest["versions"] if entry["version"] == 2)
    assert version_two["status"] == "candidate"
    assert (workspace / "configs" / "v002.yaml").exists()


def test_build_staged_config_can_be_canaried_after_rejected_optimize(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A built workspace config should remain deployable even if the first optimize cycle rejects changes."""
    workspace = tmp_path / "build-deploy-workspace"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace)])
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)

    build_result = runner.invoke(
        cli,
        ["build", "Build a support agent for order tracking and refunds"],
    )
    assert build_result.exit_code == 0, build_result.output

    eval_result = runner.invoke(cli, ["eval", "run"])
    assert eval_result.exit_code == 0, eval_result.output

    optimize_result = runner.invoke(cli, ["optimize", "--cycles", "1"])
    assert optimize_result.exit_code == 0, optimize_result.output
    assert ("Rejected" in optimize_result.output) or ("no optimization needed" in optimize_result.output), optimize_result.output

    deploy_result = runner.invoke(cli, ["deploy", "canary", "--yes"])
    assert deploy_result.exit_code == 0, deploy_result.output
    assert "as canary" in deploy_result.output

    manifest = json.loads((workspace / "configs" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["active_version"] == 1
    assert manifest["canary_version"] == 2


def test_status_distinguishes_selected_config_from_deployed_version_after_build(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`status` should show the local working config separately from the deployed active version."""
    workspace = tmp_path / "status-after-build"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace)])
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)
    build_result = runner.invoke(
        cli,
        ["build", "Build a support agent for order tracking and refunds"],
    )
    assert build_result.exit_code == 0, build_result.output

    status_result = runner.invoke(cli, ["status"])
    assert status_result.exit_code == 0, status_result.output
    assert "Config:     v002" in status_result.output
    assert "Deployment: active v001" in status_result.output


def test_doctor_treats_mock_mode_workspace_as_ready(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`doctor` should treat a normal mock-mode workspace as healthy, not broken."""
    workspace = tmp_path / "doctor-workspace"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace)])
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)
    result = runner.invoke(cli, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "Mock mode:" in result.output
    assert "Status: All checks passed" in result.output


def test_status_recommends_eval_before_any_optimization_attempts(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh workspace status screen should guide the user to the first eval run."""
    workspace = tmp_path / "status-workspace"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace)])
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)
    result = runner.invoke(cli, ["status"])

    assert result.exit_code == 0, result.output
    assert "Next step:" in result.output
    assert "autoagent eval run" in result.output


def test_eval_run_persists_latest_results_for_eval_show(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A normal eval run should save a latest-results artifact that `eval show latest` can read."""
    workspace = tmp_path / "eval-results"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace)])
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)

    fake_score = SimpleNamespace(
        quality=0.81,
        safety=1.0,
        latency=0.9,
        cost=0.95,
        composite=0.88,
        confidence_intervals={},
        safety_failures=0,
        total_cases=3,
        passed_cases=3,
        total_tokens=123,
        estimated_cost_usd=0.01,
        warnings=[],
        provenance={},
        run_id="run-persisted",
        results=[],
    )

    class _FakeEvalRunner:
        """Return a deterministic score for eval-result persistence tests."""

        def run(self, config=None, dataset_path=None, split="all"):
            del config, dataset_path, split
            return fake_score

    monkeypatch.setattr(runner_module, "_build_eval_runner", lambda runtime, **kwargs: _FakeEvalRunner())
    monkeypatch.setattr(runner_module, "_warn_mock_modes", lambda **kwargs: None)

    run_result = runner.invoke(cli, ["eval", "run"])
    show_result = runner.invoke(cli, ["eval", "show", "latest"])

    assert run_result.exit_code == 0, run_result.output
    assert (workspace / ".autoagent" / "eval_results_latest.json").exists()
    assert show_result.exit_code == 0, show_result.output
    assert "3/3 passed" in show_result.output


def test_eval_run_persists_mock_mode_and_labels_results(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mock-backed eval run should persist `mode=mock` and label both run/show output clearly."""
    workspace = tmp_path / "eval-mode"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace)])
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    run_result = runner.invoke(cli, ["eval", "run"])
    show_result = runner.invoke(cli, ["eval", "show", "latest"])
    latest = json.loads((workspace / ".autoagent" / "eval_results_latest.json").read_text(encoding="utf-8"))

    assert run_result.exit_code == 0, run_result.output
    assert latest["mode"] == "mock"
    assert "mock mode" in run_result.output.lower()
    assert show_result.exit_code == 0, show_result.output
    assert "mock mode" in show_result.output.lower()


def test_status_uses_latest_eval_result_when_no_optimize_history(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Status should surface the latest eval snapshot even before any optimize cycles exist."""
    workspace = tmp_path / "status-eval"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace)])
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)
    (workspace / ".autoagent" / "eval_results_latest.json").write_text(
        json.dumps(
            {
                "timestamp": "2026-03-30T16:00:00+00:00",
                "mode": "mixed",
                "scores": {"composite": 0.87},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = runner.invoke(cli, ["status"])

    assert result.exit_code == 0, result.output
    assert "0.8700" in result.output
    assert "Eval mode:" in result.output
    assert "MIXED" in result.output


def test_eval_generate_handles_workspace_style_config_and_writes_suite(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`eval generate` should succeed against the seeded workspace config used by the quickstart."""
    workspace = tmp_path / "eval-generate"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace)])
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)
    result = runner.invoke(
        cli,
        ["eval", "generate", "--config", "configs/v001.yaml", "--output", "generated_eval_suite.json"],
    )

    assert result.exit_code == 0, result.output
    output_path = workspace / "generated_eval_suite.json"
    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "ready"
    assert sum(len(cases) for cases in payload["categories"].values()) > 0


def test_optimize_handles_empty_best_score_file_in_fresh_workspace(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`optimize` should treat a fresh empty best-score file as zero instead of crashing."""
    workspace = tmp_path / "optimize-fresh"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace)])
    assert init_result.exit_code == 0, init_result.output
    assert (workspace / ".autoagent" / "best_score.txt").read_text(encoding="utf-8") == ""

    monkeypatch.chdir(workspace)
    result = runner.invoke(cli, ["optimize", "--cycles", "1", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["api_version"] == "1"
    assert isinstance(payload["data"], list)
    assert len(payload["data"]) == 1
    assert payload["data"][0]["cycle"] == 1


def test_init_then_build_supports_repo_free_user_flow(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user should be able to init once, then build inside the discovered workspace."""
    workspace = tmp_path / "first-run-flow"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace)])
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)
    result = runner.invoke(
        cli,
        ["build", "Build a customer support agent for order tracking with Shopify integration"],
    )

    assert result.exit_code == 0, result.output
    assert (workspace / ".autoagent" / "build_artifact_latest.json").exists()
    assert (workspace / ".autoagent" / "build_artifacts.json").exists()
    assert "Next step:" in result.output


def test_trace_latest_selectors_work_in_demo_workspace(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`trace show latest` and `trace promote latest` should work in a demo-seeded workspace."""
    workspace = tmp_path / "trace-latest"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--demo"])
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)
    show_result = runner.invoke(cli, ["trace", "show", "latest"])
    assert show_result.exit_code == 0, show_result.output
    assert "Trace:" in show_result.output

    promote_result = runner.invoke(cli, ["trace", "promote", "latest"])
    assert promote_result.exit_code == 0, promote_result.output
    promoted_files = list((workspace / "evals" / "cases").glob("promoted_*.yaml"))
    assert promoted_files


def test_status_home_screen_shows_workspace_summary_and_counts(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`status` should act as a concise home screen for the active workspace."""
    workspace = tmp_path / "status-home"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--demo"])
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)
    result = runner.invoke(cli, ["status"])

    assert result.exit_code == 0, result.output
    assert "Workspace:" in result.output
    assert "Mode:" in result.output
    assert "Config:" in result.output
    assert "Eval score:" in result.output
    assert "Pending:" in result.output
    assert "Deployment:" in result.output
    assert "Next step:" in result.output
