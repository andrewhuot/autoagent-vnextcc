"""Tests for cli.memory.store.MemoryStore.

Covers CRUD, frontmatter round-trip, slug-safety, atomic write, index
truncation, and corrupt-file resilience. Mirrors the frontmatter +
MEMORY.md index convention used at
``~/.claude/projects/<slug>/memory/`` on the user's machine.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cli.memory import Memory, MemoryStore, MemoryType


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #

def _memory(
    *,
    name: str = "sample",
    type: MemoryType = MemoryType.PROJECT,
    description: str = "A sample memory.",
    body: str = "Body content.\n\nMultiple paragraphs.",
    created_at: datetime | None = None,
    source_session_id: str | None = "sess-1",
    tags: tuple[str, ...] = (),
) -> Memory:
    return Memory(
        name=name,
        type=type,
        description=description,
        body=body,
        created_at=created_at or datetime(2026, 4, 17, 12, 34, 56, tzinfo=timezone.utc),
        source_session_id=source_session_id,
        tags=tags,
    )


# --------------------------------------------------------------------------- #
# empty store                                                                  #
# --------------------------------------------------------------------------- #

def test_fresh_store_list_returns_empty(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path / "memory")
    assert store.list() == []


def test_exists_before_write_is_false(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    assert store.exists("anything") is False


# --------------------------------------------------------------------------- #
# round-trip                                                                  #
# --------------------------------------------------------------------------- #

def test_write_read_round_trip_preserves_all_fields(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    m = _memory(
        name="prefer-terse",
        type=MemoryType.FEEDBACK,
        description="User prefers terse answers.",
        body="Why: user said 'stop summarising'.\nHow: skip trailing recap.",
        created_at=datetime(2026, 4, 17, 9, 30, tzinfo=timezone.utc),
        source_session_id="sess-42",
        tags=("communication", "style"),
    )
    store.write(m)
    restored = store.read("prefer-terse")
    assert restored == m


def test_write_then_list_returns_memory(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    m = _memory(name="alpha")
    store.write(m)
    assert [x.name for x in store.list()] == ["alpha"]


def test_exists_reflects_write_and_delete(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    m = _memory(name="alpha")
    store.write(m)
    assert store.exists("alpha") is True
    assert store.delete("alpha") is True
    assert store.exists("alpha") is False
    # list no longer includes it; read returns None
    assert store.list() == []
    assert store.read("alpha") is None


def test_delete_missing_returns_false(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    assert store.delete("never-existed") is False


# --------------------------------------------------------------------------- #
# uniqueness / update-in-place                                                #
# --------------------------------------------------------------------------- #

def test_write_same_name_replaces_in_place(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    store.write(_memory(name="same", body="v1"))
    store.write(_memory(name="same", body="v2"))
    listed = store.list()
    assert len(listed) == 1
    assert listed[0].body == "v2"


# --------------------------------------------------------------------------- #
# slug-safety                                                                 #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("bad_name", ["path/with/slash", "back\\slash", "null\0byte", ".hidden"])
def test_rejects_unsafe_names(tmp_path: Path, bad_name: str) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    with pytest.raises(ValueError):
        store.write(_memory(name=bad_name))


def test_rejects_empty_name(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    with pytest.raises(ValueError):
        store.write(_memory(name=""))


# --------------------------------------------------------------------------- #
# frontmatter                                                                 #
# --------------------------------------------------------------------------- #

def test_frontmatter_populated_tags_round_trip(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    m = _memory(name="with-tags", tags=("tests", "known-issues"))
    store.write(m)
    restored = store.read("with-tags")
    assert restored is not None
    assert restored.tags == ("tests", "known-issues")


def test_frontmatter_empty_tags_round_trip(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    m = _memory(name="no-tags", tags=())
    store.write(m)
    restored = store.read("no-tags")
    assert restored is not None
    assert restored.tags == ()


def test_frontmatter_none_session_id_round_trips(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    m = _memory(name="anon", source_session_id=None)
    store.write(m)
    restored = store.read("anon")
    assert restored is not None
    assert restored.source_session_id is None


def test_frontmatter_all_memory_types_round_trip(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    for t in MemoryType:
        store.write(_memory(name=f"m-{t.value}", type=t))
        restored = store.read(f"m-{t.value}")
        assert restored is not None
        assert restored.type == t


# --------------------------------------------------------------------------- #
# corrupt file resilience                                                     #
# --------------------------------------------------------------------------- #

def test_read_on_malformed_frontmatter_returns_none(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    bad = tmp_path / "bad.md"
    tmp_path.mkdir(parents=True, exist_ok=True)
    bad.write_text("---\n: not valid yaml :\nname: X\n---\nbody", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="cli.memory.store"):
        assert store.read("bad") is None
    assert any("malformed" in r.message.lower() or "invalid" in r.message.lower()
               for r in caplog.records)


def test_read_missing_frontmatter_returns_none(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "no-fm.md").write_text("just a body, no frontmatter\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="cli.memory.store"):
        assert store.read("no-fm") is None


def test_list_skips_corrupt_files(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    store.write(_memory(name="good"))
    (tmp_path / "corrupt.md").write_text("---\ngarbage\n", encoding="utf-8")
    names = [m.name for m in store.list()]
    assert names == ["good"]


# --------------------------------------------------------------------------- #
# MEMORY.md index                                                             #
# --------------------------------------------------------------------------- #

def test_index_rewritten_on_write(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    store.write(_memory(name="alpha", description="alpha memory"))
    store.write(_memory(name="beta", description="beta memory"))
    index = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "alpha" in index
    assert "beta" in index
    assert "alpha memory" in index
    assert "beta memory" in index


def test_index_line_format(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    store.write(_memory(name="alpha", description="alpha memory"))
    index = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    # Mirrors user's convention: "- [name](file.md) — description"
    assert "- [alpha](alpha.md) — alpha memory" in index


def test_index_rewritten_on_delete(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    store.write(_memory(name="alpha", description="a"))
    store.write(_memory(name="beta", description="b"))
    store.delete("alpha")
    index = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "alpha" not in index
    assert "beta" in index


def test_index_stays_under_200_lines_with_archive(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    # Write 300 memories with staggered created_at so oldest are deterministic.
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(300):
        store.write(_memory(
            name=f"m{i:03d}",
            description=f"memory {i}",
            created_at=base.replace(day=1, hour=0, minute=i % 60, second=0),
        ))
    index_text = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert len(index_text.splitlines()) <= 200
    # Overflow spilled into an archive file
    archives = list(tmp_path.glob("MEMORY-archive-*.md"))
    assert archives, "expected at least one MEMORY-archive-*.md file"


# --------------------------------------------------------------------------- #
# atomic write                                                                 #
# --------------------------------------------------------------------------- #

def test_atomic_write_leaves_no_tmp_file(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    store.write(_memory(name="atomic"))
    tmps = list(tmp_path.glob("*.tmp")) + list(tmp_path.glob(".*.tmp"))
    assert tmps == []


def test_pre_existing_tmp_file_does_not_break_read(tmp_path: Path) -> None:
    """A leftover .tmp file (simulated crash mid-write) must not be
    returned as a memory by list() or cause read() to raise."""
    store = MemoryStore(memory_dir=tmp_path)
    store.write(_memory(name="real"))
    # Simulate a crash partway through an atomic rename: a stray .tmp.
    (tmp_path / "orphan.md.tmp").write_text("partial garbage", encoding="utf-8")
    names = [m.name for m in store.list()]
    assert names == ["real"]


# --------------------------------------------------------------------------- #
# listing order                                                                #
# --------------------------------------------------------------------------- #

def test_list_sorted_by_name(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    store.write(_memory(name="charlie"))
    store.write(_memory(name="alpha"))
    store.write(_memory(name="bravo"))
    assert [m.name for m in store.list()] == ["alpha", "bravo", "charlie"]


# --------------------------------------------------------------------------- #
# write returns path                                                           #
# --------------------------------------------------------------------------- #

def test_write_returns_path_to_file(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    path = store.write(_memory(name="alpha"))
    assert path == tmp_path / "alpha.md"
    assert path.exists()
