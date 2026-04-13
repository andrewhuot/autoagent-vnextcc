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
# Happy path end-to-end
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_live_agent_happy_path_emits_events_from_canned_responses() -> None:
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
    assert names[0] == "plan.ready"
    assert names[-1] == "build.completed"
    # The harness engine builds a richer plan tree from the brief, so the
    # task count may exceed the 2-leaf canned plan; verify lifecycle balance.
    assert names.count("task.started") == names.count("task.completed")
    assert names.count("task.started") >= 2

    # Harness produces domain-aware artifacts across multiple categories.
    artifact_events = [e for e in events if e["event"] == "artifact.updated"]
    assert len(artifact_events) >= 2
    categories = {e["data"]["artifact"]["category"] for e in artifact_events}
    assert len(categories) >= 2  # at least two distinct categories

    # Operations are accumulated in the build.completed event.
    final = events[-1]["data"]["operations"]
    assert len(final) >= 2
    op_types = {op["operation"] for op in final}
    assert len(op_types) >= 2  # at least two distinct operation types


# ---------------------------------------------------------------------------
# Retry + fallback: malformed JSON triggers fallback to the mock executor
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_live_agent_falls_back_to_mock_on_persistent_parse_errors() -> None:
    garbage = "not json at all"
    # Plan is OK, but every executor response is garbage.
    router = StubRouter([_plan_response()] + [garbage] * 20)
    agent = LiveWorkbenchBuilderAgent(router=router, max_json_retries=1)

    request = BuildRequest(project_id="wb-fail", brief="Build a sales agent.")
    project = {"project_id": "wb-fail", "model": {"agents": [{"id": "root"}]}}

    events: list[dict] = []
    async for event in agent.run(request, project):
        events.append(event)

    # Still emits a complete lifecycle even though the LLM gave junk.
    assert events[-1]["event"] == "build.completed"
    # At least one task still produced an operation thanks to the mock fallback.
    assert any(
        event["event"] == "task.completed" and event["data"]["operations"]
        for event in events
    )
    assert any(
        event["event"] == "task.completed" and event["data"].get("source") == "template"
        for event in events
    )


@pytest.mark.asyncio
async def test_live_agent_require_live_raises_on_provider_generation_failure() -> None:
    """Strict live mode must fail instead of presenting template output as live."""
    router = StubRouter(["not json at all"] * 20)
    agent = LiveWorkbenchBuilderAgent(router=router, max_json_retries=0)

    request = BuildRequest(
        project_id="wb-strict-live",
        brief="Build a support agent.",
        require_live=True,
    )
    project = {"project_id": "wb-strict-live", "model": {"agents": [{"id": "root"}]}}

    with pytest.raises(RuntimeError, match="Live Workbench generation"):
        async for _event in agent.run(request, project):
            pass


# ---------------------------------------------------------------------------
# When the planner itself fails, the agent falls back to the canned plan.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_live_agent_falls_back_to_mock_plan_when_planner_errors() -> None:
    router = StubRouter(["garbage"] * 20)
    agent = LiveWorkbenchBuilderAgent(router=router, max_json_retries=0)

    request = BuildRequest(project_id="wb-plan-fail", brief="Build an airline agent.")
    project = {"project_id": "wb-plan-fail", "model": {"agents": [{"id": "root"}]}}

    events: list[dict] = []
    async for event in agent.run(request, project):
        events.append(event)

    # A plan.ready event was still emitted — it's the mock fallback tree.
    plan_ready = next(event for event in events if event["event"] == "plan.ready")
    assert plan_ready["data"]["plan"]["title"].startswith("Build ")
    assert events[-1]["event"] == "build.completed"
