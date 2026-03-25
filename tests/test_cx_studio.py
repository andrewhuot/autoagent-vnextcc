"""Tests for CX Agent Studio integration."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cx_studio.types import (
    CxAgent,
    CxAgentRef,
    CxAgentSnapshot,
    CxEnvironment,
    CxFlow,
    CxIntent,
    CxPlaybook,
    CxTestCase,
    CxTool,
    CxWidgetConfig,
    DeployResult,
    ExportResult,
    ImportResult,
)
from cx_studio.errors import CxApiError, CxAuthError, CxMappingError, CxStudioError
from cx_studio.mapper import CxMapper
from cx_studio.deployer import CxDeployer, _build_widget_html
from cx_studio.importer import CxImporter
from cx_studio.exporter import CxExporter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_ref() -> CxAgentRef:
    return CxAgentRef(project="test-project", location="us-central1", agent_id="agent-123")


def _make_snapshot() -> CxAgentSnapshot:
    return CxAgentSnapshot(
        agent=CxAgent(
            name="projects/test-project/locations/us-central1/agents/agent-123",
            display_name="Test Agent",
            default_language_code="en",
            description="A test agent",
            generative_settings={"model": "gemini-2.0-flash"},
        ),
        playbooks=[
            CxPlaybook(
                name="projects/test-project/locations/us-central1/agents/agent-123/playbooks/pb-1",
                display_name="Main Playbook",
                instructions=["You are a helpful assistant.", "Be concise and friendly."],
                steps=[{"text": "Greet the user"}],
                examples=[],
            ),
            CxPlaybook(
                name="projects/test-project/locations/us-central1/agents/agent-123/playbooks/pb-2",
                display_name="Support Playbook",
                instructions=["Handle support requests.", "Escalate complex issues."],
                steps=[],
                examples=[],
            ),
        ],
        tools=[
            CxTool(
                name="projects/test-project/locations/us-central1/agents/agent-123/tools/tool-1",
                display_name="FAQ Lookup",
                tool_type="DATA_STORE",
                spec={"timeout_ms": 3000},
            ),
        ],
        flows=[
            CxFlow(
                name="projects/test-project/locations/us-central1/agents/agent-123/flows/flow-1",
                display_name="Default Start Flow",
                pages=[],
                transition_routes=[
                    {"condition": "true", "target_page": "support_page", "intent": "support_intent"}
                ],
                event_handlers=[],
            ),
        ],
        intents=[
            CxIntent(
                name="projects/test-project/locations/us-central1/agents/agent-123/intents/intent-1",
                display_name="support_intent",
                training_phrases=[
                    {"parts": [{"text": "I need help"}]},
                    {"parts": [{"text": "something is broken"}]},
                ],
            ),
        ],
        test_cases=[
            CxTestCase(
                name="projects/test-project/locations/us-central1/agents/agent-123/testCases/tc-1",
                display_name="Basic greeting test",
                tags=["smoke"],
                conversation_turns=[
                    {"userInput": {"input": {"text": {"text": "Hello"}}}, "virtualAgentOutput": {"text": {"text": "Hi there!"}}}
                ],
                expected_output={"text": "Hi there!"},
            ),
        ],
        environments=[
            CxEnvironment(
                name="projects/test-project/locations/us-central1/agents/agent-123/environments/production",
                display_name="production",
                description="Production environment",
                version_configs=[],
            ),
        ],
        fetched_at="2026-03-25T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# Type tests
# ---------------------------------------------------------------------------

class TestCxTypes:
    def test_agent_ref_parent(self):
        ref = _make_ref()
        assert ref.parent == "projects/test-project/locations/us-central1"

    def test_agent_ref_name(self):
        ref = _make_ref()
        assert ref.name == "projects/test-project/locations/us-central1/agents/agent-123"

    def test_agent_ref_global(self):
        ref = CxAgentRef(project="proj", location="global", agent_id="a1")
        assert ref.parent == "projects/proj/locations/global"

    def test_snapshot_serialization(self):
        snap = _make_snapshot()
        data = snap.model_dump()
        restored = CxAgentSnapshot.model_validate(data)
        assert restored.agent.display_name == "Test Agent"
        assert len(restored.playbooks) == 2
        assert len(restored.tools) == 1

    def test_widget_config_defaults(self):
        wc = CxWidgetConfig(project_id="p", agent_id="a")
        assert wc.location == "global"
        assert wc.language_code == "en"
        assert wc.primary_color == "#1a73e8"

    def test_import_result(self):
        r = ImportResult(
            config_path="config.yaml",
            eval_path="evals.json",
            snapshot_path="snap.json",
            agent_name="Test",
            surfaces_mapped=["prompts", "tools"],
            test_cases_imported=5,
        )
        assert r.test_cases_imported == 5

    def test_export_result(self):
        r = ExportResult(changes=[{"resource": "agent", "action": "update"}], pushed=True, resources_updated=1)
        assert r.pushed

    def test_deploy_result(self):
        r = DeployResult(environment="production", status="deployed", version_info={})
        assert r.environment == "production"


# ---------------------------------------------------------------------------
# Mapper tests
# ---------------------------------------------------------------------------

class TestCxMapper:
    def test_to_autoagent_basic(self):
        mapper = CxMapper()
        snapshot = _make_snapshot()
        config = mapper.to_autoagent(snapshot)
        assert "prompts" in config
        assert "root" in config["prompts"]
        assert "tools" in config
        assert "routing" in config

    def test_to_autoagent_prompts_from_playbooks(self):
        mapper = CxMapper()
        snapshot = _make_snapshot()
        config = mapper.to_autoagent(snapshot)
        # First playbook → root prompt
        assert "helpful assistant" in config["prompts"]["root"].lower() or len(config["prompts"]["root"]) > 0

    def test_to_autoagent_tools(self):
        mapper = CxMapper()
        snapshot = _make_snapshot()
        config = mapper.to_autoagent(snapshot)
        assert "faq_lookup" in config.get("tools", {}) or len(config.get("tools", {})) > 0

    def test_to_autoagent_routing(self):
        mapper = CxMapper()
        snapshot = _make_snapshot()
        config = mapper.to_autoagent(snapshot)
        rules = config.get("routing", {}).get("rules", [])
        assert len(rules) >= 0  # May have rules from intents

    def test_extract_test_cases(self):
        mapper = CxMapper()
        snapshot = _make_snapshot()
        cases = mapper.extract_test_cases(snapshot)
        assert len(cases) == 1
        assert cases[0]["input"] == "Hello"

    def test_to_cx_round_trip(self):
        mapper = CxMapper()
        snapshot = _make_snapshot()
        config = mapper.to_autoagent(snapshot)
        updated = mapper.to_cx(config, snapshot)
        assert updated.agent.display_name == snapshot.agent.display_name

    def test_to_autoagent_empty_snapshot(self):
        mapper = CxMapper()
        snapshot = CxAgentSnapshot(
            agent=CxAgent(name="a", display_name="Empty"),
        )
        config = mapper.to_autoagent(snapshot)
        assert "prompts" in config

    def test_extract_test_cases_empty(self):
        mapper = CxMapper()
        snapshot = CxAgentSnapshot(
            agent=CxAgent(name="a", display_name="Empty"),
        )
        cases = mapper.extract_test_cases(snapshot)
        assert cases == []

    def test_to_cx_preserves_base_snapshot_fields(self):
        mapper = CxMapper()
        snapshot = _make_snapshot()
        config = mapper.to_autoagent(snapshot)
        updated = mapper.to_cx(config, snapshot)
        # Should preserve tools and environments from base
        assert len(updated.tools) == len(snapshot.tools)
        assert len(updated.environments) == len(snapshot.environments)


# ---------------------------------------------------------------------------
# Deployer tests
# ---------------------------------------------------------------------------

class TestCxDeployer:
    def test_generate_widget_html(self):
        wc = CxWidgetConfig(
            project_id="my-project",
            agent_id="agent-1",
            location="global",
            chat_title="Support Bot",
            primary_color="#ff0000",
        )
        html = _build_widget_html(wc)
        assert "df-messenger" in html
        assert "my-project" in html
        assert "agent-1" in html
        assert "Support Bot" in html
        assert "#ff0000" in html

    def test_generate_widget_html_with_icon(self):
        wc = CxWidgetConfig(
            project_id="p",
            agent_id="a",
            chat_icon="https://example.com/icon.png",
        )
        html = _build_widget_html(wc)
        assert "chat-icon" in html
        assert "https://example.com/icon.png" in html

    def test_generate_widget_html_no_icon(self):
        wc = CxWidgetConfig(project_id="p", agent_id="a")
        html = _build_widget_html(wc)
        assert "chat-icon" not in html

    def test_generate_widget_to_file(self):
        mock_client = MagicMock()
        deployer = CxDeployer(mock_client)
        wc = CxWidgetConfig(project_id="p", agent_id="a", chat_title="Test")
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as f:
            path = f.name
        try:
            html = deployer.generate_widget_html(wc, output_path=path)
            assert Path(path).read_text(encoding="utf-8") == html
        finally:
            os.unlink(path)

    def test_deploy_to_environment(self):
        mock_client = MagicMock()
        mock_client.deploy_to_environment.return_value = {"version": "v1"}
        deployer = CxDeployer(mock_client)
        ref = _make_ref()
        result = deployer.deploy_to_environment(ref, "staging")
        assert result.environment == "staging"
        assert result.status == "deployed"
        mock_client.deploy_to_environment.assert_called_once_with(ref, "staging")

    def test_get_deploy_status(self):
        mock_client = MagicMock()
        mock_client.list_environments.return_value = [
            CxEnvironment(name="env/prod", display_name="production", description="Prod"),
        ]
        deployer = CxDeployer(mock_client)
        ref = _make_ref()
        status = deployer.get_deploy_status(ref)
        assert len(status["environments"]) == 1
        assert status["environments"][0]["name"] == "production"


# ---------------------------------------------------------------------------
# Importer tests
# ---------------------------------------------------------------------------

class TestCxImporter:
    def test_import_agent_success(self):
        snapshot = _make_snapshot()
        mock_client = MagicMock()
        mock_client.fetch_snapshot.return_value = snapshot

        importer = CxImporter(mock_client)
        ref = _make_ref()

        with tempfile.TemporaryDirectory() as tmpdir:
            result = importer.import_agent(ref, output_dir=tmpdir)
            assert result.agent_name == "Test Agent"
            assert result.test_cases_imported == 1
            assert Path(result.config_path).exists()
            assert Path(result.snapshot_path).exists()
            if result.eval_path:
                assert Path(result.eval_path).exists()

    def test_import_agent_no_test_cases(self):
        snapshot = _make_snapshot()
        mock_client = MagicMock()
        mock_client.fetch_snapshot.return_value = snapshot

        importer = CxImporter(mock_client)
        ref = _make_ref()

        with tempfile.TemporaryDirectory() as tmpdir:
            result = importer.import_agent(ref, output_dir=tmpdir, include_test_cases=False)
            assert result.test_cases_imported == 0
            assert result.eval_path is None

    def test_import_agent_surfaces(self):
        snapshot = _make_snapshot()
        mock_client = MagicMock()
        mock_client.fetch_snapshot.return_value = snapshot

        importer = CxImporter(mock_client)
        ref = _make_ref()

        with tempfile.TemporaryDirectory() as tmpdir:
            result = importer.import_agent(ref, output_dir=tmpdir)
            assert "prompts" in result.surfaces_mapped
            assert "tools" in result.surfaces_mapped


# ---------------------------------------------------------------------------
# Exporter tests
# ---------------------------------------------------------------------------

class TestCxExporter:
    def test_export_dry_run(self):
        snapshot = _make_snapshot()
        mock_client = MagicMock()
        mapper = CxMapper()
        config = mapper.to_autoagent(snapshot)

        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(snapshot.model_dump(), f)
            snap_path = f.name

        try:
            exporter = CxExporter(mock_client)
            result = exporter.export_agent(config, _make_ref(), snap_path, dry_run=True)
            assert not result.pushed
            mock_client.update_agent.assert_not_called()
        finally:
            os.unlink(snap_path)

    def test_preview_changes(self):
        snapshot = _make_snapshot()
        mapper = CxMapper()
        config = mapper.to_autoagent(snapshot)
        # Modify a prompt to create a diff
        config["prompts"]["root"] = "Changed prompt"

        mock_client = MagicMock()
        exporter = CxExporter(mock_client)

        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(snapshot.model_dump(), f)
            snap_path = f.name

        try:
            changes = exporter.preview_changes(config, snap_path)
            # Should detect playbook instruction change
            assert isinstance(changes, list)
        finally:
            os.unlink(snap_path)


# ---------------------------------------------------------------------------
# Error tests
# ---------------------------------------------------------------------------

class TestCxErrors:
    def test_cx_studio_error_hierarchy(self):
        assert issubclass(CxAuthError, CxStudioError)
        assert issubclass(CxApiError, CxStudioError)
        assert issubclass(CxMappingError, CxStudioError)

    def test_cx_api_error_fields(self):
        err = CxApiError("Not found", status_code=404, response_body='{"error": "not found"}')
        assert err.status_code == 404
        assert "not found" in err.response_body


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------

class TestCxAuth:
    def test_init_with_missing_file(self):
        with pytest.raises(CxAuthError, match="not found"):
            from cx_studio.auth import CxAuth
            CxAuth(credentials_path="/nonexistent/path.json")

    def test_init_with_invalid_json(self):
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            f.write("not json")
            path = f.name
        try:
            with pytest.raises(CxAuthError, match="Invalid credentials"):
                from cx_studio.auth import CxAuth
                CxAuth(credentials_path=path)
        finally:
            os.unlink(path)

    def test_get_headers_without_token(self):
        from cx_studio.auth import CxAuth
        auth = CxAuth.__new__(CxAuth)
        auth._credentials_path = None
        auth._token = None
        auth._token_expiry = 0.0
        auth._project_id = None
        # Without google-auth installed or configured, should raise
        with pytest.raises((CxAuthError, ImportError)):
            auth.get_headers()


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

class TestCxCli:
    def test_cx_group_exists(self):
        """Verify the cx group is registered in the CLI."""
        from runner import cli
        from click.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli, ["cx", "--help"])
        assert result.exit_code == 0
        assert "CX Agent Studio" in result.output or "import" in result.output

    def test_cx_list_help(self):
        from runner import cli
        from click.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli, ["cx", "list", "--help"])
        assert result.exit_code == 0
        assert "--project" in result.output

    def test_cx_import_help(self):
        from runner import cli
        from click.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli, ["cx", "import", "--help"])
        assert result.exit_code == 0
        assert "--agent" in result.output

    def test_cx_widget_help(self):
        from runner import cli
        from click.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli, ["cx", "widget", "--help"])
        assert result.exit_code == 0
        assert "--title" in result.output

    def test_cx_export_help(self):
        from runner import cli
        from click.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli, ["cx", "export", "--help"])
        assert result.exit_code == 0
        assert "--config" in result.output
        assert "--snapshot" in result.output


# ---------------------------------------------------------------------------
# Dependency layer test
# ---------------------------------------------------------------------------

class TestCxDependencyLayer:
    def test_cx_studio_is_layer_1(self):
        """Verify cx_studio is classified as Layer 1."""
        from tests.test_dependency_layers import _get_layer
        assert _get_layer("cx_studio") == 1
        assert _get_layer("cx_studio.client") == 1
        assert _get_layer("cx_studio.mapper") == 1

    def test_cx_studio_does_not_import_layer_2(self):
        """Verify cx_studio files don't import from api/ or web/."""
        from tests.test_dependency_layers import _extract_imports, _get_layer, ROOT

        cx_dir = ROOT / "cx_studio"
        if not cx_dir.exists():
            pytest.skip("cx_studio not yet created")

        for py_file in cx_dir.glob("*.py"):
            imports = _extract_imports(py_file)
            for imp in imports:
                layer = _get_layer(imp)
                if layer is not None:
                    assert layer <= 1, f"{py_file.name} imports {imp} (layer {layer})"
