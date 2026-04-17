"""Failure preview cards for eval failures (R4.8).

Renders a Textual-markup "card" for each failed eval case, with
input/expected/actual/diff + a one-line suggested-fix hint pulled
(optionally) from the existing :mod:`optimizer.failure_analyzer`.

### Rendering model

The module returns plain Rich/Textual markup strings (no Rich ``Panel``
objects) so callers can:

- Drop the string into a :class:`~textual.widgets.Static` (matching the
  convention used by :mod:`cli.workbench_app.tui.widgets.effort_indicator_widget`
  and :mod:`cli.workbench_app.eval_progress_grid`).
- Or print it directly to a Rich console.

### Hint source

Two modes:

1. **Cluster-backed** — when a :class:`FailureAnalysis` is given, find the
   cluster containing the failing ``case_id`` and return the matching
   :attr:`SurfaceRecommendation.suggested_approach`.
2. **Deterministic heuristic** — when no analysis is available, derive a
   hint from the failure shape (empty actual, exception, large divergence,
   minor divergence). Deterministic so the snapshot tests stay stable and
   so the card can render without an LLM round-trip.

We intentionally do **not** run the LLM-backed
:class:`~optimizer.failure_analyzer.FailureAnalyzer` here: cards are
rendered per case and a full analysis is expensive. Callers that want
cluster-backed hints should run the analyzer once and pass the result in.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from optimizer.failure_analyzer import FailureAnalysis


# Truncation budget for input/expected/actual lines on the card. ~120 chars
# keeps a single line of markup readable in a standard terminal (~80–120
# columns) without wrapping awkwardly.
_TRUNCATE_AT = 120
_ELLIPSIS = "..."


@dataclass
class FailedCase:
    """A single failed eval case, suitable for card rendering.

    ``diff`` is optional; when ``None``, the card computes a unified diff
    between ``expected`` and ``actual`` inline via :func:`difflib.unified_diff`.
    ``error`` is populated for the ``error`` status — a traceback or
    exception message — and is the signal that drives the "Case errored"
    heuristic hint.
    """

    case_id: str
    input: str
    expected: str
    actual: str
    diff: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _truncate(value: str, limit: int = _TRUNCATE_AT) -> str:
    """Truncate ``value`` to ``limit`` chars with an ellipsis suffix.

    Guards against ``None``/non-string inputs — the caller is expected to
    hand us strings, but a bad upstream event must not crash the card.
    """
    if value is None:
        return ""
    text = str(value)
    if len(text) <= limit:
        return text
    # Reserve room for the ellipsis so the visible length stays at ``limit``.
    head = max(0, limit - len(_ELLIPSIS))
    return text[:head] + _ELLIPSIS


def _compute_diff(expected: str, actual: str) -> str:
    """Compute a unified diff between ``expected`` and ``actual``.

    Returns the diff body without the ``---``/``+++`` header lines — the
    card already labels the block with ``Diff:``, and the header lines add
    noise without information.
    """
    expected_lines = (expected or "").splitlines(keepends=False)
    actual_lines = (actual or "").splitlines(keepends=False)
    diff_lines = list(
        difflib.unified_diff(
            expected_lines,
            actual_lines,
            fromfile="expected",
            tofile="actual",
            lineterm="",
        )
    )
    # Drop the leading --- / +++ header lines.
    filtered = [
        line for line in diff_lines
        if not line.startswith("---") and not line.startswith("+++")
    ]
    return "\n".join(filtered)


def _color_diff_line(line: str) -> str:
    """Wrap a single diff line in Textual markup based on its prefix."""
    if line.startswith("@@"):
        return f"[yellow]{line}[/]"
    if line.startswith("+"):
        return f"[green]{line}[/]"
    if line.startswith("-"):
        return f"[red]{line}[/]"
    return line


def render_failure_card(case: FailedCase, hint: str | None = None) -> str:
    """Render a failure preview card as a Textual-markup string.

    The layout is stable and line-based so reviewers can diff snapshots:

    .. code-block:: text

        [bold]Case {case_id}[/]
        [dim]Input:[/] {input (truncated)}
        [dim]Expected:[/] {expected (truncated)}
        [dim]Actual:[/] {actual (truncated)}
        [dim]Diff:[/]
        {unified diff, colored: + green, - red, @@ yellow}
        [bold yellow]Hint:[/] {hint or "no suggestion available"}
    """
    diff_body = case.diff if case.diff is not None else _compute_diff(
        case.expected, case.actual
    )
    colored_diff_lines = [
        _color_diff_line(line) for line in diff_body.splitlines()
    ]

    lines: list[str] = [
        f"[bold]Case {case.case_id}[/]",
        f"[dim]Input:[/] {_truncate(case.input)}",
        f"[dim]Expected:[/] {_truncate(case.expected)}",
        f"[dim]Actual:[/] {_truncate(case.actual)}",
        "[dim]Diff:[/]",
    ]
    lines.extend(colored_diff_lines)
    lines.append(
        f"[bold yellow]Hint:[/] {hint if hint else 'no suggestion available'}"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Hint derivation
# ---------------------------------------------------------------------------


# Levenshtein-ratio threshold above which we call a divergence "large" and
# recommend a prompt rewrite. 0.5 is a rough midpoint — tuned by hand on the
# heuristic test fixtures. Since the heuristic exists only as a deterministic
# fallback for the snapshot test, the exact value doesn't need to be precise.
_LARGE_DIVERGENCE_RATIO = 0.5


def _divergence_ratio(expected: str, actual: str) -> float:
    """Return a divergence ratio in [0.0, 1.0] between two strings.

    Uses :class:`difflib.SequenceMatcher.ratio` as a proxy for 1 − similarity.
    ``0.0`` means identical, ``1.0`` means completely different.
    """
    if not expected and not actual:
        return 0.0
    similarity = difflib.SequenceMatcher(None, expected or "", actual or "").ratio()
    return 1.0 - similarity


def _find_cluster_recommendation(
    case_id: str, analysis: "FailureAnalysis"
) -> str | None:
    """Locate a cluster that references ``case_id`` and return its hint.

    Preference order:

    1. A :class:`SurfaceRecommendation` whose ``agent_path`` matches the
       cluster's ``affected_agent`` (the "primary" recommendation).
    2. Otherwise, the first recommendation associated with the cluster's
       ``failure_type`` surface.
    3. Otherwise, the first recommendation in the whole analysis.

    The attribute pulled is ``suggested_approach`` (matches the dataclass
    defined in :mod:`optimizer.failure_analyzer`). The spec allows
    ``surface_recommendation.text`` as a fallback name; we defensively check
    for it too in case the analyzer's schema drifts.
    """
    matching_cluster = None
    for cluster in analysis.clusters:
        if case_id in cluster.sample_ids:
            matching_cluster = cluster
            break
    if matching_cluster is None:
        return None

    if not analysis.surface_recommendations:
        return None

    # Prefer a recommendation whose agent_path matches the cluster's agent.
    preferred = None
    for rec in analysis.surface_recommendations:
        if rec.agent_path and rec.agent_path == matching_cluster.affected_agent:
            preferred = rec
            break
    rec = preferred or analysis.surface_recommendations[0]

    # Prefer the canonical ``suggested_approach`` attr; fall back to ``text``
    # if a future version of the analyzer renames it.
    text = getattr(rec, "suggested_approach", None) or getattr(rec, "text", None)
    return str(text).strip() if text else None


def suggest_fix_for_case(
    case: FailedCase,
    analysis: "FailureAnalysis | None" = None,
) -> str | None:
    """Produce a one-line suggested-fix hint for ``case``.

    When an ``analysis`` is supplied, try to pull the hint from the
    cluster that contains this ``case_id``. When no analysis is given or
    the case is not in any cluster, fall back to a deterministic
    heuristic over the failure shape.
    """
    if analysis is not None:
        cluster_hint = _find_cluster_recommendation(case.case_id, analysis)
        if cluster_hint:
            return cluster_hint
        # Fall through to heuristic.

    if case.error:
        return "Case errored — see traceback"
    if case.actual is None or case.actual == "":
        return "Actual output was empty — check generation path"

    # If no explicit diff, fall back to expected/actual string comparison.
    divergence = _divergence_ratio(case.expected or "", case.actual or "")
    if divergence > _LARGE_DIVERGENCE_RATIO:
        return "Large semantic divergence — consider prompt rewrite"
    return "Minor divergence — check few-shot examples"


__all__ = [
    "FailedCase",
    "render_failure_card",
    "suggest_fix_for_case",
]
