"""Tests for the streaming Workbench builder agent + SSE endpoint."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.workbench import router
from builder.workbench import WorkbenchService, WorkbenchStore, _append_text_delta, build_review_gate
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


def test_append_text_delta_keeps_word_boundary_chunks_readable() -> None:
    text = _append_text_delta("Here's the plan for your Lawn", "and Garden Support agent. I")
    text = _append_text_delta(text, "'ll start with Define role")
    text = _append_text_delta(text, "and capabilities.")

    assert text == "Here's the plan for your Lawn and Garden Support agent. I'll start with Define role and capabilities."


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


@pytest.mark.asyncio
async def test_mock_agent_uses_phone_billing_domain_for_wireless_bill_briefs() -> None:
    agent = MockWorkbenchBuilderAgent()
    request = BuildRequest(
        project_id="wb-phone-billing",
        brief=(
            "Build a Verizon-like phone-company support agent that explains bills, "
            "monthly plan charges, device payments, taxes, surcharges, one-time fees, "
            "roaming, credits, and why a wireless bill changed."
        ),
        target="portable",
    )

    events: list[dict] = []
    async for event in agent.run(request, project={"project_id": "wb-phone-billing"}):
        events.append(event)

    plan = events[0]["data"]["plan"]
    artifacts = [event["data"]["artifact"] for event in events if event["event"] == "artifact.updated"]
    artifact_text = "\n".join(
        str(artifact.get("name", "")) + "\n" + str(artifact.get("source", ""))
        for artifact in artifacts
    )

    assert plan["title"].startswith("Build Phone Billing Support agent")
    assert "phone_billing_explainer" in artifact_text
    assert "Phone Billing Support Agent" in artifact_text
    assert "IT Helpdesk" not in artifact_text
    assert "it_helpdesk" not in artifact_text


@pytest.mark.asyncio
async def test_mock_agent_uses_lawn_garden_domain_for_greenhouse_guide_briefs() -> None:
    agent = MockWorkbenchBuilderAgent()
    request = BuildRequest(
        project_id="wb-greenhouse-guide",
        brief=(
            "Build Greenhouse Guide, a lawn and garden store website chat agent. "
            "It should answer plant care, planting-plan, delivery, return, and escalation questions. "
            "It should avoid unsupported medical or pesticide safety claims."
        ),
        target="portable",
    )

    events: list[dict] = []
    async for event in agent.run(request, project={"project_id": "wb-greenhouse-guide"}):
        events.append(event)

    plan = events[0]["data"]["plan"]
    artifacts = [event["data"]["artifact"] for event in events if event["event"] == "artifact.updated"]
    artifact_text = "\n".join(
        str(artifact.get("name", "")) + "\n" + str(artifact.get("source", ""))
        for artifact in artifacts
    )

    assert plan["title"].startswith("Build Lawn and Garden Support agent")
    assert "Lawn and Garden Support Agent" in artifact_text
    assert "plant_care_guide_lookup" in artifact_text
    assert "No Unsupported Pesticide or Medical Claims" in artifact_text
    assert "Healthcare Intake" not in artifact_text
    assert "HIPAA" not in artifact_text
    assert "agent_lookup" not in artifact_text


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

    # Structure: turn.started seeds the multi-turn log, then plan.ready,
    # build.completed, reflect/present phases, turn.completed, and terminal
    # run.completed. Every event carries a turn_id so the UI can group events
    # even across multi-iteration loops.
    event_names = [ev["event"] for ev in events]
    assert event_names[0] == "turn.started"
    assert "plan.ready" in event_names
    assert "build.completed" in event_names
    assert "run.completed" in event_names
    assert events[-1]["event"] == "run.completed"
    final_project_id = events[-1]["data"]["project_id"]
    assert final_project_id.startswith("wb-")
    assert events[-1]["data"]["run_id"].startswith("run-")
    handoff = events[-1]["data"]["handoff"]
    assert handoff["run_id"] == events[-1]["data"]["run_id"]
    assert handoff["last_event"]["event"] == "run.completed"
    assert handoff["progress"]["total_tasks"] >= 5
    assert handoff["progress"]["completed_tasks"] == handoff["progress"]["total_tasks"]
    assert handoff["verification"]["status"] == "passed"
    assert handoff["next_action"]

    # Task status lifecycle is consistent.
    tasks_started = {ev["data"]["task_id"] for ev in events if ev["event"] == "task.started"}
    tasks_completed = {ev["data"]["task_id"] for ev in events if ev["event"] == "task.completed"}
    assert tasks_started == tasks_completed
    assert len(tasks_started) >= 5  # at least 5 leaf tasks in the canned plan

    # Every data payload is tagged with the same turn_id so the UI can
    # group events by turn even when multi-iteration loops run.
    turn_ids = {ev["data"].get("turn_id") for ev in events if ev["data"].get("turn_id")}
    assert len(turn_ids) == 1


@pytest.mark.asyncio
async def test_harness_metrics_update_snapshot_harness_state(tmp_path: Path) -> None:
    """Harness metrics should survive streaming as durable snapshot state."""

    class MetricsAgent:
        async def run(self, request: BuildRequest, project: dict) -> object:
            yield {
                "event": "harness.metrics",
                "data": {
                    "steps_completed": 2,
                    "total_steps": 4,
                    "tokens_used": 123,
                    "cost_usd": 0.001,
                    "elapsed_ms": 50,
                    "current_phase": "executing",
                },
            }
            yield {"event": "build.completed", "data": {"operations": []}}

    store = WorkbenchStore(tmp_path / "workbench.json")
    service = WorkbenchService(store)

    stream = await service.run_build_stream(
        project_id=None,
        brief="Build a support agent.",
        agent=MetricsAgent(),
    )
    events = [event async for event in stream]
    project_id = events[-1]["data"]["project_id"]

    snapshot = service.get_plan_snapshot(project_id=project_id)
    assert snapshot["harness_state"]["last_metrics"]["tokens_used"] == 123
    assert snapshot["harness_state"]["latest_handoff"]["run_id"] == events[-1]["data"]["run_id"]
    assert snapshot["harness_state"]["latest_handoff"]["metrics"]["tokens_used"] == 123


def test_build_stream_runs_reflect_and_present_phases(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    response = client.post(
        "/api/workbench/build/stream",
        json={
            "brief": "Build an airline support agent with flight status tools.",
            "target": "portable",
            "mock": True,
        },
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    names = [event["event"] for event in events]
    assert "build.completed" in names
    assert "reflect.started" in names
    assert "reflect.completed" in names
    assert "present.ready" in names
    assert "run.completed" in names
    assert names[-1] == "run.completed"
    assert names.index("build.completed") < names.index("reflect.started")
    assert names.index("reflect.completed") < names.index("present.ready")
    assert names.index("present.ready") < names.index("run.completed")

    run_completed = next(event["data"] for event in events if event["event"] == "run.completed")
    assert run_completed["status"] == "completed"
    assert run_completed["phase"] == "presenting"
    assert run_completed["version"] >= 2
    assert run_completed["validation"]["status"] == "passed"
    assert run_completed["presentation"]["next_actions"]
    assert run_completed["project"]["model"]["tools"]
    assert run_completed["exports"]["adk"]["files"]["agent.py"]


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
    assert body["build_status"] == "completed"
    assert body["active_run"]["status"] == "completed"
    assert body["active_run"]["phase"] == "presenting"
    assert body["active_run"]["validation"]["status"] == "passed"
    assert len(body["active_run"]["events"]) >= len(events)
    assert body["messages"], "assistant narration should survive reload"
    assert body["plan"] is not None
    assert body["plan"]["status"] in {PlanTaskStatus.DONE.value, PlanTaskStatus.RUNNING.value}
    assert len(body["artifacts"]) >= 3
    # Running the build should have applied operations that bumped the version.
    assert body["version"] >= 2
    # Canonical model carries at least one tool generated by the build.
    assert len(body["model"]["tools"]) >= 1


def test_build_stream_handoff_recovers_brief_from_saved_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    saved_config = tmp_path / "configs" / "v001.yaml"
    saved_config.parent.mkdir()
    saved_config.write_text(
        """
