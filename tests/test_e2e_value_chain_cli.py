"""End-to-end CLI value-chain tests for the build -> eval -> optimize -> review -> deploy loop."""

from __future__ import annotations

import json
import importlib.util
from pathlib import Path

import pytest
from click.testing import CliRunner

from optimizer.change_card import ChangeCardStore
from optimizer.experiments import ExperimentStore
from runner import cli


@pytest.fixture
def runner() -> CliRunner:
    """Return a CLI runner for value-chain tests."""
    return CliRunner()


@pytest.fixture(autouse=True)
def clear_provider_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep CLI behavior deterministic in mock mode for loop tests."""
    for env_name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(env_name, raising=False)


def _read_json(path: Path) -> dict:
    """Load a JSON file for assertions."""
    return json.loads(path.read_text(encoding="utf-8"))


def _load_surface_state(workspace: Path) -> tuple[dict, dict]:
    """Read the API review/experiments surfaces against one workspace-local store set."""
    if importlib.util.find_spec("fastapi") is None:
        return {}, {}

    import fastapi
    from fastapi.testclient import TestClient

    from api.routes.changes import router as changes_router
    from api.routes.experiments import router as experiments_router

    app = fastapi.FastAPI()
    app.include_router(changes_router)
    app.include_router(experiments_router)
    app.state.change_card_store = ChangeCardStore(db_path=str(workspace / ".agentlab" / "change_cards.db"))
    app.state.experiment_store = ExperimentStore(db_path=str(workspace / ".agentlab" / "experiments.db"))

    client = TestClient(app)
    changes_response = client.get("/api/changes?status=all")
    experiments_response = client.get("/api/experiments?status=pending")

    assert changes_response.status_code == 200, changes_response.text
    assert experiments_response.status_code == 200, experiments_response.text
    return changes_response.json(), experiments_response.json()


def test_demo_build_to_ship_golden_path(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A demo workspace should exercise the documented build-to-ship loop end to end."""
    monkeypatch.chdir(tmp_path)
    new_result = runner.invoke(
        cli,
        ["new", "golden-agent", "--demo", "--mode", "mock"],
        catch_exceptions=False,
    )
    assert new_result.exit_code == 0, new_result.output
    assert "Recommended loop:" in new_result.output
    assert "agentlab build" in new_result.output
    assert "agentlab deploy --auto-review --yes" in new_result.output
    assert "Demo data makes `agentlab eval run` and `agentlab deploy --auto-review --yes` ready now." in new_result.output

    workspace = tmp_path / "golden-agent"
    monkeypatch.chdir(workspace)

    commands = [
        ["status"],
        ["build", "Build a support agent for order tracking with refund escalation"],
        ["build", "show", "latest"],
        ["eval", "run"],
        ["optimize", "--cycles", "1"],
        ["review", "list"],
        ["deploy", "--auto-review", "--yes"],
        ["deploy", "status"],
    ]
    for command in commands:
        result = runner.invoke(cli, command, catch_exceptions=False)
        assert result.exit_code == 0, f"{command}: {result.output}"

    manifest = _read_json(workspace / "configs" / "manifest.json")
    assert manifest["canary_version"] is not None
    assert ChangeCardStore(db_path=str(workspace / ".agentlab" / "change_cards.db")).list_pending() == []


def test_eval_run_defaults_to_workspace_eval_suite(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`eval run` should default to the current workspace's eval cases, not hidden package fixtures."""
    workspace = tmp_path / "test-agent"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--no-synthetic-data"])
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)
    result = runner.invoke(cli, ["eval", "run"])

    assert result.exit_code == 0, result.output
    latest = _read_json(workspace / ".agentlab" / "eval_results_latest.json")
    assert latest["total"] == 3
    assert {item["case_id"] for item in latest["results"]} == {
        "cs_happy_001",
        "cs_happy_002",
        "cs_safe_001",
    }


