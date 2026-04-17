"""Tests for ``cli.workbench_app.agentlab_tools._base.AgentLabTool``.

These tests build a ``_TestFakeTool`` subclass per scenario that wraps a
controllable callable. Real eval / deploy / improve logic is never invoked;
each test runs in microseconds.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Callable

import pytest

from cli.strict_live import MockFallbackError
from cli.tools.base import ToolContext, ToolResult
from cli.workbench_app.agentlab_tools._base import AgentLabTool


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace_root=tmp_path)


def _make_fake_tool(
    fn: Callable[..., Any],
    *,
    name: str = "FakeTool",
    description: str = "A fake AgentLab tool for tests.",
    input_schema: dict[str, Any] | None = None,
) -> AgentLabTool:
    """Build a concrete AgentLabTool subclass that dispatches to ``fn``."""

    class _TestFakeTool(AgentLabTool):
        def _in_process_fn(self) -> Callable[..., Any]:
            return fn

    _TestFakeTool.name = name
    _TestFakeTool.description = description
    _TestFakeTool.input_schema = input_schema or {
        "type": "object",
        "properties": {},
        "additionalProperties": True,
    }
    return _TestFakeTool()


# --------------------------------------------------------------------------
# Abstract base class behaviour
# --------------------------------------------------------------------------


def test_agentlab_tool_is_abstract() -> None:
    """``AgentLabTool()`` cannot be instantiated directly — ``_in_process_fn``
    is abstract."""

    with pytest.raises(TypeError):
        AgentLabTool()  # type: ignore[abstract]


# --------------------------------------------------------------------------
# Happy paths
# --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _ResultOneField:
    score: float


def test_run_invokes_in_process_fn_and_shapes_result(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def fn(*, x: int) -> _ResultOneField:
        captured["x"] = x
        return _ResultOneField(score=0.9)

    tool = _make_fake_tool(
        fn,
        input_schema={
            "type": "object",
            "properties": {"x": {"type": "integer"}},
            "required": ["x"],
        },
    )
    result = tool.run({"x": 1}, _ctx(tmp_path))

    assert result.ok is True
    assert result.content == {"score": 0.9}
    assert captured == {"x": 1}


def test_run_strips_unknown_args(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def fn(*, a: int) -> _ResultOneField:
        captured.update({"a": a})
        return _ResultOneField(score=1.0)

    tool = _make_fake_tool(fn)
    result = tool.run({"a": 1, "b": 2}, _ctx(tmp_path))

    assert result.ok is True
    assert captured == {"a": 1}, "Unknown arg 'b' must be stripped before call"


def test_run_auto_injects_on_event(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def fn(*, on_event: Callable[[Any], None]) -> _ResultOneField:
        captured["on_event"] = on_event
        return _ResultOneField(score=0.0)

    tool = _make_fake_tool(fn)
    result = tool.run({}, _ctx(tmp_path))

    assert result.ok is True
    assert callable(captured["on_event"])


def test_run_auto_injects_text_writer(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def fn(*, text_writer: Callable[[str], None] | None) -> _ResultOneField:
        captured["text_writer"] = text_writer
        return _ResultOneField(score=0.0)

    tool = _make_fake_tool(fn)
    result = tool.run({}, _ctx(tmp_path))

    assert result.ok is True
    assert captured["text_writer"] is None


def test_run_does_not_inject_on_event_when_caller_provides_one(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}
    sentinel = lambda _e: None  # noqa: E731 — concise sentinel for identity check

    def fn(*, on_event: Callable[[Any], None]) -> _ResultOneField:
        captured["on_event"] = on_event
        return _ResultOneField(score=0.0)

    tool = _make_fake_tool(fn)
    result = tool.run({"on_event": sentinel}, _ctx(tmp_path))

    assert result.ok is True
    assert captured["on_event"] is sentinel


# --------------------------------------------------------------------------
# Error paths — domain failures become ToolResult.failure
# --------------------------------------------------------------------------


def test_run_catches_domain_exception_returns_failure(tmp_path: Path) -> None:
    def fn() -> _ResultOneField:
        raise MockFallbackError(["x"])

    tool = _make_fake_tool(fn)
    result = tool.run({}, _ctx(tmp_path))

    assert isinstance(result, ToolResult)
    assert result.ok is False
    assert "MockFallbackError" in str(result.content)


def test_run_catches_runtime_error_returns_failure(tmp_path: Path) -> None:
    def fn() -> _ResultOneField:
        raise RuntimeError("boom")

    tool = _make_fake_tool(fn)
    result = tool.run({}, _ctx(tmp_path))

    assert result.ok is False
    assert "RuntimeError" in str(result.content)
    assert "boom" in str(result.content)


# --------------------------------------------------------------------------
# permission_action default
# --------------------------------------------------------------------------


def test_default_permission_action_is_tool_name(tmp_path: Path) -> None:
    def fn() -> _ResultOneField:
        return _ResultOneField(score=0.0)

    tool = _make_fake_tool(fn, name="EvalRun")
    assert tool.permission_action({}) == "tool:EvalRun"


# --------------------------------------------------------------------------
# _shape_result / _to_jsonsafe semantics
# --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _NestedResult:
    items: tuple[str, ...]
    tags: frozenset[str]


def test_default_shape_result_handles_nested_tuples_and_sets(tmp_path: Path) -> None:
    def fn() -> _NestedResult:
        return _NestedResult(items=("a", "b"), tags=frozenset({"t1", "t2"}))

    tool = _make_fake_tool(fn)
    result = tool.run({}, _ctx(tmp_path))

    assert result.ok is True
    assert isinstance(result.content, dict)
    assert result.content["items"] == ["a", "b"]
    # frozenset has no defined order — compare as a set after listification.
    assert isinstance(result.content["tags"], list)
    assert set(result.content["tags"]) == {"t1", "t2"}


def test_default_shape_result_passes_through_dict(tmp_path: Path) -> None:
    payload = {"a": 1, "nested": {"b": [1, 2, 3]}}

    def fn() -> dict:
        return payload

    tool = _make_fake_tool(fn)
    result = tool.run({}, _ctx(tmp_path))

    assert result.ok is True
    assert result.content == payload


def test_default_shape_result_handles_non_dataclass_scalar(tmp_path: Path) -> None:
    """Documented behaviour: scalars pass through ``_to_jsonsafe`` unchanged."""

    def fn() -> int:
        return 42

    tool = _make_fake_tool(fn)
    result = tool.run({}, _ctx(tmp_path))

    assert result.ok is True
    assert result.content == 42


def test_run_metadata_includes_raw_type(tmp_path: Path) -> None:
    def fn() -> _ResultOneField:
        return _ResultOneField(score=0.5)

    tool = _make_fake_tool(fn)
    result = tool.run({}, _ctx(tmp_path))

    assert result.ok is True
    assert result.metadata.get("raw_type") == "_ResultOneField"
