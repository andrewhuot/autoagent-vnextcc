"""Eval-axis coordinator workers (V2).

Two workers drive the ``/eval`` verb end-to-end:

- :class:`EvalRunnerWorker` skips the LLM entirely and invokes
  :func:`evals.runner.run_for_coordinator` directly. It emits a
  reviewable ``eval_run_summary`` artifact plus a ``failure_fingerprints``
  list the loss analyst can cluster.
- :class:`LossAnalystWorker` calls :class:`LLMRouter` with a scoped prompt
  built from the eval runner's structured output; it produces a
  ``loss_analysis`` narrative and a ``failure_clusters`` grouping that
  downstream ``/optimize`` axis workers consume.

Both adapters conform to the :class:`WorkerAdapter` protocol so the
coordinator runtime can swap them in for the default LLM worker.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from builder.types import (
    SpecialistRole,
    WorkerExecutionResult,
)
from builder.worker_adapters import (
    DeterministicWorkerAdapter,
    WorkerAdapter,
    WorkerAdapterContext,
)
from evals.runner import EvalRunner, run_for_coordinator
from optimizer.providers import LLMRequest, LLMRouter

logger = logging.getLogger(__name__)


_EVAL_RUNNER_ARTIFACTS = ("eval_run_summary", "failure_fingerprints")
_LOSS_ANALYST_ARTIFACTS = ("loss_analysis", "failure_clusters")


class EvalRunnerWorker:
    """Worker adapter that executes the eval suite without an LLM call."""

    name = "eval_runner_worker"

    def __init__(
        self,
        *,
        runner: EvalRunner | None = None,
        fallback: WorkerAdapter | None = None,
    ) -> None:
        self._runner = runner
        self._fallback = fallback or DeterministicWorkerAdapter()

    def execute(self, context: WorkerAdapterContext) -> WorkerExecutionResult:
        """Run evals via :func:`run_for_coordinator` and shape the result."""
        if context.state.worker_role != SpecialistRole.EVAL_RUNNER:
            return self._fallback.execute(context)

        try:
            envelope = run_for_coordinator(
                dict(context.context),
                runner=self._runner,
            )
        except Exception as exc:
            logger.warning(
                "eval_runner_worker: eval execution failed — falling back",
                extra={"node_id": context.state.node_id, "error": str(exc)},
            )
            return self._fallback.execute(context)

        summary = envelope.get("summary") or {}
        failing_cases = envelope.get("failing_cases") or []
        summary_line = (
            f"Ran {summary.get('total_cases', 0)} eval cases "
            f"({summary.get('passed_cases', 0)} passed, "
            f"{len(failing_cases)} failed); "
            f"composite={summary.get('composite', 0.0):.3f}."
        )

        artifacts: dict[str, Any] = {
            "eval_run_summary": {
                "summary": summary,
                "run_id": envelope.get("run_id"),
                "warnings": envelope.get("warnings", []),
            },
            "failure_fingerprints": failing_cases,
        }

        return WorkerExecutionResult(
            node_id=context.state.node_id,
            worker_role=context.state.worker_role,
            summary=summary_line,
            artifacts=artifacts,
            context_used=_context_snapshot(context),
            output_payload={
                "adapter": self.name,
                "specialist": context.routed.get(
                    "specialist", SpecialistRole.EVAL_RUNNER.value
                ),
                "recommended_tools": list(context.routed.get("recommended_tools", [])),
                "permission_scope": list(context.routed.get("permission_scope", [])),
                "review_required": False,
                "next_actions": [
                    "Hand off to the loss_analyst to cluster failing cases."
                ],
            },
            provenance=_provenance(context, adapter=self.name),
        )


class LossAnalystWorker:
    """Worker adapter that narrates failure clusters from eval runner output."""

    name = "loss_analyst_worker"

    def __init__(
        self,
        router: LLMRouter,
        *,
        fallback: WorkerAdapter | None = None,
        temperature: float = 0.2,
        max_tokens: int = 900,
    ) -> None:
        self._router = router
        self._fallback = fallback or DeterministicWorkerAdapter()
        self._temperature = temperature
        self._max_tokens = max_tokens

    def execute(self, context: WorkerAdapterContext) -> WorkerExecutionResult:
        """Read the eval runner artifacts off the run, then LLM-summarise."""
        if context.state.worker_role != SpecialistRole.LOSS_ANALYST:
            return self._fallback.execute(context)

        eval_artifacts = _find_eval_runner_artifacts(context)
        if eval_artifacts is None:
            logger.info(
                "loss_analyst_worker: no upstream eval runner artifacts — falling back",
                extra={"node_id": context.state.node_id},
            )
            return self._fallback.execute(context)

        prompt = _build_loss_analyst_prompt(context, eval_artifacts)
        request = LLMRequest(
            prompt=prompt["user"],
            system=prompt["system"],
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            metadata={
                "worker_role": SpecialistRole.LOSS_ANALYST.value,
                "plan_id": context.run.plan_id,
                "run_id": context.run.run_id,
                "node_id": context.state.node_id,
            },
        )
        try:
            response = self._router.generate(request)
        except Exception as exc:
            logger.warning(
                "loss_analyst_worker: provider call failed — falling back",
                extra={"node_id": context.state.node_id, "error": str(exc)},
            )
            return self._fallback.execute(context)

        parsed = _parse_loss_envelope(response.text)
        if parsed is None:
            logger.warning(
                "loss_analyst_worker: response was not valid JSON — falling back",
                extra={"node_id": context.state.node_id},
            )
            return self._fallback.execute(context)

        artifacts = parsed.get("artifacts") or {}
        if not all(name in artifacts for name in _LOSS_ANALYST_ARTIFACTS):
            logger.warning(
                "loss_analyst_worker: missing required artifacts — falling back",
                extra={
                    "node_id": context.state.node_id,
                    "received": sorted(artifacts),
                },
            )
            return self._fallback.execute(context)

        return WorkerExecutionResult(
            node_id=context.state.node_id,
            worker_role=context.state.worker_role,
            summary=str(parsed.get("summary") or "").strip()
            or "Summarized eval failures into axis-scoped clusters.",
            artifacts=dict(artifacts),
            context_used=_context_snapshot(context),
            output_payload={
                "adapter": self.name,
                "specialist": context.routed.get(
                    "specialist", SpecialistRole.LOSS_ANALYST.value
                ),
                "recommended_tools": list(context.routed.get("recommended_tools", [])),
                "permission_scope": list(context.routed.get("permission_scope", [])),
                "review_required": False,
                "next_actions": [
                    "Hand clusters to the axis optimizers to draft change cards.",
                ],
            },
            provenance={
                **_provenance(context, adapter=self.name),
                "provider": response.provider,
                "model": response.model,
                "total_tokens": response.total_tokens,
            },
        )


def _context_snapshot(context: WorkerAdapterContext) -> dict[str, Any]:
    """Return a compact context snapshot for provenance."""
    return {
        "context_boundary": context.context.get("context_boundary"),
        "selected_tools": list(context.context.get("selected_tools", [])),
        "skill_candidates": list(context.context.get("skill_candidates", [])),
        "dependency_summaries": dict(context.context.get("dependency_summaries", {})),
    }


def _provenance(context: WorkerAdapterContext, *, adapter: str) -> dict[str, Any]:
    """Return the standard provenance dict for eval-axis workers."""
    routed_provenance = context.routed.get("provenance", {}) or {}
    return {
        "run_id": context.run.run_id,
        "plan_id": context.run.plan_id,
        "node_id": context.state.node_id,
        "routed_by": routed_provenance.get("routed_by"),
        "routing_reason": routed_provenance.get("routing_reason"),
        "adapter": adapter,
    }


def _find_eval_runner_artifacts(
    context: WorkerAdapterContext,
) -> dict[str, Any] | None:
    """Locate the EvalRunnerWorker's artifacts on the current coordinator run."""
    for state in context.run.worker_states:
        if state.worker_role != SpecialistRole.EVAL_RUNNER:
            continue
        if state.result is None:
            continue
        artifacts = state.result.artifacts or {}
        if all(name in artifacts for name in _EVAL_RUNNER_ARTIFACTS):
            return dict(artifacts)
    return None


