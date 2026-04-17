from __future__ import annotations

import json
from pathlib import Path

import pytest

from cli.settings import (
    LOCAL_SETTINGS_FILENAME,
    PROJECT_SETTINGS_FILENAME,
    Settings,
    load_settings,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _patch_settings_paths(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
) -> None:
    import cli.settings as settings_mod

    monkeypatch.setattr(
        settings_mod,
        "SYSTEM_SETTINGS_PATH",
        root / "etc" / "agentlab" / "settings.json",
    )
    monkeypatch.setattr(
        settings_mod,
        "USER_SETTINGS_PATH",
        root / "home" / ".agentlab" / "settings.json",
    )
    monkeypatch.setattr(
        settings_mod,
        "USER_CONFIG_PATH",
        root / "home" / ".agentlab" / "config.json",
    )


def test_defaults_only_accepts_empty_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings_paths(monkeypatch, tmp_path)

    settings = load_settings(tmp_path)

    assert isinstance(settings, Settings)
    assert settings.permissions.mode == "default"
    assert settings.hooks.timeout_seconds == 5
    assert settings.input.no_tui is False
    assert settings.providers.default_model is None


@pytest.mark.parametrize(
    ("layers", "expected_mode", "expected_model"),
    [
        (
            {"system": {"permissions": {"mode": "system-only"}}},
            "system-only",
            None,
        ),
        (
            {"user": {"permissions": {"mode": "acceptEdits"}}},
            "acceptEdits",
            None,
        ),
        (
            {
                "user": {
                    "permissions": {"mode": "acceptEdits"},
                    "providers": {"default_model": "user-model"},
                },
                "project": {"permissions": {"mode": "dontAsk"}},
            },
            "dontAsk",
            "user-model",
        ),
        (
            {
                "project": {"permissions": {"mode": "dontAsk"}},
                "local": {
                    "permissions": {"mode": "plan"},
                    "providers": {"default_model": "local-model"},
                },
            },
            "plan",
            "local-model",
        ),
    ],
)
def test_layer_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    layers: dict[str, dict],
    expected_mode: str,
    expected_model: str | None,
) -> None:
    _patch_settings_paths(monkeypatch, tmp_path)

    _write_json(tmp_path / "etc" / "agentlab" / "settings.json", layers.get("system", {}))
    _write_json(tmp_path / "home" / ".agentlab" / "config.json", layers.get("legacy_user", {}))
    _write_json(tmp_path / "home" / ".agentlab" / "settings.json", layers.get("user", {}))

    workspace = tmp_path / "workspace"
    _write_json(workspace / ".agentlab" / PROJECT_SETTINGS_FILENAME, layers.get("project", {}))
    _write_json(workspace / ".agentlab" / LOCAL_SETTINGS_FILENAME, layers.get("local", {}))

    settings = load_settings(workspace)

    assert settings.permissions.mode == expected_mode
    assert settings.providers.default_model == expected_model


def test_legacy_flat_config_expands_into_typed_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings_paths(monkeypatch, tmp_path)
    _write_json(
        tmp_path / "home" / ".agentlab" / "config.json",
        {
            "shell.prompt": "legacy> ",
            "providers.default_model": "legacy-model",
            "permissions.mode": "acceptEdits",
        },
    )

    settings = load_settings(tmp_path)

    assert settings.shell["prompt"] == "legacy> "
    assert settings.providers.default_model == "legacy-model"
    assert settings.permissions.mode == "acceptEdits"


def test_legacy_theme_settings_are_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings_paths(monkeypatch, tmp_path)
    _write_json(
        tmp_path / "home" / ".agentlab" / "config.json",
        {"theme": {"name": "ocean"}},
    )

    settings = load_settings(tmp_path)

    assert settings.theme["name"] == "ocean"
    assert settings.get("theme.name") == "ocean"


def test_strict_live_setting_is_accepted_from_project_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings_paths(monkeypatch, tmp_path)
    _write_json(
        tmp_path / "workspace" / ".agentlab" / PROJECT_SETTINGS_FILENAME,
        {"permissions": {"strict_live": True}},
    )

    settings = load_settings(tmp_path / "workspace")

    assert settings.permissions.strict_live is True
    assert settings.get("permissions.strict_live") is True


def test_models_settings_are_accepted_from_project_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings_paths(monkeypatch, tmp_path)
    _write_json(
        tmp_path / "workspace" / ".agentlab" / PROJECT_SETTINGS_FILENAME,
        {"models": {"proposer": "anthropic:claude-sonnet-4-5"}},
    )

    settings = load_settings(tmp_path / "workspace")

    assert settings.models["proposer"] == "anthropic:claude-sonnet-4-5"
    assert settings.get("models.proposer") == "anthropic:claude-sonnet-4-5"


def test_partial_overlap_keeps_unset_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings_paths(monkeypatch, tmp_path)
    _write_json(
        tmp_path / "workspace" / ".agentlab" / PROJECT_SETTINGS_FILENAME,
        {"providers": {"default_model": "project-model"}},
    )

    settings = load_settings(tmp_path / "workspace")

    assert settings.providers.default_model == "project-model"
    assert settings.providers.default_provider is None
    assert settings.permissions.mode == "default"
    assert settings.hooks.timeout_seconds == 5


def test_list_replacement_does_not_merge_items(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings_paths(monkeypatch, tmp_path)
    _write_json(
        tmp_path / "etc" / "agentlab" / "settings.json",
        {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "*",
                        "hooks": [{"type": "command", "command": "echo system"}],
                    }
                ]
            }
        },
    )
    _write_json(
        tmp_path / "workspace" / ".agentlab" / PROJECT_SETTINGS_FILENAME,
        {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "write",
                        "hooks": [{"type": "command", "command": "echo project"}],
                    }
                ]
            }
        },
    )

    settings = load_settings(tmp_path / "workspace")

    assert len(settings.hooks.PreToolUse) == 1
    assert settings.hooks.PreToolUse[0].matcher == "write"
    assert settings.hooks.PreToolUse[0].hooks[0].command == "echo project"
