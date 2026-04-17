"""Integration tests for the classifier + denial-tracker gate wired
into :func:`cli.tools.executor.execute_tool_call`.

These test the pre-check sequence added in P3.T3:

1. ``ClassifierContext`` is threaded in → classifier runs BEFORE the
   PermissionManager.decision_for_tool call.
2. ``AUTO_APPROVE`` short-circuits the legacy permission check entirely.
3. ``AUTO_DENY`` returns a DENY execution with
   ``denial_reason="classifier_deny"`` and increments the tracker.
4. ``PROMPT`` falls through to the existing ask-path (dialog fires).
5. Denial-tracker escalation: after N USER denials, even an
   AUTO_APPROVE command is forced to prompt.
6. The dialog's ``persist_scope=="settings"`` branch writes the new rule
   into the legacy ``settings.json`` allowlist, which the live
   classifier context reads from as its persisted source of truth.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from cli.permissions import PermissionManager
from cli.permissions.classifier import ClassifierContext
from cli.permissions.denial_tracking import DenialTracker
from cli.tools import ToolRegistry
from cli.tools.base import ToolContext
from cli.tools.bash_tool import BashTool
from cli.tools.executor import execute_tool_call
from cli.tools.file_edit import FileEditTool
from cli.workbench_app.permission_dialog import DialogChoice, DialogOutcome


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / ".agentlab").mkdir()
    return tmp_path


@pytest.fixture
def context(workspace: Path) -> ToolContext:
    return ToolContext(workspace_root=workspace)


def _ctx(workspace: Path) -> ClassifierContext:
    return ClassifierContext(workspace_root=workspace)


def _fail_dialog(*args: Any, **kwargs: Any) -> DialogOutcome:
    raise AssertionError("dialog should not have been invoked")


# ---------------------------------------------------------------------------
# AUTO_APPROVE short-circuit
# ---------------------------------------------------------------------------


def test_classifier_auto_approve_skips_permission_manager(
    workspace: Path, context: ToolContext
) -> None:
    """A whitelisted Bash command must bypass PermissionManager entirely."""
    registry = ToolRegistry()
    registry.register(BashTool())

    manager = MagicMock(spec=PermissionManager)
    manager.decision_for_tool.side_effect = AssertionError(
        "decision_for_tool should not be called for AUTO_APPROVE"
    )
    manager.mode = "default"

    execution = execute_tool_call(
        "Bash",
        {"command": "ls"},
        registry=registry,
        permissions=manager,
        context=context,
        dialog_runner=_fail_dialog,
        classifier_context=_ctx(workspace),
    )

    assert execution.decision.value == "allow"
    assert manager.decision_for_tool.call_count == 0


# ---------------------------------------------------------------------------
# AUTO_DENY → classifier_deny + tracker increment
# ---------------------------------------------------------------------------


def test_classifier_auto_deny_blocks_and_records_denial(
    workspace: Path, context: ToolContext
) -> None:
    """A persisted-deny pattern must short-circuit to DENY with
    ``denial_reason="classifier_deny"`` and increment the tracker."""
    registry = ToolRegistry()
    registry.register(BashTool())

    manager = PermissionManager(root=workspace)
    tracker = DenialTracker()

    ctx = ClassifierContext(
        workspace_root=workspace,
        persisted_deny_patterns=frozenset({"Bash"}),
    )

    execution = execute_tool_call(
        "Bash",
        {"command": "ls"},
        registry=registry,
        permissions=manager,
        context=context,
        dialog_runner=_fail_dialog,
        classifier_context=ctx,
        denial_tracker=tracker,
    )

    assert execution.decision.value == "deny"
    assert execution.denial_reason == "classifier_deny"
    assert tracker.denial_count("Bash") == 1


# ---------------------------------------------------------------------------
# PROMPT → existing ASK path
# ---------------------------------------------------------------------------


def test_classifier_prompt_falls_through_to_existing_ask(
    workspace: Path, context: ToolContext
) -> None:
    """An unknown bash command (PROMPT) must route through the existing
    dialog path — the dialog runner fires and the user can approve."""
    (workspace / "a.txt").write_text("hi", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(BashTool())
    manager = PermissionManager(root=workspace)

    calls: list[str] = []

    def dialog(tool: Any, tool_input: Any, *, include_persist_option: bool) -> DialogOutcome:
        calls.append(tool_input.get("command", ""))
        return DialogOutcome(
            choice=DialogChoice.APPROVE,
            allow=True,
            persist_rule=None,
            persist_scope=None,
        )

    execution = execute_tool_call(
        "Bash",
        # echo triggers a metachar-free unknown first token → PROMPT
        {"command": "banana-custom-script"},
        registry=registry,
        permissions=manager,
        context=context,
        dialog_runner=dialog,
        classifier_context=_ctx(workspace),
    )

    assert calls == ["banana-custom-script"]
    # The command fails to execute (not a real binary) but the DIALOG
    # was consulted — that's the contract we're testing.
    assert execution.decision.value == "allow"


# ---------------------------------------------------------------------------
# Denial-tracker escalation
# ---------------------------------------------------------------------------


def test_tracker_escalation_overrides_auto_approve(
    workspace: Path, context: ToolContext
) -> None:
    """After N denials, a normally AUTO_APPROVE bash command must force
    the PROMPT path instead of silently allowing."""
    registry = ToolRegistry()
    registry.register(BashTool())
    manager = PermissionManager(root=workspace)

    tracker = DenialTracker(max_per_session_per_tool=2)
    tracker.record_denial("Bash")
    tracker.record_denial("Bash")
    assert tracker.should_escalate_to_prompt("Bash")

    dialog_calls: list[str] = []

    def dialog(tool: Any, tool_input: Any, *, include_persist_option: bool) -> DialogOutcome:
        dialog_calls.append(tool_input.get("command", ""))
        return DialogOutcome(
            choice=DialogChoice.DENY,
            allow=False,
            persist_rule=None,
            persist_scope=None,
        )

    execution = execute_tool_call(
        "Bash",
        {"command": "ls"},  # normally AUTO_APPROVE
        registry=registry,
        permissions=manager,
        context=context,
        dialog_runner=dialog,
        classifier_context=_ctx(workspace),
        denial_tracker=tracker,
    )

    # Escalated to prompt, user denied.
    assert dialog_calls == ["ls"]
    assert execution.decision.value == "deny"
    assert execution.denial_reason == "user_deny"


def test_user_deny_records_denial_for_tracker(
    workspace: Path, context: ToolContext
) -> None:
    """A user pressing deny in the permission dialog must advance the
    per-tool tracker so future safe calls can escalate back to prompt."""
    registry = ToolRegistry()
    registry.register(BashTool())
    manager = PermissionManager(root=workspace)
    tracker = DenialTracker(max_per_session_per_tool=1)

    def dialog(tool: Any, tool_input: Any, *, include_persist_option: bool) -> DialogOutcome:
        return DialogOutcome(
            choice=DialogChoice.DENY,
            allow=False,
            persist_rule=None,
            persist_scope=None,
        )

    execution = execute_tool_call(
        "Bash",
        {"command": "banana-custom-script"},
        registry=registry,
        permissions=manager,
        context=context,
        dialog_runner=dialog,
        classifier_context=_ctx(workspace),
        denial_tracker=tracker,
    )

    assert execution.decision.value == "deny"
    assert execution.denial_reason == "user_deny"
    assert tracker.denial_count("Bash") == 1


# ---------------------------------------------------------------------------
# Dialog persist_scope=="settings" → both stores updated
# ---------------------------------------------------------------------------


def test_persist_rule_writes_settings_rule(
    workspace: Path, context: ToolContext
) -> None:
    """The settings-scope persist branch must write the allow rule into
    ``settings.json`` so future classifier contexts can read it back
    from the P0 settings cascade."""
    (workspace / "a.txt").write_text("one", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(FileEditTool())
    manager = PermissionManager(root=workspace)

    def persist_dialog(
        tool: Any, tool_input: Any, *, include_persist_option: bool
    ) -> DialogOutcome:
        return DialogOutcome(
            choice=DialogChoice.APPROVE_PERSIST,
            allow=True,
            persist_rule="tool:FileEdit:*",
            persist_scope="settings",
        )

    execute_tool_call(
        "FileEdit",
        {"path": "a.txt", "old_string": "one", "new_string": "two"},
        registry=registry,
        permissions=manager,
        context=context,
        dialog_runner=persist_dialog,
        classifier_context=_ctx(workspace),
    )

    settings = json.loads(
        (workspace / ".agentlab" / "settings.json").read_text(encoding="utf-8")
    )
    assert "tool:FileEdit:*" in settings["permissions"]["rules"]["allow"]
