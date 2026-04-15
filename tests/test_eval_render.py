"""Tests for the polished CLI eval scorecard renderer."""

from __future__ import annotations

from types import SimpleNamespace

import click

from cli.eval_render import render_eval_scorecard


def _score(**overrides):
    """Build a lightweight CompositeScore-like object for renderer tests."""
    data = {
        "quality": 0.82,
        "safety": 0.75,
        "latency": 0.93,
        "cost": 0.88,
        "composite": 0.84,
        "confidence_intervals": {
            "quality": (0.7, 0.9),
            "composite": (0.76, 0.91),
        },
        "safety_failures": 1,
        "total_cases": 8,
        "passed_cases": 7,
        "total_tokens": 1234,
        "estimated_cost_usd": 0.0123,
        "warnings": ["Mock mode is simulated."],
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_eval_scorecard_renders_panes_bars_and_warnings() -> None:
    """The eval summary should look like a structured CLI card, not a metric dump."""
    lines = render_eval_scorecard(
        _score(),
        heading="Full eval suite",
        mode_label="MOCK MODE - simulated",
        status_label="Healthy",
        next_action="agentlab optimize --cycles 3",
        width=72,
        color=False,
    )
    plain = click.unstyle("\n".join(lines))

    assert " Eval Results " in plain
    assert "Full eval suite" in plain
    assert "7/8 passed" in plain
    assert "Composite" in plain
    assert "████" in plain
    assert "Mock mode is simulated." in plain
    assert "agentlab optimize --cycles 3" in plain


def test_eval_scorecard_fits_narrow_terminals() -> None:
    """Renderer output should stay bounded for narrow transcript panes."""
    lines = render_eval_scorecard(
        _score(),
        heading="Safety regression suite with a long descriptive name",
        mode_label="MIXED MODE - live with fallback",
        status_label="Needs attention",
        width=40,
        color=False,
    )

    plain_lines = [click.unstyle(line) for line in lines]
    assert plain_lines
    assert all(len(line) <= 40 for line in plain_lines)
