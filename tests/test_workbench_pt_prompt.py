"""Tests for the prompt_toolkit-backed input provider.

Covers:

- :func:`cycle_permission_mode` — pure helper, no prompt_toolkit needed.
- border rendering — asserts the top/bottom frame is echoed exactly once
  per call and matches the terminal width.
- persistence — ``WorkbenchPromptState.persist`` writes through to
  ``.agentlab/settings.json`` via ``update_workspace_settings``.
- graceful failure — ``persist`` swallows write errors and flags them.
"""

from __future__ import annotations

import json
import sys
from types import ModuleType, SimpleNamespace
from pathlib import Path

import click
import pytest

from cli.permissions import DEFAULT_PERMISSION_MODE
from cli.workbench_app.pt_prompt import (
    PROMPT_PERMISSION_MODE_CYCLE,
    WorkbenchPromptState,
    render_bottom_toolbar,
    cycle_permission_mode,
)


def _install_fake_prompt_toolkit(
    monkeypatch: pytest.MonkeyPatch,
    session_cls: type,
) -> None:
    """Install a tiny prompt_toolkit stub for tests that do not need a TTY."""
    prompt_toolkit = ModuleType("prompt_toolkit")
    prompt_toolkit.PromptSession = session_cls  # type: ignore[attr-defined]

    formatted_text = ModuleType("prompt_toolkit.formatted_text")

    class ANSI(str):
        pass

    class FormattedText(list):
        pass

    formatted_text.ANSI = ANSI  # type: ignore[attr-defined]
    formatted_text.FormattedText = FormattedText  # type: ignore[attr-defined]

    history = ModuleType("prompt_toolkit.history")

    class InMemoryHistory:
        pass

    history.InMemoryHistory = InMemoryHistory  # type: ignore[attr-defined]

    key_binding = ModuleType("prompt_toolkit.key_binding")

    class KeyBindings:
        def __init__(self) -> None:
            self.bindings: list[SimpleNamespace] = []

        def add(self, *keys: str):
            def decorator(fn):
                self.bindings.append(SimpleNamespace(keys=keys, handler=fn))
                return fn

            return decorator

    key_binding.KeyBindings = KeyBindings  # type: ignore[attr-defined]

    shortcuts = ModuleType("prompt_toolkit.shortcuts")
    shortcuts.CompleteStyle = SimpleNamespace(COLUMN="COLUMN")  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "prompt_toolkit", prompt_toolkit)
    monkeypatch.setitem(sys.modules, "prompt_toolkit.formatted_text", formatted_text)
    monkeypatch.setitem(sys.modules, "prompt_toolkit.history", history)
    monkeypatch.setitem(sys.modules, "prompt_toolkit.key_binding", key_binding)
    monkeypatch.setitem(sys.modules, "prompt_toolkit.shortcuts", shortcuts)


def test_cycle_permission_mode_walks_canonical_order() -> None:
    seen = [DEFAULT_PERMISSION_MODE]
    for _ in range(len(PROMPT_PERMISSION_MODE_CYCLE)):
        seen.append(cycle_permission_mode(seen[-1]))

    assert seen == ["default", "acceptEdits", "plan", "bypass", "default"]


def test_cycle_permission_mode_keeps_dontask_as_loadable_compatibility() -> None:
    """Persisted dontAsk settings should escape back into the visible cycle."""
    assert cycle_permission_mode("dontAsk") == DEFAULT_PERMISSION_MODE


def test_cycle_permission_mode_falls_back_on_unknown_input() -> None:
    assert cycle_permission_mode("not-a-real-mode") == DEFAULT_PERMISSION_MODE


def test_prompt_state_persist_writes_settings(tmp_path: Path) -> None:
    workspace = SimpleNamespace(root=tmp_path)
    state = WorkbenchPromptState(workspace=workspace, mode="acceptEdits")
    state.persist()

    settings_path = tmp_path / ".agentlab" / "settings.json"
    assert settings_path.exists()
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    assert data["permissions"]["mode"] == "acceptEdits"
    assert state._persisted_failed is False


