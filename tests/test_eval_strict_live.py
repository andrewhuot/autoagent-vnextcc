"""Tests for --strict-live integration in eval command.

We test the integration by exercising StrictLivePolicy with synthetic
warnings of the same shape that runner.py emits at lines 3491-3512.
The full subprocess E2E test lives in tests/test_strict_live_propagation.py
(added in R1.4) which covers eval, optimize, and build together.
"""

import pytest
from cli.strict_live import StrictLivePolicy, MockFallbackError
from cli.exit_codes import EXIT_MOCK_FALLBACK


def test_strict_live_disabled_does_not_raise_on_mock_fallback_warnings():
    """The default behavior (strict_live=False) must remain back-compatible:
    mock fallback warnings are recorded but no exception is raised."""
    policy = StrictLivePolicy(enabled=False)
    policy.ingest_existing_warnings([
        "eval_run.live_fallback_to_mock: gemini 429",
        "eval_run.live_fallback_to_mock: switched to mock_agent_response",
    ])
    policy.check()  # must not raise


def test_strict_live_enabled_raises_when_post_hoc_warnings_present():
    """The exact pattern from runner.py:3491-3512: post-hoc warnings get
    written to score.warnings; with --strict-live the policy must raise."""
    policy = StrictLivePolicy(enabled=True)
    score_warnings = [
        "eval_run.live_fallback_to_mock: gemini 429 — used mock_agent_response"
    ]
    policy.ingest_existing_warnings(score_warnings)
    with pytest.raises(MockFallbackError) as exc:
        policy.check()
    assert "live_fallback_to_mock" in str(exc.value) or "mock execution" in str(exc.value).lower()


def test_exit_code_constant_is_used():
    """Sanity check that the constant the eval command will exit with is 12."""
    assert EXIT_MOCK_FALLBACK == 12
