"""Tests for Magic UX features: streaming, recommendations, status, storytelling."""
from __future__ import annotations

import pytest
from click.testing import CliRunner

from runner import (
    cli,
    _stream_cycle_output,
    _generate_recommendations,
    _bar_chart,


@pytest.fixture
def runner():
    return CliRunner()


# ---------------------------------------------------------------------------
# _bar_chart
# ---------------------------------------------------------------------------

class TestBarChart:
    def test_full_bar(self):
        assert _bar_chart(1.0) == "██████████"

    def test_empty_bar(self):
        assert _bar_chart(0.0) == "░░░░░░░░░░"

    def test_half_bar(self):
        result = _bar_chart(0.5)
        assert "█" in result
        assert "░" in result
        assert len(result) == 10

    def test_custom_width(self):
        result = _bar_chart(1.0, width=5)
        assert result == "█████"
        assert len(result) == 5

    def test_length_always_equals_width(self):
        for pct in [0.0, 0.1, 0.33, 0.5, 0.75, 0.99, 1.0]:
            assert len(_bar_chart(pct, width=10)) == 10


class TestSoulHelpers:
    def test_score_mood_none(self):
        assert _score_mood(None) == "Warming up"

    def test_score_mood_high(self):
        assert _score_mood(0.91) == "Flying"

    def test_score_mood_low(self):
        assert _score_mood(0.4) == "Needs love"

    def test_soul_line_known_context(self):
        assert "learning" in _soul_line("status").lower()

    def test_soul_line_fallback(self):
        assert _soul_line("unknown") == "AutoAgent is online."

    def test_print_cli_plan(self, runner):
        @__import__("click").command()
        def _cmd():
            _print_cli_plan("Plan", ["one", "two"])

        result = runner.invoke(_cmd, [])
        assert "Plan" in result.output
        assert "1. one" in result.output

    def test_print_next_actions(self, runner):
        @__import__("click").command()
        def _cmd():
            _print_next_actions(["autoagent status"])

        result = runner.invoke(_cmd, [])
        assert "Next actions" in result.output
        assert "autoagent status" in result.output


# ---------------------------------------------------------------------------
# _generate_recommendations
# ---------------------------------------------------------------------------

class TestGenerateRecommendations:
    def _make_report(self, buckets: dict[str, int]):
        from observer.metrics import HealthReport, HealthMetrics
        return HealthReport(
            metrics=HealthMetrics(),
            failure_buckets=buckets,
        )

    def test_maps_routing_error_to_runbook(self):
        report = self._make_report({"routing_error": 10, "safety_violation": 3})
        recs = _generate_recommendations(report, None)
        assert len(recs) >= 1
        assert "fix-retrieval-grounding" in recs[0]

    def test_maps_safety_violation_to_runbook(self):
        report = self._make_report({"safety_violation": 5})
        recs = _generate_recommendations(report, None)
        assert len(recs) == 1
        assert "tighten-safety-policy" in recs[0]

    def test_maps_timeout_to_latency_runbook(self):
        report = self._make_report({"timeout": 8})
        recs = _generate_recommendations(report, None)
        assert "reduce-tool-latency" in recs[0]

    def test_maps_tool_failure_to_latency_runbook(self):
        report = self._make_report({"tool_failure": 4})
        recs = _generate_recommendations(report, None)
        assert "reduce-tool-latency" in recs[0]

    def test_maps_unhelpful_response_to_quality_runbook(self):
        report = self._make_report({"unhelpful_response": 6})
        recs = _generate_recommendations(report, None)
        assert "improve-response-quality" in recs[0]

    def test_maps_quality_issue_to_quality_runbook(self):
        report = self._make_report({"quality_issue": 3})
        recs = _generate_recommendations(report, None)
        assert "improve-response-quality" in recs[0]

    def test_empty_buckets(self):
        report = self._make_report({})
        recs = _generate_recommendations(report, None)
        assert recs == []

    def test_returns_at_most_3(self):
        report = self._make_report({
            "routing_error": 10,
            "safety_violation": 8,
            "timeout": 6,
            "tool_failure": 4,
            "quality_issue": 2,
        })
        recs = _generate_recommendations(report, None)
        assert len(recs) <= 3

    def test_sorted_by_count_descending(self):
        report = self._make_report({
            "quality_issue": 2,
            "routing_error": 10,
            "safety_violation": 5,
        })
        recs = _generate_recommendations(report, None)
        # First rec should be for the dominant bucket (routing_error)
        assert "routing_error" in recs[0]

    def test_contains_percentage(self):
        report = self._make_report({"routing_error": 10})
        recs = _generate_recommendations(report, None)
        assert "100%" in recs[0]

    def test_unknown_bucket_gets_default_runbook(self):
        report = self._make_report({"weird_bucket": 5})
        recs = _generate_recommendations(report, None)
        # Should fall back to improve-response-quality
        assert "improve-response-quality" in recs[0]


# ---------------------------------------------------------------------------
# _stream_cycle_output
# ---------------------------------------------------------------------------

class TestStreamCycleOutput:
    def _make_report(self, buckets: dict[str, int]):
        from observer.metrics import HealthReport, HealthMetrics
        return HealthReport(
            metrics=HealthMetrics(),
            failure_buckets=buckets,
        )

    def test_prints_cycle_header(self, runner, capsys):
        report = self._make_report({})
        # Use CliRunner to capture click.echo output
        with runner.isolated_filesystem():
            import io
            from click.testing import CliRunner as CR
            r = CR()

            @__import__("click").command()
            def _cmd():
                _stream_cycle_output(
                    cycle_num=2,
                    total=3,
                    report=report,
                    proposal_desc=None,
                    score_after=None,
                    score_before=None,
                )

            result = r.invoke(_cmd, [])
            assert "Cycle 2/3" in result.output

    def test_prints_diagnosing_with_failures(self, runner):
        report = self._make_report({"routing_error": 5})

        @__import__("click").command()
        def _cmd():
            _stream_cycle_output(1, 1, report, None, 0.85, 0.80)

        result = runner.invoke(_cmd, [])
        assert "Diagnosing" in result.output
        assert "routing_error" in result.output

    def test_prints_accepted_on_improvement(self, runner):
        report = self._make_report({})

        @__import__("click").command()
        def _cmd():
            _stream_cycle_output(1, 1, report, "Fixed routing.", 0.85, 0.80)

        result = runner.invoke(_cmd, [])
        assert "Accepted" in result.output

    def test_prints_rejected_on_no_improvement(self, runner):
        report = self._make_report({})

        @__import__("click").command()
        def _cmd():
            _stream_cycle_output(1, 1, report, None, 0.75, 0.80)

        result = runner.invoke(_cmd, [])
        assert "Rejected" in result.output

    def test_prints_proposal_desc(self, runner):
        report = self._make_report({})

        @__import__("click").command()
        def _cmd():
            _stream_cycle_output(1, 1, report, "Improved billing routing.", 0.85, 0.80)

        result = runner.invoke(_cmd, [])
        assert "Improved billing routing." in result.output

    def test_no_scores_prints_no_change(self, runner):
        report = self._make_report({})

        @__import__("click").command()
        def _cmd():
            _stream_cycle_output(1, 1, report, None, None, None)

        result = runner.invoke(_cmd, [])
        assert "No change" in result.output

    def test_p_value_shown_on_accepted(self, runner):
        report = self._make_report({})

        @__import__("click").command()
        def _cmd():
            _stream_cycle_output(1, 1, report, None, 0.85, 0.80, p_value=0.02)

        result = runner.invoke(_cmd, [])
        assert "p=0.02" in result.output


# ---------------------------------------------------------------------------
# _status_next_action
# ---------------------------------------------------------------------------

class TestStatusNextAction:
    def _make_report(self, buckets: dict[str, int]):
        from observer.metrics import HealthReport, HealthMetrics
        return HealthReport(metrics=HealthMetrics(), failure_buckets=buckets)

    def test_no_attempts_prefers_quickstart(self):
        report = self._make_report({})
        assert _status_next_action(report, attempts_count=0, accepted_count=0) == "autoagent quickstart"

    def test_failures_prefers_runbook(self):
        report = self._make_report({"timeout": 3})
        action = _status_next_action(report, attempts_count=2, accepted_count=0)
        assert action.startswith("autoagent runbook apply")

    def test_multiple_wins_prefers_autopilot_loop(self):
        report = self._make_report({})
        action = _status_next_action(report, attempts_count=6, accepted_count=3)
        assert action == "autoagent loop --max-cycles 20 --stop-on-plateau"


# ---------------------------------------------------------------------------
# autoagent status command
# ---------------------------------------------------------------------------

class TestStatusCommand:
    def test_status_runs(self, runner):
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0, result.output
        assert "AutoAgent Status" in result.output

    def test_status_shows_config(self, runner):
        result = runner.invoke(cli, ["status"])
        assert "Config:" in result.output

    def test_status_shows_eval_score(self, runner):
        result = runner.invoke(cli, ["status"])
        assert "Eval score:" in result.output

    def test_status_shows_safety(self, runner):
        result = runner.invoke(cli, ["status"])
        assert "Safety:" in result.output

    def test_status_shows_cycles(self, runner):
        result = runner.invoke(cli, ["status"])
        assert "Cycles run:" in result.output

    def test_status_shows_loop(self, runner):
        result = runner.invoke(cli, ["status"])
        assert "Loop:" in result.output

    def test_status_shows_next_action(self, runner):
        result = runner.invoke(cli, ["status"])
        assert "Next action:" in result.output


# ---------------------------------------------------------------------------
# Importability checks
# ---------------------------------------------------------------------------

class TestCLIHasNewHelpers:
    def test_stream_cycle_output_importable(self):
        from runner import _stream_cycle_output
        assert callable(_stream_cycle_output)

    def test_generate_recommendations_importable(self):
        from runner import _generate_recommendations
        assert callable(_generate_recommendations)

    def test_bar_chart_importable(self):
        from runner import _bar_chart
        assert callable(_bar_chart)
