"""T22 sequence-focused regression checkpoint for the tool-call block renderer.

This module complements :mod:`tests.test_tool_call_block` (T08 coverage of
individual events and edge cases) with full-lifecycle sequences — the exact
shape the transcript consumes during ``/eval``, ``/optimize``, ``/build``, and
``/deploy`` runs. Each test walks the renderer through a realistic ordered
event stream and asserts the emitted lines + final state together, so any
regression that breaks sequence ordering (header/progress/footer) or state
transitions (running → completed / failed) surfaces here as a single
readable diff.
"""

from __future__ import annotations

import click

from cli.workbench_render import (
    ToolCallBlockRenderer,
    render_tool_call_block,
)


def _plain(lines: list[str]) -> list[str]:
    return [click.unstyle(line) for line in lines]


# ---------------------------------------------------------------------------
# Full-lifecycle sequences
# ---------------------------------------------------------------------------


def test_started_progress_completed_sequence_renders_full_block():
    events = [
        ("task.started", {"task_id": "compile", "title": "Compile prompt"}),
        ("task.progress", {"task_id": "compile", "note": "parsing spec"}),
        ("task.progress", {"task_id": "compile", "note": "applying skill"}),
        ("task.completed", {"task_id": "compile", "source": "live"}),
    ]
    lines = _plain(list(render_tool_call_block(events)))
    assert lines == [
        "⏺ Compile prompt",
        "  ⎿ parsing spec",
        "  ⎿ applying skill",
        "  ✓ done [live]",
    ]


def test_started_progress_failed_sequence_renders_error_footer():
    events = [
        ("task.started", {"task_id": "generate", "title": "Generate draft"}),
        ("task.progress", {"task_id": "generate", "note": "step 1"}),
        ("task.failed", {"task_id": "generate", "reason": "model refused"}),
    ]
    lines = _plain(list(render_tool_call_block(events)))
    assert lines == [
        "⏺ Generate draft",
        "  ⎿ step 1",
        "  ✗ failed: model refused",
    ]


def test_sequence_final_state_mirrors_emitted_footer():
    r = ToolCallBlockRenderer()
    for name, data in [
        ("task.started", {"task_id": "s", "title": "Score"}),
        ("task.progress", {"task_id": "s", "note": "grading output"}),
        ("task.completed", {"task_id": "s", "source": "judge"}),
    ]:
        r.feed(name, data)
    assert r.open_blocks == {}
    assert len(r.completed_blocks) == 1
    snap = r.completed_blocks[0]
    assert snap.status == "completed"
    assert snap.source == "judge"
    assert snap.progress_count == 1


def test_failed_sequence_captures_failure_reason_in_state():
    r = ToolCallBlockRenderer()
    for name, data in [
        ("task.started", {"task_id": "eval-1", "title": "Eval #1"}),
        ("task.progress", {"task_id": "eval-1", "note": "loading fixture"}),
        ("task.progress", {"task_id": "eval-1", "note": "scoring"}),
        ("task.failed", {"task_id": "eval-1", "failure_reason": "timeout"}),
    ]:
        r.feed(name, data)
    assert r.completed_blocks[0].status == "failed"
    assert r.completed_blocks[0].failure_reason == "timeout"
    assert r.completed_blocks[0].progress_count == 2


# ---------------------------------------------------------------------------
# Multiple sequences in a single stream
# ---------------------------------------------------------------------------


def test_back_to_back_sequences_render_in_order():
    events = [
        # First task.
        ("task.started", {"task_id": "a", "title": "Task A"}),
        ("task.progress", {"task_id": "a", "note": "a-1"}),
        ("task.completed", {"task_id": "a"}),
        # Second task, with a failure.
        ("task.started", {"task_id": "b", "title": "Task B"}),
        ("task.progress", {"task_id": "b", "note": "b-1"}),
        ("task.failed", {"task_id": "b", "reason": "invalid arg"}),
    ]
    lines = _plain(list(render_tool_call_block(events)))
    assert lines == [
        "⏺ Task A",
        "  ⎿ a-1",
        "  ✓ done",
        "⏺ Task B",
        "  ⎿ b-1",
        "  ✗ failed: invalid arg",
    ]


