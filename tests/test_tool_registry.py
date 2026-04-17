"""Unit tests for the in-process tool registry (R7.1)."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from cli.workbench_app.tool_registry import (
    ToolDescriptor,
    ToolRegistry,
    build_default_registry,
)


def test_register_then_get_returns_descriptor():
    reg = ToolRegistry()
    desc = ToolDescriptor(
        name="eval_run",
        description="Run an eval suite.",
        input_schema={"type": "object", "properties": {}},
        fn=lambda: "ok",
        shape_result=lambda v: {"value": v},
    )
    reg.register(desc)
    assert reg.get("eval_run") is desc


def test_register_rejects_duplicate_name():
    reg = ToolRegistry()
    desc = ToolDescriptor(
        name="x",
        description="x",
        input_schema={},
        fn=lambda: 0,
        shape_result=lambda v: {"v": v},
    )
    reg.register(desc)
    with pytest.raises(ValueError):
        reg.register(desc)


def test_get_unknown_raises_keyerror():
    with pytest.raises(KeyError):
        ToolRegistry().get("nope")


def test_list_returns_all_registered():
    reg = ToolRegistry()
    for name in ("a", "b", "c"):
        reg.register(
            ToolDescriptor(
                name=name,
                description="",
                input_schema={},
                fn=lambda: 0,
                shape_result=lambda v: {},
            )
        )
    assert {d.name for d in reg.list()} == {"a", "b", "c"}


def test_call_invokes_fn_and_shapes_result():
    reg = ToolRegistry()
    reg.register(
        ToolDescriptor(
            name="echo",
            description="Echo input.",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
            },
            fn=lambda text: text.upper(),
            shape_result=lambda v: {"echoed": v},
        )
    )
    assert reg.call("echo", {"text": "hello"}) == {"echoed": "HELLO"}


def test_call_filters_unknown_args():
    reg = ToolRegistry()
    reg.register(
        ToolDescriptor(
            name="strict",
            description="x",
            input_schema={
                "type": "object",
                "properties": {"a": {"type": "string"}},
            },
            fn=lambda a: a,
            shape_result=lambda v: {"v": v},
        )
    )
    # Model invents 'b'; registry strips it before invocation.
    assert reg.call("strict", {"a": "ok", "b": "ignored"}) == {"v": "ok"}


def test_default_registry_exposes_seven_tools():
    reg = build_default_registry()
    names = {d.name for d in reg.list()}
    assert names == {
        "eval_run",
        "improve_run",
        "improve_list",
        "improve_show",
        "improve_diff",
        "improve_accept",
        "deploy",
    }


def test_default_registry_descriptions_are_nonempty():
    """Hand-written descriptions are required for tool-call quality."""
    for desc in build_default_registry().list():
        assert len(desc.description) > 20, f"{desc.name} description too short"


def test_default_registry_schemas_are_object_shaped():
    for desc in build_default_registry().list():
        assert desc.input_schema.get("type") == "object"
        assert "properties" in desc.input_schema


def test_call_auto_injects_on_event():
    """The registry injects a no-op ``on_event`` for tools that require one.

    The model never sees ``on_event`` — it's a side-channel for the
    in-process command's progress stream. The registry must auto-inject
    a no-op so domain-arg-only tool calls succeed.
    """
    captured: list[dict] = []

    def fn(*, message: str, on_event):
        # Prove the injected callback is actually callable.
        on_event({"event": "ping", "message": message})
        captured.append({"message": message})
        return {"ok": True}

    reg = ToolRegistry()
    reg.register(
        ToolDescriptor(
            name="pinger",
            description="Send a ping; tests on_event injection.",
            input_schema={
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
            fn=fn,
            shape_result=lambda v: v,
        )
    )

    # No on_event supplied — registry must inject a no-op.
    result = reg.call("pinger", {"message": "hi"})
    assert result == {"ok": True}
    assert captured == [{"message": "hi"}]


def test_default_shape_result_handles_dataclass_with_tuples():
    """Tuples (e.g. ``warnings: tuple[str, ...]``) must serialize as lists."""

    @dataclass(frozen=True)
    class Sample:
        run_id: str
        warnings: tuple[str, ...]

    def fn():
        return Sample(run_id="r1", warnings=("a", "b"))

    # Use the registry's default shaper (built into build_default_registry):
    # we replicate the contract here so the test stays unit-scoped.
    from cli.workbench_app.tool_registry import dataclass_to_jsonsafe

    shaped = dataclass_to_jsonsafe(fn())
    assert shaped == {"run_id": "r1", "warnings": ["a", "b"]}
