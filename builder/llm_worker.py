"""LLM-backed worker adapter for the coordinator-worker runtime.

This is the F2 execution substrate: instead of returning a deterministic,
role-aware stub, :class:`LLMWorkerAdapter` calls a provider through
:class:`optimizer.providers.LLMRouter`, parses a JSON envelope out of the
response, and hands the coordinator a real :class:`WorkerExecutionResult`.

Operational guarantees:

- Parse / provider failures fall back to the deterministic adapter so a
  broken model or quota trip never aborts the run mid-turn.
- Every adapter run emits a single ``WORKER_MESSAGE_DELTA`` event with the
  raw response text so the REPL can render live worker commentary.
- Expected artifacts declared in the coordinator plan are honored: the LLM
  is required to return them, and missing keys trip the fallback path.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from builder.events import BuilderEventType
from builder.types import (
    SpecialistRole,
    WorkerExecutionResult,
)
from builder.worker_adapters import (
    DeterministicWorkerAdapter,
    WorkerAdapter,
    WorkerAdapterContext,
)
from builder.worker_prompts import build_worker_prompt
from optimizer.providers import LLMRequest, LLMRouter

logger = logging.getLogger(__name__)


class LLMWorkerAdapter:
    """Worker adapter that drives a real provider through :class:`LLMRouter`."""

    name = "llm_worker_adapter"

    def __init__(
        self,
        router: LLMRouter,
        *,
        fallback: WorkerAdapter | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1200,
    ) -> None:
        self._router = router
        self._fallback = fallback or DeterministicWorkerAdapter()
        self._temperature = temperature
        self._max_tokens = max_tokens

    def execute(self, context: WorkerAdapterContext) -> WorkerExecutionResult:
        """Run the LLM worker, returning parsed artifacts or fallback output."""
        prompt = build_worker_prompt(
            state=context.state,
            context=context.context,
            routed=context.routed,
        )
        request = LLMRequest(
            prompt=prompt.user,
            system=prompt.system,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            metadata={
                "worker_role": context.state.worker_role.value,
                "plan_id": context.run.plan_id,
                "run_id": context.run.run_id,
                "node_id": context.state.node_id,
            },
        )
        try:
            response = self._router.generate(request)
        except Exception as exc:
            logger.warning(
                "llm_worker: provider call failed — falling back to deterministic",
                extra={"worker_role": context.state.worker_role.value, "error": str(exc)},
            )
            return self._fallback.execute(context)

        self._emit_message_delta(context, response.text)

        parsed = _parse_envelope(response.text)
        if parsed is None:
            logger.warning(
                "llm_worker: response was not valid JSON envelope — falling back",
                extra={"worker_role": context.state.worker_role.value},
            )
            return self._fallback.execute(context)

        expected = list(context.context.get("expected_artifacts", []))
        artifacts = parsed.get("artifacts") or {}
        if expected and not all(name in artifacts for name in expected):
            logger.warning(
                "llm_worker: response missing expected artifacts — falling back",
                extra={
                    "worker_role": context.state.worker_role.value,
                    "expected": expected,
                    "received": sorted(artifacts.keys()),
                },
            )
            return self._fallback.execute(context)

        return _to_execution_result(
            context=context,
            parsed=parsed,
            provider=response.provider,
            model=response.model,
            total_tokens=response.total_tokens,
        )

    def _emit_message_delta(
        self,
        context: WorkerAdapterContext,
        text: str,
    ) -> None:
        """Publish the raw LLM response as a WORKER_MESSAGE_DELTA event."""
        try:
            context.events.publish(
                BuilderEventType.WORKER_MESSAGE_DELTA,
                context.run.session_id,
                context.run.root_task_id,
                {
                    "run_id": context.run.run_id,
                    "node_id": context.state.node_id,
                    "worker_role": context.state.worker_role.value,
                    "project_id": context.run.project_id,
                    "text": text,
                },
            )
        except Exception:  # pragma: no cover - event bus must not break execution
            pass


def _parse_envelope(text: str) -> dict[str, Any] | None:
    """Parse the JSON envelope emitted by the LLM; ``None`` if malformed."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:]
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    if "summary" not in parsed or "artifacts" not in parsed:
        return None
    return parsed


def _to_execution_result(
    *,
    context: WorkerAdapterContext,
    parsed: dict[str, Any],
    provider: str,
    model: str,
    total_tokens: int,
) -> WorkerExecutionResult:
    """Convert a validated JSON envelope into a :class:`WorkerExecutionResult`."""
    state = context.state
    output_payload = dict(parsed.get("output_payload") or {})
    output_payload.setdefault("adapter", LLMWorkerAdapter.name)
    output_payload.setdefault(
        "specialist", context.routed.get("specialist", state.worker_role.value)
    )
    output_payload.setdefault(
        "recommended_tools", list(context.routed.get("recommended_tools", []))
    )
    output_payload.setdefault(
        "permission_scope", list(context.routed.get("permission_scope", []))
    )
    output_payload.setdefault("review_required", _default_review_required(state.worker_role))

    return WorkerExecutionResult(
        node_id=state.node_id,
        worker_role=state.worker_role,
        summary=str(parsed.get("summary") or "").strip(),
        artifacts=dict(parsed.get("artifacts") or {}),
        context_used={
            "context_boundary": context.context.get("context_boundary"),
            "selected_tools": list(context.context.get("selected_tools", [])),
            "skill_candidates": list(context.context.get("skill_candidates", [])),
            "dependency_summaries": dict(context.context.get("dependency_summaries", {})),
        },
        output_payload=output_payload,
        provenance={
            "run_id": context.run.run_id,
            "plan_id": context.run.plan_id,
            "node_id": state.node_id,
            "routed_by": context.routed.get("provenance", {}).get("routed_by"),
            "routing_reason": context.routed.get("provenance", {}).get("routing_reason"),
            "adapter": LLMWorkerAdapter.name,
            "provider": provider,
            "model": model,
            "total_tokens": total_tokens,
        },
    )


_REVIEW_REQUIRED_DEFAULTS = {
    SpecialistRole.BUILD_ENGINEER: True,
    SpecialistRole.TOOL_ENGINEER: True,
    SpecialistRole.SKILL_AUTHOR: True,
    SpecialistRole.GUARDRAIL_AUTHOR: True,
    SpecialistRole.OPTIMIZATION_ENGINEER: True,
    SpecialistRole.DEPLOYMENT_ENGINEER: True,
    SpecialistRole.RELEASE_MANAGER: True,
}


def _default_review_required(role: SpecialistRole) -> bool:
    """Roles that touch source, policy, or deploy default to review-required."""
    return _REVIEW_REQUIRED_DEFAULTS.get(role, False)


__all__ = [
    "LLMWorkerAdapter",
]
