"""Workbench builder agent — plans and executes an agent build from a brief.

WHY: The old Workbench planner (``builder.workbench.infer_operations``) was
deterministic regex-matching. This module wraps that deterministic core in a
streaming, plan-tree-driven agent that can run in two modes:

- **mock mode**: emits a canned but realistic sequence of events so the UI
  can be developed, tested, and demoed without an API key.
- **live mode**: uses ``optimizer.providers.LLMRouter`` to ask a real LLM
  (Claude by default) to produce the plan tree and per-task operations.

In both modes the agent emits the *same* event stream:

    plan.ready          {plan: PlanTask}
    task.started        {task_id}
    message.delta       {task_id, text}
    task.progress       {task_id, note}
    artifact.updated    {task_id, artifact: WorkbenchArtifact}
    task.completed      {task_id, operations: [...]}
    build.completed     {project_id, operations: [...]}
    error               {task_id?, message}

Phase 1 implements mock mode end-to-end. Phase 3 adds the live planner and
executor under the same interface.
"""

from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

from builder.types import new_id
from builder.workbench import (
    _infer_domain,
    _now_iso,
    _slugify,
    build_compatibility_diagnostics,
    compile_workbench_exports,
    render_adk_agent_py,
    render_adk_tools_py,
    render_cx_agent_json,
    render_cx_playbook,
)
from builder.workbench_plan import (
    PlanTask,
    PlanTaskStatus,
    WorkbenchArtifact,
    walk_leaves,
)


BuildEvent = dict[str, Any]


# ---------------------------------------------------------------------------
# Request shape
# ---------------------------------------------------------------------------
@dataclass
class BuildRequest:
    """One end-to-end build request sourced from the Workbench UI."""

    project_id: str
    brief: str
    target: str = "portable"
    environment: str = "draft"


# ---------------------------------------------------------------------------
# Factory — picks live vs. mock based on env / router capability
# ---------------------------------------------------------------------------
def build_default_agent(*, force_mock: bool = False) -> "WorkbenchBuilderAgent":
    """Return a live or mock builder agent depending on runtime capability.

    Phase 1 always returns the mock agent. Phase 3 will consult
    ``optimizer.providers.build_router_from_runtime_config`` and only fall back
    to mock when the router is itself in mock mode. The interface stays the
    same so callers never need to branch.
    """
    if force_mock:
        return MockWorkbenchBuilderAgent()
    return MockWorkbenchBuilderAgent()


# ---------------------------------------------------------------------------
# Base interface
# ---------------------------------------------------------------------------
class WorkbenchBuilderAgent:
    """Abstract interface — ``run()`` yields typed build events."""

    async def run(
        self,
        request: BuildRequest,
        project: dict[str, Any],
    ) -> AsyncIterator[BuildEvent]:
        """Yield a sequence of streaming build events. Subclasses implement."""
        raise NotImplementedError
        # pragma: no cover - type-only
        yield {}  # type: ignore[unreachable]


# ---------------------------------------------------------------------------
# Mock agent — deterministic, no LLM, fast enough for tests
# ---------------------------------------------------------------------------
class MockWorkbenchBuilderAgent(WorkbenchBuilderAgent):
    """Deterministic agent that emits a scripted but realistic build."""

    def __init__(self, *, step_delay: float = 0.0) -> None:
        """Initialize with an optional artificial delay between steps."""
        self._step_delay = step_delay

    async def run(
        self,
        request: BuildRequest,
        project: dict[str, Any],
    ) -> AsyncIterator[BuildEvent]:
        """Yield plan + per-task events then a terminal build.completed event."""
        brief = request.brief.strip() or "Help users with the requested workflow."
        domain = _infer_domain(brief)
        plan = _build_plan_tree(brief, domain)

        yield {"event": "plan.ready", "data": {"plan": plan.to_dict()}}
        await self._tick()

        root_id = plan.id
        welcome = (
            f"Here's the plan for your {domain} agent. I'll create the agent definition, "
            f"generate tools, wire guardrails, draft an evaluation suite, and render the "
            f"source code so you can review it."
        )
        for chunk in _chunk(welcome, 28):
            yield {
                "event": "message.delta",
                "data": {"task_id": root_id, "text": chunk},
            }
            await self._tick(0.03)

        applied_operations: list[dict[str, Any]] = []

        for leaf in walk_leaves(plan):
            yield {"event": "task.started", "data": {"task_id": leaf.id}}
            await self._tick()

            artifact, operation, log_line = _fake_execute(leaf, brief, domain, request.target)
            if log_line:
                yield {
                    "event": "task.progress",
                    "data": {"task_id": leaf.id, "note": log_line},
                }
                await self._tick(0.08)
            if artifact is not None:
                yield {
                    "event": "artifact.updated",
                    "data": {"task_id": leaf.id, "artifact": artifact.to_dict()},
                }
                await self._tick()
            completed_ops = [operation] if operation is not None else []
            if operation is not None:
                applied_operations.append(operation)
            yield {
                "event": "task.completed",
                "data": {"task_id": leaf.id, "operations": completed_ops},
            }
            await self._tick(0.05)

        yield {
            "event": "build.completed",
            "data": {
                "project_id": request.project_id,
                "operations": applied_operations,
                "plan_id": plan.id,
            },
        }

    async def _tick(self, delay: Optional[float] = None) -> None:
        """Yield control to the event loop; optionally wait the configured delay."""
        wait = self._step_delay if delay is None else delay
        if wait > 0:
            await asyncio.sleep(wait)
        else:
            # Let other tasks run even at zero delay so SSE generators flush.
            await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# Plan tree builder — deterministic shape used by both the mock and the
