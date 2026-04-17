from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from cli.hooks import HookDefinition, HookEvent, HookOutcome, HookRegistry, HookVerdict
from cli.hooks.registry import HookProcessResult
from cli.llm.orchestrator import LLMOrchestrator
from cli.llm.streaming import MessageStop, TextDelta
from cli.permissions import PermissionManager
from cli.sessions import SessionStore
from cli.tools.base import PermissionDecision, Tool, ToolContext, ToolResult
from cli.tools.executor import execute_tool_call
from cli.tools.registry import ToolRegistry


class RecordingHookRegistry:
    def __init__(self, outcomes: dict[HookEvent, HookOutcome] | None = None) -> None:
        self.outcomes = outcomes or {}
        self.calls: list[tuple[HookEvent, str, dict[str, Any]]] = []

    def fire(self, event: HookEvent, *, tool_name: str = "", payload=None):
        payload_dict = dict(payload or {})
        self.calls.append((event, tool_name, payload_dict))
        return self.outcomes.get(event, HookOutcome())

    def prompt_fragments_for(self, event: HookEvent, *, tool_name: str = "") -> list[str]:
        return []


class RecordingModel:
    def __init__(self, events: list[list[Any]]) -> None:
        self.events = list(events)
        self.calls = 0
        self.messages_seen: list[list[Any]] = []

    def stream(self, *, system_prompt, messages, tools) -> Iterator[Any]:
        self.calls += 1
        self.messages_seen.append(list(messages))
        for event in self.events.pop(0):
            yield event


class FireOnlyHookRegistry:
    def __init__(self, outcomes: dict[HookEvent, HookOutcome] | None = None) -> None:
        self.outcomes = outcomes or {}
        self.calls: list[tuple[HookEvent, str, dict[str, Any]]] = []

    def fire(self, event: HookEvent, *, tool_name: str = "", payload=None):
        payload_dict = dict(payload or {})
        self.calls.append((event, tool_name, payload_dict))
        return self.outcomes.get(event, HookOutcome())


class EchoTool(Tool):
    name = "Echo"
    description = "Echo input."
    input_schema = {"type": "object", "properties": {"value": {"type": "string"}}}
    read_only = True

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult.success(tool_input["value"], metadata={})


def _orchestrator(
    tmp_path: Path,
    model: RecordingModel,
    hooks: Any,
) -> LLMOrchestrator:
    registry = ToolRegistry()
    registry.register(EchoTool())
    return LLMOrchestrator(
        model=model,
        tool_registry=registry,
        permissions=PermissionManager(root=tmp_path),
        workspace_root=tmp_path,
        hook_registry=hooks,
        system_prompt="system",
        echo=lambda _: None,
    )


def _orchestrator_with_session(
    tmp_path: Path,
    model: RecordingModel,
    hooks: Any,
) -> LLMOrchestrator:
    registry = ToolRegistry()
    registry.register(EchoTool())
    session_store = SessionStore(workspace_dir=tmp_path)
    session = session_store.create(title="hook denial regression")
    return LLMOrchestrator(
        model=model,
        tool_registry=registry,
        permissions=PermissionManager(root=tmp_path),
        workspace_root=tmp_path,
        session=session,
        session_store=session_store,
        hook_registry=hooks,
        system_prompt="system",
        echo=lambda _: None,
    )


def test_turn_hooks_fire_in_order(tmp_path: Path) -> None:
    model = RecordingModel([[TextDelta(text="hi"), MessageStop(stop_reason="end_turn")]])
    hooks = RecordingHookRegistry()
    result = _orchestrator(tmp_path, model, hooks).run_turn("hello")

    assert result.stop_reason == "end_turn"
    assert [call[0] for call in hooks.calls] == [
        HookEvent.BEFORE_QUERY,
        HookEvent.AFTER_QUERY,
        HookEvent.SESSION_END,
    ]
    assert hooks.calls[0][2]["prompt"] == "hello"
    assert hooks.calls[1][2]["stop_reason"] == "end_turn"


