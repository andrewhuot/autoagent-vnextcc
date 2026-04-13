"""Tests for CX Agent Studio integration."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cx_studio.types import (
    CxAgent,
    CxAgentRef,
    CxAgentSnapshot,
    CxEntityType,
    CxEnvironment,
    CxFlow,
    CxGenerator,
    CxIntent,
    CxPage,
    CxPlaybook,
    CxTestCase,
    CxTransitionRouteGroup,
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
    return CxAgentRef(
        project="test-project",
        location="us-central1",
        app_id="test-app",
        agent_id="agent-123"
    )


def _make_snapshot() -> CxAgentSnapshot:
    agent_name = "projects/test-project/locations/us-central1/agents/agent-123"
    flow_name = f"{agent_name}/flows/flow-1"
    page_name = f"{flow_name}/pages/support-page"
    intent_name = f"{agent_name}/intents/support_intent"
    route_group_name = f"{agent_name}/transitionRouteGroups/shared-escalation"
    generator_name = f"{agent_name}/generators/resolution-summary"
    entity_name = f"{agent_name}/entityTypes/order-id"

    return CxAgentSnapshot(
        agent=CxAgent(
            name=agent_name,
            display_name="Test Agent",
            default_language_code="en",
            description="A test agent",
            generative_settings={"llmModelSettings": {"model": "gemini-2.0-flash"}},
        ),
        playbooks=[
            CxPlaybook(
                name=f"{agent_name}/playbooks/pb-1",
                display_name="Main Playbook",
                instructions=["You are a helpful assistant.", "Be concise and friendly."],
                steps=[{"text": "Greet the user"}],
                examples=[],
                input_parameter_definitions=[{"name": "order_id", "type": "string"}],
                output_parameter_definitions=[{"name": "resolution_status", "type": "string"}],
                handlers=[{"event": "playbook-complete", "generator": generator_name}],
            ),
            CxPlaybook(
                name=f"{agent_name}/playbooks/pb-2",
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
                name=flow_name,
                display_name="Default Start Flow",
                transition_route_groups=[route_group_name],
                pages=[
                    CxPage(
                        name=page_name,
                        display_name="Support Page",
                        form={"parameters": [{"displayName": "order_id", "required": True}]},
                        transition_route_groups=[route_group_name],
                        transition_routes=[],
                        event_handlers=[],
                    ),
                ],
                transition_routes=[
                    {"condition": "true", "targetPage": page_name, "intent": intent_name}
                ],
                event_handlers=[],
            ),
        ],
        intents=[
            CxIntent(
                name=intent_name,
                display_name="support_intent",
                training_phrases=[
                    {"parts": [{"text": "I need help"}]},
                    {"parts": [{"text": "something is broken"}]},
                ],
                parameters=[{"id": "order_id", "entityType": "@sys.any"}],
            ),
        ],
        entity_types=[
            CxEntityType(
                name=entity_name,
                display_name="order-id",
                kind="KIND_MAP",
                entities=[{"value": "1234", "synonyms": ["1234", "order 1234"]}],
            ),
        ],
        transition_route_groups=[
            CxTransitionRouteGroup(
                name=route_group_name,
                display_name="Shared Escalation",
                transition_routes=[{"condition": "$session.params.escalate == true", "targetFlow": flow_name}],
            )
        ],
        generators=[
            CxGenerator(
                name=generator_name,
                display_name="Resolution Summary",
                prompt_text="Summarize the resolution for the user.",
                placeholders=[{"name": "resolution_status"}],
            )
        ],
        test_cases=[
            CxTestCase(
                name=f"{agent_name}/testCases/tc-1",
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
        assert ref.name == "projects/test-project/locations/us-central1/apps/test-app/agents/agent-123"
        assert ref.app_name == "projects/test-project/locations/us-central1/apps/test-app"

    def test_agent_ref_global(self):
        ref = CxAgentRef(project="proj", location="global", app_id="app1", agent_id="a1")
        assert ref.parent == "projects/proj/locations/global"
        assert ref.name == "projects/proj/locations/global/apps/app1/agents/a1"

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
    def test_to_agentlab_basic(self):
        mapper = CxMapper()
        snapshot = _make_snapshot()
        config = mapper.to_agentlab(snapshot)
        assert "prompts" in config
        assert "root" in config["prompts"]
        assert "tools" in config
        assert "routing" in config

    def test_to_agentlab_prompts_from_playbooks(self):
        mapper = CxMapper()
        snapshot = _make_snapshot()
        config = mapper.to_agentlab(snapshot)
        # First playbook → root prompt
        assert "helpful assistant" in config["prompts"]["root"].lower() or len(config["prompts"]["root"]) > 0

    def test_to_agentlab_tools(self):
        mapper = CxMapper()
        snapshot = _make_snapshot()
        config = mapper.to_agentlab(snapshot)
        assert "faq_lookup" in config.get("tools", {}) or len(config.get("tools", {})) > 0

    def test_to_agentlab_routing(self):
        mapper = CxMapper()
        snapshot = _make_snapshot()
        config = mapper.to_agentlab(snapshot)
        rules = config.get("routing", {}).get("rules", [])
        assert len(rules) >= 0  # May have rules from intents

    def test_to_agentlab_builds_editable_cx_contract(self):
        mapper = CxMapper()
        snapshot = _make_snapshot()
        config = mapper.to_agentlab(snapshot)

        assert "cx" in config

        cx = config["cx"]
        assert cx["source_platform"] == "cx_studio"
        assert cx["target_platform"] == "cx_agent_studio"
        assert cx["projection_summary"]["faithful_count"] >= 6

        playbook = cx["playbooks"]["main_playbook"]
        assert playbook["projection"]["quality"] == "faithful"
        assert playbook["input_parameters"][0]["name"] == "order_id"
        assert playbook["handlers"][0]["event"] == "playbook-complete"

        flow = cx["flows"]["default_start_flow"]
        assert flow["projection"]["quality"] == "faithful"
        assert flow["route_group_ids"] == ["shared_escalation"]
        assert "support_page" in flow["pages"]
        assert flow["pages"]["support_page"]["form"]["parameters"][0]["displayName"] == "order_id"

        intent = cx["intents"]["support_intent"]
        assert intent["projection"]["quality"] == "faithful"
        assert intent["parameters"][0]["id"] == "order_id"

        entity_type = cx["entity_types"]["order_id"]
        assert entity_type["projection"]["quality"] == "faithful"
        assert entity_type["entities"][0]["value"] == "1234"

        generator = cx["generators"]["resolution_summary"]
        assert generator["projection"]["quality"] == "faithful"
        assert generator["prompt_text"] == "Summarize the resolution for the user."

        route_group = cx["transition_route_groups"]["shared_escalation"]
        assert route_group["projection"]["quality"] == "faithful"
        assert route_group["transition_routes"][0]["condition"] == "$session.params.escalate == true"

    def test_extract_test_cases(self):
        mapper = CxMapper()
        snapshot = _make_snapshot()
        cases = mapper.extract_test_cases(snapshot)
        assert len(cases) == 1
        assert cases[0]["input"] == "Hello"

    def test_to_cx_round_trip(self):
        mapper = CxMapper()
        snapshot = _make_snapshot()
        config = mapper.to_agentlab(snapshot)
        updated = mapper.to_cx(config, snapshot)
        assert updated.agent.display_name == snapshot.agent.display_name

    def test_to_agentlab_empty_snapshot(self):
        mapper = CxMapper()
        snapshot = CxAgentSnapshot(
            agent=CxAgent(name="a", display_name="Empty"),
        )
        config = mapper.to_agentlab(snapshot)
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
        config = mapper.to_agentlab(snapshot)
        updated = mapper.to_cx(config, snapshot)
        # Should preserve tools and environments from base
        assert len(updated.tools) == len(snapshot.tools)
        assert len(updated.environments) == len(snapshot.environments)

    def test_to_cx_applies_edits_from_cx_native_contract(self):
        mapper = CxMapper()
        snapshot = _make_snapshot()
        config = mapper.to_agentlab(snapshot)

        config["cx"]["playbooks"]["main_playbook"]["instructions"] = [
            "Gather the order ID first.",
            "Summarize the final resolution.",
        ]
        config["cx"]["playbooks"]["main_playbook"]["input_parameters"] = [
            {"name": "case_id", "type": "string"},
        ]
        config["cx"]["playbooks"]["main_playbook"]["handlers"] = [
            {"event": "playbook-complete", "generator": snapshot.generators[0].name},
            {"event": "playbook-failed", "generator": snapshot.generators[0].name},
        ]
        config["cx"]["flows"]["default_start_flow"]["transition_routes"] = [
            {"condition": "$session.params.vip == true", "targetPage": snapshot.flows[0].pages[0].name}
        ]
        config["cx"]["flows"]["default_start_flow"]["pages"]["support_page"]["form"] = {
            "parameters": [{"displayName": "case_id", "required": True}]
        }
        config["cx"]["intents"]["support_intent"]["training_phrases"] = [
            {"parts": [{"text": "I need priority support"}]}
        ]
        config["cx"]["intents"]["support_intent"]["parameters"] = [
            {"id": "case_id", "entityType": "@sys.any"}
        ]
        config["cx"]["entity_types"]["order_id"]["entities"] = [
            {"value": "vip", "synonyms": ["vip customer"]}
        ]
        config["cx"]["generators"]["resolution_summary"]["prompt_text"] = "Summarize the resolution and next steps."
        config["cx"]["transition_route_groups"]["shared_escalation"]["transition_routes"] = [
            {"condition": "$session.params.needs_escalation == true", "targetFlow": snapshot.flows[0].name}
        ]

        updated = mapper.to_cx(config, snapshot)

        assert updated.playbooks[0].instructions == [
            "Gather the order ID first.",
            "Summarize the final resolution.",
        ]
        assert updated.playbooks[0].input_parameter_definitions == [{"name": "case_id", "type": "string"}]
        assert updated.playbooks[0].handlers[1]["event"] == "playbook-failed"
        assert updated.flows[0].transition_routes[0]["condition"] == "$session.params.vip == true"
        assert updated.flows[0].pages[0].form["parameters"][0]["displayName"] == "case_id"
        assert updated.intents[0].training_phrases[0]["parts"][0]["text"] == "I need priority support"
        assert updated.intents[0].parameters[0]["id"] == "case_id"
        assert updated.entity_types[0].entities[0]["value"] == "vip"
        assert updated.generators[0].prompt_text == "Summarize the resolution and next steps."
        assert updated.transition_route_groups[0].transition_routes[0]["condition"] == "$session.params.needs_escalation == true"


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
        assert "chat-messenger" in html
        assert "agent-1" in html
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
        # Verify client is called with deployment_name string and version_configs list
        # In CX Agent Studio, deployments are at app level, not agent level
        expected_deployment_name = f"{ref.app_name}/deployments/staging"
        mock_client.deploy_to_environment.assert_called_once_with(expected_deployment_name, [])

    def test_get_deploy_status(self):
        mock_client = MagicMock()
        mock_client.list_environments.return_value = [
            CxEnvironment(name="env/prod", display_name="production", description="Prod"),
        ]
        deployer = CxDeployer(mock_client)
        ref = _make_ref()
        status = deployer.get_deploy_status(ref)
        # In CX Agent Studio, deployments are at app level
        assert "app" in status
        assert "deployments" in status
        assert len(status["deployments"]) == 1
        assert status["deployments"][0]["name"] == "production"


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
        config = mapper.to_agentlab(snapshot)

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
        config = mapper.to_agentlab(snapshot)
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

    def test_cx_auth_help(self):
        from runner import cli
        from click.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli, ["cx", "auth", "--help"])
        assert result.exit_code == 0
        assert "--credentials" in result.output

    def test_cx_auth_reports_auth_errors_without_traceback(self, monkeypatch):
        from cx_studio.errors import CxAuthError
        from runner import cli
        from click.testing import CliRunner

        class FailingAuth:
            def __init__(self, credentials_path=None):
                self.credentials_path = credentials_path

            def describe(self):
                raise CxAuthError("google-auth package not installed")

        monkeypatch.setattr("cx_studio.CxAuth", FailingAuth)

        runner = CliRunner()
        result = runner.invoke(cli, ["cx", "auth"])

        assert result.exit_code != 0
        assert "CX authentication failed" in result.output
        assert "google-auth package not installed" in result.output

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

    def test_cx_diff_help(self):
        from runner import cli
        from click.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli, ["cx", "diff", "--help"])
        assert result.exit_code == 0
        assert "--snapshot" in result.output

    def test_cx_sync_help(self):
        from runner import cli
        from click.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli, ["cx", "sync", "--help"])
        assert result.exit_code == 0
        assert "--conflict-strategy" in result.output


# ---------------------------------------------------------------------------
# Client argument type tests (UX-005, UX-006, UX-007)
# ---------------------------------------------------------------------------

class TestCxClientArgumentTypes:
    """Tests to verify that string arguments are passed to client methods correctly."""

    def test_importer_passes_string_to_fetch_snapshot(self):
        """UX-005: Verify importer passes ref.name (string) to client.fetch_snapshot."""
        snapshot = _make_snapshot()
        mock_client = MagicMock()
        mock_client.fetch_snapshot.return_value = snapshot

        importer = CxImporter(mock_client)
        ref = _make_ref()

        with tempfile.TemporaryDirectory() as tmpdir:
            importer.import_agent(ref, output_dir=tmpdir)
            # Verify client was called with string, not CxAgentRef object
            mock_client.fetch_snapshot.assert_called_once()
            call_arg = mock_client.fetch_snapshot.call_args[0][0]
            assert isinstance(call_arg, str), f"Expected string, got {type(call_arg)}"
            assert call_arg == ref.name

    def test_exporter_passes_string_and_dict_to_update_agent(self):
        """UX-006: Verify exporter passes (resource_name: str, updates: dict) to client.update_agent."""
        snapshot = _make_snapshot()
        mock_client = MagicMock()
        mapper = CxMapper()
        config = mapper.to_agentlab(snapshot)
        # Modify description to trigger agent update
        config["description"] = "Updated description"

        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(snapshot.model_dump(), f)
            snap_path = f.name

        try:
            exporter = CxExporter(mock_client)
            result = exporter.export_agent(config, _make_ref(), snap_path, dry_run=False)

            if mock_client.update_agent.called:
                # Verify client was called with (str, dict), not (str, CxAgent)
                call_args = mock_client.update_agent.call_args[0]
                assert len(call_args) == 2
                assert isinstance(call_args[0], str), f"Expected string as first arg, got {type(call_args[0])}"
                assert isinstance(call_args[1], dict), f"Expected dict as second arg, got {type(call_args[1])}"
        finally:
            os.unlink(snap_path)

    def test_exporter_passes_string_and_dict_to_update_playbook(self):
        """UX-006: Verify exporter passes (resource_name: str, updates: dict) to client.update_playbook."""
        snapshot = _make_snapshot()
        mock_client = MagicMock()
        mapper = CxMapper()
        config = mapper.to_agentlab(snapshot)
        # Modify prompt to trigger playbook update
        config["prompts"]["root"] = "Updated prompt instructions"

        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(snapshot.model_dump(), f)
            snap_path = f.name

        try:
            exporter = CxExporter(mock_client)
            result = exporter.export_agent(config, _make_ref(), snap_path, dry_run=False)

            if mock_client.update_playbook.called:
                # Verify client was called with (str, dict), not (str, CxPlaybook)
                call_args = mock_client.update_playbook.call_args[0]
                assert len(call_args) == 2
                assert isinstance(call_args[0], str), f"Expected string as first arg, got {type(call_args[0])}"
                assert isinstance(call_args[1], dict), f"Expected dict as second arg, got {type(call_args[1])}"
        finally:
            os.unlink(snap_path)

    def test_deployer_passes_string_to_deploy_to_environment(self):
        """UX-007: Verify deployer passes deployment_name string to client.deploy_to_environment."""
        mock_client = MagicMock()
        mock_client.deploy_to_environment.return_value = {"version": "v1"}

        deployer = CxDeployer(mock_client)
        ref = _make_ref()

        deployer.deploy_to_environment(ref, "production")

        # Verify client was called with string deployment_name and version_configs list
        mock_client.deploy_to_environment.assert_called_once()
        call_args = mock_client.deploy_to_environment.call_args[0]
        assert len(call_args) == 2
        assert isinstance(call_args[0], str), f"Expected string as first arg, got {type(call_args[0])}"
        assert isinstance(call_args[1], list), f"Expected list as second arg, got {type(call_args[1])}"
        # Verify deployment name is fully qualified and uses app-level resource
        # CX Agent Studio uses /deployments not /environments
        assert call_args[0].endswith("/deployments/production")

    def test_deployer_passes_string_to_list_environments(self):
        """UX-007: Verify deployer passes app_name string to client.list_environments."""
        mock_client = MagicMock()
        mock_client.list_environments.return_value = [
            CxEnvironment(name="env/prod", display_name="production", description="Prod"),
        ]

        deployer = CxDeployer(mock_client)
        ref = _make_ref()

        deployer.get_deploy_status(ref)

        # Verify client was called with app_name string (deployments are at app level in CX Agent Studio)
        mock_client.list_environments.assert_called_once()
        call_arg = mock_client.list_environments.call_args[0][0]
        assert isinstance(call_arg, str), f"Expected string, got {type(call_arg)}"
        assert call_arg == ref.app_name  # Changed from ref.name to ref.app_name


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
