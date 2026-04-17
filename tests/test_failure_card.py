"""Tests for the failure preview card module (R4.8).

The ``failure_card`` module renders a Rich/Textual markup "card" for each
failed eval case, with input/expected/actual/diff + a one-line suggested-fix
hint pulled from the existing failure analyzer.

These tests exercise:

1. Basic markup contents — each labeled line is present for a canonical case.
2. A golden-string snapshot for a canonical fixture so review sees any
   rendering drift (matching the convention used by
   ``test_eval_progress_grid.py``).
3. The deterministic heuristic hint branches of
   :func:`suggest_fix_for_case` when no analysis is passed.
4. Cluster-backed hints: when a ``FailureAnalysis`` is given and one of its
   clusters contains the failing case id, the hint is pulled from the
   cluster's matching ``SurfaceRecommendation.suggested_approach``.
"""

from __future__ import annotations

import pytest

from cli.workbench_app.failure_card import (
    FailedCase,
    render_failure_card,
    suggest_fix_for_case,
)
from optimizer.failure_analyzer import (
    FailureAnalysis,
    FailureCluster,
    SurfaceRecommendation,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _canonical_case() -> FailedCase:
    """A small, deterministic fixture used by the golden snapshot test."""
    return FailedCase(
        case_id="case-001",
        input="What is the capital of France?",
        expected="Paris",
        actual="London",
        diff="- Paris\n+ London",
        error=None,
    )


# Golden snapshot for render_failure_card(_canonical_case(), hint="use a JSON schema").
# Pre-computed unified-diff-style payload colored as: + green, - red, @@ yellow.
GOLDEN_CARD = (
    "[bold]Case case-001[/]\n"
    "[dim]Input:[/] What is the capital of France?\n"
    "[dim]Expected:[/] Paris\n"
    "[dim]Actual:[/] London\n"
    "[dim]Diff:[/]\n"
    "[red]- Paris[/]\n"
    "[green]+ London[/]\n"
    "[bold yellow]Hint:[/] use a JSON schema"
)


# ---------------------------------------------------------------------------
# Render tests
# ---------------------------------------------------------------------------


class TestRenderFailureCard:
    def test_contains_labeled_lines(self) -> None:
        case = _canonical_case()
        rendered = render_failure_card(case, hint="use a JSON schema")
        assert "Case case-001" in rendered
        assert "[dim]Input:[/]" in rendered
        assert "[dim]Expected:[/]" in rendered
        assert "[dim]Actual:[/]" in rendered
        assert "[bold yellow]Hint:[/] use a JSON schema" in rendered

    def test_golden_snapshot(self) -> None:
        rendered = render_failure_card(_canonical_case(), hint="use a JSON schema")
        assert rendered == GOLDEN_CARD

    def test_hint_fallback_when_none(self) -> None:
        rendered = render_failure_card(_canonical_case(), hint=None)
        assert "[bold yellow]Hint:[/] no suggestion available" in rendered

    def test_computes_unified_diff_when_missing(self) -> None:
        case = FailedCase(
            case_id="c-2",
            input="q",
            expected="alpha\nbeta\n",
            actual="alpha\ngamma\n",
            diff=None,
            error=None,
        )
        rendered = render_failure_card(case, hint="x")
        # The computed unified diff should produce at least one + and - line,
        # colored green and red.
        assert "[red]-" in rendered
        assert "[green]+" in rendered

    def test_truncates_long_values(self) -> None:
        long_input = "x" * 500
        case = FailedCase(
            case_id="c-3",
            input=long_input,
            expected="ok",
            actual="ok",
            diff="",
            error=None,
        )
        rendered = render_failure_card(case, hint="x")
        # Truncation uses an ellipsis suffix; 500 chars must not appear in full.
        assert long_input not in rendered
        assert "..." in rendered

    def test_diff_at_sign_colored_yellow(self) -> None:
        case = FailedCase(
            case_id="c-4",
            input="q",
            expected="a",
            actual="b",
            diff="@@ -1 +1 @@\n- a\n+ b",
            error=None,
        )
        rendered = render_failure_card(case, hint="x")
        assert "[yellow]@@ -1 +1 @@[/]" in rendered
        assert "[red]- a[/]" in rendered
        assert "[green]+ b[/]" in rendered


# ---------------------------------------------------------------------------
# Heuristic hint tests
# ---------------------------------------------------------------------------


class TestSuggestFixHeuristic:
    def test_empty_actual(self) -> None:
        case = FailedCase(
            case_id="e1",
            input="q",
            expected="foo",
            actual="",
            diff=None,
            error=None,
        )
        assert suggest_fix_for_case(case) == (
            "Actual output was empty — check generation path"
        )

    def test_none_actual(self) -> None:
        case = FailedCase(
            case_id="e2",
            input="q",
            expected="foo",
            actual=None,  # type: ignore[arg-type]
            diff=None,
            error=None,
        )
        assert suggest_fix_for_case(case) == (
            "Actual output was empty — check generation path"
        )

    def test_errored_case(self) -> None:
        case = FailedCase(
            case_id="e3",
            input="q",
            expected="foo",
            actual="foo",
            diff=None,
            error="Traceback: NullPointerException",
        )
        assert suggest_fix_for_case(case) == "Case errored — see traceback"

    def test_large_divergence(self) -> None:
        # Expected vs actual share almost nothing — distance should exceed 50%.
        case = FailedCase(
            case_id="e4",
            input="q",
            expected="hello world foo bar",
            actual="zzzzz qqqqq mmmmm",
            diff=None,
            error=None,
        )
        assert suggest_fix_for_case(case) == (
            "Large semantic divergence — consider prompt rewrite"
        )

    def test_minor_divergence(self) -> None:
        case = FailedCase(
            case_id="e5",
            input="q",
            expected="hello world",
            actual="hello worlds",
            diff=None,
            error=None,
        )
        assert suggest_fix_for_case(case) == (
            "Minor divergence — check few-shot examples"
        )


# ---------------------------------------------------------------------------
# Analysis-backed hint test
# ---------------------------------------------------------------------------


class TestSuggestFixFromAnalysis:
    def test_hint_pulled_from_cluster_recommendation(self) -> None:
        cluster = FailureCluster(
            cluster_id="cluster-A",
            description="routing mistakes",
            root_cause_hypothesis="router keywords too narrow",
            failure_type="routing_error",
            sample_ids=["case-XYZ", "case-001"],
            affected_agent="root",
            severity=0.8,
            count=2,
        )
        rec = SurfaceRecommendation(
            surface="routing",
            agent_path="root",
            confidence=0.7,
            reasoning="routing_error dominates",
            suggested_approach="Expand routing keywords to cover greetings",
            priority=1,
        )
        analysis = FailureAnalysis(
            clusters=[cluster],
            surface_recommendations=[rec],
            severity_ranking=["cluster-A"],
            summary="",
        )
        case = FailedCase(
            case_id="case-001",
            input="hi",
            expected="greeting_agent",
            actual="default_agent",
            diff=None,
            error=None,
        )
        hint = suggest_fix_for_case(case, analysis=analysis)
        assert hint == "Expand routing keywords to cover greetings"

    def test_falls_back_to_heuristic_when_case_not_in_cluster(self) -> None:
        cluster = FailureCluster(
            cluster_id="cluster-A",
            description="x",
            root_cause_hypothesis="y",
            failure_type="routing_error",
            sample_ids=["somebody-else"],
            affected_agent="root",
            severity=0.5,
            count=1,
        )
        analysis = FailureAnalysis(clusters=[cluster])
        case = FailedCase(
            case_id="lonely-case",
            input="q",
            expected="a",
            actual="",
            diff=None,
            error=None,
        )
        hint = suggest_fix_for_case(case, analysis=analysis)
        # Falls back to empty-actual heuristic.
        assert hint == "Actual output was empty — check generation path"
