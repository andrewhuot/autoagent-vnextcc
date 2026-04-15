"""Tests for Phase-3 context / transcript / streaming primitives."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cli.sessions import Session, SessionEntry, SessionStore
from cli.workbench_app.commands import CommandRegistry
from cli.workbench_app.context_viz import (
    ContextSnapshot,
    approximate_token_count,
    render_context_grid,
    snapshot_from_transcript,
)
from cli.workbench_app.context_viz_slash import build_usage_command
from cli.workbench_app.markdown_stream import (
    BlockMode,
    RenderedLine,
    StreamingMarkdownRenderer,
    render_markdown_lines,
)
from cli.workbench_app.slash import SlashContext
from cli.workbench_app.transcript_checkpoint import (
    TranscriptCheckpoint,
    TranscriptCheckpointStore,
    TranscriptRewindManager,
)
from cli.workbench_app.transcript_rewind_slash import (
    TRANSCRIPT_REWIND_MANAGER_META_KEY,
    all_transcript_rewind_commands,
    build_transcript_checkpoint_command,
    build_transcript_checkpoints_command,
    build_transcript_rewind_command,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / ".agentlab").mkdir()
    return tmp_path


@pytest.fixture
def session_store(workspace: Path) -> SessionStore:
    return SessionStore(workspace_dir=workspace)


@pytest.fixture
def session(session_store: SessionStore) -> Session:
    session = session_store.create(title="Test")
    for role, content in [
        ("user", "Hello"),
        ("assistant", "Hi! How can I help?"),
        ("user", "Explain llm"),
    ]:
        session_store.append_entry(session, role, content)
    return session


# ---------------------------------------------------------------------------
# Token-usage grid
# ---------------------------------------------------------------------------


def _tag_styler(role: str, text: str) -> str:
    return f"<{role}>{text}</{role}>"


def test_approximate_token_count_handles_empty_and_short_strings() -> None:
    assert approximate_token_count("") == 0
    assert approximate_token_count("a") == 1
    assert approximate_token_count("abcd") == 1
    # 8 chars → 2 tokens under the chars/4 heuristic.
    assert approximate_token_count("abcdefgh") == 2


def test_snapshot_from_transcript_buckets_roles_and_overhead() -> None:
    snapshot = snapshot_from_transcript(
        [
            {"role": "user", "content": "x" * 400},
            {"role": "assistant", "content": "y" * 200},
            {"role": "tool_result", "content": "z" * 40},
        ],
        system_prompt="s" * 80,
        tool_overhead=50,
        context_limit=10_000,
    )
    assert snapshot.role_tokens["user"] == 100
    assert snapshot.role_tokens["assistant"] == 50
    # 50 hardcoded overhead + 10 from the normalised tool_result content.
    assert snapshot.role_tokens["tool"] == 60
    assert snapshot.role_tokens["system"] == 20
    assert snapshot.total_tokens == 230
    assert 0 < snapshot.used_ratio < 1


def test_snapshot_from_transcript_resolves_limit_from_model() -> None:
    # GPT-5 reports 1M; the default-limit branch should swap in the wider
    # window so the grid scales correctly.
    snapshot = snapshot_from_transcript(
        [{"role": "user", "content": "x" * 400}],
        model="gpt-5",
    )
    assert snapshot.context_limit == 1_000_000


def test_snapshot_from_transcript_explicit_limit_wins_over_model() -> None:
    # Explicit context_limit is an adapter-level signal; never second-guess
    # it, even when the model would normally report something different.
    snapshot = snapshot_from_transcript(
        [{"role": "user", "content": "x" * 400}],
        context_limit=50_000,
        model="gpt-5",
    )
    assert snapshot.context_limit == 50_000


def test_snapshot_from_transcript_unknown_model_keeps_default() -> None:
    snapshot = snapshot_from_transcript(
        [{"role": "user", "content": "x" * 400}],
        model="never-shipped-model",
    )
    assert snapshot.context_limit == 200_000


def test_usage_command_threads_active_model_from_meta(session: Session) -> None:
    # When the REPL publishes active_model via SlashContext.meta, /usage
    # should display the per-model window instead of the 200k default.
    ctx = SlashContext(session=session)
    ctx.meta = {"active_model": "gpt-5"}
    result = build_usage_command().handler(ctx)
    assert "1,000,000" in _as_text(result)


def test_snapshot_warning_flag_triggers_above_threshold() -> None:
    snapshot = ContextSnapshot(
        role_tokens={"user": 900},
        context_limit=1_000,
        warning_ratio=0.8,
    )
    assert snapshot.warning is True
    below = ContextSnapshot(
        role_tokens={"user": 200},
        context_limit=1_000,
        warning_ratio=0.8,
    )
    assert below.warning is False


def test_render_context_grid_allocates_cells_proportionally() -> None:
    snapshot = ContextSnapshot(
        role_tokens={"user": 400, "assistant": 400, "tool": 100, "system": 100},
        context_limit=1_000,
    )
    lines = render_context_grid(snapshot, rows=2, width=10, styler=_tag_styler)
    grid_lines = lines[:2]
    counts: dict[str, int] = {"user": 0, "assistant": 0, "tool": 0, "system": 0, "free": 0}
    for grid_line in grid_lines:
        for role in counts:
            counts[role] += grid_line.count(f"<{role}>")
    assert counts["user"] == 8
    assert counts["assistant"] == 8
    assert counts["tool"] == 2
    assert counts["system"] == 2
    assert counts["free"] == 0
    summary = "\n".join(lines)
    assert "1,000" in summary
    assert "100.0%" in summary


def test_render_context_grid_marks_unused_space_as_free() -> None:
    snapshot = ContextSnapshot(
        role_tokens={"user": 200},
        context_limit=1_000,
    )
    lines = render_context_grid(snapshot, rows=1, width=10, styler=_tag_styler)
    grid_line = lines[0]
    assert grid_line.count("<user>") == 2
    assert grid_line.count("<free>") == 8


def test_render_context_grid_warning_footer_present() -> None:
    snapshot = ContextSnapshot(
        role_tokens={"user": 950},
        context_limit=1_000,
        warning_ratio=0.8,
    )
    lines = render_context_grid(snapshot, rows=1, width=4, styler=_tag_styler)
    combined = "\n".join(lines)
    assert "Warning" in combined
    assert "compact" in combined


# ---------------------------------------------------------------------------
# /usage slash command
# ---------------------------------------------------------------------------


def test_usage_command_with_transcript(session: Session) -> None:
    ctx = SlashContext(session=session)
    ctx.meta = {"system_prompt": "system instructions"}
    result = build_usage_command().handler(ctx)
    body = _as_text(result)
    assert "Context window usage" in body
    assert "tokens" in body
    # Role labels from the legend render at least once.
    assert "user" in body
    assert "assistant" in body


def test_usage_command_without_transcript() -> None:
    ctx = SlashContext(session=None)
    result = build_usage_command().handler(ctx)
    assert "No transcript recorded yet" in _as_text(result)


# ---------------------------------------------------------------------------
# Transcript checkpoints
# ---------------------------------------------------------------------------


def test_transcript_checkpoint_roundtrip(workspace: Path) -> None:
    store = TranscriptCheckpointStore(workspace_dir=workspace)
    checkpoint = TranscriptCheckpoint(
        checkpoint_id="abc",
        session_id="sess1",
        message_index=4,
        label="manual",
        note="n",
        created_at=100.0,
    )
    store.save_all("sess1", [checkpoint])
    restored = store.load("sess1")
    assert restored == [checkpoint]


def test_transcript_rewind_manager_snapshot_appends(
    workspace: Path, session_store: SessionStore, session: Session
) -> None:
    manager = TranscriptRewindManager(
        store=TranscriptCheckpointStore(workspace_dir=workspace),
        session_store=session_store,
    )
    first = manager.snapshot(session, label="start")
    assert first.message_index == 3
    assert first.auto is False

    session_store.append_entry(session, "assistant", "An llm is…")
    second = manager.snapshot(session, auto=True)
    assert second.message_index == 4
    entries = manager.list(session.session_id, include_auto=True)
    assert [cp.checkpoint_id for cp in entries] == [second.checkpoint_id, first.checkpoint_id]
    manual_only = manager.list(session.session_id, include_auto=False)
    assert [cp.checkpoint_id for cp in manual_only] == [first.checkpoint_id]


def test_transcript_rewind_manager_rewinds_and_persists(
    workspace: Path, session_store: SessionStore, session: Session
) -> None:
    manager = TranscriptRewindManager(
        store=TranscriptCheckpointStore(workspace_dir=workspace),
        session_store=session_store,
    )
    checkpoint = manager.snapshot(session, label="before")
    assert checkpoint.message_index == 3
    session_store.append_entry(session, "assistant", "More")
    session_store.append_entry(session, "user", "And more")
    assert len(session.transcript) == 5

    chosen, dropped = manager.rewind(session, checkpoint.checkpoint_id)
    assert chosen.checkpoint_id == checkpoint.checkpoint_id
    assert dropped == 2
    assert len(session.transcript) == 3

    reloaded = session_store.get(session.session_id)
    assert reloaded is not None
    assert len(reloaded.transcript) == 3


def test_transcript_rewind_manager_unknown_checkpoint(
    workspace: Path, session_store: SessionStore, session: Session
) -> None:
    manager = TranscriptRewindManager(
        store=TranscriptCheckpointStore(workspace_dir=workspace),
        session_store=session_store,
    )
    with pytest.raises(ValueError):
        manager.rewind(session, "nope")


def test_maybe_snapshot_after_assistant_turn_debounces(
    workspace: Path, session_store: SessionStore, session: Session
) -> None:
    manager = TranscriptRewindManager(
        store=TranscriptCheckpointStore(workspace_dir=workspace),
        session_store=session_store,
        auto_threshold=2,
    )
    # First call: transcript has 3 entries; last auto index was -1, delta is 4 → snapshot.
    first = manager.maybe_snapshot_after_assistant_turn(session)
    assert first is not None
    # Second call without new messages: delta is 0 → no snapshot.
    assert manager.maybe_snapshot_after_assistant_turn(session) is None
    # Add one message; delta is 1 which is still below threshold → no snapshot.
    session_store.append_entry(session, "assistant", "more")
    assert manager.maybe_snapshot_after_assistant_turn(session) is None
    # Add a second message; delta hits 2 → new auto snapshot.
    session_store.append_entry(session, "user", "ok")
    third = manager.maybe_snapshot_after_assistant_turn(session)
    assert third is not None
    assert third.message_index == 5


# ---------------------------------------------------------------------------
# Transcript rewind slash commands
# ---------------------------------------------------------------------------


def _ctx_with_manager(
    session: Session,
    manager: TranscriptRewindManager | None,
) -> SlashContext:
    ctx = SlashContext(session=session)
    ctx.meta = (
        {TRANSCRIPT_REWIND_MANAGER_META_KEY: manager} if manager is not None else {}
    )
    return ctx


def test_transcript_checkpoint_slash_creates_entry(
    workspace: Path, session_store: SessionStore, session: Session
) -> None:
    manager = TranscriptRewindManager(
        store=TranscriptCheckpointStore(workspace_dir=workspace),
        session_store=session_store,
    )
    ctx = _ctx_with_manager(session, manager)
    result = build_transcript_checkpoint_command().handler(ctx, "label", "words")
    assert "Transcript checkpoint saved" in _as_text(result)
    assert len(manager.list(session.session_id)) == 1


def test_transcript_rewind_slash_dispatches_and_trims(
    workspace: Path, session_store: SessionStore, session: Session
) -> None:
    manager = TranscriptRewindManager(
        store=TranscriptCheckpointStore(workspace_dir=workspace),
        session_store=session_store,
    )
    checkpoint = manager.snapshot(session, label="before")
    session_store.append_entry(session, "assistant", "extra")
    ctx = _ctx_with_manager(session, manager)
    result = build_transcript_rewind_command().handler(ctx, checkpoint.checkpoint_id)
    assert "Rewound to checkpoint" in _as_text(result)
    assert len(session.transcript) == checkpoint.message_index


def test_transcript_rewind_slash_handles_unknown_id(
    workspace: Path, session_store: SessionStore, session: Session
) -> None:
    manager = TranscriptRewindManager(
        store=TranscriptCheckpointStore(workspace_dir=workspace),
        session_store=session_store,
    )
    ctx = _ctx_with_manager(session, manager)
    result = build_transcript_rewind_command().handler(ctx, "bogus")
    assert "Unknown transcript checkpoint" in _as_text(result)


def test_transcript_checkpoints_slash_filters_auto_by_default(
    workspace: Path, session_store: SessionStore, session: Session
) -> None:
    manager = TranscriptRewindManager(
        store=TranscriptCheckpointStore(workspace_dir=workspace),
        session_store=session_store,
    )
    manual = manager.snapshot(session, label="manual")
    auto = manager.snapshot(session, auto=True)
    ctx = _ctx_with_manager(session, manager)
    default_result = build_transcript_checkpoints_command().handler(ctx)
    default_text = _as_text(default_result)
    assert manual.checkpoint_id in default_text
    assert auto.checkpoint_id not in default_text

    all_result = build_transcript_checkpoints_command().handler(ctx, "--all")
    all_text = _as_text(all_result)
    assert manual.checkpoint_id in all_text
    assert auto.checkpoint_id in all_text


def test_transcript_slash_without_manager_warns(session: Session) -> None:
    ctx = _ctx_with_manager(session, None)
    for command in all_transcript_rewind_commands():
        result = command.handler(ctx)
        assert "not configured" in _as_text(result)


def test_transcript_slash_commands_register_cleanly() -> None:
    registry = CommandRegistry()
    for command in all_transcript_rewind_commands():
        registry.register(command)
    assert set(registry.names()) >= {
        "transcript-checkpoint",
        "transcript-rewind",
        "transcript-checkpoints",
    }


# ---------------------------------------------------------------------------
# Streaming markdown renderer
# ---------------------------------------------------------------------------


def _tagging_styler(line: str, mode: BlockMode, fence_language: str) -> str:
    return f"[{mode.value}]{line}"


def test_streaming_renderer_emits_completed_lines_only() -> None:
    emitted: list[str] = []
    renderer = StreamingMarkdownRenderer(echo=emitted.append, styler=_tagging_styler)
    renderer.feed("hello")  # no newline yet — nothing emitted
    assert emitted == []
    renderer.feed(", world\nnext line")  # one newline → one emission
    assert emitted == ["[prose]hello, world"]
    renderer.finalize()
    assert emitted == ["[prose]hello, world", "[prose]next line"]


def test_streaming_renderer_fenced_code_block() -> None:
    emitted: list[str] = []
    renderer = StreamingMarkdownRenderer(echo=emitted.append, styler=_tagging_styler)
    renderer.feed("```python\nprint(1)\n```\nnormal\n")
    renderer.finalize()
    assert emitted == [
        "[prose]```python",
        "[code]print(1)",
        "[prose]```",
        "[prose]normal",
    ]


def test_streaming_renderer_diff_block_language_tag() -> None:
    emitted: list[str] = []
    renderer = StreamingMarkdownRenderer(echo=emitted.append, styler=_tagging_styler)
    renderer.feed("```diff\n-a\n+b\n c\n```\n")
    renderer.finalize()
    assert emitted == [
        "[prose]```diff",
        "[diff]-a",
        "[diff]+b",
        "[diff] c",
        "[prose]```",
    ]


def test_streaming_renderer_detects_inline_diff_lines() -> None:
    emitted: list[str] = []
    renderer = StreamingMarkdownRenderer(echo=emitted.append, styler=_tagging_styler)
    renderer.feed("before\n+ new\n- old\nafter\n")
    renderer.finalize()
    assert emitted == [
        "[prose]before",
        "[diff]+ new",
        "[diff]- old",
        "[prose]after",
    ]


def test_streaming_renderer_records_rendered_lines() -> None:
    emitted: list[str] = []
    renderer = StreamingMarkdownRenderer(echo=emitted.append, styler=_tagging_styler)
    renderer.feed("```diff\n+ ok\n```\n")
    renderer.finalize()
    assert renderer.emitted == [
        RenderedLine(text="```diff", mode=BlockMode.PROSE, fence_language="diff"),
        RenderedLine(text="+ ok", mode=BlockMode.DIFF, fence_language="diff"),
        RenderedLine(text="```", mode=BlockMode.PROSE, fence_language="diff"),
    ]


def test_render_markdown_lines_convenience_wrapper() -> None:
    lines = render_markdown_lines(
        "Hello\n```python\nx = 1\n```\n",
        styler=_tagging_styler,
    )
    assert lines == [
        "[prose]Hello",
        "[prose]```python",
        "[code]x = 1",
        "[prose]```",
    ]


def test_streaming_renderer_accepts_crlf_input() -> None:
    emitted: list[str] = []
    renderer = StreamingMarkdownRenderer(echo=emitted.append, styler=_tagging_styler)
    renderer.feed("windows\r\nline\r\n")
    renderer.finalize()
    assert emitted == ["[prose]windows", "[prose]line"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _as_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if hasattr(result, "result"):
        return str(result.result or "")
    return str(result)
