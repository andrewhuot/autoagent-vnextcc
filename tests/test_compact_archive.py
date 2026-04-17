"""Tests for cli.llm.compact_archive.

Covers the JSONL round-trip (including truncation resilience), range
enumeration, 30-day retention predicate, and the boundary sentinel
helpers. The archive is append-only on disk and the boundary-sentinel
dance is how the orchestrator signals "this range was compacted" in
the live transcript, so both surfaces need to stay byte-stable under
load/store cycles.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cli.llm.compact_archive import (
    COMPACT_BOUNDARY_SENTINEL,
    CompactArchive,
    boundary_range,
    build_boundary_message,
    is_boundary,
)
from cli.llm.types import TurnMessage


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #


def _archive(tmp_path: Path, session_id: str = "sess-1") -> CompactArchive:
    return CompactArchive(root=tmp_path / "compact_archive", session_id=session_id)


def _sample_messages() -> list[TurnMessage]:
    """A mix of string and block-style contents to exercise JSON round-trip."""
    return [
        TurnMessage(role="user", content="hello"),
        TurnMessage(
            role="assistant",
            content=[
                {"type": "text", "text": "let me check"},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "file_read",
                    "input": {"path": "README.md"},
                },
            ],
        ),
        TurnMessage(
            role="user",
            content=[
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_1",
                    "content": "file contents here",
                }
            ],
        ),
    ]


# --------------------------------------------------------------------------- #
# write / load round-trip                                                     #
# --------------------------------------------------------------------------- #


def test_write_and_load_round_trip(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    messages = _sample_messages()

    path = archive.write(0, 3, messages)

    assert path.exists()
    loaded = archive.load(0, 3)
    assert loaded == messages


def test_write_creates_session_subdirectory(tmp_path: Path) -> None:
    archive = _archive(tmp_path, session_id="my-session")
    archive.write(5, 8, [TurnMessage(role="user", content="x")])

    session_dir = tmp_path / "compact_archive" / "my-session"
    assert session_dir.is_dir()
    assert (session_dir / "5-8.jsonl").is_file()


def test_load_missing_range_raises(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    with pytest.raises(FileNotFoundError):
        archive.load(0, 3)


def test_write_overwrites_same_range(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    archive.write(0, 2, [TurnMessage(role="user", content="first")])
    archive.write(0, 2, [TurnMessage(role="user", content="second")])

    loaded = archive.load(0, 2)
    assert len(loaded) == 1
    assert loaded[0].content == "second"


# --------------------------------------------------------------------------- #
# enumeration                                                                 #
# --------------------------------------------------------------------------- #


def test_list_archives_returns_ranges(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    archive.write(10, 20, [TurnMessage(role="user", content="a")])
    archive.write(0, 5, [TurnMessage(role="user", content="b")])
    archive.write(5, 10, [TurnMessage(role="user", content="c")])

    assert archive.ranges() == [(0, 5), (5, 10), (10, 20)]


def test_ranges_on_empty_directory_returns_empty(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    assert archive.ranges() == []


def test_ranges_ignores_non_jsonl_and_malformed_files(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    archive.write(0, 2, [TurnMessage(role="user", content="a")])

    session_dir = tmp_path / "compact_archive" / "sess-1"
    # A stray dotfile, a non-jsonl file, and a jsonl with a non-int stem.
    (session_dir / ".DS_Store").write_text("noise")
    (session_dir / "README.md").write_text("notes")
    (session_dir / "not-a-range.jsonl").write_text("{}\n")

    assert archive.ranges() == [(0, 2)]


# --------------------------------------------------------------------------- #
# append-only semantics                                                       #
# --------------------------------------------------------------------------- #


def test_jsonl_is_append_only_per_line(tmp_path: Path) -> None:
    """Truncating trailing lines still loads the surviving prefix cleanly.

    Simulates a crash mid-write: the last line may be partial or
    dropped, but the preceding fully-written lines must still load.
    """
    archive = _archive(tmp_path)
    messages = _sample_messages()  # 3 messages
    path = archive.write(0, 3, messages)

    # Keep only the first line.
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    assert len(lines) == 3
    path.write_text(lines[0], encoding="utf-8")

    loaded = archive.load(0, 3)
    assert loaded == messages[:1]


def test_load_skips_corrupt_trailing_line(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    path = archive.write(0, 2, _sample_messages()[:2])

    # Append a truncated JSON object (simulated crash mid-write).
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"role": "user", "content": "oops')  # no closing brace

    loaded = archive.load(0, 2)
    # The two complete records survive; the corrupt tail is dropped.
    assert len(loaded) == 2


# --------------------------------------------------------------------------- #
# 30-day retention                                                            #
# --------------------------------------------------------------------------- #


def test_30_day_retention_marker(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    path = archive.write(0, 1, [TurnMessage(role="user", content="x")])

    written = archive.written_at(path)
    assert archive.is_expired(path, now=written + timedelta(days=29)) is False
    assert archive.is_expired(path, now=written + timedelta(days=31)) is True


def test_30_day_retention_boundary_is_inclusive(tmp_path: Path) -> None:
    """Exactly 30 days counts as expired (>= in the predicate)."""
    archive = _archive(tmp_path)
    path = archive.write(0, 1, [TurnMessage(role="user", content="x")])

    written = archive.written_at(path)
    assert archive.is_expired(path, now=written + timedelta(days=30)) is True


def test_is_expired_accepts_naive_now(tmp_path: Path) -> None:
    """A naive datetime is treated as UTC rather than raising."""
    archive = _archive(tmp_path)
    path = archive.write(0, 1, [TurnMessage(role="user", content="x")])

    written = archive.written_at(path)
    naive_future = (written + timedelta(days=31)).replace(tzinfo=None)
    assert archive.is_expired(path, now=naive_future) is True


def test_written_at_is_timezone_aware_utc(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    path = archive.write(0, 1, [TurnMessage(role="user", content="x")])

    written = archive.written_at(path)
    assert written.tzinfo is not None
    assert written.utcoffset() == timedelta(0)


# --------------------------------------------------------------------------- #
# boundary sentinel                                                           #
# --------------------------------------------------------------------------- #


def test_build_boundary_message_round_trip() -> None:
    msg = build_boundary_message(start=3, end=9, digest_text="summary of 3..9")

    assert msg.role == "system"
    assert isinstance(msg.content, dict)
    assert msg.content["kind"] == COMPACT_BOUNDARY_SENTINEL
    assert msg.content["digest"] == "summary of 3..9"
    assert is_boundary(msg) is True
    assert boundary_range(msg) == (3, 9)


def test_is_boundary_false_for_normal_turns() -> None:
    assert is_boundary(TurnMessage(role="user", content="hello")) is False
    assert is_boundary(TurnMessage(role="assistant", content="hi")) is False
    # Correct sentinel string but wrong role — must not false-positive.
    assert is_boundary(
        TurnMessage(
            role="user",
            content={"kind": COMPACT_BOUNDARY_SENTINEL, "range": [0, 1], "digest": ""},
        )
    ) is False


def test_is_boundary_tolerates_malformed_system_content() -> None:
    """A system message with unexpected content shape must not crash."""
    # Plain string (the common system-prompt shape).
    assert is_boundary(TurnMessage(role="system", content="You are helpful.")) is False
    # Dict but without the sentinel kind.
    assert is_boundary(TurnMessage(role="system", content={"kind": "other"})) is False
    # Non-dict, non-string opaque content.
    assert is_boundary(TurnMessage(role="system", content=12345)) is False
    # None content.
    assert is_boundary(TurnMessage(role="system", content=None)) is False


def test_boundary_range_raises_on_non_boundary() -> None:
    with pytest.raises(ValueError):
        boundary_range(TurnMessage(role="user", content="hello"))


def test_boundary_range_raises_on_malformed_range() -> None:
    # Sentinel kind is correct but range is the wrong shape — loud failure
    # is better than silently returning a nonsense tuple to the caller.
    msg = TurnMessage(
        role="system",
        content={"kind": COMPACT_BOUNDARY_SENTINEL, "range": "not-a-list", "digest": ""},
    )
    with pytest.raises(ValueError):
        boundary_range(msg)


# --------------------------------------------------------------------------- #
# cross-session isolation                                                     #
# --------------------------------------------------------------------------- #


def test_sessions_are_isolated(tmp_path: Path) -> None:
    """Two archives sharing a root but different session_ids don't see each other."""
    a = _archive(tmp_path, session_id="sess-a")
    b = _archive(tmp_path, session_id="sess-b")

    a.write(0, 1, [TurnMessage(role="user", content="A")])

    assert a.ranges() == [(0, 1)]
    assert b.ranges() == []
    with pytest.raises(FileNotFoundError):
        b.load(0, 1)
