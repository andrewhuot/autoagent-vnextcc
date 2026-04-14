"""Tests for the T08 tool-call block renderer in ``cli/workbench_render.py``.

Covers the stateful :class:`ToolCallBlockRenderer` and the convenience
:func:`render_tool_call_block` generator across the full
task.started / task.progress / task.completed (and task.failed) lifecycle,
including defensive paths — interleaved task_ids, missing task.started, empty
progress payloads, duplicate starts, and stream closure with still-open
blocks.
"""

from __future__ import annotations

import click

from cli.workbench_render import (
    ToolCallBlockRenderer,
    ToolCallBlockState,
    render_tool_call_block,
)


# ---------------------------------------------------------------------------
# Happy path: one task start → progress → complete
# ---------------------------------------------------------------------------


def test_feed_emits_header_progress_and_completed_in_order():
    r = ToolCallBlockRenderer()

    header = r.feed("task.started", {"task_id": "t1", "title": "Generate prompt"})
    progress = r.feed("task.progress", {"task_id": "t1", "note": "drafted outline"})
    footer = r.feed(
        "task.completed", {"task_id": "t1", "source": "live"}
    )

    assert len(header) == 1
    assert "Generate prompt" in click.unstyle(header[0])
    assert click.unstyle(header[0]).startswith("⏺ ")

    assert len(progress) == 1
    assert "drafted outline" in click.unstyle(progress[0])
    assert click.unstyle(progress[0]).startswith("  ⎿ ")

    assert len(footer) == 1
    plain = click.unstyle(footer[0])
    assert plain.startswith("  ✓ done")
    assert "[live]" in plain


def test_header_is_cyan_bold_and_progress_is_dim():
    r = ToolCallBlockRenderer()
    header = r.feed("task.started", {"task_id": "x", "title": "H"})[0]
    progress = r.feed("task.progress", {"task_id": "x", "note": "p"})[0]

    # Cyan foreground (36) + bold (1).
    assert "\x1b[36m" in header or "\x1b[1;36m" in header
    assert "\x1b[1m" in header or "\x1b[1;" in header
    # Dim sequence (2).
    assert "\x1b[2m" in progress


def test_completed_without_source_has_no_suffix():
    r = ToolCallBlockRenderer()
    r.feed("task.started", {"task_id": "t", "title": "T"})
    out = r.feed("task.completed", {"task_id": "t"})[0]
    assert click.unstyle(out) == "  ✓ done"


def test_completed_is_green():
    r = ToolCallBlockRenderer()
    r.feed("task.started", {"task_id": "t", "title": "T"})
    out = r.feed("task.completed", {"task_id": "t", "source": "template"})[0]
    assert "\x1b[32m" in out  # green


# ---------------------------------------------------------------------------
# task.failed path
# ---------------------------------------------------------------------------


def test_failed_emits_red_footer_with_reason():
    r = ToolCallBlockRenderer()
    r.feed("task.started", {"task_id": "t", "title": "Risky"})
    out = r.feed(
        "task.failed", {"task_id": "t", "reason": "timeout after 30s"}
    )[0]
    plain = click.unstyle(out)
    assert plain == "  ✗ failed: timeout after 30s"
    assert "\x1b[31m" in out  # red


def test_failed_accepts_failure_reason_and_message_fallback():
    r = ToolCallBlockRenderer()
    r.feed("task.started", {"task_id": "t", "title": "T"})
    out = r.feed(
        "task.failed", {"task_id": "t", "failure_reason": "rate limit"}
    )[0]
    assert "rate limit" in click.unstyle(out)

    r2 = ToolCallBlockRenderer()
    r2.feed("task.started", {"task_id": "t", "title": "T"})
    out2 = r2.feed(
        "task.failed", {"task_id": "t", "message": "assertion blew up"}
    )[0]
    assert "assertion blew up" in click.unstyle(out2)


def test_failed_without_reason_shows_bare_marker():
    r = ToolCallBlockRenderer()
    r.feed("task.started", {"task_id": "t", "title": "T"})
    out = r.feed("task.failed", {"task_id": "t"})[0]
    assert click.unstyle(out) == "  ✗ failed"


# ---------------------------------------------------------------------------
# State tracking
# ---------------------------------------------------------------------------


def test_state_tracks_open_blocks_until_completion():
    r = ToolCallBlockRenderer()
    r.feed("task.started", {"task_id": "a", "title": "Alpha"})
    r.feed("task.progress", {"task_id": "a", "note": "one"})
    r.feed("task.progress", {"task_id": "a", "note": "two"})

    assert "a" in r.open_blocks
    state = r.open_blocks["a"]
    assert isinstance(state, ToolCallBlockState)
    assert state.title == "Alpha"
    assert state.progress_count == 2
    assert state.status == "running"
    assert r.completed_blocks == ()

    r.feed("task.completed", {"task_id": "a", "source": "live"})

    assert r.open_blocks == {}
    assert len(r.completed_blocks) == 1
    finished = r.completed_blocks[0]
    assert finished.status == "completed"
    assert finished.source == "live"
    assert finished.progress_count == 2


