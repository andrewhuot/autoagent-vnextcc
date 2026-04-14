"""Workbench coordinator session facade.

The Workbench should have one explicit orchestration boundary. This module
owns the active Builder project/session/task ids, delegates planning to the
Builder orchestrator, executes plans through ``CoordinatorWorkerRuntime``,
and returns the same turn result shape used by CLI and API callers.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from builder.coordinator_runtime import CoordinatorWorkerRuntime
from builder.coordinator_turn import (
    CoordinatorTurnResult,
    detect_command_intent,
    roles_for_intent,
)
from builder.events import BuilderEvent, BuilderEventType, EventBroker
from builder.orchestrator import BuilderOrchestrator
from builder.store import BuilderStore
from builder.types import (
    BuilderProject,
    BuilderSession,
    BuilderTask,
    CoordinatorExecutionRun,
    CoordinatorExecutionStatus,
    SpecialistRole,
    now_ts,
)
from cli.workbench_app.coordinator_render import format_coordinator_event


class CoordinatorSession:
    """Own one Workbench coordinator session and its active plan/run state."""

    def __init__(
        self,
        *,
        store: BuilderStore,
        orchestrator: BuilderOrchestrator,
        events: EventBroker,
        runtime: CoordinatorWorkerRuntime | None = None,
        project_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self._store = store
        self._orchestrator = orchestrator
        self._events = events
        self._runtime = runtime or CoordinatorWorkerRuntime(
            store=store,
            orchestrator=orchestrator,
            events=events,
        )
        self.active_project_id = project_id
        self.active_session_id = session_id
        self.active_task_id: str | None = None
        self.active_plan_id: str | None = None
        self.latest_run_id: str | None = None
        self._latest_synthesis: dict[str, Any] = {}
        self._active_run_count = 0
        self._cancel_requested = False

    @property
    def active_run_count(self) -> int:
        """Return the number of coordinator executions currently active."""
        return self._active_run_count

    @property
    def worker_mode(self) -> Any:
        """Return the worker mode used by the underlying runtime."""
        return self._runtime.worker_mode

    def bind_context(
        self,
        *,
        project_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        """Adopt project/session ids from Workbench metadata when present."""
        if project_id:
            self.active_project_id = project_id
        if session_id:
            self.active_session_id = session_id

    def process_turn(
        self,
        message: str,
        *,
        project_id: str | None = None,
        session_id: str | None = None,
        command_intent: str | None = None,
        permission_mode: str | None = None,
        dry_run: bool = False,
        context: Mapping[str, Any] | None = None,
    ) -> CoordinatorTurnResult:
        """Plan and optionally execute one Workbench coordinator turn."""
        cleaned = " ".join(str(message or "").split())
        if not cleaned:
            raise ValueError("Coordinator turn message cannot be empty")
        intent = command_intent or detect_command_intent(cleaned)
        self.bind_context(project_id=project_id, session_id=session_id)
        plan_context: dict[str, Any] = {
            "permission_mode": permission_mode or "default",
            "workbench_surface": "cli",
            "dry_run": dry_run,
        }
        if context:
            for key, value in dict(context).items():
                plan_context.setdefault(key, value)
        plan = self.plan(cleaned, verb=intent, context=plan_context)
        task = self._require_active_task()
        project = self._store.get_project(task.project_id)
        session = self._store.get_session(task.session_id)
        if project is None or session is None:
            raise ValueError("Coordinator session lost its active project or session")
        if dry_run:
            return self._planned_result(
                plan=plan,
                task=task,
                project=project,
                session=session,
                intent=intent,
                message=cleaned,
            )

        emitted = tuple(self.execute(str(plan["plan_id"])))
        run = self._require_latest_run()
        transcript_lines = tuple(self._render_transcript_lines(plan=plan, run=run, events=emitted))
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
            active_tasks=0 if run.status in _TERMINAL_RUN_STATUSES else len(run.worker_states),
            next_actions=tuple(self._next_actions(run_status=run.status, intent=intent)),
            review_cards=tuple(self._review_cards(run)),
            metadata={
                "coordinator_synthesis": dict(run.coordinator_synthesis),
                "worker_count": len(run.worker_states),
                "event_count": len(emitted),
                "materialized_task_ids": [
                    str(item.get("materialized_task_id"))
                    for item in plan.get("tasks", [])
                    if isinstance(item, dict) and item.get("materialized_task_id")
                ],
            },
        )

    def plan(
        self,
        goal: str,
        verb: str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create and persist a coordinator plan for ``goal``."""
        cleaned = " ".join(str(goal or "").split())
        if not cleaned:
            raise ValueError("Coordinator plan goal cannot be empty")
        intent = verb or detect_command_intent(cleaned)
        project = self._get_or_create_project(message=cleaned)
        session = self._get_or_create_session(project=project, intent=intent)
        self._orchestrator.start_session(session)
        extra_metadata: dict[str, Any] = {}
        ctx_dict = dict(context or {})
        for key in ("deploy", "skills"):
            value = ctx_dict.get(key)
            if isinstance(value, Mapping):
                extra_metadata[key] = dict(value)
        task = self._create_task(
            project=project,
            session=session,
            message=cleaned,
            intent=intent,
            permission_mode=str(ctx_dict.get("permission_mode") or "default"),
            extra_metadata=extra_metadata,
        )
        extra_context = {
            "command_intent": intent,
            "permission_mode": str((context or {}).get("permission_mode") or "default"),
            "workbench_surface": "cli",
            **dict(context or {}),
        }
        plan = self._orchestrator.plan_work(
            task=task,
            goal=cleaned,
            requested_roles=roles_for_intent(intent, cleaned),
            materialize_tasks=True,
            extra_context=extra_context,
        )
        self.active_project_id = project.project_id
        self.active_session_id = session.session_id
        self.active_task_id = task.task_id
        self.active_plan_id = str(plan["plan_id"])
        return plan

    def execute(self, plan_id: str | None = None, dry_run: bool = False) -> Iterator[BuilderEvent]:
        """Execute the active plan and yield coordinator events in order."""
        task = self._require_active_task()
        selected_plan_id = plan_id or self.active_plan_id
        if not selected_plan_id:
            raise ValueError("No active coordinator plan to execute")
        if dry_run:
            yield self._events.publish(
                BuilderEventType.PLAN_READY,
                session_id=task.session_id,
                task_id=task.task_id,
                payload={"plan_id": selected_plan_id, "status": "planned"},
            )
            return

        start_ts = now_ts()
        self._active_run_count += 1
        self._cancel_requested = False
        try:
            run = self._runtime.execute_plan(
                task_id=task.task_id,
                plan_id=selected_plan_id,
            )
            self.latest_run_id = run.run_id
            self._latest_synthesis = dict(run.coordinator_synthesis)
        finally:
            self._active_run_count = max(0, self._active_run_count - 1)

        for event in self._events.iter_events(
            session_id=task.session_id,
            task_id=task.task_id,
            since_timestamp=start_ts,
        ):
            yield event

    def cancel(self) -> bool:
        """Request cancellation of active coordinator work.

        Execution is currently synchronous, so this records intent for the
        Workbench loop and returns whether there was active work to cancel.
        """
        if self._active_run_count <= 0:
            return False
        self._cancel_requested = True
        return True

    def latest_synthesis(self) -> dict[str, Any]:
        """Return the latest coordinator synthesis payload."""
        return dict(self._latest_synthesis)

    def tasks_snapshot(self, *, limit: int = 10) -> dict[str, Any]:
        """Return persisted task and run state for the Workbench task view."""
        tasks = self._store.list_tasks(
            session_id=self.active_session_id,
            project_id=None if self.active_session_id else self.active_project_id,
            limit=max(limit * 5, limit),
        )
        runs = self._store.list_coordinator_runs(
            session_id=self.active_session_id,
            limit=limit,
        )
        root_tasks = sorted(
            (
                task
                for task in tasks
                if task.metadata.get("created_by") == "workbench_coordinator_session"
                or task.metadata.get("command_intent")
            ),
            key=lambda task: task.created_at,
            reverse=True,
        )[:limit]
        return {
            "project_id": self.active_project_id,
            "session_id": self.active_session_id,
            "active_run_count": self.active_run_count,
            "latest_run_id": self.latest_run_id,
            "tasks": [
                {
                    "task_id": task.task_id,
                    "title": task.title,
                    "status": task.status.value,
                    "command_intent": task.metadata.get("command_intent"),
                    "latest_run_id": task.metadata.get("latest_coordinator_run_id"),
                }
                for task in root_tasks
            ],
            "runs": [
                {
                    "run_id": run.run_id,
                    "plan_id": run.plan_id,
                    "status": run.status.value,
                    "worker_count": len(run.worker_states),
                    "goal": run.goal,
                }
                for run in runs
            ],
        }

    def _get_or_create_project(self, *, message: str) -> BuilderProject:
        """Return the bound project, latest project, or a new CLI project."""
        if self.active_project_id:
            project = self._store.get_project(self.active_project_id)
            if project is not None:
                return project
        latest = self._store.list_projects(archived=False, limit=1)
        if latest:
            return latest[0]
        project = BuilderProject(
            name=_project_name(message),
            description="AgentLab Workbench coordinator project.",
        )
        self._store.save_project(project)
        return project

    def _get_or_create_session(self, *, project: BuilderProject, intent: str) -> BuilderSession:
        """Return the bound session, latest open session, or a new one."""
        if self.active_session_id:
            session = self._store.get_session(self.active_session_id)
            if session is not None:
                return session
        sessions = self._store.list_sessions(project_id=project.project_id, status="open", limit=1)
        if sessions:
            return sessions[0]
        session = BuilderSession(project_id=project.project_id, title=f"Workbench {intent}")
        self._store.save_session(session)
        return session

    def _create_task(
        self,
        *,
        project: BuilderProject,
        session: BuilderSession,
        message: str,
        intent: str,
        permission_mode: str,
        extra_metadata: Mapping[str, Any] | None = None,
    ) -> BuilderTask:
        """Persist the root task representing one coordinator turn."""
        metadata: dict[str, Any] = {
            "command_intent": intent,
            "permission_mode": permission_mode,
            "created_by": "workbench_coordinator_session",
        }
        if extra_metadata:
            metadata.update({k: v for k, v in extra_metadata.items() if v is not None})
        task = BuilderTask(
            project_id=project.project_id,
            session_id=session.session_id,
            title=f"{intent.title()} agent",
            description=message,
            metadata=metadata,
        )
        self._store.save_task(task)
        session.task_ids.append(task.task_id)
        session.message_count += 1
        session.updated_at = now_ts()
        self._store.save_session(session)
        return task

    def _planned_result(
        self,
        *,
        plan: dict[str, Any],
        task: BuilderTask,
        project: BuilderProject,
        session: BuilderSession,
        intent: str,
        message: str,
    ) -> CoordinatorTurnResult:
        """Build a turn result for plan-mode review."""
        worker_roles = tuple(
            str(node.get("worker_role"))
            for node in plan.get("tasks", [])
            if isinstance(node, dict)
            and node.get("worker_role")
            and node.get("worker_role") != SpecialistRole.ORCHESTRATOR.value
        )
        lines = [
            f"  Coordinator plan {plan['plan_id']} ready - {len(worker_roles)} worker"
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
            suffix = f" - {reason}" if reason else ""
            lines.append(f"  - {role_value.replace('_', ' ')}: {title}{suffix}")
        lines.append("  Approve with y to execute, n to abort, or edit to refine.")
        return CoordinatorTurnResult(
            message=message,
            command_intent=intent,
            project_id=project.project_id,
            session_id=session.session_id,
            task_id=task.task_id,
            plan_id=str(plan["plan_id"]),
            run_id="",
            status="planned",
            transcript_lines=tuple(lines),
            worker_roles=worker_roles,
            active_tasks=0,
            next_actions=(
                "Reply y to run the plan as-is.",
                "Reply n to abort; nothing will be written.",
                "Reply edit: <annotation> to refine the goal and re-plan.",
            ),
            review_cards=(),
            metadata={"dry_run": True, "worker_count": len(worker_roles)},
        )

    def _render_transcript_lines(
        self,
        *,
        plan: dict[str, Any],
        run: CoordinatorExecutionRun,
        events: tuple[BuilderEvent, ...],
    ) -> list[str]:
        """Render event-backed transcript lines for a completed turn result."""
        lines = [
            f"  Coordinator plan {plan['plan_id']} created for {len(run.worker_states)} worker"
            f"{'' if len(run.worker_states) == 1 else 's'}."
        ]
        rendered = [line for event in events if (line := format_coordinator_event(event))]
        if rendered:
            lines.extend(rendered)
        else:
            for state in run.worker_states:
                status = state.status.value
                role = state.worker_role.value.replace("_", " ")
                summary = state.result.summary if state.result else state.blocker_reason or state.error or ""
                suffix = f" - {summary}" if summary else ""
                lines.append(f"  - {role}: {status}{suffix}")
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

    def _review_cards(self, run: CoordinatorExecutionRun) -> list[dict[str, Any]]:
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

    def _require_active_task(self) -> BuilderTask:
        """Return the active task or raise a helpful state error."""
        if not self.active_task_id:
            raise ValueError("No active coordinator task")
        task = self._store.get_task(self.active_task_id)
        if task is None:
            raise ValueError(f"Builder task not found: {self.active_task_id}")
        return task

    def _require_latest_run(self) -> CoordinatorExecutionRun:
        """Return the latest run or raise a helpful state error."""
        if not self.latest_run_id:
            raise ValueError("No coordinator run has completed")
        run = self._store.get_coordinator_run(self.latest_run_id)
        if run is None:
            raise ValueError(f"Coordinator run not found: {self.latest_run_id}")
        return run


_TERMINAL_RUN_STATUSES = {
    CoordinatorExecutionStatus.COMPLETED,
    CoordinatorExecutionStatus.FAILED,
    CoordinatorExecutionStatus.BLOCKED,
}


def _project_name(message: str) -> str:
    """Create a short project name from the first user request."""
    words = [word.strip(".,:;!?") for word in message.split() if word.strip(".,:;!?")]
    title = " ".join(words[:6]).strip()
    return title or "AgentLab Workbench Project"


__all__ = ["CoordinatorSession"]
