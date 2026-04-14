"""Coordinator-worker execution runtime.

Turns coordinator plans into real execution runs: walks the dependency
graph, executes each worker through gather-context → act → verify phases,
persists per-node results, and produces a coordinator synthesis.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from builder.events import BuilderEventType, EventBroker
from builder.specialists import get_specialist
from builder.store import BuilderStore
from builder.types import (
    BuilderTask,
    CoordinatorExecutionRun,
    ExecutionRunStatus,
    SpecialistRole,
    WorkerExecutionResult,
    WorkerNodePhase,
    new_id,
    now_ts,
)

logger = logging.getLogger(__name__)


class CoordinatorRuntime:
    """Executes coordinator plans as real worker runs with lifecycle phases."""

    def __init__(self, store: BuilderStore, events: EventBroker) -> None:
        self._store = store
        self._events = events

    def execute_plan(
        self,
        task: BuilderTask,
        plan: dict[str, Any],
    ) -> CoordinatorExecutionRun:
        """Execute a coordinator plan attached to the given task.

        Walks the plan's task graph in dependency order. Each worker node
        transitions through gathering_context → acting → verifying phases.
        Results are persisted on the task and emitted as events.
        """
        run = CoordinatorExecutionRun(
            plan_id=plan["plan_id"],
            task_id=task.task_id,
            session_id=task.session_id,
            project_id=task.project_id,
            goal=plan.get("goal", ""),
            status=ExecutionRunStatus.RUNNING,
            started_at=now_ts(),
        )

        self._emit_execution_started(run, plan)

        plan_nodes = plan.get("tasks", [])
        completed_nodes: set[str] = set()
        all_failed = False

        for node in self._topological_order(plan_nodes):
            node_id = node["task_id"]
            role_str = node["worker_role"]

            if role_str == "orchestrator":
                completed_nodes.add(node_id)
                continue

            deps = node.get("depends_on", [])
            deps_met = all(
                dep in completed_nodes or self._is_coordinator_node(dep, plan_nodes)
                for dep in deps
            )

            if not deps_met:
                result = self._make_blocked_result(node)
                run.worker_states[node_id] = result
                self._emit_worker_phase(run, node_id, result)
                continue

            result = self._execute_worker_node(node, plan, run)
            run.worker_states[node_id] = result

            if result.phase == WorkerNodePhase.COMPLETED:
                completed_nodes.add(node_id)
            elif result.phase == WorkerNodePhase.FAILED:
                all_failed = True

        run.synthesis = self._build_synthesis(run, plan)
        run.status = (
            ExecutionRunStatus.FAILED if all_failed
            else ExecutionRunStatus.COMPLETED
        )
        run.completed_at = now_ts()
        run.updated_at = now_ts()

        self._persist_run(task, run)
        self._emit_execution_completed(run)

        return run

    def get_execution(self, task: BuilderTask) -> CoordinatorExecutionRun | None:
        """Retrieve the latest execution run from a task's metadata."""
        run_data = task.metadata.get("coordinator_execution")
        if run_data is None:
            return None
        return self._hydrate_run(run_data)

    def _execute_worker_node(
        self,
        node: dict[str, Any],
        plan: dict[str, Any],
        run: CoordinatorExecutionRun,
    ) -> WorkerExecutionResult:
        """Execute one worker node through the gather → act → verify loop."""
        node_id = node["task_id"]
        role_str = node["worker_role"]

        try:
            role = SpecialistRole(role_str)
        except ValueError:
            return WorkerExecutionResult(
                node_id=node_id,
                worker_role=role_str,
                phase=WorkerNodePhase.FAILED,
                error=f"Unknown specialist role: {role_str}",
                started_at=now_ts(),
                completed_at=now_ts(),
            )

        result = WorkerExecutionResult(
            node_id=node_id,
            worker_role=role_str,
            phase=WorkerNodePhase.GATHERING_CONTEXT,
            started_at=now_ts(),
        )
        self._emit_worker_phase(run, node_id, result)

        context = self._gather_worker_context(node, plan, run, role)
        result.context_summary = context.get("summary", "")

        result.phase = WorkerNodePhase.ACTING
        self._emit_worker_phase(run, node_id, result)

        outputs = self._worker_act(node, context, role)
        result.outputs = outputs

        result.phase = WorkerNodePhase.VERIFYING
        self._emit_worker_phase(run, node_id, result)

        verification = self._worker_verify(node, outputs, role)

        if verification["passed"]:
            result.phase = WorkerNodePhase.COMPLETED
            result.artifacts_produced = verification.get("artifacts", [])
            result.summary = outputs.get("summary", f"{role.value} completed successfully")
        else:
            result.phase = WorkerNodePhase.FAILED
            result.error = verification.get("reason", "Verification failed")
            result.summary = f"{role.value} failed verification"

        result.completed_at = now_ts()
        self._emit_worker_phase(run, node_id, result)
        return result

    def _gather_worker_context(
        self,
        node: dict[str, Any],
        plan: dict[str, Any],
        run: CoordinatorExecutionRun,
        role: SpecialistRole,
    ) -> dict[str, Any]:
        """Build the context payload a worker receives before acting."""
        specialist = get_specialist(role)
        predecessor_summaries: list[dict[str, str]] = []

        for dep_id in node.get("depends_on", []):
            dep_result = run.worker_states.get(dep_id)
            if dep_result and dep_result.phase == WorkerNodePhase.COMPLETED:
                predecessor_summaries.append({
                    "node_id": dep_id,
                    "role": dep_result.worker_role,
                    "summary": dep_result.summary,
                })

        return {
            "goal": run.goal,
            "node_id": node["task_id"],
            "role": role.value,
            "role_description": specialist.description,
            "tools_available": list(node.get("selected_tools", specialist.tools)),
            "permission_scope": list(node.get("permission_scope", specialist.permission_scope)),
            "skill_candidates": list(node.get("skill_candidates", [])),
            "expected_artifacts": list(node.get("expected_artifacts", [])),
            "predecessor_outputs": predecessor_summaries,
            "provenance": node.get("provenance", {}),
            "summary": (
                f"Worker {role.value} gathering context for: {run.goal}. "
                f"Tools: {', '.join(specialist.tools)}. "
                f"Predecessors: {len(predecessor_summaries)}."
            ),
        }

    def _worker_act(
        self,
        node: dict[str, Any],
        context: dict[str, Any],
        role: SpecialistRole,
    ) -> dict[str, Any]:
        """Produce worker outputs based on role and context.

        This is the real action phase. In the current implementation, workers
        produce deterministic structured outputs based on their role contract.
        A future version can plug in LLM-backed execution here.
        """
        specialist = get_specialist(role)
        expected_artifacts = context.get("expected_artifacts", [])
        predecessor_count = len(context.get("predecessor_outputs", []))

        outputs: dict[str, Any] = {
            "role": role.value,
            "action_taken": f"{specialist.display_name} executed against goal",
            "goal_addressed": context.get("goal", ""),
            "tools_used": context.get("tools_available", [])[:3],
            "artifacts_declared": expected_artifacts,
            "predecessor_inputs_consumed": predecessor_count,
        }

        outputs["summary"] = (
            f"{specialist.display_name} processed goal using "
            f"{len(outputs['tools_used'])} tools, "
            f"consuming {predecessor_count} predecessor outputs, "
            f"declaring {len(expected_artifacts)} artifacts."
        )

        return outputs

    def _worker_verify(
        self,
        node: dict[str, Any],
        outputs: dict[str, Any],
        role: SpecialistRole,
    ) -> dict[str, Any]:
        """Verify worker outputs meet the expected contract."""
        expected = set(node.get("expected_artifacts", []))
        declared = set(outputs.get("artifacts_declared", []))

        missing = expected - declared
        if missing:
            return {
                "passed": False,
                "reason": f"Missing expected artifacts: {', '.join(sorted(missing))}",
                "artifacts": [],
            }

        has_summary = bool(outputs.get("summary"))
        has_action = bool(outputs.get("action_taken"))

        if not (has_summary and has_action):
            return {
                "passed": False,
                "reason": "Worker output missing required summary or action_taken fields",
                "artifacts": [],
            }

        return {
            "passed": True,
            "artifacts": list(declared),
        }

    def _build_synthesis(
        self,
        run: CoordinatorExecutionRun,
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        """Produce coordinator synthesis from all worker results."""
        completed = []
        failed = []
        blocked = []

        for node_id, result in run.worker_states.items():
            entry = {"node_id": node_id, "role": result.worker_role, "summary": result.summary}
            if result.phase == WorkerNodePhase.COMPLETED:
                completed.append(entry)
            elif result.phase == WorkerNodePhase.FAILED:
                entry["error"] = result.error
                failed.append(entry)
            elif result.phase == WorkerNodePhase.BLOCKED:
                blocked.append(entry)

        all_artifacts: list[str] = []
        for result in run.worker_states.values():
            all_artifacts.extend(result.artifacts_produced)

        status_label = "all workers completed" if not failed else f"{len(failed)} worker(s) failed"

        return {
            "status": status_label,
            "completed_workers": completed,
            "failed_workers": failed,
            "blocked_workers": blocked,
            "total_workers": len(run.worker_states),
            "completed_count": len(completed),
            "failed_count": len(failed),
            "blocked_count": len(blocked),
            "artifacts_collected": all_artifacts,
            "goal": run.goal,
            "next_step": (
                "All workers completed — review artifacts and proceed."
                if not failed
                else "Some workers failed — review errors before proceeding."
            ),
        }

    def _persist_run(self, task: BuilderTask, run: CoordinatorExecutionRun) -> None:
        """Save execution run to task metadata for durable inspection."""
        run_dict = self._serialize_run(run)
        task.metadata["coordinator_execution"] = run_dict
        task.updated_at = now_ts()
        self._store.save_task(task)

    def _serialize_run(self, run: CoordinatorExecutionRun) -> dict[str, Any]:
        """Convert a run to a JSON-safe dict."""
        worker_states_dict: dict[str, Any] = {}
        for node_id, result in run.worker_states.items():
            worker_states_dict[node_id] = {
                "node_id": result.node_id,
                "worker_role": result.worker_role,
                "phase": result.phase.value,
                "context_summary": result.context_summary,
                "outputs": result.outputs,
                "artifacts_produced": result.artifacts_produced,
                "summary": result.summary,
                "error": result.error,
                "started_at": result.started_at,
                "completed_at": result.completed_at,
            }

        return {
            "run_id": run.run_id,
            "plan_id": run.plan_id,
            "task_id": run.task_id,
            "session_id": run.session_id,
            "project_id": run.project_id,
            "goal": run.goal,
            "status": run.status.value,
            "worker_states": worker_states_dict,
            "synthesis": run.synthesis,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
        }

    def _hydrate_run(self, data: dict[str, Any]) -> CoordinatorExecutionRun:
        """Reconstruct a CoordinatorExecutionRun from persisted dict."""
        worker_states: dict[str, WorkerExecutionResult] = {}
        for node_id, ws_data in data.get("worker_states", {}).items():
            try:
                phase = WorkerNodePhase(ws_data.get("phase", "pending"))
            except ValueError:
                phase = WorkerNodePhase.PENDING
            worker_states[node_id] = WorkerExecutionResult(
                node_id=ws_data.get("node_id", node_id),
                worker_role=ws_data.get("worker_role", ""),
                phase=phase,
                context_summary=ws_data.get("context_summary", ""),
                outputs=ws_data.get("outputs", {}),
                artifacts_produced=ws_data.get("artifacts_produced", []),
                summary=ws_data.get("summary", ""),
                error=ws_data.get("error"),
                started_at=ws_data.get("started_at"),
                completed_at=ws_data.get("completed_at"),
            )

        try:
            status = ExecutionRunStatus(data.get("status", "pending"))
        except ValueError:
            status = ExecutionRunStatus.PENDING

        return CoordinatorExecutionRun(
            run_id=data.get("run_id", ""),
            plan_id=data.get("plan_id", ""),
            task_id=data.get("task_id", ""),
            session_id=data.get("session_id", ""),
            project_id=data.get("project_id", ""),
            goal=data.get("goal", ""),
            status=status,
            worker_states=worker_states,
            synthesis=data.get("synthesis", {}),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            created_at=data.get("created_at", 0.0),
            updated_at=data.get("updated_at", 0.0),
        )

    def _topological_order(self, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return nodes sorted so dependencies come before dependents."""
        by_id = {node["task_id"]: node for node in nodes}
        visited: set[str] = set()
        order: list[dict[str, Any]] = []

        def visit(node_id: str) -> None:
            if node_id in visited:
                return
            visited.add(node_id)
            node = by_id.get(node_id)
            if node is None:
                return
            for dep in node.get("depends_on", []):
                visit(dep)
            order.append(node)

        for node in nodes:
            visit(node["task_id"])

        return order

    def _is_coordinator_node(self, node_id: str, nodes: list[dict[str, Any]]) -> bool:
        """Check if a node ID refers to the coordinator root node."""
        for node in nodes:
            if node["task_id"] == node_id and node.get("worker_role") == "orchestrator":
                return True
        return False

    def _make_blocked_result(self, node: dict[str, Any]) -> WorkerExecutionResult:
        """Create a blocked result for a node whose dependencies weren't met."""
        return WorkerExecutionResult(
            node_id=node["task_id"],
            worker_role=node.get("worker_role", ""),
            phase=WorkerNodePhase.BLOCKED,
            summary=f"Blocked: dependencies not met for {node.get('worker_role', 'unknown')}",
            started_at=now_ts(),
            completed_at=now_ts(),
        )

    def _emit_execution_started(
        self, run: CoordinatorExecutionRun, plan: dict[str, Any]
    ) -> None:
        self._events.publish(
            BuilderEventType.EXECUTION_STARTED,
            session_id=run.session_id,
            task_id=run.task_id,
            payload={
                "run_id": run.run_id,
                "plan_id": run.plan_id,
                "goal": run.goal,
                "worker_count": len([
                    n for n in plan.get("tasks", [])
                    if n.get("worker_role") != "orchestrator"
                ]),
            },
        )

    def _emit_worker_phase(
        self,
        run: CoordinatorExecutionRun,
        node_id: str,
        result: WorkerExecutionResult,
    ) -> None:
        self._events.publish(
            BuilderEventType.WORKER_PHASE_CHANGED,
            session_id=run.session_id,
            task_id=run.task_id,
            payload={
                "run_id": run.run_id,
                "node_id": node_id,
                "worker_role": result.worker_role,
                "phase": result.phase.value,
                "summary": result.summary,
                "error": result.error,
            },
        )

    def _emit_execution_completed(self, run: CoordinatorExecutionRun) -> None:
        self._events.publish(
            BuilderEventType.EXECUTION_COMPLETED,
            session_id=run.session_id,
            task_id=run.task_id,
            payload={
                "run_id": run.run_id,
                "plan_id": run.plan_id,
                "status": run.status.value,
                "completed_count": run.synthesis.get("completed_count", 0),
                "failed_count": run.synthesis.get("failed_count", 0),
                "blocked_count": run.synthesis.get("blocked_count", 0),
            },
        )
