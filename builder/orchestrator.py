"""Builder orchestrator that routes work between specialist subagents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from builder.specialists import (
    SpecialistDefinition,
    detect_specialist_by_intent,
    get_specialist,
    get_specialist_keywords,
    list_specialists,
)
from builder.store import BuilderStore
from builder.types import BuilderProject, BuilderSession, BuilderTask, SpecialistRole, new_id, now_ts


COORDINATOR_WORKER_ORDER: tuple[SpecialistRole, ...] = (
    SpecialistRole.BUILD_ENGINEER,
    SpecialistRole.REQUIREMENTS_ANALYST,
    SpecialistRole.PROMPT_ENGINEER,
    SpecialistRole.ADK_ARCHITECT,
    SpecialistRole.TOOL_ENGINEER,
    SpecialistRole.SKILL_AUTHOR,
    SpecialistRole.GUARDRAIL_AUTHOR,
    SpecialistRole.EVAL_AUTHOR,
    SpecialistRole.OPTIMIZATION_ENGINEER,
    SpecialistRole.TRACE_ANALYST,
    SpecialistRole.DEPLOYMENT_ENGINEER,
    SpecialistRole.RELEASE_MANAGER,
)


_ROLE_SKILL_LAYER: dict[SpecialistRole, str] = {
    SpecialistRole.ORCHESTRATOR: "none",
    SpecialistRole.BUILD_ENGINEER: "build",
    SpecialistRole.REQUIREMENTS_ANALYST: "build",
    SpecialistRole.PROMPT_ENGINEER: "build",
    SpecialistRole.ADK_ARCHITECT: "build",
    SpecialistRole.TOOL_ENGINEER: "runtime",
    SpecialistRole.SKILL_AUTHOR: "mixed",
    SpecialistRole.GUARDRAIL_AUTHOR: "build",
    SpecialistRole.EVAL_AUTHOR: "build",
    SpecialistRole.OPTIMIZATION_ENGINEER: "build",
    SpecialistRole.TRACE_ANALYST: "none",
    SpecialistRole.DEPLOYMENT_ENGINEER: "none",
    SpecialistRole.RELEASE_MANAGER: "none",
}


_ROLE_EXPECTED_ARTIFACTS: dict[SpecialistRole, list[str]] = {
    SpecialistRole.ORCHESTRATOR: ["coordinator_plan", "synthesis"],
    SpecialistRole.BUILD_ENGINEER: ["source_diff", "config_draft", "test_evidence"],
    SpecialistRole.REQUIREMENTS_ANALYST: ["acceptance_criteria", "risk_notes"],
    SpecialistRole.PROMPT_ENGINEER: ["prompt_diff", "instruction_summary", "prompt_regression_cases"],
    SpecialistRole.ADK_ARCHITECT: ["agent_graph_diff", "topology_validation"],
    SpecialistRole.TOOL_ENGINEER: ["tool_contract", "integration_test"],
    SpecialistRole.SKILL_AUTHOR: ["skill_manifest", "skill_validation"],
    SpecialistRole.GUARDRAIL_AUTHOR: ["guardrail_policy", "safety_test_cases"],
    SpecialistRole.EVAL_AUTHOR: ["eval_bundle", "benchmark_plan"],
    SpecialistRole.OPTIMIZATION_ENGINEER: ["optimization_plan", "change_card", "experiment_summary"],
    SpecialistRole.TRACE_ANALYST: ["trace_evidence", "root_cause_summary"],
    SpecialistRole.DEPLOYMENT_ENGINEER: ["deployment_plan", "canary_check", "rollback_plan"],
    SpecialistRole.RELEASE_MANAGER: ["release_candidate", "promotion_evidence"],
}


_ROLE_TASK_TITLES: dict[SpecialistRole, str] = {
    SpecialistRole.ORCHESTRATOR: "Synthesize coordinator-worker plan",
    SpecialistRole.BUILD_ENGINEER: "Build or implement the agent change",
    SpecialistRole.REQUIREMENTS_ANALYST: "Clarify requirements and acceptance criteria",
    SpecialistRole.PROMPT_ENGINEER: "Refine prompts and instructions",
    SpecialistRole.ADK_ARCHITECT: "Design agent graph architecture",
    SpecialistRole.TOOL_ENGINEER: "Implement tools and integrations",
    SpecialistRole.SKILL_AUTHOR: "Author or revise skills",
    SpecialistRole.GUARDRAIL_AUTHOR: "Add guardrails and safety tests",
    SpecialistRole.EVAL_AUTHOR: "Create evals and benchmarks",
    SpecialistRole.OPTIMIZATION_ENGINEER: "Optimize from eval evidence",
    SpecialistRole.TRACE_ANALYST: "Analyze traces and failure evidence",
    SpecialistRole.DEPLOYMENT_ENGINEER: "Plan deploy, canary, and rollback",
    SpecialistRole.RELEASE_MANAGER: "Package release candidate",
}


_BUILD_VERB_BASELINE: tuple[SpecialistRole, ...] = (
    SpecialistRole.REQUIREMENTS_ANALYST,
    SpecialistRole.BUILD_ENGINEER,
    SpecialistRole.PROMPT_ENGINEER,
    SpecialistRole.EVAL_AUTHOR,
)


_VERB_BASELINE_ROLES: dict[str, tuple[SpecialistRole, ...]] = {
    "build": _BUILD_VERB_BASELINE,
    "eval": (SpecialistRole.EVAL_AUTHOR, SpecialistRole.TRACE_ANALYST),
    "optimize": (
        SpecialistRole.TRACE_ANALYST,
        SpecialistRole.OPTIMIZATION_ENGINEER,
    ),
    "deploy": (
        SpecialistRole.DEPLOYMENT_ENGINEER,
        SpecialistRole.RELEASE_MANAGER,
    ),
    "skills": (SpecialistRole.SKILL_AUTHOR,),
}


_BUILD_KEYWORD_ROLES: tuple[tuple[tuple[str, ...], SpecialistRole], ...] = (
    (("guardrail", "pii", "policy", "safety", "moderation", "compliance"), SpecialistRole.GUARDRAIL_AUTHOR),
    (("tool", "integration", "api", "endpoint", "connector", "lookup"), SpecialistRole.TOOL_ENGINEER),
    (("skill", "skills", "manifest", "playbook"), SpecialistRole.SKILL_AUTHOR),
    (("graph", "topology", "sub-agent", "sub agent", "subagent", "adk"), SpecialistRole.ADK_ARCHITECT),
    (("eval", "benchmark", "regression", "quality"), SpecialistRole.EVAL_AUTHOR),
)


def _verb_baseline_roles(verb: str) -> tuple[SpecialistRole, ...]:
    """Return the baseline worker roster for a verb (empty when unknown)."""
    return _VERB_BASELINE_ROLES.get(verb, ())


def _build_keyword_augmentation(text: str) -> list[SpecialistRole]:
    """Select extra build-time roles from keywords in the goal text."""
    extras: list[SpecialistRole] = []
    for keywords, role in _BUILD_KEYWORD_ROLES:
        if any(keyword in text for keyword in keywords):
            extras.append(role)
    return extras


@dataclass
class HandoffRecord:
    """Record representing a specialist-to-specialist handoff."""

    session_id: str
    task_id: str
    from_role: SpecialistRole
    to_role: SpecialistRole
    reason: str
    timestamp: float = field(default_factory=now_ts)


@dataclass(frozen=True)
class WorkerCapability:
    """Serializable capability contract for one builder worker role."""

    role: SpecialistRole
    display_name: str
    description: str
    tools: list[str]
    permission_scope: list[str]
    trigger_keywords: list[str]
    skill_layer: str
    expected_artifacts: list[str]
    can_call_skills: bool

    def to_dict(self) -> dict[str, Any]:
        """Return the API-safe representation of this worker capability."""

        return {
            "role": self.role.value,
            "display_name": self.display_name,
            "description": self.description,
            "tools": list(self.tools),
            "permission_scope": list(self.permission_scope),
            "trigger_keywords": list(self.trigger_keywords),
            "skill_layer": self.skill_layer,
            "expected_artifacts": list(self.expected_artifacts),
            "can_call_skills": self.can_call_skills,
        }


@dataclass
class CoordinatorTask:
    """One node in a coordinator-owned worker task graph."""

    task_id: str
    title: str
    description: str
    worker_role: SpecialistRole
    depends_on: list[str]
    selected_tools: list[str]
    skill_layer: str
    skill_candidates: list[str]
    permission_scope: list[str]
    expected_artifacts: list[str]
    routing_reason: str
    status: str = "planned"
    provenance: dict[str, Any] = field(default_factory=dict)
    materialized_task_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return the API-safe representation of this task graph node."""

        payload = {
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "worker_role": self.worker_role.value,
            "depends_on": list(self.depends_on),
            "selected_tools": list(self.selected_tools),
            "skill_layer": self.skill_layer,
            "skill_candidates": list(self.skill_candidates),
            "permission_scope": list(self.permission_scope),
            "expected_artifacts": list(self.expected_artifacts),
            "routing_reason": self.routing_reason,
            "status": self.status,
            "provenance": dict(self.provenance),
        }
        if self.materialized_task_id:
            payload["materialized_task_id"] = self.materialized_task_id
        return payload


