"""Tests for cli.workbench_app.conversation_bridge.

Covers the contract from the R7 Slice B plan, task B.6:

- record_user_turn → user message at the next position.
- record_assistant_turn → one assistant message + one tool_call row per
  ToolExecution, with the right status / payload mapping for
  succeeded / failed / denied tool calls.
- arguments are recorded as ``{}`` for now — see the bridge docstring
  for the limitation.
- long display text is truncated.
- ordering is preserved by ``started_at``.
"""

from __future__ import annotations

import pytest

from cli.tools.base import PermissionDecision, ToolResult
from cli.tools.executor import ToolExecution
from cli.llm.types import OrchestratorResult
from cli.workbench_app.conversation_bridge import ConversationBridge, _truncate
from cli.workbench_app.conversation_store import ConversationStore
from cli.tools.rendering import StructuredDiffRenderable
from cli.tools.rendering import PERSISTED_RENDER_TEXT_MAX_CHARS


# ----- Helpers ------------------------------------------------------------


def _bridge(tmp_path):
    store = ConversationStore(tmp_path / "conv.db")
    conv = store.create_conversation(workspace_root="/ws", model="opus")
    return store, conv, ConversationBridge(store, conv.id)


# ----- record_user_turn ---------------------------------------------------


def test_record_user_turn_creates_message(tmp_path):
    store, conv, bridge = _bridge(tmp_path)
    msg = bridge.record_user_turn("hi")
    assert msg.position == 0
    assert msg.content == "hi"

    fetched = store.get_conversation(conv.id)
    assert len(fetched.messages) == 1
    assert fetched.messages[0].id == msg.id


def test_record_user_turn_assigns_user_role(tmp_path):
    _store, _conv, bridge = _bridge(tmp_path)
    msg = bridge.record_user_turn("hi")
    assert msg.role == "user"


# ----- record_assistant_turn (no tools) -----------------------------------


def test_record_assistant_turn_creates_assistant_message(tmp_path):
    store, conv, bridge = _bridge(tmp_path)
    result = OrchestratorResult(assistant_text="hello", tool_executions=[])
    msg = bridge.record_assistant_turn(result)

    fetched = store.get_conversation(conv.id)
    assert len(fetched.messages) == 1
    assert fetched.messages[0].id == msg.id
    assert fetched.messages[0].role == "assistant"
    assert fetched.messages[0].content == "hello"
    assert fetched.messages[0].position == 0
    assert fetched.messages[0].tool_calls == []


def test_record_assistant_turn_with_no_text_records_empty_string(tmp_path):
    _store, conv, bridge = _bridge(tmp_path)
    # assistant_text="" — the dataclass requires the field, but the
    # bridge must defensively coerce missing/None text into "" without
    # crashing.
    result = OrchestratorResult(assistant_text="", tool_executions=[])
    msg = bridge.record_assistant_turn(result)
    assert msg.content == ""


# ----- record_assistant_turn (tool calls) ---------------------------------


def test_record_assistant_turn_records_succeeded_tool_call(tmp_path):
    store, conv, bridge = _bridge(tmp_path)
    execution = ToolExecution(
        tool_name="EvalRun",
        decision=PermissionDecision.ALLOW,
        result=ToolResult(ok=True, content="ok", display="eval ran"),
    )
    result = OrchestratorResult(
        assistant_text="running eval",
        tool_executions=[execution],
    )
    bridge.record_assistant_turn(result)

    fetched = store.get_conversation(conv.id)
    assert len(fetched.messages) == 1
    msg = fetched.messages[0]
    assert len(msg.tool_calls) == 1
    tc = msg.tool_calls[0]
    assert tc.tool_name == "EvalRun"
    assert tc.status == "succeeded"
    assert tc.result == {"display": "eval ran"}
    assert tc.arguments == {}


def test_record_assistant_turn_persists_renderable_payload(tmp_path):
    store, conv, bridge = _bridge(tmp_path)
    renderable = StructuredDiffRenderable(
        old="old\n",
        new="new\n",
        file_path="demo.py",
        language="python",
    )
    execution = ToolExecution(
        tool_name="FileEdit",
        decision=PermissionDecision.ALLOW,
        result=ToolResult(
            ok=True,
            content="ok",
            display="diff text",
            metadata={"renderable": renderable.to_payload()},
        ),
    )

    bridge.record_assistant_turn(
        OrchestratorResult(assistant_text="edited", tool_executions=[execution])
    )

    fetched = store.get_conversation(conv.id)
    payload = fetched.messages[0].tool_calls[0].result
    assert payload is not None
    assert payload["display"] == "diff text"
    assert payload["renderable"]["kind"] == "structured_diff"
    assert payload["renderable"]["file_path"] == "demo.py"


def test_record_assistant_turn_caps_persisted_renderable_text(tmp_path):
    store, conv, bridge = _bridge(tmp_path)
    long_text = "x" * (PERSISTED_RENDER_TEXT_MAX_CHARS + 25)
    renderable = StructuredDiffRenderable(
        old=long_text,
        new=long_text,
        file_path="demo.py",
        language="python",
    )
    execution = ToolExecution(
        tool_name="FileEdit",
        decision=PermissionDecision.ALLOW,
        result=ToolResult(
            ok=True,
            content="ok",
            display="diff text",
            metadata={"renderable": renderable.to_payload()},
        ),
    )

    bridge.record_assistant_turn(
        OrchestratorResult(assistant_text="edited", tool_executions=[execution])
    )

    fetched = store.get_conversation(conv.id)
    payload = fetched.messages[0].tool_calls[0].result
    assert payload is not None
    assert len(payload["renderable"]["old"]) == PERSISTED_RENDER_TEXT_MAX_CHARS
    assert len(payload["renderable"]["new"]) == PERSISTED_RENDER_TEXT_MAX_CHARS
    assert payload["renderable"]["truncated"] is True


