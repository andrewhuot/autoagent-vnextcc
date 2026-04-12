"""Canonical Agent Builder Workbench model, planner, compiler, and store."""

from __future__ import annotations

import copy
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from builder.types import new_id


WorkbenchTarget = str

RUN_STATUS_QUEUED = "queued"
RUN_STATUS_RUNNING = "running"
RUN_STATUS_REFLECTING = "reflecting"
RUN_STATUS_PRESENTING = "presenting"
RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_FAILED = "failed"
RUN_STATUS_CANCELLED = "cancelled"

ACTIVE_RUN_STATUSES = {
    RUN_STATUS_QUEUED,
    RUN_STATUS_RUNNING,
    RUN_STATUS_REFLECTING,
    RUN_STATUS_PRESENTING,
}
TERMINAL_RUN_STATUSES = {
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_CANCELLED,
}

PHASE_QUEUED = "queued"
PHASE_PLANNING = "planning"
PHASE_EXECUTING = "executing"
PHASE_REFLECTING = "reflecting"
PHASE_PRESENTING = "presenting"
PHASE_TERMINAL = "terminal"

TOKEN_COST_ESTIMATE_USD = 0.000003
DEFAULT_STALE_RUN_SECONDS = 30 * 60


def _now_iso() -> str:
    """Return a stable UTC timestamp for version and activity records."""
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any) -> datetime | None:
    """Parse a stored UTC timestamp, returning None for old/malformed values."""
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _elapsed_ms_since(value: Any) -> int:
    """Return elapsed milliseconds since a stored timestamp."""
    started = _parse_iso(value)
    if started is None:
        return 0
    return max(0, round((datetime.now(tz=timezone.utc) - started).total_seconds() * 1000))


def _positive_int(value: int | None) -> int | None:
    """Normalize optional positive integer limits."""
    if value is None:
        return None
    value = int(value)
    return value if value > 0 else None


def _positive_float(value: float | None) -> float | None:
    """Normalize optional positive float limits."""
    if value is None:
        return None
    value = float(value)
    return value if value > 0 else None


def _int_or_zero(value: Any) -> int:
    """Coerce model-supplied count fields without letting bad metrics crash."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _normalize_budget(
    *,
    max_iterations: int = 3,
    max_seconds: int | None = None,
    max_tokens: int | None = None,
    max_cost_usd: float | None = None,
) -> dict[str, Any]:
    """Build the persisted budget object for a Workbench run.

    WHY: budget state must be server-authoritative and survive page refreshes.
    The limits are optional except iterations, while usage is always present so
    API clients and operators can render honest progress.
    """
    return {
        "limits": {
            "max_iterations": max(1, int(max_iterations or 1)),
            "max_seconds": _positive_int(max_seconds),
            "max_tokens": _positive_int(max_tokens),
            "max_cost_usd": _positive_float(max_cost_usd),
        },
        "usage": {
            "iterations": 0,
            "elapsed_ms": 0,
            "tokens": 0,
            "tokens_used": 0,
            "cost_usd": 0.0,
        },
        "breach": None,
    }


def _budget_usage(budget: dict[str, Any]) -> dict[str, Any]:
    """Return a mutable usage map from a persisted budget."""
    usage = budget.setdefault("usage", {})
    usage.setdefault("iterations", 0)
    usage.setdefault("elapsed_ms", 0)
    usage.setdefault("tokens", usage.get("tokens_used", 0))
    usage.setdefault("tokens_used", 0)
    usage.setdefault("cost_usd", 0.0)
    return usage


def _phase_to_status(phase: str) -> str:
    """Map lifecycle phase to the run status used by active snapshots."""
    if phase == PHASE_REFLECTING:
        return RUN_STATUS_REFLECTING
    if phase == PHASE_PRESENTING:
        return RUN_STATUS_PRESENTING
    if phase == PHASE_TERMINAL:
        return RUN_STATUS_COMPLETED
    if phase == PHASE_QUEUED:
        return RUN_STATUS_QUEUED
    return RUN_STATUS_RUNNING


def _estimate_tokens_for_event(event_name: str, data: dict[str, Any]) -> int:
    """Cheaply estimate tokens represented by one streamed event payload."""
    if event_name == "harness.metrics":
        return 0
    if event_name == "message.delta":
        return max(1, len(str(data.get("text") or "")) // 4)
    if event_name == "artifact.updated":
        artifact = data.get("artifact") if isinstance(data.get("artifact"), dict) else {}
        text = "\n".join(
            str(artifact.get(key) or "")
            for key in ("summary", "preview", "source")
        )
        return max(1, len(text) // 4)
    if event_name == "plan.ready":
        # Plans are deterministic Workbench structure, not provider output.
        # Keep budget enforcement anchored to provider deltas and harness metrics.
        return 0
    return 0


def _iter_plan_nodes(plan: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Flatten a persisted plan tree for compact progress summaries."""
    if not isinstance(plan, dict):
        return []
    nodes: list[dict[str, Any]] = []

    def visit(node: dict[str, Any]) -> None:
        nodes.append(node)
        for child in node.get("children") or []:
            if isinstance(child, dict):
                visit(child)

    visit(plan)
    return nodes


