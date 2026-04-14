"""Tests for V1 ``/build`` specialization (worker roster, prompts, apply).

Covers:

- ``_select_worker_roles`` picks the right roster for three goal shapes when
  ``verb="build"`` is forwarded through :func:`plan_work` via
  ``extra_context``.
- ``LLMWorkerAdapter`` honors the V1 artifact contract — each specialized
  role returns the keys downstream synthesis expects.
- :func:`apply_coordinator_synthesis` turns worker artifacts into a valid
  :class:`AgentConfig` diff (guardrails, prompts, tools, config_draft).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.config.schema import AgentConfig
from builder.events import EventBroker
from builder.llm_worker import LLMWorkerAdapter
from builder.orchestrator import BuilderOrchestrator
from builder.store import BuilderStore
from builder.types import (
    BuilderProject,
    BuilderSession,
    BuilderTask,
    CoordinatorExecutionRun,
    CoordinatorExecutionStatus,
    SpecialistRole,
    WorkerExecutionResult,
    WorkerExecutionState,
    WorkerExecutionStatus,
)
from builder.worker_adapters import WorkerAdapterContext
from builder.worker_prompts import get_artifact_contract
from builder.workbench import apply_coordinator_synthesis
from optimizer.providers import LLMRequest, LLMResponse


class _FakeRouter:
    """Canned-response :class:`LLMRouter` stand-in for worker prompt tests."""

    def __init__(self, envelope: dict) -> None:
        self.text = json.dumps(envelope)
        self.calls: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        return LLMResponse(
            provider="fake",
            model="fake-model",
            text=self.text,
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            latency_ms=0.1,
        )


def _make_context(
    *,
    role: SpecialistRole,
    expected_artifacts: list[str],
    goal: str = "build a support agent with a PII guardrail",
) -> WorkerAdapterContext:
    """Build a minimal adapter context for worker-prompt round-trip tests."""
    project = BuilderProject(name="v1 build workers")
    session = BuilderSession(project_id=project.project_id, title="test")
    task = BuilderTask(
        project_id=project.project_id,
        session_id=session.session_id,
        title="Build",
        description=goal,
    )
    state = WorkerExecutionState(
        node_id="plan:w",
        worker_role=role,
        status=WorkerExecutionStatus.ACTING,
    )
    run = CoordinatorExecutionRun(
        plan_id="plan-1",
        root_task_id=task.task_id,
        session_id=session.session_id,
        project_id=project.project_id,
        goal=goal,
        worker_states=[state],
    )
    return WorkerAdapterContext(
        task=task,
        run=run,
        state=state,
        context={
            "goal": goal,
            "context_boundary": "worker",
            "selected_tools": [],
            "skill_candidates": [],
            "permission_scope": ["read"],
            "expected_artifacts": expected_artifacts,
            "dependency_summaries": {},
            "session_id": session.session_id,
            "task_id": task.task_id,
        },
        routed={
            "specialist": role.value,
            "recommended_tools": [],
            "permission_scope": ["read"],
            "display_name": role.value.replace("_", " ").title(),
            "provenance": {"routed_by": "test", "routing_reason": "test"},
        },
        store=BuilderStore(db_path=":memory:"),
        events=EventBroker(),
    )


# ---------------------------------------------------------------------------
# 1. Roster selection for three goal shapes
# ---------------------------------------------------------------------------


def _plan_for_goal(goal: str, tmp_path: Path) -> dict:
    """Create a `/build` plan for ``goal`` and return its persisted dict."""
    store = BuilderStore(db_path=str(tmp_path / "builder.db"))
    orchestrator = BuilderOrchestrator(store=store)
    project = BuilderProject(name="plan-test")
    store.save_project(project)
    session = BuilderSession(project_id=project.project_id, title="plan-test")
    store.save_session(session)
    task = BuilderTask(
        project_id=project.project_id,
        session_id=session.session_id,
        title=goal,
        description=goal,
    )
    store.save_task(task)
    orchestrator.start_session(session)
    return orchestrator.plan_work(
        task=task,
        goal=goal,
        extra_context={"command_intent": "build"},
    )


def _worker_roles(plan: dict) -> list[str]:
    """Return the worker roles (excluding the root orchestrator) in the plan."""
    return [
        node["worker_role"]
        for node in plan["tasks"]
        if node.get("worker_role") and node["worker_role"] != SpecialistRole.ORCHESTRATOR.value
    ]


def test_build_roster_always_includes_baseline(tmp_path: Path) -> None:
    """Every ``/build`` plan gets requirements + build + prompt + eval workers."""
    plan = _plan_for_goal("build me a simple support agent", tmp_path)
    roles = _worker_roles(plan)
    for required in (
        SpecialistRole.REQUIREMENTS_ANALYST.value,
        SpecialistRole.BUILD_ENGINEER.value,
        SpecialistRole.PROMPT_ENGINEER.value,
        SpecialistRole.EVAL_AUTHOR.value,
    ):
        assert required in roles, f"Missing {required} from {roles}"


def test_build_roster_adds_guardrail_and_tool_workers(tmp_path: Path) -> None:
    """Goal mentioning PII + tool picks up GUARDRAIL and TOOL engineers."""
    plan = _plan_for_goal(
        "build a support agent with a PII guardrail and an order-lookup tool",
        tmp_path,
    )
    roles = _worker_roles(plan)
    assert SpecialistRole.GUARDRAIL_AUTHOR.value in roles
    assert SpecialistRole.TOOL_ENGINEER.value in roles
    assert SpecialistRole.REQUIREMENTS_ANALYST.value in roles
    assert SpecialistRole.BUILD_ENGINEER.value in roles


def test_build_roster_picks_up_skill_and_adk_workers(tmp_path: Path) -> None:
    """Goal mentioning skills + sub-agent graph pulls the right specialists."""
    plan = _plan_for_goal(
        "build an agent with a routing topology across sub-agents and attach a manifest skill",
        tmp_path,
    )
    roles = _worker_roles(plan)
    assert SpecialistRole.SKILL_AUTHOR.value in roles
    assert SpecialistRole.ADK_ARCHITECT.value in roles


# ---------------------------------------------------------------------------
# 2. Each specialized role lands its expected artifact
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role, artifact_name, sample_payload",
    [
        (
            SpecialistRole.PROMPT_ENGINEER,
            "prompt_diff",
            {"root": {"before": "a", "after": "b"}},
        ),
        (
            SpecialistRole.GUARDRAIL_AUTHOR,
            "guardrail_policy",
            [{"name": "pii_block", "type": "output", "enforcement": "block"}],
        ),
        (
            SpecialistRole.TOOL_ENGINEER,
            "tool_contract",
            {"orders_db": {"enabled": True, "timeout_ms": 5000, "description": "Lookup"}},
        ),
        (
            SpecialistRole.BUILD_ENGINEER,
            "config_draft",
            {"model": "gemini-2.0-flash"},
        ),
        (
            SpecialistRole.REQUIREMENTS_ANALYST,
            "acceptance_criteria",
            [{"id": "a1", "criterion": "Agent responds within 3s", "verifiable_by": "latency_test"}],
        ),
        (
            SpecialistRole.EVAL_AUTHOR,
            "eval_bundle",
            {"name": "smoke", "cases": [{"prompt": "hi", "expected_behavior": "greets"}]},
        ),
    ],
)
def test_llm_worker_returns_expected_artifact_per_role(
    role: SpecialistRole, artifact_name: str, sample_payload
) -> None:
    """Each V1 build role honors the artifact contract declared in worker_prompts."""
    contracts = get_artifact_contract(role)
    assert artifact_name in contracts, f"Contract for {role.value} missing {artifact_name}"
    expected = list(contracts.keys())
    # Build a full envelope populating every expected artifact; only the
    # parametrized one carries the real sample payload.
    envelope_artifacts: dict = {name: {} for name in expected}
    envelope_artifacts[artifact_name] = sample_payload
    router = _FakeRouter(
        {
            "summary": f"{role.value} produced artifacts",
            "artifacts": envelope_artifacts,
            "output_payload": {"review_required": True},
        }
    )
    adapter = LLMWorkerAdapter(router=router)  # type: ignore[arg-type]
    context = _make_context(role=role, expected_artifacts=expected)

    result = adapter.execute(context)

    assert isinstance(result, WorkerExecutionResult)
    assert result.worker_role == role
    assert artifact_name in result.artifacts
    if sample_payload and isinstance(sample_payload, dict):
        assert result.artifacts[artifact_name] == sample_payload


# ---------------------------------------------------------------------------
# 3. apply_coordinator_synthesis produces a valid AgentConfig diff
# ---------------------------------------------------------------------------


def _fake_run_with(artifacts: dict[SpecialistRole, dict]) -> CoordinatorExecutionRun:
    """Build a completed :class:`CoordinatorExecutionRun` with the given artifacts."""
    states: list[WorkerExecutionState] = []
    for role, role_artifacts in artifacts.items():
        state = WorkerExecutionState(
            node_id=f"plan:{role.value}",
            worker_role=role,
            status=WorkerExecutionStatus.COMPLETED,
        )
        state.result = WorkerExecutionResult(
            node_id=state.node_id,
            worker_role=role,
            summary=f"{role.value} completed",
            artifacts=dict(role_artifacts),
        )
        states.append(state)
    return CoordinatorExecutionRun(
        plan_id="plan-apply",
        root_task_id="task-apply",
        session_id="sess-apply",
        project_id="proj-apply",
        goal="apply test",
        status=CoordinatorExecutionStatus.COMPLETED,
        worker_states=states,
    )


def test_apply_coordinator_synthesis_produces_valid_agent_config_diff() -> None:
    """A realistic V1 ``/build`` synthesis yields a validated AgentConfig diff."""
    base = AgentConfig()
    run = _fake_run_with(
        {
            SpecialistRole.PROMPT_ENGINEER: {
                "prompt_diff": {
                    "root": {
                        "before": base.prompts.root,
                        "after": "You are a customer-support agent. Escalate PII requests.",
                    },
                    "support": {
                        "before": base.prompts.support,
                        "after": "Handle support tickets politely.",
                    },
                },
            },
            SpecialistRole.GUARDRAIL_AUTHOR: {
                "guardrail_policy": [
                    {
                        "name": "pii_block",
                        "type": "output",
                        "enforcement": "block",
                        "description": "Blocks PII leakage.",
                    }
                ],
            },
            SpecialistRole.TOOL_ENGINEER: {
                "tool_contract": {
                    "orders_db": {
                        "enabled": True,
                        "timeout_ms": 7500,
                        "description": "Order lookup.",
                        "parameters": [
                            {"name": "order_id", "type": "string", "required": True}
                        ],
                    }
                },
            },
            SpecialistRole.BUILD_ENGINEER: {
                "config_draft": {
                    "model": "gemini-2.0-flash",
                    "thresholds": {"confidence_threshold": 0.75},
                },
            },
        }
    )

    new_config = apply_coordinator_synthesis(base, run)

    assert isinstance(new_config, AgentConfig)
    # Prompts applied through IR validation
    assert "PII" in new_config.prompts.root
    assert "Handle support" in new_config.prompts.support
    # Guardrail appended and coerced through IR enum validation
    assert any(g.name == "pii_block" and g.enforcement == "block" for g in new_config.guardrails)
    # Tool contract upserted
    assert "orders_db" in new_config.tools_config
    assert new_config.tools_config["orders_db"]["timeout_ms"] == 7500
    # BUILD_ENGINEER config_draft deep-merged last (overrides + thresholds)
    assert new_config.model == "gemini-2.0-flash"
    assert new_config.thresholds.confidence_threshold == 0.75


def test_apply_coordinator_synthesis_is_noop_for_empty_run() -> None:
    """An empty run yields a valid config equal to the input baseline."""
    base = AgentConfig()
    run = CoordinatorExecutionRun(
        plan_id="empty",
        root_task_id="t",
        session_id="s",
        project_id="p",
        status=CoordinatorExecutionStatus.COMPLETED,
        worker_states=[],
    )

    new_config = apply_coordinator_synthesis(base, run)

    assert new_config.model_dump() == base.model_dump()


def test_apply_coordinator_synthesis_dedups_guardrails_by_name() -> None:
    """Guardrails already present by name must not be duplicated."""
    from agent.config.schema import GuardrailConfig

    base = AgentConfig()
    base.guardrails.append(
        GuardrailConfig(
            name="pii_block",
            type="output",
            enforcement="warn",
            description="existing",
        )
    )
    run = _fake_run_with(
        {
            SpecialistRole.GUARDRAIL_AUTHOR: {
                "guardrail_policy": [
                    {
                        "name": "pii_block",
                        "type": "output",
                        "enforcement": "block",
                        "description": "new duplicate",
                    },
                    {
                        "name": "profanity_filter",
                        "type": "both",
                        "enforcement": "log",
                        "description": "new",
                    },
                ]
            }
        }
    )

    new_config = apply_coordinator_synthesis(base, run)

    names = [g.name for g in new_config.guardrails]
    assert names.count("pii_block") == 1
    assert "profanity_filter" in names
    # Original pii_block enforcement is preserved (dedup keeps existing entry).
    pii = next(g for g in new_config.guardrails if g.name == "pii_block")
    assert pii.enforcement == "warn"
