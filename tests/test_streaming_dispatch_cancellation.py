"""Cancellation tests for the streaming tool dispatch path."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cli.llm.orchestrator import LLMOrchestrator
from cli.llm.provider_capabilities import ProviderCapabilities
from cli.llm.streaming import TextDelta, ToolUseDelta, ToolUseEnd, ToolUseStart
from cli.llm.types import TurnMessage
from cli.permissions import PermissionManager
from cli.tools.base import Tool, ToolContext, ToolResult
from cli.tools.registry import ToolRegistry
from cli.workbench_app.cancellation import CancellationToken


@dataclass
class _ToolState:
    """Shared timing and lifecycle signals for a fake cancellable tool."""

    started: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)
    cancel_observed: threading.Event = field(default_factory=threading.Event)
    cleanup: threading.Event = field(default_factory=threading.Event)


class _CancellableTool(Tool):
    """Tool that only stops when the shared cancellation token flips."""

    def __init__(self, name: str, state: _ToolState) -> None:
        self.name = name
        self.description = name
        self.input_schema = {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        }
        self.is_concurrency_safe = True
        self.read_only = True
        self._state = state

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        self._state.started.set()
        while not self._should_stop(context):
            time.sleep(0.01)
        if self._cancelled(context):
            self._state.cancel_observed.set()
        self._state.finished.set()
        return ToolResult.success(
            f"{self.name}:{tool_input['value']}",
            metadata={"tool": self.name},
        )

    def _should_stop(self, context: ToolContext) -> bool:
        return self._cancelled(context) or self._state.cleanup.is_set()

    def _cancelled(self, context: ToolContext) -> bool:
        cancel_check = context.cancel_check
        if cancel_check is None:
            return False
        cancelled = getattr(cancel_check, "cancelled", None)
        if isinstance(cancelled, bool):
            return cancelled
        if callable(cancel_check):
            return bool(cancel_check())
        return bool(cancelled)


@dataclass
class _CapabilitiesOnlyModel:
    """Model stub that only needs to advertise streaming capabilities."""

    capabilities: ProviderCapabilities


@dataclass
class _ScriptedStreamingModel:
    """Model stub that replays a single tool-use turn."""

    capabilities: ProviderCapabilities
    turn_events: list[Any]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def stream(
        self,
        *,
        system_prompt: str,
        messages: list[TurnMessage],
        tools: list[dict[str, Any]],
    ):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": [message.to_wire() for message in messages],
                "tools": tools,
            }
        )
        yield from self.turn_events


@dataclass
class _CacheHintCancellingModel:
    """Model that flips cancellation after a tool batch is staged for replay."""

    capabilities: ProviderCapabilities
    first_turn_events: list[Any]
    token: CancellationToken
    calls: list[dict[str, Any]] = field(default_factory=list)

    def cache_hint(self, _blocks: list[Any]) -> None:
        if len(self.calls) == 1:
            self.token.cancel()

    def stream(
        self,
        *,
        system_prompt: str,
        messages: list[TurnMessage],
        tools: list[dict[str, Any]],
    ):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": [message.to_wire() for message in messages],
                "tools": tools,
            }
        )
        if len(self.calls) > 1:  # pragma: no cover - regression sentinel
            raise AssertionError("follow-up model call should have been cancelled")
        yield from self.first_turn_events


class _ImmediateTool(Tool):
    """Simple read-only tool used to stage a completed tool batch."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.description = name
        self.input_schema = {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        }
        self.is_concurrency_safe = True
        self.read_only = True

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult.success(f"{self.name}:{tool_input['value']}")


def _caps(*, parallel_tool_calls: bool) -> ProviderCapabilities:
    return ProviderCapabilities(
        streaming=True,
        native_tool_use=True,
        parallel_tool_calls=parallel_tool_calls,
        thinking=False,
        prompt_cache=False,
        vision=False,
        json_mode=False,
        max_context_tokens=1_000,
        max_output_tokens=1_000,
    )


def _build_registry(*tools: Tool) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


def _build_orchestrator(
    workspace: Path,
    model: Any,
    *,
    registry: ToolRegistry,
) -> LLMOrchestrator:
    return LLMOrchestrator(
        model=model,
        tool_registry=registry,
        permissions=PermissionManager(root=workspace),
        workspace_root=workspace,
        echo=lambda _line: None,
    )


def _feed(dispatcher: Any, tool_use_id: str, tool_name: str, tool_input: dict[str, Any]) -> None:
    dispatcher.on_tool_use_start(ToolUseStart(id=tool_use_id, name=tool_name))
    dispatcher.on_tool_use_delta(ToolUseDelta(id=tool_use_id, input_json=""))
    dispatcher.on_tool_use_end(ToolUseEnd(id=tool_use_id, name=tool_name, input=tool_input))


def _clean_up(states: list[_ToolState]) -> None:
    for state in states:
        state.cleanup.set()


