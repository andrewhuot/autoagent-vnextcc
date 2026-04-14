"""Worker adapter that executes a build-time skill in the coordinator runtime.

Where :class:`builder.llm_worker.LLMWorkerAdapter` runs an open-ended LLM
prompt for a specialist role, this adapter executes a single bounded
build-time skill — either by invoking a ``py:module.fn`` callable or by
running the skill's markdown playbook through an LLM. It is the runtime
counterpart to :class:`builder.skill_runtime.BuildtimeSkillRegistry`.

Selection contract: the orchestrator (or another worker pre-step) writes
``skill_id`` into the worker's routed extra context. When that key is
present, the coordinator binds this adapter to the node; otherwise the
default :class:`LLMWorkerAdapter` runs.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from builder.events import BuilderEventType
from builder.skill_runtime import BuildtimeSkillRegistry, SkillInvocationResult
from builder.types import WorkerExecutionResult
from builder.worker_adapters import (
    DeterministicWorkerAdapter,
    WorkerAdapter,
    WorkerAdapterContext,
)
from optimizer.providers import LLMRequest, LLMRouter

logger = logging.getLogger(__name__)


class SkillInvocationWorker:
    """Worker adapter that executes a single build-time skill."""

    name = "skill_invocation_worker"

    def __init__(
        self,
        registry: BuildtimeSkillRegistry,
        *,
        router: LLMRouter | None = None,
        fallback: WorkerAdapter | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1200,
    ) -> None:
        self._registry = registry
        self._router = router
        self._fallback = fallback or DeterministicWorkerAdapter()
        self._temperature = temperature
        self._max_tokens = max_tokens

    def execute(self, context: WorkerAdapterContext) -> WorkerExecutionResult:
        """Run the configured skill and return a structured worker result."""
        skill_id = self._resolve_skill_id(context)
        if not skill_id:
            logger.info(
                "skill_invocation_worker: no skill_id in context — falling back",
                extra={"node_id": context.state.node_id},
            )
            return self._fallback.execute(context)

        try:
            invocation = self._registry.invoke(skill_id, context.context)
        except Exception as exc:
            logger.warning(
                "skill_invocation_worker: registry invocation failed — falling back",
                extra={
                    "skill_id": skill_id,
                    "node_id": context.state.node_id,
                    "error": str(exc),
                },
            )
            return self._fallback.execute(context)

        if invocation.mode == "callable":
            return self._result_from_invocation(context, invocation, provider="callable")

        if self._router is None:
            return self._result_from_invocation(
                context,
                invocation,
                provider="playbook_no_router",
            )
        return self._run_playbook(context, invocation)

    def _resolve_skill_id(self, context: WorkerAdapterContext) -> str | None:
        """Extract the configured skill_id from routed context, if any."""
        routed_extra = context.routed.get("context") or {}
        if not isinstance(routed_extra, dict):
            routed_extra = {}
        skill_id = routed_extra.get("skill_id") or context.context.get("skill_id")
        if not skill_id:
            candidates = context.context.get("skill_candidates") or []
            if isinstance(candidates, list) and candidates:
                first = candidates[0]
                if isinstance(first, str):
                    skill_id = first
        return skill_id if isinstance(skill_id, str) and skill_id else None

    def _run_playbook(
        self,
        context: WorkerAdapterContext,
        invocation: SkillInvocationResult,
    ) -> WorkerExecutionResult:
        """Execute a markdown playbook through the LLM router."""
        prompt = self._build_playbook_prompt(context, invocation)
        request = LLMRequest(
            prompt=prompt,
            system=(
                "You are executing a build-time skill playbook for AgentLab. "
                "Return a single JSON object with keys 'summary', 'artifacts', "
                "and 'output_payload'. Honor the playbook instructions exactly."
            ),
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            metadata={
                "skill_id": invocation.skill_id,
                "skill_name": invocation.skill_name,
                "node_id": context.state.node_id,
                "plan_id": context.run.plan_id,
                "run_id": context.run.run_id,
            },
        )
        try:
            response = self._router.generate(request)
        except Exception as exc:
            logger.warning(
                "skill_invocation_worker: LLM playbook call failed — falling back to playbook descriptor",
                extra={"skill_id": invocation.skill_id, "error": str(exc)},
            )
            return self._result_from_invocation(
                context,
                invocation,
                provider="playbook_router_error",
            )

        self._emit_message_delta(context, response.text)

        parsed = _parse_envelope(response.text)
        if parsed is None:
            return self._result_from_invocation(
                context,
                invocation,
                provider=response.provider,
                model=response.model,
                raw_text=response.text,
            )
        merged_artifacts = {**invocation.artifacts, **(parsed.get("artifacts") or {})}
        merged_payload = {
            **invocation.output_payload,
            **(parsed.get("output_payload") or {}),
            "provider": response.provider,
            "model": response.model,
            "total_tokens": response.total_tokens,
        }
        summary = str(parsed.get("summary") or invocation.summary).strip()
        return self._build_result(
            context=context,
            invocation=invocation,
            summary=summary,
            artifacts=merged_artifacts,
            output_payload=merged_payload,
            provider=response.provider,
        )

    def _build_playbook_prompt(
        self,
        context: WorkerAdapterContext,
        invocation: SkillInvocationResult,
    ) -> str:
        """Compose the prompt for a markdown-playbook skill execution."""
        playbook = invocation.output_payload.get("playbook_instructions") or ""
        goal = context.context.get("goal") or context.run.goal
        worker_role = context.state.worker_role.value
        expected = context.context.get("expected_artifacts", [])
        return (
            f"Skill: {invocation.skill_name} (id={invocation.skill_id})\n"
            f"Worker role: {worker_role}\n"
            f"Goal: {goal}\n"
            f"Expected artifact keys: {list(expected)}\n\n"
            "Playbook instructions:\n"
            f"{playbook}\n\n"
            "Return a single JSON object: "
            "{\"summary\": str, \"artifacts\": {...}, \"output_payload\": {...}}."
        )

    def _result_from_invocation(
        self,
        context: WorkerAdapterContext,
        invocation: SkillInvocationResult,
        *,
        provider: str,
        model: str = "",
        raw_text: str | None = None,
    ) -> WorkerExecutionResult:
        """Convert a registry invocation directly into a worker result."""
        payload = dict(invocation.output_payload)
        if raw_text is not None:
            payload["raw_response"] = raw_text
        return self._build_result(
            context=context,
            invocation=invocation,
            summary=invocation.summary,
            artifacts=dict(invocation.artifacts),
            output_payload=payload,
            provider=provider,
            model=model,
        )

    def _build_result(
        self,
        *,
        context: WorkerAdapterContext,
        invocation: SkillInvocationResult,
        summary: str,
        artifacts: dict[str, Any],
        output_payload: dict[str, Any],
        provider: str,
        model: str = "",
    ) -> WorkerExecutionResult:
        """Assemble the final :class:`WorkerExecutionResult` for a node."""
        state = context.state
        merged_payload = {
            "adapter": self.name,
            "skill_id": invocation.skill_id,
            "skill_name": invocation.skill_name,
            "skill_invocation_mode": invocation.mode,
            "specialist": context.routed.get("specialist", state.worker_role.value),
            "recommended_tools": list(context.routed.get("recommended_tools", [])),
            "permission_scope": list(context.routed.get("permission_scope", [])),
            "review_required": True,
            **output_payload,
        }
        return WorkerExecutionResult(
            node_id=state.node_id,
            worker_role=state.worker_role,
            summary=summary,
            artifacts=artifacts,
            context_used={
                "context_boundary": context.context.get("context_boundary"),
                "selected_tools": list(context.context.get("selected_tools", [])),
                "skill_candidates": list(context.context.get("skill_candidates", [])),
                "dependency_summaries": dict(context.context.get("dependency_summaries", {})),
            },
            output_payload=merged_payload,
            provenance={
                "run_id": context.run.run_id,
                "plan_id": context.run.plan_id,
                "node_id": state.node_id,
                "routed_by": context.routed.get("provenance", {}).get("routed_by"),
                "routing_reason": context.routed.get("provenance", {}).get("routing_reason"),
                "adapter": self.name,
                "skill_id": invocation.skill_id,
                "provider": provider,
                "model": model,
            },
        )

    def _emit_message_delta(self, context: WorkerAdapterContext, text: str) -> None:
        """Publish the raw playbook response so the REPL can stream it."""
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
                    "adapter": self.name,
                },
            )
        except Exception:  # pragma: no cover - event bus must not break execution
            pass


def _parse_envelope(text: str) -> dict[str, Any] | None:
    """Parse a JSON envelope from playbook output; ``None`` if malformed."""
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
    return parsed


__all__ = [
    "SkillInvocationWorker",
]
