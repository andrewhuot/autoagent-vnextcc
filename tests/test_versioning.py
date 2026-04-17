from __future__ import annotations

import pytest

from deployer.versioning import ConfigVersionManager


def test_save_active_clears_existing_canary_pointer(tmp_path) -> None:
    manager = ConfigVersionManager(str(tmp_path / "configs"))

    canary = manager.save_version({"name": "candidate"}, scores={"composite": 0.5}, status="canary")
    active = manager.save_version({"name": "stable"}, scores={"composite": 0.9}, status="active")

    manifest = manager.manifest
    assert manifest["active_version"] == active.version
    assert manifest["canary_version"] is None
    assert manager.get_version_summary(canary.version)["status"] == "retired"
    assert manager.get_version_summary(active.version)["status"] == "active"


def test_mark_canary_rejects_active_version(tmp_path) -> None:
    manager = ConfigVersionManager(str(tmp_path / "configs"))
    active = manager.save_version({"name": "stable"}, scores={"composite": 0.9}, status="active")

    with pytest.raises(ValueError, match="active"):
        manager.mark_canary(active.version)

    manifest = manager.manifest
    assert manifest["active_version"] == active.version
    assert manifest["canary_version"] is None
    assert manager.get_version_summary(active.version)["status"] == "active"


def test_promote_and_rollback_preserve_manifest_invariants(tmp_path) -> None:
    manager = ConfigVersionManager(str(tmp_path / "configs"))
    baseline = manager.save_version({"name": "baseline"}, scores={"composite": 0.7}, status="active")
    candidate = manager.save_version({"name": "candidate"}, scores={"composite": 0.8}, status="candidate")

    manager.mark_canary(candidate.version)
    assert manager.manifest["canary_version"] == candidate.version

    manager.promote(candidate.version)
    assert manager.manifest["active_version"] == candidate.version
    assert manager.manifest["canary_version"] is None
    assert manager.get_version_summary(baseline.version)["status"] == "retired"
    assert manager.get_version_summary(candidate.version)["status"] == "active"

    canary = manager.save_version({"name": "new-canary"}, scores={"composite": 0.75}, status="candidate")
    manager.mark_canary(canary.version)
    manager.rollback(canary.version)

    assert manager.manifest["active_version"] == candidate.version
    assert manager.manifest["canary_version"] is None
    assert manager.get_version_summary(canary.version)["status"] == "rolled_back"
