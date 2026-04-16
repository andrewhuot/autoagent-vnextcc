"""Tests for cli.workbench_app.conversation_store.

Covers the contract from the R7.3 plan:
- create + retrieve a conversation
- 5-message round trip with positions preserved
- tool call lifecycle: start (pending) -> finish (succeeded/failed)
- crash safety: pending tool calls flipped to interrupted on fresh open
- list_recent orders by updated_at DESC
- get_conversation raises KeyError for unknown id
- finish_tool_call rejects non-terminal status
- conversation updated_at advances on every appended message
"""

from __future__ import annotations

import time

import pytest

from cli.workbench_app.conversation_store import (
    Conversation,
    ConversationStore,
    Message,
    ToolCall,
)


# ----- ID shape helpers ---------------------------------------------------


def test_create_conversation_returns_conversation_with_conv_id_prefix(tmp_path):
    store = ConversationStore(tmp_path / "convs.db")
    conv = store.create_conversation(workspace_root="/ws", model="opus")
    assert isinstance(conv, Conversation)
    assert conv.id.startswith("conv_")
    assert conv.workspace_root == "/ws"
    assert conv.model == "opus"
    # created_at and updated_at start out equal
    assert conv.created_at == conv.updated_at


def test_create_conversation_persists_so_get_conversation_returns_it(tmp_path):
    store = ConversationStore(tmp_path / "convs.db")
    conv = store.create_conversation(workspace_root="/ws", model="opus")
    fetched = store.get_conversation(conv.id)
    assert fetched.id == conv.id
    assert fetched.workspace_root == "/ws"
    assert fetched.model == "opus"
    assert fetched.messages == []


# ----- Round trip & positions --------------------------------------------


def test_five_message_round_trip_preserves_positions(tmp_path):
    store = ConversationStore(tmp_path / "convs.db")
    conv = store.create_conversation()
    roles = ["user", "assistant", "user", "assistant", "user"]
    contents = [f"msg-{i}" for i in range(5)]
    appended = []
    for role, content in zip(roles, contents):
        m = store.append_message(
            conversation_id=conv.id, role=role, content=content
        )
        appended.append(m)

    # Each appended message has expected position
    assert [m.position for m in appended] == [0, 1, 2, 3, 4]
    assert all(m.id.startswith("msg_") for m in appended)

    fetched = store.get_conversation(conv.id)
    assert len(fetched.messages) == 5
    assert [m.position for m in fetched.messages] == [0, 1, 2, 3, 4]
    assert [m.role for m in fetched.messages] == roles
    assert [m.content for m in fetched.messages] == contents


def test_positions_are_per_conversation(tmp_path):
    """Two parallel conversations each start their own position sequence."""
    store = ConversationStore(tmp_path / "convs.db")
    a = store.create_conversation()
    b = store.create_conversation()
    store.append_message(conversation_id=a.id, role="user", content="a0")
    store.append_message(conversation_id=b.id, role="user", content="b0")
    store.append_message(conversation_id=a.id, role="user", content="a1")

    fa = store.get_conversation(a.id)
    fb = store.get_conversation(b.id)
    assert [m.position for m in fa.messages] == [0, 1]
    assert [m.position for m in fb.messages] == [0]


# ----- updated_at progression --------------------------------------------


def test_appending_message_advances_conversation_updated_at(tmp_path):
    store = ConversationStore(tmp_path / "convs.db")
    conv = store.create_conversation()
    initial_updated = store.get_conversation(conv.id).updated_at

    # Sleep slightly to overcome clock resolution. ISO-format strings
    # compare lexically so this is enough.
    time.sleep(0.005)
    m1 = store.append_message(
        conversation_id=conv.id, role="user", content="hi"
    )
    after_first = store.get_conversation(conv.id).updated_at
    assert after_first > initial_updated
    assert m1.created_at >= initial_updated

    time.sleep(0.005)
    store.append_message(
        conversation_id=conv.id, role="assistant", content="hello"
    )
    after_second = store.get_conversation(conv.id).updated_at
    assert after_second > after_first


