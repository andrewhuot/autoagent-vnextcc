"""Tests for the ``relevant_memories`` kwarg on :func:`build_system_prompt`.

Slice B of the P2 memory plan (P2.T8). The contract is:

- Default ``None`` → zero byte diff vs. prior output.
- Empty sequence → zero byte diff.
- Truthy sequence → ``## Relevant memories`` section rendered, one
  ``- <name>: <description>`` bullet per memory, in input order, with
  a blank line after the section. Placed before the injection guard,
  which must remain the final section.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cli.memory import Memory, MemoryType
from cli.workbench_app.system_prompt import (
    PROMPT_INJECTION_GUARD,
    build_system_prompt,
)
from cli.workbench_app.tool_registry import ToolDescriptor, ToolRegistry


def _noop(**_kwargs):  # pragma: no cover - never called
    return {}


def _shape(value):  # pragma: no cover - never called
    return {"value": value}


def _empty_registry() -> ToolRegistry:
    return ToolRegistry()


def _two_tool_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        ToolDescriptor(
            name="alpha_tool",
            description="Run alpha — a read-only example tool.",
            input_schema={"type": "object", "properties": {}},
            fn=_noop,
            shape_result=_shape,
        )
    )
    reg.register(
        ToolDescriptor(
            name="beta_tool",
            description="Run beta — a write example tool.",
            input_schema={"type": "object", "properties": {}},
            fn=_noop,
            shape_result=_shape,
        )
    )
    return reg


def _m(name: str, description: str) -> Memory:
    """Build a realistic ``Memory`` for tests."""
    return Memory(
        name=name,
        type=MemoryType.USER,
        description=description,
        body=f"# {name}\n\n{description}\n",
        created_at=datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc),
        source_session_id="sess-abc",
        tags=("unit-test",),
    )


def test_default_kwarg_preserves_snapshot():
    """Omitting the kwarg must produce the same bytes as passing None."""
    old = build_system_prompt(
        workspace_name="ws",
        agent_card_path=None,
        registry=_empty_registry(),
    )
    new = build_system_prompt(
        workspace_name="ws",
        agent_card_path=None,
        registry=_empty_registry(),
        relevant_memories=None,
    )
    assert old == new
    assert "## Relevant memories" not in old


def test_empty_sequence_renders_no_section():
    out = build_system_prompt(
        workspace_name="ws",
        agent_card_path=None,
        registry=_empty_registry(),
        relevant_memories=[],
    )
    assert "## Relevant memories" not in out
    # Also byte-stable vs. the None case.
    baseline = build_system_prompt(
        workspace_name="ws",
        agent_card_path=None,
        registry=_empty_registry(),
    )
    assert out == baseline


def test_injects_relevant_memories_section():
    mems = [
        _m("prefer-terse", "be concise"),
        _m("use-uv", "uv is the package manager"),
    ]
    out = build_system_prompt(
        workspace_name="ws",
        agent_card_path=None,
        registry=_empty_registry(),
        relevant_memories=mems,
    )
    assert "## Relevant memories" in out
    assert "- prefer-terse: be concise" in out
    assert "- use-uv: uv is the package manager" in out


def test_single_memory_renders_correctly():
    mems = [_m("only-one", "the single fact")]
    out = build_system_prompt(
        workspace_name="ws",
        agent_card_path=None,
        registry=_empty_registry(),
        relevant_memories=mems,
    )
    assert "## Relevant memories\n- only-one: the single fact\n" in out


def test_memory_with_empty_description_still_renders():
    """Empty description must not crash — emits ``- <name>: `` with trailing space."""
    mems = [_m("no-desc", "")]
    out = build_system_prompt(
        workspace_name="ws",
        agent_card_path=None,
        registry=_empty_registry(),
        relevant_memories=mems,
    )
    assert "## Relevant memories" in out
    assert "- no-desc: " in out


def test_relevant_memories_kwarg_is_keyword_only():
    """Passing positionally must raise TypeError — the signature is keyword-only."""
    with pytest.raises(TypeError):
        build_system_prompt(  # type: ignore[misc]
            "ws",
            None,
            _empty_registry(),
            [_m("x", "y")],
        )


def test_memory_order_matches_input():
    mems = [
        _m("first", "one"),
        _m("second", "two"),
        _m("third", "three"),
    ]
    out = build_system_prompt(
        workspace_name="ws",
        agent_card_path=None,
        registry=_empty_registry(),
        relevant_memories=mems,
    )
    i1 = out.index("- first: one")
    i2 = out.index("- second: two")
    i3 = out.index("- third: three")
    assert i1 < i2 < i3


def test_section_appears_before_injection_guard():
    """Guard must remain the final security control — memories render above it."""
    mems = [_m("a", "first")]
    out = build_system_prompt(
        workspace_name="ws",
        agent_card_path=None,
        registry=_two_tool_registry(),
        relevant_memories=mems,
    )
    memories_idx = out.index("## Relevant memories")
    guard_idx = out.index(PROMPT_INJECTION_GUARD)
    reading_idx = out.index("## Reading tool output safely")
    assert memories_idx < reading_idx < guard_idx
    # Guard text is still present verbatim.
    assert out.endswith(PROMPT_INJECTION_GUARD)