@dataclass
class CoordinatorPlan:
    """Coordinator-owned plan for routing work across specialized workers."""

    plan_id: str
    root_task_id: str
    session_id: str
    project_id: str
    goal: str
    tasks: list[CoordinatorTask]
    worker_registry: list[dict[str, Any]]
    skill_context: dict[str, Any]
    synthesis: dict[str, Any]
    created_at: float = field(default_factory=now_ts)
    mode: str = "coordinator_worker"

    def to_dict(self) -> dict[str, Any]:
        """Return the API-safe representation of this coordinator plan."""

        return {
            "plan_id": self.plan_id,
            "mode": self.mode,
            "root_task_id": self.root_task_id,
            "session_id": self.session_id,
            "project_id": self.project_id,
            "goal": self.goal,
            "tasks": [task.to_dict() for task in self.tasks],
            "worker_registry": list(self.worker_registry),
            "skill_context": dict(self.skill_context),
            "synthesis": dict(self.synthesis),
            "created_at": self.created_at,
        }


class BuilderOrchestrator:
    """Routes task intent to specialists and tracks handoff state."""

    def __init__(self, store: BuilderStore) -> None:
        self._store = store
        self._active_specialist_by_session: dict[str, SpecialistRole] = {}
        self._handoffs_by_session: dict[str, list[HandoffRecord]] = {}

    def start_session(self, session: BuilderSession) -> None:
        """Initialize orchestrator runtime state for the provided session."""

        self._active_specialist_by_session.setdefault(session.session_id, session.active_specialist)
        self._handoffs_by_session.setdefault(session.session_id, [])

    def get_active_specialist(self, session_id: str) -> SpecialistRole:
        """Return active specialist role for a session."""

        return self._active_specialist_by_session.get(session_id, SpecialistRole.ORCHESTRATOR)

    def detect_specialist(self, message: str) -> SpecialistRole:
        """Detect the best specialist for a natural-language message."""

        return detect_specialist_by_intent(message)

    def route_request(
        self,
        session_id: str,
        task_id: str,
        message: str,
        explicit_role: SpecialistRole | None = None,
    ) -> SpecialistRole:
        """Select and activate the specialist for a request, recording handoffs."""

        target = explicit_role or self.detect_specialist(message)
        current = self.get_active_specialist(session_id)
        if current != target:
            self._record_handoff(
                session_id=session_id,
                task_id=task_id,
                from_role=current,
                to_role=target,
                reason="explicit" if explicit_role else "intent_detection",
            )
        self._active_specialist_by_session[session_id] = target
        self._persist_session_specialist(session_id, target)
        return target

    def invoke_specialist(
        self,
        task: BuilderTask,
        message: str,
        explicit_role: SpecialistRole | None = None,
        extra_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Route and invoke a specialist with task/session context."""

        role = self.route_request(
            session_id=task.session_id,
            task_id=task.task_id,
            message=message,
            explicit_role=explicit_role,
        )
        definition = get_specialist(role)
        task.active_specialist = role
        task.updated_at = now_ts()
        self._store.save_task(task)

        context = {
            "project_id": task.project_id,
            "session_id": task.session_id,
            "task_id": task.task_id,
            "task_title": task.title,
            "message": message,
        }
        if extra_context:
            context.update(extra_context)

        capability = self.worker_capability(role)
        routing_reason = "explicit" if explicit_role else "intent_detection"
        return {
            "specialist": role.value,
            "display_name": definition.display_name,
            "description": definition.description,
            "tools": definition.tools,
            "permission_scope": definition.permission_scope,
            "context_template": definition.context_template,
            "context": context,
            "worker_capability": capability.to_dict(),
            "recommended_tools": list(capability.tools),
            "provenance": {
                "routed_by": "builder_orchestrator",
                "routing_reason": routing_reason,
                "session_id": task.session_id,
                "task_id": task.task_id,
                "project_id": task.project_id,
            },
            "timestamp": now_ts(),
        }

    def worker_capability(self, role: SpecialistRole) -> WorkerCapability:
        """Return the typed worker capability contract for a specialist role."""

        definition = get_specialist(role)
        skill_layer = _ROLE_SKILL_LAYER.get(role, "none")
        return WorkerCapability(
            role=role,
            display_name=definition.display_name,
            description=definition.description,
            tools=list(definition.tools),
            permission_scope=list(definition.permission_scope),
            trigger_keywords=list(get_specialist_keywords(role)),
            skill_layer=skill_layer,
            expected_artifacts=list(_ROLE_EXPECTED_ARTIFACTS.get(role, [])),
            can_call_skills=skill_layer in {"build", "runtime", "mixed"},
        )

    def list_worker_capabilities(self) -> list[dict[str, Any]]:
        """Return the worker capability registry in deterministic role order."""

        return [self.worker_capability(role).to_dict() for role in SpecialistRole]

    def plan_work(
        self,
        task: BuilderTask,
        goal: str,
        requested_roles: list[SpecialistRole] | None = None,
        materialize_tasks: bool = False,
        extra_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build and persist a coordinator-owned task graph for worker execution.

        The plan is intentionally deterministic and non-LLM-backed. It gives
        the builder a production-safe worker routing contract before a future
        runtime executes any worker autonomously.
        """

        normalized_goal = " ".join(str(goal or task.description or task.title).split())
        project = self._store.get_project(task.project_id)
        verb = str((extra_context or {}).get("command_intent") or "").strip().lower()
        roles = self._select_worker_roles(
            normalized_goal,
            requested_roles=requested_roles,
            verb=verb or None,
        )
        plan_id = f"coord-{new_id()}"
        skill_context = self._build_skill_context(project)

        root_node_id = f"{plan_id}:coordinator"
        tasks = [
            self._coordinator_task_node(
                node_id=root_node_id,
                task=task,
                goal=normalized_goal,
                skill_context=skill_context,
                extra_context=extra_context or {},
            )
        ]
        for index, role in enumerate(roles, start=1):
            tasks.append(
                self._worker_task_node(
                    node_id=f"{plan_id}:worker-{index}",
                    root_node_id=root_node_id,
                    role=role,
                    task=task,
                    goal=normalized_goal,
                    project=project,
                    extra_context=extra_context or {},
                )
            )

        plan = CoordinatorPlan(
            plan_id=plan_id,
            root_task_id=task.task_id,
            session_id=task.session_id,
            project_id=task.project_id,
            goal=normalized_goal,
            tasks=tasks,
            worker_registry=self.list_worker_capabilities(),
            skill_context=skill_context,
            synthesis=self._build_plan_synthesis(roles, materialize_tasks=materialize_tasks),
        )

        if materialize_tasks:
            self._materialize_worker_tasks(plan, task)

        plan_dict = plan.to_dict()
        task.metadata["coordinator_plan"] = plan_dict
        task.updated_at = now_ts()
        self._store.save_task(task)
        return plan_dict

    def list_roster(self, session_id: str) -> list[dict[str, Any]]:
        """Return specialist roster for UI display with active/idle status."""

        active = self.get_active_specialist(session_id)
        roster: list[dict[str, Any]] = []
        capabilities = {item["role"]: item for item in self.list_worker_capabilities()}
        for specialist in list_specialists():
            roster.append(
                {
                    "role": specialist.role.value,
                    "display_name": specialist.display_name,
                    "description": specialist.description,
                    "tools": specialist.tools,
                    "permission_scope": specialist.permission_scope,
                    "context_template": specialist.context_template,
                    "worker_capability": capabilities.get(specialist.role.value),
                    "status": "active" if specialist.role == active else "idle",
                }
            )
        return roster

    def get_handoffs(self, session_id: str) -> list[HandoffRecord]:
        """Return handoff history for a session."""

        return list(self._handoffs_by_session.get(session_id, []))

    def get_handoffs_dict(self, session_id: str) -> list[dict[str, Any]]:
        """Return handoff history serialized for API responses."""

        return [
            {
                "session_id": handoff.session_id,
                "task_id": handoff.task_id,
                "from_role": handoff.from_role.value,
                "to_role": handoff.to_role.value,
                "reason": handoff.reason,
                "timestamp": handoff.timestamp,
            }
            for handoff in self.get_handoffs(session_id)
        ]

    def _record_handoff(
        self,
        session_id: str,
        task_id: str,
        from_role: SpecialistRole,
        to_role: SpecialistRole,
        reason: str,
    ) -> None:
        handoff = HandoffRecord(
            session_id=session_id,
            task_id=task_id,
            from_role=from_role,
            to_role=to_role,
            reason=reason,
        )
        self._handoffs_by_session.setdefault(session_id, []).append(handoff)

    def _persist_session_specialist(self, session_id: str, role: SpecialistRole) -> None:
        session = self._store.get_session(session_id)
        if session is None:
            return
        session.active_specialist = role
        session.updated_at = now_ts()
        self._store.save_session(session)

    def _select_worker_roles(
        self,
        goal: str,
        requested_roles: list[SpecialistRole] | None = None,
        verb: str | None = None,
    ) -> list[SpecialistRole]:
        """Choose worker roles for a goal using verb + keyword matches.

        Precedence:

        1. ``requested_roles`` — explicit set from caller wins.
        2. ``verb`` — when provided, seed the roster with a verb-scoped
           baseline so every ``/build`` run always gets requirements +
           build + prompt workers, then augment with keyword matches so
           goals mentioning tools, guardrails, skills, or evals pick up
           the matching specialist.
        3. Otherwise fall back to pure keyword matching.
        """

        if requested_roles:
            return [
                role
                for role in COORDINATOR_WORKER_ORDER
                if role in requested_roles and role != SpecialistRole.ORCHESTRATOR
            ]

        text = goal.lower()
        selected: set[SpecialistRole] = set()

        if verb:
            selected.update(_verb_baseline_roles(verb))

        for role in COORDINATOR_WORKER_ORDER:
            keywords = get_specialist_keywords(role)
            if any(keyword in text for keyword in keywords):
                selected.add(role)

        if verb == "build":
            selected.update(_build_keyword_augmentation(text))

        if "agent" in text and not selected:
            selected.add(SpecialistRole.BUILD_ENGINEER)
        if not selected:
            selected.add(SpecialistRole.BUILD_ENGINEER)

        return [role for role in COORDINATOR_WORKER_ORDER if role in selected]

    def _coordinator_task_node(
        self,
        node_id: str,
        task: BuilderTask,
        goal: str,
        skill_context: dict[str, Any],
        extra_context: dict[str, Any],
    ) -> CoordinatorTask:
        """Create the root coordination node for a plan."""

        capability = self.worker_capability(SpecialistRole.ORCHESTRATOR)
        return CoordinatorTask(
            task_id=node_id,
            title=_ROLE_TASK_TITLES[SpecialistRole.ORCHESTRATOR],
            description=(
                "Own the plan, route worker tasks, synthesize results, and keep next steps auditable."
            ),
            worker_role=SpecialistRole.ORCHESTRATOR,
            depends_on=[],
            selected_tools=capability.tools,
            skill_layer=capability.skill_layer,
            skill_candidates=[],
            permission_scope=capability.permission_scope,
            expected_artifacts=capability.expected_artifacts,
            routing_reason="root_coordinator",
            provenance={
                "routed_by": "builder_orchestrator",
                "routing_reason": "root_coordinator",
                "goal": goal,
                "project_buildtime_skills": skill_context["buildtime_skills"],
                "project_runtime_skills": skill_context["runtime_skills"],
                "extra_context_keys": sorted(extra_context),
                "source_task_id": task.task_id,
            },
        )

    def _worker_task_node(
        self,
        node_id: str,
        root_node_id: str,
        role: SpecialistRole,
        task: BuilderTask,
        goal: str,
        project: BuilderProject | None,
        extra_context: dict[str, Any],
    ) -> CoordinatorTask:
        """Create one worker node with tool, skill, and provenance boundaries."""

        capability = self.worker_capability(role)
        matched = [
            keyword
            for keyword in capability.trigger_keywords
            if keyword in goal.lower()
        ]
        routing_reason = (
            f"matched keywords: {', '.join(matched)}"
            if matched
            else "default builder worker"
        )
        return CoordinatorTask(
            task_id=node_id,
            title=_ROLE_TASK_TITLES.get(role, capability.display_name),
            description=capability.description,
            worker_role=role,
            depends_on=[root_node_id],
            selected_tools=capability.tools,
            skill_layer=capability.skill_layer,
            skill_candidates=self._skill_candidates_for_role(project, capability),
            permission_scope=capability.permission_scope,
            expected_artifacts=capability.expected_artifacts,
            routing_reason=routing_reason,
            provenance={
                "routed_by": "builder_orchestrator",
                "routing_reason": routing_reason,
                "source_task_id": task.task_id,
                "session_id": task.session_id,
                "project_id": task.project_id,
                "extra_context_keys": sorted(extra_context),
            },
        )

    def _build_skill_context(self, project: BuilderProject | None) -> dict[str, Any]:
        """Return project skill context safe to include in coordinator plans."""

        return {
            "buildtime_skills": list(project.buildtime_skills if project else []),
            "runtime_skills": list(project.runtime_skills if project else []),
            "skill_store_loaded": project is not None,
        }

    def _skill_candidates_for_role(
        self,
        project: BuilderProject | None,
        capability: WorkerCapability,
    ) -> list[str]:
        """Select project skill names that a worker may consider, without applying them."""

        if project is None:
            return []
        if capability.skill_layer == "build":
            return list(project.buildtime_skills)
        if capability.skill_layer == "runtime":
            return list(project.runtime_skills)
        if capability.skill_layer == "mixed":
            return list(dict.fromkeys([*project.buildtime_skills, *project.runtime_skills]))
        return []

    def _build_plan_synthesis(
        self,
        roles: list[SpecialistRole],
        *,
        materialize_tasks: bool,
    ) -> dict[str, Any]:
        """Summarize the coordinator plan and recommend the next operator step."""

        role_values = [role.value for role in roles]
        return {
            "summary": (
                "Coordinator planned specialized worker tasks for "
                f"{', '.join(role_values) if role_values else 'build_engineer'}."
            ),
            "worker_count": len(roles),
            "next_step": (
                "Start with the first materialized worker task."
                if materialize_tasks
                else "Start with the first planned worker task."
            ),
            "safety": (
                "Worker tasks declare tools, permission scopes, skill candidates, and expected artifacts; "
                "deployment remains gated by existing deployment/review paths."
            ),
        }

    def _materialize_worker_tasks(self, plan: CoordinatorPlan, parent_task: BuilderTask) -> None:
        """Persist planned worker nodes as child BuilderTask records."""

        session = self._store.get_session(parent_task.session_id)
        for node in plan.tasks:
            if node.worker_role == SpecialistRole.ORCHESTRATOR:
                continue
            child = BuilderTask(
                session_id=parent_task.session_id,
                project_id=parent_task.project_id,
                title=node.title,
                description=node.description,
                mode=parent_task.mode,
                active_specialist=node.worker_role,
                parent_task_id=parent_task.task_id,
                metadata={
                    "coordinator_plan_id": plan.plan_id,
                    "coordinator_root_task_id": parent_task.task_id,
                    "coordinator_node_id": node.task_id,
                    "worker_role": node.worker_role.value,
                    "selected_tools": list(node.selected_tools),
                    "skill_candidates": list(node.skill_candidates),
                    "expected_artifacts": list(node.expected_artifacts),
                    "provenance": dict(node.provenance),
                },
            )
            self._store.save_task(child)
            node.materialized_task_id = child.task_id
            if session is not None and child.task_id not in session.task_ids:
                session.task_ids.append(child.task_id)

        if session is not None:
            session.updated_at = now_ts()
            self._store.save_session(session)


def specialist_definition(role: SpecialistRole) -> SpecialistDefinition:
    """Expose specialist lookups for consumers that need metadata only."""

    return get_specialist(role)
