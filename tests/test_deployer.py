"""Unit tests for config versioning and canary deployment logic."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from deployer.canary import CanaryManager
from deployer.versioning import ConfigVersionManager
from logger.store import ConversationStore

from tests.helpers import build_record


def _log_outcomes(
    store: ConversationStore,
    *,
    config_version: str,
    successes: int,
    failures: int,
) -> None:
    for _ in range(successes):
        store.log(
            build_record(
                config_version=config_version,
                outcome="success",
                agent_response="I can help with this request in detail.",
            )
        )
    for _ in range(failures):
        store.log(
            build_record(
                config_version=config_version,
                outcome="fail",
                agent_response="No",
            )
        )


def test_version_manager_save_and_promote(base_config: dict, tmp_path: Path) -> None:
    """ConfigVersionManager should track active/canary versions and promotions."""
    manager = ConfigVersionManager(str(tmp_path / "configs"))

    manager.save_version(base_config, scores={"composite": 0.7}, status="active")

    canary_config = deepcopy(base_config)
    canary_config["prompts"]["root"] = canary_config["prompts"]["root"] + " Be extra clear."
    canary_version = manager.save_version(
        canary_config,
        scores={"composite": 0.8},
        status="canary",
    )

    assert manager.manifest["active_version"] == 1
    assert manager.manifest["canary_version"] == canary_version.version

    manager.promote(canary_version.version)

    assert manager.manifest["active_version"] == canary_version.version
    assert manager.manifest["canary_version"] is None

    versions = {entry["version"]: entry["status"] for entry in manager.get_version_history()}
    assert versions[1] == "retired"
    assert versions[canary_version.version] == "active"


def test_canary_rolls_back_when_underperforming(base_config: dict, tmp_path: Path) -> None:
    """Canary should roll back when success rate is significantly worse than baseline."""
    store = ConversationStore(str(tmp_path / "conversations.db"))
    manager = ConfigVersionManager(str(tmp_path / "configs"))
    manager.save_version(base_config, scores={"composite": 0.7}, status="active")

    canary_config = deepcopy(base_config)
    canary_config["thresholds"]["max_turns"] = 18
    manager.save_version(canary_config, scores={"composite": 0.72}, status="canary")

    _log_outcomes(store, config_version="v001", successes=9, failures=1)
    _log_outcomes(store, config_version="v002", successes=3, failures=7)

    canary = CanaryManager(
        manager,
        store=store,
        min_canary_conversations=5,
        max_canary_duration_s=9999,
    )
    status = canary.check_canary()
    assert status.verdict == "rollback"

    action = canary.execute_verdict(status)
    assert "Rolled back v002" in action
    assert manager.manifest["canary_version"] is None


def test_canary_promotes_when_healthy(base_config: dict, tmp_path: Path) -> None:
    """Canary should promote when it meets the minimum success threshold."""
    store = ConversationStore(str(tmp_path / "conversations.db"))
    manager = ConfigVersionManager(str(tmp_path / "configs"))
    manager.save_version(base_config, scores={"composite": 0.7}, status="active")

    canary_config = deepcopy(base_config)
    canary_config["prompts"]["root"] = canary_config["prompts"]["root"] + " Validate every answer."
    manager.save_version(canary_config, scores={"composite": 0.82}, status="canary")

    _log_outcomes(store, config_version="v001", successes=4, failures=6)
    _log_outcomes(store, config_version="v002", successes=8, failures=2)

    canary = CanaryManager(
        manager,
        store=store,
        min_canary_conversations=5,
        max_canary_duration_s=9999,
    )
    status = canary.check_canary()
    assert status.verdict == "promote"

    action = canary.execute_verdict(status)
    assert "Promoted v002 to active" in action
    assert manager.manifest["active_version"] == 2
    assert manager.manifest["canary_version"] is None


def test_version_manager_rejects_unknown_version_actions(tmp_path: Path) -> None:
    """Promote/rollback should fail fast when an unknown version is requested."""
    manager = ConfigVersionManager(str(tmp_path / "configs"))
    with pytest.raises(ValueError):
        manager.promote(999)
    with pytest.raises(ValueError):
        manager.rollback(999)