def test_record_assistant_turn_records_failed_tool_call(tmp_path):
    store, conv, bridge = _bridge(tmp_path)
    execution = ToolExecution(
        tool_name="EvalRun",
        decision=PermissionDecision.ALLOW,
        result=ToolResult(ok=False, content="boom", display="boom"),
    )
    result = OrchestratorResult(
        assistant_text="failed", tool_executions=[execution]
    )
    bridge.record_assistant_turn(result)

    fetched = store.get_conversation(conv.id)
    tc = fetched.messages[0].tool_calls[0]
    assert tc.status == "failed"
    assert tc.result == {"display": "boom"}


def test_record_assistant_turn_records_denied_tool_call(tmp_path):
    store, conv, bridge = _bridge(tmp_path)
    execution = ToolExecution(
        tool_name="Deploy",
        decision=PermissionDecision.DENY,
        result=None,
        denial_reason="user_denied",
    )
    result = OrchestratorResult(
        assistant_text="denied", tool_executions=[execution]
    )
    bridge.record_assistant_turn(result)

    fetched = store.get_conversation(conv.id)
    tc = fetched.messages[0].tool_calls[0]
    assert tc.tool_name == "Deploy"
    assert tc.status == "failed"
    assert tc.result == {"denied": True, "denial_reason": "user_denied"}


def test_record_assistant_turn_records_multiple_tools_in_order(tmp_path):
    store, conv, bridge = _bridge(tmp_path)
    e1 = ToolExecution(
        tool_name="EvalRun",
        decision=PermissionDecision.ALLOW,
        result=ToolResult(ok=True, content="r1", display="first"),
    )
    e2 = ToolExecution(
        tool_name="Deploy",
        decision=PermissionDecision.ALLOW,
        result=ToolResult(ok=True, content="r2", display="second"),
    )
    result = OrchestratorResult(
        assistant_text="two tools",
        tool_executions=[e1, e2],
    )
    bridge.record_assistant_turn(result)

    fetched = store.get_conversation(conv.id)
    tcs = fetched.messages[0].tool_calls
    assert len(tcs) == 2
    # Ordering: get_conversation orders by started_at ASC.
    assert tcs[0].tool_name == "EvalRun"
    assert tcs[1].tool_name == "Deploy"
    assert tcs[0].started_at <= tcs[1].started_at


# ----- Truncation ---------------------------------------------------------


def test_truncates_long_display_text(tmp_path):
    store, conv, bridge = _bridge(tmp_path)
    long_text = "x" * 5000
    execution = ToolExecution(
        tool_name="EvalRun",
        decision=PermissionDecision.ALLOW,
        result=ToolResult(ok=True, content="ok", display=long_text),
    )
    bridge.record_assistant_turn(
        OrchestratorResult(assistant_text="t", tool_executions=[execution])
    )

    fetched = store.get_conversation(conv.id)
    display = fetched.messages[0].tool_calls[0].result["display"]
    # Cap is 4000 chars + a short truncation marker.
    assert len(display) <= 4100
    assert display.startswith("x" * 4000)
    assert "truncated" in display


# ----- Mixed turns --------------------------------------------------------


def test_user_then_assistant_positions_advance(tmp_path):
    store, conv, bridge = _bridge(tmp_path)
    bridge.record_user_turn("hi")
    bridge.record_assistant_turn(
        OrchestratorResult(assistant_text="hello back", tool_executions=[])
    )

    fetched = store.get_conversation(conv.id)
    assert len(fetched.messages) == 2
    assert fetched.messages[0].position == 0
    assert fetched.messages[0].role == "user"
    assert fetched.messages[1].position == 1
    assert fetched.messages[1].role == "assistant"


# ----- Limitations doc-test ----------------------------------------------


def test_arguments_field_is_empty_dict_with_documentation_note(tmp_path):
    """ToolExecution doesn't carry tool_input today — see the bridge
    docstring. The recorded ``arguments`` must therefore be an empty
    dict so future readers find the limitation rather than mistake an
    accidental drop for a bug."""
    store, conv, bridge = _bridge(tmp_path)
    execution = ToolExecution(
        tool_name="EvalRun",
        decision=PermissionDecision.ALLOW,
        result=ToolResult(ok=True, content="ok", display="ran"),
    )
    bridge.record_assistant_turn(
        OrchestratorResult(assistant_text="t", tool_executions=[execution])
    )

    fetched = store.get_conversation(conv.id)
    assert fetched.messages[0].tool_calls[0].arguments == {}

    # And the bridge module docstring should warn future contributors.
    from cli.workbench_app import conversation_bridge as cb
    assert "tool_input" in (cb.ConversationBridge.__doc__ or "") + (
        cb.ConversationBridge.record_assistant_turn.__doc__ or ""
    )


# ----- _truncate helper ---------------------------------------------------


def test_truncate_helper_passes_short_text_unchanged():
    assert _truncate("hi", 4000) == "hi"
    assert _truncate(None, 4000) is None
    # Boundary: exactly at the limit.
    s = "x" * 4000
    assert _truncate(s, 4000) == s
    # One past the limit truncates.
    s = "x" * 4001
    out = _truncate(s, 4000)
    assert out is not None
    assert out.startswith("x" * 4000)
    assert "truncated" in out