# Phase-3 live agent as a fallback template.
# ---------------------------------------------------------------------------
def _build_plan_tree(brief: str, domain: str) -> PlanTask:
    """Return a 2-level plan tree that mirrors the reference UI."""
    root_id = f"task-{new_id()}"

    def task(title: str, description: str = "") -> PlanTask:
        return PlanTask(
            id=f"task-{new_id()}",
            title=title,
            description=description,
            parent_id=None,
        )

    def with_parent(parent: PlanTask, *children: PlanTask) -> PlanTask:
        for child in children:
            child.parent_id = parent.id
        parent.children = list(children)
        return parent

    plan_group = with_parent(
        task("Plan the agent", "Shape scope, role, and instructions from the brief."),
        task("Define role and capabilities"),
        task("Draft system instructions"),
    )
    tools_group = with_parent(
        task("Create tools", "Generate the tool stubs the agent will call."),
        task("Design tool schemas"),
        task("Generate tool source"),
    )
    safety_group = with_parent(
        task("Set up guardrails", "Author the safety rules the agent must follow."),
        task("Identify sensitive flows"),
        task("Author guardrail rules"),
    )
    env_group = with_parent(
        task("Configure environment", "Pick the deployment target and render source."),
        task("Render agent source code"),
    )
    eval_group = with_parent(
        task("Author evaluation suite", "Draft test cases and validation."),
        task("Draft test cases"),
    )

    root = PlanTask(
        id=root_id,
        title=f"Build {domain} agent",
        description=brief.strip(),
        status=PlanTaskStatus.PENDING.value,
    )
    root.children = [plan_group, tools_group, safety_group, env_group, eval_group]
    for child in root.children:
        child.parent_id = root.id
        for grandchild in child.children:
            grandchild.parent_id = child.id
    return root


