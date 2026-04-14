"""Tests for the T07 streaming transcript pane (`cli/workbench_app/transcript.py`)."""

from __future__ import annotations

import click
import pytest

from cli.workbench_app.transcript import (
    Transcript,
    TranscriptEntry,
    _redact,
    format_entry,
)


# ---------------------------------------------------------------------------
# format_entry — pure rendering
# ---------------------------------------------------------------------------


def test_format_entry_user_gets_cyan_bold_prefix():
    entry = TranscriptEntry(role="user", content="hello")
    rendered = format_entry(entry, color=True)
    assert "> hello" in click.unstyle(rendered)
    # Styled output must actually contain ANSI escapes when color=True.
    assert rendered != click.unstyle(rendered)


def test_format_entry_system_is_dim():
    entry = TranscriptEntry(role="system", content="info line")
    rendered = format_entry(entry, color=True)
    assert click.unstyle(rendered) == "info line"
    # Dim sequence — ANSI 2.
    assert "\x1b[2m" in rendered


def test_format_entry_error_is_red_bold_with_bang_prefix():
    entry = TranscriptEntry(role="error", content="boom")
    rendered = format_entry(entry, color=True)
    assert click.unstyle(rendered) == "! boom"
    assert "\x1b[31m" in rendered  # red


def test_format_entry_warning_is_yellow():
    entry = TranscriptEntry(role="warning", content="careful")
    rendered = format_entry(entry, color=True)
    assert click.unstyle(rendered).startswith("⚠ ")
    assert "careful" in click.unstyle(rendered)
    assert "\x1b[33m" in rendered  # yellow


def test_format_entry_meta_is_dim_without_prefix():
    entry = TranscriptEntry(role="meta", content="x=1")
    rendered = format_entry(entry, color=True)
    assert click.unstyle(rendered) == "x=1"
    assert "\x1b[2m" in rendered


def test_format_entry_tool_passes_through_existing_style():
    pre_styled = click.style("[task] running", fg="green")
    entry = TranscriptEntry(role="tool", content=pre_styled, event_name="task.started")
    rendered = format_entry(entry, color=True)
    assert rendered == pre_styled  # no additional wrapping


def test_format_entry_assistant_has_no_prefix():
    entry = TranscriptEntry(role="assistant", content="answer")
    rendered = format_entry(entry, color=True)
    assert rendered == "answer"


def test_format_entry_color_false_strips_ansi_escapes():
    entry = TranscriptEntry(role="user", content="hi")
    rendered = format_entry(entry, color=False)
    assert rendered == "> hi"
    assert "\x1b[" not in rendered


def test_format_entry_color_false_strips_tool_styling_too():
    pre_styled = click.style("[run] done", fg="green", bold=True)
    entry = TranscriptEntry(role="tool", content=pre_styled)
    rendered = format_entry(entry, color=False)
    assert rendered == "[run] done"


# ---------------------------------------------------------------------------
# Transcript.append_* helpers
# ---------------------------------------------------------------------------


def test_transcript_append_user_stores_and_echoes():
    captured: list[str] = []
    t = Transcript(echo=captured.append, color=False)
    entry = t.append_user("hey")
    assert entry.role == "user"
    assert captured == ["> hey"]
    assert t.entries == (entry,)
    assert len(t) == 1


def test_transcript_append_respects_emit_false():
    captured: list[str] = []
    t = Transcript(echo=captured.append, color=False)
    t.append_user("silent", emit=False)
    assert captured == []
    assert len(t) == 1


def test_transcript_append_assistant_and_system_and_error_and_warning_and_meta():
    captured: list[str] = []
    t = Transcript(echo=captured.append, color=False)
    t.append_assistant("answer")
    t.append_system("info")
    t.append_error("bad")
    t.append_warning("warn")
    t.append_meta("trace")
    assert captured == ["answer", "info", "! bad", "⚠ warn", "trace"]
    assert [e.role for e in t] == [
        "assistant",
        "system",
        "error",
        "warning",
        "meta",
    ]


def test_transcript_preserves_color_on_emit_when_enabled():
    captured: list[str] = []
    t = Transcript(echo=captured.append, color=True)
    t.append_user("hi")
    assert captured
    # ANSI present because color=True.
    assert captured[0] != click.unstyle(captured[0])


def test_transcript_iteration_and_entries_are_snapshots():
    t = Transcript(echo=lambda _: None, color=False)
    t.append_user("a")
    t.append_user("b")
    snap = t.entries
    t.append_user("c")
    # Snapshot should not reflect later appends.
    assert len(snap) == 2
    assert [e.content for e in t] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Transcript.append_event — delegates to format_workbench_event
# ---------------------------------------------------------------------------