# ----- Tool call lifecycle -----------------------------------------------


def test_start_tool_call_records_pending_call_with_tc_id_prefix(tmp_path):
    store = ConversationStore(tmp_path / "convs.db")
    conv = store.create_conversation()
    msg = store.append_message(
        conversation_id=conv.id, role="assistant", content="calling tool"
    )

    tc = store.start_tool_call(
        message_id=msg.id, tool_name="deploy", arguments={"target": "prod"}
    )
    assert isinstance(tc, ToolCall)
    assert tc.id.startswith("tc_")
    assert tc.message_id == msg.id
    assert tc.tool_name == "deploy"
    assert tc.arguments == {"target": "prod"}
    assert tc.status == "pending"
    assert tc.result is None
    assert tc.finished_at is None

    fetched = store.get_conversation(conv.id)
    [persisted] = fetched.messages[0].tool_calls
    assert persisted.status == "pending"
    assert persisted.arguments == {"target": "prod"}
    assert persisted.result is None
    assert persisted.finished_at is None


def test_finish_tool_call_succeeded_sets_status_and_result(tmp_path):
    store = ConversationStore(tmp_path / "convs.db")
    conv = store.create_conversation()
    msg = store.append_message(
        conversation_id=conv.id, role="assistant", content="x"
    )
    tc = store.start_tool_call(
        message_id=msg.id, tool_name="improve_list", arguments={}
    )
    store.finish_tool_call(
        tool_call_id=tc.id, status="succeeded", result={"runs": []}
    )

    fetched = store.get_conversation(conv.id)
    [persisted] = fetched.messages[0].tool_calls
    assert persisted.status == "succeeded"
    assert persisted.result == {"runs": []}
    assert persisted.finished_at is not None


def test_finish_tool_call_failed_allows_null_result(tmp_path):
    store = ConversationStore(tmp_path / "convs.db")
    conv = store.create_conversation()
    msg = store.append_message(
        conversation_id=conv.id, role="assistant", content="x"
    )
    tc = store.start_tool_call(
        message_id=msg.id, tool_name="deploy", arguments={}
    )
    store.finish_tool_call(tool_call_id=tc.id, status="failed", result=None)

    fetched = store.get_conversation(conv.id)
    [persisted] = fetched.messages[0].tool_calls
    assert persisted.status == "failed"
    assert persisted.result is None
    assert persisted.finished_at is not None


@pytest.mark.parametrize(
    "bad_status", ["pending", "running", "", "Succeeded", "DONE"]
)
def test_finish_tool_call_rejects_non_terminal_status(tmp_path, bad_status):
    store = ConversationStore(tmp_path / "convs.db")
    conv = store.create_conversation()
    msg = store.append_message(
        conversation_id=conv.id, role="assistant", content="x"
    )
    tc = store.start_tool_call(
        message_id=msg.id, tool_name="deploy", arguments={}
    )
    with pytest.raises(ValueError):
        store.finish_tool_call(
            tool_call_id=tc.id, status=bad_status, result=None
        )


# ----- Crash safety -------------------------------------------------------


def test_pending_tool_calls_flipped_to_interrupted_on_fresh_open(tmp_path):
    """Critical invariant: any tool_call left pending in the DB is from
    a previous Workbench process that was killed mid-call. A freshly
    constructed ConversationStore against the same DB must mark them
    interrupted with a non-null finished_at, so the resume UI doesn't
    pretend a killed deploy succeeded."""
    db_path = tmp_path / "convs.db"

    store_a = ConversationStore(db_path)
    conv = store_a.create_conversation()
    msg = store_a.append_message(
        conversation_id=conv.id, role="assistant", content="calling deploy"
    )
    tc = store_a.start_tool_call(
        message_id=msg.id, tool_name="deploy", arguments={"target": "prod"}
    )
    # Sanity: still pending and unfinished
    pre = store_a.get_conversation(conv.id).messages[0].tool_calls[0]
    assert pre.status == "pending"
    assert pre.finished_at is None

    # Throw away the store object — simulate Workbench crash.
    del store_a

    # Fresh store against the same DB path runs crash-safety sweep.
    store_b = ConversationStore(db_path)
    after = store_b.get_conversation(conv.id).messages[0].tool_calls[0]
    assert after.id == tc.id
    assert after.status == "interrupted"
    assert after.finished_at is not None