def _build_loss_analyst_prompt(
    context: WorkerAdapterContext,
    eval_artifacts: dict[str, Any],
) -> dict[str, str]:
    """Compose the loss-analyst prompt pair."""
    system = (
        "You are the Loss Analyst worker in AgentLab. "
        "Read the eval runner output, cluster failing cases by root cause, and "
        "return a structured narrative. "
        "Return a single JSON object with this shape and no prose outside: "
        '{"summary": "...", "artifacts": {"loss_analysis": {"...": "..."}, '
        '"failure_clusters": [{"cluster_id": "...", "hypothesis": "...", '
        '"case_ids": [], "recommended_axis": "instructions|guardrails|callbacks"}] }, '
        '"output_payload": {"review_required": false, "next_actions": []}}'
    )
    user_payload = {
        "goal": context.context.get("goal"),
        "eval_run_summary": eval_artifacts.get("eval_run_summary"),
        "failure_fingerprints": eval_artifacts.get("failure_fingerprints"),
        "dependency_summaries": dict(context.context.get("dependency_summaries", {})),
    }
    return {
        "system": system,
        "user": json.dumps(user_payload, indent=2, sort_keys=True),
    }


def _parse_loss_envelope(text: str) -> dict[str, Any] | None:
    """Parse a JSON envelope produced by the loss analyst LLM call."""
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
    if "artifacts" not in parsed:
        return None
    return parsed


__all__ = [
    "EvalRunnerWorker",
    "LossAnalystWorker",
]
