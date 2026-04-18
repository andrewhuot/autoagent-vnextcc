"""Executable coordinator-worker runtime for Builder plans.

The orchestrator creates a plan; this module turns that plan into durable
worker lifecycle state, role-scoped outputs, events, and coordinator synthesis.
"""

from __future__ import annotations

import os
from typing import Any

from builder.events import BuilderEventType, EventBroker
from builder.orchestrator import BuilderOrchestrator
from builder.skill_runtime import BuildtimeSkillRegistry
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
from builder.worker_adapters import (
    DeterministicWorkerAdapter,
    WorkerAdapter,
    WorkerAdapterContext,
    normalize_worker_adapters,
)
from builder.worker_mode import (
    DEFAULT_WORKER_MODE,
    EffectiveWorkerMode,
    WorkerMode,
    WorkerModeConfigurationError,
    resolve_effective_worker_mode,
    resolve_worker_mode,
)


class CoordinatorWorkerRuntime:
    """Executes persisted coordinator plans with explicit worker state."""

    def __init__(
        self,
        store: BuilderStore,
        orchestrator: BuilderOrchestrator,
        events: EventBroker,
        worker_adapters: dict[SpecialistRole, WorkerAdapter] | None = None,
        default_worker_adapter: WorkerAdapter | None = None,
        worker_mode: WorkerMode | None = None,
        checkpoint_manager: Any | None = None,
        skill_registry: BuildtimeSkillRegistry | None = None,
    ) -> None:
        self._store = store
        self._orchestrator = orchestrator
        self._events = events
        self._worker_adapters = _with_builtin_coordinator_adapters(
            normalize_worker_adapters(worker_adapters)
        )
        self._checkpoint_manager = checkpoint_manager
        self._skill_registry = skill_registry or getattr(orchestrator, "skill_registry", None)
        requested_mode = worker_mode
        env_mode = str(os.environ.get("AGENTLAB_WORKER_MODE", "")).strip().lower()
        env_requested_mode = requested_mode is None and env_mode in {WorkerMode.LLM.value, WorkerMode.HYBRID.value}
        self._worker_mode_resolution: EffectiveWorkerMode | None = None
        self._worker_mode_degraded_reason: str | None = None
        if requested_mode is not None:
            # Operator explicitly pinned a mode — keep existing strict semantics
            # so a broken LLM config surfaces as WorkerModeConfigurationError.
            self._worker_mode = requested_mode
        else:
            resolution = resolve_effective_worker_mode()
            self._worker_mode_resolution = resolution
            self._worker_mode = resolution.mode
        self._default_worker_adapter = (
            default_worker_adapter
            or _build_default_adapter_for_mode(
                self._worker_mode,
                strict=requested_mode is not None or env_requested_mode,
            )
        )
        if (
            default_worker_adapter is None
            and self._worker_mode_resolution is not None
            and self._worker_mode_resolution.source.startswith("autoselect.deterministic")
        ):
            # Auto-selection already chose deterministic; record the reason so
            # the transcript, status bar, and /doctor can surface it. We don't
            # emit the event from __init__ (no active run yet) — callers on the
            # first turn will pick this up via get_worker_mode_degraded_reason().
            self._worker_mode_degraded_reason = self._worker_mode_resolution.reason
        elif (
            default_worker_adapter is None
            and self._worker_mode == WorkerMode.LLM
            and isinstance(self._default_worker_adapter, DeterministicWorkerAdapter)
        ):
            # Non-strict fallback inside _build_default_adapter_for_mode silently
            # downgraded a LLM request to deterministic. Capture a reason for the UI.
            self._worker_mode_degraded_reason = (
                "WorkerMode.LLM was requested but harness.models.worker could not "
                "be satisfied; worker output is from the deterministic stub."
            )
        self._worker_mode_degraded_event_published = False

    @property
    def worker_mode(self) -> WorkerMode:
        """Return the resolved :class:`WorkerMode` backing this runtime."""
        return self._worker_mode

    @property
    def worker_mode_resolution(self) -> EffectiveWorkerMode | None:
        """Return the :class:`EffectiveWorkerMode` used for auto-selection, if any."""
        return self._worker_mode_resolution

    @property
    def worker_mode_degraded_reason(self) -> str | None:
        """Return a one-line reason when the runtime is running deterministic stubs.

        ``None`` means the runtime is running its requested mode cleanly. A
        non-empty string means workers are producing canned output and the
        UI should surface why — missing harness model, missing credentials,
        or a silent LLM-to-deterministic fallback.
        """
        return self._worker_mode_degraded_reason

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
        self._snapshot_before_execution(task, run)
        self._store.save_coordinator_run(run)
        self._remember_run_on_task(task, run)
        self._publish(
            BuilderEventType.COORDINATOR_EXECUTION_STARTED,
            run,
            payload={
                "status": run.status.value,
                "worker_count": len(worker_nodes),
                "worker_roster": self._worker_roster(run),
            },
        )

        if (
            self._worker_mode_degraded_reason is not None
            and not self._worker_mode_degraded_event_published
        ):
            resolution = self._worker_mode_resolution
            self._publish(
                BuilderEventType.COORDINATOR_WORKER_MODE_DEGRADED,
                run,
                payload={
                    "mode": self._worker_mode.value,
                    "reason": self._worker_mode_degraded_reason,
                    "source": resolution.source if resolution else "fallback",
                },
            )
            self._worker_mode_degraded_event_published = True

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
                result = self._act(task, state, context, routed, run)

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
                adapter_name = None
                if isinstance(result.output_payload, dict):
                    adapter_name = result.output_payload.get("adapter")
                self._transition_worker(
                    run,
                    state,
                    WorkerExecutionStatus.COMPLETED,
                    BuilderEventType.WORKER_COMPLETED,
                    {
                        "summary": result.summary,
                        "artifacts": sorted(result.artifacts),
                        "worker_role": state.worker_role.value,
                        "adapter": adapter_name,
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
            payload={
                "status": status.value,
                "owner": state.worker_role.value,
                "title": state.title,
                **payload,
            },
        )

    def _worker_roster(self, run: CoordinatorExecutionRun) -> list[dict[str, Any]]:
        """Return the user-visible worker roster for a coordinator run."""
        return [
            {
                "worker_id": state.node_id,
                "node_id": state.node_id,
                "role": state.worker_role.value,
                "worker_role": state.worker_role.value,
                "owner": state.worker_role.value,
                "title": state.title,
                "status": state.status.value,
                "depends_on": list(state.depends_on),
            }
            for state in run.worker_states
        ]

    def _gather_context(
        self,
        task: BuilderTask,
        plan: dict[str, Any],
        node: dict[str, Any],
        dependency_summaries: dict[str, str],
        run: CoordinatorExecutionRun,
    ) -> dict[str, Any]:
        project = self._store.get_project(task.project_id)
        skill_descriptors = self._resolve_skill_descriptors(plan, node)
        prior_turns, latest_synthesis = self._prior_turn_context(plan)
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
            "buildtime_skill_descriptors": skill_descriptors,
            "expected_artifacts": list(node.get("expected_artifacts", [])),
            "depends_on": list(node.get("depends_on", [])),
            "dependency_summaries": {
                dep: dependency_summaries[dep]
                for dep in node.get("depends_on", [])
                if dep in dependency_summaries
            },
            "provenance": dict(node.get("provenance", {})),
            "deploy": dict(task.metadata.get("deploy") or {}),
            "skills": dict(task.metadata.get("skills") or {}),
            "command_intent": task.metadata.get("command_intent"),
            "prior_turns": prior_turns,
            "latest_synthesis": latest_synthesis,
        }

    def _prior_turn_context(
        self,
        plan: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Return ``(prior_turns, latest_synthesis)`` from the root node."""
        for node in plan.get("tasks", []):
            if not isinstance(node, dict):
                continue
            if node.get("worker_role") != "orchestrator":
                continue
            provenance = node.get("provenance") or {}
            prior = provenance.get("prior_turns") or []
            synthesis = provenance.get("latest_synthesis") or {}
            prior_list = [dict(entry) for entry in prior if isinstance(entry, dict)]
            synthesis_dict = dict(synthesis) if isinstance(synthesis, dict) else {}
            return prior_list, synthesis_dict
        return [], {}

    def _resolve_skill_descriptors(
        self,
        plan: dict[str, Any],
        node: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Return rich descriptors for build-time skills relevant to a node.

        Prefers descriptors already baked into the plan (orchestrator -> registry
        match path). Falls back to a fresh registry lookup keyed on the node's
        ``skill_candidates`` so worker context always has descriptions, not
        just opaque ids.
        """
        plan_skill_context = plan.get("skill_context")
        descriptors: list[dict[str, Any]] = []
        if isinstance(plan_skill_context, dict):
            raw = plan_skill_context.get("buildtime_registry_descriptors")
            if isinstance(raw, list):
                descriptors = [item for item in raw if isinstance(item, dict)]

        if descriptors or self._skill_registry is None:
            return descriptors

        candidates = node.get("skill_candidates")
        if not isinstance(candidates, list):
            return []
        skill_layer = node.get("skill_layer")
        if skill_layer not in {"build", "mixed"}:
            return []
        out: list[dict[str, Any]] = []
        for candidate in candidates:
            if not isinstance(candidate, str) or not candidate:
                continue
            try:
                skill = self._skill_registry.store.get_by_name(candidate)
            except Exception:
                skill = None
            if skill is None or not skill.is_build_time():
                continue
            out.append(self._skill_registry.describe(skill))
        return out

    def _worker_message(self, node: dict[str, Any], goal: str) -> str:
        return (
            f"{node.get('title')}: {node.get('description')} "
            f"Goal: {goal}. Return structured summary and artifacts."
        )

    def _act(
        self,
        task: BuilderTask,
        state: WorkerExecutionState,
        context: dict[str, Any],
        routed: dict[str, Any],
        run: CoordinatorExecutionRun,
    ) -> WorkerExecutionResult:
        adapter = self._worker_adapters.get(state.worker_role, self._default_worker_adapter)
        return adapter.execute(
            WorkerAdapterContext(
                task=task,
                run=run,
                state=state,
                context=context,
                routed=routed,
                store=self._store,
                events=self._events,
            )
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

    def _snapshot_before_execution(
        self,
        task: BuilderTask,
        run: CoordinatorExecutionRun,
    ) -> None:
        """Create a config checkpoint before any worker action runs."""
        manager = self._checkpoint_manager
        if manager is None:
            return
        record = manager.snapshot(reason=f"pre_execution:{run.run_id}")
        if record is None:
            return
        task.metadata["pre_execution_checkpoint_version"] = record.version
        task.metadata["pre_execution_checkpoint_filename"] = record.filename
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
        event_payload = {
            "run_id": run.run_id,
            "plan_id": run.plan_id,
            "node_id": node_id,
            "worker_role": worker_role.value if worker_role else None,
        }
        if node_id is not None:
            event_payload["worker_id"] = node_id
        event_payload.update(payload)
        self._events.publish(
            event_type,
            session_id=run.session_id,
            task_id=run.root_task_id,
            payload=event_payload,
        )


def _with_builtin_coordinator_adapters(
    adapters: dict[SpecialistRole, WorkerAdapter],
) -> dict[SpecialistRole, WorkerAdapter]:
    """Install the V4 + V5 default coordinator workers.

    V4 ships :class:`GateRunnerWorker` / :class:`PlatformPublisherWorker`
    for the deploy roles; V5 ships :class:`SkillAuthorWorker` for
    ``/skills gap`` / ``/skills generate``. Explicit overrides in
    ``worker_adapters`` still win, so tests and integrators can inject
    stubs without touching this default.
    """
    from agent_skills.coordinator_worker import SkillAuthorWorker
    from deployer.coordinator_workers import GateRunnerWorker, PlatformPublisherWorker

    merged = dict(adapters)
    merged.setdefault(SpecialistRole.GATE_RUNNER, GateRunnerWorker())
    merged.setdefault(SpecialistRole.PLATFORM_PUBLISHER, PlatformPublisherWorker())
    merged.setdefault(SpecialistRole.SKILL_AUTHOR, SkillAuthorWorker())
    return merged


def _build_default_adapter_for_mode(
    mode: WorkerMode,
    *,
    strict: bool = False,
) -> WorkerAdapter:
    """Return the default worker adapter for a given mode.

    When ``strict`` is true (operator explicitly requested a non-default
    mode), an unsatisfiable LLM configuration raises
    :class:`WorkerModeConfigurationError` so the REPL surfaces a
    ``/doctor``-actionable diagnostic instead of silently degrading to
    deterministic output. Env-driven mode resolution stays permissive —
    missing config simply keeps deterministic execution.
    """

    if mode == WorkerMode.LLM:
        from builder.llm_worker import LLMWorkerAdapter
        from builder.model_resolver import missing_credential_env, resolve_harness_model
        from optimizer.providers import LLMRouter, RetryPolicy

        resolution = resolve_harness_model("worker")
        if resolution.config is None:
            if strict:
                raise WorkerModeConfigurationError(
                    "WorkerMode.LLM was requested but no worker model resolved "
                    "from harness.models.worker or optimizer.models[0] "
                    f"(resolver source: {resolution.source}). Run /doctor and "
                    "add explicit provider + model keys to agentlab.yaml."
                )
            return DeterministicWorkerAdapter()
        missing_env = missing_credential_env(resolution.config)
        if missing_env:
            if strict:
                raise WorkerModeConfigurationError(
                    "WorkerMode.LLM resolved "
                    f"{resolution.source} ({resolution.config.provider}/{resolution.config.model}) "
                    f"but {missing_env} is not set. Run /doctor to inspect provider settings."
                )
            return DeterministicWorkerAdapter()
        try:
            router = LLMRouter(
                strategy="single",
                models=[resolution.config],
                retry_policy=RetryPolicy(),
            )
            return LLMWorkerAdapter(router=router)
        except Exception as exc:
            if strict:
                raise WorkerModeConfigurationError(
                    f"Failed to construct LLMRouter for worker mode: {exc}. "
                    "Run /doctor to inspect provider settings."
                ) from exc
            return DeterministicWorkerAdapter()
    return DeterministicWorkerAdapter()