def test_before_query_deny_aborts_before_model_call(tmp_path: Path) -> None:
    deny = HookOutcome(verdict=HookVerdict.DENY, messages=["blocked"])
    model = RecordingModel([[TextDelta(text="should not run")]])
    hooks = RecordingHookRegistry({HookEvent.BEFORE_QUERY: deny})

    result = _orchestrator(tmp_path, model, hooks).run_turn("hello")

    assert model.calls == 0
    assert result.stop_reason == "hook_deny"
    assert result.tool_executions == []
    assert "blocked" in result.assistant_text
    assert result.metadata["hook_messages"] == ["blocked"]


def test_before_query_deny_does_not_leak_prompt_into_next_turn_or_session(
    tmp_path: Path,
) -> None:
    deny = HookOutcome(verdict=HookVerdict.DENY, messages=["blocked"])
    model = RecordingModel([[TextDelta(text="ok"), MessageStop(stop_reason="end_turn")]])
    hooks = RecordingHookRegistry({HookEvent.BEFORE_QUERY: deny})
    orchestrator = _orchestrator_with_session(tmp_path, model, hooks)

    denied = orchestrator.run_turn("blocked prompt")
    hooks.outcomes = {}
    allowed = orchestrator.run_turn("allowed prompt")

    assert denied.stop_reason == "hook_deny"
    assert allowed.stop_reason == "end_turn"
    assert model.calls == 1
    user_messages = [
        message.content
        for message in model.messages_seen[0]
        if message.role == "user" and isinstance(message.content, str)
    ]
    assert user_messages == ["allowed prompt"]
    assert all("blocked prompt" not in str(message.content) for message in model.messages_seen[0])
    assert orchestrator.session is not None
    session_user_messages = [
        entry.content for entry in orchestrator.session.transcript if entry.role == "user"
    ]
    assert session_user_messages == ["allowed prompt"]


def test_fire_only_hook_registry_without_prompt_fragments_allows_normal_turn(
    tmp_path: Path,
) -> None:
    model = RecordingModel([[TextDelta(text="hi"), MessageStop(stop_reason="end_turn")]])
    hooks = FireOnlyHookRegistry()

    try:
        result = _orchestrator(tmp_path, model, hooks).run_turn("hello")
    except AttributeError as exc:
        raise AssertionError(
            "fire-only hook registries should not need prompt_fragments_for"
        ) from exc

    assert result.stop_reason == "end_turn"
    assert model.calls == 1


def test_session_end_replaces_stop_and_legacy_stop_still_fires(tmp_path: Path) -> None:
    calls: list[tuple[HookEvent, dict[str, Any]]] = []

    def runner(hook: HookDefinition, payload: dict[str, Any]) -> HookProcessResult:
        calls.append((hook.event, payload))
        return HookProcessResult(returncode=0, stdout="", stderr="")

    registry = HookRegistry(runner=runner)
    registry.add(HookDefinition(event=HookEvent.SESSION_END, matcher="", command="session"))
    registry.add(HookDefinition(event=HookEvent.STOP, matcher="", command="stop"))
    model = RecordingModel([[TextDelta(text="hi"), MessageStop(stop_reason="end_turn")]])

    result = _orchestrator(tmp_path, model, registry).run_turn("hello")

    assert result.stop_reason == "end_turn"
    assert [call[0] for call in calls] == [HookEvent.SESSION_END, HookEvent.STOP]
    assert calls[0][1]["stop_reason"] == "end_turn"


def test_tool_hooks_wrap_dispatch_and_payloads_use_claude_keys(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())
    hooks = RecordingHookRegistry()

    execution = execute_tool_call(
        "Echo",
        {"value": "ok"},
        registry=registry,
        permissions=PermissionManager(root=tmp_path),
        context=ToolContext(workspace_root=tmp_path),
        hook_registry=hooks,
    )

    assert execution.decision is PermissionDecision.ALLOW
    assert [call[0] for call in hooks.calls] == [
        HookEvent.PRE_TOOL_USE,
        HookEvent.POST_TOOL_USE,
    ]
    assert hooks.calls[0][2] == {"tool_name": "Echo", "tool_input": {"value": "ok"}}
    assert hooks.calls[1][2]["tool_response"]["content"] == "ok"


