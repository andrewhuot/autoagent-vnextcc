"""Tests for Ink-inspired terminal rendering primitives used by Workbench."""

from __future__ import annotations

import click
import pytest

from cli.terminal_renderer import (
    render_box,
    render_divider,
    render_pane,
    render_progress_bar,
    render_status_footer,
    supports_unicode_box,
)


def _plain(lines: list[str]) -> list[str]:
    return [click.unstyle(line) for line in lines]


def test_progress_bar_clamps_ratio_and_keeps_stable_width() -> None:
    assert render_progress_bar(-1.0, width=8, color=False) == "        "
    assert render_progress_bar(1.5, width=8, color=False) == "████████"


def test_progress_bar_renders_fractional_block_segments() -> None:
    bar = render_progress_bar(0.3125, width=8, color=False)
    assert bar == "██▌     "
    assert len(bar) == 8


def test_divider_centers_title_within_requested_width() -> None:
    line = click.unstyle(render_divider("Status", width=24, color=False))
    assert len(line) == 24
    assert " Status " in line
    assert line.startswith("─")
    assert line.endswith("─")


def test_pane_wraps_body_without_exceeding_width() -> None:
    lines = _plain(
        render_pane(
            "Slash Commands",
            ["Use /status to inspect the active workspace and current candidate."],
            width=36,
            color=False,
        )
    )

    assert " Slash Commands " in lines[0]
    assert all(len(line) <= 36 for line in lines)
    assert lines[1:] == [
        "  Use /status to inspect the active",
        "  workspace and current candidate.",
    ]


def test_render_box_wraps_body_in_rounded_corners() -> None:
    if not supports_unicode_box():
        pytest.skip("Terminal encoding can't render rounded corners")
    lines = _plain(
        render_box(["Welcome", "cwd: /tmp/x"], width=32, color=False, padding=1)
    )
    assert lines[0].startswith("╭") and lines[0].endswith("╮")
    assert lines[-1].startswith("╰") and lines[-1].endswith("╯")
    # Interior lines are framed by the vertical bar on both sides.
    for middle in lines[1:-1]:
        assert middle.startswith("│") and middle.endswith("│")
        assert len(middle) == 32


def test_render_box_keeps_title_in_top_border() -> None:
    if not supports_unicode_box():
        pytest.skip("Terminal encoding can't render rounded corners")
    lines = _plain(
        render_box(["body"], title="Welcome", width=32, color=False)
    )
    assert " Welcome " in lines[0]
    assert lines[0].startswith("╭")
    assert lines[0].endswith("╮")


def test_render_box_color_false_strips_ansi() -> None:
    # Even when ``color=False`` the box chrome still appears — just without
    # ANSI escapes so tests and piped output stay clean.
    lines = render_box(["hi"], width=20, color=False)
    assert all("\x1b[" not in line for line in lines)
    # Top/bottom borders plus one body line.
    assert len(lines) == 3


def test_render_box_wraps_long_lines_within_inner_width() -> None:
    if not supports_unicode_box():
        pytest.skip("Terminal encoding can't render rounded corners")
    long_text = "word " * 20  # ~100 chars, must wrap inside a 30-col box.
    lines = _plain(render_box([long_text.strip()], width=30, color=False, padding=1))
    body = lines[1:-1]
    # Every interior line fits within the box width.
    assert all(len(line) == 30 for line in body)
    # The wrapped content must cover multiple rows.
    assert len(body) >= 2


def test_status_footer_keeps_keyboard_affordances_visible() -> None:
    lines = _plain(
        render_status_footer(
            mode="plan",
            shells=2,
            tasks=1,
            width=48,
            color=False,
        )
    )

    assert len(lines) == 2
    assert len(lines[0]) == 48
    assert lines[1] == "⏵ plan permissions on · 2 shells, 1 task"
