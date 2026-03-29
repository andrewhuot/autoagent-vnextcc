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
