"""Tests for Phase-A model adapters: streaming, retries, caching, providers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import pytest

from cli.llm.caching import CacheInput, MIN_CACHEABLE_CHARS, compute_cache_blocks
from cli.llm.providers.anthropic_client import AnthropicClient
from cli.llm.providers.factory import (
    MODEL_PROVIDERS,
    ProviderFactoryError,
    create_model_client,
    resolve_provider,
)
from cli.llm.providers.openai_client import OpenAIClient
from cli.llm.retries import RetryPolicy, retry_call
from cli.llm.streaming import (
    MessageStop,
    TextDelta,
    ThinkingDelta,
    ToolUseDelta,
    ToolUseEnd,
    ToolUseStart,
    UsageDelta,
    collect_stream,
    events_from_model_response,
)
from cli.llm.types import (
    AssistantTextBlock,
    AssistantToolUseBlock,
    ModelResponse,
    TurnMessage,
)


# ---------------------------------------------------------------------------
# Streaming — collect_stream rebuilds ModelResponse from events
# ---------------------------------------------------------------------------


def test_collect_stream_assembles_text_blocks() -> None:
    events = [
        TextDelta(text="Hello, "),
        TextDelta(text="world!"),
        MessageStop(stop_reason="end_turn"),
    ]
    response = collect_stream(events)
    assert len(response.blocks) == 1
    assert isinstance(response.blocks[0], AssistantTextBlock)
    assert response.blocks[0].text == "Hello, world!"
    assert response.stop_reason == "end_turn"


def test_collect_stream_interleaves_text_and_tool_use() -> None:
    events = [
        TextDelta(text="Reading the file.\n"),
        ToolUseStart(id="toolu_1", name="FileRead"),
        ToolUseDelta(id="toolu_1", input_json='{"path":'),
        ToolUseDelta(id="toolu_1", input_json='"a.txt"}'),
        ToolUseEnd(id="toolu_1", name="FileRead", input={"path": "a.txt"}),
        MessageStop(stop_reason="tool_use"),
    ]
    response = collect_stream(events)
    assert len(response.blocks) == 2
    assert isinstance(response.blocks[0], AssistantTextBlock)
    assert response.blocks[0].text == "Reading the file.\n"
    assert isinstance(response.blocks[1], AssistantToolUseBlock)
    assert response.blocks[1].id == "toolu_1"
    assert response.blocks[1].input == {"path": "a.txt"}
    assert response.stop_reason == "tool_use"


def test_collect_stream_parses_json_from_deltas_when_end_empty() -> None:
    events = [
        ToolUseStart(id="toolu_x", name="Grep"),
        ToolUseDelta(id="toolu_x", input_json='{"pattern": '),
        ToolUseDelta(id="toolu_x", input_json='"foo"}'),
        ToolUseEnd(id="toolu_x", name="Grep", input={}),
        MessageStop(stop_reason="end_turn"),
    ]
    response = collect_stream(events)
    tool_use = response.blocks[0]
    assert isinstance(tool_use, AssistantToolUseBlock)
    assert tool_use.input == {"pattern": "foo"}


def test_collect_stream_aggregates_usage() -> None:
    events = [
        UsageDelta(usage={"input_tokens": 10}),
        UsageDelta(usage={"output_tokens": 5}),
        UsageDelta(usage={"input_tokens": 2}),
        MessageStop(stop_reason="end_turn"),
    ]
    response = collect_stream(events)
    assert response.usage == {"input_tokens": 12, "output_tokens": 5}


def test_collect_stream_drops_thinking_deltas_from_text() -> None:
    events = [
        ThinkingDelta(text="Let me think…"),
        TextDelta(text="Here is the answer."),
        MessageStop(stop_reason="end_turn"),
    ]
    response = collect_stream(events)
    # Thinking never folds into assistant text — only the visible text shows up.
    assert response.blocks[0].text == "Here is the answer."


def test_collect_stream_handles_malformed_json_gracefully() -> None:
    events = [
        ToolUseStart(id="toolu_y", name="Bash"),
        ToolUseDelta(id="toolu_y", input_json="{not valid"),
        ToolUseEnd(id="toolu_y", name="Bash", input={}),
        MessageStop(stop_reason="end_turn"),
    ]
    response = collect_stream(events)
    tool_use = response.blocks[0]
    # Invalid JSON yields an empty dict — the tool will surface a clearer
    # error than a JSON exception would.
    assert tool_use.input == {}


def test_events_from_model_response_roundtrip() -> None:
    response = ModelResponse(
        blocks=[
            AssistantTextBlock(text="Hi"),
            AssistantToolUseBlock(id="t1", name="FileRead", input={"path": "x"}),
        ],
        stop_reason="tool_use",
        usage={"input_tokens": 3},
    )
    rebuilt = collect_stream(events_from_model_response(response))
    assert rebuilt.stop_reason == "tool_use"
    assert rebuilt.usage == {"input_tokens": 3}
    assert rebuilt.blocks[0].text == "Hi"
    assert rebuilt.blocks[1].input == {"path": "x"}


# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------


def test_retry_policy_sleep_for_scales_exponentially() -> None:
    policy = RetryPolicy(base_delay_seconds=1.0, backoff_factor=2.0, jitter_seconds=0.0)
    assert policy.sleep_for(1) == pytest.approx(1.0)
    assert policy.sleep_for(2) == pytest.approx(2.0)
    assert policy.sleep_for(3) == pytest.approx(4.0)


def test_retry_policy_applies_max_delay_ceiling() -> None:
    policy = RetryPolicy(
        base_delay_seconds=10.0,
        backoff_factor=10.0,
        jitter_seconds=0.0,
        max_delay_seconds=5.0,
    )
    assert policy.sleep_for(5) == 5.0


def test_retry_call_succeeds_eventually() -> None:
    attempts: list[int] = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("boom")
        return "ok"

    recorded_sleeps: list[float] = []
    result = retry_call(
        flaky,
        should_retry=lambda exc: isinstance(exc, RuntimeError),
        policy=RetryPolicy(base_delay_seconds=0.1, jitter_seconds=0.0),
        sleep=recorded_sleeps.append,
    )
    assert result == "ok"
    assert len(attempts) == 3
    # Two retries trigger two sleeps (first attempt is the initial call).
    assert len(recorded_sleeps) == 2


def test_retry_call_reraises_when_should_retry_returns_false() -> None:
    def explode():
        raise ValueError("no retries please")

    with pytest.raises(ValueError, match="no retries"):
        retry_call(
            explode,
            should_retry=lambda exc: False,
            policy=RetryPolicy(max_attempts=5, base_delay_seconds=0.0, jitter_seconds=0.0),
            sleep=lambda _: None,
        )


def test_retry_call_reraises_after_max_attempts() -> None:
    def always_fails():
        raise RuntimeError("gone")

    with pytest.raises(RuntimeError, match="gone"):
        retry_call(
            always_fails,
            should_retry=lambda exc: True,
            policy=RetryPolicy(max_attempts=2, base_delay_seconds=0.0, jitter_seconds=0.0),
            sleep=lambda _: None,
        )


def test_retry_call_reports_via_on_retry_callback() -> None:
    seen: list[tuple[int, str, float]] = []

    def flaky():
        raise RuntimeError("still broken")

    with pytest.raises(RuntimeError):
        retry_call(
            flaky,
            should_retry=lambda exc: True,
            policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.0, jitter_seconds=0.0),
            sleep=lambda _: None,
            on_retry=lambda idx, exc, delay: seen.append((idx, str(exc), delay)),
        )
    assert len(seen) == 2  # two retries before the final raise


# ---------------------------------------------------------------------------
# Prompt caching
# ---------------------------------------------------------------------------


def test_compute_cache_blocks_empty_inputs_returns_empty() -> None:
    assert compute_cache_blocks(CacheInput()) == []


def test_compute_cache_blocks_marks_large_system_prompt() -> None:
    long_prompt = "x" * (MIN_CACHEABLE_CHARS + 100)
    blocks = compute_cache_blocks(CacheInput(system_prompt=long_prompt))
    assert len(blocks) == 1
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}


def test_compute_cache_blocks_skips_short_prompt() -> None:
    blocks = compute_cache_blocks(CacheInput(system_prompt="short"))
    assert len(blocks) == 1
    assert "cache_control" not in blocks[0]


def test_compute_cache_blocks_preserves_order() -> None:
    long_a = "a" * (MIN_CACHEABLE_CHARS + 1)
    long_b = "b" * (MIN_CACHEABLE_CHARS + 1)
    long_c = "c" * (MIN_CACHEABLE_CHARS + 1)
    blocks = compute_cache_blocks(
        CacheInput(
            pinned_memory=long_a,
            tool_schema_text=long_b,
            system_prompt=long_c,
        )
    )
    assert [block["text"][0] for block in blocks] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------


def test_resolve_provider_matches_longest_prefix() -> None:
    assert resolve_provider("claude-sonnet-4-5") == "anthropic"
    assert resolve_provider("gpt-4o") == "openai"
    assert resolve_provider("o3-mini") == "openai"
    assert resolve_provider("gemini-2.5-pro") == "gemini"
    assert resolve_provider("echo") == "echo"


def test_resolve_provider_unknown_raises() -> None:
    with pytest.raises(ProviderFactoryError):
        resolve_provider("llama-7b")


def test_create_model_client_returns_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    client = create_model_client(model="claude-sonnet-4-5")
    assert isinstance(client, AnthropicClient)
    assert client.model == "claude-sonnet-4-5"


def test_create_model_client_returns_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client = create_model_client(model="gpt-4o")
    assert isinstance(client, OpenAIClient)


def test_create_model_client_echo_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client = create_model_client(
        model="claude-sonnet-4-5",
        echo_fallback_on_missing_keys=True,
    )
    # Echo is the stub used by print mode; verify we got it by name/shape.
    assert type(client).__name__ == "EchoModel"


# ---------------------------------------------------------------------------
# AnthropicClient — event translation via a fake SDK
# ---------------------------------------------------------------------------


@dataclass
class _FakeEvent:
    type: str
    content_block: Any = None
    delta: Any = None
    index: int | None = None
    usage: Any = None
    message: Any = None


@dataclass
class _FakeBlock:
    type: str
    id: str = ""
    name: str = ""
    input: Any = None


@dataclass
class _FakeDelta:
    type: str
    text: str = ""
    thinking: str = ""
    partial_json: str = ""


@dataclass
class _FakeUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


class _FakeStream:
    """Context-manager returned by the fake SDK's ``messages.stream``."""

    def __init__(self, events: list[_FakeEvent]) -> None:
        self._events = events
        self.enter_count = 0

    def __enter__(self):
        self.enter_count += 1
        return iter(self._events)

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeSdk:
    def __init__(self, events: list[_FakeEvent]) -> None:
        self.events = events
        self.calls: list[dict[str, Any]] = []

    def messages(self):  # pragma: no cover - only the attribute matters
        return self

    class _Messages:
        def __init__(self, outer: "_FakeSdk") -> None:
            self.outer = outer

        def stream(self, **kwargs: Any) -> _FakeStream:
            self.outer.calls.append(kwargs)
            return _FakeStream(self.outer.events)

    def __post_init__(self):  # pragma: no cover
        pass