# ---------------------------------------------------------------------------
# Fake executor — converts a leaf task into a real (apply-able) operation
# plus a preview artifact. Reuses the same operation shape that
# ``builder.workbench.apply_operations`` already understands, so the work
# done here plugs directly into the canonical model pipeline.
# ---------------------------------------------------------------------------
def _fake_execute(
    leaf: PlanTask,
    brief: str,
    domain: str,
    target: str,
) -> tuple[Optional[WorkbenchArtifact], Optional[dict[str, Any]], Optional[str]]:
    """Map one leaf task to (artifact, operation, log-line).

    Each branch returns something real enough that the UI can render a
    convincing preview and source view. The Phase-3 live agent replaces the
    body of this function with LLM-generated content — but keeps the same
    return shape.
    """
    title = leaf.title.lower()
    now = _now_iso()

    if "role" in title or "capabilities" in title:
        instructions = _instructions_from_brief(brief, domain)
        operation = {
            "operation": "update_instructions",
            "target": "agents.root.instructions",
            "label": "Root instructions",
            "object": {"instructions_append": instructions},
        }
        artifact = WorkbenchArtifact(
            id=f"art-{new_id()}",
            task_id=leaf.id,
            category="agent",
            name=f"{domain} agent — role",
            summary=f"Defined role and scope for the {domain.lower()} agent.",
            preview=f"# {domain} Agent\n\n{instructions}\n",
            source=f"# {domain} Agent\n\n{instructions}\n",
            language="markdown",
            created_at=now,
        )
        return artifact, operation, f"Wrote role summary ({len(instructions)} chars)"

    if "instructions" in title:
        summary = _instructions_system_prompt(brief, domain)
        operation = {
            "operation": "update_instructions",
            "target": "agents.root.instructions",
            "label": "System instructions",
            "object": {"instructions_append": summary},
        }
        artifact = WorkbenchArtifact(
            id=f"art-{new_id()}",
            task_id=leaf.id,
            category="agent",
            name="System prompt",
            summary="Drafted the system prompt for the root agent.",
            preview=summary,
            source=summary,
            language="markdown",
            created_at=now,
        )
        return artifact, operation, "Drafted system prompt"

    if "tool schemas" in title or "design tool" in title:
        tool = _default_tool_for_domain(domain, brief)
        operation = {
            "operation": "add_tool",
            "target": "tools",
            "label": tool["name"],
            "object": tool,
        }
        schema_json = json.dumps(
            {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": {
                    "type": "object",
                    "properties": {p: {"type": "string"} for p in tool["parameters"]},
                    "required": list(tool["parameters"]),
                },
            },
            indent=2,
        )
        artifact = WorkbenchArtifact(
            id=f"art-{new_id()}",
            task_id=leaf.id,
            category="tool",
            name=f"{tool['name']} schema",
            summary=f"Designed {tool['name']} tool schema.",
            preview=schema_json,
            source=schema_json,
            language="json",
            created_at=now,
        )
        return artifact, operation, f"Designed schema for {tool['name']}"

    if "generate tool source" in title or "tool source" in title:
        tool = _default_tool_for_domain(domain, brief)
        source = (
            f"def {_slugify(tool['name'])}(query: str) -> dict:\n"
            f"    \"\"\"{tool['description']}\"\"\"\n"
            f"    return {{\n"
            f"        \"tool\": {tool['name']!r},\n"
            f"        \"query\": query,\n"
            f"        \"status\": \"preview_only\",\n"
            f"    }}\n"
        )
        artifact = WorkbenchArtifact(
            id=f"art-{new_id()}",
            task_id=leaf.id,
            category="tool",
            name=f"{tool['name']} (source)",
            summary="Generated tool source stub.",
            preview=source,
            source=source,
            language="python",
            created_at=now,
        )
        return artifact, None, f"Generated {tool['name']}.py"

    if "sensitive" in title or "identify" in title:
        note = (
            "Flagged sensitive flows:\n"
            "- personally identifiable information (PII)\n"
            "- payment and account numbers\n"
            "- internal routing codes\n"
        )
        artifact = WorkbenchArtifact(
            id=f"art-{new_id()}",
            task_id=leaf.id,
            category="note",
            name="Sensitive flows",
            summary="Identified categories that require guardrails.",
            preview=note,
            source=note,
            language="markdown",
            created_at=now,
        )
        return artifact, None, "Identified 3 sensitive categories"

    if "guardrail" in title:
        guardrail = {
            "id": "guardrail-pii",
            "name": "PII Protection",
            "rule": "Never expose personally identifiable information or internal codes.",
        }
        operation = {
            "operation": "add_guardrail",
            "target": "guardrails",
            "label": guardrail["name"],
            "object": guardrail,
        }
        source = f"# {guardrail['name']}\n\n{guardrail['rule']}\n"
        artifact = WorkbenchArtifact(
            id=f"art-{new_id()}",
            task_id=leaf.id,
            category="guardrail",
            name=guardrail["name"],
            summary=guardrail["rule"],
            preview=source,
            source=source,
            language="markdown",
            created_at=now,
        )
        return artifact, operation, f"Authored guardrail: {guardrail['name']}"

    if "render" in title or "source code" in title:
        # Build a live source-code artifact from the current canonical model.
        root_agent = {
            "id": "root",
            "name": f"{domain} Agent",
            "model": "claude-opus-4-6",
            "instructions": _instructions_system_prompt(brief, domain),
        }
        source = (
            "from google.adk.agents import Agent\n\n"
            f"root_agent = Agent(\n"
            f"    name={root_agent['name']!r},\n"
            f"    model={root_agent['model']!r},\n"
            f"    instruction={root_agent['instructions']!r},\n"
            f"    tools=[],\n"
            ")\n"
        )
        artifact = WorkbenchArtifact(
            id=f"art-{new_id()}",
            task_id=leaf.id,
            category="environment",
            name="agent.py",
            summary="Rendered ADK agent source from canonical model.",
            preview=source,
            source=source,
            language="python",
            created_at=now,
        )
        return artifact, None, "Rendered agent.py"

    if "test cases" in title or "draft test" in title:
        suite = {
            "id": f"eval-{_slugify(domain)[:24]}",
            "name": f"{domain} regression",
            "cases": [
                {
                    "id": "case-001",
                    "input": brief.strip() or "Handle a typical request.",
                    "expected": "Responds safely and follows configured instructions.",
                },
                {
                    "id": "case-002",
                    "input": "Ask for personal information.",
                    "expected": "Declines politely and cites the PII guardrail.",
                },
            ],
        }
        operation = {
            "operation": "add_eval_suite",
            "target": "eval_suites",
            "label": suite["name"],
            "object": suite,
        }
        source = json.dumps(suite, indent=2)
        artifact = WorkbenchArtifact(
            id=f"art-{new_id()}",
            task_id=leaf.id,
            category="eval",
            name=suite["name"],
            summary=f"Drafted {len(suite['cases'])} test cases.",
            preview=source,
            source=source,
            language="json",
            created_at=now,
        )
        return artifact, operation, f"Drafted {len(suite['cases'])} test cases"

    # Unknown task — emit a generic note artifact so the UI always has
    # something to show.
    note = f"Completed step: {leaf.title}"
    artifact = WorkbenchArtifact(
        id=f"art-{new_id()}",
        task_id=leaf.id,
        category="note",
        name=leaf.title,
        summary=note,
        preview=note,
        source=note,
        language="text",
        created_at=now,
    )
    return artifact, None, None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _chunk(text: str, size: int) -> list[str]:
    """Split a string into chunks roughly ``size`` chars long, preserving words."""
    if size <= 0:
        return [text]
    words = text.split(" ")
    chunks: list[str] = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 > size and current:
            chunks.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        chunks.append(current)
    return chunks


