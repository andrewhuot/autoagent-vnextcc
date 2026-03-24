"""Release manager with multi-stage promotion pipeline.

Implements a structured promotion flow: gate_check -> holdout_eval ->
slice_check -> canary -> released/rolled_back. Each stage must pass
before proceeding to the next.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from deployer.canary import CanaryManager
from deployer.versioning import ConfigVersionManager


class PromotionStage(str, Enum):
    """Stages in the promotion pipeline."""

    gate_check = "gate_check"
    holdout_eval = "holdout_eval"
    slice_check = "slice_check"
    canary = "canary"
    released = "released"
    rolled_back = "rolled_back"


@dataclass
class PromotionRecord:
    """Record of a candidate's journey through the promotion pipeline.

    Tracks which stages have been completed, their results, and the
    final outcome (released or rolled_back).
    """

    record_id: str
    candidate_version: str
    stages_completed: list[PromotionStage]
    current_stage: PromotionStage
    gate_results: dict[str, bool]
    holdout_score: float | None = None
    slice_results: dict[str, float] = field(default_factory=dict)
    canary_verdict: str | None = None
    started_at: str = ""
    completed_at: str | None = None
    status: str = "in_progress"  # in_progress, released, rolled_back, failed
    failure_reason: str | None = None


class ReleaseManager:
    """Orchestrates multi-stage promotion from candidate to production.

    Coordinates gate checks, holdout evaluation, slice regression checks,
    and canary deployment to ensure safe, validated releases.
    """

    def __init__(
        self,
        version_manager: ConfigVersionManager,
        canary_manager: CanaryManager | None = None,
    ) -> None:
        self.version_manager = version_manager
        self.canary_manager = canary_manager
        self.records: list[PromotionRecord] = []

    def start_promotion(self, candidate_version: str) -> PromotionRecord:
        """Begin a new promotion pipeline for a candidate version.

        Args:
            candidate_version: Version identifier of the candidate to promote.

        Returns:
            A new PromotionRecord in the gate_check stage.
        """
        record = PromotionRecord(
            record_id=uuid.uuid4().hex[:12],
            candidate_version=candidate_version,
            stages_completed=[],
            current_stage=PromotionStage.gate_check,
            gate_results={},
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self.records.append(record)
        return record

    def check_gates(self, record: PromotionRecord, gate_results: dict[str, bool]) -> bool:
        """Verify all hard gates pass for a candidate.

        All gates must pass for the candidate to proceed. Any failure
        stops the pipeline.

        Args:
            record: The promotion record to update.
            gate_results: Map of gate name to pass/fail.

        Returns:
            True if all gates passed, False otherwise.
        """
        record.gate_results = dict(gate_results)
        all_passed = all(gate_results.values()) if gate_results else False

        if all_passed:
            record.stages_completed.append(PromotionStage.gate_check)
            record.current_stage = PromotionStage.holdout_eval
        else:
            failed_gates = [g for g, v in gate_results.items() if not v]
            record.status = "failed"
            record.failure_reason = f"Gates failed: {', '.join(failed_gates)}"
            record.completed_at = datetime.now(timezone.utc).isoformat()

        return all_passed

    def check_holdout(
        self,
        record: PromotionRecord,
        holdout_score: float,
        threshold: float = 0.0,
    ) -> bool:
        """Verify candidate does not regress on the holdout set.

        Args:
            record: The promotion record to update.
            holdout_score: Relative score vs baseline (positive = improvement).
            threshold: Minimum acceptable score (default 0.0 = no regression).

        Returns:
            True if holdout score meets or exceeds threshold.
        """
        record.holdout_score = holdout_score
        passed = holdout_score >= threshold

        if passed:
            record.stages_completed.append(PromotionStage.holdout_eval)
            record.current_stage = PromotionStage.slice_check
        else:
            record.status = "failed"
            record.failure_reason = (
                f"Holdout regression: score {holdout_score:.4f} < threshold {threshold:.4f}"
            )
            record.completed_at = datetime.now(timezone.utc).isoformat()

        return passed

    def check_slices(
        self,
        record: PromotionRecord,
        slice_results: dict[str, float],
        regression_threshold: float = -0.05,
    ) -> bool:
        """Verify no slice regresses beyond the threshold.

        Args:
            record: The promotion record to update.
            slice_results: Map of slice name to relative score delta.
            regression_threshold: Maximum acceptable regression per slice.

        Returns:
            True if no slice regresses more than threshold.
        """
        record.slice_results = dict(slice_results)
        regressed_slices = [
            name for name, delta in slice_results.items()
            if delta < regression_threshold
        ]
        passed = len(regressed_slices) == 0

        if passed:
            record.stages_completed.append(PromotionStage.slice_check)
            record.current_stage = PromotionStage.canary
        else:
            record.status = "failed"
            record.failure_reason = (
                f"Slice regressions: {', '.join(regressed_slices)}"
            )
            record.completed_at = datetime.now(timezone.utc).isoformat()

        return passed

    def start_canary(self, record: PromotionRecord) -> bool:
        """Begin canary deployment for the candidate.

        Delegates to the canary_manager if available. If no canary manager
        is configured, the canary stage is skipped (auto-passes).

        Args:
            record: The promotion record to update.

        Returns:
            True if canary was started (or skipped), False on error.
        """
        if self.canary_manager is None:
            record.stages_completed.append(PromotionStage.canary)
            record.current_stage = PromotionStage.released
            return True

        try:
            self.canary_manager.deploy_canary(
                config={"version": record.candidate_version},
                scores={},
            )
            return True
        except Exception as exc:
            record.status = "failed"
            record.failure_reason = f"Canary deployment failed: {exc}"
            record.completed_at = datetime.now(timezone.utc).isoformat()
            return False

    def complete_promotion(
        self,
        record: PromotionRecord,
        canary_verdict: str,
    ) -> str:
        """Complete the promotion pipeline with a canary verdict.

        Args:
            record: The promotion record to finalize.
            canary_verdict: "promote" or "rollback".

        Returns:
            Final status: "released" or "rolled_back".
        """
        record.canary_verdict = canary_verdict
        record.completed_at = datetime.now(timezone.utc).isoformat()

        if canary_verdict == "promote":
            record.stages_completed.append(PromotionStage.canary)
            record.stages_completed.append(PromotionStage.released)
            record.current_stage = PromotionStage.released
            record.status = "released"
        else:
            record.stages_completed.append(PromotionStage.rolled_back)
            record.current_stage = PromotionStage.rolled_back
            record.status = "rolled_back"

        return record.status

    def run_full_pipeline(
        self,
        candidate_version: str,
        gate_results: dict[str, bool],
        holdout_score: float,
        slice_results: dict[str, float],
        canary_verdict: str | None = None,
    ) -> PromotionRecord:
        """Run all promotion stages in sequence.

        Stops at the first failing stage and records the failure.

        Args:
            candidate_version: Version identifier of the candidate.
            gate_results: Hard gate pass/fail results.
            holdout_score: Relative holdout score vs baseline.
            slice_results: Per-slice score deltas.
            canary_verdict: Optional canary verdict ("promote"/"rollback").
                If None, canary stage is skipped.

        Returns:
            The completed PromotionRecord.
        """
        record = self.start_promotion(candidate_version)

        if not self.check_gates(record, gate_results):
            return record

        if not self.check_holdout(record, holdout_score):
            return record

        if not self.check_slices(record, slice_results):
            return record

        if canary_verdict is not None:
            self.start_canary(record)
            self.complete_promotion(record, canary_verdict)
        else:
            # No canary step — auto-release
            record.stages_completed.append(PromotionStage.canary)
            record.stages_completed.append(PromotionStage.released)
            record.current_stage = PromotionStage.released
            record.status = "released"
            record.completed_at = datetime.now(timezone.utc).isoformat()

        return record

    def get_record(self, record_id: str) -> PromotionRecord | None:
        """Look up a promotion record by its ID.

        Args:
            record_id: The record_id to search for.

        Returns:
            The matching PromotionRecord, or None if not found.
        """
        for record in self.records:
            if record.record_id == record_id:
                return record
        return None
