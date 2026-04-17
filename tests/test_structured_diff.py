"""Tests for the structured diff helper + widget.

Pins the branch-native P1b contract:

- ``build_diff_lines`` is pure and width-sensitive.
- Side-by-side layout is used on wide viewports, unified on narrow ones.
- Binary-ish input degrades to a single safe row.
- Cache hits and LRU eviction are observable.
- Missing ``pygments`` falls back to plain text.
"""

from __future__ import annotations

from collections.abc import Callable

from cli.workbench_app.tui.widgets.structured_diff import (
    STRUCTURED_DIFF_CACHE_MAX,
    StructuredDiff,
    build_diff_lines,
    clear_diff_cache,
    diff_cache_size,
)


def test_build_diff_lines_uses_side_by_side_layout_on_wide_viewports() -> None:
    rows = build_diff_lines(
        "def add(x, y):\n    return x + y\n",
        "def add(x, y):\n    return x - y\n",
        language="python",
        width=120,
    )

    assert rows
    assert all(row.layout == "side_by_side" for row in rows)
    assert any(row.left_text == "    return x + y" for row in rows)
    assert any(row.right_text == "    return x - y" for row in rows)


def test_build_diff_lines_falls_back_to_unified_on_narrow_viewports() -> None:
    rows = build_diff_lines(
        "alpha\nbeta\ngamma\n",
        "alpha\nbeta changed\ngamma\n",
        language="text",
        width=72,
    )

    assert rows
    assert all(row.layout == "unified" for row in rows)
    assert any(row.text.startswith("-") and "beta" in row.text for row in rows)
    assert any(row.text.startswith("+") and "beta changed" in row.text for row in rows)


def test_build_diff_lines_detects_binary_content() -> None:
    rows = build_diff_lines("a\x00b", "a\x00c", language=None, width=120)

    assert len(rows) == 1
    assert rows[0].kind == "binary"
    assert "Binary" in rows[0].text


def test_build_diff_lines_cache_hit_and_clear() -> None:
    clear_diff_cache()

    first = build_diff_lines("one\n", "two\n", language="text", width=120)
    size_after_first = diff_cache_size()
    second = build_diff_lines("one\n", "two\n", language="text", width=120)

    assert size_after_first == 1
    assert diff_cache_size() == 1
    assert first == second

    clear_diff_cache()
    assert diff_cache_size() == 0


def test_build_diff_lines_cache_evicts_lru_entries() -> None:
    clear_diff_cache()

    for index in range(STRUCTURED_DIFF_CACHE_MAX + 1):
        build_diff_lines(
            f"old {index}\n",
            f"new {index}\n",
            language="text",
            width=120,
        )

    assert diff_cache_size() == STRUCTURED_DIFF_CACHE_MAX


def test_build_diff_lines_falls_back_when_pygments_is_unavailable(
    monkeypatch,
) -> None:
    import cli.workbench_app.tui.widgets.structured_diff as structured_diff

    monkeypatch.setattr(structured_diff, "_load_pygments", lambda: None)

    widget = StructuredDiff(
        old="const value = 1;\n",
        new="const value = 2;\n",
        language="typescript",
        width=120,
    )

    rendered = widget.render()

    assert rendered is not None
    assert any(row.left_text == "const value = 1;" for row in widget.rows)
    assert any(row.right_text == "const value = 2;" for row in widget.rows)


def test_structured_diff_widget_refresh_is_guarded_when_unmounted() -> None:
    widget = StructuredDiff(
        old="one\n",
        new="two\n",
        language="text",
        width=120,
    )

    widget.update_diff(old="left\n", new="right\n", language="text", width=90)

    assert widget.rows
    assert isinstance(widget.rows[0].text, str)


def test_structured_diff_widget_update_width_switches_to_unified_layout() -> None:
    widget = StructuredDiff(
        old="alpha\nbeta\ngamma\n",
        new="alpha\nbeta changed\ngamma\n",
        language="text",
        width=None,
    )

    widget.update_width(72)

    assert widget.rows
    assert all(row.layout == "unified" for row in widget.rows)