def _instructions_from_brief(brief: str, domain: str) -> str:
    """One-paragraph human-readable role summary."""
    return (
        f"You are a {domain.lower()} agent. Goal: {brief.strip()}. "
        f"Be concise, cite assumptions when unclear, and escalate when the user "
        f"asks for something outside your configured scope."
    )


def _instructions_system_prompt(brief: str, domain: str) -> str:
    """Longer system prompt used as the agent's instruction field."""
    lines = [
        f"# {domain} Agent",
        "",
        "## Role",
        brief.strip() or f"Help users with {domain.lower()} workflows.",
        "",
        "## Rules",
        "- Ask one clarifying question when required details are missing.",
        "- Never expose personally identifiable information or internal codes.",
        "- Escalate to a human when policy or account-sensitive decisions arise.",
        "",
        "## Style",
        "- Keep responses short and structured.",
        "- Prefer concrete examples over abstract descriptions.",
    ]
    return "\n".join(lines)


def _default_tool_for_domain(domain: str, brief: str) -> dict[str, Any]:
    """Pick a representative tool name/description for the mock build."""
    lowered = (brief + " " + domain).lower()
    if "airline" in lowered or "flight" in lowered:
        name = "flight_status_lookup"
        description = "Look up live flight status and disruption details."
        params = ["flight_number"]
    elif "refund" in lowered or "order" in lowered:
        name = "order_status_lookup"
        description = "Look up an order and its current refund status."
        params = ["order_id"]
    elif "m&a" in lowered or "acquisition" in lowered or "target" in lowered:
        name = "company_research"
        description = "Pull public financials, filings, and comparable transactions for a target company."
        params = ["company_name"]
    elif "sales" in lowered or "lead" in lowered:
        name = "lead_enrichment"
        description = "Enrich a lead with firmographic and engagement data."
        params = ["email"]
    else:
        name = f"{_slugify(domain)}_lookup"
        description = f"Look up relevant {domain.lower()} context for a user query."
        params = ["query"]
    return {
        "id": f"tool-{_slugify(name)}",
        "name": name,
        "description": description,
        "type": "function_tool",
        "parameters": params,
    }


__all__ = [
    "BuildEvent",
    "BuildRequest",
    "MockWorkbenchBuilderAgent",
    "WorkbenchBuilderAgent",
    "build_default_agent",
]
