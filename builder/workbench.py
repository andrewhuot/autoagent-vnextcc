"""Canonical Agent Builder Workbench model, planner, compiler, and store."""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from builder.types import new_id


WorkbenchTarget = str


def _now_iso() -> str:
    """Return a stable UTC timestamp for version and activity records."""
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


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
            "model": model,
            "compatibility": build_compatibility_diagnostics(model, target=target),
            "exports": compile_workbench_exports(model),
            "last_test": None,
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
        except json.JSONDecodeError:
            return {"projects": {}}
        if not isinstance(payload, dict):
            return {"projects": {}}
        projects = payload.get("projects")
        if not isinstance(projects, dict):
            payload["projects"] = {}
        return payload

    def _write(self, payload: dict[str, Any]) -> None:
        """Write the full store atomically enough for local MVP usage."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


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
    ) -> Any:
        """Drive a streaming build run, yielding events the UI can consume.

        Returns an async iterator of ``{"event": str, "data": dict}`` events.
        Ensures a project exists (creating one from ``brief`` if needed),
        invokes the builder agent, applies ``operations`` emitted by each
        completed task to the canonical model, and persists plan+artifacts
        on every event. Safe to call with ``project_id=None`` for a brand-new
        build.
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
                project = self._require_project(project_id)
            except KeyError:
                project = self.store.create_project(
                    brief=brief, target=target, environment=environment
                )
        else:
            project = self.store.create_project(
                brief=brief, target=target, environment=environment
            )
        project.setdefault("plan", None)
        project.setdefault("artifacts", [])
        project.setdefault("build_status", "running")
        project["build_status"] = "running"
        project["last_brief"] = brief
        self.store.save_project(project)

        plan_root: PlanTask | None = None
        request = BuildRequest(
            project_id=project["project_id"],
            brief=brief,
            target=target,
            environment=environment,
        )

        async def _stream() -> Any:
            nonlocal plan_root
            operations_for_version: list[dict[str, Any]] = []
            async for event in runner.run(request, project):
                event_name = str(event.get("event") or "")
                data = event.get("data") or {}

                if event_name == "plan.ready":
                    plan_root = PlanTask.from_dict(data["plan"])
                    project["plan"] = plan_root.to_dict()
                    project["artifacts"] = []
                    self.store.save_project(project)

                elif event_name == "task.started" and plan_root is not None:
                    task = find_task(plan_root, str(data.get("task_id") or ""))
                    if task is not None:
                        task.status = PlanTaskStatus.RUNNING.value
                        task.started_at = _now_iso()
                        recompute_parent_status(plan_root)
                        project["plan"] = plan_root.to_dict()
                        self.store.save_project(project)

                elif event_name == "task.progress" and plan_root is not None:
                    task = find_task(plan_root, str(data.get("task_id") or ""))
                    note = str(data.get("note") or "")
                    if task is not None and note:
                        task.log.append(note)
                        project["plan"] = plan_root.to_dict()
                        self.store.save_project(project)

                elif event_name == "artifact.updated" and plan_root is not None:
                    artifact_payload = data.get("artifact") or {}
                    artifact = WorkbenchArtifact.from_dict(artifact_payload)
                    artifacts = list(project.get("artifacts", []))
                    artifacts = [a for a in artifacts if a.get("id") != artifact.id]
                    artifacts.append(artifact.to_dict())
                    project["artifacts"] = artifacts
                    task = find_task(plan_root, artifact.task_id)
                    if task is not None and artifact.id not in task.artifact_ids:
                        task.artifact_ids.append(artifact.id)
                        project["plan"] = plan_root.to_dict()
                    self.store.save_project(project)

                elif event_name == "task.completed" and plan_root is not None:
                    task = find_task(plan_root, str(data.get("task_id") or ""))
                    if task is not None:
                        task.status = PlanTaskStatus.DONE.value
                        task.completed_at = _now_iso()
                        recompute_parent_status(plan_root)
                        project["plan"] = plan_root.to_dict()
                    operations = list(data.get("operations") or [])
                    if operations:
                        operations_for_version.extend(operations)
                        project["model"] = apply_operations(project["model"], operations)
                        project["compatibility"] = build_compatibility_diagnostics(
                            project["model"],
                            target=str(project.get("target") or "portable"),
                        )
                        project["exports"] = compile_workbench_exports(project["model"])
                    self.store.save_project(project)

                elif event_name == "build.completed":
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
                                project["versions"][-2]["model"]
                                if len(project.get("versions", [])) >= 2
                                else project["model"],
                                project["model"],
                                operations_for_version,
                            ),
                        )
                    project["build_status"] = "idle"
                    self.store.save_project(project)

                elif event_name == "error":
                    project["build_status"] = "error"
                    self.store.save_project(project)

                # Always enrich the event with the current project_id so the
                # frontend can correlate even when a build creates a new one.
                data.setdefault("project_id", project["project_id"])
                yield {"event": event_name, "data": data}

        return _stream()

    def get_plan_snapshot(self, *, project_id: str) -> dict[str, Any]:
        """Return the current plan + artifacts snapshot for page hydration."""
        project = self._require_project(project_id)
        return {
            "project_id": project["project_id"],
            "name": project.get("name"),
            "target": project.get("target"),
            "environment": project.get("environment"),
            "version": project.get("version"),
            "build_status": project.get("build_status", "idle"),
            "plan": project.get("plan"),
            "artifacts": list(project.get("artifacts", [])),
            "model": project.get("model"),
            "exports": project.get("exports"),
            "compatibility": project.get("compatibility"),
            "last_brief": project.get("last_brief"),
        }

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
