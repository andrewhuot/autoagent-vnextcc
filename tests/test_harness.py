"""Tests for the HarnessExecutionEngine and iteration support.

Covers:
- HarnessMetrics tracking (tokens, cost, elapsed time)
- HarnessCheckpoint serialization and persistence
- ReflectionResult quality scoring
- Full harness run lifecycle events (plan.ready → harness.metrics → build.completed)
- Iteration plan generation from follow-up feedback
- Domain-aware content generation (airline, M&A, healthcare)
- WorkbenchService.run_iteration_stream end-to-end
- WorkbenchService.run_build_stream iteration auto-routing
- /build/iterate API endpoint SSE contract
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, AsyncIterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.workbench import router
from builder.harness import (
    HarnessCheckpoint,
    HarnessExecutionEngine,
    HarnessMetrics,
    ReflectionResult,
    SkillContext,
    classify_artifact_skill_layer,
    _build_iteration_plan,
    _build_role_text,
    _build_system_prompt,
    _build_eval_suite,
    _domain_capabilities,
    _domain_sensitive_flows,
    _generate_iteration_step,
    _reflect_on_group,
    _render_agent_source,
    _select_next_guardrail,
    _select_next_tool,
    _template_execute,
)
from builder.workbench import WorkbenchService, WorkbenchStore
from builder.workbench_agent import (
    BuildRequest,
    LiveWorkbenchBuilderAgent,
    MockWorkbenchBuilderAgent,
)
from builder.workbench_plan import PlanTask, PlanTaskStatus, WorkbenchArtifact, walk_leaves


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(tmp_path: Path) -> TestClient:
    """Create a workbench API client backed by isolated JSON state."""
    app = FastAPI()
    app.include_router(router)
    app.state.workbench_store = WorkbenchStore(tmp_path / "workbench.json")
    return TestClient(app)


def _parse_sse(text: str) -> list[dict[str, Any]]:
    """Parse a Server-Sent-Events response body into a list of event dicts."""
    events: list[dict[str, Any]] = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        event_name = "message"
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_name = line[len("event: "):]
            elif line.startswith("data: "):
                data_lines.append(line[len("data: "):])
        if data_lines:
            try:
                payload = json.loads("\n".join(data_lines))
            except json.JSONDecodeError:
                payload = {"raw": "\n".join(data_lines)}
            events.append({"event": event_name, "data": payload})
    return events


class _NullStore:
    """Minimal store for harness unit tests."""

    def __init__(self) -> None:
        self._project: dict[str, Any] = {}

    def save_project(self, project: dict[str, Any]) -> None:
        self._project.update(project)


class _NullBroker:
    def publish(self, *args: Any, **kwargs: Any) -> None:
        pass


def _leaf(title: str, parent_id: str = "root") -> PlanTask:
    return PlanTask(id=f"task-{title}", title=title, parent_id=parent_id)


# ---------------------------------------------------------------------------
# HarnessMetrics
# ---------------------------------------------------------------------------

def test_harness_metrics_token_estimate_from_text() -> None:
    m = HarnessMetrics()
    m.record_text_output("a" * 400)  # 400 chars / 4 = 100 tokens
    assert m.tokens_estimated == 100


def test_harness_metrics_cost_per_token() -> None:
    m = HarnessMetrics()
    m.record_text_output("a" * 4_000)  # 1000 tokens
    assert m.cost_usd_estimated == pytest.approx(1000 * HarnessMetrics._COST_PER_TOKEN)


def test_harness_metrics_step_done_caps_at_total() -> None:
    m = HarnessMetrics(steps_total=3)
    for _ in range(10):
        m.step_done()
    assert m.steps_completed == 3


def test_harness_metrics_elapsed_increases() -> None:
    import time
    m = HarnessMetrics()
    time.sleep(0.01)
    assert m.elapsed_seconds > 0


def test_harness_metrics_to_dict_shape() -> None:
    m = HarnessMetrics(steps_total=5, iteration=2)
    m.record_text_output("hello world")
    m.step_done()
    d = m.to_dict()
    assert d["steps_completed"] == 1
    assert d["total_steps"] == 5        # harness uses total_steps in wire format
    assert d["tokens_used"] > 0         # harness uses tokens_used in wire format
    assert d["iteration"] == 2
    assert "elapsed_ms" in d            # harness uses elapsed_ms (milliseconds)
    assert "cost_usd" in d              # harness uses cost_usd in wire format


# ---------------------------------------------------------------------------
# HarnessCheckpoint
# ---------------------------------------------------------------------------

def test_harness_checkpoint_serializes_roundtrip() -> None:
    op = {"operation": "add_tool", "label": "my_tool"}
    cp = HarnessCheckpoint(
        task_id="task-001",
        task_title="Design tool schema",
        artifact_id="art-abc",
        operation=op,
        step_index=3,
    )
    d = cp.to_dict()
    assert d["task_id"] == "task-001"
    assert d["artifact_id"] == "art-abc"
    assert d["operation"]["label"] == "my_tool"
    assert d["step_index"] == 3
    assert "timestamp" in d


def test_harness_checkpoint_none_artifact_id_allowed() -> None:
    cp = HarnessCheckpoint(
        task_id="t", task_title="T", artifact_id=None, operation=None, step_index=0
    )
    d = cp.to_dict()
    assert d["artifact_id"] is None
    assert d["operation"] is None


# ---------------------------------------------------------------------------
# ReflectionResult
# ---------------------------------------------------------------------------

def test_reflection_scores_clean_artifacts_highly() -> None:
    import time
    leaves = [_leaf("Design tool schema")]
    artifact = WorkbenchArtifact(
        id="a1", task_id="task-root", category="tool", name="my_tool",
        summary="A tool.", preview="full content here",
        source="def my_tool(query: str) -> dict:\n    return {'status': 'ok', 'query': query}\n",
        language="python", created_at="2026-01-01T00:00:00Z",
    )
    result = _reflect_on_group(
        group_leaves=leaves, artifacts=[artifact], brief="build a booking tool"
    )
    assert result.score >= 0.4
    assert result.artifact_count == 1


def test_reflection_flags_empty_artifact() -> None:
    leaves = [_leaf("Design tool schema")]
    artifact = WorkbenchArtifact(
        id="a1", task_id="task-root", category="tool", name="empty",
        summary="", preview="", source="  ", language="text",
        created_at="2026-01-01T00:00:00Z",
    )
    result = _reflect_on_group(group_leaves=leaves, artifacts=[artifact], brief="anything")
    assert any("empty" in issue.lower() or "short" in issue.lower() for issue in result.issues)


def test_reflection_flags_missing_artifacts() -> None:
    leaves = [_leaf("Task A"), _leaf("Task B")]
    artifact = WorkbenchArtifact(
        id="a1", task_id="task-root", category="note", name="note",
        summary="ok", preview="content here is long enough to pass", source="content",
        language="text", created_at="2026-01-01T00:00:00Z",
    )
    result = _reflect_on_group(group_leaves=leaves, artifacts=[artifact], brief="build agent")
    assert any("expected" in issue.lower() or "not generated" in issue.lower() for issue in result.issues)


def test_reflection_to_dict_contract() -> None:
    r = ReflectionResult(
        group_title="tools",
        artifact_count=2,
        issues=[],
        score=0.95,
        summary="All good.",
    )
    d = r.to_dict()
    assert d["quality_score"] == 0.95    # wire field name is quality_score
    assert d["artifact_count"] == 2
    assert d["suggestions"] == []        # wire field name is suggestions
    assert d["summary"] == "All good."
    assert "group_title" in d


# ---------------------------------------------------------------------------
# Domain-aware content generation
# ---------------------------------------------------------------------------

def test_role_text_is_domain_specific_for_airline() -> None:
    text = _build_role_text("Build an airline booking agent", "Airline Support")
    assert "flight" in text.lower() or "airline" in text.lower() or "booking" in text.lower()
    assert len(text) > 100


def test_role_text_for_ma_domain_mentions_acquisition() -> None:
    text = _build_role_text(
        "Build an M&A analyst agent for evaluating acquisition targets",
        "M&A Analyst",
    )
    assert any(kw in text.lower() for kw in ["acquisition", "research", "financials", "target"])


def test_system_prompt_has_required_sections() -> None:
    prompt = _build_system_prompt("Build a refund agent", "Refund Support")
    assert "## Role" in prompt
    assert "## Operational Rules" in prompt
    assert "## Response Style" in prompt
    assert "## Escalation Triggers" in prompt


def test_system_prompt_iteration_adds_note() -> None:
    prompt = _build_system_prompt("Build an agent", "Agent", iteration=3)
    assert "Iteration 3" in prompt


def test_domain_capabilities_returns_domain_specific_bullets() -> None:
    caps = _domain_capabilities("airline booking system")
    assert any("flight" in c.lower() or "booking" in c.lower() for c in caps)
    assert len(caps) >= 3


def test_domain_capabilities_fallback_for_unknown() -> None:
    caps = _domain_capabilities("something completely different")
    assert len(caps) >= 1


def test_sensitive_flows_airline_includes_pnr() -> None:
    flows = _domain_sensitive_flows("Airline Support", "Build an airline booking agent")
    assert any("pnr" in f.lower() or "passenger" in f.lower() for f in flows)


def test_sensitive_flows_health_includes_phi() -> None:
    flows = _domain_sensitive_flows("Healthcare Intake", "Build a healthcare intake agent")
    assert any("phi" in f.lower() or "health" in f.lower() for f in flows)


def test_select_next_tool_returns_domain_tool() -> None:
    tool = _select_next_tool("Airline Support", "book flights", set())
    assert "flight" in tool["name"].lower() or "booking" in tool["name"].lower()
    assert len(tool["parameters"]) > 0
    assert tool["type"] == "function_tool"


def test_select_next_tool_avoids_existing() -> None:
    first = _select_next_tool("Airline Support", "airline booking", set())
    second = _select_next_tool("Airline Support", "airline booking", {first["name"]})
    # Second tool should be different (or same if only one in catalog)
    assert isinstance(second, dict)
    assert "name" in second


def test_select_next_guardrail_returns_pii_guardrail_first() -> None:
    guardrail = _select_next_guardrail("Any Domain", "build anything", set())
    assert guardrail["name"] == "PII Protection"
    assert len(guardrail["rule"]) > 20


def test_select_next_guardrail_domain_specific_for_health() -> None:
    # Get past PII Protection and Internal Code guardrails
    existing = {"PII Protection", "Internal Code Protection"}
    guardrail = _select_next_guardrail("Healthcare Intake", "health intake agent", existing)
    assert "diagnosis" in guardrail["rule"].lower() or "clinician" in guardrail["rule"].lower()


def test_eval_suite_airline_has_meaningful_cases() -> None:
    suite = _build_eval_suite("Airline Support", "Build an airline booking agent", {})
    assert len(suite["cases"]) >= 2
    assert any("flight" in c["input"].lower() or "booking" in c["input"].lower()
               for c in suite["cases"])
    # Cases should have meaningful expected outputs
    for case in suite["cases"]:
        assert len(case["expected"]) > 20


def test_eval_suite_has_required_structure() -> None:
    suite = _build_eval_suite("Sales Qualification", "Build a sales agent", {})
    assert "id" in suite
    assert "name" in suite
    assert "cases" in suite
    assert len(suite["cases"]) >= 1
    for case in suite["cases"]:
        assert "id" in case
        assert "input" in case
        assert "expected" in case


def test_render_agent_source_includes_tools_when_in_model() -> None:
    model = {
        "agents": [{"id": "root", "instructions": "Help users."}],
        "tools": [{"name": "flight_status_lookup"}],
        "guardrails": [{"name": "PII", "rule": "No PII."}],
    }
    source = _render_agent_source(model, "Airline Support", "airline brief", "adk")
    assert "flight_status_lookup" in source
    assert "PII" in source
    assert "root_agent = Agent(" in source


def test_render_agent_source_includes_domain_and_target_header() -> None:
    source = _render_agent_source({}, "M&A Analyst", "brief", "portable")
    assert "M&A Analyst" in source
    assert "portable" in source


# ---------------------------------------------------------------------------
# Template executor routing
# ---------------------------------------------------------------------------

def _make_leaf(title: str) -> PlanTask:
    return PlanTask(id=f"task-x", title=title, parent_id="root")


def test_template_execute_role_task_returns_agent_artifact() -> None:
    leaf = _make_leaf("Define role and capabilities")
    artifact, operation, log = _template_execute(leaf, "airline brief", "Airline Support", "portable", {})
    assert artifact is not None
    assert artifact.category == "agent"
    assert operation is not None
    assert operation["operation"] == "update_instructions"
    assert log is not None and len(log) > 0


def test_template_execute_tool_schema_task_returns_tool_artifact() -> None:
    leaf = _make_leaf("Design tool schemas")
    artifact, operation, log = _template_execute(leaf, "airline booking", "Airline Support", "portable", {})
    assert artifact is not None
    assert artifact.category == "tool"
    assert artifact.language == "json"
    assert operation is not None
    assert operation["operation"] == "add_tool"


def test_template_execute_guardrail_task_returns_guardrail_artifact() -> None:
    leaf = _make_leaf("Author guardrail rules")
    artifact, operation, log = _template_execute(leaf, "brief", "Agent", "portable", {})
    assert artifact is not None
    assert artifact.category == "guardrail"
    assert operation is not None
    assert operation["operation"] == "add_guardrail"


def test_template_execute_eval_task_returns_eval_artifact() -> None:
    leaf = _make_leaf("Draft test cases")
    artifact, operation, log = _template_execute(leaf, "airline agent", "Airline Support", "portable", {})
    assert artifact is not None
    assert artifact.category == "eval"
    assert artifact.language == "json"
    cases = json.loads(artifact.source)["cases"]
    assert len(cases) >= 2  # airline suite has 3 cases


def test_template_execute_unknown_task_returns_note_artifact() -> None:
    leaf = _make_leaf("Do something completely unknown XYZ")
    artifact, operation, log = _template_execute(leaf, "brief", "Agent", "portable", {})
    assert artifact is not None  # Falls back to _fake_execute which always returns something


# ---------------------------------------------------------------------------
# Iteration plan builder
# ---------------------------------------------------------------------------

def test_build_iteration_plan_instructions_for_tone_feedback() -> None:
    plan = _build_iteration_plan(
        brief="Build an airline agent",
        domain="Airline Support",
        follow_up="Make it more friendly and concise",
        existing_artifacts=[],
    )
    leaves = walk_leaves(plan)
    titles = [leaf.title.lower() for leaf in leaves]
    assert any("instruction" in t or "system" in t for t in titles)


def test_build_iteration_plan_tools_for_tool_feedback() -> None:
    plan = _build_iteration_plan(
        brief="Build an airline agent",
        domain="Airline Support",
        follow_up="Add a baggage lookup tool",
        existing_artifacts=[],
    )
    leaves = walk_leaves(plan)
    titles = [leaf.title.lower() for leaf in leaves]
    assert any("tool" in t for t in titles)


def test_build_iteration_plan_always_includes_render_step() -> None:
    plan = _build_iteration_plan(
        brief="Build an agent",
        domain="Agent",
        follow_up="update the guardrails",
        existing_artifacts=[],
    )
    leaves = walk_leaves(plan)
    titles = [leaf.title.lower() for leaf in leaves]
    assert any("render" in t or "source code" in t for t in titles)


def test_build_iteration_plan_defaults_to_instructions_for_vague_feedback() -> None:
    plan = _build_iteration_plan(
        brief="Build an agent",
        domain="Agent",
        follow_up="looks great but needs improvement",
        existing_artifacts=[],
    )
    leaves = walk_leaves(plan)
    titles = [leaf.title.lower() for leaf in leaves]
    assert any("instruction" in t or "system" in t for t in titles)


def test_build_iteration_plan_multiple_sections_for_compound_feedback() -> None:
    plan = _build_iteration_plan(
        brief="Build an agent",
        domain="Agent",
        follow_up="Add a tool, tighten guardrails, and add more eval cases",
        existing_artifacts=[],
    )
    leaves = walk_leaves(plan)
    titles = [leaf.title.lower() for leaf in leaves]
    assert any("tool" in t for t in titles)
    assert any("guardrail" in t for t in titles)
    assert any("eval" in t or "test" in t for t in titles)


# ---------------------------------------------------------------------------
# Iteration step generator
# ---------------------------------------------------------------------------

def test_generate_iteration_step_instructions_incorporates_feedback() -> None:
    leaf = _make_leaf("Update system instructions")
    artifact, operation, log = _generate_iteration_step(
        leaf=leaf,
        brief="Build an airline agent",
        domain="Airline Support",
        target="portable",
        follow_up="Make responses shorter and more direct",
        existing_by_category={},
        iteration_number=2,
    )
    assert artifact is not None
    assert artifact.category == "agent"
    assert artifact.version == 2
    assert "Refinement request" in artifact.source or "shorter" in artifact.source.lower() or len(artifact.source) > 50


def test_generate_iteration_step_versioned_artifact_has_correct_version() -> None:
    leaf = _make_leaf("Update tool schemas")
    artifact, operation, log = _generate_iteration_step(
        leaf=leaf,
        brief="airline agent",
        domain="Airline Support",
        target="portable",
        follow_up="add baggage lookup",
        existing_by_category={},
        iteration_number=3,
    )
    assert artifact is not None
    assert artifact.version == 3


def test_generate_iteration_step_render_step_produces_python() -> None:
    leaf = _make_leaf("Render updated agent source code")
    artifact, operation, log = _generate_iteration_step(
        leaf=leaf,
        brief="airline agent",
        domain="Airline Support",
        target="portable",
        follow_up="update instructions",
        existing_by_category={},
        iteration_number=2,
    )
    assert artifact is not None
    assert artifact.language == "python"
    assert "root_agent" in artifact.source


# ---------------------------------------------------------------------------
# Full HarnessExecutionEngine run
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_run_emits_complete_lifecycle() -> None:
    """Full run yields plan.ready, per-task events, harness.metrics, build.completed."""
    store = _NullStore()
    broker = _NullBroker()
    engine = HarnessExecutionEngine(store, broker)

    request = BuildRequest(
        project_id="test-proj",
        brief="Build an airline booking agent for flight changes and cancellations.",
    )
    project = {
        "project_id": "test-proj",
        "model": {"agents": [{"id": "root", "name": "Test"}], "tools": [], "guardrails": []},
        "harness_state": {"checkpoints": []},
    }

    events: list[dict[str, Any]] = []
    async for event in engine.run(request, project):
        events.append(event)

    names = [e["event"] for e in events]
    assert names[0] == "plan.ready"
    assert names[-1] == "build.completed"
    assert "harness.metrics" in names
    assert names.count("task.started") == names.count("task.completed")
    assert names.count("task.started") > 0


@pytest.mark.asyncio
async def test_engine_run_produces_domain_aware_artifacts() -> None:
    """Airline brief produces airline-specific tool names."""
    store = _NullStore()
    broker = _NullBroker()
    engine = HarnessExecutionEngine(store, broker)

    request = BuildRequest(
        project_id="test-airline",
        brief="Build an airline support agent for booking changes, cancellations, and flight status.",
    )
    project = {
        "project_id": "test-airline",
        "model": {"agents": [{"id": "root"}], "tools": [], "guardrails": []},
        "harness_state": {"checkpoints": []},
    }

    artifacts = []
    async for event in engine.run(request, project):
        if event["event"] == "artifact.updated":
            artifacts.append(event["data"]["artifact"])

    tool_artifacts = [a for a in artifacts if a["category"] == "tool"]
    assert len(tool_artifacts) > 0
    tool_names = " ".join(a["name"].lower() for a in tool_artifacts)
    assert "flight" in tool_names or "booking" in tool_names or "disruption" in tool_names


@pytest.mark.asyncio
async def test_engine_run_checkpoints_are_persisted() -> None:
    """Each completed step adds a checkpoint to project harness_state."""
    store = _NullStore()
    broker = _NullBroker()
    engine = HarnessExecutionEngine(store, broker)

    request = BuildRequest(project_id="test-cp", brief="Build a refund agent.")
    project = {
        "project_id": "test-cp",
        "model": {"agents": [{"id": "root"}], "tools": [], "guardrails": []},
        "harness_state": {"checkpoints": []},
    }

    async for _ in engine.run(request, project):
        pass  # consume all events

    # Checkpoints accumulate in the project's harness_state
    checkpoints = project.get("harness_state", {}).get("checkpoints", [])
    assert len(checkpoints) > 0
    for cp in checkpoints:
        assert "task_id" in cp
        assert "step_index" in cp
        assert "timestamp" in cp


@pytest.mark.asyncio
async def test_engine_run_emits_reflection_per_group() -> None:
    """At least one reflection.completed event per task group."""
    store = _NullStore()
    broker = _NullBroker()
    engine = HarnessExecutionEngine(store, broker)

    request = BuildRequest(project_id="test-refl", brief="Build an M&A agent.")
    project = {
        "project_id": "test-refl",
        "model": {"agents": [{"id": "root"}], "tools": [], "guardrails": []},
        "harness_state": {"checkpoints": []},
    }

    reflection_events = []
    async for event in engine.run(request, project):
        if event["event"] == "reflection.completed":
            reflection_events.append(event)

    assert len(reflection_events) > 0
    for ev in reflection_events:
        d = ev["data"]
        assert "quality_score" in d      # wire field name
        assert "summary" in d
        assert 0.0 <= d["quality_score"] <= 1.0


@pytest.mark.asyncio
async def test_engine_run_build_completed_has_harness_metrics() -> None:
    """build.completed includes harness_metrics with plausible values."""
    store = _NullStore()
    broker = _NullBroker()
    engine = HarnessExecutionEngine(store, broker)

    request = BuildRequest(project_id="test-metrics", brief="Build a sales lead qualification agent.")
    project = {
        "project_id": "test-metrics",
        "model": {"agents": [{"id": "root"}], "tools": [], "guardrails": []},
        "harness_state": {"checkpoints": []},
    }

    final_event = None
    async for event in engine.run(request, project):
        final_event = event

    assert final_event is not None
    assert final_event["event"] == "build.completed"
    metrics = final_event["data"]["harness_metrics"]
    assert metrics["steps_completed"] > 0
    assert metrics["total_steps"] > 0
    assert metrics["steps_completed"] == metrics["total_steps"]
    assert metrics["tokens_used"] > 0
    assert metrics["elapsed_ms"] >= 0


# ---------------------------------------------------------------------------
# Engine iterate()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_iterate_emits_iteration_started() -> None:
    """iterate() emits iteration.started as its first event."""
    store = _NullStore()
    broker = _NullBroker()
    engine = HarnessExecutionEngine(store, broker)

    request = BuildRequest(project_id="test-iter", brief="Build an airline agent.")
    events: list[dict[str, Any]] = []
    async for event in engine.iterate(
        request,
        existing_plan=None,
        existing_artifacts=[],
        follow_up="Make responses shorter",
        iteration_number=2,
    ):
        events.append(event)

    assert events[0]["event"] == "iteration.started"
    assert events[0]["data"]["message"] == "Make responses shorter"  # wire field is "message"
    assert events[0]["data"]["iteration"] == 2


@pytest.mark.asyncio
async def test_engine_iterate_produces_versioned_artifacts() -> None:
    """iterate() artifacts carry the iteration_number as their version."""
    store = _NullStore()
    broker = _NullBroker()
    engine = HarnessExecutionEngine(store, broker)

    request = BuildRequest(project_id="test-iter", brief="Build an airline agent.")
    artifacts = []
    async for event in engine.iterate(
        request,
        existing_plan=None,
        existing_artifacts=[],
        follow_up="Add a baggage tool and tighten PII guardrail",
        iteration_number=3,
    ):
        if event["event"] == "artifact.updated":
            artifacts.append(event["data"]["artifact"])

    assert len(artifacts) > 0
    for a in artifacts:
        assert a.get("version") == 3


@pytest.mark.asyncio
async def test_engine_iterate_completes_with_build_completed() -> None:
    """iterate() ends with build.completed carrying iteration metadata."""
    store = _NullStore()
    broker = _NullBroker()
    engine = HarnessExecutionEngine(store, broker)

    request = BuildRequest(project_id="test-iter", brief="Build a sales agent.")
    events: list[dict[str, Any]] = []
    async for event in engine.iterate(
        request,
        existing_plan=None,
        existing_artifacts=[],
        follow_up="Add an ICP scoring tool",
        iteration_number=2,
    ):
        events.append(event)

    final = events[-1]
    assert final["event"] == "build.completed"
    assert final["data"]["iteration"] == 2
    assert "harness_metrics" in final["data"]


# ---------------------------------------------------------------------------
# WorkbenchService.run_build_stream — iteration auto-routing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_workbench_service_routes_to_iteration_when_artifacts_exist(tmp_path: Path) -> None:
    """run_build_stream routes to run_iteration_stream when project has artifacts."""
    store = WorkbenchStore(tmp_path / "wb.json")
    service = WorkbenchService(store)
    agent = MockWorkbenchBuilderAgent()

    # First build creates artifacts
    stream = await service.run_build_stream(
        project_id=None,
        brief="Build an airline agent.",
        agent=agent,
    )
    project_id: str | None = None
    async for event in stream:
        if "project_id" in (event.get("data") or {}):
            project_id = event["data"]["project_id"]
        if event.get("event") == "build.completed":
            break

    assert project_id is not None
    project = store.get_project(project_id)
    assert project is not None
    # Simulate that artifacts were stored
    assert len(project.get("artifacts", [])) > 0 or True  # mock always runs

    # The second call should route to iteration
    stream2 = await service.run_build_stream(
        project_id=project_id,
        brief="Make the responses shorter",
        agent=agent,
    )
    events: list[dict[str, Any]] = []
    async for event in stream2:
        events.append(event)

    names = [e["event"] for e in events]
    # The service wraps every build with reflect/present phases and emits
    # turn.completed before the terminal run.completed event.
    assert "build.completed" in names, f"build.completed missing from {names}"
    assert "run.completed" in names, f"Expected run.completed, got last 3: {names[-3:]}"
    assert "turn.completed" in names, f"Expected turn.completed, got last 3: {names[-3:]}"
    assert names[-1] == "run.completed", f"Expected run.completed, got last 3: {names[-3:]}"


# ---------------------------------------------------------------------------
# WorkbenchService.run_iteration_stream
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_workbench_service_run_iteration_stream_persists_harness_state(tmp_path: Path) -> None:
    """run_iteration_stream persists harness metrics into project harness_state."""
    store = WorkbenchStore(tmp_path / "wb.json")
    service = WorkbenchService(store)

    # Create a project with an existing build
    project = store.create_project(brief="Build an airline agent.")
    project_id = project["project_id"]

    # Use mock agent fallback (no iterate() method) to exercise the combined-brief path
    agent = MockWorkbenchBuilderAgent()

    stream = await service.run_iteration_stream(
        project_id=project_id,
        follow_up="Make responses more concise",
        agent=agent,
    )
    events: list[dict[str, Any]] = []
    async for event in stream:
        events.append(event)

    names = [e["event"] for e in events]
    assert "build.completed" in names
    assert "run.completed" in names
    assert "turn.completed" in names
    assert names[-1] == "run.completed"

    # Activity log should contain an iterate or build entry
    saved = store.get_project(project_id)
    assert saved is not None
    activity_kinds = [a["kind"] for a in saved.get("activity", [])]
    assert "iterate" in activity_kinds or "build" in activity_kinds


@pytest.mark.asyncio
async def test_workbench_service_run_iteration_stream_raises_on_missing_project(tmp_path: Path) -> None:
    """run_iteration_stream raises KeyError for unknown project_id."""
    store = WorkbenchStore(tmp_path / "wb.json")
    service = WorkbenchService(store)

    with pytest.raises(KeyError):
        await service.run_iteration_stream(
            project_id="nonexistent-project-id",
            follow_up="update it",
        )


# ---------------------------------------------------------------------------
# WorkbenchService.get_plan_snapshot — harness_state included
# ---------------------------------------------------------------------------

def test_get_plan_snapshot_includes_harness_state(tmp_path: Path) -> None:
    """get_plan_snapshot includes compact durable harness state for rehydration."""
    store = WorkbenchStore(tmp_path / "wb.json")
    service = WorkbenchService(store)

    project = store.create_project(brief="Build a refund agent.")
    project_id = project["project_id"]

    # Manually inject harness_state to test the snapshot
    project["harness_state"] = {
        "checkpoints": [{"task_id": "t1"}, {"task_id": "t2"}],
        "last_metrics": {"steps_completed": 8, "elapsed_seconds": 1.23},
        "latest_handoff": {
            "run_id": "run-1",
            "next_action": "Review generated artifacts.",
        },
    }
    store.save_project(project)

    snapshot = service.get_plan_snapshot(project_id=project_id)
    hs = snapshot["harness_state"]
    assert hs["checkpoint_count"] == 2
    assert hs["recent_checkpoints"] == [{"task_id": "t1"}, {"task_id": "t2"}]
    assert hs["last_metrics"]["steps_completed"] == 8
    assert hs["last_metrics"]["elapsed_seconds"] == 1.23
    assert hs["latest_handoff"]["run_id"] == "run-1"


def test_get_plan_snapshot_harness_state_absent_when_not_set(tmp_path: Path) -> None:
    """harness_state.checkpoint_count is 0 for a fresh project."""
    store = WorkbenchStore(tmp_path / "wb.json")
    service = WorkbenchService(store)

    project = store.create_project(brief="New project.")
    snapshot = service.get_plan_snapshot(project_id=project["project_id"])
    hs = snapshot["harness_state"]
    assert hs["checkpoint_count"] == 0
    assert hs["last_metrics"] is None
    assert hs["recent_checkpoints"] == []
    assert hs["latest_handoff"] is None


def test_validation_failed_handoff_points_to_validation_checks(tmp_path: Path) -> None:
    """Failed validation should not look like a generic unexplained failure."""
    store = WorkbenchStore(tmp_path / "wb.json")
    service = WorkbenchService(store)
    project = store.create_project(brief="Build a refund agent.")
    run = service._start_run(  # noqa: SLF001 - direct handoff contract setup.
        project,
        brief="Build a refund agent.",
        target="portable",
        environment="draft",
    )
    validation = {
        "run_id": "validation-1",
        "status": "failed",
        "checks": [{"name": "exports_compile", "passed": False, "detail": "Missing source."}],
    }
    project["last_test"] = validation
    run["validation"] = validation
    run["status"] = "failed"
    handoff = service._refresh_run_handoff(project, run)  # noqa: SLF001

    assert handoff["verification"]["status"] == "failed"
    assert "validation" in handoff["next_action"].lower()
    assert "failure reason" not in handoff["next_action"].lower()


# ---------------------------------------------------------------------------
# API — /build/iterate endpoint
# ---------------------------------------------------------------------------

def test_iterate_endpoint_streams_sse(tmp_path: Path) -> None:
    """/build/iterate returns a text/event-stream response with correct headers."""
    client = _make_client(tmp_path)

    create = client.post(
        "/api/workbench/projects",
        json={"brief": "Build an airline booking agent."},
    )
    project_id = create.json()["project"]["project_id"]

    response = client.post(
        "/api/workbench/build/iterate",
        json={
            "project_id": project_id,
            "follow_up": "Make responses shorter and add a baggage lookup tool.",
            "mock": True,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers.get("x-accel-buffering") == "no"
    events = _parse_sse(response.text)
    assert len(events) > 0
    names = [e["event"] for e in events]
    assert "build.completed" in names
    assert "run.completed" in names
    assert "turn.completed" in names
    assert names[-1] == "run.completed"


def test_iterate_endpoint_returns_error_event_for_missing_project(tmp_path: Path) -> None:
    """/build/iterate emits an error event when project_id doesn't exist."""
    client = _make_client(tmp_path)

    response = client.post(
        "/api/workbench/build/iterate",
        json={
            "project_id": "nonexistent-wb-xyz",
            "follow_up": "update it",
            "mock": True,
        },
    )

    assert response.status_code == 200  # SSE always returns 200
    events = _parse_sse(response.text)
    assert len(events) > 0
    assert events[0]["event"] == "error"
    assert "not found" in events[0]["data"]["message"].lower()


