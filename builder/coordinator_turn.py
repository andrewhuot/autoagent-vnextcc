"""Shared coordinator turn service for CLI and API entry points."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from builder.coordinator_runtime import CoordinatorWorkerRuntime
from builder.events import EventBroker
from builder.orchestrator import BuilderOrchestrator
from builder.store import BuilderStore
from builder.types import (
    BuilderProject,
    BuilderSession,
    BuilderTask,
    CoordinatorExecutionStatus,
    SpecialistRole,
    now_ts,
)


@dataclass(frozen=True)
class CoordinatorTurnResult:
    """Serializable result for one user turn through the coordinator."""

    message: str
    command_intent: str
    project_id: str
    session_id: str
    task_id: str
    plan_id: str
    run_id: str
    status: str
    transcript_lines: tuple[str, ...]
    worker_roles: tuple[str, ...] = ()
    active_tasks: int = 0
    next_actions: tuple[str, ...] = ()
    review_cards: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class CoordinatorTurnService:
    """Create a coordinator plan and execution run for a natural-language turn."""

    def __init__(
        self,
        *,
        store: BuilderStore,
        orchestrator: BuilderOrchestrator,
        events: EventBroker,
        runtime: CoordinatorWorkerRuntime | None = None,
    ) -> None:
        self._store = store
        self._orchestrator = orchestrator
        self._events = events
        self._runtime = runtime or CoordinatorWorkerRuntime(
            store=store,
            orchestrator=orchestrator,
            events=events,
        )

    def process_turn(
        self,
        message: str,
        *,
        project_id: str | None = None,
        session_id: str | None = None,
        command_intent: str | None = None,
        permission_mode: str | None = None,
        dry_run: bool = False,
    ) -> CoordinatorTurnResult:
        """Plan and (when ``dry_run`` is false) execute one coordinator turn.

        ``dry_run=True`` stops after the plan is persisted: the returned
        :class:`CoordinatorTurnResult` has ``status="planned"``, no ``run_id``,
        and a transcript describing the intended worker roster. This is the
        foundation for plan-mode gating where the operator approves a plan
        before workers act.
        """
        cleaned = " ".join(str(message or "").split())
        if not cleaned:
            raise ValueError("Coordinator turn message cannot be empty")
        intent = command_intent or detect_command_intent(cleaned)
        project = self._get_or_create_project(project_id=project_id, message=cleaned)
        session = self._get_or_create_session(
            session_id=session_id,
            project=project,
            intent=intent,
        )
        self._orchestrator.start_session(session)
        task = self._create_task(
            project=project,
            session=session,
            message=cleaned,
            intent=intent,
            permission_mode=permission_mode,
        )
        requested_roles = roles_for_intent(intent, cleaned)
        plan = self._orchestrator.plan_work(
            task=task,
            goal=cleaned,
            requested_roles=requested_roles,
            materialize_tasks=True,
            extra_context={
                "command_intent": intent,
                "permission_mode": permission_mode or "default",
                "workbench_surface": "cli",
                "dry_run": dry_run,
            },
        )
        if dry_run:
            return self._build_planned_result(
                plan=plan,
                task=task,
                project=project,
                session=session,
                intent=intent,
                message=cleaned,
            )
        run = self._runtime.execute_plan(
            task_id=task.task_id,
            plan_id=str(plan["plan_id"]),
        )
        task = self._store.get_task(task.task_id) or task
        transcript_lines = tuple(self._render_transcript_lines(plan=plan, run=run))
        next_actions = tuple(self._next_actions(run_status=run.status, intent=intent))
        review_cards = tuple(self._review_cards(run))
        return CoordinatorTurnResult(
            message=cleaned,
            command_intent=intent,
            project_id=project.project_id,
            session_id=session.session_id,
            task_id=task.task_id,
            plan_id=str(plan["plan_id"]),
            run_id=run.run_id,
            status=run.status.value,
            transcript_lines=transcript_lines,
            worker_roles=tuple(state.worker_role.value for state in run.worker_states),
            active_tasks=0 if run.status in {
                CoordinatorExecutionStatus.COMPLETED,
                CoordinatorExecutionStatus.FAILED,
                CoordinatorExecutionStatus.BLOCKED,
            } else len(run.worker_states),
            next_actions=next_actions,
            review_cards=review_cards,
            metadata={
                "coordinator_synthesis": dict(run.coordinator_synthesis),
                "worker_count": len(run.worker_states),
                "materialized_task_ids": [
                    str(item.get("materialized_task_id"))
                    for item in plan.get("tasks", [])
                    if isinstance(item, dict) and item.get("materialized_task_id")
                ],
            },
        )

    def _build_planned_result(
        self,
        *,
        plan: dict[str, Any],
        task: BuilderTask,
        project: BuilderProject,
        session: BuilderSession,
        intent: str,
        message: str,
    ) -> CoordinatorTurnResult:
        """Assemble a :class:`CoordinatorTurnResult` for a dry-run plan."""
        worker_roles = tuple(
            str(node.get("worker_role"))
            for node in plan.get("tasks", [])
            if isinstance(node, dict)
            and node.get("worker_role")
            and node.get("worker_role") != SpecialistRole.ORCHESTRATOR.value
        )
        plan_lines: list[str] = [
            f"  Coordinator plan {plan['plan_id']} ready — {len(worker_roles)} worker"
            f"{'' if len(worker_roles) == 1 else 's'} queued.",
        ]
        for node in plan.get("tasks", []):
            if not isinstance(node, dict):
                continue
            role_value = node.get("worker_role")
            if not role_value or role_value == SpecialistRole.ORCHESTRATOR.value:
                continue
            title = str(node.get("title") or role_value)
            reason = str(node.get("routing_reason") or "").strip()
            suffix = f" — {reason}" if reason else ""
            plan_lines.append(f"  • {role_value.replace('_', ' ')}: {title}{suffix}")
        plan_lines.append("  Approve with y to execute, n to abort, or edit to refine.")
        return CoordinatorTurnResult(
            message=message,
            command_intent=intent,
            project_id=project.project_id,
            session_id=session.session_id,
            task_id=task.task_id,
            plan_id=str(plan["plan_id"]),
            run_id="",
            status="planned",
            transcript_lines=tuple(plan_lines),
            worker_roles=worker_roles,
            active_tasks=0,
            next_actions=(
                "Reply y to run the plan as-is.",
                "Reply n to abort; nothing will be written.",
                "Reply edit: <annotation> to refine the goal and re-plan.",
            ),
            review_cards=(),
            metadata={
                "dry_run": True,
                "worker_count": len(worker_roles),
            },
        )

    def _get_or_create_project(
        self,
        *,
        project_id: str | None,
        message: str,
    ) -> BuilderProject:
        """Return the requested project or create a CLI builder project."""
        if project_id:
            project = self._store.get_project(project_id)
            if project is not None:
                return project
        latest = self._store.list_projects(archived=False, limit=1)
        if latest and project_id is None:
            return latest[0]
        project = BuilderProject(
            name=_project_name(message),
            description="AgentLab Workbench coordinator project.",
        )
        self._store.save_project(project)
        return project

    def _get_or_create_session(
        self,
        *,
        session_id: str | None,
        project: BuilderProject,
        intent: str,
    ) -> BuilderSession:
        """Return the active builder session or create one for this intent."""
        if session_id:
            session = self._store.get_session(session_id)
            if session is not None:
                return session
        sessions = self._store.list_sessions(project_id=project.project_id, status="open", limit=1)
        if sessions and session_id is None:
            return sessions[0]
        session = BuilderSession(
            project_id=project.project_id,
            title=f"Workbench {intent}",
        )
        self._store.save_session(session)
        return session

    def _create_task(
        self,
        *,
        project: BuilderProject,
        session: BuilderSession,
        message: str,
        intent: str,
        permission_mode: str | None,
    ) -> BuilderTask:
        """Persist the root task for one coordinator turn."""
        task = BuilderTask(
            project_id=project.project_id,
            session_id=session.session_id,
            title=f"{intent.title()} agent",
            description=message,
            metadata={
                "command_intent": intent,
                "permission_mode": permission_mode or "default",
                "created_by": "workbench_coordinator_turn",
            },
        )
        self._store.save_task(task)
        session.task_ids.append(task.task_id)
        session.message_count += 1
        session.updated_at = now_ts()
        self._store.save_session(session)
        return task

    def _render_transcript_lines(self, *, plan: dict[str, Any], run: Any) -> list[str]:
        """Render the coordinator result for the terminal transcript."""
        worker_count = len(run.worker_states)
        lines = [
            f"  Coordinator plan {plan['plan_id']} created for {worker_count} worker"
            f"{'' if worker_count == 1 else 's'}.",
        ]
        for state in run.worker_states:
            status = state.status.value
            role = state.worker_role.value.replace("_", " ")
            summary = state.result.summary if state.result else state.blocker_reason or state.error or ""
            suffix = f" — {summary}" if summary else ""
            lines.append(f"  • {role}: {status}{suffix}")
        synthesis = run.coordinator_synthesis or {}
        if synthesis.get("next_step"):
            lines.append(f"  Next: {synthesis['next_step']}")
        return lines

    def _next_actions(
        self,
        *,
        run_status: CoordinatorExecutionStatus,
        intent: str,
    ) -> list[str]:
        """Return action hints for the operator after a turn."""
        if run_status == CoordinatorExecutionStatus.FAILED:
            return ["/tasks to inspect the failed worker, then retry the turn."]
        if run_status == CoordinatorExecutionStatus.BLOCKED:
            return ["/tasks to inspect blockers before continuing."]
        if intent == "build":
            return ["/eval to test the candidate", "/save to materialize approved changes"]
        if intent == "eval":
            return ["/optimize to improve from loss patterns"]
        if intent == "optimize":
            return ["/review to inspect optimization cards", "/deploy for a canary gate"]
        if intent == "deploy":
            return ["/deploy --approve after reviewing canary and rollback evidence"]
        if intent == "skills":
            return ["/skills <request> to attach build-time skills after review"]
        return ["/tasks to inspect coordinator progress"]

    def _review_cards(self, run: Any) -> list[dict[str, Any]]:
        """Extract review-required worker outputs into lightweight cards."""
        cards: list[dict[str, Any]] = []
        for state in run.worker_states:
            result = state.result
            if result is None or not result.output_payload.get("review_required"):
                continue
            cards.append(
                {
                    "node_id": state.node_id,
                    "worker_role": state.worker_role.value,
                    "summary": result.summary,
                    "artifacts": sorted(result.artifacts),
                }
            )
        return cards


def detect_command_intent(message: str) -> str:
    """Infer the slash-command workflow that should own a free-text turn."""
    text = message.lower()
    if any(word in text for word in ("deploy", "release", "ship", "canary")):
        return "deploy"
    if any(word in text for word in ("optimize", "improve", "tune", "loss pattern")):
        return "optimize"
    if any(word in text for word in ("eval", "evaluate", "benchmark", "test it")):
        return "eval"
    if any(word in text for word in ("skill", "skills")):
        return "skills"
    if any(word in text for word in ("build", "agent", "create", "make")):
        return "build"
    return "build"


def roles_for_intent(intent: str, message: str) -> list[SpecialistRole]:
    """Return the deterministic specialist set for a Workbench workflow."""
    text = message.lower()
    role_map: dict[str, list[SpecialistRole]] = {
        "build": [
            SpecialistRole.REQUIREMENTS_ANALYST,
            SpecialistRole.BUILD_ENGINEER,
            SpecialistRole.PROMPT_ENGINEER,
            SpecialistRole.ADK_ARCHITECT,
            SpecialistRole.EVAL_AUTHOR,
        ],
        "eval": [
            SpecialistRole.EVAL_AUTHOR,
            SpecialistRole.EVAL_RUNNER,
            SpecialistRole.LOSS_ANALYST,
            SpecialistRole.TRACE_ANALYST,
        ],
        "optimize": [
            SpecialistRole.TRACE_ANALYST,
            SpecialistRole.OPTIMIZATION_ENGINEER,
            SpecialistRole.INSTRUCTION_OPTIMIZER,
            SpecialistRole.GUARDRAIL_OPTIMIZER,
            SpecialistRole.CALLBACK_OPTIMIZER,
            SpecialistRole.EVAL_AUTHOR,
        ],
        "deploy": [
            SpecialistRole.DEPLOYMENT_ENGINEER,
            SpecialistRole.RELEASE_MANAGER,
        ],
        "skills": [
            SpecialistRole.SKILL_AUTHOR,
            SpecialistRole.BUILD_ENGINEER,
        ],
    }
    roles = list(role_map.get(intent, role_map["build"]))
    if "tool" in text and SpecialistRole.TOOL_ENGINEER not in roles:
        roles.append(SpecialistRole.TOOL_ENGINEER)
    if "guardrail" in text and SpecialistRole.GUARDRAIL_AUTHOR not in roles:
        roles.append(SpecialistRole.GUARDRAIL_AUTHOR)
    if "callback" in text and SpecialistRole.TOOL_ENGINEER not in roles:
        roles.append(SpecialistRole.TOOL_ENGINEER)
    return roles


def _project_name(message: str) -> str:
    """Create a short project name from the first user request."""
    words = [word.strip(".,:;!?") for word in message.split() if word.strip(".,:;!?")]
    title = " ".join(words[:6]).strip()
    return title or "AgentLab Workbench Project"


__all__ = [
    "CoordinatorTurnResult",
    "CoordinatorTurnService",
    "detect_command_intent",
    "roles_for_intent",
]