journey_build:
  agent_name: Greenhouse Guide
  source_prompt: >
    Build Greenhouse Guide, a lawn and garden store website chat agent.
    It should answer plant care, planting-plan, delivery, return, and escalation questions.
    It should avoid unsupported medical or pesticide safety claims.
""",
        encoding="utf-8",
    )
    client = _make_client(tmp_path)

    response = client.post(
        "/api/workbench/build/stream",
        json={
            "brief": "Continue building Greenhouse Guide from the saved Build config.",
            "config_path": str(saved_config),
            "target": "portable",
            "mock": True,
            "max_iterations": 1,
        },
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    project_id = events[-1]["data"]["project_id"]
    snapshot = client.get(f"/api/workbench/projects/{project_id}/plan").json()
    artifact_text = "\n".join(
        str(artifact.get("name", "")) + "\n" + str(artifact.get("source", ""))
        for artifact in snapshot["artifacts"]
    )
    assert snapshot["last_brief"].startswith("Build Greenhouse Guide, a lawn and garden store")
    assert "Lawn and Garden Support Agent" in artifact_text
    assert "No Unsupported Pesticide or Medical Claims" in artifact_text
    assert "agent_lookup" not in artifact_text


def test_build_stream_persists_one_user_conversation_message_per_turn(tmp_path: Path) -> None:
    """The durable planner transcript should not duplicate a user brief."""
    client = _make_client(tmp_path)
    brief = "Build a refund support agent with escalation rules."

    response = client.post(
        "/api/workbench/build/stream",
        json={"brief": brief, "mock": True, "max_iterations": 1},
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    project_id = events[-1]["data"]["project_id"]
    turn_id = events[0]["data"]["turn_id"]

    snapshot = client.get(f"/api/workbench/projects/{project_id}/plan").json()
    user_messages = [
        message
        for message in snapshot["conversation"]
        if message["role"] == "user" and message.get("turn_id") == turn_id
    ]

    assert len(user_messages) == 1
    assert user_messages[0]["content"] == brief


def test_completed_run_exposes_review_gate_and_handoff(tmp_path: Path) -> None:
    """Terminal payloads should make review status and resume context explicit."""
    client = _make_client(tmp_path)

    response = client.post(
        "/api/workbench/build/stream",
        json={
            "brief": "Build an airline support agent with flight status tools.",
            "target": "portable",
            "mock": True,
            "max_iterations": 1,
        },
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    completed = next(event["data"] for event in events if event["event"] == "run.completed")
    presentation = completed["presentation"]

    review_gate = presentation["review_gate"]
    assert review_gate["status"] == "review_required"
    assert review_gate["promotion_status"] == "draft"
    assert review_gate["requires_human_review"] is True
    assert review_gate["blocking_reasons"] == []
    checks = {check["name"]: check for check in review_gate["checks"]}
    assert checks["harness_validation"]["status"] == "passed"
    assert checks["target_compatibility"]["status"] == "passed"
    assert checks["human_review"]["status"] == "required"
    assert completed["review_gate"] == review_gate

    presentation_handoff = presentation["handoff"]
    assert presentation_handoff["project_id"] == completed["project_id"]
    assert presentation_handoff["run_id"] == completed["run_id"]
    assert presentation_handoff["version"] == completed["version"]
    assert presentation_handoff["review_gate_status"] == "review_required"
    assert presentation_handoff["last_event_sequence"] >= 1
    assert "Resume Workbench project" in presentation_handoff["resume_prompt"]

    durable_handoff = completed["handoff"]
    assert durable_handoff["project_id"] == completed["project_id"]
    assert durable_handoff["run_id"] == completed["run_id"]
    assert durable_handoff["last_event"]["event"] == "run.completed"
    assert durable_handoff["verification"]["status"] == "passed"
    assert durable_handoff["next_action"]


def test_review_gate_blocks_failed_validation_and_invalid_compatibility() -> None:
    """Promotion must stay blocked when machine checks fail."""
    review_gate = build_review_gate(
        {
            "compatibility": [{"status": "invalid", "label": "CX-only local shell"}],
            "last_test": {"status": "failed"},
        },
        run={"validation": {"status": "failed"}},
    )

    assert review_gate["status"] == "blocked"
    checks = {check["name"]: check for check in review_gate["checks"]}
    assert checks["harness_validation"]["status"] == "failed"
    assert checks["target_compatibility"]["status"] == "failed"
    assert checks["human_review"]["status"] == "required"
    assert review_gate["blocking_reasons"] == [
        "Latest harness validation is failed.",
        "1 invalid target compatibility diagnostic(s).",
    ]


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
    assert snapshot["build_status"] == "completed"


@pytest.mark.asyncio
async def test_run_build_stream_marks_run_failed_when_agent_raises(tmp_path: Path) -> None:
    store = WorkbenchStore(tmp_path / "workbench.json")
    from builder.workbench import WorkbenchService

    class FailingAgent:
        """Test agent that raises after the project/run has been created."""

        async def run(self, request: BuildRequest, project: dict) -> object:
            raise RuntimeError("planner crashed")
            yield  # pragma: no cover

    service = WorkbenchService(store)
    stream = await service.run_build_stream(
        project_id=None,
        brief="Build a support agent.",
        target="portable",
        agent=FailingAgent(),
    )

    events = [event async for event in stream]
    event_names = [event["event"] for event in events]
    assert event_names[-1] == "run.failed"
    assert "error" in event_names
    assert "turn.completed" in event_names
    project_id = events[-1]["data"]["project_id"]
    snapshot = service.get_plan_snapshot(project_id=project_id)
    assert snapshot["build_status"] == "failed"
    assert snapshot["active_run"]["status"] == "failed"
    assert snapshot["active_run"]["error"] == "planner crashed"