def test_prompt_state_persist_flags_failure_on_readonly_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = SimpleNamespace(root=tmp_path)
    state = WorkbenchPromptState(workspace=workspace, mode="plan")

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("read-only filesystem")

    monkeypatch.setattr("cli.workbench_app.pt_prompt.update_workspace_settings", _boom)
    state.persist()
    assert state._persisted_failed is True


def test_prompt_state_persist_noop_without_workspace() -> None:
    state = WorkbenchPromptState(workspace=None, mode="plan")
    state.persist()  # Must not raise — state has no root to write to.
    assert state._persisted_failed is False


def test_build_prompt_input_provider_registers_slash_and_shift_tab_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The popup keybinding wiring (/ opens menu, shift+tab cycles modes)
    must survive refactors — regressing it silently breaks the UX.
    """
    from cli.workbench_app import pt_prompt
    from cli.workbench_app.slash import build_builtin_registry

    captured_kwargs: dict[str, object] = {}

    class _FakeSession:
        def __init__(self, **kwargs: object) -> None:
            captured_kwargs.update(kwargs)

        def prompt(self, _prompt: str) -> str:
            return ""

    _install_fake_prompt_toolkit(monkeypatch, _FakeSession)

    registry = build_builtin_registry(include_streaming=False)
    pt_prompt.build_prompt_input_provider(
        registry, WorkbenchPromptState(), echo=lambda _s: None
    )

    bindings = captured_kwargs.get("key_bindings")
    assert bindings is not None
    binding_strs = {
        ",".join(str(key) for key in binding.keys)
        for binding in bindings.bindings
    }
    assert "/" in binding_strs
    assert any("s-tab" in b or "Keys.BackTab" in b for b in binding_strs)

    assert captured_kwargs.get("complete_while_typing") is True
    assert captured_kwargs.get("reserve_space_for_menu", 0) >= 6
    assert captured_kwargs.get("history") is not None
    assert captured_kwargs.get("enable_history_search") is True


def test_bottom_toolbar_compacts_to_single_line_on_narrow_width() -> None:
    """The prompt-owned toolbar should not consume two rows in short terminals."""
    toolbar = render_bottom_toolbar("default", width=36)
    assert "\n" not in toolbar
    assert "Default permissions on" in toolbar
    assert "shift+tab" in toolbar
    assert len(toolbar) <= 36


def test_bottom_toolbar_keeps_full_hint_when_width_allows() -> None:
    toolbar = render_bottom_toolbar("plan", width=96)
    assert "\n" not in toolbar
    assert "Plan Mode permissions on" in toolbar
    assert "? shortcuts" in toolbar
    assert "/ commands" in toolbar
    assert "ctrl+t transcript" in toolbar


def test_build_prompt_input_provider_renders_borders(monkeypatch: pytest.MonkeyPatch) -> None:
    """Borders should wrap every prompt call, even when prompt_toolkit
    raises (e.g. EOF) — we rely on a ``try / finally`` for that.
    """
    from cli.workbench_app import pt_prompt
    from cli.workbench_app.slash import build_builtin_registry

    captured: list[str] = []

    class _FakeSession:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def prompt(self, _prompt: str) -> str:
            return "hi"

    # Swap the real PromptSession for a stub so the test doesn't open a TTY.
    _install_fake_prompt_toolkit(monkeypatch, _FakeSession)
    monkeypatch.setattr(pt_prompt, "_terminal_width", lambda default=80: 20)

    registry = build_builtin_registry(include_streaming=False)
    state = WorkbenchPromptState()
    provider = pt_prompt.build_prompt_input_provider(
        registry, state, echo=captured.append
    )

    assert provider("› ") == "hi"
    plain = [click.unstyle(line) for line in captured]
    # Rounded-corner input card: one ╭──╮ top and one ╰──╯ bottom.
    top_corners = [line for line in plain if line.startswith("╭") and line.endswith("╮")]
    bottom_corners = [line for line in plain if line.startswith("╰") and line.endswith("╯")]
    assert len(top_corners) == 1
    assert len(bottom_corners) == 1
    # Both corners span the mocked 20-column width.
    assert len(top_corners[0]) == 20
    assert len(bottom_corners[0]) == 20