def test_interleaved_sequences_preserve_event_order():
    # Two task_ids running concurrently, finishing in opposite order.
    events = [
        ("task.started", {"task_id": "a", "title": "A"}),
        ("task.started", {"task_id": "b", "title": "B"}),
        ("task.progress", {"task_id": "a", "note": "a-1"}),
        ("task.progress", {"task_id": "b", "note": "b-1"}),
        ("task.progress", {"task_id": "a", "note": "a-2"}),
        ("task.completed", {"task_id": "b", "source": "live"}),
        ("task.completed", {"task_id": "a", "source": "cache"}),
    ]
    r = ToolCallBlockRenderer()
    emitted: list[str] = []
    for name, data in events:
        emitted.extend(r.feed(name, data))
    assert _plain(emitted) == [
        "⏺ A",
        "⏺ B",
        "  ⎿ a-1",
        "  ⎿ b-1",
        "  ⎿ a-2",
        "  ✓ done [live]",
        "  ✓ done [cache]",
    ]
    # Completion order matches footer order.
    assert [b.task_id for b in r.completed_blocks] == ["b", "a"]


def test_mixed_success_and_failure_across_sequences():
    events = [
        ("task.started", {"task_id": "ok", "title": "Ok"}),
        ("task.started", {"task_id": "bad", "title": "Bad"}),
        ("task.progress", {"task_id": "ok", "note": "fine"}),
        ("task.failed", {"task_id": "bad", "reason": "boom"}),
        ("task.completed", {"task_id": "ok"}),
    ]
    r = ToolCallBlockRenderer()
    for name, data in events:
        r.feed(name, data)
    statuses = {b.task_id: b.status for b in r.completed_blocks}
    assert statuses == {"ok": "completed", "bad": "failed"}
    assert r.open_blocks == {}


# ---------------------------------------------------------------------------
# Stream termination
# ---------------------------------------------------------------------------


def test_truncated_sequence_closes_open_block_with_default_reason():
    events = [
        ("task.started", {"task_id": "x", "title": "Truncated"}),
        ("task.progress", {"task_id": "x", "note": "half-way"}),
    ]
    lines = _plain(list(render_tool_call_block(events)))
    assert lines[-1] == "  ✗ failed: stream ended"


def test_stream_with_only_orphan_progress_synthesises_header():
    events = [
        ("task.progress", {"task_id": "orphan", "note": "late"}),
        ("task.completed", {"task_id": "orphan"}),
    ]
    lines = _plain(list(render_tool_call_block(events)))
    assert lines == [
        "⏺ orphan",
        "  ⎿ late",
        "  ✓ done",
    ]


# ---------------------------------------------------------------------------
# Sequences interleaved with non-task events
# ---------------------------------------------------------------------------


def test_non_task_events_interleave_cleanly_with_sequence():
    events = [
        ("turn.started", {"turn_number": 1}),
        ("task.started", {"task_id": "a", "title": "A"}),
        ("harness.heartbeat", {"ts": 5}),  # suppressed
        ("task.progress", {"task_id": "a", "note": "tick"}),
        ("message.delta", {"text": "..."}),  # suppressed
        ("task.completed", {"task_id": "a"}),
        ("run.completed", {"version": 4}),
    ]
    lines = _plain(list(render_tool_call_block(events)))
    assert "Started turn 1" in lines[0]
    assert lines[1:4] == ["⏺ A", "  ⎿ tick", "  ✓ done"]
    assert "Draft v4" in lines[4]
    assert len(lines) == 5  # heartbeat + message.delta contributed nothing
