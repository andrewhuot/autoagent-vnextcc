from __future__ import annotations

from pathlib import Path

from cli.paste.placeholders import expand_placeholders, render_placeholder
from cli.paste.store import PasteStore
from cli.workbench_app.input_router import externalize_paste


def test_render_placeholder_uses_display_number_and_extra_lines(tmp_path: Path) -> None:
    store = PasteStore(tmp_path / "pastes")
    handle = store.store("first\nsecond\nthird\n")

    assert render_placeholder(handle) == "[Pasted text #1 +2 lines]"


def test_expand_placeholders_restores_full_content(tmp_path: Path) -> None:
    store = PasteStore(tmp_path / "pastes")
    handle = store.store("alpha\nbeta\n")
    placeholder = render_placeholder(handle)

    expanded = expand_placeholders(f"before\n{placeholder}\nafter", store)

    assert expanded == "before\nalpha\nbeta\n\nafter"


def test_externalize_paste_leaves_small_inline_text_unchanged(tmp_path: Path) -> None:
    store = PasteStore(tmp_path / "pastes")

    result = externalize_paste(
        "short text",
        paste_store=store,
        inline_threshold_bytes=2048,
        pasted=True,
    )

    assert result.raw_text == "short text"
    assert result.display_text == "short text"
    assert result.handle is None


def test_externalize_paste_replaces_large_paste_with_placeholder(tmp_path: Path) -> None:
    store = PasteStore(tmp_path / "pastes")
    text = "line\n" * 600

    result = externalize_paste(
        text,
        paste_store=store,
        inline_threshold_bytes=64,
        pasted=True,
    )

    assert result.raw_text == text
    assert result.display_text == "[Pasted text #1 +599 lines]"
    assert result.handle is not None
