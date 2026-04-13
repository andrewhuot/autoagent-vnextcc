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
from dataclasses import dataclass, field
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
from builder.workbench_prompts import (
    EXECUTOR_SCHEMAS,
    EXECUTOR_SYSTEM_PROMPT,
    PLANNER_SYSTEM_PROMPT,
    executor_user_prompt,
    planner_user_prompt,
)


BuildEvent = dict[str, Any]


# ---------------------------------------------------------------------------
# Request shape
# ---------------------------------------------------------------------------
@dataclass
class BuildRequest:
    """One end-to-end build request sourced from the Workbench UI.

    Multi-turn fields:
        mode                   — ``"initial"`` for the first turn,
                                 ``"follow_up"`` for subsequent user turns,
                                 or ``"correction"`` when the autonomous
                                 loop is making a self-directed fix.
        conversation_history   — Compact (role, content) pairs of prior
                                 messages so the planner can reason about
                                 the running dialogue.
        prior_turn_summary     — Lightweight summaries of prior turns so
                                 planner prompts don't have to ingest the
                                 full plan tree or artifact blobs.
        current_model_summary  — Condensed canonical-model snapshot so the
                                 planner can ask for deltas (add one tool)
                                 instead of rebuilding everything.
    """

    project_id: str
    brief: str
    target: str = "portable"
    environment: str = "draft"
    mode: str = "initial"
    conversation_history: list[dict[str, Any]] = field(default_factory=list)
    prior_turn_summary: list[dict[str, Any]] = field(default_factory=list)
    current_model_summary: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Factory — picks live vs. mock based on env / router capability
# ---------------------------------------------------------------------------
def build_default_agent(*, force_mock: bool = False) -> "WorkbenchBuilderAgent":
    """Return a live or mock builder agent depending on runtime capability.

    Live mode is only selected when all of the following hold:
      1. ``force_mock`` is False
      2. A runtime config + LLMRouter can be constructed
      3. That router is NOT itself in mock mode (real provider keys present)

    On any failure we fall back to the mock agent so the UI always has
    something coherent to render.
    """
    agent, _metadata = build_default_agent_with_readiness(force_mock=force_mock)
    return agent


