"""Tests for Ink-inspired terminal rendering primitives used by Workbench."""

from __future__ import annotations

import click

from cli.terminal_renderer import (
    render_divider,
    render_pane,
    render_progress_bar,
    render_status_footer,
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
