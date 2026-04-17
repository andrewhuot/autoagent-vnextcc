"""R7 Slice C.4 — strict-live gate in ``build_workbench_runtime``.

When a workspace opts in via ``permissions.strict_live: true`` in
``.agentlab/settings.json``, the runtime constructor must refuse to
build a chat runtime if the caller signals that no provider key is
configured. The refusal is communicated by raising
:class:`cli.strict_live.MockFallbackError` so the existing R1 exit-code
machinery (``EXIT_MOCK_FALLBACK`` / ``EXIT_MISSING_PROVIDER``) can
translate it at the CLI boundary.

The gate is purely additive:

* The new kwarg ``provider_key_present`` defaults to ``True`` so legacy
  callers (TUI, tests) keep working.
* Workspaces without ``permissions.strict_live`` (or without a settings
  file at all) do not gate — the chat runtime tolerates mock fallback
  outside strict mode for R7 back-compat.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

import pytest

from cli.llm.streaming import MessageStop
from cli.llm.types import TurnMessage
from cli.strict_live import MockFallbackError
from cli.workbench_app.orchestrator_runtime import build_workbench_runtime


# ---------------------------------------------------------------------------
# Fakes + fixtures
# ---------------------------------------------------------------------------


class _ScriptedModel:
    """Minimal fake satisfying the ``ModelClient`` protocol."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def stream(
        self,
        *,
        system_prompt: str,
        messages: list[TurnMessage],
        tools: list[dict[str, Any]],
    ) -> Iterator[Any]:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": [m.to_wire() for m in messages],
                "tools": tools,
            }
        )
        yield MessageStop(stop_reason="end_turn")


def _write_settings(workspace_root: Path, payload: dict[str, Any]) -> None:
    """Write a workspace ``.agentlab/settings.json`` with ``payload``."""
    agentlab_dir = workspace_root / ".agentlab"
    agentlab_dir.mkdir(parents=True, exist_ok=True)
    (agentlab_dir / "settings.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


# ---------------------------------------------------------------------------
# Behaviour
# ---------------------------------------------------------------------------


def test_strict_live_with_provider_key_builds_successfully(workspace: Path) -> None:
    _write_settings(workspace, {"permissions": {"strict_live": True}})

    runtime = build_workbench_runtime(
        workspace_root=workspace,
        model=_ScriptedModel(),
        provider_key_present=True,
    )
    assert runtime is not None
    assert runtime.orchestrator is not None


def test_strict_live_without_provider_key_raises_mock_fallback_error(
    workspace: Path,
) -> None:
    _write_settings(workspace, {"permissions": {"strict_live": True}})

    with pytest.raises(MockFallbackError):
        build_workbench_runtime(
            workspace_root=workspace,
            model=_ScriptedModel(),
            provider_key_present=False,
        )


def test_no_strict_live_without_key_builds_with_no_gate(workspace: Path) -> None:
    """Non-strict workspaces tolerate a missing provider key — the gate
    is opt-in. This pins the back-compat contract for legacy workspaces."""
    _write_settings(workspace, {"permissions": {"strict_live": False}})

    runtime = build_workbench_runtime(
        workspace_root=workspace,
        model=_ScriptedModel(),
        provider_key_present=False,
    )
    assert runtime is not None


def test_no_settings_file_at_all_does_not_gate(workspace: Path) -> None:
    """Fresh workspace with no settings.json — no gate. The runtime must
    not require the agentlab config dir to exist before building."""
    # Note: workspace fixture intentionally does NOT create .agentlab here.
    runtime = build_workbench_runtime(
        workspace_root=workspace,
        model=_ScriptedModel(),
        provider_key_present=False,
    )
    assert runtime is not None


def test_strict_live_message_mentions_anthropic_api_key(workspace: Path) -> None:
    _write_settings(workspace, {"permissions": {"strict_live": True}})

    with pytest.raises(MockFallbackError) as excinfo:
        build_workbench_runtime(
            workspace_root=workspace,
            model=_ScriptedModel(),
            provider_key_present=False,
        )

    assert "ANTHROPIC_API_KEY" in str(excinfo.value)


def test_strict_live_message_mentions_settings_path(workspace: Path) -> None:
    _write_settings(workspace, {"permissions": {"strict_live": True}})

    with pytest.raises(MockFallbackError) as excinfo:
        build_workbench_runtime(
            workspace_root=workspace,
            model=_ScriptedModel(),
            provider_key_present=False,
        )

    rendered = str(excinfo.value)
    assert "permissions.strict_live" in rendered or "settings.json" in rendered


def test_strict_live_setting_is_workspace_scoped(tmp_path: Path) -> None:
    workspace_a = tmp_path / "ws_a"
    workspace_a.mkdir()
    _write_settings(workspace_a, {"permissions": {"strict_live": True}})

    workspace_b = tmp_path / "ws_b"
    workspace_b.mkdir()
    # No strict_live setting in workspace_b.

    with pytest.raises(MockFallbackError):
        build_workbench_runtime(
            workspace_root=workspace_a,
            model=_ScriptedModel(),
            provider_key_present=False,
        )

    runtime_b = build_workbench_runtime(
        workspace_root=workspace_b,
        model=_ScriptedModel(),
        provider_key_present=False,
    )
    assert runtime_b is not None


def test_default_provider_key_present_true_is_back_compat(workspace: Path) -> None:
    """Calling without the new kwarg must keep the old behaviour even
    when strict_live is set — the gate only fires when the caller
    explicitly admits no key. This pins back-compat for callers that
    haven't been updated yet (e.g. the TUI)."""
    _write_settings(workspace, {"permissions": {"strict_live": True}})

    runtime = build_workbench_runtime(
        workspace_root=workspace,
        model=_ScriptedModel(),
    )
    assert runtime is not None
