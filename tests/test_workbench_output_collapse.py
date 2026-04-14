"""Tests for :mod:`cli.workbench_app.output_collapse` (T18b — Ctrl-O expand)."""

from __future__ import annotations

import pytest
import click

from cli.workbench_app.output_collapse import (
    DEFAULT_COLLAPSE_THRESHOLD,
    CollapsibleOutput,
    format_summary,
)


# ---------------------------------------------------------------------------
# CollapsibleOutput
# ---------------------------------------------------------------------------


def test_default_threshold_matches_claude_ten_lines() -> None:
    assert DEFAULT_COLLAPSE_THRESHOLD == 10


def test_append_and_line_count() -> None:
    buf = CollapsibleOutput()
    buf.append("a")
    buf.append("b")
    assert buf.line_count == 2
    assert buf.lines == ("a", "b")


def test_extend_adds_multiple_in_order() -> None:
    buf = CollapsibleOutput()
    buf.extend(["a", "b", "c"])
    assert buf.lines == ("a", "b", "c")


def test_clear_empties_the_buffer_but_keeps_flag() -> None:
    buf = CollapsibleOutput(collapsed=True)
    buf.extend(["x"] * 20)
    assert buf.is_collapsed is True
    buf.clear()
    assert buf.line_count == 0
    assert buf.lines == ()
    assert buf.collapsed is True  # flag untouched


def test_is_collapsible_requires_strictly_more_than_threshold() -> None:
    buf = CollapsibleOutput(collapse_threshold=3)
    buf.extend(["a", "b", "c"])
    assert buf.is_collapsible is False
    buf.append("d")
    assert buf.is_collapsible is True


def test_short_buffer_renders_in_full_regardless_of_flag() -> None:
    buf = CollapsibleOutput(collapse_threshold=5, collapsed=True)
    buf.extend(["a", "b", "c"])
    assert buf.is_collapsed is False
    assert buf.render(color=False) == ["a", "b", "c"]


def test_collapsed_long_buffer_renders_summary() -> None:
    buf = CollapsibleOutput(collapse_threshold=2, collapsed=True)
    buf.extend(["line-1", "line-2", "line-3", "line-4"])
    rendered = buf.render(color=False)
    assert len(rendered) == 1
    assert "4 lines hidden" in rendered[0]
    assert "Ctrl-O" in rendered[0]


def test_expanded_long_buffer_renders_full_lines() -> None:
    buf = CollapsibleOutput(collapse_threshold=2, collapsed=False)
    buf.extend(["line-1", "line-2", "line-3", "line-4"])
    assert buf.render(color=False) == ["line-1", "line-2", "line-3", "line-4"]


def test_toggle_flips_state_on_collapsible_buffer() -> None:
    buf = CollapsibleOutput(collapse_threshold=1, collapsed=True)
    buf.extend(["a", "b", "c"])
    assert buf.is_collapsed is True
    assert buf.toggle() is False
    assert buf.is_collapsed is False
    assert buf.toggle() is True
    assert buf.is_collapsed is True


def test_toggle_is_noop_on_short_buffer() -> None:
    buf = CollapsibleOutput(collapse_threshold=5, collapsed=True)
    buf.extend(["a", "b"])
    # Short — toggle is a no-op; flag stays as-is.
    assert buf.toggle() is True
    assert buf.collapsed is True


def test_expand_force_shows_full_view_even_on_short_buffer() -> None:
    buf = CollapsibleOutput(collapse_threshold=5, collapsed=True)
    buf.extend(["a", "b"])
    buf.expand()
    assert buf.collapsed is False


def test_collapse_force_sets_flag_but_short_still_renders_full() -> None:
    buf = CollapsibleOutput(collapse_threshold=5, collapsed=False)
    buf.extend(["a", "b"])
    buf.collapse()
    # Flag set, but buffer is short so is_collapsed is still False.
    assert buf.collapsed is True
    assert buf.is_collapsed is False
    assert buf.render(color=False) == ["a", "b"]


def test_summary_includes_token_count_when_set() -> None:
    buf = CollapsibleOutput(collapse_threshold=2, collapsed=True)
    buf.extend(["a", "b", "c", "d"])
    buf.set_token_count(1800)
    summary = buf.summary(color=False)
    assert "4 lines hidden" in summary
    assert "1.8k tok" in summary
    assert "Ctrl-O" in summary


def test_summary_omits_token_count_when_unset() -> None:
    buf = CollapsibleOutput(collapse_threshold=1, collapsed=True)
    buf.extend(["a", "b"])
    summary = buf.summary(color=False)
    assert "tok" not in summary


def test_set_token_count_rejects_negative() -> None:
    buf = CollapsibleOutput()
    with pytest.raises(ValueError):
        buf.set_token_count(-1)


def test_set_token_count_accepts_none_to_clear() -> None:
    buf = CollapsibleOutput()
    buf.set_token_count(500)
    buf.set_token_count(None)
    assert buf.token_count is None


def test_lines_snapshot_is_immutable_tuple() -> None:
    buf = CollapsibleOutput()
    buf.extend(["a", "b"])
    snap = buf.lines
    assert isinstance(snap, tuple)
    buf.append("c")
    # Prior snapshot unaffected.
    assert snap == ("a", "b")


def test_render_returns_fresh_list_not_internal_buffer() -> None:
    buf = CollapsibleOutput(collapse_threshold=5, collapsed=False)
    buf.extend(["a", "b"])
    out = buf.render(color=False)
    out.append("mutated")
    # Internal buffer untouched.
    assert buf.lines == ("a", "b")


def test_render_colored_default_unstyles_to_plain() -> None:
    buf = CollapsibleOutput(collapse_threshold=1, collapsed=True)
    buf.extend(["a", "b", "c"])
    styled = buf.render()
    plain = buf.render(color=False)
    assert [click.unstyle(line) for line in styled] == plain


# ---------------------------------------------------------------------------
# format_summary
# ---------------------------------------------------------------------------


def test_format_summary_plural_vs_singular() -> None:
    assert "1 line hidden" in format_summary(1, None, color=False)
    assert "2 lines hidden" in format_summary(2, None, color=False)


def test_format_summary_zero_renders_as_plural() -> None:
    # Edge case — "0 lines hidden" reads better than "0 line hidden".
    summary = format_summary(0, None, color=False)
    assert "0 lines hidden" in summary


def test_format_summary_formats_token_scales() -> None:
    assert "999 tok" in format_summary(1, 999, color=False)
    assert "1.0k tok" in format_summary(1, 1000, color=False)
    assert "2.5k tok" in format_summary(1, 2500, color=False)
    assert "1.0M tok" in format_summary(1, 1_000_000, color=False)


def test_format_summary_always_mentions_ctrl_o() -> None:
    assert "press Ctrl-O to expand" in format_summary(1, None, color=False)


def test_format_summary_colored_is_dim() -> None:
    styled = format_summary(5, None)
    plain = format_summary(5, None, color=False)
    assert click.unstyle(styled) == plain
    assert "\x1b[" in styled