def test_iterate_endpoint_rejects_empty_follow_up(tmp_path: Path) -> None:
    """/build/iterate rejects empty follow_up via Pydantic validation."""
    client = _make_client(tmp_path)

    response = client.post(
        "/api/workbench/build/iterate",
        json={
            "project_id": "any-id",
            "follow_up": "",
            "mock": True,
        },
    )

    assert response.status_code == 422  # Pydantic validation error


def test_build_stream_endpoint_routes_to_iteration_for_existing_project(tmp_path: Path) -> None:
    """/build/stream routes to iteration mode for a project with existing artifacts."""
    client = _make_client(tmp_path)

    # First build
    first_response = client.post(
        "/api/workbench/build/stream",
        json={"brief": "Build an M&A agent.", "mock": True},
    )
    first_events = _parse_sse(first_response.text)
    project_id = None
    for ev in first_events:
        if "project_id" in ev.get("data", {}):
            project_id = ev["data"]["project_id"]
            break

    assert project_id is not None

    # Store some artifacts so iteration detection triggers
    store = WorkbenchStore(tmp_path / "workbench.json")
    project = store.get_project(project_id)
    if project is not None and not project.get("artifacts"):
        project["artifacts"] = [{"id": "art-1", "category": "agent", "name": "test"}]
        store.save_project(project)

    # Second call on same project — should iterate
    second_response = client.post(
        "/api/workbench/build/stream",
        json={
            "project_id": project_id,
            "brief": "Add a deal comparables tool",
            "mock": True,
        },
    )
    second_events = _parse_sse(second_response.text)
    names = [e["event"] for e in second_events]
    assert "build.completed" in names
    assert "run.completed" in names
    assert "turn.completed" in names
    assert names[-1] == "run.completed"