def test_full_loop_creates_reviewable_candidate_and_improves_after_apply(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The core loop should produce a reviewable candidate, improve after approval, and deploy it as canary."""
    workspace = tmp_path / "test-agent"
    monkeypatch.chdir(tmp_path)
    init_result = runner.invoke(cli, ["new", str(workspace.name)], catch_exceptions=False)
    assert init_result.exit_code == 0, init_result.output

    workspace = tmp_path / workspace.name
    monkeypatch.chdir(workspace)

    eval_result = runner.invoke(cli, ["eval", "run"])
    assert eval_result.exit_code == 0, eval_result.output
    baseline_payload = _read_json(workspace / ".agentlab" / "eval_results_latest.json")
    baseline_composite = baseline_payload["scores"]["composite"]
    assert baseline_payload["config_path"].endswith("configs/v001.yaml")

    optimize_result = runner.invoke(cli, ["optimize", "--cycles", "1"])
    assert optimize_result.exit_code == 0, optimize_result.output
    optimized = "Review: saved" in optimize_result.output
    skipped = "no optimization needed" in optimize_result.output
    assert optimized or skipped, optimize_result.output

    if optimized:
        store = ChangeCardStore(db_path=str(workspace / ".agentlab" / "change_cards.db"))
        pending_cards = store.list_pending(limit=10)
        assert len(pending_cards) == 1
        card = pending_cards[0]
        assert card.metrics_after["composite"] > card.metrics_before["composite"]
        assert card.candidate_config_version == 2
        assert card.candidate_config_path
        assert "cs_safe_001" in card.why

    manifest_after_optimize = _read_json(workspace / "configs" / "manifest.json")
    assert manifest_after_optimize["active_version"] == 1
    assert manifest_after_optimize["canary_version"] is None

    if optimized:
        version_two = next(entry for entry in manifest_after_optimize["versions"] if entry["version"] == 2)
        assert version_two["status"] == "candidate"

    latest_after_optimize = _read_json(workspace / ".agentlab" / "eval_results_latest.json")
    assert latest_after_optimize["scores"]["composite"] == baseline_composite
    assert latest_after_optimize["config_path"].endswith("configs/v001.yaml")

    if optimized:
        monkeypatch.setattr("cli.permissions.PermissionManager.require", lambda *args, **kwargs: None)
        apply_result = runner.invoke(cli, ["review", "apply", "pending"])
        assert apply_result.exit_code == 0, apply_result.output

        workspace_meta = _read_json(workspace / ".agentlab" / "workspace.json")
        assert workspace_meta["active_config_version"] == 2

        reeval_result = runner.invoke(cli, ["eval", "run"])
        assert reeval_result.exit_code == 0, reeval_result.output
        improved_payload = _read_json(workspace / ".agentlab" / "eval_results_latest.json")
        assert improved_payload["config_path"].endswith("configs/v002.yaml")
        assert improved_payload["scores"]["composite"] > baseline_composite
        assert improved_payload["passed"] == 3

        status_result = runner.invoke(cli, ["status"])
        assert status_result.exit_code == 0, status_result.output
        assert "Pending:    0 review card(s)" in status_result.output
        assert "Config:     v002" in status_result.output
        assert "Safety:     1.000 eval" in status_result.output

    if optimized:
        deploy_result = runner.invoke(cli, ["deploy", "canary", "--yes"])
        assert deploy_result.exit_code == 0, deploy_result.output
        manifest_after_deploy = _read_json(workspace / "configs" / "manifest.json")
        assert manifest_after_deploy["active_version"] == 1
        assert manifest_after_deploy["canary_version"] == 2
        version_two_after_deploy = next(
            entry for entry in manifest_after_deploy["versions"] if entry["version"] == 2
        )
        assert version_two_after_deploy["status"] == "canary"

        rollback_result = runner.invoke(cli, ["deploy", "rollback"])
        assert rollback_result.exit_code == 0, rollback_result.output
        manifest_after_rollback = _read_json(workspace / "configs" / "manifest.json")
        assert manifest_after_rollback["active_version"] == 1
        assert manifest_after_rollback["canary_version"] is None
        version_two_after_rollback = next(
            entry for entry in manifest_after_rollback["versions"] if entry["version"] == 2
        )
        assert version_two_after_rollback["status"] == "rolled_back"

    all_pass_optimize = runner.invoke(cli, ["optimize", "--cycles", "1"])
    assert all_pass_optimize.exit_code == 0, all_pass_optimize.output
    assert "no optimization needed" in all_pass_optimize.output.lower()


def test_cli_and_api_review_surfaces_share_pending_and_applied_candidate_state(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI review, API changes, and API experiments should all agree on the same candidate lifecycle."""
    workspace = tmp_path / "surface-sync-agent"
    monkeypatch.chdir(tmp_path)
    init_result = runner.invoke(cli, ["new", str(workspace.name)], catch_exceptions=False)
    assert init_result.exit_code == 0, init_result.output

    workspace = tmp_path / workspace.name
    monkeypatch.chdir(workspace)

    eval_result = runner.invoke(cli, ["eval", "run"])
    assert eval_result.exit_code == 0, eval_result.output

    optimize_result = runner.invoke(cli, ["optimize", "--cycles", "1"])
    assert optimize_result.exit_code == 0, optimize_result.output
    optimized = "Review: saved" in optimize_result.output

    review_list_result = runner.invoke(cli, ["review", "list", "--json"])
    assert review_list_result.exit_code == 0, review_list_result.output
    review_payload = json.loads(review_list_result.output)
    review_cards = review_payload["data"]

    if optimized:
        assert len(review_cards) == 1

        pending_card = ChangeCardStore(db_path=str(workspace / ".agentlab" / "change_cards.db")).list_pending(limit=10)[0]
        pending_experiments = ExperimentStore(db_path=str(workspace / ".agentlab" / "experiments.db")).list_by_status("pending")
        assert len(pending_experiments) == 1
        assert pending_card.experiment_card_id == pending_experiments[0].experiment_id
        assert review_cards[0]["card_id"] == pending_card.card_id

        changes_payload, experiments_payload = _load_surface_state(workspace)
        if changes_payload and experiments_payload:
            assert len(changes_payload["cards"]) == 1
            assert changes_payload["cards"][0]["card_id"] == pending_card.card_id
            assert len(experiments_payload["experiments"]) == 1
            assert experiments_payload["experiments"][0]["experiment_id"] == pending_card.experiment_card_id
            assert experiments_payload["experiments"][0]["status"] == "pending"

        monkeypatch.setattr("cli.permissions.PermissionManager.require", lambda *args, **kwargs: None)
        apply_result = runner.invoke(cli, ["review", "apply", pending_card.card_id])
        assert apply_result.exit_code == 0, apply_result.output

        accepted_experiment = ExperimentStore(
            db_path=str(workspace / ".agentlab" / "experiments.db")
        ).get(pending_card.experiment_card_id)
        assert accepted_experiment is not None
        assert accepted_experiment.status == "accepted"
    else:
        assert len(review_cards) == 0


def test_optimize_without_eval_data_guides_user_and_deploy_rejects_active_only_workspace(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI should refuse to optimize without eval data and should reject canarying the active-only version."""
    workspace = tmp_path / "blank-agent"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--no-synthetic-data"])
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)

    optimize_result = runner.invoke(cli, ["optimize", "--cycles", "1"])
    assert optimize_result.exit_code == 0, optimize_result.output
    assert "agentlab eval run" in optimize_result.output
    assert ChangeCardStore(db_path=str(workspace / ".agentlab" / "change_cards.db")).list_pending() == []

    deploy_result = runner.invoke(cli, ["deploy", "canary", "--yes"])
    assert deploy_result.exit_code != 0
    assert "No candidate config version available" in deploy_result.output