def _build_fake_sdk(events: list[_FakeEvent]) -> _FakeSdk:
    sdk = _FakeSdk(events)
    sdk.messages = _FakeSdk._Messages(sdk)  # type: ignore[attr-defined]
    return sdk


def test_anthropic_client_translates_text_deltas() -> None:
    events = [
        _FakeEvent(
            type="content_block_delta",
            delta=_FakeDelta(type="text_delta", text="Hello "),
        ),
        _FakeEvent(
            type="content_block_delta",
            delta=_FakeDelta(type="text_delta", text="world"),
        ),
        _FakeEvent(
            type="message_stop",
            message=type("M", (), {"stop_reason": "end_turn", "usage": _FakeUsage(input_tokens=5, output_tokens=2)})(),
        ),
    ]
    sdk = _build_fake_sdk(events)
    client = AnthropicClient(
        model="claude-sonnet-4-5",
        api_key="sk-ant-test",
        sdk_factory=lambda _key: sdk,
    )
    response = client.complete(
        system_prompt="You are helpful.",
        messages=[TurnMessage(role="user", content="Hi")],
        tools=[],
    )
    assert response.blocks[0].text == "Hello world"
    assert response.stop_reason == "end_turn"
    assert response.usage["input_tokens"] == 5
    assert response.usage["output_tokens"] == 2
    # Exactly one SDK call made.
    assert len(sdk.calls) == 1  # type: ignore[attr-defined]


