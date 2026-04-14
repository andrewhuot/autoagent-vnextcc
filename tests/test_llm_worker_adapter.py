"""Tests for the LLM-backed coordinator worker adapter (F2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from builder.coordinator_runtime import CoordinatorWorkerRuntime
from builder.events import BuilderEventType, EventBroker
from builder.llm_worker import LLMWorkerAdapter
from builder.orchestrator import BuilderOrchestrator
from builder.store import BuilderStore
from builder.types import (
    BuilderProject,
    BuilderSession,
    BuilderTask,
    CoordinatorExecutionRun,
    SpecialistRole,
    WorkerExecutionResult,
    WorkerExecutionState,
    WorkerExecutionStatus,
)
from builder.worker_adapters import WorkerAdapterContext
from builder.worker_mode import WorkerMode, resolve_worker_mode
from optimizer.providers import LLMRequest, LLMResponse, LLMRouter, ModelConfig


class _FakeRouter:
    """Minimal :class:`LLMRouter` stand-in for adapter tests."""

    def __init__(self, text: str = '{"summary": "ok", "artifacts": {}}') -> None:
        self.text = text
        self.calls: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        return LLMResponse(
            provider="fake",
            model="fake-model",
            text=self.text,
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            latency_ms=1.0,
        )


def _make_adapter_context(
    *,
    role: SpecialistRole = SpecialistRole.BUILD_ENGINEER,
    expected_artifacts: list[str] | None = None,
) -> WorkerAdapterContext:
    """Build a minimal :class:`WorkerAdapterContext` for unit tests."""
    events = EventBroker()
    store = BuilderStore(db_path=":memory:")
    project = BuilderProject(name="LLM worker test")
    session = BuilderSession(project_id=project.project_id, title="test session")
    task = BuilderTask(
        project_id=project.project_id,
        session_id=session.session_id,
        title="Add guardrail",
        description="add a PII guardrail to the support agent",
    )
    state = WorkerExecutionState(
        node_id="plan:worker-1",
        worker_role=role,
        status=WorkerExecutionStatus.ACTING,
    )
    run = CoordinatorExecutionRun(
        plan_id="plan-1",
        root_task_id=task.task_id,
        session_id=session.session_id,
        project_id=project.project_id,
        goal="add a PII guardrail to the support agent",
        worker_states=[state],
    )
    return WorkerAdapterContext(
        task=task,
        run=run,
        state=state,
        context={
            "goal": run.goal,
            "context_boundary": "worker",
            "selected_tools": ["guardrail_editor"],
            "skill_candidates": [],
            "permission_scope": ["read", "source_write"],
            "expected_artifacts": expected_artifacts or ["guardrail_spec"],
            "dependency_summaries": {},
            "session_id": session.session_id,
            "task_id": task.task_id,
        },
        routed={
            "specialist": role.value,
            "recommended_tools": ["guardrail_editor"],
            "permission_scope": ["read", "source_write"],
            "display_name": role.value.replace("_", " ").title(),
            "provenance": {"routed_by": "builder_orchestrator", "routing_reason": "test"},
        },
        store=store,
        events=events,
    )


def test_llm_worker_parses_structured_response_into_execution_result() -> None:
    """A well-formed JSON envelope should map to a :class:`WorkerExecutionResult`."""
    router = _FakeRouter(
        text=json.dumps(
            {
                "summary": "Drafted guardrail policy",
                "artifacts": {
                    "guardrail_spec": {
                        "name": "pii_block",
                        "level": "block",
                        "description": "Blocks PII leakage in outbound messages.",
                    }
                },
                "output_payload": {
                    "review_required": True,
                    "next_actions": ["Review guardrail before saving."],
                },
            }
        )
    )
    adapter = LLMWorkerAdapter(router=router)  # type: ignore[arg-type]
    context = _make_adapter_context(
        role=SpecialistRole.GUARDRAIL_AUTHOR,
        expected_artifacts=["guardrail_spec"],
    )

    result = adapter.execute(context)

    assert isinstance(result, WorkerExecutionResult)
    assert result.worker_role == SpecialistRole.GUARDRAIL_AUTHOR
    assert result.summary == "Drafted guardrail policy"
    assert "guardrail_spec" in result.artifacts
    assert result.output_payload["adapter"] == LLMWorkerAdapter.name
    assert result.output_payload["review_required"] is True
    assert result.provenance["provider"] == "fake"
    assert result.provenance["model"] == "fake-model"
    assert result.provenance["total_tokens"] == 30
    assert len(router.calls) == 1


def test_llm_worker_emits_worker_message_delta_event() -> None:
    """The adapter should publish the raw response text for streaming UI."""
    router = _FakeRouter(
        text=json.dumps(
            {
                "summary": "done",
                "artifacts": {"guardrail_spec": {}},
                "output_payload": {},
            }
        )
    )
    adapter = LLMWorkerAdapter(router=router)  # type: ignore[arg-type]
    context = _make_adapter_context(
        role=SpecialistRole.GUARDRAIL_AUTHOR,
        expected_artifacts=["guardrail_spec"],
    )

    adapter.execute(context)

    delta_events = [
        event
        for event in context.events.list_events(
            session_id=context.run.session_id, limit=10
        )
        if event.event_type == BuilderEventType.WORKER_MESSAGE_DELTA
    ]
    assert len(delta_events) == 1
    assert delta_events[0].payload["worker_role"] == SpecialistRole.GUARDRAIL_AUTHOR.value
    assert "guardrail_spec" in delta_events[0].payload["text"]


def test_llm_worker_falls_back_when_response_is_not_json() -> None:
    """Malformed responses should route through the deterministic adapter."""
    router = _FakeRouter(text="not a json envelope at all")
    adapter = LLMWorkerAdapter(router=router)  # type: ignore[arg-type]
    context = _make_adapter_context(
        role=SpecialistRole.BUILD_ENGINEER,
        expected_artifacts=["agent_config_candidate"],
    )

    result = adapter.execute(context)

    assert result.output_payload["adapter"] == "deterministic_worker_adapter"


def test_llm_worker_falls_back_when_required_artifacts_missing() -> None:
    """The envelope must include every expected artifact; otherwise fallback."""
    router = _FakeRouter(
        text=json.dumps(
            {
                "summary": "missing artifacts",
                "artifacts": {"unrelated_key": {}},
                "output_payload": {},
            }
        )
    )
    adapter = LLMWorkerAdapter(router=router)  # type: ignore[arg-type]
    context = _make_adapter_context(
        role=SpecialistRole.BUILD_ENGINEER,
        expected_artifacts=["agent_config_candidate"],
    )

    result = adapter.execute(context)

    assert result.output_payload["adapter"] == "deterministic_worker_adapter"


def test_llm_worker_falls_back_when_provider_raises() -> None:
    """Provider errors must never bubble up — deterministic fallback is used."""

    class _ExplodingRouter:
        def generate(self, request: LLMRequest) -> LLMResponse:
            raise RuntimeError("quota exceeded")

    adapter = LLMWorkerAdapter(router=_ExplodingRouter())  # type: ignore[arg-type]
    context = _make_adapter_context(
        role=SpecialistRole.BUILD_ENGINEER,
        expected_artifacts=["agent_config_candidate"],
    )

    result = adapter.execute(context)

    assert result.output_payload["adapter"] == "deterministic_worker_adapter"


def test_resolve_worker_mode_defaults_to_deterministic() -> None:
    """Missing env variable falls back to deterministic mode."""
    assert resolve_worker_mode({}) == WorkerMode.DETERMINISTIC


def test_resolve_worker_mode_reads_env_value() -> None:
    """Valid env values select the matching mode."""
    assert resolve_worker_mode({"AGENTLAB_WORKER_MODE": "llm"}) == WorkerMode.LLM
    assert resolve_worker_mode({"AGENTLAB_WORKER_MODE": "LLM"}) == WorkerMode.LLM
    assert resolve_worker_mode({"AGENTLAB_WORKER_MODE": "hybrid"}) == WorkerMode.HYBRID


def test_resolve_worker_mode_falls_back_on_unknown_value() -> None:
    """Bad values must never crash startup."""
    assert resolve_worker_mode({"AGENTLAB_WORKER_MODE": "rainbow"}) == WorkerMode.DETERMINISTIC


def test_resolve_harness_model_reads_harness_section(tmp_path: Path) -> None:
    """``harness.models.<role>`` should take precedence over optimizer.models."""
    from builder.model_resolver import resolve_harness_model

    config = tmp_path / "agentlab.yaml"
    config.write_text(
        """
