"""Tests for agent-config checkpoint / rewind (F3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cli.workbench_app.checkpoint import (
    CHECKPOINT_STATUS,
    CheckpointManager,
    CheckpointRecord,
)
from deployer.versioning import ConfigVersionManager


@pytest.fixture
def configs_dir(tmp_path: Path) -> Path:
    """Seed a ``configs/`` directory with one active version."""
    configs = tmp_path / "configs"
    versions = ConfigVersionManager(configs_dir=str(configs))
    versions.save_version(
        config={"model": "gemini-2.5-flash", "routing": {"rules": []}},
        scores={"composite": 0.8},
        status="active",
    )
    return configs


def test_snapshot_writes_new_version_with_reason(configs_dir: Path) -> None:
    """/checkpoint should create a new version marked as a checkpoint."""
    manager = CheckpointManager(configs_dir=configs_dir)

    record = manager.snapshot(reason="pre_guardrail_change")

    assert isinstance(record, CheckpointRecord)
    assert record.status == CHECKPOINT_STATUS
    assert record.reason == "pre_guardrail_change"
    assert (configs_dir / record.filename).exists()


def test_snapshot_returns_none_when_no_active_config(tmp_path: Path) -> None:
    """Snapshots are best-effort when the workspace has no active config."""
    empty = tmp_path / "configs"
    manager = CheckpointManager(configs_dir=empty)

    assert manager.snapshot(reason="manual") is None


def test_list_checkpoints_only_returns_checkpoint_entries(configs_dir: Path) -> None:
    """``/checkpoints`` should hide candidate and active rows."""
    manager = CheckpointManager(configs_dir=configs_dir)
    first = manager.snapshot(reason="first")
    assert first is not None
    second = manager.snapshot(reason="second")
    assert second is not None

    records = manager.list_checkpoints()

    assert [record.reason for record in records] == ["second", "first"]


def test_rewind_promotes_prior_version_and_rolls_forward_back(configs_dir: Path) -> None:
    """Rewinding promotes the target and rolls back any intervening versions."""
    versions = ConfigVersionManager(configs_dir=str(configs_dir))
    base_active = versions.manifest.get("active_version")
    assert base_active is not None

    versions.save_version(
        config={"model": "gemini-2.5-flash", "routing": {"rules": ["new"]}},
        scores={"composite": 0.9},
        status="active",
    )
    manager = CheckpointManager(configs_dir=configs_dir)

    record = manager.rewind(base_active)

    assert record.version == base_active
    versions.reload()
    assert versions.manifest["active_version"] == base_active
    rolled = [
        entry
        for entry in versions.manifest["versions"]
        if entry["version"] > base_active
    ]
    assert rolled and all(entry["status"] == "rolled_back" for entry in rolled)


def test_rewind_raises_on_unknown_version(configs_dir: Path) -> None:
    """Unknown versions should raise ``ValueError`` so /rewind can surface it."""
    manager = CheckpointManager(configs_dir=configs_dir)

    with pytest.raises(ValueError, match="Unknown checkpoint version"):
        manager.rewind(999)