def _plan_progress_summary(
    plan: dict[str, Any] | None,
    *,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return operator-facing progress without requiring full plan context."""
    nodes = _iter_plan_nodes(plan)
    leaves = [node for node in nodes if not node.get("children")]
    if leaves:
        completed = sum(1 for node in leaves if str(node.get("status") or "") in {"done", "completed"})
        running = sum(1 for node in leaves if str(node.get("status") or "") == "running")
        blocked = sum(1 for node in leaves if str(node.get("status") or "") in {"error", "failed", "blocked"})
        current = next(
            (
                node
                for node in leaves
                if str(node.get("status") or "") in {"running", "pending", "error", "failed", "blocked"}
            ),
            None,
        )
        return {
            "total_tasks": len(leaves),
            "completed_tasks": completed,
            "running_tasks": running,
            "blocked_tasks": blocked,
            "current_task": _task_progress_summary(current),
        }

    metrics = metrics if isinstance(metrics, dict) else {}
    total_steps = _int_or_zero(metrics.get("total_steps") or metrics.get("steps_total"))
    completed_steps = _int_or_zero(metrics.get("steps_completed"))
    return {
        "total_tasks": total_steps,
        "completed_tasks": min(completed_steps, total_steps) if total_steps else completed_steps,
        "running_tasks": 1 if total_steps and completed_steps < total_steps else 0,
        "blocked_tasks": 0,
        "current_task": None,
    }


def _task_progress_summary(task: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the small task subset that is safe to repeat in handoff state."""
    if not isinstance(task, dict):
        return None
    return {
        "task_id": task.get("id") or task.get("task_id"),
        "title": task.get("title"),
        "status": task.get("status"),
    }


def _verification_summary(validation: dict[str, Any] | None) -> dict[str, Any]:
    """Summarize validation so recovery views can tell if proof ran."""
    if not isinstance(validation, dict):
        return {
            "status": "not_run",
            "passed_checks": 0,
            "total_checks": 0,
            "blocking": True,
        }
    checks = [check for check in validation.get("checks", []) if isinstance(check, dict)]
    passed = sum(1 for check in checks if check.get("passed") is True)
    status = str(validation.get("status") or "unknown")
    return {
        "status": status,
        "passed_checks": passed,
        "total_checks": len(checks),
        "blocking": status != "passed",
    }


def _latest_artifact_summary(project: dict[str, Any]) -> dict[str, Any] | None:
    """Return a compact pointer to the newest generated artifact."""
    artifacts = [item for item in project.get("artifacts", []) if isinstance(item, dict)]
    if not artifacts:
        return None
    artifact = artifacts[-1]
    return {
        "artifact_id": artifact.get("id"),
        "task_id": artifact.get("task_id"),
        "name": artifact.get("name"),
        "category": artifact.get("category"),
        "summary": artifact.get("summary"),
    }


def _last_event_summary(event: dict[str, Any] | None) -> dict[str, Any] | None:
    """Expose the last replayable event without copying nested payloads."""
    if not isinstance(event, dict):
        return None
    return {
        "sequence": event.get("sequence"),
        "event": event.get("event"),
        "phase": event.get("phase"),
        "status": event.get("status"),
        "created_at": event.get("created_at"),
    }


def _default_execution_metadata() -> dict[str, Any]:
    """Return conservative mock execution metadata for direct service tests."""
    return {
        "mode": "mock",
        "provider": "mock",
        "model": "mock-workbench",
        "mock_reason": "Execution metadata was not supplied by the API route.",
        "requested_mock": False,
        "live_ready": False,
    }


def _slugify(value: str, fallback: str = "item") -> str:
    """Create stable object IDs from user-facing names."""
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or fallback


def _title_from_slug(value: str) -> str:
    """Make generated names readable in the Workbench UI."""
    return " ".join(part.capitalize() for part in value.replace("_", " ").split())


def _dedupe_by_id(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep canonical collections stable when repeated plans add the same object."""
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        item_id = str(item.get("id") or "")
        if item_id in seen:
            continue
        seen.add(item_id)
        deduped.append(item)
    return deduped


def _infer_domain(brief: str) -> str:
    """Infer a short domain label from a plain-English brief."""
    lowered = brief.lower()
    if "airline" in lowered or "flight" in lowered or "booking" in lowered:
        return "Airline Support"
    if "refund" in lowered or "order" in lowered:
        return "Refund Support"
    if "sales" in lowered or "qualification" in lowered or "lead" in lowered:
        return "Sales Qualification"
    if "health" in lowered or "intake" in lowered:
        return "Healthcare Intake"
    if "it " in lowered or "vpn" in lowered or "password" in lowered:
        return "IT Helpdesk"
    if (
        "m&a" in lowered
        or "acquisition" in lowered
        or "merger" in lowered
        or "deal memo" in lowered
        or "investment" in lowered
    ):
        return "M&A Analyst"
    return "Agent"


def _default_model(brief: str, *, target: WorkbenchTarget, environment: str) -> dict[str, Any]:
    """Build the initial canonical model from a plain-English brief.

    WHY: The Workbench always edits this structured object first; generated ADK
    and CX artifacts are downstream compiler output, never the source of truth.
    """
    domain = _infer_domain(brief)
    agent_name = f"{domain} Agent" if not domain.endswith("Agent") else domain
    return {
        "project": {
            "name": f"{domain} Workbench",
            "description": brief.strip() or "New agent workbench project.",
        },
        "agents": [
            {
                "id": "root",
                "name": agent_name,
                "role": f"Handle {domain.lower()} conversations safely and clearly.",
                "model": "gpt-5.4-mini",
                "instructions": (
                    f"{brief.strip() or 'Help the user with the requested workflow.'}\n\n"
                    "Ask one clarifying question when required details are missing. "
                    "Escalate when safety, policy, or account-sensitive decisions require review."
                ),
                "sub_agents": [],
            }
        ],
        "tools": [],
        "callbacks": [],
        "guardrails": [],
        "eval_suites": [],
        "environments": [
            {
                "id": environment,
                "name": _title_from_slug(environment),
                "target": target,
            }
        ],
        "deployments": [],
    }


def _operation_label(operation: dict[str, Any]) -> str:
    """Return a readable label for activity and diff records."""
    return str(operation.get("label") or operation.get("object", {}).get("name") or operation.get("operation") or "change")


def _compact_conversation(
    conversation: list[dict[str, Any]],
    *,
    limit: int = 16,
) -> list[dict[str, Any]]:
    """Return the most recent N conversation messages in planner-friendly form.

    WHY: The live planner prompt embeds conversation history so a follow-up
    turn can reason about the agent it has already built. We pass it to the
    agent as a compact list ordered oldest→newest and capped so prompts stay
    within the planner's token budget.
    """
    if not conversation:
        return []
    tail = conversation[-limit:]
    compact: list[dict[str, Any]] = []
    for message in tail:
        if not isinstance(message, dict):
            continue
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        compact.append(
            {
                "role": str(message.get("role") or "user"),
                "content": content[:1200],
                "turn_id": message.get("turn_id"),
            }
        )
    return compact


def _summarize_prior_turns(
    turns: list[dict[str, Any]],
    *,
    limit: int = 6,
) -> list[dict[str, Any]]:
    """Return compact per-turn summaries for the planner.

    WHY: Planners only need titles and status of earlier turns, not the raw
    plan tree or artifacts. Keeping this structured lets the agent decide
    whether a follow-up is a delta (add one tool) or a rewrite.
    """
    compact: list[dict[str, Any]] = []
    for turn in turns[-limit:]:
        if not isinstance(turn, dict):
            continue
        compact.append(
            {
                "turn_id": turn.get("turn_id"),
                "brief": str(turn.get("brief") or "")[:500],
                "status": turn.get("status"),
                "mode": turn.get("mode"),
                "operation_labels": [
                    _operation_label(op) for op in (turn.get("operations") or [])
                ][:6],
            }
        )
    return compact


def _model_summary(model: dict[str, Any]) -> dict[str, Any]:
    """Condensed canonical model view used inside agent prompts."""
    if not isinstance(model, dict):
        return {}
    root_agent = (model.get("agents") or [{}])[0] if model.get("agents") else {}
    return {
        "agent_name": root_agent.get("name"),
        "agent_role": root_agent.get("role"),
        "instructions_excerpt": str(root_agent.get("instructions") or "")[:600],
        "tool_names": [t.get("name") for t in model.get("tools", []) if t.get("name")],
        "guardrail_names": [g.get("name") for g in model.get("guardrails", []) if g.get("name")],
        "eval_suite_names": [s.get("name") for s in model.get("eval_suites", []) if s.get("name")],
        "sub_agent_count": len(root_agent.get("sub_agents") or []),
    }


def _append_assistant_chunk(
    project: dict[str, Any],
    *,
    turn_id: str,
    task_id: str,
    chunk: str,
) -> None:
    """Append a streamed assistant chunk onto the conversation history.

    Chunks from the same (turn, task) tuple coalesce onto a single message so
    the persisted log shows one narration bubble per leaf task rather than one
    per token.
    """
    conversation = project.setdefault("conversation", [])
    # Look for the most recent assistant bubble belonging to this turn+task
    # from the end so we merge into the right message even when multiple
    # leaves narrate concurrently.
    for message in reversed(conversation):
        if not isinstance(message, dict):
            continue
        if message.get("role") != "assistant":
            continue
        if message.get("turn_id") != turn_id:
            continue
        if message.get("task_id") != task_id:
            continue
        message["content"] = f"{message.get('content', '')}{chunk}"
        return
    conversation.append(
        {
            "id": f"msg-{new_id()}",
            "role": "assistant",
            "content": chunk,
            "turn_id": turn_id,
            "task_id": task_id,
            "created_at": _now_iso(),
            "kind": "narration",
        }
    )


class WorkbenchStore:
    """Persist canonical Workbench projects as JSON.

    WHY: The MVP needs durable structured state without introducing a new
    database migration. The store can later be swapped for SQLite while keeping
    the service API stable.
    """

    def __init__(self, path: str | Path = ".agentlab/workbench_projects.json") -> None:
        """Initialize the JSON store path and create parent directories lazily."""
        self.path = Path(path)

    def create_project(
        self,
        *,
        brief: str,
        target: WorkbenchTarget = "portable",
        environment: str = "draft",
    ) -> dict[str, Any]:
        """Create and persist a new canonical Workbench project."""
        project_id = f"wb-{new_id()}"
        created_at = _now_iso()
        model = _default_model(brief, target=target, environment=environment)
        project = {
            "project_id": project_id,
            "name": model["project"]["name"],
            "target": target,
            "environment": environment,
            "version": 1,
            "draft_badge": "Draft v1",
            "build_status": "idle",
            "active_run_id": None,
            "model": model,
            "compatibility": build_compatibility_diagnostics(model, target=target),
            "exports": compile_workbench_exports(model),
            "last_test": None,
            "messages": [],
            "runs": {},
            "versions": [
                {
                    "version": 1,
                    "created_at": created_at,
                    "summary": "Initial project draft",
                    "model": copy.deepcopy(model),
                }
            ],
            "plans": {},
            "activity": [
                {
                    "id": f"activity-{new_id()}",
                    "kind": "create",
                    "created_at": created_at,
                    "summary": "Created initial canonical project.",
                    "diff": [],
                }
            ],
            # Multi-turn autonomy state. ``conversation`` is the flat list of
            # user + assistant messages shown in the left pane across every
            # turn of the Workbench session. ``turns`` groups each user brief
            # with its plan tree, artifacts, and autonomous iteration history
            # so the UI can render a Claude-Code/Manus-style running log.
            "conversation": [],
            "turns": [],
            "plan": None,
            "artifacts": [],
            "build_status": "idle",
            "last_brief": "",
        }
        self.save_project(project)
        return project

    def get_default_project(self) -> dict[str, Any]:
        """Return the newest project, creating a starter project when needed."""
        projects = self._load()["projects"]
        if projects:
            newest = sorted(projects.values(), key=lambda item: item.get("version", 0), reverse=True)[0]
            return copy.deepcopy(newest)
        return self.create_project(
            brief="Build an airline support agent for booking changes, cancellations, and flight status.",
            target="portable",
            environment="draft",
        )

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        """Load one project by ID without exposing mutable store internals."""
        project = self._load()["projects"].get(project_id)
        return copy.deepcopy(project) if project is not None else None

    def list_projects(self) -> list[dict[str, Any]]:
        """Return all persisted projects for run-level lookups."""
        return [copy.deepcopy(project) for project in self._load()["projects"].values()]

    def save_project(self, project: dict[str, Any]) -> None:
        """Persist a project snapshot to disk."""
        payload = self._load()
        payload["projects"][project["project_id"]] = copy.deepcopy(project)
        self._write(payload)

    def _load(self) -> dict[str, Any]:
        """Load the store payload, tolerating empty first-run state."""
        if not self.path.exists():
            return {"projects": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"corrupt Workbench store at {self.path}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"corrupt Workbench store at {self.path}")
        projects = payload.get("projects")
        if not isinstance(projects, dict):
            raise RuntimeError(f"corrupt Workbench store at {self.path}")
        return payload

    def _write(self, payload: dict[str, Any]) -> None:
        """Write the full store atomically enough for local MVP usage."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(f".{self.path.name}.{new_id()}.tmp")
        try:
            tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            os.replace(tmp_path, self.path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()


class WorkbenchService:
    """Coordinate planning, canonical mutation, compiler output, validation, and rollback."""

    def __init__(self, store: WorkbenchStore) -> None:
        """Attach the durable canonical project store."""
        self.store = store

    def create_project(self, *, brief: str, target: str = "portable", environment: str = "draft") -> dict[str, Any]:
        """Create a canonical project and return the API response payload."""
        project = self.store.create_project(brief=brief, target=target, environment=environment)
        return self.response(project)

    def get_default_project(self) -> dict[str, Any]:
        """Return the default project with fresh compiler outputs."""
        return self.response(self.store.get_default_project())

    def get_project(self, project_id: str) -> dict[str, Any]:
        """Return a project or raise a caller-friendly lookup error."""
        project = self.store.get_project(project_id)
        if project is None:
            raise KeyError(project_id)
        if self._recover_stale_runs(project):
            self.store.save_project(project)
        return self.response(project)

    def plan_change(
        self,
        *,
        project_id: str,
        message: str,
        target: str | None = None,
        mode: str = "plan",
    ) -> dict[str, Any]:
        """Create a structured change plan without mutating the canonical model."""
        project = self._require_project(project_id)
        plan = build_change_plan(
            project=project,
            message=message,
            target=target or str(project.get("target") or "portable"),
            mode=mode,
        )
        plans = project.setdefault("plans", {})
        plans[plan["plan_id"]] = plan
        self.store.save_project(project)
        return self.response(project, plan=plan)

    def apply_plan(self, *, project_id: str, plan_id: str) -> dict[str, Any]:
        """Apply an approved plan, create a version, and run validation immediately."""
        project = self._require_project(project_id)
        plan = project.get("plans", {}).get(plan_id)
        if not isinstance(plan, dict):
            raise KeyError(plan_id)
        if plan.get("status") == "applied":
            return self.response(project, plan=plan)

        before_model = copy.deepcopy(project["model"])
        model = apply_operations(project["model"], plan.get("operations", []))
        project["model"] = model
        project["version"] = int(project.get("version") or 1) + 1
        project["draft_badge"] = f"Draft v{project['version']}"
        project["target"] = str(plan.get("target") or project.get("target") or "portable")
        project["compatibility"] = build_compatibility_diagnostics(model, target=project["target"])
        project["exports"] = compile_workbench_exports(model)
        plan["status"] = "applied"
        plan["applied_version"] = project["version"]
        plan["applied_at"] = _now_iso()

        diff = build_model_diff(before_model, model, plan.get("operations", []))
        self._add_version(project, summary=plan.get("summary") or "Applied Workbench plan.")
        self._add_activity(project, kind="apply", summary=str(plan.get("summary") or "Applied plan."), diff=diff)

        test_result = run_workbench_validation(project)
        project["last_test"] = test_result
        self._add_activity(
            project,
            kind="test",
            summary=f"Automatic test {test_result['status']}.",
            diff=[
                {
                    "field": "last_test",
                    "before": None,
                    "after": test_result["status"],
                }
            ],
        )

        self.store.save_project(project)
        return self.response(project, plan=plan)

    def run_test(self, *, project_id: str, message: str = "") -> dict[str, Any]:
        """Run deterministic validation against the current canonical model."""
        project = self._require_project(project_id)
        result = run_workbench_validation(project, sample_message=message)
        project["last_test"] = result
        self._add_activity(
            project,
            kind="test",
            summary=f"Manual test {result['status']}.",
            diff=[{"field": "last_test", "before": None, "after": result["status"]}],
        )
        self.store.save_project(project)
        return self.response(project)

    async def run_build_stream(
        self,
        *,
        project_id: str | None,
        brief: str,
        target: str = "portable",
        environment: str = "draft",
        agent: Any = None,
        auto_iterate: bool = True,
        max_iterations: int = 3,
        max_seconds: int | None = None,
        max_tokens: int | None = None,
        max_cost_usd: float | None = None,
        execution: dict[str, Any] | None = None,
    ) -> Any:
        """Drive a multi-turn streaming build run, yielding events the UI consumes.

        Returns an async iterator of ``{"event": str, "data": dict}`` events.

        Multi-turn semantics:
            * Each call represents ONE user turn (initial build or follow-up).
            * Conversation history persists on the project so the agent can
              generate delta plans that build on earlier work.
            * When ``project_id`` is provided AND the project already has
              artifacts from a prior build, this method automatically routes
              to ``run_iteration_stream()`` for delta behavior.

        Ensures a project exists (creating one from ``brief`` if needed),
        invokes the builder agent, applies ``operations`` emitted by each
        completed task to the canonical model, and persists plan+artifacts
        on every event.  The durable run lifecycle drives reflect/present
        phases after the build, ending with ``run.completed``.
        """
        from builder.workbench_agent import (  # local import to avoid cycle
            BuildRequest,
            build_default_agent,
        )
        from builder.workbench_plan import (
            PlanTask,
            PlanTaskStatus,
            WorkbenchArtifact,
            find_task,
            recompute_parent_status,
        )

        runner = agent if agent is not None else build_default_agent()

        if project_id:
            try:
                existing = self._require_project(project_id)
            except KeyError:
                existing = None

            if existing is not None and existing.get("artifacts") and brief:
                # Project has prior artifacts — treat as an iteration.
                return await self.run_iteration_stream(
                    project_id=project_id,
                    follow_up=brief,
                    target=target,
                    environment=environment,
                    agent=runner,
                    max_iterations=max_iterations,
                    max_seconds=max_seconds,
                    max_tokens=max_tokens,
                    max_cost_usd=max_cost_usd,
                    execution=execution,
                )
            project = existing or self.store.create_project(
                brief=brief, target=target, environment=environment
            )
        else:
            project = self.store.create_project(
                brief=brief, target=target, environment=environment
            )
        project.setdefault("plan", None)
        project.setdefault("artifacts", [])
        project.setdefault("messages", [])
        project.setdefault("runs", {})
        project.setdefault("harness_state", {"checkpoints": []})
        project.setdefault("build_status", "running")
        project.setdefault("conversation", [])
        project.setdefault("turns", [])
        project["build_status"] = "running"
        project["last_brief"] = brief
        project["target"] = target
        project["environment"] = environment
        started_model = copy.deepcopy(project["model"])
        run = self._start_run(
            project,
            brief=brief,
            target=target,
            environment=environment,
            budget=_normalize_budget(
                max_iterations=max_iterations,
                max_seconds=max_seconds,
                max_tokens=max_tokens,
                max_cost_usd=max_cost_usd,
            ),
            execution=execution or self._execution_metadata_from_agent(runner),
        )
        # Stable turn_id so every event in this run can be grouped by the UI.
        turn_id = run["run_id"]
        run["turn_id"] = turn_id
        self._start_turn(project, run, brief=brief, mode="initial")
        self._append_message(
            project,
            run,
            role="user",
            text=brief,
            task_id=None,
            append_to_previous=False,
        )
        self.store.save_project(project)

        request = BuildRequest(
            project_id=project["project_id"],
            brief=brief,
            target=target,
            environment=environment,
            mode="initial",
            conversation_history=_compact_conversation(project.get("conversation", [])),
            prior_turn_summary=_summarize_prior_turns(project.get("turns", [])),
            current_model_summary=_model_summary(project["model"]),
        )
        plan_root: PlanTask | None = None

        async def _stream() -> Any:
            nonlocal plan_root
            operations_for_version: list[dict[str, Any]] = []
            try:
                for startup_name, startup_data in self._run_start_events(project, run, brief=brief, mode="initial"):
                    event_payload = self._prepare_stream_event(
                        project,
                        run,
                        startup_name,
                        startup_data,
                    )
                    self._record_run_event(project, run, startup_name, event_payload)
                    self.store.save_project(project)
                    yield {"event": startup_name, "data": event_payload}

                async for event in runner.run(request, project):
                    event_name = str(event.get("event") or "")
                    data = copy.deepcopy(event.get("data") or {})

                    if self._is_cancel_requested(project, run):
                        async for cancelled in self._cancel_run_stream(
                            project,
                            run,
                            reason=str(run.get("cancel_reason") or "Run cancelled."),
                        ):
                            yield cancelled
                        return

                    if event_name == "plan.ready":
                        run["phase"] = PHASE_PLANNING
                        plan_root = PlanTask.from_dict(data["plan"])
                        project["plan"] = plan_root.to_dict()
                        project["artifacts"] = []
                        self._update_turn(project, run, plan=project["plan"])
                        self.store.save_project(project)

                    elif event_name == "message.delta":
                        run["phase"] = PHASE_PLANNING if plan_root is None else PHASE_EXECUTING
                        self._append_message(
                            project,
                            run,
                            role="assistant",
                            text=str(data.get("text") or ""),
                            task_id=str(data.get("task_id") or "") or None,
                            append_to_previous=True,
                        )
                        self.store.save_project(project)

                    elif event_name == "task.started" and plan_root is not None:
                        run["phase"] = PHASE_EXECUTING
                        task = find_task(plan_root, str(data.get("task_id") or ""))
                        if task is not None:
                            task.status = PlanTaskStatus.RUNNING.value
                            task.started_at = _now_iso()
                            recompute_parent_status(plan_root)
                            project["plan"] = plan_root.to_dict()
                        self.store.save_project(project)

                    elif event_name == "task.progress" and plan_root is not None:
                        run["phase"] = PHASE_EXECUTING
                        task = find_task(plan_root, str(data.get("task_id") or ""))
                        note = str(data.get("note") or "")
                        if task is not None and note:
                            task.log.append(note)
                            project["plan"] = plan_root.to_dict()
                            self.store.save_project(project)

                    elif event_name == "artifact.updated" and plan_root is not None:
                        run["phase"] = PHASE_EXECUTING
                        artifact_payload = data.get("artifact") or {}
                        artifact_payload.setdefault("turn_id", turn_id)
                        artifact_payload.setdefault("iteration_id", run.get("iteration_id"))
                        artifact = WorkbenchArtifact.from_dict(artifact_payload)
                        artifact_dict = artifact.to_dict()
                        artifact_dict["turn_id"] = turn_id
                        artifact_dict["iteration_id"] = run.get("iteration_id")
                        artifacts = list(project.get("artifacts", []))
                        artifacts = [a for a in artifacts if a.get("id") != artifact.id]
                        artifacts.append(artifact_dict)
                        project["artifacts"] = artifacts
                        data["artifact"] = artifact_dict
                        task = find_task(plan_root, artifact.task_id)
                        if task is not None and artifact.id not in task.artifact_ids:
                            task.artifact_ids.append(artifact.id)
                            project["plan"] = plan_root.to_dict()
                        self._update_turn(project, run, artifact_id=artifact.id, plan=project.get("plan"))
                        self.store.save_project(project)

                    elif event_name == "task.completed" and plan_root is not None:
                        run["phase"] = PHASE_EXECUTING
                        task = find_task(plan_root, str(data.get("task_id") or ""))
                        if task is not None:
                            task.status = PlanTaskStatus.DONE.value
                            task.completed_at = _now_iso()
                            recompute_parent_status(plan_root)
                            project["plan"] = plan_root.to_dict()
                        operations = list(data.get("operations") or [])
                        if operations:
                            operations_for_version.extend(operations)
                            self._update_turn(project, run, operations=operations)
                            project["model"] = apply_operations(project["model"], operations)
                            project["compatibility"] = build_compatibility_diagnostics(
                                project["model"],
                                target=str(project.get("target") or "portable"),
                            )
                            project["exports"] = compile_workbench_exports(project["model"])
                        self.store.save_project(project)

                    elif event_name == "build.completed":
                        run["phase"] = PHASE_EXECUTING
                        if operations_for_version:
                            project["version"] = int(project.get("version") or 1) + 1
                            project["draft_badge"] = f"Draft v{project['version']}"
                            self._add_version(
                                project,
                                summary=f"Built {len(operations_for_version)} change(s) from brief",
                            )
                            self._add_activity(
                                project,
                                kind="build",
                                summary=brief.strip()[:120] or "Built agent from brief.",
                                diff=build_model_diff(
                                    started_model,
                                    project["model"],
                                    operations_for_version,
                                ),
                            )
                        data["operations"] = operations_for_version
                        data["version"] = project.get("version")
                        self.store.save_project(project)

                    elif event_name == "harness.metrics":
                        # Additive harness metrics become the recovery progress
                        # fallback when a run has not emitted a plan yet.
                        project.setdefault("harness_state", {"checkpoints": []})["last_metrics"] = copy.deepcopy(data)

                    elif event_name in ("reflection.completed", "iteration.started"):
                        # Additive harness events — persist and pass through.
                        pass

                    elif event_name == "error":
                        async for failure in self._fail_run_stream(
                            project,
                            run,
                            message=str(data.get("message") or "Build failed."),
                        ):
                            yield failure
                        return

                    # Always enrich the event with the current IDs so the
                    # frontend can correlate even when a build creates a new one.
                    data = self._prepare_stream_event(project, run, event_name, data)
                    self._record_run_event(project, run, event_name, data)
                    self.store.save_project(project)
                    yield {"event": event_name, "data": data}
                    breach = self._budget_breach(run)
                    if breach is not None:
                        async for failure in self._fail_run_stream(
                            project,
                            run,
                            message=breach["message"],
                            failure_reason="budget_exceeded",
                            budget_breach=breach,
                        ):
                            yield failure
                        return

                async for terminal_event in self._complete_run_stream(
                    project=project,
                    run=run,
                    operations=operations_for_version,
                ):
                    yield terminal_event
            except Exception as exc:  # noqa: BLE001 - persist failure before surfacing it
                async for failure in self._fail_run_stream(
                    project,
                    run,
                    message=str(exc),
                ):
                    yield failure

        return _stream()

    async def run_iteration_stream(
        self,
        *,
        project_id: str,
        follow_up: str,
        target: str = "portable",
        environment: str = "draft",
        agent: Any = None,
        max_iterations: int = 3,
        max_seconds: int | None = None,
        max_tokens: int | None = None,
        max_cost_usd: float | None = None,
        execution: dict[str, Any] | None = None,
    ) -> Any:
        """Handle a follow-up iteration on an existing build.

        Loads the project, determines the iteration number from prior
        harness_state, and delegates to the agent's ``iterate()`` method
        (if available) or falls back to a fresh ``run()`` with the follow-up
        as the brief.
        """
        from builder.workbench_agent import (
            BuildRequest,
            build_default_agent,
        )
        from builder.workbench_plan import (
            PlanTask,
            PlanTaskStatus,
            WorkbenchArtifact,
            find_task,
            recompute_parent_status,
        )

        runner = agent if agent is not None else build_default_agent()
        project = self._require_project(project_id)

        # Determine iteration number from prior harness_state
        harness_state = project.setdefault("harness_state", {"checkpoints": []})
        completed_checkpoints = len(harness_state.get("checkpoints") or [])
        iteration_number = max(2, (completed_checkpoints // 5) + 2)

        project["build_status"] = "running"
        started_model = copy.deepcopy(project["model"])
        run = self._start_run(
            project,
            brief=follow_up,
            target=target,
            environment=environment,
            budget=_normalize_budget(
                max_iterations=max_iterations,
                max_seconds=max_seconds,
                max_tokens=max_tokens,
                max_cost_usd=max_cost_usd,
            ),
            execution=execution or self._execution_metadata_from_agent(runner),
        )
        run["turn_id"] = run["run_id"]
        self._start_turn(project, run, brief=follow_up, mode="follow_up")
        self._append_message(
            project,
            run,
            role="user",
            text=follow_up,
            task_id=None,
            append_to_previous=False,
        )
        self.store.save_project(project)

        request = BuildRequest(
            project_id=project["project_id"],
            brief=project.get("last_brief") or follow_up,
            target=target or str(project.get("target") or "portable"),
            environment=environment,
            mode="follow_up",
            conversation_history=_compact_conversation(project.get("conversation", [])),
            prior_turn_summary=_summarize_prior_turns(project.get("turns", [])),
            current_model_summary=_model_summary(project["model"]),
        )

        # Use agent.iterate() if available (harness-aware agents)
        if hasattr(runner, "iterate"):
            source_iter = runner.iterate(request, project, follow_up)
        else:
            # Fallback — run with combined brief
            combined_brief = f"{request.brief}\n\nIteration feedback: {follow_up}"
            request_with_followup = BuildRequest(
                project_id=request.project_id,
                brief=combined_brief,
                target=request.target,
                environment=request.environment,
                mode="follow_up",
                conversation_history=request.conversation_history,
                prior_turn_summary=request.prior_turn_summary,
                current_model_summary=request.current_model_summary,
            )
            source_iter = runner.run(request_with_followup, project)

        plan_root: PlanTask | None = None
        operations_for_version: list[dict[str, Any]] = []

        async def _stream() -> Any:
            nonlocal plan_root
            nonlocal operations_for_version
            try:
                for startup_name, startup_data in self._run_start_events(project, run, brief=follow_up, mode="follow_up"):
                    if startup_name == "iteration.started":
                        startup_data["iteration_number"] = iteration_number
                        startup_data["artifact_count"] = len(project.get("artifacts", []))
                    event_payload = self._prepare_stream_event(project, run, startup_name, startup_data)
                    self._record_run_event(project, run, startup_name, event_payload)
                    self.store.save_project(project)
                    yield {"event": startup_name, "data": event_payload}

                async for event in source_iter:
                    event_name = str(event.get("event") or "")
                    data = copy.deepcopy(event.get("data") or {})
                    if event_name == "iteration.started":
                        # Durable iteration lifecycle is owned by WorkbenchService.
                        continue
                    if self._is_cancel_requested(project, run):
                        async for cancelled in self._cancel_run_stream(
                            project,
                            run,
                            reason=str(run.get("cancel_reason") or "Run cancelled."),
                        ):
                            yield cancelled
                        return

                    if event_name == "plan.ready":
                        run["phase"] = PHASE_PLANNING
                        plan_root = PlanTask.from_dict(data["plan"])
                        project["plan"] = plan_root.to_dict()
                        self._update_turn(project, run, plan=project["plan"])
                        self.store.save_project(project)

                    elif event_name == "message.delta":
                        run["phase"] = PHASE_PLANNING if plan_root is None else PHASE_EXECUTING
                        self._append_message(
                            project,
                            run,
                            role="assistant",
                            text=str(data.get("text") or ""),
                            task_id=str(data.get("task_id") or "") or None,
                            append_to_previous=True,
                        )
                        self.store.save_project(project)

                    elif event_name == "task.started" and plan_root is not None:
                        run["phase"] = PHASE_EXECUTING
                        task = find_task(plan_root, str(data.get("task_id") or ""))
                        if task is not None:
                            task.status = PlanTaskStatus.RUNNING.value
                            task.started_at = _now_iso()
                            recompute_parent_status(plan_root)
                            project["plan"] = plan_root.to_dict()
                            self.store.save_project(project)

                    elif event_name == "task.progress" and plan_root is not None:
                        run["phase"] = PHASE_EXECUTING
                        task = find_task(plan_root, str(data.get("task_id") or ""))
                        note = str(data.get("note") or "")
                        if task is not None and note:
                            task.log.append(note)
                            project["plan"] = plan_root.to_dict()
                            self.store.save_project(project)

                    elif event_name == "artifact.updated" and plan_root is not None:
                        run["phase"] = PHASE_EXECUTING
                        artifact_payload = data.get("artifact") or {}
                        artifact_payload.setdefault("turn_id", run["turn_id"])
                        artifact_payload.setdefault("iteration_id", run.get("iteration_id"))
                        artifact = WorkbenchArtifact.from_dict(artifact_payload)
                        artifact_dict = artifact.to_dict()
                        artifact_dict["turn_id"] = run["turn_id"]
                        artifact_dict["iteration_id"] = run.get("iteration_id")
                        # Preserve prior-turn artifacts for auditability. Follow-up
                        # iterations only replace an artifact when the generator
                        # intentionally reuses the same artifact id.
                        artifacts = list(project.get("artifacts", []))
                        artifacts = [a for a in artifacts if a.get("id") != artifact.id]
                        artifacts.append(artifact_dict)
                        project["artifacts"] = artifacts
                        data["artifact"] = artifact_dict
                        task = find_task(plan_root, artifact.task_id)
                        if task is not None and artifact.id not in task.artifact_ids:
                            task.artifact_ids.append(artifact.id)
                            project["plan"] = plan_root.to_dict()
                        self._update_turn(project, run, artifact_id=artifact.id, plan=project.get("plan"))
                        self.store.save_project(project)

                    elif event_name == "task.completed" and plan_root is not None:
                        run["phase"] = PHASE_EXECUTING
                        task = find_task(plan_root, str(data.get("task_id") or ""))
                        if task is not None:
                            task.status = PlanTaskStatus.DONE.value
                            task.completed_at = _now_iso()
                            recompute_parent_status(plan_root)
                            project["plan"] = plan_root.to_dict()
                        operations = list(data.get("operations") or [])
                        if operations:
                            operations_for_version.extend(operations)
                            self._update_turn(project, run, operations=operations)
                            project["model"] = apply_operations(project["model"], operations)
                            project["compatibility"] = build_compatibility_diagnostics(
                                project["model"],
                                target=str(project.get("target") or "portable"),
                            )
                            project["exports"] = compile_workbench_exports(project["model"])
                        self.store.save_project(project)

                    elif event_name == "build.completed":
                        run["phase"] = PHASE_EXECUTING
                        if operations_for_version:
                            project["version"] = int(project.get("version") or 1) + 1
                            project["draft_badge"] = f"Draft v{project['version']}"
                            self._add_version(
                                project,
                                summary=f"Iteration {iteration_number}: {follow_up.strip()[:80]}",
                            )
                            self._add_activity(
                                project,
                                kind="build",
                                summary=f"Iteration {iteration_number}: {follow_up.strip()[:120]}",
                                diff=build_model_diff(
                                    started_model,
                                    project["model"],
                                    operations_for_version,
                                ),
                            )
                        data["operations"] = operations_for_version
                        data["version"] = project.get("version")
                        self.store.save_project(project)

                    elif event_name == "harness.metrics":
                        project.setdefault("harness_state", {"checkpoints": []})["last_metrics"] = copy.deepcopy(data)

                    elif event_name == "reflection.completed":
                        pass  # persist and yield below

                    elif event_name == "error":
                        async for failure in self._fail_run_stream(
                            project,
                            run,
                            message=str(data.get("message") or "Build failed."),
                        ):
                            yield failure
                        return

                    data = self._prepare_stream_event(project, run, event_name, data)
                    self._record_run_event(project, run, event_name, data)
                    self.store.save_project(project)
                    yield {"event": event_name, "data": data}
                    breach = self._budget_breach(run)
                    if breach is not None:
                        async for failure in self._fail_run_stream(
                            project,
                            run,
                            message=breach["message"],
                            failure_reason="budget_exceeded",
                            budget_breach=breach,
                        ):
                            yield failure
                        return

                async for terminal_event in self._complete_run_stream(
                    project=project,
                    run=run,
                    operations=operations_for_version,
                ):
                    yield terminal_event
            except Exception as exc:  # noqa: BLE001
                async for failure in self._fail_run_stream(
                    project,
                    run,
                    message=str(exc),
                ):
                    yield failure

        return _stream()

    def get_plan_snapshot(self, *, project_id: str) -> dict[str, Any]:
        """Return the current plan + artifacts snapshot for page hydration."""
        project = self._require_project(project_id)
        if self._recover_stale_runs(project):
            self.store.save_project(project)
        return {
            "project_id": project["project_id"],
            "name": project.get("name"),
            "target": project.get("target"),
            "environment": project.get("environment"),
            "version": project.get("version"),
            "build_status": project.get("build_status", "idle"),
            "plan": project.get("plan"),
            "artifacts": list(project.get("artifacts", [])),
            "messages": list(project.get("messages", [])),
            "model": project.get("model"),
            "exports": project.get("exports"),
            "compatibility": project.get("compatibility"),
            "last_test": project.get("last_test"),
            "activity": list(project.get("activity", [])),
            "active_run": self._active_run(project),
            "runs": list(project.get("runs", {}).values()),
            "last_brief": project.get("last_brief"),
            # Multi-turn state needed to rehydrate a live Workbench session.
            "conversation": list(project.get("conversation", [])),
            "turns": copy.deepcopy(project.get("turns") or []),
            "harness_state": self._harness_state_summary(project),
        }

    def _harness_state_summary(self, project: dict[str, Any]) -> dict[str, Any]:
        """Build a harness_state summary for snapshot hydration."""
        hs = project.get("harness_state") or {}
        checkpoints = hs.get("checkpoints") or []
        checkpoints = checkpoints if isinstance(checkpoints, list) else []
        latest_handoff = hs.get("latest_handoff")
        active_run = self._active_run(project)
        if latest_handoff is None and isinstance(active_run, dict):
            latest_handoff = active_run.get("handoff")
        return {
            "checkpoint_count": len(checkpoints),
            "recent_checkpoints": copy.deepcopy(checkpoints[-5:]),
            "last_metrics": hs.get("last_metrics"),
            "latest_handoff": copy.deepcopy(latest_handoff),
        }

    def _refresh_run_handoff(
        self,
        project: dict[str, Any],
        run: dict[str, Any],
        *,
        last_event: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist the compact recovery contract for a run and project."""
        handoff = self._build_run_handoff(project, run, last_event=last_event)
        run["handoff"] = handoff
        harness_state = project.setdefault("harness_state", {"checkpoints": []})
        harness_state.setdefault("checkpoints", [])
        harness_state["latest_handoff"] = copy.deepcopy(handoff)
        return handoff

    def _build_run_handoff(
        self,
        project: dict[str, Any],
        run: dict[str, Any],
        *,
        last_event: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the durable operator handoff derived from persisted run state."""
        harness_state = project.get("harness_state") if isinstance(project.get("harness_state"), dict) else {}
        metrics = harness_state.get("last_metrics") if isinstance(harness_state, dict) else None
        metrics = metrics if isinstance(metrics, dict) else None
        validation = run.get("validation") if isinstance(run.get("validation"), dict) else project.get("last_test")
        budget = run.get("budget") if isinstance(run.get("budget"), dict) else {}
        breach = budget.get("breach") if isinstance(budget.get("breach"), dict) else None
        checkpoints = harness_state.get("checkpoints") if isinstance(harness_state, dict) else []
        checkpoints = checkpoints if isinstance(checkpoints, list) else []
        handoff = {
            "project_id": project.get("project_id"),
            "run_id": run.get("run_id"),
            "turn_id": run.get("turn_id") or run.get("run_id"),
            "iteration_id": run.get("iteration_id"),
            "phase": run.get("phase"),
            "status": run.get("status"),
            "updated_at": run.get("updated_at") or _now_iso(),
            "last_event": _last_event_summary(last_event),
            "progress": _plan_progress_summary(project.get("plan"), metrics=metrics),
            "metrics": copy.deepcopy(metrics),
            "verification": _verification_summary(validation if isinstance(validation, dict) else None),
            "latest_artifact": _latest_artifact_summary(project),
            "recent_checkpoints": copy.deepcopy((checkpoints or [])[-3:]),
            "budget": {
                "usage": copy.deepcopy(budget.get("usage") or {}),
                "breach": copy.deepcopy(breach),
            },
            "failure_reason": run.get("failure_reason"),
            "cancel_reason": run.get("cancel_reason"),
            "recovery": None,
        }
        if run.get("failure_reason") == "stale_interrupted":
            handoff["recovery"] = {
                "reason": "stale_interrupted",
                "recovered_at": run.get("recovered_at"),
                "last_update_at": run.get("updated_at"),
                "checkpoint_count": len(checkpoints or []),
            }
        handoff["next_action"] = self._handoff_next_action(
            run,
            verification=handoff["verification"],
            breach=breach,
        )
        return handoff

    def _handoff_next_action(
        self,
        run: dict[str, Any],
        *,
        verification: dict[str, Any],
        breach: dict[str, Any] | None,
    ) -> str:
        """Choose one concrete next step for the operator handoff."""
        status = str(run.get("status") or "")
        if run.get("failure_reason") == "stale_interrupted":
            return "Run was interrupted after process recovery; review the last event and restart from preserved artifacts."
        if status == RUN_STATUS_CANCELLED:
            return "Run was cancelled; review preserved artifacts or start a follow-up turn."
        if breach:
            kind = str(breach.get("kind") or "budget")
            return f"Resolve the {kind} budget breach or raise the budget before retrying."
        if verification.get("status") == "failed":
            return "Review failed validation checks before promoting this build."
        if status == RUN_STATUS_FAILED:
            return "Review the failure reason, latest event, and validation state before retrying."
        if status == RUN_STATUS_COMPLETED:
            return "Review generated artifacts and run or extend evals before promotion."
        phase = str(run.get("phase") or "")
        if phase == PHASE_PLANNING:
            return "Wait for plan.ready, then check task coverage before execution."
        if phase == PHASE_EXECUTING:
            return "Watch task progress and verify artifacts appear before completion."
        if phase == PHASE_REFLECTING:
            return "Wait for validation.ready before accepting completion."
        if phase == PHASE_PRESENTING:
            return "Review the presentation summary and generated outputs."
        return "Continue monitoring the run log for the next durable event."

    def rollback(self, *, project_id: str, version: int) -> dict[str, Any]:
        """Create a new version from an earlier canonical snapshot."""
        project = self._require_project(project_id)
        current_version = int(project.get("version") or 1)
        source = next((entry for entry in project.get("versions", []) if int(entry.get("version") or 0) == version), None)
        if not isinstance(source, dict) or not isinstance(source.get("model"), dict):
            raise KeyError(str(version))

        before_model = copy.deepcopy(project["model"])
        project["model"] = copy.deepcopy(source["model"])
        project["version"] = current_version + 1
        project["draft_badge"] = f"Draft v{project['version']}"
        project["rolled_back_from_version"] = current_version
        project["rolled_back_to_version"] = version
        project["compatibility"] = build_compatibility_diagnostics(project["model"], target=str(project.get("target") or "portable"))
        project["exports"] = compile_workbench_exports(project["model"])
        self._add_version(project, summary=f"Rolled back to v{version}")
        self._add_activity(
            project,
            kind="rollback",
            summary=f"Rolled back from v{current_version} to v{version}.",
            diff=[{"field": "model", "before": _model_counts(before_model), "after": _model_counts(project["model"])}],
        )
        self.store.save_project(project)
        return self.response(project)

    def response(self, project: dict[str, Any], *, plan: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return a frontend-safe project payload with hidden snapshots removed."""
        prepared = prepare_project_payload(project)
        payload = {
            "project": prepared,
            "exports": prepared["exports"],
            "activity": prepared["activity"],
        }
        if plan is not None:
            payload["plan"] = copy.deepcopy(plan)
        return payload

    def _require_project(self, project_id: str) -> dict[str, Any]:
        """Load a project or raise `KeyError` for API 404 mapping."""
        project = self.store.get_project(project_id)
        if project is None:
            raise KeyError(project_id)
        return project

    def _add_version(self, project: dict[str, Any], *, summary: str) -> None:
        """Record an immutable canonical snapshot in the version history."""
        project.setdefault("versions", []).append(
            {
                "version": project["version"],
                "created_at": _now_iso(),
                "summary": summary,
                "model": copy.deepcopy(project["model"]),
            }
        )

    def _add_activity(
        self,
        project: dict[str, Any],
        *,
        kind: str,
        summary: str,
        diff: list[dict[str, Any]],
    ) -> None:
        """Record newest-first activity used by the Workbench diff tab."""
        project.setdefault("activity", []).insert(
            0,
            {
                "id": f"activity-{new_id()}",
                "kind": kind,
                "created_at": _now_iso(),
                "summary": summary,
                "diff": diff,
            },
        )

    def _start_run(
        self,
        project: dict[str, Any],
        *,
        brief: str,
        target: str,
        environment: str,
        budget: dict[str, Any] | None = None,
        execution: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create the durable run envelope for one builder-agent request."""
        run_id = f"run-{new_id()}"
        execution_payload = copy.deepcopy(execution or _default_execution_metadata())
        run = {
            "run_id": run_id,
            "project_id": project["project_id"],
            "brief": brief,
            "target": target,
            "environment": environment,
            "status": RUN_STATUS_RUNNING,
            "phase": PHASE_PLANNING,
            "execution": execution_payload,
            "execution_mode": execution_payload.get("mode", "mock"),
            "provider": execution_payload.get("provider", "mock"),
            "model": execution_payload.get("model", "mock-workbench"),
            "mode_reason": execution_payload.get("mock_reason", ""),
            "budget": copy.deepcopy(budget or _normalize_budget(max_iterations=3)),
            "telemetry_summary": {
                "run_id": run_id,
                "provider": execution_payload.get("provider", "mock"),
                "model": execution_payload.get("model", "mock-workbench"),
                "execution_mode": execution_payload.get("mode", "mock"),
                "duration_ms": 0,
                "tokens_used": 0,
                "cost_usd": 0.0,
                "event_count": 0,
            },
            "started_version": int(project.get("version") or 1),
            "completed_version": None,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "completed_at": None,
            "error": None,
            "failure_reason": None,
            "cancel_reason": None,
            "cancel_requested_at": None,
            "cancellation_requested": False,
            "events": [],
            "messages": [],
            "validation": None,
            "presentation": None,
            "review_gate": None,
            "handoff": None,
        }
        project.setdefault("runs", {})[run_id] = run
        project["active_run_id"] = run_id
        self._refresh_run_handoff(project, run)
        return run

    def _active_run(self, project: dict[str, Any]) -> dict[str, Any] | None:
        """Return the currently selected run for snapshot hydration."""
        run_id = project.get("active_run_id")
        runs = project.get("runs", {})
        if isinstance(run_id, str) and isinstance(runs, dict):
            run = runs.get(run_id)
            return copy.deepcopy(run) if isinstance(run, dict) else None
        if isinstance(runs, dict) and runs:
            newest = sorted(runs.values(), key=lambda item: item.get("created_at", ""))[-1]
            return copy.deepcopy(newest)
        return None

    def _recover_stale_runs(self, project: dict[str, Any]) -> bool:
        """Mark stale in-flight runs as interrupted during snapshot hydration."""
        runs = project.get("runs")
        if not isinstance(runs, dict):
            return False
        try:
            stale_seconds = int(os.environ.get("AGENTLAB_WORKBENCH_STALE_RUN_SECONDS", DEFAULT_STALE_RUN_SECONDS))
        except ValueError:
            stale_seconds = DEFAULT_STALE_RUN_SECONDS
        if stale_seconds <= 0:
            return False

        now = datetime.now(tz=timezone.utc)
        changed = False
        for run in runs.values():
            if not isinstance(run, dict):
                continue
            if str(run.get("status") or "") not in ACTIVE_RUN_STATUSES:
                continue
            updated_at = _parse_iso(run.get("updated_at") or run.get("created_at"))
            if updated_at is None:
                continue
            age_seconds = (now - updated_at).total_seconds()
            if age_seconds < stale_seconds:
                continue
            run["status"] = RUN_STATUS_FAILED
            run["phase"] = PHASE_TERMINAL
            run["failure_reason"] = "stale_interrupted"
            run["error"] = f"Run interrupted after process recovery; last update was {round(age_seconds)} seconds ago."
            run["completed_at"] = _now_iso()
            run["recovered_at"] = run["completed_at"]
            if project.get("active_run_id") == run.get("run_id"):
                project["build_status"] = RUN_STATUS_FAILED
            turn = self._current_turn(project, run)
            iteration = self._current_iteration(project, run)
            if iteration is not None:
                self._complete_iteration_record(
                    iteration,
                    status=RUN_STATUS_FAILED,
                    operations=list(iteration.get("operations") or []),
                    plan=project.get("plan"),
                )
            self._complete_turn_record(turn, status=RUN_STATUS_FAILED)
            payload = {
                "project_id": project["project_id"],
                "run_id": run.get("run_id"),
                "phase": PHASE_TERMINAL,
                "status": RUN_STATUS_FAILED,
                "failure_reason": "stale_interrupted",
                "message": run["error"],
            }
            self._enrich_stream_payload(run, payload)
            self._record_run_event(project, run, "run.recovered", payload)
            changed = True
        return changed

    def _refresh_run_from_store(
        self,
        project: dict[str, Any],
        run: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Reload the project/run so stream loops observe external cancellation."""
        latest = self.store.get_project(str(project["project_id"]))
        if not isinstance(latest, dict):
            return project, run
        latest_run = (latest.get("runs") or {}).get(run.get("run_id"))
        if not isinstance(latest_run, dict):
            return latest, run
        return latest, latest_run

    def _is_cancelled_or_requested(self, run: dict[str, Any]) -> bool:
        """Return whether a run should stop cooperatively at the next boundary."""
        return (
            str(run.get("status") or "") == RUN_STATUS_CANCELLED
            or bool(run.get("cancellation_requested"))
            or bool(run.get("cancel_requested_at"))
        )

    def _enrich_stream_payload(
        self,
        run: dict[str, Any],
        data: dict[str, Any],
        *,
        turn_id: str | None = None,
        iteration_id: str | None = None,
    ) -> None:
        """Attach IDs, lifecycle, execution mode, and budget to one SSE payload."""
        execution = run.get("execution") if isinstance(run.get("execution"), dict) else {}
        data.setdefault("run_id", run["run_id"])
        data.setdefault("turn_id", turn_id or run.get("turn_id") or run["run_id"])
        if iteration_id or run.get("iteration_id"):
            data.setdefault("iteration_id", iteration_id or run.get("iteration_id"))
        data.setdefault("phase", run.get("phase", PHASE_EXECUTING))
        data.setdefault("status", run.get("status", RUN_STATUS_RUNNING))
        data.setdefault("execution_mode", execution.get("mode") or run.get("execution_mode") or "mock")
        data.setdefault("provider", execution.get("provider") or run.get("provider") or "mock")
        data.setdefault("model", execution.get("model") or run.get("model") or "mock-workbench")
        data.setdefault("mode_reason", execution.get("mock_reason") or run.get("mode_reason") or "")
        data.setdefault("budget", copy.deepcopy(run.get("budget") or {}))

    def _update_budget_from_event(
        self,
        run: dict[str, Any],
        *,
        event_name: str,
        data: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Update budget usage from a streamed event and return a breach, if any."""
        budget = run.setdefault("budget", _normalize_budget(max_iterations=3))
        usage = _budget_usage(budget)
        usage["elapsed_ms"] = _elapsed_ms_since(run.get("created_at"))

        if event_name == "iteration.started":
            index = data.get("index")
            if isinstance(index, int):
                usage["iterations"] = max(int(usage.get("iterations") or 0), index + 1)
            else:
                usage["iterations"] = max(int(usage.get("iterations") or 0), 1)

        if event_name == "harness.metrics":
            token_usage = max(
                int(usage.get("tokens_used") or 0),
                int(data.get("tokens_used") or 0),
            )
            usage["tokens_used"] = token_usage
            usage["tokens"] = token_usage
            usage["cost_usd"] = max(
                float(usage.get("cost_usd") or 0.0),
                float(data.get("cost_usd") or 0.0),
            )
            usage["elapsed_ms"] = max(
                int(usage.get("elapsed_ms") or 0),
                int(data.get("elapsed_ms") or 0),
            )
        else:
            tokens = _estimate_tokens_for_event(event_name, data)
            if tokens:
                token_usage = int(usage.get("tokens_used") or 0) + tokens
                usage["tokens_used"] = token_usage
                usage["tokens"] = token_usage
                usage["cost_usd"] = round(
                    float(usage.get("cost_usd") or 0.0) + tokens * TOKEN_COST_ESTIMATE_USD,
                    6,
                )

        limits = budget.setdefault("limits", {})
        checks = (
            ("iterations", limits.get("max_iterations"), usage.get("iterations")),
            ("seconds", limits.get("max_seconds"), float(usage.get("elapsed_ms") or 0) / 1000.0),
            ("tokens", limits.get("max_tokens"), usage.get("tokens_used")),
            ("cost", limits.get("max_cost_usd"), usage.get("cost_usd")),
        )
        for kind, limit, actual in checks:
            if limit is None:
                continue
            if float(actual or 0) > float(limit):
                breach = {"kind": kind, "limit": limit, "actual": actual}
                budget["breach"] = breach
                return breach
        budget["breach"] = None
        return None

    def _execution_metadata_from_agent(self, agent: Any) -> dict[str, Any]:
        """Extract operator-visible execution metadata from a builder agent."""
        metadata = getattr(agent, "execution_metadata", None)
        if isinstance(metadata, dict):
            return copy.deepcopy(metadata)
        return {
            "mode": str(getattr(agent, "execution_mode", "mock")),
            "provider": str(getattr(agent, "provider", "mock")),
            "model": str(getattr(agent, "model", "mock-workbench")),
            "mock_reason": str(getattr(agent, "mode_reason", "")),
            "requested_mock": bool(getattr(agent, "requested_mock", False)),
            "live_ready": str(getattr(agent, "execution_mode", "mock")) == "live",
        }

    def _current_turn(self, project: dict[str, Any], run: dict[str, Any]) -> dict[str, Any] | None:
        """Return the durable turn record for a run, if present."""
        turn_id = run.get("turn_id") or run.get("run_id")
        for turn in project.get("turns") or []:
            if isinstance(turn, dict) and turn.get("turn_id") == turn_id:
                return turn
        return None

    def _current_iteration(self, project: dict[str, Any], run: dict[str, Any]) -> dict[str, Any] | None:
        """Return the active iteration record for a run, if present."""
        turn = self._current_turn(project, run)
        if not isinstance(turn, dict):
            return None
        iteration_id = run.get("iteration_id")
        iterations = turn.get("iterations") or []
        for iteration in iterations:
            if isinstance(iteration, dict) and iteration.get("iteration_id") == iteration_id:
                return iteration
        return iterations[-1] if iterations and isinstance(iterations[-1], dict) else None

    def _update_turn(
        self,
        project: dict[str, Any],
        run: dict[str, Any],
        *,
        plan: dict[str, Any] | None = None,
        artifact_id: str | None = None,
        operations: list[dict[str, Any]] | None = None,
    ) -> None:
        """Keep the durable turn and iteration records in sync with stream state."""
        turn = self._current_turn(project, run)
        if turn is None:
            return
        iteration = self._current_iteration(project, run)
        if plan is not None:
            turn["plan"] = copy.deepcopy(plan)
            if iteration is not None:
                iteration["plan"] = copy.deepcopy(plan)
        if artifact_id:
            artifact_ids = turn.setdefault("artifact_ids", [])
            if artifact_id not in artifact_ids:
                artifact_ids.append(artifact_id)
        if operations:
            turn.setdefault("operations", []).extend(copy.deepcopy(operations))
            if iteration is not None:
                iteration.setdefault("operations", []).extend(copy.deepcopy(operations))

    def _run_start_events(
        self,
        project: dict[str, Any],
        run: dict[str, Any],
        *,
        brief: str,
        mode: str,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Return startup lifecycle events for a Workbench turn."""
        turn = self._current_turn(project, run)
        if turn is None:
            turn = self._start_turn(project, run, brief=brief, mode=mode)
        iteration = self._start_iteration_record(turn, brief=brief, mode=mode)
        run["iteration_id"] = iteration["iteration_id"]
        return [
            (
                "turn.started",
                {
                    "project_id": project["project_id"],
                    "run_id": run["run_id"],
                    "turn_id": run["turn_id"],
                    "mode": mode,
                    "brief": brief,
                },
            ),
            (
                "iteration.started",
                {
                    "project_id": project["project_id"],
                    "run_id": run["run_id"],
                    "turn_id": run["turn_id"],
                    "iteration_id": iteration["iteration_id"],
                    "index": iteration["index"],
                    "iteration_number": iteration["index"] + 1,
                    "mode": mode,
                    "message": brief,
                    "artifact_count": len(project.get("artifacts", [])),
                },
            ),
        ]

    def _prepare_stream_event(
        self,
        project: dict[str, Any],
        run: dict[str, Any],
        event_name: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Enrich and budget-check one outgoing stream event payload."""
        payload = copy.deepcopy(data)
        payload.setdefault("project_id", project["project_id"])
        self._enrich_stream_payload(
            run,
            payload,
            turn_id=str(run.get("turn_id") or run["run_id"]),
            iteration_id=run.get("iteration_id"),
        )
        self._update_budget_from_event(run, event_name=event_name, data=payload)
        payload["budget"] = copy.deepcopy(run.get("budget") or {})
        payload["telemetry_summary"] = copy.deepcopy(run.get("telemetry_summary") or {})
        return payload

    def _budget_breach(self, run: dict[str, Any]) -> dict[str, Any] | None:
        """Return a caller-friendly budget breach payload, if one exists."""
        budget = run.get("budget") if isinstance(run.get("budget"), dict) else {}
        breach = budget.get("breach")
        if not isinstance(breach, dict):
            return None
        kind = str(breach.get("kind") or "budget")
        exceeded = (
            "max_tokens"
            if kind == "tokens"
            else "max_cost_usd"
            if kind == "cost"
            else f"max_{kind}"
        )
        budget["exceeded"] = exceeded
        budget["message"] = f"Workbench run stopped because the {kind} budget was exceeded."
        return {
            **breach,
            "exceeded": exceeded,
            "message": budget["message"],
        }

    def _is_cancel_requested(self, project: dict[str, Any], run: dict[str, Any]) -> bool:
        """Refresh persisted state and detect cooperative cancellation."""
        latest_project, latest_run = self._refresh_run_from_store(project, run)
        latest_status = str(latest_run.get("status") or "")
        if latest_status == RUN_STATUS_CANCELLED or self._is_cancelled_or_requested(latest_run):
            run.update(copy.deepcopy(latest_run))
            project.setdefault("runs", {})[run["run_id"]] = run
            project["build_status"] = RUN_STATUS_CANCELLED
            return True
        return self._is_cancelled_or_requested(run)

    def _start_turn(
        self,
        project: dict[str, Any],
        run: dict[str, Any],
        *,
        brief: str,
        mode: str,
    ) -> dict[str, Any]:
        """Create the durable multi-turn record for one user turn."""
        turn = {
            "turn_id": run["run_id"],
            "brief": brief,
            "mode": mode,
            "status": RUN_STATUS_RUNNING,
            "created_at": _now_iso(),
            "completed_at": None,
            "plan": None,
            "artifact_ids": [],
            "operations": [],
            "iterations": [],
            "validation": None,
        }
        project.setdefault("turns", []).append(turn)
        run["turn_id"] = turn["turn_id"]
        return turn

    def _start_iteration_record(
        self,
        turn: dict[str, Any],
        *,
        brief: str,
        mode: str,
    ) -> dict[str, Any]:
        """Create a durable iteration record under the active turn."""
        iterations = turn.setdefault("iterations", [])
        iteration = {
            "iteration_id": f"iter-{new_id()}",
            "index": len(iterations),
            "mode": mode,
            "brief": brief,
            "status": RUN_STATUS_RUNNING,
            "operations": [],
            "plan": None,
            "created_at": _now_iso(),
            "completed_at": None,
        }
        iterations.append(iteration)
        return iteration

    def _complete_iteration_record(
        self,
        iteration: dict[str, Any],
        *,
        status: str,
        operations: list[dict[str, Any]],
        plan: dict[str, Any] | None,
    ) -> None:
        """Persist terminal state for one iteration record."""
        iteration["status"] = status
        iteration["completed_at"] = _now_iso()
        iteration["operations"] = copy.deepcopy(operations)
        if plan is not None:
            iteration["plan"] = copy.deepcopy(plan)

    def _complete_turn_record(
        self,
        turn: dict[str, Any] | None,
        *,
        status: str,
        validation: dict[str, Any] | None = None,
    ) -> None:
        """Persist terminal state for a turn, if one exists."""
        if turn is None:
            return
        turn["status"] = status
        turn["completed_at"] = _now_iso()
        if validation is not None:
            turn["validation"] = {
                "run_id": validation.get("run_id"),
                "status": validation.get("status"),
                "checks": validation.get("checks", []),
            }

    async def _turn_completed_stream(
        self,
        project: dict[str, Any],
        run: dict[str, Any],
        *,
        status: str | None = None,
        validation: dict[str, Any] | None = None,
    ) -> Any:
        """Persist and emit a turn.completed event for UI hydration."""
        final_status = status or str(run.get("status") or RUN_STATUS_COMPLETED)
        turn = self._current_turn(project, run)
        iteration = self._current_iteration(project, run)
        if iteration is not None:
            self._complete_iteration_record(
                iteration,
                status=final_status,
                operations=list(iteration.get("operations") or []),
                plan=iteration.get("plan") or (turn or {}).get("plan"),
            )
        self._complete_turn_record(turn, status=final_status, validation=validation)
        payload = {
            "project_id": project["project_id"],
            "run_id": run["run_id"],
            "turn_id": run.get("turn_id") or run["run_id"],
            "phase": PHASE_TERMINAL,
            "status": final_status,
            "version": int(project.get("version") or 1),
            "validation": validation,
            "iterations": len((turn or {}).get("iterations") or []),
        }
        self._enrich_stream_payload(run, payload)
        self._record_run_event(project, run, "turn.completed", payload)
        self.store.save_project(project)
        yield {"event": "turn.completed", "data": payload}

    def cancel_run(
        self,
        *,
        project_id: str | None = None,
        run_id: str,
        reason: str = "",
    ) -> dict[str, Any]:
        """Request and persist cancellation for an active Workbench run.

        WHY: operators often only have the run id from logs or telemetry.  The
        service accepts an optional project id for fast-path API calls, but can
        also locate the run across persisted projects.
        """
        projects = [self._require_project(project_id)] if project_id else self.store.list_projects()
        for project in projects:
            run = (project.get("runs") or {}).get(run_id)
            if not isinstance(run, dict):
                continue
            if str(run.get("status") or "") in TERMINAL_RUN_STATUSES:
                return build_run_completion_payload(project, run)
            now = _now_iso()
            run["cancellation_requested"] = True
            run["cancel_requested_at"] = now
            run["cancel_reason"] = reason or "Cancelled by operator."
            requested = {
                "project_id": project["project_id"],
                "run_id": run_id,
                "phase": run.get("phase", PHASE_EXECUTING),
                "status": RUN_STATUS_CANCELLED,
                "cancel_reason": run["cancel_reason"],
            }
            self._enrich_stream_payload(run, requested)
            self._record_run_event(project, run, "run.cancel_requested", requested)
            run["status"] = RUN_STATUS_CANCELLED
            run["phase"] = PHASE_TERMINAL
            run["completed_at"] = now
            project["build_status"] = RUN_STATUS_CANCELLED
            turn = self._current_turn(project, run)
            iteration = self._current_iteration(project, run)
            if iteration is not None:
                self._complete_iteration_record(
                    iteration,
                    status=RUN_STATUS_CANCELLED,
                    operations=list(iteration.get("operations") or []),
                    plan=project.get("plan"),
                )
            self._complete_turn_record(turn, status=RUN_STATUS_CANCELLED)
            cancelled = build_run_completion_payload(project, run)
            cancelled["turn_id"] = run.get("turn_id") or run["run_id"]
            cancelled["iteration_id"] = iteration.get("iteration_id") if isinstance(iteration, dict) else run.get("iteration_id")
            self._enrich_stream_payload(run, cancelled, turn_id=cancelled["turn_id"], iteration_id=cancelled.get("iteration_id"))
            self._record_run_event(project, run, "run.cancelled", cancelled)
            self.store.save_project(project)
            return build_run_completion_payload(project, run)
        raise KeyError(run_id)

    def _record_run_event(
        self,
        project: dict[str, Any],
        run: dict[str, Any],
        event_name: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Append one replayable event to the active run."""
        events = run.setdefault("events", [])
        telemetry = self._build_telemetry(run, event_name=event_name, data=data)
        data.setdefault("telemetry", telemetry)
        event = {
            "sequence": len(events) + 1,
            "event": event_name,
            "phase": data.get("phase") or run.get("phase"),
            "status": data.get("status") or run.get("status"),
            "created_at": _now_iso(),
            "data": copy.deepcopy(data),
            "telemetry": telemetry,
        }
        events.append(event)
        run["updated_at"] = event["created_at"]
        self._update_telemetry_summary(run, telemetry, event_count=len(events))
        handoff = self._refresh_run_handoff(project, run, last_event=event)
        data["handoff"] = copy.deepcopy(handoff)
        if isinstance(data.get("run"), dict):
            data["run"]["handoff"] = copy.deepcopy(handoff)
        event["data"]["handoff"] = copy.deepcopy(handoff)
        if isinstance(event["data"].get("run"), dict):
            event["data"]["run"]["handoff"] = copy.deepcopy(handoff)
        project.setdefault("runs", {})[run["run_id"]] = run
        return event

    def _build_telemetry(
        self,
        run: dict[str, Any],
        *,
        event_name: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the normalized telemetry envelope for one run event."""
        budget = run.get("budget") if isinstance(run.get("budget"), dict) else {}
        usage = budget.get("usage") if isinstance(budget.get("usage"), dict) else {}
        execution = run.get("execution") if isinstance(run.get("execution"), dict) else {}
        return {
            "event": event_name,
            "run_id": run.get("run_id"),
            "turn_id": data.get("turn_id") or run.get("turn_id") or run.get("run_id"),
            "iteration_id": data.get("iteration_id") or run.get("iteration_id"),
            "phase": data.get("phase") or run.get("phase"),
            "status": data.get("status") or run.get("status"),
            "provider": data.get("provider") or execution.get("provider") or run.get("provider"),
            "model": data.get("model") or execution.get("model") or run.get("model"),
            "execution_mode": data.get("execution_mode") or execution.get("mode") or run.get("execution_mode"),
            "tokens_used": int(usage.get("tokens_used") or 0),
            "cost_usd": float(usage.get("cost_usd") or 0.0),
            "duration_ms": _elapsed_ms_since(run.get("created_at")),
            "failure_reason": data.get("failure_reason") or run.get("failure_reason"),
            "cancel_reason": data.get("cancel_reason") or run.get("cancel_reason"),
            "budget_breach": budget.get("breach"),
        }

    def _update_telemetry_summary(
        self,
        run: dict[str, Any],
        telemetry: dict[str, Any],
        *,
        event_count: int,
    ) -> None:
        """Maintain a compact, operator-visible telemetry summary on the run."""
        summary = run.setdefault("telemetry_summary", {})
        summary.update(
            {
                "run_id": telemetry.get("run_id"),
                "provider": telemetry.get("provider"),
                "model": telemetry.get("model"),
                "execution_mode": telemetry.get("execution_mode"),
                "phase": telemetry.get("phase"),
                "status": telemetry.get("status"),
                "duration_ms": telemetry.get("duration_ms"),
                "tokens_used": telemetry.get("tokens_used"),
                "cost_usd": telemetry.get("cost_usd"),
                "failure_reason": telemetry.get("failure_reason"),
                "cancel_reason": telemetry.get("cancel_reason"),
                "budget_breach": telemetry.get("budget_breach"),
                "event_count": event_count,
            }
        )

    def _append_message(
        self,
        project: dict[str, Any],
        run: dict[str, Any],
        *,
        role: str,
        text: str,
        task_id: str | None,
        append_to_previous: bool,
    ) -> None:
        """Persist user and assistant narration so refreshes keep context."""
        if not text:
            return
        if role == "assistant":
            _append_assistant_chunk(
                project,
                turn_id=str(run.get("turn_id") or run["run_id"]),
                task_id=task_id or "",
                chunk=text,
            )
        for collection in (project.setdefault("messages", []), run.setdefault("messages", [])):
            last = collection[-1] if collection else None
            if (
                append_to_previous
                and isinstance(last, dict)
                and last.get("role") == role
                and last.get("task_id") == task_id
                and last.get("run_id") == run["run_id"]
            ):
                last["text"] = f"{last.get('text', '')}{text}".strip()
                last["updated_at"] = _now_iso()
                continue
            collection.append(
                {
                    "id": f"message-{new_id()}",
                    "run_id": run["run_id"],
                    "turn_id": run.get("turn_id"),
                    "role": role,
                    "task_id": task_id,
                    "text": text.strip(),
                    "created_at": _now_iso(),
                }
            )
        conversation = project.setdefault("conversation", [])
        last = conversation[-1] if conversation else None
        if (
            append_to_previous
            and isinstance(last, dict)
            and last.get("role") == role
            and last.get("task_id") == task_id
            and last.get("turn_id") == run.get("turn_id")
        ):
            last["content"] = f"{last.get('content', '')}{text}".strip()
            last["updated_at"] = _now_iso()
            return
        conversation.append(
            {
                "id": f"conversation-{new_id()}",
                "run_id": run["run_id"],
                "turn_id": run.get("turn_id"),
                "role": role,
                "task_id": task_id,
                "content": text.strip(),
                "created_at": _now_iso(),
            }
        )

    async def _complete_run_stream(
        self,
        *,
        project: dict[str, Any],
        run: dict[str, Any],
        operations: list[dict[str, Any]],
        turn: dict[str, Any] | None = None,
        iteration: dict[str, Any] | None = None,
    ) -> Any:
        """Run reflection, produce presentation data, and emit terminal events."""
        turn = turn or self._current_turn(project, run)
        iteration = iteration or self._current_iteration(project, run)
        run["phase"] = PHASE_REFLECTING
        run["status"] = RUN_STATUS_REFLECTING
        project["build_status"] = RUN_STATUS_REFLECTING
        reflect_started = {
            "project_id": project["project_id"],
            "run_id": run["run_id"],
            "turn_id": run.get("turn_id") or run["run_id"],
            "iteration_id": iteration.get("iteration_id") if isinstance(iteration, dict) else run.get("iteration_id"),
            "phase": PHASE_REFLECTING,
            "status": RUN_STATUS_REFLECTING,
            "checks": ["canonical_model_present", "exports_compile", "target_compatibility"],
        }
        self._enrich_stream_payload(run, reflect_started, turn_id=reflect_started["turn_id"], iteration_id=reflect_started.get("iteration_id"))
        self._record_run_event(project, run, "reflect.started", reflect_started)
        self.store.save_project(project)
        yield {"event": "reflect.started", "data": reflect_started}

        project["exports"] = compile_workbench_exports(project["model"])
        project["compatibility"] = build_compatibility_diagnostics(
            project["model"],
            target=str(project.get("target") or "portable"),
        )
        validation = run_workbench_validation(project)
        project["last_test"] = validation
        run["validation"] = validation
        self._add_activity(
            project,
            kind="test",
            summary=f"Harness reflection {validation['status']}.",
            diff=[{"field": "last_test", "before": None, "after": validation["status"]}],
        )
        reflect_completed = {
            "project_id": project["project_id"],
            "run_id": run["run_id"],
            "turn_id": run.get("turn_id") or run["run_id"],
            "iteration_id": iteration.get("iteration_id") if isinstance(iteration, dict) else run.get("iteration_id"),
            "phase": PHASE_REFLECTING,
            "status": validation["status"],
            "validation": validation,
        }
        self._enrich_stream_payload(run, reflect_completed, turn_id=reflect_completed["turn_id"], iteration_id=reflect_completed.get("iteration_id"))
        self._record_run_event(project, run, "reflect.completed", reflect_completed)
        self.store.save_project(project)
        yield {"event": "reflect.completed", "data": reflect_completed}

        validation_ready = {
            "project_id": project["project_id"],
            "run_id": run["run_id"],
            "turn_id": run.get("turn_id") or run["run_id"],
            "iteration_id": iteration.get("iteration_id") if isinstance(iteration, dict) else run.get("iteration_id"),
            "phase": PHASE_REFLECTING,
            "status": validation["status"],
            "checks": validation.get("checks", []),
            "validation": validation,
        }
        self._enrich_stream_payload(run, validation_ready, turn_id=validation_ready["turn_id"], iteration_id=validation_ready.get("iteration_id"))
        self._record_run_event(project, run, "validation.ready", validation_ready)
        self.store.save_project(project)
        yield {"event": "validation.ready", "data": validation_ready}

        run["phase"] = PHASE_PRESENTING
        run["status"] = RUN_STATUS_PRESENTING
        project["build_status"] = RUN_STATUS_PRESENTING
        presentation = build_presentation_manifest(project, run=run, operations=operations)
        run["presentation"] = presentation
        run["review_gate"] = copy.deepcopy(presentation.get("review_gate"))
        run["handoff"] = copy.deepcopy(presentation.get("handoff"))
        present_ready = {
            "project_id": project["project_id"],
            "run_id": run["run_id"],
            "turn_id": run.get("turn_id") or run["run_id"],
            "iteration_id": iteration.get("iteration_id") if isinstance(iteration, dict) else run.get("iteration_id"),
            "phase": PHASE_PRESENTING,
            "status": "ready",
            "presentation": presentation,
        }
        self._enrich_stream_payload(run, present_ready, turn_id=present_ready["turn_id"], iteration_id=present_ready.get("iteration_id"))
        self._record_run_event(project, run, "present.ready", present_ready)
        self.store.save_project(project)
        yield {"event": "present.ready", "data": present_ready}

        final_status = RUN_STATUS_COMPLETED if validation["status"] == "passed" else RUN_STATUS_FAILED
        run["status"] = final_status
        run["phase"] = PHASE_PRESENTING
        run["completed_version"] = int(project.get("version") or 1)
        run["completed_at"] = _now_iso()
        project["build_status"] = final_status
        if iteration is not None:
            self._complete_iteration_record(
                iteration,
                status=final_status,
                operations=operations,
                plan=project.get("plan"),
            )
        self._complete_turn_record(turn, status=final_status, validation=validation)
        turn_iteration_id = iteration.get("iteration_id") if isinstance(iteration, dict) else run.get("iteration_id")
        turn_payload = {
            "project_id": project["project_id"],
            "run_id": run["run_id"],
            "turn_id": run.get("turn_id") or run["run_id"],
            "iteration_id": turn_iteration_id,
            "phase": PHASE_TERMINAL,
            "status": final_status,
            "version": int(project.get("version") or 1),
            "iterations": len(turn.get("iterations", [])) if isinstance(turn, dict) else 1,
            "validation": validation,
            "run": copy.deepcopy(run),
        }
        self._enrich_stream_payload(run, turn_payload, turn_id=turn_payload["turn_id"], iteration_id=turn_iteration_id)
        self._record_run_event(project, run, "turn.completed", turn_payload)
        self.store.save_project(project)
        yield {"event": "turn.completed", "data": turn_payload}

        payload = build_run_completion_payload(project, run)
        payload["turn_id"] = run.get("turn_id") or run["run_id"]
        payload["iteration_id"] = iteration.get("iteration_id") if isinstance(iteration, dict) else run.get("iteration_id")
        self._enrich_stream_payload(run, payload, turn_id=payload.get("turn_id"), iteration_id=payload.get("iteration_id"))
        self._record_run_event(project, run, "run.completed", payload)
        self.store.save_project(project)
        yield {"event": "run.completed", "data": payload}

    async def _fail_run_stream(
        self,
        project: dict[str, Any],
        run: dict[str, Any],
        *,
        message: str,
        failure_reason: str = "error",
        budget_breach: dict[str, Any] | None = None,
        turn: dict[str, Any] | None = None,
        iteration: dict[str, Any] | None = None,
    ) -> Any:
        """Persist and emit a failed terminal run state."""
        turn = turn or self._current_turn(project, run)
        iteration = iteration or self._current_iteration(project, run)
        run["status"] = RUN_STATUS_FAILED
        run["phase"] = PHASE_TERMINAL
        run["error"] = message
        run["failure_reason"] = failure_reason
        if budget_breach is not None:
            run.setdefault("budget", _normalize_budget())["breach"] = copy.deepcopy(budget_breach)
        run["completed_at"] = _now_iso()
        project["build_status"] = RUN_STATUS_FAILED
        if iteration is not None:
            self._complete_iteration_record(
                iteration,
                status=RUN_STATUS_FAILED,
                operations=list(iteration.get("operations") or []),
                plan=project.get("plan"),
            )
        self._complete_turn_record(turn, status=RUN_STATUS_FAILED)
        error_payload = {
            "project_id": project["project_id"],
            "run_id": run["run_id"],
            "turn_id": run.get("turn_id") or run["run_id"],
            "iteration_id": iteration.get("iteration_id") if isinstance(iteration, dict) else run.get("iteration_id"),
            "phase": PHASE_TERMINAL,
            "status": RUN_STATUS_FAILED,
            "message": message,
            "failure_reason": failure_reason,
        }
        self._enrich_stream_payload(run, error_payload, turn_id=error_payload["turn_id"], iteration_id=error_payload.get("iteration_id"))
        self._record_run_event(project, run, "error", error_payload)
        self.store.save_project(project)
        yield {"event": "error", "data": error_payload}

        if turn is not None:
            turn_iteration_id = iteration.get("iteration_id") if isinstance(iteration, dict) else run.get("iteration_id")
            turn_payload = {
                "project_id": project["project_id"],
                "run_id": run["run_id"],
                "turn_id": run.get("turn_id") or run["run_id"],
                "iteration_id": turn_iteration_id,
                "phase": PHASE_TERMINAL,
                "status": RUN_STATUS_FAILED,
                "failure_reason": failure_reason,
                "message": message,
                "run": copy.deepcopy(run),
            }
            self._enrich_stream_payload(run, turn_payload, turn_id=turn_payload["turn_id"], iteration_id=turn_iteration_id)
            self._record_run_event(project, run, "turn.completed", turn_payload)
            self.store.save_project(project)
            yield {"event": "turn.completed", "data": turn_payload}

        failed_payload = build_run_completion_payload(project, run)
        failed_payload["message"] = message
        failed_payload["failure_reason"] = failure_reason
        failed_payload["turn_id"] = run.get("turn_id") or run["run_id"]
        failed_payload["iteration_id"] = iteration.get("iteration_id") if isinstance(iteration, dict) else run.get("iteration_id")
        self._enrich_stream_payload(run, failed_payload, turn_id=failed_payload["turn_id"], iteration_id=failed_payload.get("iteration_id"))
        self._record_run_event(project, run, "run.failed", failed_payload)
        self.store.save_project(project)
        yield {"event": "run.failed", "data": failed_payload}

    async def _cancel_run_stream(
        self,
        project: dict[str, Any],
        run: dict[str, Any],
        *,
        reason: str | None = None,
        turn: dict[str, Any] | None = None,
        iteration: dict[str, Any] | None = None,
    ) -> Any:
        """Emit terminal cancellation state for a cooperatively stopped stream."""
        turn = turn or self._current_turn(project, run)
        iteration = iteration or self._current_iteration(project, run)
        now = _now_iso()
        run["status"] = RUN_STATUS_CANCELLED
        run["phase"] = PHASE_TERMINAL
        run["cancel_reason"] = reason or run.get("cancel_reason") or "Cancelled by operator."
        run["completed_at"] = run.get("completed_at") or now
        run["cancellation_requested"] = True
        run["cancel_requested_at"] = run.get("cancel_requested_at") or now
        project["build_status"] = RUN_STATUS_CANCELLED
        if iteration is not None:
            self._complete_iteration_record(
                iteration,
                status=RUN_STATUS_CANCELLED,
                operations=list(iteration.get("operations") or []),
                plan=project.get("plan"),
            )
        self._complete_turn_record(turn, status=RUN_STATUS_CANCELLED)
        if turn is not None:
            turn_iteration_id = iteration.get("iteration_id") if isinstance(iteration, dict) else run.get("iteration_id")
            turn_payload = {
                "project_id": project["project_id"],
                "run_id": run["run_id"],
                "turn_id": run.get("turn_id") or run["run_id"],
                "iteration_id": turn_iteration_id,
                "phase": PHASE_TERMINAL,
                "status": RUN_STATUS_CANCELLED,
                "cancel_reason": run.get("cancel_reason"),
                "run": copy.deepcopy(run),
            }
            self._enrich_stream_payload(run, turn_payload, turn_id=turn_payload["turn_id"], iteration_id=turn_iteration_id)
            self._record_run_event(project, run, "turn.completed", turn_payload)
            self.store.save_project(project)
            yield {"event": "turn.completed", "data": turn_payload}

        payload = build_run_completion_payload(project, run)
        payload["cancel_reason"] = run["cancel_reason"]
        payload["turn_id"] = run.get("turn_id") or run["run_id"]
        payload["iteration_id"] = iteration.get("iteration_id") if isinstance(iteration, dict) else run.get("iteration_id")
        self._enrich_stream_payload(run, payload, turn_id=payload["turn_id"], iteration_id=payload.get("iteration_id"))
        self._record_run_event(project, run, "run.cancelled", payload)
        self.store.save_project(project)
        yield {"event": "run.cancelled", "data": payload}


def build_presentation_manifest(
    project: dict[str, Any],
    *,
    run: dict[str, Any],
    operations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Summarize the completed harness run for the right-side workspace."""
    artifacts = list(project.get("artifacts", []))
    latest_artifact = artifacts[-1] if artifacts else None
    invalid = [
        item
        for item in project.get("compatibility", [])
        if isinstance(item, dict) and item.get("status") == "invalid"
    ]
    next_actions = [
        "Review the generated artifacts and source previews.",
        "Run or extend the evaluation suite before saving to Agent Library.",
    ]
    if invalid:
        next_actions.insert(0, "Resolve invalid target compatibility before deployment.")
    else:
        next_actions.append("Complete human review before promotion to Eval Runs or Deploy.")
    review_gate = build_review_gate(project, run=run)
    presentation = {
        "run_id": run["run_id"],
        "version": int(project.get("version") or 1),
        "summary": f"Built {len(operations)} canonical change(s) and refreshed generated outputs.",
        "artifact_ids": [artifact.get("id") for artifact in artifacts if artifact.get("id")],
        "active_artifact_id": latest_artifact.get("id") if isinstance(latest_artifact, dict) else None,
        "generated_outputs": sorted((project.get("exports", {}).get("adk", {}).get("files") or {}).keys()),
        "validation_status": (project.get("last_test") or {}).get("status"),
        "next_actions": next_actions,
        "review_gate": review_gate,
    }
    presentation["handoff"] = build_run_handoff(project, run=run, presentation=presentation)
    return presentation


def build_review_gate(project: dict[str, Any], *, run: dict[str, Any]) -> dict[str, Any]:
    """Return explicit promotion-readiness checks for one completed run.

    WHY: the Workbench can generate useful drafts, but the PRD requires human
    promotion and durable evidence. This gate makes that state explicit instead
    of relying on optimistic UI copy.
    """
    validation = run.get("validation") if isinstance(run.get("validation"), dict) else project.get("last_test") or {}
    validation_status = str(validation.get("status") or "missing")
    invalid = [
        item
        for item in project.get("compatibility", [])
        if isinstance(item, dict) and item.get("status") == "invalid"
    ]
    checks = [
        {
            "name": "harness_validation",
            "status": "passed" if validation_status == "passed" else "failed",
            "required": True,
            "detail": (
                "Latest harness validation passed."
                if validation_status == "passed"
                else f"Latest harness validation is {validation_status}."
            ),
        },
        {
            "name": "target_compatibility",
            "status": "passed" if not invalid else "failed",
            "required": True,
            "detail": (
                "No invalid target compatibility diagnostics."
                if not invalid
                else f"{len(invalid)} invalid target compatibility diagnostic(s)."
            ),
        },
        {
            "name": "human_review",
            "status": "required",
            "required": True,
            "detail": "Human review is required before promotion to Eval Runs or Deploy.",
        },
    ]
    blocking_reasons = [
        check["detail"]
        for check in checks
        if check["required"] and check["status"] == "failed"
    ]
    return {
        "status": "blocked" if blocking_reasons else "review_required",
        "promotion_status": "draft",
        "requires_human_review": True,
        "checks": checks,
        "blocking_reasons": blocking_reasons,
    }


def build_run_handoff(
    project: dict[str, Any],
    *,
    run: dict[str, Any],
    presentation: dict[str, Any],
) -> dict[str, Any]:
    """Build compact resume context for the next Workbench session."""
    review_gate = presentation.get("review_gate") if isinstance(presentation.get("review_gate"), dict) else {}
    gate_status = str(review_gate.get("status") or "unknown")
    if gate_status == "blocked":
        next_action = "Resolve blocking review gate issues before promotion."
    else:
        next_action = "Review candidate and run evals before promotion."
    version = int(project.get("version") or 1)
    run_id = str(run.get("run_id") or "")
    return {
        "project_id": project["project_id"],
        "run_id": run_id,
        "turn_id": run.get("turn_id") or run_id,
        "version": version,
        "review_gate_status": gate_status,
        "active_artifact_id": presentation.get("active_artifact_id"),
        "last_event_sequence": len(run.get("events") or []),
        "next_operator_action": next_action,
        "resume_prompt": (
            f"Resume Workbench project {project['project_id']} at Draft v{version}. "
            f"Review run {run_id}, inspect the review gate ({gate_status}), "
            f"and {next_action[0].lower()}{next_action[1:]}"
        ),
    }


def build_run_completion_payload(project: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    """Build a terminal SSE payload with all state the UI needs to stay honest."""
    prepared = prepare_project_payload(project)
    return {
        "project_id": project["project_id"],
        "run_id": run["run_id"],
        "phase": run.get("phase"),
        "status": run.get("status"),
        "execution_mode": run.get("execution_mode") or (run.get("execution") or {}).get("mode"),
        "provider": run.get("provider") or (run.get("execution") or {}).get("provider"),
        "model": run.get("model") or (run.get("execution") or {}).get("model"),
        "mode_reason": run.get("mode_reason") or (run.get("execution") or {}).get("mock_reason"),
        "budget": copy.deepcopy(run.get("budget") or {}),
        "telemetry_summary": copy.deepcopy(run.get("telemetry_summary") or {}),
        "failure_reason": run.get("failure_reason"),
        "cancel_reason": run.get("cancel_reason"),
        "review_gate": copy.deepcopy(run.get("review_gate")),
        "handoff": copy.deepcopy(run.get("handoff")),
        "version": int(project.get("version") or 1),
        "validation": run.get("validation") or project.get("last_test"),
        "presentation": run.get("presentation"),
        "project": prepared,
        "exports": prepared.get("exports"),
        "compatibility": prepared.get("compatibility"),
        "activity": prepared.get("activity", []),
        "messages": prepared.get("messages", []),
        "run": copy.deepcopy(run),
    }


def build_change_plan(
    *,
    project: dict[str, Any],
    message: str,
    target: str,
    mode: str = "plan",
) -> dict[str, Any]:
    """Interpret a natural-language request into structured model operations."""
    operations = infer_operations(message)
    if not operations:
        operations = [
            {
                "operation": "update_instructions",
                "target": "agents.root.instructions",
                "label": "Instruction refinement",
                "object": {"instructions_append": message.strip()},
            }
        ]

    for operation in operations:
        operation["compatibility_status"] = compatibility_status_for_object(
            operation.get("object", {}),
            target=target,
        )["status"]

    summary = summarize_plan(operations)
    return {
        "plan_id": f"plan-{new_id()}",
        "status": "planned",
        "mode": mode,
        "target": target,
        "summary": summary,
        "requires_approval": True,
        "operations": operations,
        "created_at": _now_iso(),
        "test_after_apply": True,
        "source_version": project.get("version", 1),
    }


def infer_operations(message: str) -> list[dict[str, Any]]:
    """Infer deterministic MVP operations from a free-form user request."""
    lowered = message.lower()
    operations: list[dict[str, Any]] = []

    if "flight status" in lowered or ("status" in lowered and "tool" in lowered):
        operations.append(_tool_operation("flight_status_lookup", "Look up live flight status and disruption details.", "function_tool"))
    elif "local shell" in lowered or "terminal command" in lowered or "shell tool" in lowered:
        operations.append(_tool_operation("local_shell", "Run a local terminal command for diagnostics.", "local_shell"))
    elif "tool" in lowered:
        tool_name = _slugify(message, "custom_tool")[:40]
        operations.append(_tool_operation(tool_name, f"Tool requested by: {message.strip()}", "function_tool"))

    if "callback" in lowered or "after response" in lowered or "after_response" in lowered:
        operations.append(
            {
                "operation": "add_callback",
                "target": "callbacks",
                "label": "after_response_summary",
                "object": {
                    "id": "callback-after-response-summary",
                    "name": "after_response_summary",
                    "hook": "after_response",
                    "description": "Summarize response quality signals after each agent answer.",
                },
            }
        )

    if "guardrail" in lowered or "policy" in lowered or "never" in lowered or "pii" in lowered:
        if "pii" in lowered or "private" in lowered:
            name = "PII Protection"
            rule = "Never expose private data or personally identifiable information."
            item_id = "guardrail-pii"
        elif "internal code" in lowered or "internal codes" in lowered:
            name = "Internal Code Protection"
            rule = "Never reveal internal codes, private routing metadata, or hidden system details."
            item_id = "guardrail-internal-code-protection"
        else:
            name = "Safety Guardrail"
            rule = message.strip()
            item_id = f"guardrail-{_slugify(name)}"
        operations.append(
            {
                "operation": "add_guardrail",
                "target": "guardrails",
                "label": name,
                "object": {"id": item_id, "name": name, "rule": rule},
            }
        )

    if "eval" in lowered or "test" in lowered:
        if "delayed flight" in lowered or "delayed flights" in lowered or "flight" in lowered:
            suite = {
                "id": "eval-delayed-flights",
                "name": "Delayed Flights",
                "cases": [
                    {
                        "id": "case-delayed-flight-change",
                        "input": "My flight is delayed and I need to change my booking.",
                        "expected": "Uses disruption-aware booking guidance and protects private details.",
                    }
                ],
            }
        else:
            suite = {
                "id": f"eval-{_slugify(message, 'regression')[:32]}",
                "name": "Regression Checks",
                "cases": [
                    {
                        "id": "case-regression-001",
                        "input": message.strip() or "Validate the current draft.",
                        "expected": "Responds safely and follows configured instructions.",
                    }
                ],
            }
        operations.append(
            {
                "operation": "add_eval_suite",
                "target": "eval_suites",
                "label": suite["name"],
                "object": suite,
            }
        )

    if "sub-agent" in lowered or "subagent" in lowered or "sub agent" in lowered:
        name = "Escalation Specialist"
        operations.append(
            {
                "operation": "add_sub_agent",
                "target": "agents.root.sub_agents",
                "label": name,
                "object": {
                    "id": "agent-escalation-specialist",
                    "name": name,
                    "role": "Handle escalations and edge cases that need expert review.",
                    "model": "gpt-5.4-mini",
                    "instructions": "Review escalated conversations, ask for missing context, and keep decisions auditable.",
                    "sub_agents": [],
                },
            }
        )

    return operations


def _tool_operation(name: str, description: str, tool_type: str) -> dict[str, Any]:
    """Build a canonical add-tool operation from inferred request details."""
    tool_id = f"tool-{_slugify(name)}"
    return {
        "operation": "add_tool",
        "target": "tools",
        "label": name,
        "object": {
            "id": tool_id,
            "name": name,
            "description": description,
            "type": tool_type,
            "parameters": ["query"] if tool_type != "local_shell" else ["command"],
        },
    }


def summarize_plan(operations: list[dict[str, Any]]) -> str:
    """Create concise plan copy from structured operations."""
    labels = [_operation_label(operation) for operation in operations]
    if len(labels) == 1:
        return f"Add {labels[0]} to the canonical model."
    if {"flight_status_lookup", "PII Protection"}.issubset(set(labels)):
        return "Add a flight status lookup tool and guardrail."
    return "Apply " + ", ".join(labels[:-1]) + f", and {labels[-1]}."


def apply_operations(model: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a new canonical model with operations applied."""
    next_model = copy.deepcopy(model)
    for operation in operations:
        op = operation.get("operation")
        obj = copy.deepcopy(operation.get("object") or {})
        if op == "add_tool":
            next_model["tools"] = _dedupe_by_id([*next_model.get("tools", []), obj])
        elif op == "add_callback":
            next_model["callbacks"] = _dedupe_by_id([*next_model.get("callbacks", []), obj])
        elif op == "add_guardrail":
            next_model["guardrails"] = _dedupe_by_id([*next_model.get("guardrails", []), obj])
        elif op == "add_eval_suite":
            next_model["eval_suites"] = _dedupe_by_id([*next_model.get("eval_suites", []), obj])
        elif op == "add_sub_agent":
            next_model["agents"] = _dedupe_by_id([*next_model.get("agents", []), obj])
            root = _root_agent(next_model)
            sub_agents = list(root.get("sub_agents", []))
            if obj["id"] not in sub_agents:
                sub_agents.append(obj["id"])
            root["sub_agents"] = sub_agents
        elif op == "update_instructions":
            append = str(obj.get("instructions_append") or "").strip()
            if append:
                root = _root_agent(next_model)
                root["instructions"] = f"{root.get('instructions', '').strip()}\n\nRefinement: {append}".strip()
    return next_model


def build_model_diff(
    before: dict[str, Any],
    after: dict[str, Any],
    operations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Summarize canonical changes for Activity / Diff."""
    diff: list[dict[str, Any]] = []
    for key in ("agents", "tools", "callbacks", "guardrails", "eval_suites"):
        before_count = len(before.get(key, []))
        after_count = len(after.get(key, []))
        if before_count != after_count:
            diff.append({"field": key, "before": before_count, "after": after_count})
    for operation in operations:
        diff.append(
            {
                "field": str(operation.get("target") or operation.get("operation") or "model"),
                "before": None,
                "after": _operation_label(operation),
            }
        )
    return diff


def compile_workbench_exports(model: dict[str, Any]) -> dict[str, Any]:
    """Compile ADK and CX export previews from the canonical model."""
    generated_config = canonical_to_generated_config(model)
    return {
        "generated_config": generated_config,
        "adk": {
            "target": "adk",
            "label": "Google ADK export preview",
            "files": {
                "agent.py": render_adk_agent_py(model),
                "tools.py": render_adk_tools_py(model),
                "agentlab.yaml": yaml.safe_dump(generated_config, sort_keys=False),
            },
        },
        "cx": {
            "target": "cx",
            "label": "CX Agent Studio export preview",
            "files": {
                "agent.json": json.dumps(render_cx_agent_json(model), indent=2, sort_keys=True),
                "playbook.yaml": yaml.safe_dump(render_cx_playbook(model), sort_keys=False),
            },
        },
    }


def canonical_to_generated_config(model: dict[str, Any]) -> dict[str, Any]:
    """Project canonical Workbench state into the existing Build config contract."""
    root = _root_agent(model)
    tools = [
        {
            "name": tool.get("name"),
            "description": tool.get("description", ""),
            "parameters": list(tool.get("parameters", [])),
            "tool_type": tool.get("type", "function_tool"),
        }
        for tool in model.get("tools", [])
    ]
    return {
        "model": root.get("model", "gpt-5.4-mini"),
        "system_prompt": root.get("instructions", ""),
        "tools": tools,
        "routing_rules": [
            {
                "condition": f"Request fits {agent.get('name')}",
                "action": f"route_to_{_slugify(str(agent.get('name') or 'agent'))}",
                "priority": index + 1,
            }
            for index, agent in enumerate(model.get("agents", []))
        ],
        "policies": [
            {
                "name": guardrail.get("name"),
                "description": guardrail.get("rule", ""),
                "enforcement": "strict",
            }
            for guardrail in model.get("guardrails", [])
        ],
        "eval_criteria": [
            {
                "name": suite.get("name"),
                "description": f"{len(suite.get('cases', []))} cases from Workbench canonical eval suite.",
                "weight": 1.0,
            }
            for suite in model.get("eval_suites", [])
        ],
        "metadata": {
            "agent_name": root.get("name", "Workbench Agent"),
            "created_from": "agent_builder_workbench",
            "canonical_version": 1,
        },
    }


def render_adk_agent_py(model: dict[str, Any]) -> str:
    """Render a copyable ADK source preview from the canonical model."""
    root = _root_agent(model)
    tool_names = [str(tool.get("name")) for tool in model.get("tools", []) if tool.get("name")]
    tools_expr = "[" + ", ".join(tool_names) + "]" if tool_names else "[]"
    return (
        "from google.adk.agents import Agent\n"
        "from .tools import *\n\n"
        "root_agent = Agent(\n"
        f"    name={root.get('name', 'Workbench Agent')!r},\n"
        f"    model={root.get('model', 'gpt-5.4-mini')!r},\n"
        f"    instruction={root.get('instructions', '')!r},\n"
        f"    tools={tools_expr},\n"
        ")\n"
    )


def render_adk_tools_py(model: dict[str, Any]) -> str:
    """Render ADK tool stubs from canonical tool records."""
    lines = [
        '"""Generated Workbench tool stubs."""',
        "",
    ]
    for tool in model.get("tools", []):
        name = _slugify(str(tool.get("name") or "custom_tool"))
        description = str(tool.get("description") or "Generated Workbench tool.")
        lines.extend(
            [
                f"def {name}(query: str) -> dict:",
                f"    \"\"\"{description}\"\"\"",
                f"    return {{\"tool\": {name!r}, \"query\": query, \"status\": \"preview_only\"}}",
                "",
            ]
        )
    if len(lines) == 2:
        lines.extend(["# No tools configured yet.", ""])
    return "\n".join(lines)


def render_cx_agent_json(model: dict[str, Any]) -> dict[str, Any]:
    """Render a representative CX Agent Studio JSON preview."""
    root = _root_agent(model)
    return {
        "displayName": root.get("name", "Workbench Agent"),
        "description": model.get("project", {}).get("description", ""),
        "defaultLanguageCode": "en",
        "generativeSettings": {
            "llmModelSettings": {"model": root.get("model", "gpt-5.4-mini")},
            "safetySettings": [guardrail.get("rule", "") for guardrail in model.get("guardrails", [])],
        },
        "tools": [
            {
                "displayName": tool.get("name"),
                "toolType": tool.get("type", "function_tool"),
                "description": tool.get("description", ""),
            }
            for tool in model.get("tools", [])
        ],
    }


def render_cx_playbook(model: dict[str, Any]) -> dict[str, Any]:
    """Render a CX playbook-shaped YAML preview from canonical state."""
    root = _root_agent(model)
    return {
        "display_name": root.get("name", "Workbench Agent"),
        "goal": root.get("role", ""),
        "instructions": [line for line in str(root.get("instructions", "")).splitlines() if line.strip()],
        "tools": [tool.get("name") for tool in model.get("tools", [])],
        "callbacks": [callback.get("name") for callback in model.get("callbacks", [])],
        "guardrails": [guardrail.get("name") for guardrail in model.get("guardrails", [])],
        "examples": [
            case
            for suite in model.get("eval_suites", [])
            for case in suite.get("cases", [])
        ],
    }


def build_compatibility_diagnostics(model: dict[str, Any], *, target: str) -> list[dict[str, Any]]:
    """Label canonical objects as portable, ADK-only, CX-only, or invalid for target."""
    diagnostics: list[dict[str, Any]] = []
    for agent in model.get("agents", []):
        diagnostics.append(
            {
                "object_id": agent.get("id", "agent"),
                "label": agent.get("name", "Agent"),
                "target": target,
                "status": "portable",
                "reason": "LLM agents can be represented in ADK and CX playbooks.",
            }
        )
    for tool in model.get("tools", []):
        diagnostics.append(compatibility_status_for_object(tool, target=target))
    for callback in model.get("callbacks", []):
        diagnostics.append(
            {
                "object_id": callback.get("id", "callback"),
                "label": callback.get("name", "Callback"),
                "target": target,
                "status": "portable",
                "reason": "Callbacks map to ADK callback hooks and CX generator processors.",
            }
        )
    for guardrail in model.get("guardrails", []):
        diagnostics.append(
            {
                "object_id": guardrail.get("id", "guardrail"),
                "label": guardrail.get("name", "Guardrail"),
                "target": target,
                "status": "portable",
                "reason": "Guardrails map to ADK policies and CX safety settings.",
            }
        )
    for suite in model.get("eval_suites", []):
        diagnostics.append(
            {
                "object_id": suite.get("id", "eval_suite"),
                "label": suite.get("name", "Eval suite"),
                "target": target,
                "status": "portable",
                "reason": "Eval cases can run in AgentLab and export as CX examples when needed.",
            }
        )
    return diagnostics


def compatibility_status_for_object(obj: dict[str, Any], *, target: str) -> dict[str, Any]:
    """Classify one canonical object for the selected target."""
    label = str(obj.get("name") or obj.get("id") or "object")
    object_id = str(obj.get("id") or label)
    tool_type = str(obj.get("type") or "function_tool")
    if tool_type == "local_shell":
        status = "invalid" if target == "cx" else "adk-only"
        reason = "Local shell tools are ADK-only and not exportable to CX Agent Studio."
    elif tool_type == "cx_widget":
        status = "cx-only" if target != "adk" else "invalid"
        reason = "CX widget tools are CX-only and have no ADK runtime equivalent."
    else:
        status = "portable"
        reason = "Function tools export to ADK and CX."
    return {
        "object_id": object_id,
        "label": label,
        "target": target,
        "status": status,
        "reason": reason,
    }


def run_workbench_validation(project: dict[str, Any], *, sample_message: str = "") -> dict[str, Any]:
    """Run deterministic post-change validation for Workbench MVP safety."""
    model = project.get("model", {})
    compatibility = project.get("compatibility") or build_compatibility_diagnostics(
        model,
        target=str(project.get("target") or "portable"),
    )
    invalid = [item for item in compatibility if item.get("status") == "invalid"]
    checks = [
        {
            "name": "canonical_model_present",
            "passed": bool(model.get("agents")),
            "detail": "Canonical model has at least one agent.",
        },
        {
            "name": "exports_compile",
            "passed": bool(project.get("exports", {}).get("adk", {}).get("files", {}).get("agent.py"))
            and bool(project.get("exports", {}).get("cx", {}).get("files", {}).get("agent.json")),
            "detail": "ADK and CX export previews rendered from canonical state.",
        },
        {
            "name": "target_compatibility",
            "passed": not invalid,
            "detail": "No invalid objects for selected target." if not invalid else f"{len(invalid)} invalid objects for target.",
        },
    ]
    if sample_message.strip():
        checks.append(
            {
                "name": "sample_message_recorded",
                "passed": True,
                "detail": sample_message.strip(),
            }
        )
    return {
        "run_id": f"workbench-test-{new_id()}",
        "status": "passed" if all(check["passed"] for check in checks) else "failed",
        "created_at": _now_iso(),
        "checks": checks,
        "trace": [
            {"event": "load_canonical_model", "status": "passed"},
            {"event": "compile_exports", "status": "passed"},
            {"event": "validate_target", "status": "passed" if not invalid else "failed"},
        ],
    }


def prepare_project_payload(project: dict[str, Any]) -> dict[str, Any]:
    """Strip internal plan snapshots while keeping user-facing version history."""
    prepared = copy.deepcopy(project)
    prepared["exports"] = compile_workbench_exports(prepared["model"])
    prepared["compatibility"] = build_compatibility_diagnostics(
        prepared["model"],
        target=str(prepared.get("target") or "portable"),
    )
    prepared["versions"] = [
        {key: value for key, value in version.items() if key != "model"}
        for version in prepared.get("versions", [])
    ]
    active_run_id = prepared.get("active_run_id")
    runs = prepared.get("runs") if isinstance(prepared.get("runs"), dict) else {}
    prepared["active_run"] = runs.get(active_run_id) if isinstance(active_run_id, str) else None
    prepared.pop("plans", None)
    return prepared


def _root_agent(model: dict[str, Any]) -> dict[str, Any]:
    """Return the root agent record, creating a safe fallback when absent."""
    agents = model.setdefault("agents", [])
    for agent in agents:
        if agent.get("id") == "root":
            return agent
    fallback = {
        "id": "root",
        "name": "Workbench Agent",
        "role": "Handle user requests safely.",
        "model": "gpt-5.4-mini",
        "instructions": "Help the user safely and clearly.",
        "sub_agents": [],
    }
    agents.insert(0, fallback)
    return fallback


def _model_counts(model: dict[str, Any]) -> dict[str, int]:
    """Return compact model counts for rollback diff summaries."""
    return {
        "agents": len(model.get("agents", [])),
        "tools": len(model.get("tools", [])),
        "callbacks": len(model.get("callbacks", [])),
        "guardrails": len(model.get("guardrails", [])),
        "eval_suites": len(model.get("eval_suites", [])),
    }
