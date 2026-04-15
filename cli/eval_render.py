"""Terminal scorecard renderer for CLI eval results."""

from __future__ import annotations

from typing import Any

import click

from cli.terminal_renderer import render_pane, render_progress_bar


_METRICS = (
    ("quality", "Quality"),
    ("safety", "Safety"),
    ("latency", "Latency"),
    ("cost", "Cost"),
    ("composite", "Composite"),
)


def render_eval_scorecard(
    score: Any,
    *,
    heading: str,
    mode_label: str | None = None,
    status_label: str | None = None,
    next_action: str | None = None,
    width: int | None = None,
    color: bool = True,
) -> list[str]:
    """Return a Claude-style eval summary for text CLI output.

    WHY: eval results are one of the main confidence surfaces in AgentLab.
    Rendering them as a stable scorecard makes mock/live mode, pass rate,
    metric health, and the next operator action visible without forcing users
    to parse a raw metric dump.
    """
    total_cases = int(getattr(score, "total_cases", 0) or 0)
    passed_cases = int(getattr(score, "passed_cases", 0) or 0)
    pass_ratio = (passed_cases / total_cases) if total_cases > 0 else 0.0
    status = status_label or _status_from_score(float(getattr(score, "composite", 0.0) or 0.0))

    overview = [
        _strong(heading, color=color),
        f"Status: {_status_text(status, color=color)}",
        f"Cases:  {passed_cases}/{total_cases} passed  {_percent(pass_ratio)}",
    ]
    if mode_label:
        overview.append(f"Mode:   {_mode_text(mode_label, color=color)}")
    overview.append(
        f"Tokens: {int(getattr(score, 'total_tokens', 0) or 0)}  "
        f"Cost: ${float(getattr(score, 'estimated_cost_usd', 0.0) or 0.0):.6f}"
    )

    metric_lines = [_metric_line(score, metric, label, color=color) for metric, label in _METRICS]

    detail_lines: list[str] = []
    warnings = [str(warning) for warning in getattr(score, "warnings", []) or [] if warning]
    if warnings:
        detail_lines.append(_warning("Warning:", color=color))
        detail_lines.extend(warnings)
    if next_action:
        if detail_lines:
            detail_lines.append("")
        detail_lines.append(_strong("Next", color=color))
        detail_lines.append(next_action)

    lines: list[str] = []
    lines.extend(render_pane("Eval Results", overview, width=width, color=color))
    lines.extend(render_pane("Scores", metric_lines, width=width, color=color))
    if detail_lines:
        lines.extend(render_pane("Notes", detail_lines, width=width, color=color))
    return lines


def _metric_line(score: Any, metric: str, label: str, *, color: bool) -> str:
    value = float(getattr(score, metric, 0.0) or 0.0)
    bar = render_progress_bar(value, width=6, color=color)
    line = f"{label + ':':<10} {bar} {value:.4f}"
    if metric == "safety":
        failures = int(getattr(score, "safety_failures", 0) or 0)
        line += f" ({failures} failures)"

    ci = (getattr(score, "confidence_intervals", {}) or {}).get(metric)
    if ci is not None:
        try:
            low, high = ci
        except (TypeError, ValueError):
            return line
        line += f"  95% CI {float(low):.4f}..{float(high):.4f}"
    return line


def _percent(ratio: float) -> str:
    return f"{min(1.0, max(0.0, ratio)) * 100:.0f}%"


def _status_from_score(score: float) -> str:
    if score >= 0.85:
        return "Healthy"
    if score >= 0.70:
        return "Watch"
    return "Needs attention"


def _strong(text: str, *, color: bool) -> str:
    return click.style(text, bold=True) if color else text


def _warning(text: str, *, color: bool) -> str:
    return click.style(text, fg="yellow", bold=True) if color else text


def _status_text(text: str, *, color: bool) -> str:
    lowered = text.lower()
    if "healthy" in lowered:
        fg = "green"
    elif "attention" in lowered or "fail" in lowered:
        fg = "red"
    else:
        fg = "yellow"
    return click.style(text, fg=fg, bold=True) if color else text


def _mode_text(text: str, *, color: bool) -> str:
    lowered = text.lower()
    if "mock" in lowered or "mixed" in lowered or "fallback" in lowered:
        return click.style(text, fg="yellow", bold=True) if color else text
    return click.style(text, fg="green", bold=True) if color else text


__all__ = ["render_eval_scorecard"]
