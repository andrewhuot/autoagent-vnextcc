from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from cli.settings import load_settings


BRIDGED_ENV_VARS = (
    "AGENTLAB_NO_TUI",
    "AGENTLAB_EXPOSE_SLASH_TO_MODEL",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
)


def _env_overrides() -> tuple[dict[str, object], list[str]]:
    try:
        from cli.settings.env_bridge import env_overrides
    except ModuleNotFoundError as exc:
        pytest.fail(f"cli.settings.env_bridge is missing: {exc}")
    return env_overrides()


def _clear_bridge_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in BRIDGED_ENV_VARS:
        monkeypatch.delenv(key, raising=False)


def _patch_settings_paths(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    import cli.settings as settings_mod

    monkeypatch.setattr(settings_mod, "SYSTEM_SETTINGS_PATH", root / "etc" / "settings.json")
    monkeypatch.setattr(settings_mod, "USER_SETTINGS_PATH", root / "home" / ".agentlab" / "settings.json")
    monkeypatch.setattr(settings_mod, "USER_CONFIG_PATH", root / "home" / ".agentlab" / "config.json")


def test_absent_env_vars_leave_settings_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_bridge_env(monkeypatch)

    assert _env_overrides() == ({}, [])


@pytest.mark.parametrize(
    ("env_name", "env_value", "dotted_path", "expected"),
    [
        ("AGENTLAB_NO_TUI", "1", "input.no_tui", True),
        ("AGENTLAB_NO_TUI", "false", "input.no_tui", False),
        ("AGENTLAB_EXPOSE_SLASH_TO_MODEL", "yes", "input.expose_slash_to_model", True),
        ("ANTHROPIC_API_KEY", "anthropic-key", "providers.anthropic_api_key", "anthropic-key"),
        ("OPENAI_API_KEY", "openai-key", "providers.openai_api_key", "openai-key"),
        ("GOOGLE_API_KEY", "google-key", "providers.google_api_key", "google-key"),
        ("GEMINI_API_KEY", "gemini-key", "providers.gemini_api_key", "gemini-key"),
    ],
)
def test_documented_env_vars_lift_to_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    env_name: str,
    env_value: str,
    dotted_path: str,
    expected: object,
) -> None:
    _clear_bridge_env(monkeypatch)
    _patch_settings_paths(monkeypatch, tmp_path)
    monkeypatch.setenv(env_name, env_value)

    settings = load_settings(tmp_path)

    node: object = settings
    for part in dotted_path.split("."):
        node = getattr(node, part)
    assert node == expected
    assert env_name in settings._env_overrides


def test_env_overrides_project_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_bridge_env(monkeypatch)
    _patch_settings_paths(monkeypatch, tmp_path)
    project_path = tmp_path / ".agentlab" / "settings.json"
    project_path.parent.mkdir(parents=True)
    project_path.write_text(
        json.dumps({"providers": {"anthropic_api_key": "from-file"}, "input": {"no_tui": False}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    monkeypatch.setenv("AGENTLAB_NO_TUI", "1")

    settings = load_settings(tmp_path)

    assert settings.providers.anthropic_api_key == "from-env"
    assert settings.input.no_tui is True


def test_no_tui_env_disables_tui_even_when_tui_requested(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_bridge_env(monkeypatch)
    _patch_settings_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENTLAB_TUI", "1")
    monkeypatch.setenv("AGENTLAB_NO_TUI", "1")
    monkeypatch.setenv("AGENTLAB_SKIP_ONBOARDING", "1")

    from cli.workbench_app import app as app_module

    class _TTY:
        def isatty(self) -> bool:
            return True

    tui_calls: list[str] = []

    def _fake_tui(*args: Any, **kwargs: Any) -> app_module.StubAppResult:
        tui_calls.append("called")
        raise AssertionError("TUI should not launch when AGENTLAB_NO_TUI=1")

    def _fake_run(*args: Any, **kwargs: Any) -> app_module.StubAppResult:
        return app_module.StubAppResult(lines_read=0, exited_via="eof")

    fake_tui_module = types.ModuleType("cli.workbench_app.tui.app")
    fake_tui_module.run_tui_app = _fake_tui

    monkeypatch.setattr(sys, "stdin", _TTY())
    monkeypatch.setitem(sys.modules, "cli.workbench_app.tui.app", fake_tui_module)
    monkeypatch.setattr(app_module, "run_workbench_app", _fake_run)
    monkeypatch.setattr(app_module, "_maybe_build_orchestrator", lambda *args, **kwargs: None)

    result = app_module.launch_workbench(None, show_banner=False)

    assert result.exited_via == "eof"
    assert tui_calls == []
