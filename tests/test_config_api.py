"""Tests for config API actions added for the aligned UI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import config as config_routes
from deployer.versioning import ConfigVersionManager


@pytest.fixture()
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    configs_dir = tmp_path / "configs"
    vm = ConfigVersionManager(configs_dir=str(configs_dir))
    vm.save_version({"agent": {"name": "v1"}}, scores={"composite": 0.7}, status="active")
    vm.save_version({"agent": {"name": "v2"}}, scores={"composite": 0.8}, status="canary")

    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    monkeypatch.chdir(tmp_path)

    test_app = FastAPI()
    test_app.include_router(config_routes.router)
    test_app.state.version_manager = vm
    return test_app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_activate_config_promotes_selected_version(client: TestClient) -> None:
    response = client.post("/api/config/activate", json={"version": 2})

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == 2
    assert payload["status"] == "active"


def test_import_config_adds_versioned_file(client: TestClient, tmp_path: Path) -> None:
    source = tmp_path / "incoming.yaml"
    source.write_text(yaml.safe_dump({"agent": {"name": "imported"}}), encoding="utf-8")

    response = client.post("/api/config/import", json={"file_path": str(source)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == 3
    assert payload["source_file"] == "incoming.yaml"
    assert Path(payload["dest_path"]).exists()


def test_migrate_config_returns_yaml_and_writes_output(client: TestClient, tmp_path: Path) -> None:
    source = tmp_path / "legacy.yaml"
    source.write_text(
        yaml.safe_dump({"optimizer": {"search_strategy": "adaptive"}, "budget": {"per_cycle_dollars": 2.0}}),
        encoding="utf-8",
    )
    output = tmp_path / "migrated.yaml"

    response = client.post(
        "/api/config/migrate",
        json={"input_file": str(source), "output_file": str(output)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["output_file"] == str(output)
    assert output.exists()
    migrated = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert migrated["optimization"]["mode"] == "advanced"
