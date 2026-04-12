"""Tests for the LLM-driven LiveWorkbenchBuilderAgent.

Uses a ``StubRouter`` that returns pre-canned JSON so tests stay
deterministic and never make real API calls. Exercises:
- happy-path planner → executor flow
- malformed-JSON retries then fallback to the mock body
- operations flowing into the canonical model so downstream tasks see fresh
  state
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from builder.workbench_agent import (
    BuildRequest,
    LiveWorkbenchBuilderAgent,
    _parse_json_object,
    _plan_from_llm_payload,
)
from builder.workbench_plan import PlanTask, PlanTaskStatus, walk_leaves


@dataclass
class StubResponse:
    text: str
    provider: str = "stub"
    model: str = "stub-model"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class StubRouter:
    """Dumb LLMRouter replacement that serves a queue of canned responses."""

    mock_mode = False

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[Any] = []

    def generate(self, request: Any) -> StubResponse:
        self.calls.append(request)
        if not self._responses:
            raise RuntimeError("StubRouter exhausted")
        return StubResponse(text=self._responses.pop(0))


def _plan_response() -> str:
    return json.dumps(
        {
            "assistant_intro": "Here's the plan I'll execute for you.",
            "root": {
                "title": "Build M&A agent",
                "description": "Evaluate acquisition targets.",
                "children": [
                    {
                        "title": "Create tools",
                        "description": "Generate the tool the agent will call.",
                        "children": [
                            {
                                "title": "Design tool schema",
                                "description": "Design one tool.",
                                "kind": "tool_schema",
                            }
                        ],
                    },
                    {
                        "title": "Add safety",
                        "description": "Author a guardrail.",
                        "children": [
                            {
                                "title": "Author guardrail",
                                "description": "PII protection.",
                                "kind": "guardrail",
                            }
                        ],
                    },
                ],
            },
        }
    )


def _tool_schema_response() -> str:
    return json.dumps(
        {
            "name": "company_research",
            "description": "Pull public financials for a target company.",
            "parameters": ["company_name"],
            "type": "function_tool",
        }
    )


def _guardrail_response() -> str:
    return json.dumps(
        {
            "name": "Material Non-Public Information",
            "rule": "Never disclose material non-public information about any target.",
        }
    )


# ---------------------------------------------------------------------------
# _parse_json_object tolerates fences and surrounding prose
# ---------------------------------------------------------------------------
def test_parse_json_object_strips_code_fences() -> None:
    text = """```json
{"role_summary": "hello"}
```"""
    assert _parse_json_object(text) == {"role_summary": "hello"}


def test_parse_json_object_finds_object_inside_prose() -> None:
    text = "Sure, here you go: {\"name\": \"x\"} hope that helps"
    assert _parse_json_object(text) == {"name": "x"}


def test_parse_json_object_returns_none_on_garbage() -> None:
    assert _parse_json_object("no json here") is None
    assert _parse_json_object("{ not valid ") is None


# ---------------------------------------------------------------------------
# Planner payload validation
# ---------------------------------------------------------------------------
def test_plan_from_llm_payload_rejects_unknown_kind() -> None:
    payload = {
        "title": "Root",
        "description": "desc",
        "children": [
            {
                "title": "Group",
                "description": "",
                "children": [
                    {"title": "bad", "description": "", "kind": "unknown_kind"}
                ],
            }
        ],
    }
    assert _plan_from_llm_payload(payload, brief="brief", domain="Agent") is None


def test_plan_from_llm_payload_accepts_two_level_tree() -> None:
    payload = {
        "title": "Root",
        "description": "desc",
        "children": [
            {
                "title": "Group",
                "description": "",
                "children": [
                    {"title": "leaf", "description": "", "kind": "guardrail"}
                ],
            }
        ],
    }
    plan = _plan_from_llm_payload(payload, brief="brief", domain="Agent")
    assert plan is not None
    leaves = walk_leaves(plan)
    assert len(leaves) == 1
    assert "kind:guardrail" in (leaves[0].log or [])


# ---------------------------------------------------------------------------
# Happy path end-to-end — harness engine lifecycle
#
# WHY: LiveWorkbenchBuilderAgent.run() now delegates to HarnessExecutionEngine
# which always runs a full plan tree (~8 leaves) regardless of router canned
# responses. The router is used only as an optional LLM enhancement layer;
# the engine falls back to domain-aware template generation when the router
# response doesn't parse (or the router is exhaust). Tests verify the
# complete lifecycle and that domain-relevant artifacts are produced.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_live_agent_happy_path_emits_harness_lifecycle() -> None:
    """Harness engine emits plan.ready, per-task events, metrics, and build.completed."""
    router = StubRouter(
        [_plan_response(), _tool_schema_response(), _guardrail_response()]
    )
    agent = LiveWorkbenchBuilderAgent(router=router)

    request = BuildRequest(
        project_id="wb-live",
        brief="Build an M&A agent that evaluates acquisition targets.",
    )
    project = {"project_id": "wb-live", "model": {"agents": [{"id": "root", "name": "X"}]}}

    events: list[dict[str, Any]] = []
    async for event in agent.run(request, project):
        events.append(event)

    names = [event["event"] for event in events]
    assert names[0] == "plan.ready", f"First event should be plan.ready, got {names[:3]}"
    assert names[-1] == "build.completed", f"Last event should be build.completed, got {names[-3:]}"

    # Harness engine always runs the full plan tree — expect multiple tasks
    assert names.count("task.started") > 0
    assert names.count("task.started") == names.count("task.completed"), (
        "Every started task must complete"
    )

    # Artifacts are domain-aware: M&A brief should produce tool + guardrail categories
    artifact_events = [e for e in events if e["event"] == "artifact.updated"]
    assert len(artifact_events) > 0, "Expected at least one artifact"
    categories = {e["data"]["artifact"]["category"] for e in artifact_events}
    assert "tool" in categories, f"Expected tool artifact, got: {categories}"

    # Harness metrics event should appear
    assert "harness.metrics" in names, "Expected at least one harness.metrics event"

    # build.completed carries harness_metrics
    final = events[-1]["data"]
    assert "operations" in final
    assert "harness_metrics" in final
    # Wire format uses elapsed_ms (int milliseconds) from HarnessMetrics.to_dict()
    assert isinstance(final["harness_metrics"]["elapsed_ms"], int)


@pytest.mark.asyncio
async def test_live_agent_emits_reflection_events() -> None:
    """HarnessExecutionEngine emits reflection.completed after each task group."""
    router = StubRouter([])  # no LLM responses — use template generation
    agent = LiveWorkbenchBuilderAgent(router=router)

    request = BuildRequest(project_id="wb-reflect", brief="Build a healthcare intake agent.")
    project = {"project_id": "wb-reflect", "model": {"agents": [{"id": "root"}]}}

    events: list[dict] = []
    async for event in agent.run(request, project):
        events.append(event)

    reflection_events = [e for e in events if e["event"] == "reflection.completed"]
    assert len(reflection_events) > 0, "Expected at least one reflection.completed event"

    first_reflection = reflection_events[0]["data"]
    assert "quality_score" in first_reflection   # wire field name from ReflectionResult.to_dict()
    assert "summary" in first_reflection
    assert "artifact_count" in first_reflection
    assert 0.0 <= first_reflection["quality_score"] <= 1.0


# ---------------------------------------------------------------------------
# Retry + fallback: exhausted router still produces a complete build
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_live_agent_completes_build_when_router_exhausted() -> None:
    """Template generation handles all steps when the router runs out of responses."""
    router = StubRouter([])  # empty — forces template fallback immediately
    agent = LiveWorkbenchBuilderAgent(router=router)

    request = BuildRequest(project_id="wb-fail", brief="Build a sales agent.")
    project = {"project_id": "wb-fail", "model": {"agents": [{"id": "root"}]}}

    events: list[dict] = []
    async for event in agent.run(request, project):
        events.append(event)

    # Template generation completes the full lifecycle
    assert events[-1]["event"] == "build.completed"
    # At least one task produced an operation from template generation
    assert any(
        event["event"] == "task.completed" and event["data"]["operations"]
        for event in events
    )


# ---------------------------------------------------------------------------
# Graceful degradation: RuntimeError in engine falls back to mock agent
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_live_agent_falls_back_to_mock_on_engine_error() -> None:
    """If the engine raises, the agent falls back to MockWorkbenchBuilderAgent."""

    class BrokenRouter:
        mock_mode = False

        def generate(self, _: Any) -> Any:
            raise RuntimeError("router exploded")

    agent = LiveWorkbenchBuilderAgent(router=BrokenRouter())

    request = BuildRequest(project_id="wb-plan-fail", brief="Build an airline agent.")
    project = {"project_id": "wb-plan-fail", "model": {"agents": [{"id": "root"}]}}

    events: list[dict] = []
    async for event in agent.run(request, project):
        events.append(event)

    # Should still complete — the mock fallback runs when the engine errors
    assert events[-1]["event"] == "build.completed"
    plan_ready = next((e for e in events if e["event"] == "plan.ready"), None)
    assert plan_ready is not None
    assert plan_ready["data"]["plan"]["title"].startswith("Build ")
