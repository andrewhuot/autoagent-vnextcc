"""Tests for the Phase-4 hook framework and executor integration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cli.hooks import (
    HookDefinition,
    HookEvent,
    HookOutcome,
    HookRegistry,
    HookVerdict,
    load_hook_registry,
)
from cli.hooks.registry import HookProcessResult
from cli.permissions import PermissionManager
from cli.tools.base import ToolContext
from cli.tools.executor import execute_tool_call
from cli.tools.file_edit import FileEditTool
from cli.tools.file_read import FileReadTool
from cli.tools.registry import ToolRegistry
from cli.workbench_app.permission_dialog import DialogChoice, DialogOutcome


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / ".agentlab").mkdir()
    return tmp_path


@pytest.fixture
def context(workspace: Path) -> ToolContext:
    return ToolContext(workspace_root=workspace)


# ---------------------------------------------------------------------------
# Parsing settings.json
# ---------------------------------------------------------------------------


def test_load_hook_registry_parses_nested_block() -> None:
    settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {"type": "command", "command": "./check.sh", "timeout_seconds": 5}
                    ],
                }
            ],
            "Stop": [
                {"hooks": [{"command": "echo done"}]},
            ],
        }
    }
    registry = load_hook_registry(settings)
    pre = registry.hooks_for(HookEvent.PRE_TOOL_USE, tool_name="Bash")
    assert len(pre) == 1
    assert pre[0].command == "./check.sh"
    assert pre[0].timeout_seconds == 5
    # Stop hooks ignore the tool_name matcher even if one is supplied.
    stop = registry.hooks_for(HookEvent.STOP, tool_name="Bash")
    assert len(stop) == 1


def test_load_hook_registry_skips_unknown_types() -> None:
    settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {"type": "prompt", "command": "ignore me"},
                        {"type": "command", "command": "./ok.sh"},
                    ],
                }
            ]
        }
    }
    registry = load_hook_registry(settings)
    hooks = registry.hooks_for(HookEvent.PRE_TOOL_USE, tool_name="Bash")
    assert [h.command for h in hooks] == ["./ok.sh"]


def test_load_hook_registry_ignores_unknown_events() -> None:
    settings = {
        "hooks": {
            "MadeUpEvent": [
                {"matcher": "", "hooks": [{"command": "echo hi"}]}
            ]
        }
    }
    registry = load_hook_registry(settings)
    # No known events — no definitions.
    assert registry.definitions == {} or all(
        not values for values in registry.definitions.values()
    )


def test_matcher_fnmatch_semantics() -> None:
    hook = HookDefinition(
        event=HookEvent.PRE_TOOL_USE,
        matcher="File*",
        command="noop",
    )
    assert hook.matches_tool("FileRead") is True
    assert hook.matches_tool("FileEdit") is True
    assert hook.matches_tool("Bash") is False
    assert HookDefinition(
        event=HookEvent.STOP, matcher="", command="noop"
    ).matches_tool("anything") is True


# ---------------------------------------------------------------------------
# Firing semantics
# ---------------------------------------------------------------------------


def test_fire_allows_when_no_hooks_subscribed() -> None:
    registry = HookRegistry()
    outcome = registry.fire(HookEvent.PRE_TOOL_USE, tool_name="Bash")
    assert outcome.verdict is HookVerdict.ALLOW
    assert outcome.messages == []


def test_fire_gating_stops_on_first_deny() -> None:
    calls: list[str] = []

    def runner(hook, payload):
        calls.append(hook.command)
        if hook.command == "deny":
            return HookProcessResult(returncode=1, stdout="", stderr="blocked")
        return HookProcessResult(returncode=0, stdout="", stderr="")

    registry = HookRegistry(runner=runner)
    registry.add(HookDefinition(event=HookEvent.PRE_TOOL_USE, matcher="", command="first"))
    registry.add(HookDefinition(event=HookEvent.PRE_TOOL_USE, matcher="", command="deny"))
    registry.add(HookDefinition(event=HookEvent.PRE_TOOL_USE, matcher="", command="skipped"))

    outcome = registry.fire(HookEvent.PRE_TOOL_USE, tool_name="Bash")
    assert outcome.verdict is HookVerdict.DENY
    assert "blocked" in outcome.messages
    assert calls == ["first", "deny"]  # third hook never fires


def test_fire_non_gating_runs_every_hook() -> None:
    calls: list[str] = []

    def runner(hook, payload):
        calls.append(hook.command)
        return HookProcessResult(returncode=1, stdout="", stderr="warn")

    registry = HookRegistry(runner=runner)
    registry.add(HookDefinition(event=HookEvent.POST_TOOL_USE, matcher="", command="one"))
    registry.add(HookDefinition(event=HookEvent.POST_TOOL_USE, matcher="", command="two"))

    outcome = registry.fire(HookEvent.POST_TOOL_USE, tool_name="Bash")
    # PostToolUse is non-gating so a non-zero exit degrades to deny but
    # does not block subsequent hooks.
    assert calls == ["one", "two"]
    assert outcome.verdict is HookVerdict.DENY
    assert outcome.messages == ["warn", "warn"]


def test_fire_timeout_records_deny_for_gating_event() -> None:
    def runner(hook, payload):
        return HookProcessResult(returncode=124, stdout="", stderr="", timed_out=True)

    registry = HookRegistry(runner=runner)
    registry.add(HookDefinition(event=HookEvent.PRE_TOOL_USE, matcher="", command="slow"))
    outcome = registry.fire(HookEvent.PRE_TOOL_USE, tool_name="Bash")
    assert outcome.verdict is HookVerdict.DENY
    assert any("timed out" in msg for msg in outcome.messages)


# ---------------------------------------------------------------------------
# Executor integration
# ---------------------------------------------------------------------------


def test_executor_pre_tool_use_deny_blocks_invocation(
    workspace: Path, context: ToolContext
) -> None:
    (workspace / "a.txt").write_text("old", encoding="utf-8")
    tool_registry = ToolRegistry()
    tool_registry.register(FileEditTool())
    permissions = PermissionManager(root=workspace)

    hook_registry = HookRegistry(runner=lambda hook, payload: HookProcessResult(
        returncode=1, stdout="", stderr="pre denied",
    ))
    hook_registry.add(HookDefinition(
        event=HookEvent.PRE_TOOL_USE, matcher="", command="noop",
    ))

    # Approve at the dialog so we prove the pre-tool-use hook is consulted
    # after permission, not before — and still blocks.
    def approve_dialog(tool, tool_input, *, include_persist_option):
        return DialogOutcome(
            choice=DialogChoice.APPROVE,
            allow=True,
            persist_rule=None,
            persist_scope=None,
        )

    execution = execute_tool_call(
        "FileEdit",
        {"path": "a.txt", "old_string": "old", "new_string": "new"},
        registry=tool_registry,
        permissions=permissions,
        context=context,
        dialog_runner=approve_dialog,
        hook_registry=hook_registry,
    )
    assert execution.decision.value == "deny"
    assert execution.denial_reason == "hook_deny"
    assert (workspace / "a.txt").read_text() == "old"


def test_executor_on_permission_request_allow_skips_dialog(
    workspace: Path, context: ToolContext
) -> None:
    (workspace / "a.txt").write_text("old", encoding="utf-8")
    tool_registry = ToolRegistry()
    tool_registry.register(FileEditTool())
    permissions = PermissionManager(root=workspace)

    hook_registry = HookRegistry(runner=lambda hook, payload: HookProcessResult(
        returncode=0, stdout="", stderr="auto-approved",
    ))
    hook_registry.add(HookDefinition(
        event=HookEvent.ON_PERMISSION_REQUEST, matcher="", command="noop",
    ))

    def fail_if_called(*args, **kwargs):
        raise AssertionError("dialog should have been skipped by the hook")

    execution = execute_tool_call(
        "FileEdit",
        {"path": "a.txt", "old_string": "old", "new_string": "new"},
        registry=tool_registry,
        permissions=permissions,
        context=context,
        dialog_runner=fail_if_called,
        hook_registry=hook_registry,
    )
    assert execution.decision.value == "allow"
    assert execution.result is not None and execution.result.ok


def test_executor_post_tool_use_messages_surface_in_metadata(
    workspace: Path, context: ToolContext
) -> None:
    (workspace / "a.txt").write_text("hi", encoding="utf-8")
    tool_registry = ToolRegistry()
    tool_registry.register(FileReadTool())
    permissions = PermissionManager(root=workspace)

    def runner(hook, payload):
        return HookProcessResult(returncode=0, stdout="", stderr="post-note")

    hook_registry = HookRegistry(runner=runner)
    hook_registry.add(HookDefinition(
        event=HookEvent.POST_TOOL_USE, matcher="", command="noop",
    ))

    execution = execute_tool_call(
        "FileRead",
        {"path": "a.txt"},
        registry=tool_registry,
        permissions=permissions,
        context=context,
        hook_registry=hook_registry,
    )
    assert execution.result is not None and execution.result.ok
    assert execution.result.metadata.get("hook_messages") == ["post-note"]