def test_anthropic_client_translates_tool_use_stream() -> None:
    events = [
        _FakeEvent(
            type="content_block_start",
            content_block=_FakeBlock(type="tool_use", id="toolu_a", name="FileRead"),
        ),
        _FakeEvent(
            type="content_block_delta",
            index=0,
            delta=_FakeDelta(type="input_json_delta", partial_json='{"path":'),
        ),
        _FakeEvent(
            type="content_block_delta",
            index=0,
            delta=_FakeDelta(type="input_json_delta", partial_json='"a.txt"}'),
        ),
        _FakeEvent(
            type="content_block_stop",
            content_block=_FakeBlock(type="tool_use", id="toolu_a", name="FileRead", input={"path": "a.txt"}),
        ),
        _FakeEvent(
            type="message_stop",
            message=type("M", (), {"stop_reason": "tool_use", "usage": _FakeUsage()})(),
        ),
    ]
    sdk = _build_fake_sdk(events)
    client = AnthropicClient(api_key="k", sdk_factory=lambda _: sdk)
    response = client.complete(system_prompt="", messages=[], tools=[])
    assert response.stop_reason == "tool_use"
    assert response.blocks[0].name == "FileRead"
    assert response.blocks[0].input == {"path": "a.txt"}


def test_anthropic_client_uses_system_cache_blocks_for_long_prompt() -> None:
    long_prompt = "x" * (MIN_CACHEABLE_CHARS + 10)
    events = [
        _FakeEvent(
            type="message_stop",
            message=type("M", (), {"stop_reason": "end_turn", "usage": _FakeUsage()})(),
        ),
    ]
    sdk = _build_fake_sdk(events)
    client = AnthropicClient(api_key="k", sdk_factory=lambda _: sdk)
    client.complete(system_prompt=long_prompt, messages=[], tools=[])
    call = sdk.calls[0]  # type: ignore[attr-defined]
    # The system field should now be a list of cache-annotated blocks.
    assert isinstance(call["system"], list)
    cached_blocks = [block for block in call["system"] if block.get("cache_control")]
    assert len(cached_blocks) == 1
    assert cached_blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert cached_blocks[0]["text"] == long_prompt