def test_failed_state_is_recorded_on_completed_blocks():
    r = ToolCallBlockRenderer()
    r.feed("task.started", {"task_id": "x", "title": "X"})
    r.feed("task.failed", {"task_id": "x", "reason": "boom"})
    assert r.open_blocks == {}
    assert r.completed_blocks[0].status == "failed"
    assert r.completed_blocks[0].failure_reason == "boom"


# ---------------------------------------------------------------------------
# Interleaved task_ids
# ---------------------------------------------------------------------------


def test_interleaved_tasks_render_independently():
    r = ToolCallBlockRenderer()
    lines: list[str] = []
    lines += r.feed("task.started", {"task_id": "a", "title": "A"})
    lines += r.feed("task.started", {"task_id": "b", "title": "B"})
    lines += r.feed("task.progress", {"task_id": "a", "note": "na"})
    lines += r.feed("task.progress", {"task_id": "b", "note": "nb"})
    lines += r.feed("task.completed", {"task_id": "b"})
    lines += r.feed("task.completed", {"task_id": "a"})

    plain = [click.unstyle(line) for line in lines]
    assert plain == [
        "⏺ A",
        "⏺ B",
        "  ⎿ na",
        "  ⎿ nb",
        "  ✓ done",
        "  ✓ done",
    ]
    assert r.open_blocks == {}
    assert [b.task_id for b in r.completed_blocks] == ["b", "a"]


# ---------------------------------------------------------------------------
# Defensive / edge cases
# ---------------------------------------------------------------------------


def test_duplicate_task_started_does_not_reemit_header():
    r = ToolCallBlockRenderer()
    first = r.feed("task.started", {"task_id": "t", "title": "Short"})
    second = r.feed(
        "task.started", {"task_id": "t", "title": "Nicer label"}
    )
    assert len(first) == 1
    assert second == []
    # Title refresh sticks though.
    assert r.open_blocks["t"].title == "Nicer label"


def test_progress_without_prior_started_opens_block_implicitly():
    r = ToolCallBlockRenderer()
    out = r.feed("task.progress", {"task_id": "orphan", "note": "hi"})
    assert len(out) == 2  # synthesized header + progress
    assert click.unstyle(out[0]) == "⏺ orphan"
    assert click.unstyle(out[1]) == "  ⎿ hi"
    assert "orphan" in r.open_blocks


def test_completed_without_prior_started_synthesizes_header():
    r = ToolCallBlockRenderer()
    out = r.feed(
        "task.completed", {"task_id": "late", "title": "Late task"}
    )
    assert len(out) == 2
    assert click.unstyle(out[0]) == "⏺ Late task"
    assert click.unstyle(out[1]).startswith("  ✓ done")
    assert r.open_blocks == {}
    assert r.completed_blocks[0].status == "completed"


def test_progress_with_empty_note_is_dropped():
    r = ToolCallBlockRenderer()
    r.feed("task.started", {"task_id": "t", "title": "T"})
    assert r.feed("task.progress", {"task_id": "t", "note": ""}) == []
    assert r.feed("task.progress", {"task_id": "t"}) == []
    assert r.open_blocks["t"].progress_count == 0


def test_progress_accepts_message_field_fallback():
    r = ToolCallBlockRenderer()
    r.feed("task.started", {"task_id": "t", "title": "T"})
    out = r.feed("task.progress", {"task_id": "t", "message": "msg note"})
    assert click.unstyle(out[0]) == "  ⎿ msg note"


def test_progress_with_current_total_renders_fractional_bar():
    r = ToolCallBlockRenderer()
    r.feed("task.started", {"task_id": "t", "title": "T"})
    out = r.feed(
        "task.progress",
        {"task_id": "t", "note": "scoring cases", "current": 2, "total": 4},
    )
    plain = click.unstyle(out[0])
    assert plain.startswith("  ⎿ scoring cases")
    assert "█████" in plain
    assert "50%" in plain


def test_title_falls_back_to_task_id_then_task_then_name():
    r = ToolCallBlockRenderer()
    # task_id only
    out = r.feed("task.started", {"task_id": "only-id"})
    assert click.unstyle(out[0]) == "⏺ only-id"

    # `task` key wins over task_id
    r2 = ToolCallBlockRenderer()
    out2 = r2.feed(
        "task.started", {"task_id": "id", "task": "Pretty task"}
    )
    assert click.unstyle(out2[0]) == "⏺ Pretty task"

    # `name` key is accepted too
    r3 = ToolCallBlockRenderer()
    out3 = r3.feed("task.started", {"task_id": "id", "name": "Named"})
    assert click.unstyle(out3[0]) == "⏺ Named"


