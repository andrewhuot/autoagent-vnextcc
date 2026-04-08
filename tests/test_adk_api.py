"""Tests for ADK API routes."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi.testclient import TestClient

from api.server import app


client = TestClient(app)


@pytest.fixture
def mock_adk_tree():
    """Mock AdkAgentTree for testing."""
    from adk.types import AdkAgent, AdkAgentTree, AdkTool
    from pathlib import Path
    tool = AdkTool(name="test_tool", description="Test tool", function_body="def test(): pass")
    sub_agent = AdkAgent(name="sub", model="gemini", instruction="Sub", tools=[], sub_agents=[])
    sub_agent_tree = AdkAgentTree(agent=sub_agent, tools=[], sub_agents=[], source_path=Path("."))
    agent = AdkAgent(
        name="test_agent",
        model="gemini-2.0-flash",
        instruction="Test instruction",
        tools=["test_tool"],
        sub_agents=["sub"],
        generate_config={"temperature": 0.3},
    )
    return AdkAgentTree(agent=agent, tools=[tool], sub_agents=[sub_agent_tree], source_path=Path("."))


@pytest.fixture
def mock_import_result():
    """Mock ImportResult for testing."""
    return SimpleNamespace(
        config_path="/tmp/config.yaml",
        snapshot_path="/tmp/snapshot",
        agent_name="test_agent",
        surfaces_mapped=["prompts", "tools", "routing"],
        tools_imported=3,
        portability_report={
            "platform": "adk",
            "summary": {"imported_surfaces": 5},
            "optimization_eligibility": {"score": 72},
            "callbacks": [],
            "topology": {"summary": {"agent_count": 2}},
            "export_matrix": {
                "status": "lossy",
                "ready_surfaces": ["instructions"],
                "blocked_surfaces": ["routing"],
                "surfaces": [],
            },
            "surfaces": [],
        },
    )


@pytest.fixture
def mock_export_result():
    """Mock ExportResult for testing."""
    return SimpleNamespace(
        output_path="/tmp/output",
        changes=[{"file": "agent.py", "field": "instruction", "action": "update"}],
        files_modified=2,
        export_matrix={
            "status": "lossy",
            "ready_surfaces": ["instructions"],
            "blocked_surfaces": ["routing"],
            "surfaces": [],
        },
    )


@pytest.fixture
def mock_deploy_result():
    """Mock DeployResult for testing."""
    from adk.types import DeployResult
    return DeployResult(
        target="cloud-run",
        url="https://test-service.run.app",
        status="deployed",
        deployment_info={"revision": "test-001"},
    )


def test_import_endpoint(mock_import_result):
    """Test POST /api/adk/import."""
    with patch("api.routes.adk.AdkImporter") as MockImporter:
        mock_instance = Mock()
        mock_instance.import_agent.return_value = mock_import_result
        MockImporter.return_value = mock_instance

        response = client.post("/api/adk/import", json={
            "path": "/path/to/agent",
            "output_dir": "/tmp",
        })

        assert response.status_code == 201
        data = response.json()
        assert data["agent_name"] == "test_agent"
        assert data["tools_imported"] == 3
        assert "prompts" in data["surfaces_mapped"]
        assert data["portability_report"]["optimization_eligibility"]["score"] == 72
        assert data["portability_report"]["export_matrix"]["status"] == "lossy"


def test_import_invalid_path_returns_400(mock_import_result):
    """Test import with invalid path."""
    with patch("api.routes.adk.AdkImporter") as MockImporter:
        mock_instance = Mock()
        mock_instance.import_agent.side_effect = Exception("Path not found")
        MockImporter.return_value = mock_instance

        response = client.post("/api/adk/import", json={
            "path": "/invalid/path",
        })

        assert response.status_code == 502


def test_export_endpoint(mock_export_result):
    """Test POST /api/adk/export."""
    with patch("api.routes.adk.AdkExporter") as MockExporter:
        mock_instance = Mock()
        mock_instance.export_agent.return_value = mock_export_result
        MockExporter.return_value = mock_instance

        response = client.post("/api/adk/export", json={
            "config": {"prompts": {"root": "Updated"}},
            "snapshot_path": "/tmp/snapshot",
            "output_dir": "/tmp/output",
            "dry_run": False,
        })

        assert response.status_code == 200
        data = response.json()
        assert data["files_modified"] == 2
        assert data["export_matrix"]["blocked_surfaces"] == ["routing"]


def test_deploy_endpoint(mock_deploy_result):
    """Test POST /api/adk/deploy."""
    with patch("api.routes.adk.AdkDeployer") as MockDeployer:
        mock_instance = Mock()
        mock_instance.deploy_to_cloud_run.return_value = mock_deploy_result
        MockDeployer.return_value = mock_instance

        response = client.post("/api/adk/deploy", json={
            "path": "/path/to/agent",
            "target": "cloud-run",
            "project": "test-project",
            "region": "us-central1",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["target"] == "cloud-run"


def test_deploy_invalid_target_returns_400():
    """Test deploy with invalid target returns 400."""
    response = client.post("/api/adk/deploy", json={
        "path": "/path/to/agent",
        "target": "invalid-target",
        "project": "test-project",
    })

    assert response.status_code == 400


def test_status_endpoint(mock_adk_tree):
    """Test GET /api/adk/status."""
    with patch("api.routes.adk.parse_agent_directory") as mock_parse:
        mock_parse.return_value = mock_adk_tree

        response = client.get("/api/adk/status?path=/path/to/agent")

        assert response.status_code == 200
        data = response.json()
        assert "agent" in data
        assert data["agent"]["name"] == "test_agent"


def test_diff_endpoint():
    """Test GET /api/adk/diff."""
    with patch("api.routes.adk.AdkExporter") as MockExporter, \
         patch("builtins.open", create=True) as mock_open:
        from io import StringIO
        mock_open.return_value.__enter__.return_value = StringIO("prompts:\n  root: Test")
        mock_instance = Mock()
        mock_instance.preview_changes.return_value = [
            {"file": "agent.py", "field": "instruction", "action": "update"}
        ]
        MockExporter.return_value = mock_instance

        response = client.get(
            "/api/adk/diff?config_path=/tmp/config.yaml&snapshot_path=/tmp/snapshot"
        )

        assert response.status_code == 200
        data = response.json()
        assert "changes" in data
        assert "diff" in data
