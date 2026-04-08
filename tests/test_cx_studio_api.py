"""Tests for CX Studio API routes."""

from __future__ import annotations

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import cx_studio as cx_studio_routes


@pytest.fixture()
def app(tmp_path: Path) -> FastAPI:
    """Build a minimal app with an isolated CX workspace root."""
    test_app = FastAPI()
    test_app.include_router(cx_studio_routes.router)
    test_app.state.cx_workspace_root = str(tmp_path)
    return test_app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    """Create a synchronous test client."""
    return TestClient(app, raise_server_exceptions=False)


def test_preview_accepts_relative_paths_within_workspace(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preview succeeds when both files stay inside the configured workspace."""
    (tmp_path / "config.yaml").write_text("alpha: 1\n", encoding="utf-8")
    (tmp_path / "snapshot.json").write_text('{"flows":[],"playbooks":[],"tools":[]}', encoding="utf-8")

    def _fake_preview_changes(self, config, snapshot_path):  # noqa: ANN001
        assert config == {"alpha": 1}
        assert snapshot_path == str(tmp_path / "snapshot.json")
        return []

    monkeypatch.setattr("cx_studio.CxExporter.preview_changes", _fake_preview_changes)

    response = client.get("/api/cx/preview", params={"config_path": "config.yaml", "snapshot_path": "snapshot.json"})

    assert response.status_code == 200
    assert response.json() == {"changes": []}


def test_preview_rejects_paths_outside_workspace(client: TestClient, tmp_path: Path) -> None:
    """Preview rejects config and snapshot files outside the configured workspace."""
    external_root = tmp_path.parent
    external_config = external_root / "external-config.yaml"
    external_snapshot = external_root / "external-snapshot.json"
    external_config.write_text("alpha: 1\n", encoding="utf-8")
    external_snapshot.write_text('{"flows":[]}', encoding="utf-8")

    response = client.get(
        "/api/cx/preview",
        params={
            "config_path": str(external_config),
            "snapshot_path": str(external_snapshot),
        },
    )

    assert response.status_code == 400
    assert "escapes workspace root" in response.json()["detail"].lower()


def test_preview_returns_400_when_snapshot_preview_fails(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preview converts malformed snapshot errors into 400 responses."""
    (tmp_path / "config.yaml").write_text("alpha: 1\n", encoding="utf-8")
    (tmp_path / "snapshot.json").write_text("not-json", encoding="utf-8")

    def _raise_preview_error(self, config, snapshot_path):  # noqa: ANN001
        raise ValueError("bad snapshot")

    monkeypatch.setattr("cx_studio.CxExporter.preview_changes", _raise_preview_error)

    response = client.get("/api/cx/preview", params={"config_path": "config.yaml", "snapshot_path": "snapshot.json"})

    assert response.status_code == 400
    assert "invalid snapshot" in response.json()["detail"].lower()


def test_auth_returns_auth_metadata(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auth route should surface the resolved credential metadata."""

    class _FakeAuth:
        def __init__(self, credentials_path: str | None = None) -> None:
            self.credentials_path = credentials_path

        def describe(self) -> dict[str, str | None]:
            return {
                "project_id": "demo-project",
                "auth_type": "service_account",
                "principal": "bot@example.iam.gserviceaccount.com",
                "credentials_path": self.credentials_path,
            }

    monkeypatch.setattr("cx_studio.CxAuth", _FakeAuth)

    response = client.post("/api/cx/auth", json={"credentials_path": "/tmp/key.json"})

    assert response.status_code == 200
    assert response.json()["project_id"] == "demo-project"
    assert response.json()["auth_type"] == "service_account"


def test_import_returns_portability_parity_fields(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Import route should expose the richer parity fields in the response contract."""

    class _FakeAuth:
        def __init__(self, credentials_path: str | None = None) -> None:
            self.credentials_path = credentials_path

    class _FakeClient:
        def __init__(self, auth) -> None:  # noqa: ANN001
            self.auth = auth

    class _FakeImporter:
        def __init__(self, client) -> None:  # noqa: ANN001
            self.client = client

        def import_agent(self, ref, output_dir, include_test_cases):  # noqa: ANN001
            assert ref.agent_id == "support-bot"
            assert output_dir == "/tmp/out"
            assert include_test_cases is True

            class _Result:
                config_path = "/tmp/out/configs/v001.yaml"
                eval_path = "/tmp/out/evals/imported.yaml"
                snapshot_path = "/tmp/out/.agentlab/cx/snapshot.json"
                agent_name = "Support Bot"
                surfaces_mapped = ["instructions", "webhooks", "routing"]
                test_cases_imported = 1
                workspace_path = "/tmp/out"
                portability_report = {
                    "platform": "cx_studio",
                    "summary": {
                        "supported_parity_surfaces": 3,
                        "partial_parity_surfaces": 1,
                        "read_only_parity_surfaces": 2,
                        "unsupported_parity_surfaces": 1,
                    },
                    "surfaces": [
                        {
                            "surface_id": "instructions",
                            "label": "Instructions",
                            "parity_status": "supported",
                            "coverage_status": "imported",
                            "portability_status": "optimizable",
                            "export_status": "ready",
                            "documentation_refs": [
                                "https://docs.cloud.google.com/dialogflow/cx/docs/reference/rest/v3/projects.locations.agents.playbooks"
                            ],
                            "code_refs": ["cx_studio/surface_inventory.py"],
                        }
                    ],
                }

            return _Result()

    monkeypatch.setattr("cx_studio.CxAuth", _FakeAuth)
    monkeypatch.setattr("cx_studio.CxClient", _FakeClient)
    monkeypatch.setattr("cx_studio.CxImporter", _FakeImporter)

    response = client.post(
        "/api/cx/import",
        json={
            "project": "demo-project",
            "location": "us-central1",
            "agent_id": "support-bot",
            "output_dir": "/tmp/out",
            "include_test_cases": True,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["portability_report"]["summary"]["supported_parity_surfaces"] == 3
    assert payload["portability_report"]["surfaces"][0]["parity_status"] == "supported"
    assert payload["portability_report"]["surfaces"][0]["documentation_refs"]


def test_diff_returns_changes_and_conflicts(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Diff route should return both planned changes and merge conflicts."""

    class _FakeAuth:
        def __init__(self, credentials_path: str | None = None) -> None:
            self.credentials_path = credentials_path

    class _FakeClient:
        def __init__(self, auth) -> None:  # noqa: ANN001
            self.auth = auth

    class _FakeExporter:
        def __init__(self, client) -> None:  # noqa: ANN001
            self.client = client

        def diff_agent(self, config, ref, snapshot_path):  # noqa: ANN001
            assert config == {"prompts": {"root": "hello"}}
            assert ref.agent_id == "support-bot"
            assert snapshot_path == ".agentlab/cx/snapshot.json"

            class _Result:
                changes = [{"resource": "playbook", "field": "instruction", "action": "update"}]
                pushed = False
                resources_updated = 0
                conflicts = [{"resource": "playbook", "field": "instruction", "name": "Escalation"}]
                export_matrix = {
                    "status": "lossy",
                    "ready_surfaces": ["instructions"],
                    "blocked_surfaces": ["routing"],
                    "surfaces": [],
                }

            return _Result()

    monkeypatch.setattr("cx_studio.CxAuth", _FakeAuth)
    monkeypatch.setattr("cx_studio.CxClient", _FakeClient)
    monkeypatch.setattr("cx_studio.CxExporter", _FakeExporter)

    response = client.post(
        "/api/cx/diff",
        json={
            "project": "demo-project",
            "location": "us-central1",
            "agent_id": "support-bot",
            "config": {"prompts": {"root": "hello"}},
            "snapshot_path": ".agentlab/cx/snapshot.json",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["changes"][0]["resource"] == "playbook"
    assert payload["conflicts"][0]["name"] == "Escalation"
    assert payload["export_matrix"]["status"] == "lossy"


def test_sync_returns_conflicts_without_pushing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sync route should return blocked conflicts when the exporter detects overlap."""

    class _FakeAuth:
        def __init__(self, credentials_path: str | None = None) -> None:
            self.credentials_path = credentials_path

    class _FakeClient:
        def __init__(self, auth) -> None:  # noqa: ANN001
            self.auth = auth

    class _FakeExporter:
        def __init__(self, client) -> None:  # noqa: ANN001
            self.client = client

        def sync_agent(self, config, ref, snapshot_path, conflict_strategy):  # noqa: ANN001
            assert conflict_strategy == "detect"
            assert ref.agent_id == "support-bot"

            class _Result:
                changes = [{"resource": "playbook", "field": "instruction", "action": "update"}]
                pushed = False
                resources_updated = 0
                conflicts = [{"resource": "playbook", "field": "instruction", "name": "Escalation"}]
                export_matrix = {
                    "status": "lossy",
                    "ready_surfaces": ["instructions"],
                    "blocked_surfaces": ["routing"],
                    "surfaces": [],
                }

            return _Result()

    monkeypatch.setattr("cx_studio.CxAuth", _FakeAuth)
    monkeypatch.setattr("cx_studio.CxClient", _FakeClient)
    monkeypatch.setattr("cx_studio.CxExporter", _FakeExporter)

    response = client.post(
        "/api/cx/sync",
        json={
            "project": "demo-project",
            "location": "us-central1",
            "agent_id": "support-bot",
            "config": {"prompts": {"root": "hello"}},
            "snapshot_path": ".agentlab/cx/snapshot.json",
            "conflict_strategy": "detect",
        },
    )

    assert response.status_code == 200
    assert response.json()["pushed"] is False
    assert response.json()["conflicts"][0]["field"] == "instruction"
    assert response.json()["export_matrix"]["blocked_surfaces"] == ["routing"]