def test_events_without_task_id_group_by_title():
    r = ToolCallBlockRenderer()
    r.feed("task.started", {"title": "Titled task"})
    r.feed("task.progress", {"title": "Titled task", "note": "step"})
    r.feed("task.completed", {"title": "Titled task"})

    assert r.open_blocks == {}
    # The state is keyed by title when task_id is absent.
    assert r.completed_blocks[0].task_id == "Titled task"
    assert r.completed_blocks[0].progress_count == 1


# ---------------------------------------------------------------------------
# Non-task events fall through to the standard renderer
# ---------------------------------------------------------------------------


def test_non_task_events_fall_through_to_format_workbench_event():
    r = ToolCallBlockRenderer()
    out = r.feed("turn.started", {"turn_number": 3})
    assert len(out) == 1
    assert "Started turn 3" in click.unstyle(out[0])


def test_unknown_event_returns_empty():
    r = ToolCallBlockRenderer()
    assert r.feed("nothing.here", {}) == []


def test_suppressed_events_return_empty():
    r = ToolCallBlockRenderer()
    # harness.heartbeat renders to None — should be skipped, not crash.
    assert r.feed("harness.heartbeat", {"ts": 1}) == []
    assert r.feed("message.delta", {"text": "x"}) == []


def test_feed_accepts_none_data():
    r = ToolCallBlockRenderer()
    # A caller that doesn't thread payload through should still get sensible
    # output rather than a TypeError.
    out = r.feed("task.started")
    assert click.unstyle(out[0]) == "⏺ task"


# ---------------------------------------------------------------------------
# close_all / render_tool_call_block
# ---------------------------------------------------------------------------


def test_close_all_emits_failure_footer_for_each_open_block():
    r = ToolCallBlockRenderer()
    r.feed("task.started", {"task_id": "a", "title": "A"})
    r.feed("task.started", {"task_id": "b", "title": "B"})

    closed = r.close_all(reason="ctrl-c")
    assert len(closed) == 2
    for line in closed:
        plain = click.unstyle(line)
        assert plain == "  ✗ failed: ctrl-c"
    assert r.open_blocks == {}
    # Both blocks moved to completed_blocks in the order they were closed.
    statuses = [b.status for b in r.completed_blocks]
    assert statuses == ["failed", "failed"]
    assert {b.failure_reason for b in r.completed_blocks} == {"ctrl-c"}


def test_close_all_is_noop_when_nothing_is_open():
    r = ToolCallBlockRenderer()
    assert r.close_all() == []


def test_render_tool_call_block_streams_full_sequence():
    events = [
        ("task.started", {"task_id": "a", "title": "Alpha"}),
        ("task.progress", {"task_id": "a", "note": "n1"}),
        ("task.progress", {"task_id": "a", "note": "n2"}),
        ("task.completed", {"task_id": "a", "source": "live"}),
    ]
    lines = [click.unstyle(line) for line in render_tool_call_block(events)]
    assert lines == [
        "⏺ Alpha",
        "  ⎿ n1",
        "  ⎿ n2",
        "  ✓ done [live]",
    ]


def test_render_tool_call_block_closes_open_blocks_when_stream_ends():
    events = [
        ("task.started", {"task_id": "a", "title": "Alpha"}),
        ("task.progress", {"task_id": "a", "note": "mid"}),
    ]
    lines = [click.unstyle(line) for line in render_tool_call_block(events)]
    assert lines == [
        "⏺ Alpha",
        "  ⎿ mid",
        "  ✗ failed: stream ended",
    ]


def test_render_tool_call_block_respects_close_unfinished_flag():
    events = [("task.started", {"task_id": "a", "title": "Alpha"})]
    lines = list(
        render_tool_call_block(events, close_unfinished=False)
    )
    assert len(lines) == 1
    assert click.unstyle(lines[0]) == "⏺ Alpha"


def test_render_tool_call_block_passes_through_non_task_events():
    events = [
        ("turn.started", {"turn_number": 1}),
        ("task.started", {"task_id": "a", "title": "A"}),
        ("task.completed", {"task_id": "a"}),
        ("run.completed", {"version": 7}),
    ]
    lines = [click.unstyle(line) for line in render_tool_call_block(events)]
    assert "Started turn 1" in lines[0]
    assert lines[1] == "⏺ A"
    assert lines[2] == "  ✓ done"
    assert "Draft v7" in lines[3]
