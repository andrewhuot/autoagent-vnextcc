"""Release manager with multi-stage promotion pipeline.

Implements a structured promotion flow: gate_check -> holdout_eval ->
slice_check -> canary -> released/rolled_back. Each stage must pass
before proceeding to the next.

Also exposes a higher-level signed-release API (create_release,
sign_release, deploy_release, rollback_release, verify_release,
list_releases, get_release) that operates on
:class:`~deployer.release_objects.ReleaseObject` instances and
persists them in an in-memory store keyed by release_id.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from deployer.canary import CanaryManager
from deployer.release_objects import ReleaseObject, ReleaseStatus
from deployer.signing import ReleaseSigner
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
        signing_key: str = "autoagent-default-key",
    ) -> None:
        self.version_manager = version_manager
        self.canary_manager = canary_manager
        self.records: list[PromotionRecord] = []
        # Signed-release store and signer (P1-8)
        self._releases: dict[str, ReleaseObject] = {}
        self._signer = ReleaseSigner(secret_key=signing_key)

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

    # ------------------------------------------------------------------
    # Signed-release API (P1-8)
    # ------------------------------------------------------------------

    def create_release(
        self, experiment_id: str, config: dict[str, Any]
    ) -> ReleaseObject:
        """Create a new DRAFT :class:`~deployer.release_objects.ReleaseObject`.

        Args:
            experiment_id: Identifier of the upstream experiment or change
                request that motivated this release.
            config: Arbitrary configuration / provenance data for the
                release.  Recognised keys (all optional):

                ``version`` (str), ``code_diff`` (dict),
                ``config_diff`` (dict), ``prompt_diff`` (dict),
                ``dataset_version`` (str), ``eval_results`` (dict),
                ``grader_versions`` (dict), ``judge_versions`` (dict),
                ``skill_versions`` (dict), ``model_version`` (str),
                ``risk_class`` (str), ``approval_chain`` (list),
                ``canary_plan`` (dict), ``rollback_instructions`` (str),
                ``business_outcomes`` (dict), ``metadata`` (dict).

        Returns:
            A newly created :class:`~deployer.release_objects.ReleaseObject`
            in ``DRAFT`` status.
        """
        release_id = str(uuid.uuid4())
        version = config.get("version", f"0.0.{len(self._releases) + 1}")
        release = ReleaseObject(
            release_id=release_id,
            version=version,
            status=ReleaseStatus.DRAFT,
            code_diff=config.get("code_diff", {}),
            config_diff=config.get("config_diff", {}),
            prompt_diff=config.get("prompt_diff", {}),
            dataset_version=config.get("dataset_version", ""),
            eval_results=config.get("eval_results", {}),
            grader_versions=config.get("grader_versions", {}),
            judge_versions=config.get("judge_versions", {}),
            skill_versions=config.get("skill_versions", {}),
            model_version=config.get("model_version", ""),
            risk_class=config.get("risk_class", ""),
            approval_chain=config.get("approval_chain", []),
            canary_plan=config.get("canary_plan", {}),
            rollback_instructions=config.get("rollback_instructions", ""),
            business_outcomes=config.get("business_outcomes", {}),
            metadata={**config.get("metadata", {}), "experiment_id": experiment_id},
        )
        self._releases[release_id] = release
        return release

    def sign_release(self, release_id: str) -> ReleaseObject:
        """Sign a DRAFT release, advancing it to SIGNED status.

        Computes an HMAC-SHA256 signature over the release content and
        records the ``signed_at`` timestamp.

        Args:
            release_id: ID of the release to sign.

        Returns:
            The updated :class:`~deployer.release_objects.ReleaseObject`
            with ``status=SIGNED``.

        Raises:
            KeyError: If *release_id* does not exist.
            ValueError: If the release is not in DRAFT status.
        """
        release = self._get_release_or_raise(release_id)
        if release.status != ReleaseStatus.DRAFT:
            raise ValueError(
                f"Release {release_id} must be in DRAFT status to sign "
                f"(current: {release.status.value})"
            )
        release.signature = self._signer.sign(release)
        release.signed_at = datetime.now(timezone.utc).isoformat()
        release.status = ReleaseStatus.SIGNED
        return release

    def deploy_release(self, release_id: str) -> dict[str, Any]:
        """Deploy a SIGNED release, advancing it to DEPLOYED status.

        Also marks any previously DEPLOYED release as SUPERSEDED.

        Args:
            release_id: ID of the release to deploy.

        Returns:
            A summary dict with ``release_id``, ``version``, ``status``,
            and ``deployed_at``.

        Raises:
            KeyError: If *release_id* does not exist.
            ValueError: If the release is not SIGNED or its signature fails
                verification.
        """
        release = self._get_release_or_raise(release_id)
        if release.status != ReleaseStatus.SIGNED:
            raise ValueError(
                f"Release {release_id} must be SIGNED before deploying "
                f"(current: {release.status.value})"
            )
        if release.signature is None or not self._signer.verify(
            release, release.signature
        ):
            raise ValueError(
                f"Signature verification failed for release {release_id}."
            )

        # Supersede any currently deployed release
        for other in self._releases.values():
            if other.release_id != release_id and other.status == ReleaseStatus.DEPLOYED:
                other.status = ReleaseStatus.SUPERSEDED

        deployed_at = datetime.now(timezone.utc).isoformat()
        release.status = ReleaseStatus.DEPLOYED
        release.metadata["deployed_at"] = deployed_at

        return {
            "release_id": release_id,
            "version": release.version,
            "status": release.status.value,
            "deployed_at": deployed_at,
        }

    def rollback_release(self, release_id: str) -> dict[str, Any]:
        """Roll back a DEPLOYED release, marking it as ROLLED_BACK.

        Args:
            release_id: ID of the release to roll back.

        Returns:
            A summary dict with ``release_id``, ``version``, ``status``,
            and ``rolled_back_at``.

        Raises:
            KeyError: If *release_id* does not exist.
            ValueError: If the release is not currently DEPLOYED.
        """
        release = self._get_release_or_raise(release_id)
        if release.status != ReleaseStatus.DEPLOYED:
            raise ValueError(
                f"Only DEPLOYED releases can be rolled back "
                f"(current: {release.status.value})"
            )
        rolled_back_at = datetime.now(timezone.utc).isoformat()
        release.status = ReleaseStatus.ROLLED_BACK
        release.metadata["rolled_back_at"] = rolled_back_at
        return {
            "release_id": release_id,
            "version": release.version,
            "status": release.status.value,
            "rolled_back_at": rolled_back_at,
        }

    def verify_release(self, release_id: str) -> bool:
        """Verify the cryptographic signature of a release.

        Args:
            release_id: ID of the release to verify.

        Returns:
            True if the release has a valid signature, False if the
            signature is missing or invalid.

        Raises:
            KeyError: If *release_id* does not exist.
        """
        release = self._get_release_or_raise(release_id)
        if release.signature is None:
            return False
        return self._signer.verify(release, release.signature)

    def list_releases(
        self, status: str | None = None
    ) -> list[ReleaseObject]:
        """Return all managed releases, optionally filtered by status.

        Args:
            status: Optional :class:`~deployer.release_objects.ReleaseStatus`
                value string (e.g. ``"DRAFT"``, ``"DEPLOYED"``).  When
                ``None`` all releases are returned.

        Returns:
            List of :class:`~deployer.release_objects.ReleaseObject`,
            ordered by ``created_at`` ascending.
        """
        releases = list(self._releases.values())
        if status is not None:
            target = ReleaseStatus(status.upper())
            releases = [r for r in releases if r.status == target]
        releases.sort(key=lambda r: r.created_at)
        return releases

    def get_release(self, release_id: str) -> ReleaseObject | None:
        """Return the release with the given ID, or None if not found.

        Args:
            release_id: The release to look up.

        Returns:
            The :class:`~deployer.release_objects.ReleaseObject` or ``None``.
        """
        return self._releases.get(release_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_release_or_raise(self, release_id: str) -> ReleaseObject:
        release = self._releases.get(release_id)
        if release is None:
            raise KeyError(f"Release not found: {release_id}")
        return release
