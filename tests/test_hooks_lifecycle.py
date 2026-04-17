from __future__ import annotations

from cli.hooks import HookEvent, HookRegistry, HookVerdict, load_hook_registry
from cli.hooks.registry import HookProcessResult
from cli.settings import Settings


def test_lifecycle_event_names_are_supported() -> None:
    assert HookEvent.BEFORE_QUERY.value == "beforeQuery"
    assert HookEvent.AFTER_QUERY.value == "afterQuery"
    assert HookEvent.PRE_TOOL_USE.value == "PreToolUse"
    assert HookEvent.POST_TOOL_USE.value == "PostToolUse"
    assert HookEvent.ON_PERMISSION_REQUEST.value == "OnPermissionRequest"
    assert HookEvent.SUBAGENT_STOP.value == "SubagentStop"
    assert HookEvent.SESSION_END.value == "SessionEnd"
    assert HookEvent.STOP.value == "Stop"


def test_settings_defined_hook_fires_for_matching_tool() -> None:
    calls: list[tuple[str, dict]] = []

    def runner(hook, payload):
        calls.append((hook.command, payload))
        return HookProcessResult(returncode=0, stdout="", stderr="ok")

    settings = Settings.model_validate(
        {
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo pre"}]}
                ]
            }
        }
    )
    registry = HookRegistry.load_from_settings(settings, runner=runner)

    outcome = registry.fire(
        HookEvent.PRE_TOOL_USE,
        tool_name="Bash",
        payload={"tool_name": "Bash", "tool_input": {"command": "pwd"}},
    )

    assert outcome.verdict is HookVerdict.INFORM
    assert calls == [("echo pre", {"tool_name": "Bash", "tool_input": {"command": "pwd"}})]


def test_non_matching_hook_does_not_fire() -> None:
    settings = Settings.model_validate(
        {
            "hooks": {
                "PostToolUse": [
                    {"matcher": "FileEdit", "hooks": [{"command": "echo post"}]}
                ]
            }
        }
    )
    registry = HookRegistry.load_from_settings(
        settings,
        runner=lambda *_: (_ for _ in ()).throw(AssertionError("should not run")),
    )

    outcome = registry.fire(HookEvent.POST_TOOL_USE, tool_name="FileRead", payload={})

    assert outcome.fired == 0
    assert outcome.verdict is HookVerdict.ALLOW


def test_timeout_returns_timeout_verdict_without_crashing() -> None:
    settings = Settings.model_validate(
        {
            "hooks": {
                "timeout_seconds": 5,
                "beforeQuery": [{"hooks": [{"command": "slow"}]}],
            }
        }
    )
    registry = HookRegistry.load_from_settings(
        settings,
        runner=lambda hook, payload: HookProcessResult(
            returncode=124,
            stdout="",
            stderr="",
            timed_out=True,
        ),
    )

    outcome = registry.fire(HookEvent.BEFORE_QUERY, payload={"prompt": "hi"})

    assert outcome.verdict is HookVerdict.TIMEOUT
    assert outcome.fired == 1
    assert "timed out after 5s" in outcome.messages[0]


def test_per_hook_timeout_overrides_settings_default() -> None:
    settings = Settings.model_validate(
        {
            "hooks": {
                "timeout_seconds": 5,
                "beforeQuery": [{"hooks": [{"command": "slow", "timeout": 9}]}],
            }
        }
    )
    registry = HookRegistry.load_from_settings(
        settings,
        runner=lambda hook, payload: HookProcessResult(
            returncode=124,
            stdout="",
            stderr="",
            timed_out=True,
        ),
    )

    outcome = registry.fire(HookEvent.BEFORE_QUERY, payload={"prompt": "hi"})

    assert outcome.verdict is HookVerdict.TIMEOUT
    assert "timed out after 9s" in outcome.messages[0]


def test_json_ask_verdict_is_recorded() -> None:
    settings = Settings.model_validate(
        {
            "hooks": {
                "PreToolUse": [{"hooks": [{"command": "ask"}]}],
            }
        }
    )
    registry = HookRegistry.load_from_settings(
        settings,
        runner=lambda hook, payload: HookProcessResult(
            returncode=0,
            stdout='{"decision":"ask","reason":"needs review"}',
            stderr="",
        ),
    )

    outcome = registry.fire(HookEvent.PRE_TOOL_USE, tool_name="Bash", payload={})

    assert outcome.verdict is HookVerdict.ASK
    assert outcome.messages == ["needs review"]


