"""Tests for ``ask_for_session`` and the AgentLab permission preset (R7.B.5).

The preset closes the gap from default-mode ``_MODE_RULES["default"]`` —
which routes any tool not in its short ``ask`` list (FileEdit/FileWrite/
Bash/ConfigEdit) to ``allow`` via the ``allow: ["*"]`` catch-all. Out of the
box that lets the model run ``EvalRun``, ``Deploy:*``, ``ImproveRun`` and
``ImproveAccept`` without prompting; the preset routes them through the
``ask`` gate via the new in-memory session-ask layer.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cli.permissions import PermissionManager, settings_path
from cli.workbench_app.agentlab_tools import (
    ImproveDiffTool,
    ImproveListTool,
    ImproveShowTool,
)
from cli.workbench_app.permission_preset import (
    AGENTLAB_ASK_PATTERNS,
    apply_agentlab_defaults,
)


# --------------------------------------------------------------------------
# Test helpers
# --------------------------------------------------------------------------


def _write_settings(root: Path, rules: dict[str, list[str]]) -> Path:
    """Persist a permissions.rules block under ``root/.agentlab/settings.json``."""
    path = root / ".agentlab" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"permissions": {"rules": rules}}, indent=2),
        encoding="utf-8",
    )
    return path


# --------------------------------------------------------------------------
# PermissionManager extension — ask_for_session
# --------------------------------------------------------------------------


def test_ask_for_session_records_pattern(tmp_path: Path) -> None:
    """``ask_for_session`` appends to ``_session_ask`` once per pattern."""
    manager = PermissionManager(root=tmp_path)
    manager.ask_for_session("tool:EvalRun")
    assert manager._session_ask == ["tool:EvalRun"]
    # Idempotent — calling twice does not duplicate.
    manager.ask_for_session("tool:EvalRun")
    assert manager._session_ask == ["tool:EvalRun"]


def test_ask_for_session_decision_routes_through_ask(tmp_path: Path) -> None:
    """A bare manager with one ask pattern returns ``ask`` for that action."""
    manager = PermissionManager(root=tmp_path)
    # Default mode would otherwise fall through to ``allow: ["*"]``.
    assert manager.decision_for("tool:EvalRun") == "allow"
    manager.ask_for_session("tool:EvalRun")
    assert manager.decision_for("tool:EvalRun") == "ask"


def test_ask_for_session_below_explicit_allow(tmp_path: Path) -> None:
    """Workspace explicit ``allow`` rules win over the in-memory ask pattern.

    Users who deliberately allowlist a tool in ``settings.json`` should keep
    that decision even after the preset is applied.
    """
    _write_settings(tmp_path, {"allow": ["tool:EvalRun"]})
    manager = PermissionManager(root=tmp_path)
    manager.ask_for_session("tool:EvalRun")
    assert manager.decision_for("tool:EvalRun") == "allow"


def test_ask_for_session_below_explicit_deny(tmp_path: Path) -> None:
    """Explicit deny still wins — preset is purely an upgrade from allow."""
    _write_settings(tmp_path, {"deny": ["tool:EvalRun"]})
    manager = PermissionManager(root=tmp_path)
    manager.ask_for_session("tool:EvalRun")
    assert manager.decision_for("tool:EvalRun") == "deny"


def test_ask_for_session_below_explicit_ask(tmp_path: Path) -> None:
    """Explicit ask matches first — outcome unchanged but ordering verified."""
    _write_settings(tmp_path, {"ask": ["tool:EvalRun"]})
    manager = PermissionManager(root=tmp_path)
    manager.ask_for_session("tool:EvalRun")
    assert manager.decision_for("tool:EvalRun") == "ask"


def test_ask_for_session_above_session_allow(tmp_path: Path) -> None:
    """``_session_allow`` (an explicit user "always-yes") still wins.

    The session-allow layer represents an explicit dialog choice and should
    not be silently downgraded to ``ask`` by a programmatic preset.
    """
    manager = PermissionManager(root=tmp_path)
    manager.allow_for_session("tool:X")
    manager.ask_for_session("tool:X")
    assert manager.decision_for("tool:X") == "allow"


def test_ask_for_session_below_session_deny(tmp_path: Path) -> None:
    """``_session_deny`` is the strongest signal and outranks ask."""
    manager = PermissionManager(root=tmp_path)
    manager.deny_for_session("tool:X")
    manager.ask_for_session("tool:X")
    assert manager.decision_for("tool:X") == "deny"


# --------------------------------------------------------------------------
# Preset
# --------------------------------------------------------------------------


def test_apply_agentlab_defaults_adds_eval_run_ask(tmp_path: Path) -> None:
    """``EvalRun`` flips from default-mode ``allow`` to ``ask``."""
    manager = PermissionManager(root=tmp_path)
    apply_agentlab_defaults(manager)
    assert manager.decision_for("tool:EvalRun") == "ask"


def test_apply_agentlab_defaults_adds_deploy_glob(tmp_path: Path) -> None:
    """``tool:Deploy:*`` should match every Deploy strategy via fnmatch."""
    manager = PermissionManager(root=tmp_path)
    apply_agentlab_defaults(manager)
    assert manager.decision_for("tool:Deploy:canary") == "ask"
    assert manager.decision_for("tool:Deploy:full") == "ask"
    assert manager.decision_for("tool:Deploy:immediate") == "ask"


def test_apply_agentlab_defaults_adds_improve_run_ask(tmp_path: Path) -> None:
    manager = PermissionManager(root=tmp_path)
    apply_agentlab_defaults(manager)
    assert manager.decision_for("tool:ImproveRun") == "ask"


def test_apply_agentlab_defaults_adds_improve_accept_ask(tmp_path: Path) -> None:
    manager = PermissionManager(root=tmp_path)
    apply_agentlab_defaults(manager)
    assert manager.decision_for("tool:ImproveAccept") == "ask"


def test_apply_agentlab_defaults_does_not_block_read_only_tools(tmp_path: Path) -> None:
    """Read-only inspection tools short-circuit to ``allow`` regardless of preset."""
    manager = PermissionManager(root=tmp_path)
    apply_agentlab_defaults(manager)
    assert manager.decision_for_tool(ImproveListTool(), {}) == "allow"
    assert manager.decision_for_tool(ImproveShowTool(), {}) == "allow"
    assert manager.decision_for_tool(ImproveDiffTool(), {}) == "allow"


def test_apply_agentlab_defaults_idempotent(tmp_path: Path) -> None:
    """Calling the preset twice neither duplicates patterns nor changes decisions."""
    manager = PermissionManager(root=tmp_path)
    apply_agentlab_defaults(manager)
    first_snapshot = list(manager._session_ask)
    apply_agentlab_defaults(manager)
    assert manager._session_ask == first_snapshot
    # Decisions unchanged.
    assert manager.decision_for("tool:EvalRun") == "ask"
    assert manager.decision_for("tool:Deploy:canary") == "ask"
    assert manager.decision_for("tool:ImproveRun") == "ask"
    assert manager.decision_for("tool:ImproveAccept") == "ask"


def test_apply_agentlab_defaults_does_not_persist_to_settings_json(tmp_path: Path) -> None:
    """The preset is purely in-memory — it must not write settings.json."""
    manager = PermissionManager(root=tmp_path)
    apply_agentlab_defaults(manager)
    assert not settings_path(tmp_path).exists()


def test_agentlab_ask_patterns_includes_expected_tools() -> None:
    """The exported pattern list pins the tools the preset gates."""
    assert "tool:EvalRun" in AGENTLAB_ASK_PATTERNS
    assert "tool:ImproveRun" in AGENTLAB_ASK_PATTERNS
    assert "tool:ImproveAccept" in AGENTLAB_ASK_PATTERNS
    assert "tool:Deploy:*" in AGENTLAB_ASK_PATTERNS
