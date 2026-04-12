"""Regression tests for the typed Workbench -> Eval -> Optimize bridge."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.workbench import router
from builder.workbench import WorkbenchStore
from builder.workbench_bridge import (
    build_workbench_improvement_bridge,
    build_workbench_optimize_request,
)
from cli.workspace import AgentLabWorkspace
from shared.build_artifact_store import BuildArtifactStore


def _parse_sse(stream_body: str) -> list[dict]:
    """Parse a test SSE body into structured event dictionaries."""
    events: list[dict] = []
    for block in stream_body.strip().split("\n\n"):
        event_name = "message"
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line[len("event: ") :].strip()
            elif line.startswith("data: "):
                data_lines.append(line[len("data: ") :])
        if data_lines:
            events.append({"event": event_name, "data": json.loads("\n".join(data_lines))})
    return events


def _seed_workspace(root: Path) -> None:
    """Create a real local workspace so bridge materialization writes runnable config files."""
    workspace = AgentLabWorkspace.create(
        root=root,
        name=root.name,
        template="customer-support",
        agent_name="Workbench Bridge Agent",
        platform="Google ADK",
    )
    workspace.ensure_structure()
    workspace.runtime_config_path.write_text(
        yaml.safe_dump(
            {
                "optimizer": {
                    "use_mock": False,
                    "models": [
                        {
                            "provider": "openai",
                            "model": "gpt-4o-mini",
                            "role": "default",
                            "api_key_env": "OPENAI_API_KEY",
                        }
                    ],
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.chdir(tmp_path)
    _seed_workspace(tmp_path)
    app = FastAPI()
    app.include_router(router)
    app.state.workbench_store = WorkbenchStore(tmp_path / ".agentlab" / "workbench.json")
    app.state.build_artifact_store = BuildArtifactStore(
        path=tmp_path / ".agentlab" / "build_artifacts.json",
        latest_path=tmp_path / ".agentlab" / "build_artifact_latest.json",
    )
    return TestClient(app)


def test_materialized_eval_bridge_saves_candidate_and_returns_downstream_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(tmp_path, monkeypatch)

    build_response = client.post(
        "/api/workbench/build/stream",
        json={
            "brief": "Build an airline support agent with flight status tools.",
            "target": "portable",
            "mock": True,
            "max_iterations": 1,
        },
    )
    assert build_response.status_code == 200
    events = _parse_sse(build_response.text)
    project_id = events[-1]["data"]["project_id"]

    bridge_response = client.post(f"/api/workbench/projects/{project_id}/bridge/eval", json={})

    assert bridge_response.status_code == 201
    payload = bridge_response.json()
    save_result = payload["save_result"]
    assert Path(save_result["config_path"]).exists()

    bridge = payload["bridge"]
    assert bridge["kind"] == "workbench_eval_optimize"
    assert bridge["schema_version"] == 1
    assert bridge["candidate"]["project_id"] == project_id
    assert bridge["candidate"]["config_path"] == save_result["config_path"]
    assert bridge["candidate"]["eval_cases_path"] == save_result["eval_cases_path"]
    assert bridge["candidate"]["generated_config_hash"]

    assert bridge["evaluation"]["status"] == "ready"
    assert bridge["evaluation"]["request"]["config_path"] == save_result["config_path"]
    assert bridge["evaluation"]["request"]["split"] == "all"
    assert payload["eval_request"] == bridge["evaluation"]["request"]

    assert bridge["optimization"]["status"] == "awaiting_eval_run"
    assert bridge["optimization"]["requires_eval_run"] is True
    assert bridge["optimization"]["request_template"]["config_path"] == save_result["config_path"]
    assert bridge["optimization"]["request_template"]["eval_run_id"] is None
    assert payload["optimize_request_template"] == bridge["optimization"]["request_template"]
    assert payload["next"]["start_eval_endpoint"] == "/api/eval/run"
    assert payload["next"]["start_optimize_endpoint"] == "/api/optimize/run"


def test_bridge_blocks_downstream_requests_when_validation_failed() -> None:
    bridge = build_workbench_improvement_bridge(
        {
            "project_id": "wb-failed",
            "version": 2,
            "target": "cx",
            "environment": "draft",
            "compatibility": [{"status": "invalid", "label": "Local shell tool"}],
            "exports": {"generated_config": {"model": "gpt-5.4-mini"}},
            "last_test": {"status": "failed", "checks": []},
        },
        run={
            "run_id": "run-failed",
            "turn_id": "turn-failed",
            "status": "failed",
            "validation": {"status": "failed", "checks": []},
            "review_gate": {
                "status": "blocked",
                "blocking_reasons": ["Latest harness validation is failed."],
            },
        },
    )

    payload = bridge.model_dump(mode="python")
    assert payload["evaluation"]["status"] == "blocked"
    assert payload["evaluation"]["request"] is None
    assert "Latest harness validation is failed." in payload["evaluation"]["blocking_reasons"]
    assert payload["optimization"]["status"] == "blocked"
    assert payload["optimization"]["request_template"] is None

    with pytest.raises(ValueError, match="completed eval run"):
        build_workbench_optimize_request(bridge, eval_run_id="")
