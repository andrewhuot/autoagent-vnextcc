"""CLI coverage for the terminal Workbench workflow."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
import pytest
from click.testing import CliRunner

from cli.workspace import AgentLabWorkspace
from runner import cli


@pytest.fixture()
def runner() -> CliRunner:
    """Provide an isolated Click runner for CLI command tests."""
    return CliRunner()


def _seed_workspace(root: Path) -> AgentLabWorkspace:
    """Create a minimal workspace so Workbench saves target real AgentLab paths."""
    workspace = AgentLabWorkspace.create(
        root=root,
        name=root.name,
        template="customer-support",
        agent_name="CLI Workbench Agent",
        platform="Google ADK",
    )
    workspace.ensure_structure()
    workspace.save_metadata()
    workspace.runtime_config_path.write_text(
        yaml.safe_dump({"optimizer": {"use_mock": True}}, sort_keys=False),
        encoding="utf-8",
    )
    return workspace


def _json_payload(output: str) -> dict:
    """Parse a standard CLI JSON envelope from command output."""
    return json.loads(output)


def test_workbench_build_json_creates_eval_candidate_readiness(
    runner: CliRunner,
) -> None:
    """`agentlab workbench build` should run the real Workbench stream contract."""
    with runner.isolated_filesystem():
        _seed_workspace(Path.cwd())

        result = runner.invoke(
            cli,
            [
                "workbench",
                "build",
                "Build a support agent for refunds with PII guardrails.",
                "--mock",
                "--max-iterations",
                "1",
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        payload = _json_payload(result.output)
        assert payload["api_version"] == "1"
        assert payload["status"] == "ok"
        data = payload["data"]
        assert data["project_id"].startswith("wb-")
        assert data["run"]["status"] == "completed"
        assert data["summary"]["validation_status"] == "passed"
        assert data["bridge"]["evaluation"]["readiness_state"] == "needs_materialization"
        assert data["bridge"]["evaluation"]["label"] == "Save candidate before Eval"
        assert data["bridge"]["optimization"]["readiness_state"] == "needs_eval_candidate"
        assert data["next_commands"]["save"].startswith("agentlab workbench save")


def test_workbench_show_text_renders_readiness_and_next_step(
    runner: CliRunner,
) -> None:
    """`agentlab workbench show` should explain readiness without saving anything."""
    with runner.isolated_filesystem():
        _seed_workspace(Path.cwd())
        build = runner.invoke(
            cli,
            [
                "workbench",
                "build",
                "Build a billing support agent with lookup tools.",
                "--mock",
                "--max-iterations",
                "1",
                "--json",
            ],
        )
        assert build.exit_code == 0, build.output

        result = runner.invoke(cli, ["workbench", "show"])

        assert result.exit_code == 0, result.output
        assert "AgentLab Workbench" in result.output
        assert "Save candidate before Eval" in result.output
        assert "Eval candidate not ready" in result.output
        assert "agentlab workbench save" in result.output
        assert "structural validation is not an eval result" in result.output


def test_workbench_save_materializes_candidate_for_eval(
    runner: CliRunner,
) -> None:
    """`agentlab workbench save` should reuse the typed Workbench bridge path."""
    with runner.isolated_filesystem():
        workspace = _seed_workspace(Path.cwd())
        build = runner.invoke(
            cli,
            [
                "workbench",
                "build",
                "Build an airline support agent with flight status tools.",
                "--mock",
                "--max-iterations",
                "1",
                "--json",
            ],
        )
        assert build.exit_code == 0, build.output

        result = runner.invoke(cli, ["workbench", "save", "--json"])

        assert result.exit_code == 0, result.output
        payload = _json_payload(result.output)
        data = payload["data"]
        save_result = data["save_result"]
        assert Path(save_result["config_path"]).exists()
        assert Path(save_result["eval_cases_path"]).exists()
        assert data["bridge"]["evaluation"]["readiness_state"] == "ready_for_eval"
        assert data["bridge"]["optimization"]["readiness_state"] == "awaiting_eval_run"
        assert data["eval_request"]["config_path"] == save_result["config_path"]
        assert data["optimize_request_template"]["eval_run_id"] is None

        refreshed = AgentLabWorkspace(root=workspace.root, metadata=workspace.metadata)
        active = refreshed.resolve_active_config()
        assert active is not None
        assert str(active.path) == save_result["config_path"]


def test_workbench_iterate_json_continues_latest_project(
    runner: CliRunner,
) -> None:
    """`agentlab workbench iterate` should append a follow-up turn to latest project."""
    with runner.isolated_filesystem():
        _seed_workspace(Path.cwd())
        build = runner.invoke(
            cli,
            [
                "workbench",
                "build",
                "Build a support agent for order status.",
                "--mock",
                "--max-iterations",
                "1",
                "--json",
            ],
        )
        assert build.exit_code == 0, build.output
        build_payload = _json_payload(build.output)
        project_id = build_payload["data"]["project_id"]

        result = runner.invoke(
            cli,
            [
                "workbench",
                "iterate",
                "Add a regression eval for missing orders.",
                "--mock",
                "--max-iterations",
                "1",
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        payload = _json_payload(result.output)
        data = payload["data"]
        assert data["project_id"] == project_id
        assert data["run"]["status"] == "completed"
        assert data["turn_count"] >= 2
        assert data["artifact_count"] >= build_payload["data"]["artifact_count"]
        assert data["bridge"]["evaluation"]["readiness_state"] == "needs_materialization"
