"""Tests for cli/settings.py — CLI settings hierarchy."""

from __future__ import annotations

import json
from pathlib import Path

from cli.settings import (
    DEFAULTS,
    ResolvedSettings,
    Sessions,
    _deep_merge,
    _flatten_dotted,
    _load_json,
    load_settings,
    resolve_settings,
    save_local_settings,
    save_project_settings,
    save_user_config,
    settings_file_paths,
)


def test_deep_merge_flat() -> None:
    base = {"a": 1, "b": 2}
    override = {"b": 3, "c": 4}
    assert _deep_merge(base, override) == {"a": 1, "b": 3, "c": 4}


def test_deep_merge_nested() -> None:
    base = {"shell": {"prompt": ">", "color": True}, "x": 1}
    override = {"shell": {"prompt": "$"}}
    result = _deep_merge(base, override)
    assert result == {"shell": {"prompt": "$", "color": True}, "x": 1}


def test_deep_merge_does_not_mutate_base() -> None:
    base = {"a": {"b": 1}}
    override = {"a": {"c": 2}}
    _deep_merge(base, override)
    assert base == {"a": {"b": 1}}


def test_flatten_dotted_simple() -> None:
    assert _flatten_dotted({"shell.prompt": ">"}) == {"shell": {"prompt": ">"}}


def test_flatten_dotted_multiple_levels() -> None:
    result = _flatten_dotted({"a.b.c": 1})
    assert result == {"a": {"b": {"c": 1}}}


def test_flatten_dotted_no_dots() -> None:
    assert _flatten_dotted({"key": "val"}) == {"key": "val"}


def test_load_json_missing_file(tmp_path: Path) -> None:
    assert _load_json(tmp_path / "nope.json") == {}


def test_load_json_valid(tmp_path: Path) -> None:
    path = tmp_path / "test.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    assert _load_json(path) == {"a": 1}


def test_load_json_invalid(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("not json!", encoding="utf-8")
    assert _load_json(path) == {}


def test_resolved_settings_get_dotted() -> None:
    settings = ResolvedSettings(values={"shell": {"prompt": "$"}})
    assert settings.get("shell.prompt") == "$"


def test_resolved_settings_get_default() -> None:
    settings = ResolvedSettings(values={})
    assert settings.get("missing.key", "fallback") == "fallback"


def test_resolved_settings_get_top_level() -> None:
    settings = ResolvedSettings(values={"mode": "plan"})
    assert settings.get("mode") == "plan"


def test_sessions_is_re_exported() -> None:
    assert Sessions.__name__ == "Sessions"


def test_resolve_defaults_when_no_files(tmp_path: Path, monkeypatch) -> None:
    import cli.settings as settings_mod

    monkeypatch.setattr(
        settings_mod,
        "USER_CONFIG_PATH",
        tmp_path / "noexist" / "config.json",
    )
    settings = resolve_settings()
    assert settings.get("shell.show_status_bar") == DEFAULTS["shell.show_status_bar"]


def test_load_settings_uses_package_level_path_monkeypatches(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import cli.settings as settings_mod

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(settings_mod, "SYSTEM_SETTINGS_PATH", tmp_path / "etc" / "agentlab" / "settings.json")
    monkeypatch.setattr(settings_mod, "USER_CONFIG_DIR", fake_home / ".agentlab")
    monkeypatch.setattr(settings_mod, "USER_CONFIG_PATH", fake_home / ".agentlab" / "config.json")
    monkeypatch.setattr(settings_mod, "USER_SETTINGS_PATH", fake_home / ".agentlab" / "settings.json")

    settings_mod.USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    settings_mod.USER_CONFIG_PATH.write_text(
        json.dumps({"theme": {"name": "ocean"}}),
        encoding="utf-8",
    )

    settings = load_settings(tmp_path)

    assert settings.theme["name"] == "ocean"


def test_resolve_project_overrides_defaults(tmp_path: Path) -> None:
    agentlab_dir = tmp_path / ".agentlab"
    agentlab_dir.mkdir()
    (agentlab_dir / "settings.json").write_text(
        json.dumps({"shell.prompt": "project> "}),
        encoding="utf-8",
    )
    settings = resolve_settings(workspace_dir=tmp_path)
    assert settings.get("shell.prompt") == "project> "


def test_resolve_local_overrides_project(tmp_path: Path) -> None:
    agentlab_dir = tmp_path / ".agentlab"
    agentlab_dir.mkdir()
    (agentlab_dir / "settings.json").write_text(
        json.dumps({"shell.prompt": "project> "}),
        encoding="utf-8",
    )
    (agentlab_dir / "settings.local.json").write_text(
        json.dumps({"shell.prompt": "local> "}),
        encoding="utf-8",
    )
    settings = resolve_settings(workspace_dir=tmp_path)
    assert settings.get("shell.prompt") == "local> "


def test_resolve_session_overrides_local(tmp_path: Path) -> None:
    agentlab_dir = tmp_path / ".agentlab"
    agentlab_dir.mkdir()
    (agentlab_dir / "settings.local.json").write_text(
        json.dumps({"mode": "local-mode"}),
        encoding="utf-8",
    )
    settings = resolve_settings(
        workspace_dir=tmp_path,
        session_overrides={"mode": "session-mode"},
    )
    assert settings.get("mode") == "session-mode"


def test_resolve_flags_override_everything(tmp_path: Path) -> None:
    settings = resolve_settings(
        workspace_dir=tmp_path,
        session_overrides={"mode": "session"},
        flag_overrides={"mode": "flag"},
    )
    assert settings.get("mode") == "flag"


def test_save_project_settings(tmp_path: Path) -> None:
    (tmp_path / ".agentlab").mkdir()
    path = save_project_settings(tmp_path, {"shell.prompt": "saved> "})
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["shell.prompt"] == "saved> "


def test_save_local_settings(tmp_path: Path) -> None:
    (tmp_path / ".agentlab").mkdir()
    path = save_local_settings(tmp_path, {"mode": "test"})
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mode"] == "test"


def test_save_user_config(tmp_path: Path, monkeypatch: "pytest.MonkeyPatch") -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    import cli.settings as settings_mod

    monkeypatch.setattr(settings_mod, "USER_CONFIG_DIR", fake_home / ".agentlab")
    monkeypatch.setattr(
        settings_mod,
        "USER_CONFIG_PATH",
        fake_home / ".agentlab" / "config.json",
    )
    path = save_user_config({"output.color": False})
    assert path.exists()


def test_settings_file_paths_with_workspace(tmp_path: Path) -> None:
    paths = settings_file_paths(workspace_dir=tmp_path)
    labels = [label for label, _ in paths]
    assert "user" in labels
    assert "project" in labels
    assert "local" in labels


def test_settings_file_paths_without_workspace() -> None:
    paths = settings_file_paths(workspace_dir=None)
    assert len(paths) == 1
    assert paths[0][0] == "user"
