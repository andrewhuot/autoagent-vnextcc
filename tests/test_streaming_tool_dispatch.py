"""Tests for cli.llm.streaming_tool_dispatcher."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

from cli.llm.provider_capabilities import ProviderCapabilities
from cli.llm.streaming import ToolUseDelta, ToolUseEnd, ToolUseStart
from cli.llm.streaming_tool_dispatcher import StreamingToolDispatcher
from cli.tools.base import PermissionDecision, Tool, ToolResult
from cli.tools.executor import ToolExecution
from cli.tools.registry import ToolRegistry


class _FakeTool(Tool):
    def __init__(self, name: str, *, is_concurrency_safe: bool) -> None:
        self.name = name
        self.description = name
        self.input_schema = {}
        self.is_concurrency_safe = is_concurrency_safe

    def run(self, tool_input: dict[str, Any], context: Any) -> ToolResult:
        return ToolResult.success({"tool_input": dict(tool_input)})


@dataclass
class _ToolBehavior:
    release_event: threading.Event
    result: ToolResult | None = None
    raises: Exception | None = None
    requires_prompt: bool = False


class _BlockingExecutor:
    def __init__(self, behaviors: dict[str, _ToolBehavior]) -> None:
        self.behaviors = behaviors
        self.started: list[str] = []
        self.finished: list[str] = []
        self.active_count = 0
        self.max_active_count = 0
        self.overlap_seen = threading.Event()
        self.cancel_called = False
        self.cancel_requested = threading.Event()
        self.started_events: dict[str, threading.Event] = {
            name: threading.Event() for name in behaviors
        }
        self.finished_events: dict[str, threading.Event] = {
            name: threading.Event() for name in behaviors
        }
        self._lock = threading.Lock()

    def requires_permission_prompt(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        return self.behaviors[tool_name].requires_prompt

    def cancel_all(self) -> None:
        self.cancel_called = True
        self.cancel_requested.set()
        for behavior in self.behaviors.values():
            behavior.release_event.set()

    def cancel(self, tool_use_id: str) -> None:
        self.cancel_called = True
        self.cancel_requested.set()
        behavior = self.behaviors.get(tool_use_id)
        if behavior is not None:
            behavior.release_event.set()

    def __call__(self, tool_name: str, tool_input: dict[str, Any]) -> ToolExecution:
        with self._lock:
            self.started.append(tool_name)
            self.active_count += 1
            self.max_active_count = max(self.max_active_count, self.active_count)
            if self.active_count > 1:
                self.overlap_seen.set()
        self.started_events[tool_name].set()

        behavior = self.behaviors[tool_name]
        behavior.release_event.wait(timeout=2)

        try:
            if self.cancel_requested.is_set():
                return ToolExecution(
                    tool_name=tool_name,
                    decision=PermissionDecision.DENY,
                    result=ToolResult.failure(f"{tool_name} cancelled"),
                    denial_reason="cancelled",
                )
            if behavior.raises is not None:
                raise behavior.raises
            result = behavior.result or ToolResult.success({"tool": tool_name})
            return ToolExecution(
                tool_name=tool_name,
                decision=PermissionDecision.ALLOW if result.ok else PermissionDecision.DENY,
                result=result,
            )
        finally:
            with self._lock:
                self.active_count -= 1
                self.finished.append(tool_name)
            self.finished_events[tool_name].set()


def _build_registry(tools: list[_FakeTool]) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


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


def _dispatcher(
    *,
    registry: ToolRegistry,
    executor: Callable[[str, dict[str, Any]], ToolExecution],
    parallel_tool_calls: bool,
    max_concurrency: int = 4,
) -> StreamingToolDispatcher:
    return StreamingToolDispatcher(
        registry=registry,
        executor=executor,
        capabilities=_caps(parallel_tool_calls=parallel_tool_calls),
        max_concurrency=max_concurrency,
    )


def _feed(dispatcher: StreamingToolDispatcher, tool_name: str, tool_input: dict[str, Any]) -> None:
    dispatcher.on_tool_use_start(ToolUseStart(id=tool_name, name=tool_name))
    dispatcher.on_tool_use_delta(ToolUseDelta(id=tool_name, input_json=""))
    dispatcher.on_tool_use_end(ToolUseEnd(id=tool_name, name=tool_name, input=tool_input))


def test_sequential_mode_runs_tools_one_at_a_time() -> None:
    first_release = threading.Event()
    second_release = threading.Event()
    executor = _BlockingExecutor(
        {
            "safe1": _ToolBehavior(release_event=first_release),
            "safe2": _ToolBehavior(release_event=second_release),
        }
    )
    dispatcher = _dispatcher(
        registry=_build_registry(
            [
                _FakeTool("safe1", is_concurrency_safe=True),
                _FakeTool("safe2", is_concurrency_safe=True),
            ]
        ),
        executor=executor,
        parallel_tool_calls=False,
    )

    _feed(dispatcher, "safe1", {"value": 1})
    assert executor.started_events["safe1"].wait(timeout=2)

    _feed(dispatcher, "safe2", {"value": 2})
    assert not executor.started_events["safe2"].is_set()

    first_release.set()
    assert executor.finished_events["safe1"].wait(timeout=2)
    assert executor.started_events["safe2"].wait(timeout=2)

    second_release.set()
    assert executor.finished_events["safe2"].wait(timeout=2)

    results = dispatcher.results_in_order()
    assert [execution.tool_name for execution in results] == ["safe1", "safe2"]


def test_safe_tools_overlap_when_parallel_calls_are_allowed() -> None:
    first_release = threading.Event()
    second_release = threading.Event()
    executor = _BlockingExecutor(
        {
            "safe1": _ToolBehavior(release_event=first_release),
            "safe2": _ToolBehavior(release_event=second_release),
        }
    )
    dispatcher = _dispatcher(
        registry=_build_registry(
            [
                _FakeTool("safe1", is_concurrency_safe=True),
                _FakeTool("safe2", is_concurrency_safe=True),
            ]
        ),
        executor=executor,
        parallel_tool_calls=True,
        max_concurrency=4,
    )

    _feed(dispatcher, "safe1", {"value": 1})
    _feed(dispatcher, "safe2", {"value": 2})

    assert executor.started_events["safe1"].wait(timeout=2)
    assert executor.started_events["safe2"].wait(timeout=2)
    assert executor.overlap_seen.is_set()

    first_release.set()
    second_release.set()

    results = dispatcher.results_in_order()
    assert [execution.tool_name for execution in results] == ["safe1", "safe2"]


def test_unsafe_tool_is_an_order_barrier_for_later_safe_tools() -> None:
    safe1_release = threading.Event()
    safe2_release = threading.Event()
    unsafe_release = threading.Event()
    safe4_release = threading.Event()
    executor = _BlockingExecutor(
        {
            "safe1": _ToolBehavior(release_event=safe1_release),
            "safe2": _ToolBehavior(release_event=safe2_release),
            "unsafe3": _ToolBehavior(release_event=unsafe_release),
            "safe4": _ToolBehavior(release_event=safe4_release),
        }
    )
    dispatcher = _dispatcher(
        registry=_build_registry(
            [
                _FakeTool("safe1", is_concurrency_safe=True),
                _FakeTool("safe2", is_concurrency_safe=True),
                _FakeTool("unsafe3", is_concurrency_safe=False),
                _FakeTool("safe4", is_concurrency_safe=True),
            ]
        ),
        executor=executor,
        parallel_tool_calls=True,
        max_concurrency=4,
    )

    _feed(dispatcher, "safe1", {"value": 1})
    _feed(dispatcher, "safe2", {"value": 2})
    assert executor.started_events["safe1"].wait(timeout=2)
    assert executor.started_events["safe2"].wait(timeout=2)

    _feed(dispatcher, "unsafe3", {"value": 3})
    _feed(dispatcher, "safe4", {"value": 4})
    assert not executor.started_events["unsafe3"].is_set()
    assert not executor.started_events["safe4"].is_set()

    safe1_release.set()
    safe2_release.set()
    assert executor.finished_events["safe1"].wait(timeout=2)
    assert executor.finished_events["safe2"].wait(timeout=2)
    assert executor.started_events["unsafe3"].wait(timeout=2)
    assert not executor.started_events["safe4"].is_set()

    unsafe_release.set()
    assert executor.finished_events["unsafe3"].wait(timeout=2)
    assert executor.started_events["safe4"].wait(timeout=2)

    safe4_release.set()
    assert executor.finished_events["safe4"].wait(timeout=2)

    results = dispatcher.results_in_order()
    assert [execution.tool_name for execution in results] == [
        "safe1",
        "safe2",
        "unsafe3",
        "safe4",
    ]


def test_results_are_returned_in_declared_order_when_completion_is_reversed() -> None:
    first_release = threading.Event()
    second_release = threading.Event()
    executor = _BlockingExecutor(
        {
            "first": _ToolBehavior(release_event=first_release),
            "second": _ToolBehavior(release_event=second_release),
        }
    )
    dispatcher = _dispatcher(
        registry=_build_registry(
            [
                _FakeTool("first", is_concurrency_safe=True),
                _FakeTool("second", is_concurrency_safe=True),
            ]
        ),
        executor=executor,
        parallel_tool_calls=True,
    )

    _feed(dispatcher, "first", {"value": 1})
    _feed(dispatcher, "second", {"value": 2})
    assert executor.started_events["first"].wait(timeout=2)
    assert executor.started_events["second"].wait(timeout=2)

    second_release.set()
    assert executor.finished_events["second"].wait(timeout=2)
    first_release.set()
    assert executor.finished_events["first"].wait(timeout=2)

    results = dispatcher.results_in_order()
    assert [execution.tool_name for execution in results] == ["first", "second"]


def test_prompting_tool_drains_active_work_before_running_exclusively() -> None:
    safe_release = threading.Event()
    prompt_release = threading.Event()
    later_release = threading.Event()
    executor = _BlockingExecutor(
        {
            "safe1": _ToolBehavior(release_event=safe_release),
            "prompt2": _ToolBehavior(
                release_event=prompt_release,
                requires_prompt=True,
            ),
            "safe3": _ToolBehavior(release_event=later_release),
        }
    )
    dispatcher = _dispatcher(
        registry=_build_registry(
            [
                _FakeTool("safe1", is_concurrency_safe=True),
                _FakeTool("prompt2", is_concurrency_safe=True),
                _FakeTool("safe3", is_concurrency_safe=True),
            ]
        ),
        executor=executor,
        parallel_tool_calls=True,
    )

    _feed(dispatcher, "safe1", {"value": 1})
    assert executor.started_events["safe1"].wait(timeout=2)

    _feed(dispatcher, "prompt2", {"value": 2})
    _feed(dispatcher, "safe3", {"value": 3})
    assert not executor.started_events["prompt2"].is_set()
    assert not executor.started_events["safe3"].is_set()

    safe_release.set()
    assert executor.finished_events["safe1"].wait(timeout=2)
    assert executor.started_events["prompt2"].wait(timeout=2)
    assert not executor.started_events["safe3"].is_set()

    prompt_release.set()
    assert executor.finished_events["prompt2"].wait(timeout=2)
    assert executor.started_events["safe3"].wait(timeout=2)

    later_release.set()
    assert executor.finished_events["safe3"].wait(timeout=2)

    results = dispatcher.results_in_order()
    assert [execution.tool_name for execution in results] == ["safe1", "prompt2", "safe3"]


def test_late_safe_tool_waits_for_started_exclusive_tool_to_finish() -> None:
    prompt_release = threading.Event()
    safe_release = threading.Event()
    executor = _BlockingExecutor(
        {
            "prompt1": _ToolBehavior(
                release_event=prompt_release,
                requires_prompt=True,
            ),
            "safe2": _ToolBehavior(release_event=safe_release),
        }
    )
    dispatcher = _dispatcher(
        registry=_build_registry(
            [
                _FakeTool("prompt1", is_concurrency_safe=True),
                _FakeTool("safe2", is_concurrency_safe=True),
            ]
        ),
        executor=executor,
        parallel_tool_calls=True,
    )

    _feed(dispatcher, "prompt1", {"value": 1})
    assert executor.started_events["prompt1"].wait(timeout=2)

    _feed(dispatcher, "safe2", {"value": 2})
    assert not executor.started_events["safe2"].is_set()

    prompt_release.set()
    assert executor.finished_events["prompt1"].wait(timeout=2)
    assert executor.started_events["safe2"].wait(timeout=2)

    safe_release.set()
    results = dispatcher.results_in_order()
    assert [execution.tool_name for execution in results] == ["prompt1", "safe2"]


def test_a_failing_tool_does_not_abort_a_sibling_call() -> None:
    fail_release = threading.Event()
    sibling_release = threading.Event()
    executor = _BlockingExecutor(
        {
            "fail": _ToolBehavior(release_event=fail_release, raises=RuntimeError("boom")),
            "sibling": _ToolBehavior(release_event=sibling_release),
        }
    )
    dispatcher = _dispatcher(
        registry=_build_registry(
            [
                _FakeTool("fail", is_concurrency_safe=True),
                _FakeTool("sibling", is_concurrency_safe=True),
            ]
        ),
        executor=executor,
        parallel_tool_calls=True,
    )

    _feed(dispatcher, "fail", {"value": 1})
    _feed(dispatcher, "sibling", {"value": 2})
    assert executor.started_events["fail"].wait(timeout=2)
    assert executor.started_events["sibling"].wait(timeout=2)

    fail_release.set()
    sibling_release.set()

    results = dispatcher.results_in_order()
    assert [execution.tool_name for execution in results] == ["fail", "sibling"]
    assert results[0].result is not None
    assert results[0].result.ok is False
    assert results[1].result is not None
    assert results[1].result.ok is True


def test_cancel_all_prevents_partial_results_from_surfaces() -> None:
    first_release = threading.Event()
    second_release = threading.Event()
    executor = _BlockingExecutor(
        {
            "first": _ToolBehavior(release_event=first_release),
            "second": _ToolBehavior(release_event=second_release),
        }
    )
    dispatcher = _dispatcher(
        registry=_build_registry(
            [
                _FakeTool("first", is_concurrency_safe=True),
                _FakeTool("second", is_concurrency_safe=True),
            ]
        ),
        executor=executor,
        parallel_tool_calls=True,
        max_concurrency=1,
    )

    _feed(dispatcher, "first", {"value": 1})
    _feed(dispatcher, "second", {"value": 2})
    assert executor.started_events["first"].wait(timeout=2)
    assert not executor.started_events["second"].is_set()

    dispatcher.cancel_all()
    assert executor.cancel_called is True
    assert executor.finished_events["first"].wait(timeout=2)

    results = dispatcher.results_in_order()
    assert results == []
    assert not executor.started_events["second"].is_set()


def test_results_in_order_returns_immediately_for_empty_dispatcher() -> None:
    dispatcher = _dispatcher(
        registry=_build_registry([]),
        executor=_BlockingExecutor({}),
        parallel_tool_calls=True,
    )

    assert dispatcher.results_in_order() == []


def test_results_in_order_waits_without_an_artificial_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()
    executor = _BlockingExecutor(
        {
            "safe": _ToolBehavior(release_event=release),
        }
    )
    dispatcher = _dispatcher(
        registry=_build_registry([_FakeTool("safe", is_concurrency_safe=True)]),
        executor=executor,
        parallel_tool_calls=True,
    )

    _feed(dispatcher, "safe", {"value": 1})
    assert executor.started_events["safe"].wait(timeout=2)

    observed: dict[str, Any] = {}
    original_wait_for = threading.Condition.wait_for

    def fake_wait_for(self, predicate, timeout=None):
        observed["timeout"] = timeout
        return original_wait_for(self, predicate, timeout=timeout)

    monkeypatch.setattr(threading.Condition, "wait_for", fake_wait_for)
    release.set()

    results = dispatcher.results_in_order()
    assert [execution.tool_name for execution in results] == ["safe"]
    assert observed["timeout"] is None