def test_pre_tool_deny_returns_first_class_tool_error(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())
    hooks = RecordingHookRegistry(
        {
            HookEvent.PRE_TOOL_USE: HookOutcome(
                verdict=HookVerdict.DENY,
                messages=["policy"],
            )
        }
    )

    execution = execute_tool_call(
        "Echo",
        {"value": "ok"},
        registry=registry,
        permissions=PermissionManager(root=tmp_path),
        context=ToolContext(workspace_root=tmp_path),
        hook_registry=hooks,
    )

    assert execution.decision is PermissionDecision.DENY
    assert execution.result is not None
    assert execution.result.content == "denied by hook: policy"


def test_pre_tool_ask_forces_permission_prompt_even_when_policy_allows(
    tmp_path: Path,
) -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())
    hooks = RecordingHookRegistry(
        {
            HookEvent.PRE_TOOL_USE: HookOutcome(
                verdict=HookVerdict.ASK,
                messages=["review"],
            )
        }
    )
    prompts: list[str] = []

    class DialogOutcome:
        allow = True
        persist_rule = None
        persist_scope = None

    def dialog(tool, tool_input, *, include_persist_option=True):
        prompts.append(tool.name)
        return DialogOutcome()

    execution = execute_tool_call(
        "Echo",
        {"value": "ok"},
        registry=registry,
        permissions=PermissionManager(root=tmp_path),
        context=ToolContext(workspace_root=tmp_path),
        dialog_runner=dialog,
        hook_registry=hooks,
    )

    assert prompts == ["Echo"]
    assert execution.decision is PermissionDecision.ALLOW


def test_on_permission_request_ask_falls_through_to_permission_prompt(
    tmp_path: Path,
) -> None:
    class WriteTool(Tool):
        name = "Write"
        description = "Write input."
        input_schema = {"type": "object", "properties": {}}
        read_only = False

        def permission_action(self, tool_input: dict[str, Any]) -> str:
            return "tool:FileWrite:note.txt"

        def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
            return ToolResult.success("wrote", metadata={})

    registry = ToolRegistry()
    registry.register(WriteTool())
    hooks = RecordingHookRegistry(
        {
            HookEvent.ON_PERMISSION_REQUEST: HookOutcome(
                verdict=HookVerdict.ASK,
                messages=["ask user"],
                fired=1,
            )
        }
    )
    prompts: list[str] = []

    class DialogOutcome:
        allow = True
        persist_rule = None
        persist_scope = None

    def dialog(tool, tool_input, *, include_persist_option=True):
        prompts.append(tool.name)
        return DialogOutcome()

    execution = execute_tool_call(
        "Write",
        {},
        registry=registry,
        permissions=PermissionManager(root=tmp_path),
        context=ToolContext(workspace_root=tmp_path),
        dialog_runner=dialog,
        hook_registry=hooks,
    )

    assert prompts == ["Write"]
    assert execution.decision is PermissionDecision.ALLOW


def test_post_tool_hook_can_mutate_tool_result(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())
    hooks = RecordingHookRegistry(
        {
            HookEvent.POST_TOOL_USE: HookOutcome(
                verdict=HookVerdict.INFORM,
                messages=["rewrote"],
                metadata={"updated_mcp_tool_output": "mutated"},
            )
        }
    )

    execution = execute_tool_call(
        "Echo",
        {"value": "original"},
        registry=registry,
        permissions=PermissionManager(root=tmp_path),
        context=ToolContext(workspace_root=tmp_path),
        hook_registry=hooks,
    )

    assert execution.result is not None
    assert execution.result.ok is True
    assert execution.result.content == "mutated"
    assert execution.result.metadata["hook_messages"] == ["rewrote"]
