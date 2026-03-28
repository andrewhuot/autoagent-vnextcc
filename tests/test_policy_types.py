"""Tests for PolicyArtifact, TrainingJob, and OPEReport types in policy_opt/types.py."""

from __future__ import annotations

import pytest

from policy_opt.types import (
    OPEReport,
    PolicyArtifact,
    PolicyType,
    TrainerBackend,
    TrainingJob,
    TrainingMode,
    TrainingStatus,
)


# ---------------------------------------------------------------------------
# Enum value tests
# ---------------------------------------------------------------------------

def test_policy_type_values():
    assert PolicyType.mutation_policy.value == "mutation_policy"
    assert PolicyType.routing_policy.value == "routing_policy"
    assert PolicyType.tool_policy.value == "tool_policy"
    assert PolicyType.preference_tuned_model.value == "preference_tuned_model"


def test_training_status_values():
    assert TrainingStatus.pending.value == "pending"
    assert TrainingStatus.running.value == "running"
    assert TrainingStatus.completed.value == "completed"
    assert TrainingStatus.failed.value == "failed"
    assert TrainingStatus.cancelled.value == "cancelled"


def test_training_mode_values():
    assert TrainingMode.control.value == "control"
    assert TrainingMode.verifier.value == "verifier"
    assert TrainingMode.preference.value == "preference"


# ---------------------------------------------------------------------------
# PolicyArtifact round-trip
# ---------------------------------------------------------------------------

def test_policy_artifact_round_trip():
    artifact = PolicyArtifact(
        name="my_policy",
        policy_type=PolicyType.routing_policy,
        training_mode=TrainingMode.verifier,
        training_dataset_version="v2",
        reward_spec_version="r1",
        trainer_backend=TrainerBackend.openai_rft.value,
        eval_report={"score": 0.85},
        ope_report={"uplift": 0.1},
        canary_report={"canary_pass": True},
        rollback_target="policy-old-id",
        provenance={"algo": "rlvr"},
        status="canary",
        version=3,
        model_reference="ft:gpt-4o-mini:...",
        metadata={"note": "test"},
    )
    restored = PolicyArtifact.from_dict(artifact.to_dict())

    assert restored.policy_id == artifact.policy_id
    assert restored.name == "my_policy"
    assert restored.policy_type == PolicyType.routing_policy
    assert restored.training_mode == TrainingMode.verifier
    assert restored.training_dataset_version == "v2"
    assert restored.eval_report == {"score": 0.85}
    assert restored.status == "canary"
    assert restored.version == 3
    assert restored.model_reference == "ft:gpt-4o-mini:..."


def test_policy_artifact_defaults():
    artifact = PolicyArtifact()
    assert artifact.policy_type == PolicyType.mutation_policy
    assert artifact.training_mode == TrainingMode.control
    assert artifact.status == "candidate"
    assert artifact.version == 1
    assert artifact.eval_report == {}
    assert artifact.metadata == {}


def test_policy_artifact_from_dict_missing_fields():
    restored = PolicyArtifact.from_dict({"name": "sparse"})
    assert restored.name == "sparse"
    assert restored.status == "candidate"
    assert restored.version == 1


# ---------------------------------------------------------------------------
# TrainingJob round-trip
# ---------------------------------------------------------------------------

def test_training_job_round_trip():
    job = TrainingJob(
        mode=TrainingMode.preference,
        backend=TrainerBackend.openai_dpo.value,
        dataset_path="/data/pref.jsonl",
        reward_spec={"kind": "preference"},
        config={"epochs": 3},
        status=TrainingStatus.running,
        result={"model_id": "ft-abc"},
        policy_id="pol-123",
        error_message="",
        metadata={"run": "exp1"},
    )
    restored = TrainingJob.from_dict(job.to_dict())

    assert restored.job_id == job.job_id
    assert restored.mode == TrainingMode.preference
    assert restored.backend == TrainerBackend.openai_dpo.value
    assert restored.dataset_path == "/data/pref.jsonl"
    assert restored.status == TrainingStatus.running
    assert restored.result == {"model_id": "ft-abc"}
    assert restored.policy_id == "pol-123"


def test_training_job_defaults():
    job = TrainingJob()
    assert job.mode == TrainingMode.control
    assert job.status == TrainingStatus.pending
    assert job.result == {}
    assert job.error_message == ""


# ---------------------------------------------------------------------------
# OPEReport round-trip
# ---------------------------------------------------------------------------

def test_ope_report_round_trip():
    report = OPEReport(
        policy_id="pol-xyz",
        baseline_replay_score=0.72,
        candidate_estimated_uplift=0.05,
        uncertainty_lower=-0.01,
        uncertainty_upper=0.11,
        support_coverage=0.8,
        diagnostics={"n_episodes": 50},
    )
    restored = OPEReport.from_dict(report.to_dict())

    assert restored.policy_id == "pol-xyz"
    assert restored.baseline_replay_score == pytest.approx(0.72)
    assert restored.candidate_estimated_uplift == pytest.approx(0.05)
    assert restored.uncertainty_lower == pytest.approx(-0.01)
    assert restored.uncertainty_upper == pytest.approx(0.11)
    assert restored.support_coverage == pytest.approx(0.8)
    assert restored.diagnostics == {"n_episodes": 50}


def test_ope_report_defaults():
    report = OPEReport()
    assert report.policy_id == ""
    assert report.baseline_replay_score == 0.0
    assert report.diagnostics == {}
