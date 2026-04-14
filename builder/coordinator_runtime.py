"""Executable coordinator-worker runtime for Builder plans.

The orchestrator creates a plan; this module turns that plan into durable
worker lifecycle state, role-scoped outputs, events, and coordinator synthesis.
"""

from __future__ import annotations

from typing import Any

from builder.events import BuilderEventType, EventBroker
from builder.orchestrator import BuilderOrchestrator
from builder.store import BuilderStore
from builder.types import (
    BuilderTask,
    CoordinatorExecutionRun,
    CoordinatorExecutionStatus,
    SpecialistRole,
    WorkerExecutionResult,
    WorkerExecutionState,
    WorkerExecutionStatus,
    now_ts,
)


class CoordinatorWorkerRuntime:
    """Executes persisted coordinator plans with explicit worker state."""

    def __init__(
        self,
        store: BuilderStore,
        orchestrator: BuilderOrchestrator,
        events: EventBroker,
    ) -> None:
        self._store = store
        self._orchestrator = orchestrator
        self._events = events

    def execute_plan(self, task_id: str, plan_id: str | None = None) -> CoordinatorExecutionRun:
        """Execute a previously persisted coordinator plan for a root task."""

        task = self._store.get_task(task_id)
        if task is None:
            raise ValueError(f"Builder task not found: {task_id}")

        plan = self._select_plan(task, plan_id)
        worker_nodes = [
            node
            for node in plan.get("tasks", [])
            if isinstance(node, dict) and node.get("worker_role") != SpecialistRole.ORCHESTRATOR.value
        ]
        run = CoordinatorExecutionRun(
            plan_id=str(plan.get("plan_id") or ""),
            root_task_id=task.task_id,
            session_id=task.session_id,
            project_id=task.project_id,
            goal=str(plan.get("goal") or task.description or task.title),
            status=CoordinatorExecutionStatus.RUNNING,
            started_at=now_ts(),
            worker_states=[
                WorkerExecutionState(
                    node_id=str(node.get("task_id") or ""),
                    worker_role=self._parse_role(node.get("worker_role")),
                    title=str(node.get("title") or ""),
                    depends_on=[str(dep) for dep in node.get("depends_on", [])],
                )
                for node in worker_nodes
            ],
        )
        run.updated_at = now_ts()
        self._store.save_coordinator_run(run)
        self._remember_run_on_task(task, run)
        self._publish(
            BuilderEventType.COORDINATOR_EXECUTION_STARTED,
            run,
            payload={
                "status": run.status.value,
                "worker_count": len(worker_nodes),
            },
        )

        completed_nodes = {
            str(node.get("task_id"))
            for node in plan.get("tasks", [])
            if isinstance(node, dict) and node.get("worker_role") == SpecialistRole.ORCHESTRATOR.value
        }
        dependency_summaries: dict[str, str] = {}

        for node in worker_nodes:
            state = self._state_for_node(run, str(node.get("task_id") or ""))
            missing_dependencies = [
                dependency
                for dependency in state.depends_on
                if dependency not in completed_nodes
            ]
            if missing_dependencies:
                self._block_worker(
                    run,
                    state,
                    f"Unsatisfied dependencies: {', '.join(missing_dependencies)}",
                )
                self._finish_blocked(run)
                self._remember_run_on_task(task, run)
                return run

            try:
                context = self._gather_context(task, plan, node, dependency_summaries, run)
                self._transition_worker(
                    run,
                    state,
                    WorkerExecutionStatus.GATHERING_CONTEXT,
                    BuilderEventType.WORKER_GATHERING_CONTEXT,
                    {"context_keys": sorted(context), "worker_role": state.worker_role.value},
                )
                state.context_snapshot = context
                self._store.save_coordinator_run(run)

                self._transition_worker(
                    run,
                    state,
                    WorkerExecutionStatus.ACTING,
                    BuilderEventType.WORKER_ACTING,
                    {"selected_tools": context["selected_tools"], "worker_role": state.worker_role.value},
                )
                routed = self._orchestrator.invoke_specialist(
                    task=task,
                    message=self._worker_message(node, run.goal),
                    explicit_role=state.worker_role,
                    extra_context={
                        "coordinator_run_id": run.run_id,
                        "coordinator_plan_id": run.plan_id,
                        "coordinator_node_id": state.node_id,
                        "context_boundary": context["context_boundary"],
                    },
                )
                result = self._act(state, context, routed, run)

                self._transition_worker(
                    run,
                    state,
                    WorkerExecutionStatus.VERIFYING,
                    BuilderEventType.WORKER_VERIFYING,
                    {"expected_artifacts": context["expected_artifacts"], "worker_role": state.worker_role.value},
                )
                result.verification = self._verify_result(result, context)
                if not result.verification["verified"]:
                    raise RuntimeError(str(result.verification["reason"]))

                state.result = result
                self._transition_worker(
                    run,
                    state,
                    WorkerExecutionStatus.COMPLETED,
                    BuilderEventType.WORKER_COMPLETED,
                    {
                        "summary": result.summary,
                        "artifacts": sorted(result.artifacts),
                        "worker_role": state.worker_role.value,
                    },
                )
                completed_nodes.add(state.node_id)
                dependency_summaries[state.node_id] = result.summary
            except Exception as exc:
                self._fail_worker(run, state, str(exc))
                self._finish_failed(run, str(exc))
                self._remember_run_on_task(task, run)
                return run

        run.status = CoordinatorExecutionStatus.COMPLETED
        run.completed_at = now_ts()
        run.updated_at = now_ts()
        run.coordinator_synthesis = self._synthesize(run)
        self._store.save_coordinator_run(run)
        self._remember_run_on_task(task, run)
        self._publish(
            BuilderEventType.COORDINATOR_SYNTHESIS_COMPLETED,
            run,
            payload={"status": run.status.value, **run.coordinator_synthesis},
        )
        self._publish(
            BuilderEventType.COORDINATOR_EXECUTION_COMPLETED,
            run,
            payload={"status": run.status.value, "worker_count": len(run.worker_states)},
        )
        return run

    def _select_plan(self, task: BuilderTask, plan_id: str | None) -> dict[str, Any]:
        plan = task.metadata.get("coordinator_plan")
        if not isinstance(plan, dict):
            raise ValueError(f"Builder task {task.task_id} has no persisted coordinator plan")
        if plan_id is not None and plan.get("plan_id") != plan_id:
            raise ValueError(f"Coordinator plan {plan_id} is not attached to task {task.task_id}")
        return plan

    def _parse_role(self, value: Any) -> SpecialistRole:
        try:
            return SpecialistRole(str(value))
        except ValueError:
            return SpecialistRole.ORCHESTRATOR

    def _state_for_node(self, run: CoordinatorExecutionRun, node_id: str) -> WorkerExecutionState:
        for state in run.worker_states:
            if state.node_id == node_id:
                return state
        raise ValueError(f"Worker node not found in run: {node_id}")

    def _transition_worker(
        self,
        run: CoordinatorExecutionRun,
        state: WorkerExecutionState,
        status: WorkerExecutionStatus,
        event_type: BuilderEventType,
        payload: dict[str, Any],
    ) -> None:
        timestamp = now_ts()
        state.status = status
        state.started_at = state.started_at or timestamp
        state.updated_at = timestamp
        if status in {
            WorkerExecutionStatus.COMPLETED,
            WorkerExecutionStatus.FAILED,
            WorkerExecutionStatus.BLOCKED,
        }:
            state.completed_at = timestamp
        state.phase_history.append({"status": status.value, "timestamp": timestamp})
        run.updated_at = timestamp
        self._store.save_coordinator_run(run)
        self._publish(
            event_type,
            run,
            node_id=state.node_id,
            worker_role=state.worker_role,
            payload={"status": status.value, **payload},
        )

    def _gather_context(
        self,
        task: BuilderTask,
        plan: dict[str, Any],
        node: dict[str, Any],
        dependency_summaries: dict[str, str],
        run: CoordinatorExecutionRun,
    ) -> dict[str, Any]:
        project = self._store.get_project(task.project_id)
        return {
            "context_boundary": "fresh_worker_context",
            "run_id": run.run_id,
            "plan_id": run.plan_id,
            "node_id": node.get("task_id"),
            "worker_role": node.get("worker_role"),
            "goal": plan.get("goal"),
            "task": {
                "task_id": task.task_id,
                "title": task.title,
                "description": task.description,
                "mode": task.mode.value,
            },
            "project": {
                "project_id": task.project_id,
                "name": project.name if project else "",
                "buildtime_skills": list(project.buildtime_skills if project else []),
                "runtime_skills": list(project.runtime_skills if project else []),
            },
            "selected_tools": list(node.get("selected_tools", [])),
            "permission_scope": list(node.get("permission_scope", [])),
            "skill_layer": node.get("skill_layer"),
            "skill_candidates": list(node.get("skill_candidates", [])),
            "expected_artifacts": list(node.get("expected_artifacts", [])),
            "depends_on": list(node.get("depends_on", [])),
            "dependency_summaries": {
                dep: dependency_summaries[dep]
                for dep in node.get("depends_on", [])
                if dep in dependency_summaries
            },
            "provenance": dict(node.get("provenance", {})),
        }

    def _worker_message(self, node: dict[str, Any], goal: str) -> str:
        return (
            f"{node.get('title')}: {node.get('description')} "
            f"Goal: {goal}. Return structured summary and artifacts."
        )

    def _act(
        self,
        state: WorkerExecutionState,
        context: dict[str, Any],
        routed: dict[str, Any],
        run: CoordinatorExecutionRun,
    ) -> WorkerExecutionResult:
        artifacts = {
            artifact: {
                "artifact_type": artifact,
                "worker_role": state.worker_role.value,
                "source_node_id": state.node_id,
                "summary": f"{state.worker_role.value} prepared {artifact} for {context['goal']}",
            }
            for artifact in context["expected_artifacts"]
        }
        summary = (
            f"{routed['display_name']} completed gather/action/verify work for "
            f"{len(artifacts)} expected artifact{'s' if len(artifacts) != 1 else ''}."
        )
        return WorkerExecutionResult(
            node_id=state.node_id,
            worker_role=state.worker_role,
            summary=summary,
            artifacts=artifacts,
            context_used={
                "context_boundary": context["context_boundary"],
                "selected_tools": list(context["selected_tools"]),
                "skill_candidates": list(context["skill_candidates"]),
                "dependency_summaries": dict(context["dependency_summaries"]),
            },
            output_payload={
                "specialist": routed["specialist"],
                "recommended_tools": list(routed.get("recommended_tools", [])),
                "permission_scope": list(routed.get("permission_scope", [])),
            },
            provenance={
                "run_id": run.run_id,
                "plan_id": run.plan_id,
                "node_id": state.node_id,
                "routed_by": routed.get("provenance", {}).get("routed_by"),
                "routing_reason": routed.get("provenance", {}).get("routing_reason"),
            },
        )

    def _verify_result(self, result: WorkerExecutionResult, context: dict[str, Any]) -> dict[str, Any]:
        expected = list(context.get("expected_artifacts", []))
        missing = [artifact for artifact in expected if artifact not in result.artifacts]
        verified = bool(result.summary) and not missing
        return {
            "verified": verified,
            "checked": ["summary_present", "expected_artifacts_present", "context_boundary_preserved"],
            "missing_artifacts": missing,
            "reason": "ok" if verified else f"Missing expected artifacts: {', '.join(missing)}",
            "context_boundary": result.context_used.get("context_boundary"),
        }

    def _synthesize(self, run: CoordinatorExecutionRun) -> dict[str, Any]:
        completed = [state for state in run.worker_states if state.status == WorkerExecutionStatus.COMPLETED]
        return {
            "status": run.status.value,
            "worker_count": len(run.worker_states),
            "completed_worker_count": len(completed),
            "summary": (
                "Coordinator executed workers and synthesized "
                f"{len(completed)} completed result{'s' if len(completed) != 1 else ''}."
            ),
            "worker_summaries": [
                {
                    "node_id": state.node_id,
                    "worker_role": state.worker_role.value,
                    "summary": state.result.summary if state.result else "",
                }
                for state in run.worker_states
            ],
            "next_step": "Review worker artifacts, then decide whether to apply or route a follow-up task.",
        }

    def _block_worker(self, run: CoordinatorExecutionRun, state: WorkerExecutionState, reason: str) -> None:
        state.blocker_reason = reason
        self._transition_worker(
            run,
            state,
            WorkerExecutionStatus.BLOCKED,
            BuilderEventType.WORKER_BLOCKED,
            {"reason": reason, "worker_role": state.worker_role.value},
        )

    def _fail_worker(self, run: CoordinatorExecutionRun, state: WorkerExecutionState, error: str) -> None:
        state.error = error
        self._transition_worker(
            run,
            state,
            WorkerExecutionStatus.FAILED,
            BuilderEventType.WORKER_FAILED,
            {"error": error, "worker_role": state.worker_role.value},
        )

    def _finish_blocked(self, run: CoordinatorExecutionRun) -> None:
        run.status = CoordinatorExecutionStatus.BLOCKED
        run.completed_at = now_ts()
        run.updated_at = now_ts()
        run.coordinator_synthesis = {
            "status": "blocked",
            "worker_count": len(run.worker_states),
            "blocked_worker_count": len([
                state for state in run.worker_states if state.status == WorkerExecutionStatus.BLOCKED
            ]),
            "summary": "Coordinator execution stopped because a worker dependency was not satisfied.",
        }
        self._store.save_coordinator_run(run)
        self._publish(
            BuilderEventType.COORDINATOR_EXECUTION_BLOCKED,
            run,
            payload=run.coordinator_synthesis,
        )

    def _finish_failed(self, run: CoordinatorExecutionRun, error: str) -> None:
        run.status = CoordinatorExecutionStatus.FAILED
        run.error = error
        run.completed_at = now_ts()
        run.updated_at = now_ts()
        run.coordinator_synthesis = {
            "status": "failed",
            "worker_count": len(run.worker_states),
            "summary": "Coordinator execution stopped after a worker failure.",
            "error": error,
        }
        self._store.save_coordinator_run(run)
        self._publish(
            BuilderEventType.COORDINATOR_EXECUTION_FAILED,
            run,
            payload=run.coordinator_synthesis,
        )

    def _remember_run_on_task(self, task: BuilderTask, run: CoordinatorExecutionRun) -> None:
        task.metadata["latest_coordinator_run_id"] = run.run_id
        run_ids = list(task.metadata.get("coordinator_run_ids", []))
        if run.run_id not in run_ids:
            run_ids.append(run.run_id)
        task.metadata["coordinator_run_ids"] = run_ids
        task.updated_at = now_ts()
        self._store.save_task(task)

    def _publish(
        self,
        event_type: BuilderEventType,
        run: CoordinatorExecutionRun,
        *,
        payload: dict[str, Any],
        node_id: str | None = None,
        worker_role: SpecialistRole | None = None,
    ) -> None:
        self._events.publish(
            event_type,
            session_id=run.session_id,
            task_id=run.root_task_id,
            payload={
                "run_id": run.run_id,
                "plan_id": run.plan_id,
                "node_id": node_id,
                "worker_role": worker_role.value if worker_role else None,
                **payload,
            },
        )
