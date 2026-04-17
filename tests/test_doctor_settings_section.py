"""Tests for the /doctor settings cascade section."""

from __future__ import annotations

from pathlib import Path

import pytest

from cli.doctor_sections import settings_section
from cli.settings import Settings


def test_settings_section_returns_dict_with_expected_top_keys() -> None:
    settings = Settings()
    section = settings_section(settings)

    # Structural keys callers depend on.
    for key in (
        "loaded_layers",
        "env_overrides",
        "permission_mode",
        "providers",
        "sessions_root",
        "hooks",
    ):
        assert key in section, f"missing {key} in settings_section"


def test_settings_section_reports_loaded_layers_with_paths() -> None:
    settings = Settings()
    settings._loaded_layers = [
        {"layer": "user", "path": "/tmp/u/settings.json", "exists": "true"},
        {"layer": "project", "path": "/tmp/p/.agentlab/settings.json", "exists": "false"},
    ]
    section = settings_section(settings)

    # Each entry must include both the source label and a path string so
    # the user can audit which file is being read.
    layers = section["loaded_layers"]
    assert isinstance(layers, list)
    assert any(layer.get("path") == "/tmp/u/settings.json" for layer in layers)
    assert any(layer.get("layer") == "project" for layer in layers)


def test_settings_section_reports_env_overrides() -> None:
    settings = Settings()
    settings._env_overrides = ["ANTHROPIC_API_KEY", "AGENTLAB_NO_TUI"]

    section = settings_section(settings)

    assert "ANTHROPIC_API_KEY" in section["env_overrides"]
    assert "AGENTLAB_NO_TUI" in section["env_overrides"]


def test_settings_section_does_not_leak_api_key_values() -> None:
    settings = Settings.model_validate(
        {
            "providers": {
                "default_provider": "anthropic",
                "default_model": "claude-opus",
                "anthropic_api_key": "sk-do-not-print-me",
            },
        }
    )
    section = settings_section(settings)

    rendered = repr(section)
    assert "sk-do-not-print-me" not in rendered
    # But provider/model identifiers should still surface.
    assert section["providers"]["default_provider"] == "anthropic"
    assert section["providers"]["default_model"] == "claude-opus"


def test_settings_section_reports_hook_counts_per_event() -> None:
    settings = Settings.model_validate(
        {
            "hooks": {
                "beforeQuery": [{"hooks": [{"command": "echo before"}]}],
                "PreToolUse": [
                    {"matcher": "Bash", "hooks": [{"command": "echo pre"}]},
                    {"matcher": "FileEdit", "hooks": [{"command": "echo pre2"}]},
                ],
            }
        }
    )

    section = settings_section(settings)

    assert section["hooks"]["beforeQuery"] == 1
    assert section["hooks"]["PreToolUse"] == 2


def test_settings_section_reports_permission_mode_and_sessions_root() -> None:
    settings = Settings.model_validate(
        {
            "permissions": {"mode": "acceptEdits"},
            "sessions": {"root": "/var/agentlab/sessions"},
        }
    )

    section = settings_section(settings)

    assert section["permission_mode"] == "acceptEdits"
    assert section["sessions_root"] == "/var/agentlab/sessions"


def test_render_settings_section_yields_human_lines() -> None:
    """The text-mode renderer must produce non-empty lines and no secret leakage."""
    from cli.doctor_sections import render_settings_section

    settings = Settings.model_validate(
        {
            "permissions": {"mode": "default"},
            "providers": {
                "default_model": "claude",
                "anthropic_api_key": "sk-secret",
            },
        }
    )
    settings._loaded_layers = [
        {"layer": "user", "path": "/u/settings.json"},
    ]
    settings._env_overrides = ["ANTHROPIC_API_KEY"]

    lines = render_settings_section(settings)

    assert isinstance(lines, list)
    assert any("Settings" in line for line in lines)
    text = "\n".join(lines)
    assert "sk-secret" not in text
    assert "ANTHROPIC_API_KEY" in text


def test_settings_section_handles_partial_settings_without_crash() -> None:
    """Doctor must degrade gracefully if settings load partially."""
    settings = Settings()
    # Simulate a half-loaded settings: missing private attrs default to empty.
    section = settings_section(settings)

    assert section["loaded_layers"] == []
    assert section["env_overrides"] == []
    # Default permission mode is "default"
    assert section["permission_mode"] == "default"
