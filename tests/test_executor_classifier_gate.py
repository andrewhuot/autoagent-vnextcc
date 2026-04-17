"""Integration tests for the classifier + denial-tracker gate wired
into :func:`cli.tools.executor.execute_tool_call`.

These test the pre-check sequence added in P3.T3:

1. ``ClassifierContext`` is threaded in → classifier runs BEFORE the
   PermissionManager.decision_for_tool call.
2. ``AUTO_APPROVE`` short-circuits the legacy permission check entirely.
3. ``AUTO_DENY`` returns a DENY execution with
   ``denial_reason="classifier_deny"`` and increments the tracker.
4. ``PROMPT`` falls through to the existing ask-path (dialog fires).
5. Denial-tracker escalation: after N denials, even an AUTO_APPROVE
   command is forced to prompt.
6. The dialog's ``persist_scope=="settings"`` branch writes the new rule
   into BOTH the legacy ``settings.json`` allowlist AND the classifier
   allowlist JSON.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from cli.permissions import PermissionManager
from cli.permissions.classifier import ClassifierContext, ClassifierDecision
from cli.permissions.classifier_persistence import (
    CLASSIFIER_ALLOWLIST_FILENAME,
    load_persisted_patterns,
)
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


# ---------------------------------------------------------------------------
# Dialog persist_scope=="settings" → both stores updated
# ---------------------------------------------------------------------------


def test_persist_rule_writes_classifier_allowlist(
    workspace: Path, context: ToolContext
) -> None:
    """The settings-scope persist branch must update BOTH the legacy
    settings.json allowlist AND the classifier allowlist JSON."""
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

    # Legacy store still updated (back-compat).
    settings = json.loads(
        (workspace / ".agentlab" / "settings.json").read_text(encoding="utf-8")
    )
    assert "tool:FileEdit:*" in settings["permissions"]["rules"]["allow"]

    # New classifier allowlist file written.
    classifier_path = workspace / ".agentlab" / CLASSIFIER_ALLOWLIST_FILENAME
    assert classifier_path.exists()
    assert load_persisted_patterns(workspace) == frozenset({"tool:FileEdit:*"})


# ---------------------------------------------------------------------------
# P5.T2 — Dialog persist_scope=="session" must teach through to the classifier
# ---------------------------------------------------------------------------
#
# Before P5.T2, approving a tool with "always this session" only taught the
# legacy PermissionManager._session_allow list. The classifier's
# ``persisted_allow_patterns`` was a frozen snapshot taken once at the
# orchestrator boundary, so the next identical tool call in the same session
# re-ran the classifier heuristic from scratch — which for tools whose
# default is PROMPT (FileEdit, FileWrite, unknown) meant the dialog fired
# again. Users hit "always this session" precisely to avoid that.
#
# The fix lives inside ``execute_tool_call``: before invoking the classifier,
# merge ``permissions._session_allow`` into ``classifier_context.persisted_allow_patterns``.
# That keeps ``ClassifierContext`` immutable while still letting the live
# session state influence each subsequent decision.


def test_persist_rule_session_scope_teaches_classifier_for_next_call(
    workspace: Path, context: ToolContext
) -> None:
    """After the user chooses "Approve always (this session)" for FileEdit,
    the very next FileEdit in the same session must AUTO_APPROVE via the
    classifier — no dialog, no PermissionManager ask path."""
    (workspace / "a.txt").write_text("one", encoding="utf-8")
    (workspace / "b.txt").write_text("three", encoding="utf-8")

    registry = ToolRegistry()
    registry.register(FileEditTool())
    manager = PermissionManager(root=workspace)

    # First call: dialog returns APPROVE_PERSIST with session scope.
    first_dialog_calls = 0

    def first_dialog(
        tool: Any, tool_input: Any, *, include_persist_option: bool
    ) -> DialogOutcome:
        nonlocal first_dialog_calls
        first_dialog_calls += 1
        return DialogOutcome(
            choice=DialogChoice.APPROVE_PERSIST,
            allow=True,
            persist_rule="tool:FileEdit:*",
            persist_scope="session",
        )

    first_exec = execute_tool_call(
        "FileEdit",
        {"path": "a.txt", "old_string": "one", "new_string": "two"},
        registry=registry,
        permissions=manager,
        context=context,
        dialog_runner=first_dialog,
        classifier_context=_ctx(workspace),
    )
    assert first_exec.decision.value == "allow"
    assert first_dialog_calls == 1

    # A session-scope rule must NOT have written to settings.json on disk.
    # (If it did, we'd be violating the user's "this session only" intent.)
    settings_path = workspace / ".agentlab" / "settings.json"
    if settings_path.exists():
        raw = json.loads(settings_path.read_text(encoding="utf-8"))
        allow_list = (
            raw.get("permissions", {}).get("rules", {}).get("allow", [])
            if isinstance(raw, dict)
            else []
        )
        assert "tool:FileEdit:*" not in allow_list, (
            "session scope must not persist to settings.json"
        )
    classifier_path = workspace / ".agentlab" / CLASSIFIER_ALLOWLIST_FILENAME
    assert not classifier_path.exists(), (
        "session scope must not persist to the classifier JSON"
    )

    # Second call: classifier sees the session-allow pattern and AUTO_APPROVES.
    # The dialog runner must NOT be invoked again.
    second_exec = execute_tool_call(
        "FileEdit",
        {"path": "b.txt", "old_string": "three", "new_string": "four"},
        registry=registry,
        permissions=manager,
        context=context,
        dialog_runner=_fail_dialog,   # asserts if called
        classifier_context=_ctx(workspace),
    )
    assert second_exec.decision.value == "allow"


def test_session_scope_merge_does_not_mutate_classifier_context(
    workspace: Path, context: ToolContext
) -> None:
    """The ``ClassifierContext`` passed in by the caller is a frozen
    dataclass — the executor must never mutate it. We assert the caller's
    context object is observationally unchanged after the call."""
    (workspace / "a.txt").write_text("one", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(FileEditTool())
    manager = PermissionManager(root=workspace)

    def dialog(tool: Any, tool_input: Any, *, include_persist_option: bool) -> DialogOutcome:
        return DialogOutcome(
            choice=DialogChoice.APPROVE_PERSIST,
            allow=True,
            persist_rule="tool:FileEdit:*",
            persist_scope="session",
        )

    caller_ctx = _ctx(workspace)
    before = caller_ctx.persisted_allow_patterns
    execute_tool_call(
        "FileEdit",
        {"path": "a.txt", "old_string": "one", "new_string": "two"},
        registry=registry,
        permissions=manager,
        context=context,
        dialog_runner=dialog,
        classifier_context=caller_ctx,
    )
    assert caller_ctx.persisted_allow_patterns is before
    assert caller_ctx.persisted_allow_patterns == frozenset()


def test_session_allow_from_permissions_is_visible_to_classifier_on_first_call(
    workspace: Path, context: ToolContext
) -> None:
    """If the caller has already populated ``permissions._session_allow``
    (e.g. via a /permissions command), the executor must honor it on the
    very first tool call — without requiring the dialog to run first."""
    (workspace / "a.txt").write_text("one", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(FileEditTool())
    manager = PermissionManager(root=workspace)
    manager.allow_for_session("tool:FileEdit:*")

    execution = execute_tool_call(
        "FileEdit",
        {"path": "a.txt", "old_string": "one", "new_string": "two"},
        registry=registry,
        permissions=manager,
        context=context,
        dialog_runner=_fail_dialog,
        classifier_context=_ctx(workspace),
    )
    assert execution.decision.value == "allow"


def test_session_allow_is_reported_as_auto_approve_in_audit_log(
    workspace: Path, context: ToolContext, tmp_path: Path
) -> None:
    """When the caller has session-allowed a pattern, the classifier
    audit log must record the decision as AUTO_APPROVE — not PROMPT with
    a downstream legacy allow. Otherwise an operator reading the audit
    log sees a pile of misleading PROMPT entries for tools the user
    explicitly whitelisted for the session."""
    from cli.permissions.audit_log import ClassifierAuditLog

    (workspace / "a.txt").write_text("one", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(FileEditTool())
    manager = PermissionManager(root=workspace)
    manager.allow_for_session("tool:FileEdit:*")
    audit = ClassifierAuditLog(path=tmp_path / "audit.jsonl")

    execute_tool_call(
        "FileEdit",
        {"path": "a.txt", "old_string": "one", "new_string": "two"},
        registry=registry,
        permissions=manager,
        context=context,
        dialog_runner=_fail_dialog,
        classifier_context=_ctx(workspace),
        audit_log=audit,
    )

    entries = list(audit.iter_recent())
    assert len(entries) == 1
    entry = entries[0]
    # The classifier decision — not the final PermissionDecision — is
    # what the audit log stores. A session-allowed pattern should drive
    # the classifier to AUTO_APPROVE.
    assert entry["decision"] == ClassifierDecision.AUTO_APPROVE.value, entry
