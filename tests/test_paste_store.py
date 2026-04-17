from __future__ import annotations

from pathlib import Path

from cli.paste.store import PasteStore


def test_store_deduplicates_by_content_hash(tmp_path: Path) -> None:
    store = PasteStore(tmp_path / "pastes")

    first = store.store("alpha\nbeta\n")
    second = store.store("alpha\nbeta\n")

    assert first.id == second.id
    assert first.display_number == second.display_number
    assert store.load(first.id) == "alpha\nbeta\n"


def test_store_tracks_line_count_preview_and_display_number(tmp_path: Path) -> None:
    store = PasteStore(tmp_path / "pastes")

    handle = store.store("first line\nsecond line\nthird line\n")

    assert handle.line_count == 3
    assert handle.preview == "first line"
    assert handle.display_number == 1


def test_store_assigns_incrementing_display_numbers_for_unique_content(tmp_path: Path) -> None:
    store = PasteStore(tmp_path / "pastes")

    first = store.store("first")
    second = store.store("second")

    assert first.display_number == 1
    assert second.display_number == 2
