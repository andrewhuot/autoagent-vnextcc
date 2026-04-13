"""CLI coverage for the integrated terminal Workbench workflow.

Combines Codex lifecycle tests (build/show/save/iterate — authoritative
materialization semantics) with Claude-ported tests for the broader command
surface (create/list/plan/apply/test/rollback/cancel/bridge).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from builder.workbench import WorkbenchService, WorkbenchStore, _infer_domain
from cli.workbench import workbench_group
from cli.workspace import AgentLabWorkspace
from evals import EvalRunner
from runner import cli


@pytest.fixture()
def runner() -> CliRunner:
    """Provide an isolated Click runner for CLI command tests."""
    return CliRunner()


def _seed_workspace(root: Path) -> AgentLabWorkspace:
    """Create a minimal workspace so Workbench targets real AgentLab paths."""
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


def _seed_workspace_minimal(root: Path) -> None:
    """Create a minimal workspace for commands that only need service access."""
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


def _json_payload(output: str) -> dict:
    """Parse a standard CLI JSON envelope from command output."""
    return json.loads(output)


def _make_service(root: Path) -> WorkbenchService:
    """Build a WorkbenchService for direct assertions."""
    store_path = root / ".agentlab" / "workbench_projects.json"
    return WorkbenchService(WorkbenchStore(path=store_path))


# ---------------------------------------------------------------------------
# Codex lifecycle tests — validate authoritative save/handoff semantics
# ---------------------------------------------------------------------------


class TestWorkbenchDomainInference:
    """Regression coverage for prompt-domain detection used by Workbench."""

    def test_phone_billing_prompt_does_not_match_it_pronoun(self) -> None:
        brief = (
            "Build a Verizon-like phone-company support agent. It should explain bills, "
            "plan charges, fees, surcharges, promo credits, and roaming confusion."
        )

        assert _infer_domain(brief) == "Phone Billing Support"


class TestWorkbenchBuildLifecycle:
    """Build → JSON: verify bridge readiness after streaming build."""

    def test_workbench_build_json_creates_eval_candidate_readiness(
        self, runner: CliRunner,
    ) -> None:
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


class TestWorkbenchShowLifecycle:
    """Show: verify readiness rendering without saving anything."""

    def test_workbench_show_text_renders_readiness_and_next_step(
        self, runner: CliRunner,
    ) -> None:
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
            assert "Execution:" in result.output
            assert "mock" in result.output
            assert "Save candidate before Eval" in result.output
            assert "Eval candidate not ready" in result.output
            assert "agentlab workbench save" in result.output
            assert "structural validation is not an eval result" in result.output


class TestWorkbenchSaveLifecycle:
    """Save: verify materialization writes real files and transitions readiness."""

    def test_workbench_save_materializes_candidate_for_eval(
        self, runner: CliRunner,
    ) -> None:
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
            generated_cases = yaml.safe_load(Path(save_result["eval_cases_path"]).read_text(encoding="utf-8"))
            assert isinstance(generated_cases, dict)
            assert isinstance(generated_cases["cases"], list)
            assert generated_cases["cases"]
            assert any("airline support" in case["user_message"].lower() for case in generated_cases["cases"])
            loaded_cases = EvalRunner(cases_dir=str(Path("evals") / "cases")).load_cases()
            assert any("airline support" in case.user_message.lower() for case in loaded_cases)
            assert data["bridge"]["evaluation"]["readiness_state"] == "ready_for_eval"
            assert data["bridge"]["optimization"]["readiness_state"] == "awaiting_eval_run"
            assert data["eval_request"]["config_path"] == save_result["config_path"]
            assert data["optimize_request_template"]["eval_run_id"] is None
            saved_config = yaml.safe_load(Path(save_result["config_path"]).read_text(encoding="utf-8"))
            assert saved_config["journey_build"]["source_prompt"] == (
                "Build an airline support agent with flight status tools."
            )

            refreshed = AgentLabWorkspace(root=workspace.root, metadata=workspace.metadata)
            active = refreshed.resolve_active_config()
            assert active is not None
            assert str(active.path) == save_result["config_path"]

            bridge = runner.invoke(
                cli,
                ["workbench", "bridge", "--eval-run-id", "eval-run-123", "--json"],
            )
            assert bridge.exit_code == 0, bridge.output
            bridge_payload = _json_payload(bridge.output)
            bridge_data = bridge_payload["data"]
            assert bridge_payload["next"] == "agentlab optimize --cycles 3"
            assert bridge_data["candidate"]["config_path"] == save_result["config_path"]
            assert bridge_data["candidate"]["eval_cases_path"] == save_result["eval_cases_path"]
            assert bridge_data["evaluation"]["readiness_state"] == "ready_for_eval"
            assert bridge_data["optimization"]["readiness_state"] == "ready_for_optimize"
            assert bridge_data["optimization"]["request_template"]["eval_run_id"] == "eval-run-123"

    def test_workbench_save_preserves_billing_routing_and_eval_cases(
        self, runner: CliRunner,
    ) -> None:
        with runner.isolated_filesystem():
            _seed_workspace(Path.cwd())
            prompt = (
                "Build a Verizon-like phone-company support agent. It should explain bills, "
                "plan charges, activation fees, surcharges, taxes, device payments, promo "
                "credits, roaming, and autopay discounts."
            )
            build = runner.invoke(
                cli,
                [
                    "workbench",
                    "build",
                    prompt,
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
            save_result = payload["data"]["save_result"]
            saved_config = yaml.safe_load(Path(save_result["config_path"]).read_text(encoding="utf-8"))
            support_rule = next(
                rule for rule in saved_config["routing"]["rules"] if rule["specialist"] == "support"
            )
            orders_rule = next(
                rule for rule in saved_config["routing"]["rules"] if rule["specialist"] == "orders"
            )
            support_keywords = set(support_rule["keywords"])
            orders_keywords = set(orders_rule["keywords"])

            assert saved_config["journey_build"]["source_prompt"] == prompt
            assert saved_config["tools"]["faq"]["enabled"] is True
            assert "billing" in support_keywords
            assert "autopay" in support_keywords
            assert "billing" not in orders_keywords
            assert "charges" not in orders_keywords

            generated_cases = yaml.safe_load(Path(save_result["eval_cases_path"]).read_text(encoding="utf-8"))
            messages = " ".join(case["user_message"].lower() for case in generated_cases["cases"])
            assert "bills" in messages
            assert "promo credit" in messages
            assert any(case.get("safety_probe") for case in generated_cases["cases"])


class TestWorkbenchIterateLifecycle:
    """Iterate: verify follow-up turn continues the same project."""

    def test_workbench_iterate_json_continues_latest_project(
        self, runner: CliRunner,
    ) -> None:
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


# ---------------------------------------------------------------------------
# Claude-ported tests — validate broader command surface
# ---------------------------------------------------------------------------


class TestWorkbenchCreate:
    def test_create_text_output(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace_minimal(tmp_path)

        result = runner.invoke(workbench_group, ["create", "Build a flight agent"])
        assert result.exit_code == 0, result.output
        assert "project created" in result.output.lower()
        assert "wb-" in result.output

    def test_create_json_output(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace_minimal(tmp_path)

        result = runner.invoke(workbench_group, ["create", "Build a support agent", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "ok"
        assert "project" in payload["data"]
        assert payload["data"]["project"]["project_id"].startswith("wb-")

    def test_create_with_target(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace_minimal(tmp_path)

        result = runner.invoke(workbench_group, ["create", "Agent for ADK", "--target", "adk"])
        assert result.exit_code == 0, result.output
        assert "adk" in result.output.lower()


class TestWorkbenchStatus:
    def test_status_default_project(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace_minimal(tmp_path)

        runner.invoke(workbench_group, ["create", "Test agent"])
        result = runner.invoke(workbench_group, ["status"])
        assert result.exit_code == 0, result.output
        assert "Workbench Status" in result.output

    def test_status_json(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace_minimal(tmp_path)

        runner.invoke(workbench_group, ["create", "Test agent"])
        result = runner.invoke(workbench_group, ["status", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "ok"

    def test_bare_workbench_shows_status(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace_minimal(tmp_path)

        runner.invoke(workbench_group, ["create", "Test agent"])
        result = runner.invoke(workbench_group, [])
        assert result.exit_code == 0, result.output
        assert "Workbench Status" in result.output


class TestWorkbenchPlanApply:
    def test_plan_creates_operations(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace_minimal(tmp_path)

        runner.invoke(workbench_group, ["create", "Airline agent"])
        result = runner.invoke(workbench_group, ["plan", "Add a flight status tool"])
        assert result.exit_code == 0, result.output
        assert "Change Plan" in result.output
        assert "plan-" in result.output

    def test_plan_json(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace_minimal(tmp_path)

        runner.invoke(workbench_group, ["create", "Airline agent"])
        result = runner.invoke(workbench_group, ["plan", "Add a flight status tool", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "ok"
        assert "plan" in payload["data"]

    def test_apply_increments_version(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace_minimal(tmp_path)

        runner.invoke(workbench_group, ["create", "Airline agent"])

        plan_result = runner.invoke(workbench_group, [
            "plan", "Add a flight status tool", "--json",
        ])
        plan_data = json.loads(plan_result.output)
        plan_id = plan_data["data"]["plan"]["plan_id"]

        result = runner.invoke(workbench_group, ["apply", plan_id])
        assert result.exit_code == 0, result.output
        assert "Draft v2" in result.output


class TestWorkbenchTest:
    def test_validation_runs(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace_minimal(tmp_path)

        runner.invoke(workbench_group, ["create", "Airline agent"])
        result = runner.invoke(workbench_group, ["test"])
        assert result.exit_code == 0, result.output
        assert "Validation" in result.output

    def test_validation_json(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace_minimal(tmp_path)

        runner.invoke(workbench_group, ["create", "Airline agent"])
        result = runner.invoke(workbench_group, ["test", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "ok"


class TestWorkbenchRollback:
    def test_rollback_creates_new_version(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace_minimal(tmp_path)

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
        _seed_workspace_minimal(tmp_path)

        result = runner.invoke(workbench_group, ["list"])
        assert result.exit_code == 0, result.output

    def test_list_with_projects(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace_minimal(tmp_path)

        runner.invoke(workbench_group, ["create", "Agent A"])
        runner.invoke(workbench_group, ["create", "Agent B"])
        result = runner.invoke(workbench_group, ["list"])
        assert result.exit_code == 0, result.output
        assert "Workbench Projects" in result.output

    def test_list_json(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace_minimal(tmp_path)

        runner.invoke(workbench_group, ["create", "Agent A"])
        result = runner.invoke(workbench_group, ["list", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "ok"
        assert isinstance(payload["data"], list)
        assert len(payload["data"]) >= 1


class TestWorkbenchCancel:
    def test_cancel_no_active_run(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace_minimal(tmp_path)

        runner.invoke(workbench_group, ["create", "Test agent"])
        result = runner.invoke(workbench_group, ["cancel"])
        assert result.exit_code != 0
        assert "No active run" in result.output


class TestWorkbenchBridge:
    def test_bridge_after_build(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            _seed_workspace(Path.cwd())
            build = runner.invoke(
                cli,
                [
                    "workbench", "build",
                    "Build a flight status agent",
                    "--mock", "--max-iterations", "1", "--json",
                ],
            )
            assert build.exit_code == 0, build.output

            result = runner.invoke(cli, ["workbench", "bridge"])
            assert result.exit_code == 0, result.output
            assert "Bridge Status" in result.output

    def test_bridge_json(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            _seed_workspace(Path.cwd())
            build = runner.invoke(
                cli,
                [
                    "workbench", "build",
                    "Build a flight status agent",
                    "--mock", "--max-iterations", "1", "--json",
                ],
            )
            assert build.exit_code == 0, build.output

            result = runner.invoke(cli, ["workbench", "bridge", "--json"])
            assert result.exit_code == 0, result.output
            payload = _json_payload(result.output)
            assert payload["status"] == "ok"
            assert "evaluation" in payload["data"]
            assert "optimization" in payload["data"]


class TestWorkbenchBuildStreaming:
    def test_build_mock_stream_json(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace_minimal(tmp_path)

        result = runner.invoke(workbench_group, [
            "build", "Build an airline support agent",
            "--mock", "--output-format", "stream-json",
        ])
        assert result.exit_code == 0, result.output
        lines = [line for line in result.output.strip().splitlines() if line.strip()]
        assert len(lines) >= 1
        first = json.loads(lines[0])
        assert "event" in first

    def test_build_mock_text(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace_minimal(tmp_path)

        result = runner.invoke(workbench_group, [
            "build", "Build an airline support agent", "--mock",
        ])
        assert result.exit_code == 0, result.output
        assert "[workbench]" in result.output

    def test_build_require_live_refuses_mock_builder(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_workspace_minimal(tmp_path)

        result = runner.invoke(workbench_group, [
            "build", "Build an airline support agent", "--mock", "--require-live", "--json",
        ])

        assert result.exit_code != 0
        assert "Live Workbench required" in result.output


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
        assert "save" in result.output
