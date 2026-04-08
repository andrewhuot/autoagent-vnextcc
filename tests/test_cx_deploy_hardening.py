"""Tests for CX deploy hardening: preflight, diff classification, canary/promote/rollback."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cx_studio.types import (
    CanaryState,
    ChangeSafety,
    CxAgent,
    CxAgentRef,
    CxAgentSnapshot,
    CxFlow,
    CxPlaybook,
    CxWebhook,
    DeployPhase,
    DeployResult,
    PreflightResult,
)
from cx_studio.deployer import CxDeployer
from cx_studio.exporter import CxExporter
from cx_studio.errors import CxStudioError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_ref() -> CxAgentRef:
    return CxAgentRef(
        project="test-project",
        location="us-central1",
        app_id="test-app",
        agent_id="agent-123",
    )


def _make_snapshot(**overrides) -> CxAgentSnapshot:
    defaults = dict(
        agent=CxAgent(
            name="projects/test-project/locations/us-central1/agents/agent-123",
            display_name="Test Agent",
            description="A test agent",
            generative_settings={"model": "gemini-2.0-flash"},
        ),
        playbooks=[
            CxPlaybook(
                name="projects/test-project/locations/us-central1/agents/agent-123/playbooks/pb-1",
                display_name="Main Playbook",
                instructions=["Be helpful."],
            ),
        ],
        webhooks=[
            CxWebhook(
                name="projects/test-project/locations/us-central1/agents/agent-123/webhooks/wh-1",
                display_name="Order Webhook",
                generic_web_service={"uri": "https://example.com/order"},
                timeout_seconds=10,
            ),
        ],
        flows=[
            CxFlow(
                name="projects/test-project/locations/us-central1/agents/agent-123/flows/flow-1",
                display_name="Default Flow",
                description="Main flow",
                transition_routes=[{"condition": "true", "target_page": "p1"}],
            ),
        ],
    )
    defaults.update(overrides)
    return CxAgentSnapshot(**defaults)


def _write_snapshot(path: Path, snapshot: CxAgentSnapshot) -> str:
    filepath = path / "snapshot.json"
    filepath.write_text(json.dumps(snapshot.model_dump(), indent=2), encoding="utf-8")
    return str(filepath)


# ---------------------------------------------------------------------------
# Diff classification tests
# ---------------------------------------------------------------------------

class TestDiffClassification:
    """Verify each change is tagged with safety classification."""

    def test_safe_change_on_playbook_instruction(self, tmp_path: Path):
        base = _make_snapshot()
        snapshot_path = _write_snapshot(tmp_path, base)

        modified_config = {"instructions": "Updated instructions"}
        client = MagicMock()
        exporter = CxExporter(client)

        # Modify instruction in snapshot to create a diff
        import copy
        target = copy.deepcopy(base)
        target.playbooks[0].instruction = "Updated instructions"
        target.playbooks[0].instructions = ["Updated instructions"]
        _write_snapshot(tmp_path, base)  # keep base

        changes = exporter._compute_changes(base, target)
        assert len(changes) >= 1

        instruction_change = [c for c in changes if c["field"] == "instruction"]
        assert len(instruction_change) == 1
        assert instruction_change[0]["safety"] == "safe"
        assert "round-trips faithfully" in instruction_change[0]["rationale"]

    def test_safe_change_on_agent_description(self, tmp_path: Path):
        base = _make_snapshot()
        import copy
        target = copy.deepcopy(base)
        target.agent.description = "New description"

        client = MagicMock()
        exporter = CxExporter(client)
        changes = exporter._compute_changes(base, target)

        desc_change = [c for c in changes if c["field"] == "description" and c["resource"] == "agent"]
        assert len(desc_change) == 1
        assert desc_change[0]["safety"] == "safe"

    def test_safe_change_on_webhook(self, tmp_path: Path):
        base = _make_snapshot()
        import copy
        target = copy.deepcopy(base)
        target.webhooks[0].timeout_seconds = 30

        client = MagicMock()
        exporter = CxExporter(client)
        changes = exporter._compute_changes(base, target)

        wh_change = [c for c in changes if c["field"] == "timeout_seconds"]
        assert len(wh_change) == 1
        assert wh_change[0]["safety"] == "safe"

    def test_lossy_change_on_flow_routes(self, tmp_path: Path):
        base = _make_snapshot()
        import copy
        target = copy.deepcopy(base)
        target.flows[0].transition_routes = [{"condition": "false", "target_page": "p2"}]

        client = MagicMock()
        exporter = CxExporter(client)
        changes = exporter._compute_changes(base, target)

        route_change = [c for c in changes if c["field"] == "transition_routes"]
        assert len(route_change) == 1
        assert route_change[0]["safety"] == "lossy"
        assert "may lose" in route_change[0]["rationale"]

    def test_blocked_change_classification(self):
        """Verify _classify_change_safety returns blocked for unknown resources."""
        safety, rationale = CxExporter._classify_change_safety("intent", "training_phrases", "update")
        assert safety == ChangeSafety.BLOCKED
        assert "read-only" in rationale

    def test_all_changes_have_safety_field(self, tmp_path: Path):
        base = _make_snapshot()
        import copy
        target = copy.deepcopy(base)
        target.agent.description = "Changed"
        target.playbooks[0].instruction = "Changed"
        target.flows[0].description = "Changed"

        client = MagicMock()
        exporter = CxExporter(client)
        changes = exporter._compute_changes(base, target)

        for change in changes:
            assert "safety" in change, f"Change missing safety: {change}"
            assert "rationale" in change, f"Change missing rationale: {change}"
            assert change["safety"] in ("safe", "lossy", "blocked")


# ---------------------------------------------------------------------------
# Preflight tests
# ---------------------------------------------------------------------------

class TestPreflight:
    """Verify preflight validation gates deploy/export."""

    def test_preflight_passes_for_valid_config(self):
        client = MagicMock()
        deployer = CxDeployer(client)
        config = {"agent_type": "LlmAgent", "tools": {}}
        result = deployer.run_preflight(config)
        assert result.passed is True
        assert result.errors == []

    def test_preflight_fails_for_invalid_agent_type(self):
        client = MagicMock()
        deployer = CxDeployer(client)
        config = {"agent_type": "SequentialAgent", "tools": {}}
        result = deployer.run_preflight(config)
        assert result.passed is False
        assert len(result.errors) > 0
        assert any("SequentialAgent" in e for e in result.errors)

    def test_preflight_includes_export_matrix_surfaces(self):
        client = MagicMock()
        deployer = CxDeployer(client)
        config = {"agent_type": "LlmAgent", "tools": {}}
        matrix = {
            "ready_surfaces": ["instructions", "webhooks"],
            "lossy_surfaces": ["routing"],
            "blocked_surfaces": ["flows", "intents"],
        }
        result = deployer.run_preflight(config, matrix)
        assert result.passed is True
        assert "instructions" in result.safe_surfaces
        assert "routing" in result.lossy_surfaces
        assert "flows" in result.blocked_surfaces

    def test_preflight_warns_on_adk_only_tools(self):
        client = MagicMock()
        deployer = CxDeployer(client)
        config = {
            "agent_type": "LlmAgent",
            "tools": {"t1": {"tool_type": "agent_tool", "name": "sub_agent"}},
        }
        result = deployer.run_preflight(config)
        assert result.passed is True  # warnings don't block
        assert len(result.warnings) > 0


# ---------------------------------------------------------------------------
# Canary / promote / rollback tests
# ---------------------------------------------------------------------------

class TestCanaryWorkflow:
    """Verify canary deploy → promote → rollback state transitions."""

    def test_deploy_canary_returns_canary_phase(self):
        client = MagicMock()
        client.deploy_to_environment.return_value = {"version": "v2", "previous_version": "v1"}
        deployer = CxDeployer(client)
        ref = _make_ref()

        result, canary = deployer.deploy_canary(ref, "production", traffic_pct=10)

        assert result.status == "canary"
        assert result.environment == "production"
        assert canary.phase == DeployPhase.CANARY
        assert canary.traffic_pct == 10
        assert canary.deployed_version == "v2"
        assert canary.previous_version == "v1"

    def test_promote_canary_transitions_to_promoted(self):
        client = MagicMock()
        client.deploy_to_environment.return_value = {"version": "v2"}
        deployer = CxDeployer(client)
        ref = _make_ref()

        canary = CanaryState(
            phase=DeployPhase.CANARY,
            traffic_pct=10,
            deployed_version="v2",
            previous_version="v1",
            environment="production",
        )

        result, updated = deployer.promote_canary(ref, canary)

        assert result.status == "promoted"
        assert updated.phase == DeployPhase.PROMOTED
        assert updated.traffic_pct == 100
        assert updated.promoted_at != ""

    def test_promote_rejects_non_canary_phase(self):
        client = MagicMock()
        deployer = CxDeployer(client)
        ref = _make_ref()

        canary = CanaryState(phase=DeployPhase.PROMOTED)

        with pytest.raises(CxStudioError, match="Cannot promote"):
            deployer.promote_canary(ref, canary)

    def test_rollback_from_canary(self):
        client = MagicMock()
        client.deploy_to_environment.return_value = {"version": "v1"}
        deployer = CxDeployer(client)
        ref = _make_ref()

        canary = CanaryState(
            phase=DeployPhase.CANARY,
            traffic_pct=10,
            deployed_version="v2",
            previous_version="v1",
            environment="production",
        )

        result, rolled_back = deployer.rollback(ref, canary)

        assert result.status == "rolled_back"
        assert rolled_back.phase == DeployPhase.ROLLED_BACK
        assert rolled_back.deployed_version == "v1"
        assert rolled_back.previous_version == "v2"
        assert rolled_back.rolled_back_at != ""

    def test_rollback_from_promoted(self):
        client = MagicMock()
        client.deploy_to_environment.return_value = {"version": "v1"}
        deployer = CxDeployer(client)
        ref = _make_ref()

        canary = CanaryState(
            phase=DeployPhase.PROMOTED,
            deployed_version="v2",
            previous_version="v1",
            environment="staging",
        )

        result, rolled_back = deployer.rollback(ref, canary)
        assert rolled_back.phase == DeployPhase.ROLLED_BACK
        assert result.environment == "staging"

    def test_rollback_rejects_preflight_phase(self):
        client = MagicMock()
        deployer = CxDeployer(client)
        ref = _make_ref()

        canary = CanaryState(phase=DeployPhase.PREFLIGHT)

        with pytest.raises(CxStudioError, match="Cannot rollback"):
            deployer.rollback(ref, canary)

    def test_canary_deploy_failure_raises(self):
        client = MagicMock()
        client.deploy_to_environment.side_effect = Exception("API down")
        deployer = CxDeployer(client)
        ref = _make_ref()

        with pytest.raises(CxStudioError, match="Canary deploy"):
            deployer.deploy_canary(ref, "production")


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi import FastAPI
from fastapi.testclient import TestClient
from api.routes import cx_studio as cx_studio_routes


@pytest.fixture()
def app(tmp_path: Path) -> FastAPI:
    test_app = FastAPI()
    test_app.include_router(cx_studio_routes.router)
    test_app.state.cx_workspace_root = str(tmp_path)
    return test_app


@pytest.fixture()
def api_client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


class TestPreflightRoute:
    def test_preflight_returns_pass_for_valid_config(self, api_client: TestClient):
        response = api_client.post("/api/cx/preflight", json={
            "config": {"agent_type": "LlmAgent", "tools": {}},
        })
        assert response.status_code == 200
        data = response.json()
        assert data["passed"] is True
        assert data["errors"] == []

    def test_preflight_returns_fail_for_invalid_type(self, api_client: TestClient):
        response = api_client.post("/api/cx/preflight", json={
            "config": {"agent_type": "SequentialAgent", "tools": {}},
        })
        assert response.status_code == 200
        data = response.json()
        assert data["passed"] is False
        assert len(data["errors"]) > 0

    def test_preflight_includes_surface_classification(self, api_client: TestClient):
        response = api_client.post("/api/cx/preflight", json={
            "config": {"agent_type": "LlmAgent", "tools": {}},
            "export_matrix": {
                "ready_surfaces": ["instructions"],
                "lossy_surfaces": ["routing"],
                "blocked_surfaces": ["flows"],
            },
        })
        assert response.status_code == 200
        data = response.json()
        assert "instructions" in data["safe_surfaces"]
        assert "routing" in data["lossy_surfaces"]
        assert "flows" in data["blocked_surfaces"]


class TestDeployRoute:
    def test_canary_deploy_strategy(
        self,
        api_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ):
        def _fake_canary(self, ref, env, traffic_pct):
            return (
                DeployResult(environment=env, status="canary", version_info={"phase": "canary"}),
                CanaryState(
                    phase=DeployPhase.CANARY,
                    traffic_pct=traffic_pct,
                    deployed_version="v2",
                    environment=env,
                ),
            )

        monkeypatch.setattr("cx_studio.CxDeployer.deploy_canary", _fake_canary)
        monkeypatch.setattr("cx_studio.CxAuth.__init__", lambda self, **kw: None)
        monkeypatch.setattr("cx_studio.CxClient.__init__", lambda self, auth: None)

        response = api_client.post("/api/cx/deploy", json={
            "project": "test-project",
            "location": "us-central1",
            "agent_id": "agent-123",
            "environment": "production",
            "strategy": "canary",
            "traffic_pct": 10,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["phase"] == "canary"
        assert data["canary"]["traffic_pct"] == 10


class TestPromoteRoute:
    def test_promote_returns_promoted_phase(
        self,
        api_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ):
        def _fake_promote(self, ref, canary):
            return (
                DeployResult(environment="production", status="promoted", version_info={}),
                CanaryState(
                    phase=DeployPhase.PROMOTED,
                    traffic_pct=100,
                    deployed_version="v2",
                    environment="production",
                    promoted_at="2026-04-08T00:00:00Z",
                ),
            )

        monkeypatch.setattr("cx_studio.CxDeployer.promote_canary", _fake_promote)
        monkeypatch.setattr("cx_studio.CxAuth.__init__", lambda self, **kw: None)
        monkeypatch.setattr("cx_studio.CxClient.__init__", lambda self, auth: None)

        response = api_client.post("/api/cx/promote", json={
            "project": "test-project",
            "location": "us-central1",
            "agent_id": "agent-123",
            "canary": {
                "phase": "canary",
                "traffic_pct": 10,
                "deployed_version": "v2",
                "previous_version": "v1",
                "environment": "production",
            },
        })
        assert response.status_code == 200
        data = response.json()
        assert data["phase"] == "promoted"
        assert data["canary"]["traffic_pct"] == 100


class TestRollbackRoute:
    def test_rollback_returns_rolled_back_phase(
        self,
        api_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ):
        def _fake_rollback(self, ref, canary):
            return (
                DeployResult(environment="production", status="rolled_back", version_info={}),
                CanaryState(
                    phase=DeployPhase.ROLLED_BACK,
                    traffic_pct=0,
                    deployed_version="v1",
                    previous_version="v2",
                    environment="production",
                    rolled_back_at="2026-04-08T00:00:00Z",
                ),
            )

        monkeypatch.setattr("cx_studio.CxDeployer.rollback", _fake_rollback)
        monkeypatch.setattr("cx_studio.CxAuth.__init__", lambda self, **kw: None)
        monkeypatch.setattr("cx_studio.CxClient.__init__", lambda self, auth: None)

        response = api_client.post("/api/cx/rollback", json={
            "project": "test-project",
            "location": "us-central1",
            "agent_id": "agent-123",
            "canary": {
                "phase": "canary",
                "traffic_pct": 10,
                "deployed_version": "v2",
                "previous_version": "v1",
                "environment": "production",
            },
        })
        assert response.status_code == 200
        data = response.json()
        assert data["phase"] == "rolled_back"
        assert data["canary"]["deployed_version"] == "v1"