def _make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def test_cancel_all_signals_in_flight_work_and_exits_promptly(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    state = _ToolState()
    registry = _build_registry(_CancellableTool("alpha", state))
    orchestrator = _build_orchestrator(
        workspace,
        _CapabilitiesOnlyModel(capabilities=_caps(parallel_tool_calls=False)),
        registry=registry,
    )
    orchestrator.tool_cancellation = CancellationToken()
    dispatcher = orchestrator._build_streaming_tool_dispatcher()

    try:
        _feed(dispatcher, "alpha", "alpha", {"value": "one"})
        assert state.started.wait(timeout=1)

        started = time.perf_counter()
        dispatcher.cancel_all()

        assert state.finished.wait(timeout=0.25)
        assert state.cancel_observed.is_set()
        assert time.perf_counter() - started < 0.5
    finally:
        _clean_up([state])


def test_cancel_all_discards_partial_results_after_worker_finishes(
    tmp_path: Path,
) -> None:
    workspace = _make_workspace(tmp_path)
    state = _ToolState()
    registry = _build_registry(_CancellableTool("alpha", state))
    orchestrator = _build_orchestrator(
        workspace,
        _CapabilitiesOnlyModel(capabilities=_caps(parallel_tool_calls=False)),
        registry=registry,
    )
    orchestrator.tool_cancellation = CancellationToken()
    dispatcher = orchestrator._build_streaming_tool_dispatcher()

    try:
        _feed(dispatcher, "alpha", "alpha", {"value": "one"})
        assert state.started.wait(timeout=1)

        dispatcher.cancel_all()

        assert state.finished.wait(timeout=0.25)
        results = dispatcher.results_in_order()
        assert results == []
    finally:
        _clean_up([state])


def test_cancel_all_keeps_queued_work_from_starting(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    first = _ToolState()
    second = _ToolState()
    registry = _build_registry(
        _CancellableTool("first", first),
        _CancellableTool("second", second),
    )
    orchestrator = _build_orchestrator(
        workspace,
        _CapabilitiesOnlyModel(capabilities=_caps(parallel_tool_calls=False)),
        registry=registry,
    )
    orchestrator.tool_cancellation = CancellationToken()
    dispatcher = orchestrator._build_streaming_tool_dispatcher()

    try:
        _feed(dispatcher, "first", "first", {"value": "one"})
        _feed(dispatcher, "second", "second", {"value": "two"})
        assert first.started.wait(timeout=1)
        assert not second.started.is_set()

        dispatcher.cancel_all()

        assert first.finished.wait(timeout=0.25)
        assert not second.started.wait(timeout=0.05)
        assert not second.started.is_set()
    finally:
        _clean_up([first, second])


def test_cancelled_in_flight_tool_does_not_leak_tool_result_to_next_model_call(
    tmp_path: Path,
) -> None:
    workspace = _make_workspace(tmp_path)
    state = _ToolState()
    registry = _build_registry(_CancellableTool("alpha", state))
    model = _ScriptedStreamingModel(
        capabilities=_caps(parallel_tool_calls=True),
        turn_events=[
            ToolUseStart(id="tool-1", name="alpha"),
            ToolUseDelta(id="tool-1", input_json='{"value":"one"}'),
            ToolUseEnd(id="tool-1", name="alpha", input={"value": "one"}),
        ],
    )
    orchestrator = _build_orchestrator(workspace, model, registry=registry)
    token = CancellationToken()
    orchestrator.tool_cancellation = token

    result_box: dict[str, Any] = {}
    done = threading.Event()

    def _run_turn() -> None:
        try:
            result_box["result"] = orchestrator.run_turn("please cancel me")
        except Exception as exc:  # pragma: no cover - only used for test diagnostics
            result_box["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=_run_turn, daemon=True)

    try:
        thread.start()
        assert state.started.wait(timeout=1)
        token.cancel()
        assert done.wait(timeout=0.5)
        assert "error" not in result_box
        result = result_box["result"]
        assert len(model.calls) == 1
        assert result.stop_reason == "cancelled"
        assert result.tool_executions == []
        assert len(orchestrator.messages) == 1
        remaining = orchestrator.messages[0]
        assert remaining.role == "user"
        assert remaining.content == "please cancel me"
    finally:
        _clean_up([state])


def test_cancelled_turn_discards_partial_assistant_text(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    state = _ToolState()
    registry = _build_registry(_CancellableTool("alpha", state))
    model = _ScriptedStreamingModel(
        capabilities=_caps(parallel_tool_calls=True),
        turn_events=[
            TextDelta(text="working"),
            ToolUseStart(id="tool-1", name="alpha"),
            ToolUseDelta(id="tool-1", input_json='{"value":"one"}'),
            ToolUseEnd(id="tool-1", name="alpha", input={"value": "one"}),
        ],
    )
    token = CancellationToken()
    orchestrator = _build_orchestrator(workspace, model, registry=registry)
    orchestrator.tool_cancellation = token

    result_box: dict[str, Any] = {}
    done = threading.Event()

    def _run_turn() -> None:
        result_box["result"] = orchestrator.run_turn("please cancel me")
        done.set()

    thread = threading.Thread(target=_run_turn, daemon=True)
    try:
        thread.start()
        assert state.started.wait(timeout=1)
        token.cancel()
        assert done.wait(timeout=0.5)
        result = result_box["result"]
        assert result.stop_reason == "cancelled"
        assert result.assistant_text == ""
        assert result.tool_executions == []
        assert len(model.calls) == 1
        assert orchestrator.messages == [TurnMessage(role="user", content="please cancel me")]
    finally:
        _clean_up([state])


def test_cancel_between_tool_batch_and_followup_model_call_discards_results(
    tmp_path: Path,
) -> None:
    workspace = _make_workspace(tmp_path)
    token = CancellationToken()
    model = _CacheHintCancellingModel(
        capabilities=_caps(parallel_tool_calls=True),
        first_turn_events=[
            ToolUseStart(id="tool-1", name="alpha"),
            ToolUseDelta(id="tool-1", input_json='{"value":"one"}'),
            ToolUseEnd(id="tool-1", name="alpha", input={"value": "one"}),
        ],
        token=token,
    )
    registry = _build_registry(_ImmediateTool("alpha"))
    orchestrator = _build_orchestrator(workspace, model, registry=registry)
    orchestrator.tool_cancellation = token

    result = orchestrator.run_turn("please cancel me")

    assert result.stop_reason == "cancelled"
    assert result.assistant_text == ""
    assert result.tool_executions == []
    assert len(model.calls) == 1
    assert orchestrator.messages == [TurnMessage(role="user", content="please cancel me")]