harness:
  models:
    worker:
      provider: anthropic
      model: claude-sonnet-4-6
      api_key_env: ANTHROPIC_API_KEY
    coordinator:
      provider: anthropic
      model: claude-opus-4-6
      api_key_env: ANTHROPIC_API_KEY
optimizer:
  models:
    - provider: google
      model: gemini-2.5-flash
""",
        encoding="utf-8",
    )

    worker = resolve_harness_model("worker", config_path=config)
    coordinator = resolve_harness_model("coordinator", config_path=config)

    assert worker.config is not None
    assert worker.config.provider == "anthropic"
    assert worker.config.model == "claude-sonnet-4-6"
    assert worker.source == "harness.models.worker"
    assert coordinator.config is not None
    assert coordinator.config.model == "claude-opus-4-6"


def test_resolve_harness_model_falls_back_to_optimizer_models(tmp_path: Path) -> None:
    """When harness.models is absent, fall back to the first optimizer model."""
    from builder.model_resolver import resolve_harness_model

    config = tmp_path / "agentlab.yaml"
    config.write_text(
        """
optimizer:
  models:
    - provider: google
      model: gemini-2.5-flash
      api_key_env: GOOGLE_API_KEY
""",
        encoding="utf-8",
    )

    worker = resolve_harness_model("worker", config_path=config)

    assert worker.config is not None
    assert worker.config.provider == "google"
    assert worker.source == "optimizer.models[0]"


def test_resolve_harness_model_returns_missing_when_nothing_configured(tmp_path: Path) -> None:
    """Empty configs must not raise — caller decides how to degrade."""
    from builder.model_resolver import resolve_harness_model

    config = tmp_path / "agentlab.yaml"
    config.write_text("", encoding="utf-8")

    resolution = resolve_harness_model("worker", config_path=config)

    assert resolution.config is None
    assert resolution.source == "missing"


def test_coordinator_runtime_uses_deterministic_adapter_by_default(tmp_path: Path) -> None:
    """Default construction produces a deterministic-mode runtime."""
    store = BuilderStore(db_path=str(tmp_path / "runtime.db"))
    orchestrator = BuilderOrchestrator(store=store)
    runtime = CoordinatorWorkerRuntime(
        store=store,
        orchestrator=orchestrator,
        events=EventBroker(),
    )

    assert runtime.worker_mode == WorkerMode.DETERMINISTIC


def test_coordinator_runtime_reports_llm_mode_when_requested(tmp_path: Path) -> None:
    """Explicit WorkerMode.LLM is preserved even if provider config is missing."""
    store = BuilderStore(db_path=str(tmp_path / "runtime.db"))
    orchestrator = BuilderOrchestrator(store=store)

    runtime = CoordinatorWorkerRuntime(
        store=store,
        orchestrator=orchestrator,
        events=EventBroker(),
        worker_mode=WorkerMode.LLM,
    )

    assert runtime.worker_mode == WorkerMode.LLM