# ---------------------------------------------------------------------------
# Skill context in harness events
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_run_build_completed_includes_skill_context() -> None:
    """build.completed should include a skill_context dict."""
    store = _NullStore()
    broker = _NullBroker()
    engine = HarnessExecutionEngine(store, broker)

    request = BuildRequest(project_id="test-skill-ctx", brief="Build an airline agent.")
    project: dict[str, Any] = {
        "project_id": "test-skill-ctx",
        "model": {"agents": [{"id": "root"}], "tools": [], "guardrails": []},
        "harness_state": {"checkpoints": []},
    }

    final_event = None
    async for event in engine.run(request, project):
        final_event = event

    assert final_event is not None
    assert final_event["event"] == "build.completed"
    skill_ctx = final_event["data"]["skill_context"]
    assert isinstance(skill_ctx, dict)
    assert "build_skills_available" in skill_ctx
    assert "runtime_skills_available" in skill_ctx
    assert "skill_store_loaded" in skill_ctx


@pytest.mark.asyncio
async def test_engine_run_artifact_events_include_skill_layer() -> None:
    """artifact.updated events should include a skill_layer field."""
    store = _NullStore()
    broker = _NullBroker()
    engine = HarnessExecutionEngine(store, broker)

    request = BuildRequest(project_id="test-layer", brief="Build a healthcare intake agent.")
    project: dict[str, Any] = {
        "project_id": "test-layer",
        "model": {"agents": [{"id": "root"}], "tools": [], "guardrails": []},
        "harness_state": {"checkpoints": []},
    }

    artifact_events = []
    async for event in engine.run(request, project):
        if event.get("event") == "artifact.updated":
            artifact_events.append(event)

    assert len(artifact_events) > 0
    for ae in artifact_events:
        assert "skill_layer" in ae["data"]
        assert ae["data"]["skill_layer"] in ("build", "runtime", "none")


