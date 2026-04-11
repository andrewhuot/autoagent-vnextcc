"""Tests for the streaming Workbench builder agent + SSE endpoint."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.workbench import router
from builder.workbench import WorkbenchStore
from builder.workbench_agent import (
    BuildRequest,
    MockWorkbenchBuilderAgent,
)
from builder.workbench_plan import (
    PlanTask,
    PlanTaskStatus,
    WorkbenchArtifact,
    find_task,
    recompute_parent_status,
    walk_all,
    walk_leaves,
)


# ---------------------------------------------------------------------------
# Unit: plan tree data model
# ---------------------------------------------------------------------------
def test_plan_task_serializes_roundtrip() -> None:
    root = PlanTask(
        id="task-root",
        title="Build agent",
        description="Top-level build",
        children=[
            PlanTask(id="task-a", title="Plan", parent_id="task-root"),
            PlanTask(id="task-b", title="Tools", parent_id="task-root"),
        ],
    )
    payload = root.to_dict()
    restored = PlanTask.from_dict(payload)
    assert restored.id == "task-root"
    assert [child.title for child in restored.children] == ["Plan", "Tools"]
    assert restored.to_dict() == payload


def test_recompute_parent_status_bubbles_done_up() -> None:
    root = PlanTask(
        id="r",
        title="root",
        children=[
            PlanTask(id="a", title="a", status=PlanTaskStatus.DONE.value, parent_id="r"),
            PlanTask(id="b", title="b", status=PlanTaskStatus.DONE.value, parent_id="r"),
        ],
    )
    recompute_parent_status(root)
    assert root.status == PlanTaskStatus.DONE.value


def test_recompute_parent_status_running_when_mixed() -> None:
    root = PlanTask(
        id="r",
        title="root",
        children=[
            PlanTask(id="a", title="a", status=PlanTaskStatus.DONE.value, parent_id="r"),
            PlanTask(id="b", title="b", status=PlanTaskStatus.RUNNING.value, parent_id="r"),
            PlanTask(id="c", title="c", status=PlanTaskStatus.PENDING.value, parent_id="r"),
        ],
    )
    recompute_parent_status(root)
    assert root.status == PlanTaskStatus.RUNNING.value


def test_recompute_parent_status_error_overrides_running() -> None:
    root = PlanTask(
        id="r",
        title="root",
        children=[
            PlanTask(id="a", title="a", status=PlanTaskStatus.DONE.value, parent_id="r"),
            PlanTask(id="b", title="b", status=PlanTaskStatus.ERROR.value, parent_id="r"),
        ],
    )
    recompute_parent_status(root)
    assert root.status == PlanTaskStatus.ERROR.value


def test_walk_leaves_and_find_task_traverse_nested_tree() -> None:
    root = PlanTask(
        id="r",
        title="root",
        children=[
            PlanTask(
                id="g1",
                title="group 1",
                children=[
                    PlanTask(id="l1", title="leaf 1"),
                    PlanTask(id="l2", title="leaf 2"),
                ],
            ),
            PlanTask(
                id="g2",
                title="group 2",
                children=[PlanTask(id="l3", title="leaf 3")],
            ),
        ],
    )
    assert [leaf.id for leaf in walk_leaves(root)] == ["l1", "l2", "l3"]
    assert [node.id for node in walk_all(root)] == ["r", "g1", "l1", "l2", "g2", "l3"]
    assert find_task(root, "l2") is not None
    assert find_task(root, "l2").title == "leaf 2"
    assert find_task(root, "missing") is None


def test_workbench_artifact_serializes_roundtrip() -> None:
    artifact = WorkbenchArtifact(
        id="art-1",
        task_id="task-a",
        category="tool",
        name="flight_status_lookup",
        summary="Looks up flight status",
        preview="def flight_status_lookup(...): ...",
        source="def flight_status_lookup(...): ...",
        language="python",
        created_at="2026-01-01T00:00:00Z",
    )
    restored = WorkbenchArtifact.from_dict(artifact.to_dict())
    assert restored.id == "art-1"
    assert restored.language == "python"


# ---------------------------------------------------------------------------
# Unit: mock agent emits the full event sequence
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_mock_agent_emits_full_event_sequence() -> None:
    agent = MockWorkbenchBuilderAgent()
    request = BuildRequest(
        project_id="wb-test",
        brief="Build an airline support agent for delayed flights.",
        target="portable",
    )

    events: list[dict] = []
    async for event in agent.run(request, project={"project_id": "wb-test"}):
        events.append(event)

    event_names = [event["event"] for event in events]

    # Must start with plan.ready and end with build.completed.
    assert event_names[0] == "plan.ready"
    assert event_names[-1] == "build.completed"

    # Plan tree is non-trivial.
    plan = events[0]["data"]["plan"]
    assert plan["title"].startswith("Build ")
    assert len(plan["children"]) >= 3

    # Every task.started has a matching task.completed.
    started = [ev for ev in events if ev["event"] == "task.started"]
    completed = [ev for ev in events if ev["event"] == "task.completed"]
    assert len(started) == len(completed)
    assert {ev["data"]["task_id"] for ev in started} == {
        ev["data"]["task_id"] for ev in completed
    }

    # At least one artifact was emitted.
    artifacts = [ev for ev in events if ev["event"] == "artifact.updated"]
    assert len(artifacts) >= 3
    categories = {ev["data"]["artifact"]["category"] for ev in artifacts}
    # The mock agent always produces at least agent, tool, and eval artifacts.
    assert {"agent", "tool", "eval"}.issubset(categories)


# ---------------------------------------------------------------------------
# Integration: SSE endpoint end-to-end
# ---------------------------------------------------------------------------
def _make_client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.workbench_store = WorkbenchStore(tmp_path / "workbench.json")
    return TestClient(app)


def _parse_sse(stream_body: str) -> list[dict]:
    """Parse an SSE response body into a list of ``{event, data}`` dicts."""
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


def test_build_stream_endpoint_emits_sse_events(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    response = client.post(
        "/api/workbench/build/stream",
        json={
            "brief": "Build an M&A agent that evaluates acquisition targets.",
            "target": "portable",
            "mock": True,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers.get("x-accel-buffering") == "no"

    events = _parse_sse(response.text)
    assert events, "expected at least one SSE event"

    # Multi-turn structure: turn.started wraps the run, plan.ready is the
    # second event, build.completed closes the agent pass, and
    # turn.completed is the final event consumed by the UI.
    event_names = [ev["event"] for ev in events]
    assert event_names[0] == "turn.started"
    assert event_names[1] == "iteration.started"
    assert event_names[2] == "plan.ready"
    assert event_names[-1] == "turn.completed"
    assert "build.completed" in event_names
    assert "validation.ready" in event_names
    final_project_id = events[-1]["data"]["project_id"]
    assert final_project_id.startswith("wb-")

    # Task status lifecycle is consistent.
    tasks_started = {ev["data"]["task_id"] for ev in events if ev["event"] == "task.started"}
    tasks_completed = {ev["data"]["task_id"] for ev in events if ev["event"] == "task.completed"}
    assert tasks_started == tasks_completed
    assert len(tasks_started) >= 5  # at least 5 leaf tasks in the canned plan

    # Every data payload is tagged with the same turn_id so the UI can
    # group events by turn even when multi-iteration loops run.
    turn_ids = {ev["data"].get("turn_id") for ev in events if ev["data"].get("turn_id")}
    assert len(turn_ids) == 1


def test_build_stream_persists_plan_and_artifacts(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    response = client.post(
        "/api/workbench/build/stream",
        json={"brief": "Build a refund support agent.", "mock": True},
    )
    events = _parse_sse(response.text)
    project_id = events[-1]["data"]["project_id"]

    snapshot = client.get(f"/api/workbench/projects/{project_id}/plan")
    assert snapshot.status_code == 200
    body = snapshot.json()

    assert body["project_id"] == project_id
    assert body["build_status"] == "idle"
    assert body["plan"] is not None
    assert body["plan"]["status"] in {PlanTaskStatus.DONE.value, PlanTaskStatus.RUNNING.value}
    assert len(body["artifacts"]) >= 3
    # Running the build should have applied operations that bumped the version.
    assert body["version"] >= 2
    # Canonical model carries at least one tool generated by the build.
    assert len(body["model"]["tools"]) >= 1


def test_build_stream_creates_project_when_no_id_provided(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    response = client.post(
        "/api/workbench/build/stream",
        json={"brief": "Build a sales qualification agent.", "mock": True},
    )
    assert response.status_code == 200

    events = _parse_sse(response.text)
    project_ids = {ev["data"].get("project_id") for ev in events}
    project_ids.discard(None)
    assert len(project_ids) == 1, "all events should carry one consistent project_id"


def test_build_stream_existing_project_appends_version(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    create = client.post(
        "/api/workbench/projects",
        json={"brief": "Build an airline support agent."},
    )
    assert create.status_code == 201
    project_id = create.json()["project"]["project_id"]
    starting_version = create.json()["project"]["version"]

    response = client.post(
        "/api/workbench/build/stream",
        json={
            "project_id": project_id,
            "brief": "Build a flight status lookup and PII guardrail.",
            "mock": True,
        },
    )
    assert response.status_code == 200

    snapshot = client.get(f"/api/workbench/projects/{project_id}/plan").json()
    assert snapshot["version"] > starting_version
    assert snapshot["plan"] is not None
    assert snapshot["build_status"] == "idle"
