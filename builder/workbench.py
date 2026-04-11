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
        auto_iterate: bool = True,
        max_iterations: int = 3,
    ) -> Any:
        """Drive a multi-turn streaming build run, yielding events the UI consumes.

        Returns an async iterator of ``{"event": str, "data": dict}`` events.

        Multi-turn semantics:
            * Each call represents ONE user turn (initial build or follow-up).
            * Conversation history + prior turns persist on the project so the
              agent can generate delta plans that build on earlier work.
            * Artifacts and plans from previous turns are preserved (the store
              keeps them under ``project["turns"]``) and only the *latest* turn
              is mirrored in ``project["plan"]``.
            * When ``auto_iterate`` is set and validation flags problems after
              a turn, the service autonomously drives additional corrective
              iterations (bounded by ``max_iterations``) — that's what turns
              the Workbench into a Claude-Code/Manus-style agent loop.
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
        project.setdefault("conversation", [])
        project.setdefault("turns", [])
        project["build_status"] = "running"
        project["last_brief"] = brief
        project["target"] = target

        # --- turn bookkeeping ------------------------------------------------
        # A "turn" is everything the agent does in response to one user
        # message. Its plan, artifacts, validation result and iteration log
        # all hang off the same record so the UI and downstream analytics can
        # trace every iteration back to the message that produced it.
        prior_turns = list(project.get("turns") or [])
        prior_turn_count = len(prior_turns)
        is_initial_turn = prior_turn_count == 0
        turn_id = f"turn-{new_id()}"
        now = _now_iso()
        user_message = {
            "id": f"msg-{new_id()}",
            "role": "user",
            "content": brief,
            "turn_id": turn_id,
            "created_at": now,
        }
        project.setdefault("conversation", []).append(user_message)
        turn_record: dict[str, Any] = {
            "turn_id": turn_id,
            "brief": brief,
            "mode": "initial" if is_initial_turn else "follow_up",
            "status": "running",
            "created_at": now,
            "plan": None,
            "artifact_ids": [],
            "operations": [],
            "iterations": [],
            "validation": None,
        }
        prior_turns.append(turn_record)
        project["turns"] = prior_turns
        self.store.save_project(project)

        # Build a compact conversation history so the agent's planner can
        # reason about prior turns without seeing the entire artifact blob.
        conversation_history = _compact_conversation(project.get("conversation", []))
        prior_turn_summary = _summarize_prior_turns(prior_turns[:-1])

        service = self

        async def _run_one_pass(
            iteration_index: int,
            pass_brief: str,
            pass_mode: str,
        ) -> Any:
            """Run one agent pass (one plan-tree execution) and persist events.

            Writes the iteration result back to ``turn_record["iterations"][-1]``
            before returning so the outer loop can read ``operations`` and
            ``status`` off the record.
            """
            nonlocal project
            iteration_id = f"iter-{new_id()}"
            iteration_record = {
                "iteration_id": iteration_id,
                "index": iteration_index,
                "mode": pass_mode,
                "brief": pass_brief,
                "status": "running",
                "operations": [],
                "created_at": _now_iso(),
            }
            turn_record["iterations"].append(iteration_record)
            project["turns"] = prior_turns
            service.store.save_project(project)

            yield {
                "event": "iteration.started",
                "data": {
                    "turn_id": turn_id,
                    "iteration_id": iteration_id,
                    "index": iteration_index,
                    "mode": pass_mode,
                },
            }

            request = BuildRequest(
                project_id=project["project_id"],
                brief=pass_brief,
                target=target,
                environment=environment,
                mode=pass_mode,
                conversation_history=conversation_history,
                prior_turn_summary=prior_turn_summary,
                current_model_summary=_model_summary(project["model"]),
            )

            plan_root: PlanTask | None = None
            operations_in_pass: list[dict[str, Any]] = []
            pass_status = "completed"

            async for event in runner.run(request, project):
                event_name = str(event.get("event") or "")
                data = event.get("data") or {}
                data = dict(data)
                data.setdefault("turn_id", turn_id)
                data.setdefault("iteration_id", iteration_id)

                if event_name == "plan.ready":
                    plan_root = PlanTask.from_dict(data["plan"])
                    turn_record["plan"] = plan_root.to_dict()
                    project["plan"] = plan_root.to_dict()
                    iteration_record["plan"] = plan_root.to_dict()
                    service.store.save_project(project)

                elif event_name == "task.started" and plan_root is not None:
                    task = find_task(plan_root, str(data.get("task_id") or ""))
                    if task is not None:
                        task.status = PlanTaskStatus.RUNNING.value
                        task.started_at = _now_iso()
                        recompute_parent_status(plan_root)
                        turn_record["plan"] = plan_root.to_dict()
                        project["plan"] = plan_root.to_dict()
                        service.store.save_project(project)

                elif event_name == "task.progress" and plan_root is not None:
                    task = find_task(plan_root, str(data.get("task_id") or ""))
                    note = str(data.get("note") or "")
                    if task is not None and note:
                        task.log.append(note)
                        turn_record["plan"] = plan_root.to_dict()
                        project["plan"] = plan_root.to_dict()
                        service.store.save_project(project)

                elif event_name == "artifact.updated" and plan_root is not None:
                    artifact_payload = data.get("artifact") or {}
                    artifact = WorkbenchArtifact.from_dict(artifact_payload)
                    # Stamp each artifact with the turn so the UI can group it.
                    artifact_dict = artifact.to_dict()
                    artifact_dict["turn_id"] = turn_id
                    artifact_dict["iteration_id"] = iteration_id
                    artifacts = list(project.get("artifacts", []))
                    artifacts = [a for a in artifacts if a.get("id") != artifact.id]
                    artifacts.append(artifact_dict)
                    project["artifacts"] = artifacts
                    if artifact.id not in turn_record["artifact_ids"]:
                        turn_record["artifact_ids"].append(artifact.id)
                    task = find_task(plan_root, artifact.task_id)
                    if task is not None and artifact.id not in task.artifact_ids:
                        task.artifact_ids.append(artifact.id)
                        turn_record["plan"] = plan_root.to_dict()
                        project["plan"] = plan_root.to_dict()
                    service.store.save_project(project)
                    # Re-emit the enriched artifact so the UI receives the
                    # turn/iteration metadata alongside the original payload.
                    data["artifact"] = artifact_dict

                elif event_name == "task.completed" and plan_root is not None:
                    task = find_task(plan_root, str(data.get("task_id") or ""))
                    if task is not None:
                        task.status = PlanTaskStatus.DONE.value
                        task.completed_at = _now_iso()
                        recompute_parent_status(plan_root)
                        turn_record["plan"] = plan_root.to_dict()
                        project["plan"] = plan_root.to_dict()
                    operations = list(data.get("operations") or [])
                    if operations:
                        operations_in_pass.extend(operations)
                        project["model"] = apply_operations(project["model"], operations)
                        project["compatibility"] = build_compatibility_diagnostics(
                            project["model"],
                            target=str(project.get("target") or "portable"),
                        )
                        project["exports"] = compile_workbench_exports(project["model"])
                    service.store.save_project(project)

                elif event_name == "message.delta":
                    # Capture assistant narration as a conversation message so
                    # the history survives reloads. Buffer per (turn, task)
                    # tuple by merging onto the most recent assistant message.
                    text_chunk = str(data.get("text") or "")
                    if text_chunk:
                        _append_assistant_chunk(
                            project,
                            turn_id=turn_id,
                            task_id=str(data.get("task_id") or ""),
                            chunk=text_chunk,
                        )
                        service.store.save_project(project)

                elif event_name == "build.completed":
                    pass_status = "completed"

                elif event_name == "error":
                    pass_status = "error"
                    project["build_status"] = "error"
                    service.store.save_project(project)

                data.setdefault("project_id", project["project_id"])
                yield {"event": event_name, "data": data}

            iteration_record["status"] = pass_status
            iteration_record["operations"] = list(operations_in_pass)
            iteration_record["completed_at"] = _now_iso()
            project["turns"] = prior_turns
            service.store.save_project(project)

        async def _stream() -> Any:
            nonlocal project
            # Emit a turn.started event so the UI can group subsequent events.
            yield {
                "event": "turn.started",
                "data": {
                    "turn_id": turn_id,
                    "mode": turn_record["mode"],
                    "brief": brief,
                    "project_id": project["project_id"],
                    "message_id": user_message["id"],
                },
            }
            total_operations: list[dict[str, Any]] = []
            current_brief = brief
            current_mode = turn_record["mode"]
            iterations_to_run = max(1, int(max_iterations or 1))
            final_status = "completed"

            for iteration_index in range(iterations_to_run):
                # ``_run_one_pass`` is an async generator; it writes its
                # result into ``turn_record["iterations"][-1]`` before
                # finishing, so we read back from there once it's exhausted.
                async for event in _run_one_pass(
                    iteration_index, current_brief, current_mode
                ):
                    yield event

                latest_iter = turn_record["iterations"][-1]
                pass_ops = list(latest_iter.get("operations") or [])
                total_operations.extend(pass_ops)
                if latest_iter.get("status") == "error":
                    final_status = "error"
                    break

                # Run deterministic validation so we can decide whether to
                # autonomously iterate again.
                validation = run_workbench_validation(project)
                project["last_test"] = validation
                turn_record["validation"] = validation
                self.store.save_project(project)

                yield {
                    "event": "validation.ready",
                    "data": {
                        "turn_id": turn_id,
                        "iteration_id": turn_record["iterations"][-1]["iteration_id"],
                        "status": validation.get("status"),
                        "checks": validation.get("checks", []),
                        "project_id": project["project_id"],
                    },
                }

                should_iterate = (
                    auto_iterate
                    and validation.get("status") != "passed"
                    and iteration_index + 1 < iterations_to_run
                )
                if not should_iterate:
                    break

                # Frame the next pass as a self-directed correction and tell
                # the agent to produce the smallest plan that fixes the gaps.
                failed_checks = [c for c in validation.get("checks", []) if not c.get("passed")]
                correction_notes = "; ".join(
                    str(c.get("detail") or c.get("name") or "") for c in failed_checks
                ) or "Validation flagged issues in the current canonical model."
                current_brief = (
                    "Autonomous correction pass. The previous plan left validation "
                    f"issues: {correction_notes}. Produce a minimal delta plan that "
                    "resolves them without rewriting the agent from scratch."
                )
                current_mode = "correction"
                # Feed the agent a refreshed snapshot of its own state.
                nonlocal_conversation = _compact_conversation(project.get("conversation", []))
                # Update the closed-over variables _run_one_pass reads.
                conversation_history.clear()
                conversation_history.extend(nonlocal_conversation)
                # Also update the model summary for the correction pass.
                prior_turn_summary.clear()
                prior_turn_summary.extend(_summarize_prior_turns(prior_turns[:-1]))

            # --- finalize turn ------------------------------------------------
            if total_operations and final_status != "error":
                project["version"] = int(project.get("version") or 1) + 1
                project["draft_badge"] = f"Draft v{project['version']}"
                self._add_version(
                    project,
                    summary=f"Turn {prior_turn_count + 1}: {len(total_operations)} change(s)",
                )
                before_model = (
                    project["versions"][-2]["model"]
                    if len(project.get("versions", [])) >= 2
                    else project["model"]
                )
                self._add_activity(
                    project,
                    kind="build",
                    summary=brief.strip()[:120] or "Built agent from brief.",
                    diff=build_model_diff(before_model, project["model"], total_operations),
                )

            turn_record["status"] = final_status
            turn_record["operations"] = total_operations
            turn_record["completed_at"] = _now_iso()
            project["turns"] = prior_turns
            project["build_status"] = "idle" if final_status != "error" else "error"

            # Push an assistant "done" bubble into the conversation so
            # reloading the page rehydrates the running log.
            closing_text = (
                f"Completed turn with {len(total_operations)} change(s)."
                if total_operations
                else "Turn completed without canonical changes."
            )
            project["conversation"].append(
                {
                    "id": f"msg-{new_id()}",
                    "role": "assistant",
                    "content": closing_text,
                    "turn_id": turn_id,
                    "created_at": _now_iso(),
                    "kind": "turn_summary",
                }
            )
            self.store.save_project(project)

            yield {
                "event": "turn.completed",
                "data": {
                    "turn_id": turn_id,
                    "status": final_status,
                    "operations": total_operations,
                    "version": project["version"],
                    "project_id": project["project_id"],
                    "iterations": len(turn_record["iterations"]),
                },
            }

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
            # Multi-turn state needed to rehydrate a live Workbench session.
            "conversation": list(project.get("conversation", [])),
            "turns": copy.deepcopy(project.get("turns") or []),
            "last_test": project.get("last_test"),
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
