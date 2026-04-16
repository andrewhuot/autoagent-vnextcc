"""Tests for enhanced ConfigVersionManager: diff, summary, and listing."""

from __future__ import annotations

from pathlib import Path

import pytest

from deployer.versioning import ConfigVersionManager


# ── fixtures ─────────────────────────────────────────────────────────


@pytest.fixture()
def manager(tmp_path: Path) -> ConfigVersionManager:
    """Return a manager with two saved versions whose configs differ."""
    mgr = ConfigVersionManager(str(tmp_path / "configs"))

    config_a = {"model": "gpt-4", "temperature": 0.7, "prompts": {"root": "Hello"}}
    config_b = {"model": "gpt-4", "temperature": 0.9, "prompts": {"root": "Hi there"}}

    mgr.save_version(config_a, scores={"composite": 0.80}, status="active")
    mgr.save_version(config_b, scores={"quality": 0.9, "composite": 0.85}, status="canary")
    return mgr


# ── diff_versions ────────────────────────────────────────────────────


class TestDiffVersions:
    def test_diff_shows_changes(self, manager: ConfigVersionManager) -> None:
        diff = manager.diff_versions(1, 2)
        # Unified diff should contain file labels and changed lines
        assert "v001.yaml" in diff
        assert "v002.yaml" in diff
        assert "-" in diff or "+" in diff  # at least one changed line marker

    def test_diff_identical_content(self, tmp_path: Path) -> None:
        mgr = ConfigVersionManager(str(tmp_path / "configs"))
        same = {"model": "gpt-4", "temperature": 0.5}
        mgr.save_version(same, scores={"composite": 0.7}, status="active")
        mgr.save_version(same, scores={"composite": 0.7}, status="canary")

        assert mgr.diff_versions(1, 2) == "No changes"

    def test_diff_invalid_version_a(self, manager: ConfigVersionManager) -> None:
        result = manager.diff_versions(999, 1)
        assert "Error" in result
        assert "999" in result

    def test_diff_invalid_version_b(self, manager: ConfigVersionManager) -> None:
        result = manager.diff_versions(1, 888)
        assert "Error" in result
        assert "888" in result


# ── get_version_summary ──────────────────────────────────────────────


class TestGetVersionSummary:
    def test_summary_returns_correct_fields(self, manager: ConfigVersionManager) -> None:
        summary = manager.get_version_summary(1)
        assert summary["version"] == 1
        assert summary["status"] == "active"
        assert "config_hash" in summary
        assert "filename" in summary
        assert "timestamp" in summary
        assert summary["scores"] == {"composite": 0.80}

    def test_summary_for_canary(self, manager: ConfigVersionManager) -> None:
        summary = manager.get_version_summary(2)
        assert summary["status"] == "canary"
        assert summary["scores"]["quality"] == 0.9

    def test_summary_unknown_version(self, manager: ConfigVersionManager) -> None:
        summary = manager.get_version_summary(42)
        assert "error" in summary


# ── list_versions ────────────────────────────────────────────────────


class TestListVersions:
    def test_returns_newest_first(self, manager: ConfigVersionManager) -> None:
        versions = manager.list_versions()
        assert versions[0]["version"] == 2
        assert versions[1]["version"] == 1

    def test_returns_correct_count(self, manager: ConfigVersionManager) -> None:
        assert len(manager.list_versions()) == 2

    def test_respects_limit(self, manager: ConfigVersionManager) -> None:
        versions = manager.list_versions(limit=1)
        assert len(versions) == 1
        assert versions[0]["version"] == 2

    def test_limit_larger_than_total(self, manager: ConfigVersionManager) -> None:
        versions = manager.list_versions(limit=100)
        assert len(versions) == 2
