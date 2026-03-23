"""Core optimization loop: propose -> validate -> eval -> gate -> accept/reject."""

from __future__ import annotations

import json
import time
import uuid

from .gates import Gates
from .memory import OptimizationAttempt, OptimizationMemory
from .proposer import Proposer
from agent.config.schema import AgentConfig, config_diff, validate_config
from evals.runner import EvalRunner
from observer.metrics import HealthReport


class Optimizer:
    """Runs one optimization cycle: propose a config change, evaluate it, gate it."""

    def __init__(
        self,
        eval_runner: EvalRunner,
        memory: OptimizationMemory | None = None,
        proposer: Proposer | None = None,
        gates: Gates | None = None,
    ) -> None:
        self.eval_runner = eval_runner
        self.memory = memory or OptimizationMemory()
        self.proposer = proposer or Proposer(use_mock=True)
        self.gates = gates or Gates()

    def optimize(
        self,
        health_report: HealthReport,
        current_config: dict,
        failure_samples: list[dict] | None = None,
    ) -> tuple[dict | None, str]:
        """Run one optimization cycle. Returns (new_config_or_None, status_message)."""
        validated_current: AgentConfig
        try:
            validated_current = validate_config(current_config)
        except Exception as exc:  # pragma: no cover - defensive branch
            return None, f"Current config invalid: {exc}"

        # 1. Gather failure samples and past attempts for the proposer
        normalized_failure_samples = failure_samples or []
        past_attempts = [
            {
                "change_description": a.change_description,
                "config_section": a.config_section,
                "status": a.status,
            }
            for a in self.memory.recent(limit=20)
        ]

        # 2. Propose a config change
        proposal = self.proposer.propose(
            current_config=current_config,
            health_metrics=health_report.metrics.to_dict(),
            failure_samples=normalized_failure_samples,
            failure_buckets=health_report.failure_buckets,
            past_attempts=past_attempts,
        )
        if proposal is None:
            return None, "No proposal generated"

        # 3. Validate the proposed config against the schema
        try:
            validated_new = validate_config(proposal.new_config)
        except Exception as exc:
            # Build a best-effort AgentConfig for diff even though validation failed
            attempt = OptimizationAttempt(
                attempt_id=str(uuid.uuid4())[:8],
                timestamp=time.time(),
                change_description=proposal.change_description,
                config_diff=f"Invalid config: {exc}",
                status="rejected_invalid",
                config_section=proposal.config_section,
                health_context=json.dumps(health_report.metrics.to_dict()),
            )
            self.memory.log(attempt)
            return None, f"Invalid config: {exc}"

        # 4. Compute config diff and short-circuit no-op proposals
        baseline_config = validated_current.model_dump(mode="python")
        candidate_config = validated_new.model_dump(mode="python")
        diff_str = config_diff(validated_current, validated_new)
        if diff_str == "No changes.":
            attempt = OptimizationAttempt(
                attempt_id=str(uuid.uuid4())[:8],
                timestamp=time.time(),
                change_description=proposal.change_description,
                config_diff=diff_str,
                status="rejected_noop",
                config_section=proposal.config_section,
                health_context=json.dumps(health_report.metrics.to_dict()),
            )
            self.memory.log(attempt)
            return None, "REJECTED (rejected_noop): Proposal did not change config"

        # 5. Run eval suite on baseline and candidate configs
        baseline_score = self.eval_runner.run(config=baseline_config)
        candidate_score = self.eval_runner.run(config=candidate_config)

        # 6. Run gates
        accepted, status, reason = self.gates.evaluate(candidate_score, baseline_score)

        # 7. Log the attempt
        attempt = OptimizationAttempt(
            attempt_id=str(uuid.uuid4())[:8],
            timestamp=time.time(),
            change_description=proposal.change_description,
            config_diff=diff_str,
            status=status,
            config_section=proposal.config_section,
            score_before=baseline_score.composite,
            score_after=candidate_score.composite,
            health_context=json.dumps(health_report.metrics.to_dict()),
        )
        self.memory.log(attempt)

        if accepted:
            return candidate_config, f"ACCEPTED: {reason}"
        return None, f"REJECTED ({status}): {reason}"
