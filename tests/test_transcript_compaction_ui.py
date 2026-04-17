"""Tests for P2.T4 — compact boundary UI rendering in the transcript pane.

The workbench transcript surfaces a compact boundary as a fenced block so
the operator can visually distinguish the live tail from the archived
prefix. These tests pin:

- :func:`format_entry` routes boundary entries through the rule renderer.
- :meth:`Transcript.append_compact_boundary` stores the right shape.
- :func:`transcript_has_boundary` is a pure predicate over the entries.
- Non-boundary system entries still render via the existing branch.
- Color mode also renders (ANSI escapes are allowed).
"""

from __future__ import annotations

from cli.workbench_app.transcript import (
    Transcript,
    TranscriptEntry,
    format_entry,
    transcript_has_boundary,
)


# --------------------------------------------------------------------- helpers


def _user_entry(content: str = "hello") -> TranscriptEntry:
    return TranscriptEntry(role="user", content=content)


def _boundary_entry(start: int = 3, end: int = 17) -> TranscriptEntry:
    count = end - start
    return TranscriptEntry(
        role="system",
        content=f"Compacted {count} turns — /uncompact to restore",
        event_name="compact_boundary",
        data={"range": (start, end)},
    )


# ---------------------------------------------------------- format_entry


def test_format_entry_renders_boundary_rule():
    entry = TranscriptEntry(
        role="system",
        content="Compacted 14 turns — /uncompact to restore",
        event_name="compact_boundary",
        data={"range": (3, 17)},
    )
    rendered = format_entry(entry, color=False)
    assert "─" * 10 in rendered
    assert "Compacted 14 turns" in rendered
    assert "/uncompact" in rendered


def test_format_entry_boundary_has_rule_above_and_below():
    entry = _boundary_entry()
    rendered = format_entry(entry, color=False)
    lines = rendered.splitlines()
    # Rule / content / rule.
    assert len(lines) == 3
    assert set(lines[0]) == {"─"}
    assert "Compacted" in lines[1]
    assert set(lines[2]) == {"─"}


def test_format_entry_boundary_color_mode_does_not_crash():
    entry = _boundary_entry()
    rendered = format_entry(entry, color=True)
    # Still contains the rule characters and the content — ANSI escapes
    # may surround them but the substrings remain locatable.
    assert "─" * 10 in rendered
    assert "Compacted 14 turns" in rendered
    assert "/uncompact" in rendered


def test_format_entry_non_boundary_system_unchanged():
    # Plain system entry with no event_name should go through the existing
    # branch, NOT the boundary renderer. A plain system line has no rule.
    entry = TranscriptEntry(role="system", content="plain system line")
    rendered = format_entry(entry, color=False)
    assert "─" not in rendered
    assert rendered == "plain system line"


def test_format_entry_system_with_other_event_name_unchanged():
    # An event_name that isn't "compact_boundary" still uses the default branch.
    entry = TranscriptEntry(
        role="system",
        content="weather report",
        event_name="not_a_boundary",
    )
    rendered = format_entry(entry, color=False)
    assert "─" not in rendered
    assert rendered == "weather report"


# ---------------------------------------------------- append_compact_boundary


def test_append_compact_boundary_stores_entry():
    t = Transcript(echo=lambda s: None, color=False)
    entry = t.append_compact_boundary(start=3, end=17, summary="tool phase")
    assert entry.event_name == "compact_boundary"
    assert entry.data["range"] == (3, 17)


def test_append_compact_boundary_content_reflects_range_count():
    t = Transcript(echo=lambda s: None, color=False)
    entry = t.append_compact_boundary(start=3, end=17, summary="ignored")
    # end - start == 14 turns compacted (start inclusive, end exclusive).
    assert "Compacted 14 turns" in entry.content
    assert "/uncompact" in entry.content


def test_append_compact_boundary_echoes_rendered_block():
    captured: list[str] = []
    t = Transcript(echo=captured.append, color=False)
    t.append_compact_boundary(start=0, end=5, summary="s")
    assert len(captured) == 1
    assert "─" * 10 in captured[0]
    assert "Compacted 5 turns" in captured[0]


def test_append_compact_boundary_appears_in_entries():
    t = Transcript(echo=lambda s: None, color=False)
    t.append_user("hi")
    t.append_compact_boundary(start=1, end=4, summary="x")
    entries = t.entries
    assert len(entries) == 2
    assert entries[1].event_name == "compact_boundary"
    assert entries[1].data["summary"] == "x"


# ---------------------------------------------------- transcript_has_boundary


def test_transcript_has_boundary_detects_boundary():
    entries = [_user_entry(), _boundary_entry()]
    assert transcript_has_boundary(entries) is True
    assert transcript_has_boundary([_user_entry()]) is False


def test_transcript_has_boundary_empty_returns_false():
    assert transcript_has_boundary([]) is False


def test_transcript_has_boundary_multiple_boundaries():
    entries = [
        _user_entry(),
        _boundary_entry(0, 3),
        _user_entry("mid"),
        _boundary_entry(5, 9),
    ]
    assert transcript_has_boundary(entries) is True


def test_transcript_has_boundary_works_on_live_transcript():
    t = Transcript(echo=lambda s: None, color=False)
    t.append_user("hello")
    assert transcript_has_boundary(t.entries) is False
    t.append_compact_boundary(start=0, end=1, summary="s")
    assert transcript_has_boundary(t.entries) is True