def test_anthropic_client_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client = AnthropicClient(sdk_factory=lambda _: _build_fake_sdk([]))
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        client.complete(system_prompt="", messages=[], tools=[])


def test_anthropic_client_is_retryable_error_classifies_rate_limit() -> None:
    rate_limit = type("RateLimitError", (Exception,), {"status_code": 429})()
    timeout_error = type("TimeoutError", (Exception,), {"status_code": 504})()
    auth_error = type("AuthError", (Exception,), {"status_code": 401})()
    assert AnthropicClient._is_retryable_error(rate_limit) is True
    assert AnthropicClient._is_retryable_error(timeout_error) is True
    assert AnthropicClient._is_retryable_error(auth_error) is False


# ---------------------------------------------------------------------------
# OpenAIClient — translation via a fake SDK
# ---------------------------------------------------------------------------


@dataclass
class _FakeFunction:
    name: str
    arguments: str


@dataclass
class _FakeToolCall:
    id: str
    function: _FakeFunction
    type: str = "function"


@dataclass
class _FakeMessage:
    role: str = "assistant"
    content: str | None = None
    tool_calls: list[_FakeToolCall] = None  # type: ignore[assignment]


@dataclass
class _FakeChoice:
    message: _FakeMessage
    finish_reason: str


@dataclass
class _FakeOpenAiUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class _FakeOpenAiResponse:
    choices: list[_FakeChoice]
    usage: _FakeOpenAiUsage


