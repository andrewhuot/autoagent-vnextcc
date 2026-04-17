"""Tests for the one-time legacy settings migration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cli.settings.migration import MigrationResult, migrate_legacy_settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clear_bridge_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid bleed-through from the developer's real env."""
    for key in (
        "AGENTLAB_NO_TUI",
        "AGENTLAB_EXPOSE_SLASH_TO_MODEL",
        "AGENTLAB_MODEL",
        "AGENTLAB_PROVIDER",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "AGENTLAB_NO_SETTINGS_MIGRATION",
    ):
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_fresh_install_is_noop_when_no_legacy_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_bridge_env(monkeypatch)

    result = migrate_legacy_settings(tmp_path)

    assert isinstance(result, MigrationResult)
    assert result.migrated is False
    assert result.source == "none"
    assert result.keys_migrated == []
    # Marker file is still created so we don't re-scan on every launch.
    assert (tmp_path / ".settings_migrated_v1").exists()
    # No settings.json should be written for a true fresh install.
    assert not (tmp_path / "settings.json").exists()


def test_env_only_legacy_is_migrated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_bridge_env(monkeypatch)
    monkeypatch.setenv("AGENTLAB_MODEL", "claude-opus-4-5")
    monkeypatch.setenv("AGENTLAB_PROVIDER", "anthropic")
    monkeypatch.setenv("AGENTLAB_NO_TUI", "1")

    result = migrate_legacy_settings(tmp_path)

    assert result.migrated is True
    assert result.source == "env"
    assert "providers.default_model" in result.keys_migrated
    assert "providers.default_provider" in result.keys_migrated
    assert "input.no_tui" in result.keys_migrated

    written = json.loads((tmp_path / "settings.json").read_text("utf-8"))
    assert written["providers"]["default_model"] == "claude-opus-4-5"
    assert written["providers"]["default_provider"] == "anthropic"
    assert written["input"]["no_tui"] is True


def test_legacy_json_config_is_migrated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_bridge_env(monkeypatch)
    legacy = tmp_path / "config.json"
    legacy.write_text(
        json.dumps(
            {
                "providers.default_model": "gpt-5",
                "providers.default_provider": "openai",
                "permissions.mode": "acceptEdits",
                "future.unknown_key": "preserve me",
            }
        ),
        encoding="utf-8",
    )

    result = migrate_legacy_settings(tmp_path)

    assert result.migrated is True
    assert result.source == "legacy_config"

    written = json.loads((tmp_path / "settings.json").read_text("utf-8"))
    assert written["providers"]["default_model"] == "gpt-5"
    assert written["permissions"]["mode"] == "acceptEdits"
    # Forward-compat: unknown keys must survive.
    assert written["future"]["unknown_key"] == "preserve me"
    # Legacy file is left in place (non-destructive).
    assert legacy.exists()


def test_migration_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_bridge_env(monkeypatch)
    monkeypatch.setenv("AGENTLAB_MODEL", "claude-opus-4-5")

    first = migrate_legacy_settings(tmp_path)
    assert first.migrated is True

    # Mutate the env to something different so a re-run would otherwise overwrite.
    monkeypatch.setenv("AGENTLAB_MODEL", "different-model")

    second = migrate_legacy_settings(tmp_path)
    assert second.migrated is False
    assert second.source == "already_migrated"

    written = json.loads((tmp_path / "settings.json").read_text("utf-8"))
    # Original migrated value must still be there.
    assert written["providers"]["default_model"] == "claude-opus-4-5"


def test_escape_hatch_skips_migration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_bridge_env(monkeypatch)
    monkeypatch.setenv("AGENTLAB_MODEL", "claude-opus-4-5")
    monkeypatch.setenv("AGENTLAB_NO_SETTINGS_MIGRATION", "1")

    result = migrate_legacy_settings(tmp_path)

    assert result.migrated is False
    assert result.source == "skipped"
    assert not (tmp_path / "settings.json").exists()
    assert not (tmp_path / ".settings_migrated_v1").exists()


def test_marker_file_is_created_after_migration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_bridge_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")

    result = migrate_legacy_settings(tmp_path)

    assert result.migrated is True
    assert (tmp_path / ".settings_migrated_v1").exists()


def test_unknown_keys_in_legacy_config_are_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_bridge_env(monkeypatch)
    legacy = tmp_path / "config.json"
    legacy.write_text(
        json.dumps(
            {
                "experimental": {"flag_a": True, "flag_b": "x"},
                "providers.default_model": "claude",
            }
        ),
        encoding="utf-8",
    )

    result = migrate_legacy_settings(tmp_path)

    assert result.migrated is True
    written = json.loads((tmp_path / "settings.json").read_text("utf-8"))
    assert written["experimental"] == {"flag_a": True, "flag_b": "x"}


def test_existing_settings_file_skips_migration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the user already has a new-style settings.json, do nothing."""
    _clear_bridge_env(monkeypatch)
    existing = tmp_path / "settings.json"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text(
        json.dumps({"providers": {"default_model": "user-already-here"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTLAB_MODEL", "do-not-overwrite")

    result = migrate_legacy_settings(tmp_path)

    assert result.migrated is False
    assert result.source == "settings_present"
    written = json.loads(existing.read_text("utf-8"))
    assert written["providers"]["default_model"] == "user-already-here"


def test_creates_parent_dir_when_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_bridge_env(monkeypatch)
    monkeypatch.setenv("AGENTLAB_MODEL", "claude")

    nested = tmp_path / "deep" / "home" / ".agentlab"
    # Don't create the dir — migration must.
    result = migrate_legacy_settings(nested)

    assert result.migrated is True
    assert nested.exists()
    assert (nested / "settings.json").exists()
