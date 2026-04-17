"""Streaming-dispatch integration tests for the turn orchestrator."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import pytest

from cli.hooks import HookDefinition, HookEvent, HookRegistry, HookType
from cli.hooks.registry import HookProcessResult
from cli.llm.orchestrator import LLMOrchestrator
from cli.llm.provider_capabilities import ProviderCapabilities
from cli.llm.streaming import (
    MessageStop,
    TextDelta,
    ToolUseDelta,
    ToolUseEnd,
    ToolUseStart,
)
from cli.llm.types import TurnMessage
from cli.permissions import PermissionManager
from cli.tools.base import Tool, ToolContext, ToolResult
from cli.tools.file_edit import FileEditTool
from cli.tools.file_read import FileReadTool
from cli.tools.registry import ToolRegistry


@dataclass(frozen=True)
class _Pause:
    seconds: float


class _ScriptedStreamingModel:
    """Fake model that replays scripted streaming turns."""

    def __init__(self, turns: list[list[Any]], *, capabilities: ProviderCapabilities) -> None:
        self._turns = [list(turn) for turn in turns]
        self.capabilities = capabilities
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
                "messages": [message.to_wire() for message in messages],
                "tools": tools,
            }
        )
        events = self._turns.pop(0)
        for event in events:
            if isinstance(event, _Pause):
                time.sleep(event.seconds)
                continue
            yield event


@dataclass
class _TimingState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    started_at: dict[str, float] = field(default_factory=dict)
    finished_at: dict[str, float] = field(default_factory=dict)
    start_order: list[str] = field(default_factory=list)
    finish_order: list[str] = field(default_factory=list)


class _TimedTool(Tool):
    """Tool that records when it starts and finishes, then sleeps."""

    def __init__(
        self,
        name: str,
        *,
        delay_seconds: float,
        state: _TimingState,
        read_only: bool = True,
        is_concurrency_safe: bool = True,
    ) -> None:
        self.name = name
        self.description = f"Timed {name}."
        self.input_schema = {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        }
        self.read_only = read_only
        self.is_concurrency_safe = is_concurrency_safe
        self._delay_seconds = delay_seconds
        self._state = state

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        started = time.perf_counter()
        with self._state.lock:
            self._state.started_at[self.name] = started
            self._state.start_order.append(self.name)
        time.sleep(self._delay_seconds)
        finished = time.perf_counter()
        with self._state.lock:
            self._state.finished_at[self.name] = finished
            self._state.finish_order.append(self.name)
        return ToolResult.success(
            f"{self.name}:{tool_input['value']}",
            metadata={"tool": self.name},
        )


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


def _tool_use(tool_use_id: str, name: str, input_data: dict[str, Any]) -> list[Any]:
    return [
        ToolUseStart(id=tool_use_id, name=name),
        ToolUseDelta(id=tool_use_id, input_json=json.dumps(input_data)),
        ToolUseEnd(id=tool_use_id, name=name, input=input_data),
    ]


def _write_settings(workspace: Path, payload: dict[str, Any]) -> None:
    agentlab_dir = workspace / ".agentlab"
    agentlab_dir.mkdir(parents=True, exist_ok=True)
    (agentlab_dir / "settings.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def _build_orchestrator(
    workspace: Path,
    model: _ScriptedStreamingModel,
    *,
    tool_registry: ToolRegistry | None = None,
    hook_registry: HookRegistry | None = None,
) -> LLMOrchestrator:
    registry = tool_registry or ToolRegistry()
    return LLMOrchestrator(
        model=model,
        tool_registry=registry,
        permissions=PermissionManager(root=workspace),
        workspace_root=workspace,
        hook_registry=hook_registry,
        system_prompt="system",
        echo=lambda _: None,
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".agentlab").mkdir()
    return workspace


def test_streaming_dispatch_overlapping_safe_tools_beats_sequential_baseline(
    workspace: Path,
) -> None:
    state = _TimingState()
    registry = ToolRegistry()
    registry.register(
        _TimedTool("ToolA", delay_seconds=0.18, state=state, read_only=True)
    )
    registry.register(
        _TimedTool("ToolB", delay_seconds=0.18, state=state, read_only=True)
    )
    model = _ScriptedStreamingModel(
        [
            [
                *_tool_use("t1", "ToolA", {"value": "alpha"}),
                _Pause(0.05),
                *_tool_use("t2", "ToolB", {"value": "bravo"}),
                _Pause(0.05),
                MessageStop(stop_reason="tool_use"),
            ],
            [TextDelta(text="done"), MessageStop(stop_reason="end_turn")],
        ],
        capabilities=_caps(parallel_tool_calls=True),
    )

    orchestrator = _build_orchestrator(workspace, model, tool_registry=registry)

    started = time.perf_counter()
    result = orchestrator.run_turn("run both")
    elapsed = time.perf_counter() - started

    assert result.stop_reason == "end_turn"
    assert result.assistant_text.strip() == "done"
    assert state.start_order == ["ToolA", "ToolB"]
    assert state.finish_order[0] in {"ToolA", "ToolB"}
    assert state.started_at["ToolB"] - state.started_at["ToolA"] < 0.12

    sequential_baseline = 0.05 + 0.18 + 0.18 + 0.05
    assert elapsed < sequential_baseline - 0.08


def test_streaming_dispatch_returns_results_in_declared_order(
    workspace: Path,
) -> None:
    state = _TimingState()
    registry = ToolRegistry()
    registry.register(
        _TimedTool("First", delay_seconds=0.20, state=state, read_only=True)
    )
    registry.register(
        _TimedTool("Second", delay_seconds=0.05, state=state, read_only=True)
    )
    model = _ScriptedStreamingModel(
        [
            [
                *_tool_use("u1", "First", {"value": "one"}),
                *_tool_use("u2", "Second", {"value": "two"}),
                MessageStop(stop_reason="tool_use"),
            ],
            [TextDelta(text="ok"), MessageStop(stop_reason="end_turn")],
        ],
        capabilities=_caps(parallel_tool_calls=True),
    )

    orchestrator = _build_orchestrator(workspace, model, tool_registry=registry)
    orchestrator.run_turn("order")

    second_call_messages = model.calls[1]["messages"]
    last_user_content = second_call_messages[-1]["content"]
    assert [block["tool_use_id"] for block in last_user_content if block["type"] == "tool_result"] == [
        "u1",
        "u2",
    ]


def test_streaming_dispatch_still_blocks_write_tools_in_plan_mode(
    workspace: Path,
) -> None:
    _write_settings(workspace, {"permissions": {"mode": "plan"}})
    (workspace / "note.txt").write_text("hello\n", encoding="utf-8")
    tool_registry = ToolRegistry()
    tool_registry.register(FileEditTool())
    model = _ScriptedStreamingModel(
        [
            [
                *_tool_use(
                    "edit1",
                    "FileEdit",
                    {"path": "note.txt", "old_string": "hello", "new_string": "world"},
                ),
                MessageStop(stop_reason="tool_use"),
            ],
            [MessageStop(stop_reason="end_turn")],
        ],
        capabilities=_caps(parallel_tool_calls=True),
    )

    orchestrator = _build_orchestrator(workspace, model, tool_registry=tool_registry)
    result = orchestrator.run_turn("edit it")

    assert len(result.tool_executions) == 1
    assert result.tool_executions[0].tool_name == "FileEdit"
    assert result.tool_executions[0].decision.value == "deny"
    assert result.tool_executions[0].denial_reason == "policy_deny"


def test_streaming_dispatch_attaches_post_tool_prompt_fragments(
    workspace: Path,
) -> None:
    (workspace / "note.txt").write_text("hello\n", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(FileReadTool())

    hooks = HookRegistry()
    hooks.add(
        HookDefinition(
            event=HookEvent.POST_TOOL_USE,
            matcher="FileRead",
            hook_type=HookType.PROMPT,
            prompt="Summarise the file in one sentence.",
            id="summary",
        )
    )

    model = _ScriptedStreamingModel(
        [
            [
                *_tool_use("read1", "FileRead", {"path": "note.txt"}),
                MessageStop(stop_reason="tool_use"),
            ],
            [TextDelta(text="done"), MessageStop(stop_reason="end_turn")],
        ],
        capabilities=_caps(parallel_tool_calls=True),
    )

    orchestrator = _build_orchestrator(
        workspace,
        model,
        tool_registry=registry,
        hook_registry=hooks,
    )
    orchestrator.run_turn("read it")

    second_call_messages = model.calls[1]["messages"]
    last_user_content = second_call_messages[-1]["content"]
    assert last_user_content[0]["type"] == "tool_result"
    assert last_user_content[-1]["type"] == "text"
    assert "Summarise the file in one sentence." in last_user_content[-1]["text"]


def test_streaming_dispatch_handles_tool_use_closed_only_at_message_stop(
    workspace: Path,
) -> None:
    (workspace / "note.txt").write_text("hello\n", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(FileReadTool())
    model = _ScriptedStreamingModel(
        [
            [
                ToolUseStart(id="read1", name="FileRead"),
                ToolUseDelta(id="read1", input_json='{"path":"note.txt"}'),
                MessageStop(stop_reason="tool_use"),
            ],
            [TextDelta(text="done"), MessageStop(stop_reason="end_turn")],
        ],
        capabilities=_caps(parallel_tool_calls=True),
    )

    orchestrator = _build_orchestrator(workspace, model, tool_registry=registry)
    result = orchestrator.run_turn("read it")

    assert len(result.tool_executions) == 1
    assert result.tool_executions[0].tool_name == "FileRead"
    tool_result_block = model.calls[1]["messages"][-1]["content"][0]
    assert tool_result_block["tool_use_id"] == "read1"
    assert "hello" in tool_result_block["content"]


def test_streaming_dispatch_serializes_hook_prompted_tool(
    workspace: Path,
) -> None:
    state = _TimingState()
    registry = ToolRegistry()
    registry.register(
        _TimedTool("PromptTool", delay_seconds=0.18, state=state, read_only=True)
    )
    registry.register(
        _TimedTool("LaterTool", delay_seconds=0.05, state=state, read_only=True)
    )

    def runner(hook, payload):
        if hook.event is HookEvent.PRE_TOOL_USE and payload.get("tool_name") == "PromptTool":
            return HookProcessResult(
                returncode=0,
                stdout=json.dumps({"decision": "ask", "reason": "review"}),
                stderr="",
            )
        return HookProcessResult(returncode=0, stdout="", stderr="")

    hooks = HookRegistry(runner=runner)
    hooks.add(
        HookDefinition(
            event=HookEvent.PRE_TOOL_USE,
            matcher="PromptTool",
            hook_type=HookType.COMMAND,
            command="prompt-check",
        )
    )

    model = _ScriptedStreamingModel(
        [
            [
                *_tool_use("prompt1", "PromptTool", {"value": "alpha"}),
                _Pause(0.02),
                *_tool_use("later2", "LaterTool", {"value": "bravo"}),
                MessageStop(stop_reason="tool_use"),
            ],
            [TextDelta(text="done"), MessageStop(stop_reason="end_turn")],
        ],
        capabilities=_caps(parallel_tool_calls=True),
    )

    orchestrator = _build_orchestrator(
        workspace,
        model,
        tool_registry=registry,
        hook_registry=hooks,
    )
    orchestrator.dialog_runner = lambda *_a, **_k: type(
        "DialogOutcome",
        (),
        {"allow": True, "persist_rule": None, "persist_scope": None},
    )()

    result = orchestrator.run_turn("run both")

    assert result.stop_reason == "end_turn"
    assert state.start_order == ["PromptTool", "LaterTool"]
    assert state.started_at["LaterTool"] >= state.finished_at["PromptTool"]


def test_streaming_dispatch_preserves_single_tool_semantics(
    workspace: Path,
) -> None:
    state = _TimingState()
    registry = ToolRegistry()
    registry.register(
        _TimedTool("OnlyTool", delay_seconds=0.05, state=state, read_only=True)
    )
    model = _ScriptedStreamingModel(
        [
            [
                *_tool_use("solo", "OnlyTool", {"value": "value"}),
                MessageStop(stop_reason="tool_use"),
            ],
            [TextDelta(text="final answer"), MessageStop(stop_reason="end_turn")],
        ],
        capabilities=_caps(parallel_tool_calls=True),
    )

    orchestrator = _build_orchestrator(workspace, model, tool_registry=registry)
    result = orchestrator.run_turn("single")

    assert result.assistant_text.strip() == "final answer"
    assert len(result.tool_executions) == 1
    assert result.tool_executions[0].tool_name == "OnlyTool"
    assert result.tool_executions[0].decision.value == "allow"
    assert model.calls[0]["messages"][0]["content"] == "single"