class _FakeOpenAiSdk:
    def __init__(self, response: _FakeOpenAiResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

        class _Completions:
            def __init__(self, outer: "_FakeOpenAiSdk") -> None:
                self.outer = outer

            def create(self, **kwargs: Any) -> _FakeOpenAiResponse:
                self.outer.calls.append(kwargs)
                return self.outer.response

        class _Chat:
            def __init__(self, outer: "_FakeOpenAiSdk") -> None:
                self.completions = _Completions(outer)

        self.chat = _Chat(self)


def test_openai_client_text_response_becomes_assistant_text_block() -> None:
    response = _FakeOpenAiResponse(
        choices=[
            _FakeChoice(
                message=_FakeMessage(content="Hello!", tool_calls=None),
                finish_reason="stop",
            )
        ],
        usage=_FakeOpenAiUsage(prompt_tokens=3, completion_tokens=1, total_tokens=4),
    )
    sdk = _FakeOpenAiSdk(response)
    client = OpenAIClient(api_key="k", sdk_factory=lambda _: sdk)
    result = client.complete(
        system_prompt="sys",
        messages=[TurnMessage(role="user", content="Hi")],
        tools=[],
    )
    assert result.blocks[0].text == "Hello!"
    assert result.stop_reason == "stop"
    assert result.usage["prompt_tokens"] == 3


def test_openai_client_tool_calls_translate_to_anthropic_blocks() -> None:
    response = _FakeOpenAiResponse(
        choices=[
            _FakeChoice(
                message=_FakeMessage(
                    content="",
                    tool_calls=[
                        _FakeToolCall(
                            id="call_1",
                            function=_FakeFunction(
                                name="FileRead",
                                arguments=json.dumps({"path": "a.txt"}),
                            ),
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )
        ],
        usage=_FakeOpenAiUsage(),
    )
    sdk = _FakeOpenAiSdk(response)
    client = OpenAIClient(api_key="k", sdk_factory=lambda _: sdk)
    result = client.complete(system_prompt="", messages=[], tools=[])
    assert result.stop_reason == "tool_use"
    assert result.blocks[0].name == "FileRead"
    assert result.blocks[0].input == {"path": "a.txt"}


def test_openai_client_tool_schema_translated_to_function_spec() -> None:
    response = _FakeOpenAiResponse(
        choices=[
            _FakeChoice(
                message=_FakeMessage(content="ok", tool_calls=None),
                finish_reason="stop",
            )
        ],
        usage=_FakeOpenAiUsage(),
    )
    sdk = _FakeOpenAiSdk(response)
    client = OpenAIClient(api_key="k", sdk_factory=lambda _: sdk)
    client.complete(
        system_prompt="",
        messages=[],
        tools=[
            {
                "name": "FileRead",
                "description": "Read a file",
                "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
            }
        ],
    )
    tools_arg = sdk.calls[0]["tools"]
    assert tools_arg[0] == {
        "type": "function",
        "function": {
            "name": "FileRead",
            "description": "Read a file",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        },
    }


def test_openai_client_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = OpenAIClient(sdk_factory=lambda _: _FakeOpenAiSdk(
        _FakeOpenAiResponse(choices=[], usage=_FakeOpenAiUsage()),
    ))
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        client.complete(system_prompt="", messages=[], tools=[])


# ---------------------------------------------------------------------------
# Orchestrator + streaming integration
# ---------------------------------------------------------------------------


class _FakeStreamingModel:
    """ModelClient that implements stream() so the orchestrator prefers it."""

    def __init__(self, event_sequences: list[list[Any]]) -> None:
        self._sequences = list(event_sequences)
        self.calls: list[dict[str, Any]] = []

    def stream(
        self,
        *,
        system_prompt: str,
        messages: list[TurnMessage],
        tools: list[dict[str, Any]],
    ) -> Iterator[Any]:
        self.calls.append(
            {"system_prompt": system_prompt, "messages": [m.to_wire() for m in messages], "tools": tools}
        )
        events = self._sequences.pop(0) if self._sequences else [MessageStop(stop_reason="end_turn")]
        for event in events:
            yield event


def test_orchestrator_consumes_streaming_events(tmp_path: Path) -> None:
    from cli.llm.orchestrator import LLMOrchestrator
    from cli.permissions import PermissionManager
    from cli.sessions import SessionStore
    from cli.tools.file_read import FileReadTool
    from cli.tools.registry import ToolRegistry

    (tmp_path / ".agentlab").mkdir()
    model = _FakeStreamingModel(
        [
            [
                TextDelta(text="part one "),
                TextDelta(text="part two"),
                MessageStop(stop_reason="end_turn"),
            ]
        ]
    )
    echo_sink: list[str] = []
    session_store = SessionStore(workspace_dir=tmp_path)
    session = session_store.create(title="streaming test")
    tool_registry = ToolRegistry()
    tool_registry.register(FileReadTool())
    orchestrator = LLMOrchestrator(
        model=model,
        tool_registry=tool_registry,
        permissions=PermissionManager(root=tmp_path),
        workspace_root=tmp_path,
        session=session,
        session_store=session_store,
        echo=echo_sink.append,
    )
    result = orchestrator.run_turn("Stream this")
    # Both chunks render live through the markdown streamer.
    rendered = "\n".join(echo_sink)
    assert "part one " in rendered
    assert "part two" in rendered
    assert "part one part two" in result.assistant_text


def test_orchestrator_roundtrips_streaming_tool_use(tmp_path: Path) -> None:
    from cli.llm.orchestrator import LLMOrchestrator
    from cli.permissions import PermissionManager
    from cli.sessions import SessionStore
    from cli.tools.file_read import FileReadTool
    from cli.tools.registry import ToolRegistry

    (tmp_path / ".agentlab").mkdir()
    (tmp_path / "note.txt").write_text("hello\n", encoding="utf-8")

    model = _FakeStreamingModel(
        [
            [
                TextDelta(text="Reading…\n"),
                ToolUseStart(id="t1", name="FileRead"),
                ToolUseDelta(id="t1", input_json='{"path":"note.txt"}'),
                ToolUseEnd(id="t1", name="FileRead", input={"path": "note.txt"}),
                MessageStop(stop_reason="tool_use"),
            ],
            [
                TextDelta(text="Done."),
                MessageStop(stop_reason="end_turn"),
            ],
        ]
    )

    echo_sink: list[str] = []
    session_store = SessionStore(workspace_dir=tmp_path)
    session = session_store.create(title="tool round-trip")
    tool_registry = ToolRegistry()
    tool_registry.register(FileReadTool())
    orchestrator = LLMOrchestrator(
        model=model,
        tool_registry=tool_registry,
        permissions=PermissionManager(root=tmp_path),
        workspace_root=tmp_path,
        session=session,
        session_store=session_store,
        echo=echo_sink.append,
    )
    result = orchestrator.run_turn("Summarise the note")
    assert len(result.tool_executions) == 1
    assert result.tool_executions[0].tool_name == "FileRead"
    # Second model call saw the tool_result block.
    assert len(model.calls) == 2
    tool_result_block = model.calls[1]["messages"][-1]["content"][0]
    assert tool_result_block["type"] == "tool_result"
    assert "hello" in tool_result_block["content"]
    assert "Done." in result.assistant_text
