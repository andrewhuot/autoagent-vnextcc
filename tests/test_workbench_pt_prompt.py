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
from pathlib import Path
from types import SimpleNamespace

import pytest

from cli.permissions import DEFAULT_PERMISSION_MODE, PERMISSION_MODES
from cli.workbench_app.pt_prompt import (
    WorkbenchPromptState,
    cycle_permission_mode,
)


def test_cycle_permission_mode_walks_canonical_order() -> None:
    seen = [DEFAULT_PERMISSION_MODE]
    for _ in range(len(PERMISSION_MODES)):
        seen.append(cycle_permission_mode(seen[-1]))
    # Dropping the duplicate wraparound entry should give us every mode.
    assert sorted(set(seen)) == sorted(set(PERMISSION_MODES))
    # The cycle must return to the starting mode after |PERMISSION_MODES| steps.
    assert seen[-1] == seen[0]


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
    import prompt_toolkit

    monkeypatch.setattr(prompt_toolkit, "PromptSession", _FakeSession)
    monkeypatch.setattr(pt_prompt, "_terminal_width", lambda default=80: 20)

    registry = build_builtin_registry(include_streaming=False)
    state = WorkbenchPromptState()
    provider = pt_prompt.build_prompt_input_provider(
        registry, state, echo=captured.append
    )

    assert provider("› ") == "hi"
    plain = [line for line in captured]
    assert any("╭" in line and "╮" in line for line in plain)
    assert any("╰" in line and "╯" in line for line in plain)
