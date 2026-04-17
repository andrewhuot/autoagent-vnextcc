"""Tests for ``cli.workbench_app.conversation_resume`` (R7.C.6 part A).

These cover the pure helpers that:

- Hydrate a persisted :class:`Conversation` into a list of
  :class:`TurnMessage` instances ready to plug into
  ``LLMOrchestrator.messages``.
- Render a one-line resume hint when the most recent conversation has
  any tool_call rows in ``interrupted`` status (already tagged on store
  load by R7.3).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cli.llm.types import TurnMessage
from cli.workbench_app.conversation_resume import (
    TOOL_RESULT_RESUME_LIMIT,
    format_resume_hint,
    load_history,
)
from cli.workbench_app.conversation_store import ConversationStore


@pytest.fixture
def store(tmp_path: Path) -> ConversationStore:
    return ConversationStore(tmp_path / "conv.db")


def test_load_history_yields_turn_messages_in_position_order(
    store: ConversationStore,
) -> None:
    convo = store.create_conversation()
    store.append_message(conversation_id=convo.id, role="user", content="hi")
    store.append_message(conversation_id=convo.id, role="assistant", content="hello")
    store.append_message(conversation_id=convo.id, role="user", content="thanks")

    history = load_history(store, convo.id)

    assert [m.role for m in history] == ["user", "assistant", "user"]
    assert [m.content for m in history] == ["hi", "hello", "thanks"]
    assert all(isinstance(m, TurnMessage) for m in history)


def test_load_history_handles_empty_conversation(store: ConversationStore) -> None:
    convo = store.create_conversation()
    history = load_history(store, convo.id)
    assert history == []


def test_load_history_summarises_tool_calls_inline_in_assistant_message(
    store: ConversationStore,
) -> None:
    convo = store.create_conversation()
    msg = store.append_message(
        conversation_id=convo.id, role="assistant", content="working on it"
    )
    tc = store.start_tool_call(
        message_id=msg.id, tool_name="Bash", arguments={"cmd": "ls"}
    )
    store.finish_tool_call(
        tool_call_id=tc.id, status="succeeded", result={"display": "x12"}
    )

    history = load_history(store, convo.id)

    assert len(history) == 1
    rendered = history[0].content
    assert "working on it" in rendered
    assert "[tool: Bash → succeeded] x12" in rendered


def test_load_history_truncates_long_tool_result_display(
    store: ConversationStore,
) -> None:
    convo = store.create_conversation()
    msg = store.append_message(
        conversation_id=convo.id, role="assistant", content=""
    )
    tc = store.start_tool_call(
        message_id=msg.id, tool_name="Bash", arguments={}
    )
    long_display = "z" * 1000
    store.finish_tool_call(
        tool_call_id=tc.id, status="succeeded", result={"display": long_display}
    )

    history = load_history(store, convo.id)

    rendered = history[0].content
    # Sanity: prefix is present, the truncation marker is present, and the
    # rendered content is roughly bounded by TOOL_RESULT_RESUME_LIMIT plus
    # the small "[tool: Bash → succeeded] " prefix and " [...]" suffix.
    assert "[tool: Bash → succeeded]" in rendered
    assert "[...]" in rendered
    assert len(rendered) <= TOOL_RESULT_RESUME_LIMIT + 64


def test_load_history_preserves_user_message_content_unchanged(
    store: ConversationStore,
) -> None:
    convo = store.create_conversation()
    store.append_message(
        conversation_id=convo.id, role="user", content="exact: please don't reword"
    )

    history = load_history(store, convo.id)

    assert history[0].role == "user"
    assert history[0].content == "exact: please don't reword"


def test_format_resume_hint_returns_none_when_no_interruptions(
    store: ConversationStore,
) -> None:
    convo = store.create_conversation()
    msg = store.append_message(
        conversation_id=convo.id, role="assistant", content=""
    )
    tc = store.start_tool_call(message_id=msg.id, tool_name="Bash", arguments={})
    store.finish_tool_call(tool_call_id=tc.id, status="succeeded", result=None)

    full = store.get_conversation(convo.id)
    assert format_resume_hint(full) is None


def test_format_resume_hint_returns_message_when_interrupted_calls_exist(
    tmp_path: Path,
) -> None:
    # Seed: one assistant message with two tool_calls; one finished cleanly,
    # one left pending. Reopen the store so R7.3 flips pending → interrupted.
    db_path = tmp_path / "conv.db"
    store = ConversationStore(db_path)
    convo = store.create_conversation()
    msg = store.append_message(
        conversation_id=convo.id, role="assistant", content=""
    )
    finished = store.start_tool_call(
        message_id=msg.id, tool_name="Bash", arguments={}
    )
    store.finish_tool_call(tool_call_id=finished.id, status="succeeded", result=None)
    # Leave this one pending.
    store.start_tool_call(message_id=msg.id, tool_name="Bash", arguments={})

    # Reopen — flips pending → interrupted.
    store2 = ConversationStore(db_path)
    full = store2.get_conversation(convo.id)
    hint = format_resume_hint(full)

    assert hint is not None
    assert convo.id in hint
    assert "1 pending tool call" in hint


def test_format_resume_hint_mentions_resume_command(tmp_path: Path) -> None:
    db_path = tmp_path / "conv.db"
    store = ConversationStore(db_path)
    convo = store.create_conversation()
    msg = store.append_message(
        conversation_id=convo.id, role="assistant", content=""
    )
    store.start_tool_call(message_id=msg.id, tool_name="Bash", arguments={})

    store2 = ConversationStore(db_path)
    full = store2.get_conversation(convo.id)
    hint = format_resume_hint(full)

    assert hint is not None
    assert "/resume " in hint


def test_format_resume_hint_pluralises_when_many(tmp_path: Path) -> None:
    db_path = tmp_path / "conv.db"
    store = ConversationStore(db_path)
    convo = store.create_conversation()
    msg = store.append_message(
        conversation_id=convo.id, role="assistant", content=""
    )
    for _ in range(3):
        store.start_tool_call(message_id=msg.id, tool_name="Bash", arguments={})

    store2 = ConversationStore(db_path)
    full = store2.get_conversation(convo.id)
    hint = format_resume_hint(full)

    assert hint is not None
    assert "3 pending tool calls" in hint
