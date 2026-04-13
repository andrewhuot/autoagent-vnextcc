"""Tests for the CLI Workbench commands.

Tests the ``agentlab workbench`` command group using CliRunner with
isolated filesystems backed by real WorkbenchStore/WorkbenchService.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from builder.workbench import WorkbenchService, WorkbenchStore
from cli.workbench import workbench_group


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def _seed_workspace(root: Path) -> None:
    """Create a minimal workspace so discover_workspace() finds it."""
    agentlab_dir = root / ".agentlab"
    agentlab_dir.mkdir(parents=True, exist_ok=True)
    configs_dir = root / "configs"
    configs_dir.mkdir(parents=True, exist_ok=True)
    (root / "evals" / "cases").mkdir(parents=True, exist_ok=True)
    workspace_meta = {
        "name": "test-workspace",
        "active_config_version": None,
        "template": "customer-support",
        "agent_name": "Test Agent",
        "platform": "portable",
    }
    (agentlab_dir / "workspace.json").write_text(
        json.dumps(workspace_meta, indent=2), encoding="utf-8",
    )


def _make_service(root: Path) -> WorkbenchService:
    """Build a WorkbenchService for direct assertions."""
    store_path = root / ".agentlab" / "workbench_projects.json"
    return WorkbenchService(WorkbenchStore(path=store_path))


class TestWorkbenchCreate:
    def test_create_text_output(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace(tmp_path)

        result = runner.invoke(workbench_group, ["create", "Build a flight agent"])
        assert result.exit_code == 0, result.output
        assert "project created" in result.output.lower()
        assert "wb-" in result.output

    def test_create_json_output(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace(tmp_path)

        result = runner.invoke(workbench_group, ["create", "Build a support agent", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "ok"
        assert "project" in payload["data"]
        assert payload["data"]["project"]["project_id"].startswith("wb-")

    def test_create_with_target(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace(tmp_path)

        result = runner.invoke(workbench_group, ["create", "Agent for ADK", "--target", "adk"])
        assert result.exit_code == 0, result.output
        assert "adk" in result.output.lower()


class TestWorkbenchStatus:
    def test_status_default_project(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace(tmp_path)

        runner.invoke(workbench_group, ["create", "Test agent"])
        result = runner.invoke(workbench_group, ["status"])
        assert result.exit_code == 0, result.output
        assert "Workbench Status" in result.output

    def test_status_json(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace(tmp_path)

        runner.invoke(workbench_group, ["create", "Test agent"])
        result = runner.invoke(workbench_group, ["status", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "ok"

    def test_bare_workbench_shows_status(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace(tmp_path)

        runner.invoke(workbench_group, ["create", "Test agent"])
        result = runner.invoke(workbench_group, [])
        assert result.exit_code == 0, result.output
        assert "Workbench Status" in result.output


class TestWorkbenchPlanApply:
    def test_plan_creates_operations(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace(tmp_path)

        runner.invoke(workbench_group, ["create", "Airline agent"])
        result = runner.invoke(workbench_group, ["plan", "Add a flight status tool"])
        assert result.exit_code == 0, result.output
        assert "Change Plan" in result.output
        assert "plan-" in result.output

    def test_plan_json(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace(tmp_path)

        runner.invoke(workbench_group, ["create", "Airline agent"])
        result = runner.invoke(workbench_group, ["plan", "Add a flight status tool", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "ok"
        assert "plan" in payload["data"]

    def test_apply_increments_version(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace(tmp_path)

        runner.invoke(workbench_group, ["create", "Airline agent"])

        plan_result = runner.invoke(workbench_group, [
            "plan", "Add a flight status tool", "--json",
        ])
        plan_data = json.loads(plan_result.output)
        plan_id = plan_data["data"]["plan"]["plan_id"]

        result = runner.invoke(workbench_group, ["apply", plan_id])
        assert result.exit_code == 0, result.output
        assert "Draft v2" in result.output

    def test_apply_json(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace(tmp_path)

        runner.invoke(workbench_group, ["create", "Airline agent"])
        plan_result = runner.invoke(workbench_group, [
            "plan", "Add a flight status tool", "--json",
        ])
        plan_id = json.loads(plan_result.output)["data"]["plan"]["plan_id"]

        result = runner.invoke(workbench_group, ["apply", plan_id, "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "ok"
        assert payload["data"]["project"]["version"] == 2


class TestWorkbenchTest:
    def test_validation_runs(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace(tmp_path)

        runner.invoke(workbench_group, ["create", "Airline agent"])
        result = runner.invoke(workbench_group, ["test"])
        assert result.exit_code == 0, result.output
        assert "Validation" in result.output

    def test_validation_json(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace(tmp_path)

        runner.invoke(workbench_group, ["create", "Airline agent"])
        result = runner.invoke(workbench_group, ["test", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "ok"


class TestWorkbenchRollback:
    def test_rollback_creates_new_version(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace(tmp_path)

        runner.invoke(workbench_group, ["create", "Airline agent"])
        plan_result = runner.invoke(workbench_group, [
            "plan", "Add a flight status tool", "--json",
        ])
        plan_id = json.loads(plan_result.output)["data"]["plan"]["plan_id"]
        runner.invoke(workbench_group, ["apply", plan_id])

        result = runner.invoke(workbench_group, ["rollback", "1"])
        assert result.exit_code == 0, result.output
        assert "Rolled back" in result.output
        assert "v1" in result.output


class TestWorkbenchList:
    def test_list_empty(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace(tmp_path)

        result = runner.invoke(workbench_group, ["list"])
        assert result.exit_code == 0, result.output

    def test_list_with_projects(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace(tmp_path)

        runner.invoke(workbench_group, ["create", "Agent A"])
        runner.invoke(workbench_group, ["create", "Agent B"])
        result = runner.invoke(workbench_group, ["list"])
        assert result.exit_code == 0, result.output
        assert "Workbench Projects" in result.output

    def test_list_json(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace(tmp_path)

        runner.invoke(workbench_group, ["create", "Agent A"])
        result = runner.invoke(workbench_group, ["list", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "ok"
        assert isinstance(payload["data"], list)
        assert len(payload["data"]) >= 1


class TestWorkbenchExport:
    def test_export_writes_yaml(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace(tmp_path)

        runner.invoke(workbench_group, ["create", "Flight agent"])
        plan_result = runner.invoke(workbench_group, [
            "plan", "Add a flight status tool", "--json",
        ])
        plan_id = json.loads(plan_result.output)["data"]["plan"]["plan_id"]
        runner.invoke(workbench_group, ["apply", plan_id])

        result = runner.invoke(workbench_group, ["export"])
        assert result.exit_code == 0, result.output
        assert "workbench_candidate.yaml" in result.output

        candidate = tmp_path / "configs" / "workbench_candidate.yaml"
        assert candidate.exists()
        config = yaml.safe_load(candidate.read_text(encoding="utf-8"))
        assert isinstance(config, dict)

    def test_export_custom_path(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace(tmp_path)

        runner.invoke(workbench_group, ["create", "Flight agent"])
        out_path = str(tmp_path / "custom" / "agent.yaml")
        result = runner.invoke(workbench_group, ["export", "-o", out_path])
        assert result.exit_code == 0, result.output
        assert Path(out_path).exists()

    def test_export_json(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace(tmp_path)

        runner.invoke(workbench_group, ["create", "Flight agent"])
        result = runner.invoke(workbench_group, ["export", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "ok"
        assert "config_path" in payload["data"]
        assert "config" in payload["data"]


class TestWorkbenchBuild:
    def test_build_mock_stream_json(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace(tmp_path)

        result = runner.invoke(workbench_group, [
            "build", "Build an airline support agent",
            "--mock", "--output-format", "stream-json",
        ])
        assert result.exit_code == 0, result.output
        lines = [l for l in result.output.strip().splitlines() if l.strip()]
        assert len(lines) >= 1
        first = json.loads(lines[0])
        assert "event" in first

    def test_build_mock_text(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace(tmp_path)

        result = runner.invoke(workbench_group, [
            "build", "Build an airline support agent", "--mock",
        ])
        assert result.exit_code == 0, result.output
        assert "[workbench]" in result.output

    def test_build_mock_json(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace(tmp_path)

        result = runner.invoke(workbench_group, [
            "build", "Build a travel agent",
            "--mock", "--json",
        ])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "ok"
        assert "events" in payload["data"]
        assert "final" in payload["data"]


class TestWorkbenchIterate:
    def test_iterate_mock(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace(tmp_path)

        build_result = runner.invoke(workbench_group, [
            "build", "Build an airline agent", "--mock", "--json",
        ])
        assert build_result.exit_code == 0, build_result.output

        result = runner.invoke(workbench_group, [
            "iterate", "Add a guardrail for PII", "--mock",
        ])
        assert result.exit_code == 0, result.output
        assert "[workbench]" in result.output


class TestWorkbenchCancel:
    def test_cancel_no_active_run(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace(tmp_path)

        runner.invoke(workbench_group, ["create", "Test agent"])
        result = runner.invoke(workbench_group, ["cancel"])
        assert result.exit_code != 0
        assert "No active run" in result.output


class TestWorkbenchHelp:
    def test_help_shows_commands(self, runner: CliRunner) -> None:
        result = runner.invoke(workbench_group, ["--help"])
        assert result.exit_code == 0
        assert "workbench" in result.output.lower()
        assert "create" in result.output
        assert "build" in result.output
        assert "iterate" in result.output
        assert "plan" in result.output
        assert "bridge" in result.output
        assert "export" in result.output