def build_default_agent_with_readiness(
    *,
    force_mock: bool = False,
) -> tuple["WorkbenchBuilderAgent", dict[str, Any]]:
    """Return the selected builder agent and operator-visible mode metadata.

    WHY: staging operators need to know whether a Workbench run used a real
    provider or deterministic mock output. The legacy factory intentionally
    fell back to mock mode to keep the UI usable; this companion keeps that
    behavior while making the selected mode explicit and durable.
    """
    if force_mock:
        return MockWorkbenchBuilderAgent(), {
            "mode": "mock",
            "provider": "mock",
            "model": "mock-workbench",
            "mock_reason": "Mock mode forced by request.",
            "requested_mock": True,
            "live_ready": False,
        }
    try:
        from cli.mode import load_runtime_with_builder_live_preference
        from optimizer.providers import build_router_from_runtime_config

        runtime = load_runtime_with_builder_live_preference()
        router = build_router_from_runtime_config(runtime.optimizer)
        model = router.models[0] if getattr(router, "models", None) else None
        provider_name = str(getattr(model, "provider", "mock"))
        model_name = str(getattr(model, "model", "mock-workbench"))
        if router.mock_mode:
            return MockWorkbenchBuilderAgent(), {
                "mode": "mock",
                "provider": provider_name or "mock",
                "model": model_name or "mock-workbench",
                "mock_reason": getattr(router, "mock_reason", "") or "Provider router selected mock mode.",
                "requested_mock": bool(getattr(router, "requested_mock", False)),
                "live_ready": False,
                "skipped_models": list(getattr(router, "skipped_models", []) or []),
            }
        return LiveWorkbenchBuilderAgent(router=router), {
            "mode": "live",
            "provider": provider_name,
            "model": model_name,
            "mock_reason": "",
            "requested_mock": False,
            "live_ready": True,
            "skipped_models": list(getattr(router, "skipped_models", []) or []),
        }
    except Exception as exc:  # noqa: BLE001 — any failure downgrades to mock
        return MockWorkbenchBuilderAgent(), {
            "mode": "mock",
            "provider": "mock",
            "model": "mock-workbench",
            "mock_reason": f"Workbench live provider setup failed; falling back to mock mode: {exc}",
            "requested_mock": False,
            "live_ready": False,
        }


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

        # Follow-up / correction turns emit a smaller delta plan tree so the
        # UI shows a focused change set on top of the existing build instead
        # of rebuilding from scratch.
        if request.mode in {"follow_up", "correction"}:
            plan = _build_follow_up_plan_tree(
                brief=brief,
                domain=domain,
                model_summary=request.current_model_summary,
                mode=request.mode,
            )
        else:
            plan = _build_plan_tree(brief, domain)

        yield {"event": "plan.ready", "data": {"plan": plan.to_dict()}}
        await self._tick()

        root_id = plan.id
        if request.mode == "follow_up":
            welcome = (
                f"Got it — I'll apply your follow-up delta to the existing "
                f"{domain} agent and surface any affected artifacts."
            )
        elif request.mode == "correction":
            welcome = (
                "Running an autonomous correction pass to resolve the issues "
                "validation flagged last time."
            )
        else:
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

    def task(title: str, description: str = "", *, kind: str | None = None) -> PlanTask:
        t = PlanTask(
            id=f"task-{new_id()}",
            title=title,
            description=description,
            parent_id=None,
        )
        if kind:
            t.log.append(f"kind:{kind}")
        return t

    def with_parent(parent: PlanTask, *children: PlanTask) -> PlanTask:
        for child in children:
            child.parent_id = parent.id
        parent.children = list(children)
        return parent

    plan_group = with_parent(
        task("Plan the agent", "Shape scope, role, and instructions from the brief."),
        task("Define role and capabilities", kind="role"),
        task("Draft system instructions", kind="instructions"),
    )
    tools_group = with_parent(
        task("Create tools", "Generate the tool stubs the agent will call."),
        task("Design tool schemas", kind="tool_schema"),
        task("Generate tool source", kind="tool_source"),
    )
    safety_group = with_parent(
        task("Set up guardrails", "Author the safety rules the agent must follow."),
        task("Identify sensitive flows"),
        task("Author guardrail rules", kind="guardrail"),
    )
    env_group = with_parent(
        task("Configure environment", "Pick the deployment target and render source."),
        task("Render agent source code", kind="environment"),
    )
    eval_group = with_parent(
        task("Author evaluation suite", "Draft test cases and validation."),
        task("Draft test cases", kind="eval_suite"),
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


def _build_follow_up_plan_tree(
    *,
    brief: str,
    domain: str,
    model_summary: dict[str, Any] | None,
    mode: str,
) -> PlanTask:
    """Return a minimal delta plan tree for follow-up or correction turns.

    WHY: Multi-turn autonomy should feel like Claude Code — each follow-up
    message produces a focused delta, not a full rebuild. Correction passes
    do the same but with an autonomous framing so the UI can surface "the
    agent fixed itself" feedback.
    """
    lowered = brief.lower()
    model_summary = model_summary or {}
    root_title = (
        "Autonomous correction"
        if mode == "correction"
        else f"Apply follow-up to {domain} agent"
    )
    root = PlanTask(
        id=f"task-{new_id()}",
        title=root_title,
        description=brief.strip()[:240],
        status=PlanTaskStatus.PENDING.value,
    )

    def leaf(title: str, description: str = "") -> PlanTask:
        return PlanTask(
            id=f"task-{new_id()}",
            title=title,
            description=description,
            parent_id=root.id,
            status=PlanTaskStatus.PENDING.value,
        )

    leaves: list[PlanTask] = []

    # Heuristic routing: decide which change(s) the delta should apply based
    # on the user's text. This keeps the mock agent's output realistic for
    # tests and no-key demos.
    want_guardrail = (
        "guardrail" in lowered
        or "policy" in lowered
        or "never" in lowered
        or "pii" in lowered
        or mode == "correction"
    )
    want_tool = (
        "tool" in lowered
        or "lookup" in lowered
        or "integration" in lowered
    )
    want_eval = "eval" in lowered or "regression" in lowered or "test case" in lowered
    want_instructions = (
        "instruction" in lowered
        or "tone" in lowered
        or "persona" in lowered
        or "style" in lowered
    )

    if not any([want_guardrail, want_tool, want_eval, want_instructions]):
        # Default to an instructions refinement so at least one artifact is
        # always produced on a follow-up turn.
        want_instructions = True

    if want_instructions:
        leaves.append(leaf("Draft system instructions", "Refine the root system prompt."))
    if want_tool:
        leaves.append(leaf("Design tool schemas", "Design the new tool the user requested."))
        leaves.append(leaf("Generate tool source", "Emit a stub for the new tool."))
    if want_guardrail:
        leaves.append(leaf("Author guardrail rules", "Add the safety rule the user asked for."))
    if want_eval:
        leaves.append(leaf("Draft test cases", "Append a regression case for the new behaviour."))

    root.children = leaves
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
        agent_label = _agent_label(domain)
        artifact = WorkbenchArtifact(
            id=f"art-{new_id()}",
            task_id=leaf.id,
            category="agent",
            name=f"{agent_label} — role",
            summary=f"Defined role and scope for the {agent_label.lower()}.",
            preview=f"# {agent_label}\n\n{instructions}\n",
            source=f"# {agent_label}\n\n{instructions}\n",
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
        agent_label = _agent_label(domain)
        suite = {
            "id": f"eval-{_slugify(domain)[:24]}",
            "name": f"{agent_label} regression",
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


def _agent_label(domain: str) -> str:
    """Render a non-redundant agent label, e.g. "Agent" not "Agent agent"."""
    cleaned = domain.strip() or "Agent"
    if cleaned.lower().endswith("agent"):
        return cleaned
    return f"{cleaned} agent"


def _instructions_from_brief(brief: str, domain: str) -> str:
    """One-paragraph human-readable role summary."""
    label = _agent_label(domain).lower()
    return (
        f"You are a{'n' if label[:1] in 'aeiou' else ''} {label}. "
        f"Goal: {brief.strip()}. "
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


# ---------------------------------------------------------------------------
# Live LLM-driven agent
# ---------------------------------------------------------------------------
class LiveWorkbenchBuilderAgent(WorkbenchBuilderAgent):
    """Real harness-backed builder. Delegates to ``HarnessExecutionEngine``.

    The ``HarnessExecutionEngine`` provides the full plan-execute-reflect-present
    lifecycle. This class is the ``WorkbenchBuilderAgent`` adapter that:

    - Wires the engine with the optional LLM router
    - Tracks version/iteration state across ``iterate()`` calls
    - Falls back to ``MockWorkbenchBuilderAgent`` if the engine raises
      unexpectedly, matching the global graceful-degradation rule

    Both ``run()`` and ``iterate()`` share the same event contract so the
    ``WorkbenchService`` SSE stream is forward-compatible.
    """

    def __init__(
        self,
        *,
        router: Any,
        max_json_retries: int = 2,
        max_tokens_plan: int = 1500,
        max_tokens_task: int = 900,
    ) -> None:
        """Bind an LLMRouter and retry budget."""
        self.router = router
        self.max_json_retries = max_json_retries
        self.max_tokens_plan = max_tokens_plan
        self.max_tokens_task = max_tokens_task
        # Iteration tracking — survives across successive iterate() calls
        self._iteration: int = 1
        self._previous_artifacts: list[dict[str, Any]] = []
        self._previous_plan: Optional[dict[str, Any]] = None

    def _make_engine(self, store: Any = None, event_broker: Any = None) -> Any:
        """Construct a ``HarnessExecutionEngine`` bound to this agent's router."""
        from builder.harness import HarnessExecutionEngine

        _store = store or _NullStore()
        _broker = event_broker or _NullEventBroker()
        return HarnessExecutionEngine(_store, _broker, router=self.router)

    async def run(
        self,
        request: BuildRequest,
        project: dict[str, Any],
    ) -> AsyncIterator[BuildEvent]:
        """Drive a real harness build, yielding the same event shape as the mock.

        Delegates to ``HarnessExecutionEngine.run()``. Falls back to
        ``MockWorkbenchBuilderAgent`` on any unexpected error so the UI always
        receives a coherent event stream.
        """
        try:
            engine = self._make_engine()
            async for event in engine.run(request, project):
                # Track state for subsequent iterate() calls
                if event.get("event") == "artifact.updated":
                    artifact_data = (event.get("data") or {}).get("artifact")
                    if isinstance(artifact_data, dict):
                        self._previous_artifacts.append(artifact_data)
                elif event.get("event") == "plan.ready":
                    self._previous_plan = (event.get("data") or {}).get("plan")
                yield event
            self._iteration = 2  # Next call is an iteration
        except Exception:  # noqa: BLE001 — always degrade gracefully
            async for event in MockWorkbenchBuilderAgent().run(request, project):
                yield event

    async def iterate(
        self,
        request: BuildRequest,
        project: dict[str, Any],
        follow_up: str,
    ) -> AsyncIterator[BuildEvent]:
        """Handle a follow-up iteration refining a previous build.

        Passes the prior plan and artifacts to the engine so it can produce
        delta artifacts rather than rebuilding from scratch.
        """
        try:
            engine = self._make_engine()
            existing_artifacts = list(project.get("artifacts") or self._previous_artifacts)
            existing_plan = project.get("plan") or self._previous_plan
            async for event in engine.iterate(
                request,
                existing_plan=existing_plan,
                existing_artifacts=existing_artifacts,
                follow_up=follow_up,
                iteration_number=self._iteration,
            ):
                if event.get("event") == "artifact.updated":
                    artifact_data = (event.get("data") or {}).get("artifact")
                    if isinstance(artifact_data, dict):
                        self._previous_artifacts.append(artifact_data)
                yield event
            self._iteration += 1
        except Exception:  # noqa: BLE001 — degrade to mock
            async for event in MockWorkbenchBuilderAgent().run(request, project):
                yield event


# ---------------------------------------------------------------------------
# JSON parsing helpers — tolerant to fenced output
# ---------------------------------------------------------------------------
def _parse_json_object(text: str) -> dict[str, Any] | None:
    """Parse a JSON object out of the LLM response, ignoring code fences."""
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        # Strip a leading ```lang line and a trailing ``` line.
        lines = stripped.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    candidate = stripped[start : end + 1]
    try:
        result = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return result if isinstance(result, dict) else None


def _plan_from_llm_payload(
    root_payload: dict[str, Any],
    *,
    brief: str,
    domain: str,
) -> PlanTask | None:
    """Turn a planner JSON payload into a PlanTask tree, if it validates."""
    title = str(root_payload.get("title") or f"Build {domain} agent")
    description = str(root_payload.get("description") or brief.strip())
    try:
        children_payload = list(root_payload.get("children") or [])
    except TypeError:
        return None
    if not children_payload:
        return None

    root = PlanTask(
        id=f"task-{new_id()}",
        title=title[:120],
        description=description[:320],
        status=PlanTaskStatus.PENDING.value,
    )

    def build_node(payload: dict[str, Any], parent_id: str, depth: int) -> PlanTask | None:
        if not isinstance(payload, dict):
            return None
        node_title = str(payload.get("title") or "Task")[:120]
        node_desc = str(payload.get("description") or "")[:320]
        node = PlanTask(
            id=f"task-{new_id()}",
            title=node_title,
            description=node_desc,
            status=PlanTaskStatus.PENDING.value,
            parent_id=parent_id,
        )
        children = payload.get("children")
        if depth < 2 and isinstance(children, list) and children:
            for child_payload in children:
                child = build_node(child_payload, parent_id=node.id, depth=depth + 1)
                if child is not None:
                    node.children.append(child)
            if not node.children:
                return None
        else:
            kind = str(payload.get("kind") or "").strip()
            if kind not in EXECUTOR_SCHEMAS:
                return None
            node.log.append(f"kind:{kind}")
        return node

    for child_payload in children_payload:
        child = build_node(child_payload, parent_id=root.id, depth=1)
        if child is not None:
            root.children.append(child)

    return root if root.children else None


def _infer_kind_from_leaf(leaf: PlanTask) -> str | None:
    """Pull the kind tag out of a leaf's log (set during planner parsing)."""
    for entry in leaf.log or []:
        if entry.startswith("kind:"):
            candidate = entry.split(":", 1)[1]
            if candidate in EXECUTOR_SCHEMAS:
                return candidate
    return None


def _artifact_and_op_from_executor(
    *,
    kind: str,
    payload: dict[str, Any],
    leaf: PlanTask,
    brief: str,
    domain: str,
) -> tuple[WorkbenchArtifact | None, dict[str, Any] | None, str | None] | None:
    """Translate a validated executor payload into an artifact + operation."""
    now = _now_iso()
    artifact_id = f"art-{new_id()}"

    if kind == "role":
        summary = str(payload.get("role_summary") or "").strip()
        if not summary:
            return None
        operation = {
            "operation": "update_instructions",
            "target": "agents.root.instructions",
            "label": "Root role",
            "object": {"instructions_append": summary},
        }
        artifact = WorkbenchArtifact(
            id=artifact_id,
            task_id=leaf.id,
            category="agent",
            name=f"{domain} agent role",
            summary="Role summary from the planner.",
            preview=summary,
            source=summary,
            language="markdown",
            created_at=now,
        )
        return artifact, operation, "Wrote role summary"

    if kind == "instructions":
        prompt_text = str(payload.get("system_prompt") or "").strip()
        if not prompt_text:
            return None
        operation = {
            "operation": "update_instructions",
            "target": "agents.root.instructions",
            "label": "System instructions",
            "object": {"instructions_append": prompt_text},
        }
        artifact = WorkbenchArtifact(
            id=artifact_id,
            task_id=leaf.id,
            category="agent",
            name="System prompt",
            summary="Drafted system prompt.",
            preview=prompt_text,
            source=prompt_text,
            language="markdown",
            created_at=now,
        )
        return artifact, operation, "Drafted system prompt"

    if kind == "tool_schema":
        name = str(payload.get("name") or "").strip()
        description = str(payload.get("description") or "").strip()
        raw_params = payload.get("parameters") or []
        if isinstance(raw_params, str):
            params = [raw_params]
        else:
            params = [str(p) for p in raw_params][:8]
        if not name:
            return None
        tool = {
            "id": f"tool-{_slugify(name)}",
            "name": _slugify(name),
            "description": description,
            "type": "function_tool",
            "parameters": params or ["query"],
        }
        operation = {
            "operation": "add_tool",
            "target": "tools",
            "label": tool["name"],
            "object": tool,
        }
        schema_blob = json.dumps(
            {
                "name": tool["name"],
                "description": description,
                "parameters": tool["parameters"],
            },
            indent=2,
        )
        artifact = WorkbenchArtifact(
            id=artifact_id,
            task_id=leaf.id,
            category="tool",
            name=f"{tool['name']} schema",
            summary=description or f"Tool schema for {tool['name']}.",
            preview=schema_blob,
            source=schema_blob,
            language="json",
            created_at=now,
        )
        return artifact, operation, f"Designed schema for {tool['name']}"

    if kind == "tool_source":
        name = str(payload.get("name") or "").strip()
        source = str(payload.get("source") or "").strip()
        if not name or not source:
            return None
        artifact = WorkbenchArtifact(
            id=artifact_id,
            task_id=leaf.id,
            category="tool",
            name=f"{_slugify(name)}.py",
            summary=f"Generated source for {name}.",
            preview=source,
            source=source,
            language="python",
            created_at=now,
        )
        return artifact, None, f"Generated {_slugify(name)}.py"

    if kind == "guardrail":
        name = str(payload.get("name") or "").strip()
        rule = str(payload.get("rule") or "").strip()
        if not name or not rule:
            return None
        guardrail = {
            "id": f"guardrail-{_slugify(name)}",
            "name": name,
            "rule": rule,
        }
        operation = {
            "operation": "add_guardrail",
            "target": "guardrails",
            "label": name,
            "object": guardrail,
        }
        source = f"# {name}\n\n{rule}\n"
        artifact = WorkbenchArtifact(
            id=artifact_id,
            task_id=leaf.id,
            category="guardrail",
            name=name,
            summary=rule,
            preview=source,
            source=source,
            language="markdown",
            created_at=now,
        )
        return artifact, operation, f"Authored guardrail: {name}"

    if kind == "environment":
        filename = str(payload.get("filename") or "agent.py").strip()
        source = str(payload.get("source") or "").strip()
        if not source:
            return None
        artifact = WorkbenchArtifact(
            id=artifact_id,
            task_id=leaf.id,
            category="environment",
            name=filename,
            summary="Rendered ADK agent source.",
            preview=source,
            source=source,
            language="python",
            created_at=now,
        )
        return artifact, None, f"Rendered {filename}"

    if kind == "eval_suite":
        name = str(payload.get("name") or "").strip()
        cases_payload = payload.get("cases") or []
        if not name or not isinstance(cases_payload, list) or not cases_payload:
            return None
        cases = []
        for index, raw_case in enumerate(cases_payload[:5]):
            if not isinstance(raw_case, dict):
                continue
            cases.append(
                {
                    "id": f"case-{index + 1:03d}",
                    "input": str(raw_case.get("input") or ""),
                    "expected": str(raw_case.get("expected") or ""),
                }
            )
        if not cases:
            return None
        suite = {
            "id": f"eval-{_slugify(name)[:24]}",
            "name": name,
            "cases": cases,
        }
        operation = {
            "operation": "add_eval_suite",
            "target": "eval_suites",
            "label": name,
            "object": suite,
        }
        source = json.dumps(suite, indent=2)
        artifact = WorkbenchArtifact(
            id=artifact_id,
            task_id=leaf.id,
            category="eval",
            name=name,
            summary=f"{len(cases)} test case(s) drafted.",
            preview=source,
            source=source,
            language="json",
            created_at=now,
        )
        return artifact, operation, f"Drafted {len(cases)} test cases"

    return None


def _apply_operation_in_place(model: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    """Lightweight in-process apply so subsequent task prompts see fresh state.

    Real persistence happens in WorkbenchService.run_build_stream via the
    canonical ``apply_operations`` helper — this one just keeps a working copy
    in sync inside the agent.
    """
    from builder.workbench import apply_operations

    return apply_operations(model, [operation])


def _default_intro(domain: str, plan: PlanTask) -> str:
    """Generate a fallback assistant intro when the LLM forgets to."""
    leaf_titles = [leaf.title for leaf in walk_leaves(plan)][:3]
    joined = ", ".join(leaf_titles) if leaf_titles else "the required steps"
    return (
        f"Here's the plan for your {domain} agent. I'll start with {joined} "
        f"and render each artifact on the right as I go."
    )


class _NullStore:
    """No-op store used when no persistent store is available."""

    def save_project(self, project: dict[str, Any]) -> None:
        """Accept but discard a project save request."""


class _NullEventBroker:
    """No-op event broker used when no real broker is available."""

    def publish(self, *args: Any, **kwargs: Any) -> None:
        """Accept but discard a publish request."""


__all__ = [
    "BuildEvent",
    "BuildRequest",
    "LiveWorkbenchBuilderAgent",
    "MockWorkbenchBuilderAgent",
    "WorkbenchBuilderAgent",
    "build_default_agent",
]