def test_json_deny_verdict_is_first_deny_for_gating_event() -> None:
    calls: list[str] = []

    def runner(hook, payload):
        calls.append(hook.command)
        if hook.command == "deny":
            return HookProcessResult(
                returncode=0,
                stdout='{"decision":"deny","reason":"blocked"}',
                stderr="",
            )
        return HookProcessResult(returncode=0, stdout="", stderr="")

    settings = Settings.model_validate(
        {
            "hooks": {
                "PreToolUse": [
                    {"hooks": [{"command": "allow"}, {"command": "deny"}, {"command": "skip"}]}
                ],
            }
        }
    )
    registry = HookRegistry.load_from_settings(settings, runner=runner)

    outcome = registry.fire(HookEvent.PRE_TOOL_USE, tool_name="Bash", payload={})

    assert outcome.verdict is HookVerdict.DENY
    assert outcome.messages == ["blocked"]
    assert calls == ["allow", "deny"]


def test_claude_style_hook_specific_output_ask_is_recorded() -> None:
    settings = Settings.model_validate(
        {
            "hooks": {
                "PreToolUse": [{"hooks": [{"command": "ask"}]}],
            }
        }
    )
    registry = HookRegistry.load_from_settings(
        settings,
        runner=lambda hook, payload: HookProcessResult(
            returncode=0,
            stdout=(
                '{"hookSpecificOutput":{"hookEventName":"PreToolUse",'
                '"permissionDecision":"ask",'
                '"permissionDecisionReason":"needs review"}}'
            ),
            stderr="",
        ),
    )

    outcome = registry.fire(HookEvent.PRE_TOOL_USE, tool_name="Bash", payload={})

    assert outcome.verdict is HookVerdict.ASK
    assert outcome.messages == ["needs review"]


def test_post_tool_use_json_updated_output_is_captured_in_metadata() -> None:
    settings = Settings.model_validate(
        {
            "hooks": {
                "PostToolUse": [{"hooks": [{"command": "rewrite"}]}],
            }
        }
    )
    registry = HookRegistry.load_from_settings(
        settings,
        runner=lambda hook, payload: HookProcessResult(
            returncode=0,
            stdout=(
                '{"hookSpecificOutput":{"hookEventName":"PostToolUse",'
                '"updatedMCPToolOutput":{"content":"patched"}}}'
            ),
            stderr="",
        ),
    )

    outcome = registry.fire(HookEvent.POST_TOOL_USE, tool_name="Bash", payload={})

    assert outcome.verdict is HookVerdict.ALLOW
    assert outcome.metadata["updated_mcp_tool_output"] == {"content": "patched"}


def test_legacy_before_tool_name_normalizes_to_pre_tool_use() -> None:
    settings = Settings.model_validate(
        {
            "hooks": {
                "beforeTool": [{"hooks": [{"command": "legacy"}]}],
            }
        }
    )
    registry = HookRegistry.load_from_settings(settings)

    hooks = registry.hooks_for(HookEvent.PRE_TOOL_USE, tool_name="Anything")

    assert [hook.command for hook in hooks] == ["legacy"]


def test_legacy_after_tool_name_normalizes_to_post_tool_use() -> None:
    settings = Settings.model_validate(
        {
            "hooks": {
                "afterTool": [{"hooks": [{"command": "legacy"}]}],
            }
        }
    )
    registry = HookRegistry.load_from_settings(settings)

    hooks = registry.hooks_for(HookEvent.POST_TOOL_USE, tool_name="Anything")

    assert [hook.command for hook in hooks] == ["legacy"]


def test_load_hook_registry_compatibility_wrapper_accepts_raw_mapping() -> None:
    registry = load_hook_registry(
        {
            "hooks": {
                "beforeTool": [{"hooks": [{"command": "legacy"}]}],
            }
        }
    )

    hooks = registry.hooks_for(HookEvent.PRE_TOOL_USE, tool_name="Anything")

    assert [hook.command for hook in hooks] == ["legacy"]
