"""Tests for challenge suites in rewards/challenge_suites.py."""

from __future__ import annotations

import pytest

from rewards.challenge_suites import (
    ChallengeSuiteRunner,
    get_builtin_suites,
)


# ---------------------------------------------------------------------------
# get_builtin_suites
# ---------------------------------------------------------------------------

def test_get_builtin_suites_returns_five():
    suites = get_builtin_suites()
    assert len(suites) == 5


def test_builtin_suite_names():
    suites = get_builtin_suites()
    names = {s.name for s in suites}
    assert "sycophancy" in names
    assert "reward_hacking" in names
    assert "impossible_task" in names
    assert "truthfulness" in names
    assert "shortcut_learning" in names


def test_builtin_suites_have_probes():
    for suite in get_builtin_suites():
        assert len(suite.probes) > 0, f"Suite {suite.name!r} has no probes"


def test_challenge_suite_to_dict():
    suite = get_builtin_suites()[0]
    d = suite.to_dict()
    assert "name" in d
    assert "probes" in d
    assert isinstance(d["probes"], list)


# ---------------------------------------------------------------------------
# ChallengeSuiteRunner.run_suite without reward_fn
# ---------------------------------------------------------------------------

def test_run_suite_without_reward_fn_all_pass():
    runner = ChallengeSuiteRunner()
    suite = get_builtin_suites()[0]
    report = runner.run_suite(suite)

    assert report.suite_name == suite.name
    assert report.total_probes == len(suite.probes)
    assert report.passed == report.total_probes
    assert report.failed == 0
    assert report.pass_rate == pytest.approx(1.0)


def test_run_suite_report_results_count():
    runner = ChallengeSuiteRunner()
    suite = get_builtin_suites()[1]
    report = runner.run_suite(suite)
    assert len(report.results) == suite.total_probes if hasattr(suite, "total_probes") else len(suite.probes)


# ---------------------------------------------------------------------------
# ChallengeSuiteRunner.run_suite with reward_fn
# ---------------------------------------------------------------------------

def test_run_suite_with_reward_fn_that_prefers_correct():
    """A reward function that always rewards the correct response more."""
    def good_reward(response: str, probe) -> float:
        return 1.0 if response == probe.correct_response else 0.0

    runner = ChallengeSuiteRunner()
    suite = get_builtin_suites()[0]
    report = runner.run_suite(suite, reward_fn=good_reward)

    assert report.pass_rate == pytest.approx(1.0)
    assert report.failed == 0


def test_run_suite_with_reward_fn_that_prefers_trap():
    """A reward function that always rewards the trap response (bad reward)."""
    def bad_reward(response: str, probe) -> float:
        return 1.0 if response == probe.trap_response else 0.0

    runner = ChallengeSuiteRunner()
    suite = get_builtin_suites()[0]
    report = runner.run_suite(suite, reward_fn=bad_reward)

    assert report.pass_rate == pytest.approx(0.0)
    assert report.failed == report.total_probes
    assert len(report.findings) == report.total_probes


# ---------------------------------------------------------------------------
# ChallengeSuiteRunner.run_all_builtin
# ---------------------------------------------------------------------------

def test_run_all_builtin_returns_five_reports():
    runner = ChallengeSuiteRunner()
    reports = runner.run_all_builtin()
    assert len(reports) == 5


def test_run_all_builtin_report_names_match_suites():
    runner = ChallengeSuiteRunner()
    suite_names = {s.name for s in get_builtin_suites()}
    report_names = {r.suite_name for r in runner.run_all_builtin()}
    assert suite_names == report_names
