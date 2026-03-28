"""Tests for PolicyArtifactRegistry in policy_opt/registry.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from policy_opt.registry import PolicyArtifactRegistry
from policy_opt.types import (
    PolicyArtifact,
    PolicyType,
    TrainingJob,
    TrainingMode,
    TrainingStatus,
)


@pytest.fixture
def registry(tmp_path: Path) -> PolicyArtifactRegistry:
    db = tmp_path / "policy_test.db"
    reg = PolicyArtifactRegistry(str(db))
    yield reg
    reg.close()


def _make_artifact(
    name: str,
    policy_type: PolicyType = PolicyType.mutation_policy,
    status: str = "candidate",
) -> PolicyArtifact:
    return PolicyArtifact(
        name=name,
        policy_type=policy_type,
        training_mode=TrainingMode.control,
        status=status,
    )


def _make_job(mode: TrainingMode = TrainingMode.control) -> TrainingJob:
    return TrainingJob(mode=mode, dataset_path="/data/ep.jsonl")


# ---------------------------------------------------------------------------
# register / get / get_by_id
# ---------------------------------------------------------------------------

def test_register_and_get_latest(registry: PolicyArtifactRegistry):
    artifact = _make_artifact("policy_a")
    name, version = registry.register(artifact)
    assert name == "policy_a"
    assert version == 1

    fetched = registry.get("policy_a")
    assert fetched is not None
    assert fetched.name == "policy_a"
    assert fetched.version == 1


def test_register_increments_version(registry: PolicyArtifactRegistry):
    registry.register(_make_artifact("p"))
    _, v2 = registry.register(_make_artifact("p"))
    assert v2 == 2
    fetched = registry.get("p")
    assert fetched.version == 2


def test_get_specific_version(registry: PolicyArtifactRegistry):
    registry.register(_make_artifact("p"))
    registry.register(_make_artifact("p"))
    v1 = registry.get("p", version=1)
    assert v1 is not None
    assert v1.version == 1


def test_get_by_id(registry: PolicyArtifactRegistry):
    artifact = _make_artifact("unique_policy")
    registry.register(artifact)
    fetched = registry.get_by_id(artifact.policy_id)
    assert fetched is not None
    assert fetched.policy_id == artifact.policy_id


def test_get_missing_returns_none(registry: PolicyArtifactRegistry):
    assert registry.get("nonexistent") is None


# ---------------------------------------------------------------------------
# list_all / list_by_type / list_by_status
# ---------------------------------------------------------------------------

def test_list_all(registry: PolicyArtifactRegistry):
    registry.register(_make_artifact("p1"))
    registry.register(_make_artifact("p2"))
    all_policies = registry.list_all()
    names = {a.name for a in all_policies}
    assert "p1" in names and "p2" in names


def test_list_by_type(registry: PolicyArtifactRegistry):
    registry.register(_make_artifact("mut", PolicyType.mutation_policy))
    registry.register(_make_artifact("rout", PolicyType.routing_policy))
    results = registry.list_by_type("mutation_policy")
    assert all(a.policy_type == PolicyType.mutation_policy for a in results)
    assert any(a.name == "mut" for a in results)


def test_list_by_status(registry: PolicyArtifactRegistry):
    registry.register(_make_artifact("cand", status="candidate"))
    artifact = _make_artifact("promoted_p", status="candidate")
    registry.register(artifact)
    registry.update_status(artifact.policy_id, "promoted")
    promoted = registry.list_by_status("promoted")
    assert any(a.name == "promoted_p" for a in promoted)


# ---------------------------------------------------------------------------
# update_status / get_active_policy
# ---------------------------------------------------------------------------

def test_update_status(registry: PolicyArtifactRegistry):
    artifact = _make_artifact("canary_p")
    registry.register(artifact)
    updated = registry.update_status(artifact.policy_id, "canary")
    assert updated is True
    fetched = registry.get_by_id(artifact.policy_id)
    assert fetched.status == "canary"


def test_update_status_missing_returns_false(registry: PolicyArtifactRegistry):
    assert registry.update_status("no-such-id", "promoted") is False


def test_get_active_policy(registry: PolicyArtifactRegistry):
    artifact = _make_artifact("active_mut", PolicyType.mutation_policy)
    registry.register(artifact)
    registry.update_status(artifact.policy_id, "promoted")
    active = registry.get_active_policy("mutation_policy")
    assert active is not None
    assert active.policy_id == artifact.policy_id


def test_get_active_policy_none_when_not_promoted(registry: PolicyArtifactRegistry):
    registry.register(_make_artifact("just_candidate"))
    assert registry.get_active_policy("mutation_policy") is None


# ---------------------------------------------------------------------------
# deprecate
# ---------------------------------------------------------------------------

def test_deprecate_hides_from_list_all(registry: PolicyArtifactRegistry):
    registry.register(_make_artifact("old_policy"))
    registry.deprecate("old_policy", 1)
    all_policies = registry.list_all()
    assert not any(a.name == "old_policy" for a in all_policies)


# ---------------------------------------------------------------------------
# create_job / get_job / list_jobs / update_job_status
# ---------------------------------------------------------------------------

def test_create_and_get_job(registry: PolicyArtifactRegistry):
    job = _make_job()
    job_id = registry.create_job(job)
    assert job_id == job.job_id
    fetched = registry.get_job(job_id)
    assert fetched is not None
    assert fetched.job_id == job_id


def test_get_job_missing_returns_none(registry: PolicyArtifactRegistry):
    assert registry.get_job("no-such-job") is None


def test_list_jobs_all(registry: PolicyArtifactRegistry):
    registry.create_job(_make_job())
    registry.create_job(_make_job())
    jobs = registry.list_jobs()
    assert len(jobs) == 2


def test_list_jobs_by_status(registry: PolicyArtifactRegistry):
    j1 = _make_job()
    j2 = _make_job()
    registry.create_job(j1)
    registry.create_job(j2)
    registry.update_job_status(j1.job_id, "completed", result={"ok": True})
    completed = registry.list_jobs(status="completed")
    assert len(completed) == 1
    assert completed[0].job_id == j1.job_id


def test_update_job_status_with_error(registry: PolicyArtifactRegistry):
    job = _make_job()
    registry.create_job(job)
    updated = registry.update_job_status(job.job_id, "failed", error="out of memory")
    assert updated is True
    fetched = registry.get_job(job.job_id)
    assert fetched.status == TrainingStatus.failed
    assert "out of memory" in fetched.error_message