def test_append_event_stores_pre_styled_tool_line():
    captured: list[str] = []
    t = Transcript(echo=captured.append, color=True)
    entry = t.append_event("task.started", {"title": "build", "task_id": "t1"})
    assert entry is not None
    assert entry.role == "tool"
    assert entry.event_name == "task.started"
    assert entry.data == {"title": "build", "task_id": "t1"}
    assert "[task] build" in entry.content
    assert "...started" in entry.content
    # Captured line matches the entry content (tool lines are pass-through).
    assert captured == [entry.content]


def test_append_event_returns_none_for_unknown_event():
    captured: list[str] = []
    t = Transcript(echo=captured.append)
    result = t.append_event("no.such.event", {"foo": "bar"})
    assert result is None
    assert captured == []
    assert len(t) == 0


def test_append_event_suppresses_heartbeat_and_message_delta():
    captured: list[str] = []
    t = Transcript(echo=captured.append)
    assert t.append_event("harness.heartbeat", {}) is None
    assert t.append_event("harness.metrics", {}) is None
    assert t.append_event("message.delta", {"delta": "x"}) is None
    assert captured == []
    assert len(t) == 0


def test_append_event_defaults_data_to_empty_dict():
    t = Transcript(echo=lambda _: None)
    entry = t.append_event("reflect.started")
    assert entry is not None
    assert entry.data == {}


def test_append_event_colored_task_completed_uses_green():
    captured: list[str] = []
    t = Transcript(echo=captured.append, color=True)
    t.append_event("task.completed", {"title": "build", "task_id": "t1"})
    assert captured
    assert "\x1b[32m" in captured[0]  # green from click.style


# ---------------------------------------------------------------------------
# replace_tail / extend / clear / render
# ---------------------------------------------------------------------------


def test_replace_tail_swaps_last_entry():
    captured: list[str] = []
    t = Transcript(echo=captured.append, color=False)
    t.append_user("first")
    t.append_assistant("second")
    t.replace_tail(TranscriptEntry(role="assistant", content="third"))
    assert [e.content for e in t] == ["first", "third"]
    assert captured == ["> first", "second", "third"]


def test_replace_tail_on_empty_transcript_raises():
    t = Transcript(echo=lambda _: None)
    with pytest.raises(IndexError):
        t.replace_tail(TranscriptEntry(role="assistant", content="oops"))


def test_extend_appends_multiple_entries():
    captured: list[str] = []
    t = Transcript(echo=captured.append, color=False)
    t.extend(
        [
            TranscriptEntry(role="user", content="q1"),
            TranscriptEntry(role="assistant", content="a1"),
        ]
    )
    assert [e.role for e in t] == ["user", "assistant"]
    assert captured == ["> q1", "a1"]


def test_clear_drops_entries_but_does_not_echo():
    captured: list[str] = []
    t = Transcript(echo=captured.append, color=False)
    t.append_user("keep-me-briefly")
    t.clear()
    assert len(t) == 0
    # Only the original append's line was echoed.
    assert captured == ["> keep-me-briefly"]


def test_render_joins_entries_with_newlines_and_respects_color_flag():
    t = Transcript(echo=lambda _: None, color=False)
    t.append_user("hi")
    t.append_assistant("there")
    plain = t.render()
    assert plain == "> hi\nthere"
    # Color override still produces an un-styled version when requested.
    plain_override = t.render(color=False)
    assert plain_override == plain
    # Explicit color=True re-styles.
    styled = t.render(color=True)
    assert click.unstyle(styled) == plain


# ---------------------------------------------------------------------------
# set_color / copy_with / _redact
# ---------------------------------------------------------------------------


def test_set_color_toggles_future_emit_only():
    captured: list[str] = []
    t = Transcript(echo=captured.append, color=False)
    t.append_user("plain")
    t.set_color(True)
    t.append_user("styled")
    assert captured[0] == "> plain"
    assert captured[1] != click.unstyle(captured[1])


def test_copy_with_shares_history_but_swaps_echo_and_color():
    base_captured: list[str] = []
    t = Transcript(echo=base_captured.append, color=False)
    t.append_user("original")

    clone_captured: list[str] = []
    clone = t.copy_with(echo=clone_captured.append, color=True)
    # History is shared at construction time.
    assert clone.entries == t.entries
    # Further appends on either side do not bleed.
    t.append_assistant("on-base")
    clone.append_assistant("on-clone")
    assert [e.content for e in t] == ["original", "on-base"]
    assert [e.content for e in clone] == ["original", "on-clone"]
    # Base captured only its new append (history itself was silent on copy).
    assert base_captured == ["> original", "on-base"]
    assert clone_captured == ["on-clone"]


def test_redact_drops_event_payload_but_keeps_everything_else():
    entry = TranscriptEntry(
        role="tool",
        content="[task] x",
        event_name="task.started",
        data={"big": "payload"},
    )
    out = _redact(entry)
    assert out.data is None
    assert out.event_name == "task.started"
    assert out.content == "[task] x"
    assert out.role == "tool"


def test_redact_on_non_tool_entry_is_idempotent():
    entry = TranscriptEntry(role="user", content="hi")
    assert _redact(entry) is entry