def test_crash_sweep_leaves_terminal_calls_alone(tmp_path):
    """Already-terminal tool calls must not be touched by the crash
    sweep on next open — only pending ones get flipped."""
    db_path = tmp_path / "convs.db"

    store_a = ConversationStore(db_path)
    conv = store_a.create_conversation()
    msg = store_a.append_message(
        conversation_id=conv.id, role="assistant", content="x"
    )
    tc_done = store_a.start_tool_call(
        message_id=msg.id, tool_name="improve_list", arguments={}
    )
    store_a.finish_tool_call(
        tool_call_id=tc_done.id, status="succeeded", result={"ok": True}
    )
    tc_failed = store_a.start_tool_call(
        message_id=msg.id, tool_name="deploy", arguments={}
    )
    store_a.finish_tool_call(
        tool_call_id=tc_failed.id, status="failed", result=None
    )
    finished_at_before = (
        store_a.get_conversation(conv.id).messages[0].tool_calls
    )
    succeeded_finished = next(
        t for t in finished_at_before if t.id == tc_done.id
    ).finished_at
    failed_finished = next(
        t for t in finished_at_before if t.id == tc_failed.id
    ).finished_at

    del store_a

    store_b = ConversationStore(db_path)
    after = store_b.get_conversation(conv.id).messages[0].tool_calls
    by_id = {t.id: t for t in after}
    assert by_id[tc_done.id].status == "succeeded"
    assert by_id[tc_done.id].result == {"ok": True}
    assert by_id[tc_done.id].finished_at == succeeded_finished
    assert by_id[tc_failed.id].status == "failed"
    assert by_id[tc_failed.id].result is None
    assert by_id[tc_failed.id].finished_at == failed_finished


# ----- get_conversation error ---------------------------------------------


def test_get_conversation_raises_keyerror_for_unknown_id(tmp_path):
    store = ConversationStore(tmp_path / "convs.db")
    with pytest.raises(KeyError):
        store.get_conversation("conv_doesnotexist")


# ----- list_recent --------------------------------------------------------


def test_list_recent_orders_by_updated_at_desc(tmp_path):
    store = ConversationStore(tmp_path / "convs.db")
    a = store.create_conversation(model="a")
    time.sleep(0.005)
    b = store.create_conversation(model="b")
    time.sleep(0.005)
    c = store.create_conversation(model="c")

    # Touch `a` last so it should bubble to the top.
    time.sleep(0.005)
    store.append_message(conversation_id=a.id, role="user", content="bump")

    recents = store.list_recent()
    ids = [r.id for r in recents]
    # `a` was just updated, then `c`, then `b`.
    assert ids[0] == a.id
    assert ids[1] == c.id
    assert ids[2] == b.id


def test_list_recent_respects_limit(tmp_path):
    store = ConversationStore(tmp_path / "convs.db")
    for _ in range(5):
        store.create_conversation()
        time.sleep(0.001)
    assert len(store.list_recent(limit=3)) == 3
    assert len(store.list_recent(limit=10)) == 5


def test_list_recent_returns_empty_on_empty_db(tmp_path):
    store = ConversationStore(tmp_path / "convs.db")
    assert store.list_recent() == []


# ----- Hermetic isolation between tests ----------------------------------


def test_two_stores_with_different_db_paths_do_not_share_state(tmp_path):
    store_a = ConversationStore(tmp_path / "a.db")
    store_b = ConversationStore(tmp_path / "b.db")
    store_a.create_conversation(model="from-a")
    assert store_a.list_recent() != []
    assert store_b.list_recent() == []
