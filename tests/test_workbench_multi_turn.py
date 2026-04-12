"""Tests for multi-turn autonomous Workbench behaviour.

These tests cover the Claude-Code / Manus-style features added to the
Workbench:
- follow-up turns append deltas instead of clobbering prior plans/artifacts
- conversation history persists across turns
- autonomous validation loop runs corrective iterations
- plan snapshots expose the full multi-turn state for UI hydration
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.workbench import router
from builder.workbench import WorkbenchService, WorkbenchStore
from builder.workbench_plan import PlanTask, WorkbenchArtifact


class _InvalidCxToolAgent:
    execution_mode = "mock"
    provider = "test"
    model = "invalid-tool-agent"
    mode_reason = "deterministic invalid tool fixture"
    requested_mock = True

    async def run(self, request, project):
        task_id = "task-invalid-tool"
        plan = PlanTask(
            id="task-root",
            title="Build CX-invalid tool agent",
            children=[
                PlanTask(
                    id=task_id,
                    title="Add local shell diagnostic tool",
                    parent_id="task-root",
                )
            ],
        )
        tool = {
            "id": "tool-local-shell",
            "name": "local_diagnostic_shell",
            "description": "Runs local diagnostics for the operator.",
            "type": "local_shell",
            "parameters": [],
        }
        artifact = WorkbenchArtifact(
            id="artifact-local-shell",
            task_id=task_id,
            category="tool",
            name="local_diagnostic_shell",
            summary="Local shell diagnostic tool.",
            preview="local_diagnostic_shell()",
            source="def local_diagnostic_shell(): ...",
            language="python",
            created_at="2026-04-12T00:00:00Z",
        )
        yield {"event": "plan.ready", "data": {"plan": plan.to_dict()}}
        yield {"event": "task.started", "data": {"task_id": task_id}}
        yield {"event": "artifact.updated", "data": {"artifact": artifact.to_dict()}}
        yield {
            "event": "task.completed",
            "data": {
                "task_id": task_id,
                "operations": [
                    {
                        "operation": "add_tool",
                        "target": "tools",
                        "label": "local_diagnostic_shell",
                        "object": tool,
                    }
                ],
            },
        }
        yield {"event": "build.completed", "data": {"summary": "Added local shell tool."}}


class _NoEvidenceAgent:
    execution_mode = "mock"
    provider = "test"
    model = "no-evidence-agent"
    mode_reason = "deterministic no evidence fixture"
    requested_mock = True

    async def run(self, request, project):
        plan = PlanTask(id="task-root", title="Say the build is done")
        yield {"event": "plan.ready", "data": {"plan": plan.to_dict()}}
        yield {"event": "build.completed", "data": {"summary": "No canonical changes."}}


def _make_client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.workbench_store = WorkbenchStore(tmp_path / "workbench.json")
    return TestClient(app)


def _parse_sse(stream_body: str) -> list[dict]:
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
            events.append(
                {
                    "event": event_name,
                    "data": json.loads("\n".join(data_lines)),
                }
            )
    return events


def _stream(client: TestClient, body: dict) -> list[dict]:
    response = client.post("/api/workbench/build/stream", json=body)
    assert response.status_code == 200
    return _parse_sse(response.text)


async def _collect_service_stream(stream) -> list[dict]:
    events: list[dict] = []
    async for event in stream:
        events.append(event)
    return events


def test_multi_turn_preserves_artifacts_and_conversation(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    # --- turn 1: initial build -------------------------------------------
    events1 = _stream(
        client,
        {
            "brief": "Build an airline support agent for delayed flights.",
            "mock": True,
            "max_iterations": 1,
        },
    )
    assert events1[0]["event"] == "turn.started"
    assert events1[-1]["event"] == "run.completed"
    assert "turn.completed" in [event["event"] for event in events1]
    project_id = events1[-1]["data"]["project_id"]
    turn_one_id = events1[0]["data"]["turn_id"]

    snapshot1 = client.get(f"/api/workbench/projects/{project_id}/plan").json()
    assert snapshot1["build_status"] == "completed"
    assert len(snapshot1["turns"]) == 1
    assert snapshot1["turns"][0]["turn_id"] == turn_one_id
    assert snapshot1["turns"][0]["mode"] == "initial"
    assert len(snapshot1["conversation"]) >= 2  # user + assistant summary
    first_turn_artifact_count = len(snapshot1["artifacts"])
    assert first_turn_artifact_count >= 3
    # Every artifact is tagged with its turn id so the UI can group them.
    assert all(a.get("turn_id") == turn_one_id for a in snapshot1["artifacts"])

    # --- turn 2: follow-up delta -----------------------------------------
    events2 = _stream(
        client,
        {
            "project_id": project_id,
            "brief": "Add a PII guardrail and a flight status tool.",
            "mock": True,
            "max_iterations": 1,
        },
    )
    assert events2[0]["event"] == "turn.started"
    assert events2[0]["data"]["mode"] == "follow_up"
    turn_two_id = events2[0]["data"]["turn_id"]
    assert turn_two_id != turn_one_id

    snapshot2 = client.get(f"/api/workbench/projects/{project_id}/plan").json()
    # Prior turn artifacts are still present — follow-ups never clobber.
    assert len(snapshot2["turns"]) == 2
    assert snapshot2["turns"][0]["turn_id"] == turn_one_id
    assert snapshot2["turns"][1]["turn_id"] == turn_two_id
    assert snapshot2["turns"][1]["mode"] == "follow_up"
    assert len(snapshot2["artifacts"]) > first_turn_artifact_count
    turn_one_artifacts = [a for a in snapshot2["artifacts"] if a.get("turn_id") == turn_one_id]
    turn_two_artifacts = [a for a in snapshot2["artifacts"] if a.get("turn_id") == turn_two_id]
    assert turn_one_artifacts, "initial turn artifacts should survive a follow-up turn"
    assert turn_two_artifacts, "follow-up turn should emit its own artifacts"

    # Conversation accumulates user + assistant across both turns.
    roles_per_turn = {turn_one_id: set(), turn_two_id: set()}
    for message in snapshot2["conversation"]:
        turn_id = message.get("turn_id")
        if turn_id in roles_per_turn:
            roles_per_turn[turn_id].add(message["role"])
    assert {"user", "assistant"} <= roles_per_turn[turn_one_id]
    assert {"user", "assistant"} <= roles_per_turn[turn_two_id]


def test_autonomous_loop_caps_at_max_iterations(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    events = _stream(
        client,
        {
            "brief": "Build a refund support agent.",
            "mock": True,
            "auto_iterate": True,
            "max_iterations": 2,
        },
    )

    iterations = [ev for ev in events if ev["event"] == "iteration.started"]
    validations = [ev for ev in events if ev["event"] == "validation.ready"]
    assert 1 <= len(iterations) <= 2
    assert len(validations) == len(iterations)

    project_id = events[-1]["data"]["project_id"]
    snapshot = client.get(f"/api/workbench/projects/{project_id}/plan").json()
    turn = snapshot["turns"][-1]
    assert 1 <= len(turn["iterations"]) <= 2
    assert turn["status"] in {"completed", "failed"}


def test_follow_up_emits_delta_plan(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    initial = _stream(
        client,
        {
            "brief": "Build an airline support agent.",
            "mock": True,
            "max_iterations": 1,
        },
    )
    project_id = initial[-1]["data"]["project_id"]

    initial_plan_event = next(ev for ev in initial if ev["event"] == "plan.ready")
    initial_leaf_count = _leaf_count(initial_plan_event["data"]["plan"])

    followup = _stream(
        client,
        {
            "project_id": project_id,
            "brief": "Add a tool for flight status lookups.",
            "mock": True,
            "max_iterations": 1,
        },
    )
    followup_plan_event = next(ev for ev in followup if ev["event"] == "plan.ready")
    followup_leaf_count = _leaf_count(followup_plan_event["data"]["plan"])

    # Delta plans are always smaller than the initial plan tree.
    assert followup_leaf_count < initial_leaf_count
    assert followup_leaf_count >= 1


def test_auto_iterate_off_runs_one_pass_only(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    events = _stream(
        client,
        {
            "brief": "Build an IT helpdesk agent.",
            "mock": True,
            "auto_iterate": False,
            "max_iterations": 4,
        },
    )
    iterations = [ev for ev in events if ev["event"] == "iteration.started"]
    assert len(iterations) == 1


@pytest.mark.asyncio
async def test_auto_iterate_false_keeps_validation_failure_honest(tmp_path: Path) -> None:
    service = WorkbenchService(WorkbenchStore(tmp_path / "workbench.json"))
    stream = await service.run_build_stream(
        project_id=None,
        brief="Build a CX agent with a local diagnostic tool.",
        target="cx",
        agent=_InvalidCxToolAgent(),
        auto_iterate=False,
        max_iterations=2,
    )

    events = await _collect_service_stream(stream)

    iterations = [event for event in events if event["event"] == "iteration.started"]
    validations = [event for event in events if event["event"] == "validation.ready"]
    terminal = events[-1]
    project_id = terminal["data"]["project_id"]
    snapshot = service.get_plan_snapshot(project_id=project_id)

    assert len(iterations) == 1
    assert validations[-1]["data"]["status"] == "failed"
    assert terminal["event"] == "run.completed"
    assert terminal["data"]["status"] == "failed"
    assert terminal["data"]["evidence_summary"]["structural_status"] == "failed"
    assert terminal["data"]["evidence_summary"]["improvement_status"] == "changed"
    assert terminal["data"]["review_gate"]["status"] == "blocked"
    assert any(tool["type"] == "local_shell" for tool in snapshot["model"]["tools"])


@pytest.mark.asyncio
async def test_auto_iterate_repairs_known_target_compatibility_failure(tmp_path: Path) -> None:
    service = WorkbenchService(WorkbenchStore(tmp_path / "workbench.json"))
    stream = await service.run_build_stream(
        project_id=None,
        brief="Build a CX agent with a local diagnostic tool.",
        target="cx",
        agent=_InvalidCxToolAgent(),
        auto_iterate=True,
        max_iterations=2,
    )

    events = await _collect_service_stream(stream)

    iterations = [event for event in events if event["event"] == "iteration.started"]
    validations = [event for event in events if event["event"] == "validation.ready"]
    terminal = events[-1]
    project_id = terminal["data"]["project_id"]
    snapshot = service.get_plan_snapshot(project_id=project_id)

    assert len(iterations) == 2
    assert iterations[1]["data"]["mode"] == "correction"
    assert len(validations) == 2
    assert validations[0]["data"]["status"] == "failed"
    assert validations[1]["data"]["status"] == "passed"
    assert terminal["event"] == "run.completed"
    assert terminal["data"]["status"] == "completed"
    assert terminal["data"]["validation"]["status"] == "passed"
    assert terminal["data"]["evidence_summary"]["correction_status"] == "corrected"
    assert terminal["data"]["evidence_summary"]["improvement_status"] == "changed"
    assert not any(tool["type"] == "local_shell" for tool in snapshot["model"]["tools"])


@pytest.mark.asyncio
async def test_structural_validation_without_change_evidence_is_not_success(tmp_path: Path) -> None:
    service = WorkbenchService(WorkbenchStore(tmp_path / "workbench.json"))
    stream = await service.run_build_stream(
        project_id=None,
        brief="Build a support agent.",
        target="portable",
        agent=_NoEvidenceAgent(),
        auto_iterate=False,
        max_iterations=1,
    )

    events = await _collect_service_stream(stream)
    terminal = events[-1]

    assert terminal["event"] == "run.completed"
    assert terminal["data"]["status"] == "failed"
    assert terminal["data"]["failure_reason"] == "insufficient_completion_evidence"
    assert terminal["data"]["validation"]["status"] == "passed"
    assert terminal["data"]["evidence_summary"]["structural_status"] == "passed"
    assert terminal["data"]["evidence_summary"]["improvement_status"] == "missing"
    assert terminal["data"]["review_gate"]["status"] == "blocked"


def _leaf_count(plan_payload: dict) -> int:
    """Count the leaves in a serialized plan tree."""
    if not isinstance(plan_payload, dict):
        return 0
    children = plan_payload.get("children") or []
    if not children:
        return 1
    total = 0
    for child in children:
        total += _leaf_count(child)
    return total