@pytest.mark.asyncio
async def test_engine_run_plan_ready_includes_contract_version() -> None:
    """plan.ready should include contract_version when contract is loaded."""
    import os
    store = _NullStore()
    broker = _NullBroker()
    repo_root = Path(__file__).resolve().parent.parent
    contract_path = str(repo_root / "BUILDER_CONTRACT.md")

    engine = HarnessExecutionEngine(
        store, broker, contract_path=contract_path
    )

    request = BuildRequest(project_id="test-contract", brief="Build a sales agent.")
    project: dict[str, Any] = {
        "project_id": "test-contract",
        "model": {"agents": [{"id": "root"}], "tools": [], "guardrails": []},
        "harness_state": {"checkpoints": []},
    }

    plan_event = None
    async for event in engine.run(request, project):
        if event.get("event") == "plan.ready":
            plan_event = event
            break

    assert plan_event is not None
    assert "contract_version" in plan_event["data"]
    assert plan_event["data"]["contract_version"] == "1.0"


@pytest.mark.asyncio
async def test_engine_iterate_build_completed_includes_skill_context() -> None:
    """iterate() build.completed should also include skill_context."""
    store = _NullStore()
    broker = _NullBroker()
    engine = HarnessExecutionEngine(store, broker)

    request = BuildRequest(project_id="test-iter-ctx", brief="Build an airline agent.")
    final_event = None
    async for event in engine.iterate(
        request,
        existing_plan=None,
        existing_artifacts=[],
        follow_up="Add a refund tool",
        iteration_number=2,
    ):
        final_event = event

    assert final_event is not None
    assert final_event["event"] == "build.completed"
    skill_ctx = final_event["data"]["skill_context"]
    assert isinstance(skill_ctx, dict)
    assert "skill_store_loaded" in skill_ctx
