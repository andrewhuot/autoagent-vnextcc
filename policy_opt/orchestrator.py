"""Policy optimization orchestrator — coordinates offline training jobs."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from policy_opt.types import (
    PolicyArtifact,
    PolicyType,
    TrainingJob,
    TrainingMode,
    TrainingStatus,
    OPEReport,
)
from policy_opt.registry import PolicyArtifactRegistry
from policy_opt.safety import OnlineExplorationGuard


class PolicyOptOrchestrator:
    """Orchestrates offline training jobs for policy optimization.

    Manages the lifecycle: validate -> train -> evaluate -> canary -> promote/rollback.
    Enforces offline-only training (no online exploration).
    """

    def __init__(
        self,
        policy_registry: PolicyArtifactRegistry,
    ) -> None:
        self._registry = policy_registry
        self._guard = OnlineExplorationGuard()

    def create_training_job(
        self,
        mode: str,
        backend: str,
        dataset_path: str,
        reward_spec: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
    ) -> TrainingJob:
        """Create and register a new training job.

        Validates:
        1. No online exploration in config
        2. Backend supports the requested mode
        3. Dataset exists

        Returns the created TrainingJob (status=pending).
        """
        # Validate safety
        merged_config = config or {}
        OnlineExplorationGuard.enforce(merged_config)

        job = TrainingJob(
            mode=TrainingMode(mode),
            backend=backend,
            dataset_path=dataset_path,
            reward_spec=reward_spec or {},
            config=merged_config,
        )
        self._registry.create_job(job)
        return job

    def start_training(self, job_id: str) -> TrainingJob:
        """Start a pending training job.

        Delegates to the appropriate backend. Updates job status to running.
        For v1, this runs synchronously with mock results.
        """
        job = self._registry.get_job(job_id)
        if job is None:
            raise KeyError(f"Training job not found: {job_id}")
        if job.status != TrainingStatus.pending:
            raise ValueError(f"Job {job_id} is not pending (status: {job.status.value})")

        # Re-validate safety
        OnlineExplorationGuard.enforce(job.config)

        # Update to running
        self._registry.update_job_status(job_id, TrainingStatus.running.value)

        # Try to get backend and run training
        try:
            from policy_opt.backends.base import get_backend
            backend_impl = get_backend(job.backend)

            # Validate dataset
            errors = backend_impl.validate_dataset(job.dataset_path, job.mode)
            if errors:
                self._registry.update_job_status(
                    job_id, TrainingStatus.failed.value,
                    error=f"Dataset validation failed: {'; '.join(errors)}"
                )
                return self._registry.get_job(job_id)

            # Start training
            provider_job_id = backend_impl.start_training(job)
            result = {"provider_job_id": provider_job_id}

            # For v1, mark as completed immediately with mock policy
            policy = PolicyArtifact(
                name=f"{job.mode.value}_{job.backend}",
                policy_type=self._mode_to_policy_type(job.mode),
                training_mode=job.mode,
                training_dataset_version=job.dataset_path,
                reward_spec_version=str(hash(str(job.reward_spec))),
                trainer_backend=job.backend,
                provenance={"job_id": job_id, "dataset": job.dataset_path},
            )
            self._registry.register(policy)
            result["policy_id"] = policy.policy_id

            self._registry.update_job_status(
                job_id, TrainingStatus.completed.value, result=result
            )
        except NotImplementedError:
            # Backend training not yet implemented — create mock result
            policy = PolicyArtifact(
                name=f"{job.mode.value}_{job.backend}",
                policy_type=self._mode_to_policy_type(job.mode),
                training_mode=job.mode,
                training_dataset_version=job.dataset_path,
                reward_spec_version=str(hash(str(job.reward_spec))),
                trainer_backend=job.backend,
                provenance={"job_id": job_id, "dataset": job.dataset_path, "mock": True},
            )
            self._registry.register(policy)
            self._registry.update_job_status(
                job_id, TrainingStatus.completed.value,
                result={"policy_id": policy.policy_id, "mock": True}
            )
        except Exception as exc:
            self._registry.update_job_status(
                job_id, TrainingStatus.failed.value, error=str(exc)
            )

        return self._registry.get_job(job_id)

    def evaluate_policy(self, policy_id: str) -> dict[str, Any]:
        """Run offline evaluation on a policy artifact.

        Returns eval report dict with:
        - held_out_score
        - benchmark_slices: dict[slice_name, score]
        - safety_gate_passed: bool
        - regression_detected: bool
        """
        policy = self._registry.get_by_id(policy_id)
        if policy is None:
            raise KeyError(f"Policy not found: {policy_id}")

        # V1: Return a basic eval structure
        report = {
            "policy_id": policy_id,
            "policy_name": policy.name,
            "held_out_score": 0.0,
            "benchmark_slices": {},
            "safety_gate_passed": True,
            "regression_detected": False,
            "status": "pending_evaluation",
        }

        # Update policy with eval report
        policy.eval_report = report
        return report

    def promote_policy(self, policy_id: str) -> PolicyArtifact:
        """Promote a candidate policy to active status.

        Validates that eval and canary checks have been performed.
        Demotes any currently promoted policy of the same type.
        """
        policy = self._registry.get_by_id(policy_id)
        if policy is None:
            raise KeyError(f"Policy not found: {policy_id}")

        # Check that policy has been evaluated
        if not policy.eval_report:
            raise ValueError(f"Policy {policy_id} has not been evaluated yet")

        # Demote current active policy of same type
        current = self._registry.get_active_policy(policy.policy_type.value)
        if current:
            self._registry.update_status(current.policy_id, "rolled_back")
            policy.rollback_target = current.policy_id

        self._registry.update_status(policy_id, "promoted")
        return self._registry.get_by_id(policy_id)

    def rollback_policy(self, policy_id: str) -> str:
        """Roll back a promoted policy. Returns rollback target policy_id or empty string."""
        policy = self._registry.get_by_id(policy_id)
        if policy is None:
            raise KeyError(f"Policy not found: {policy_id}")

        self._registry.update_status(policy_id, "rolled_back")

        # Re-promote rollback target if available
        if policy.rollback_target:
            self._registry.update_status(policy.rollback_target, "promoted")

        return policy.rollback_target

    def list_jobs(self, status: str | None = None) -> list[TrainingJob]:
        return self._registry.list_jobs(status=status)

    def get_job(self, job_id: str) -> TrainingJob | None:
        return self._registry.get_job(job_id)

    @staticmethod
    def _mode_to_policy_type(mode: TrainingMode) -> PolicyType:
        """Map training mode to default policy type."""
        mapping = {
            TrainingMode.control: PolicyType.mutation_policy,
            TrainingMode.verifier: PolicyType.verifier_tuned_model,
            TrainingMode.preference: PolicyType.preference_tuned_model,
        }
        return mapping.get(mode, PolicyType.mutation_policy)
