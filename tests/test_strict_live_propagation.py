"""Unit tests for --strict-live integration in optimize and build commands.

We test the exit-code constants and policy behavior directly, plus a
help-output smoke check that the flag is registered.
"""

import subprocess
import sys

import pytest
from cli.strict_live import StrictLivePolicy, MockFallbackError
from cli.exit_codes import EXIT_MOCK_FALLBACK


def test_optimize_help_lists_strict_live():
    """Smoke: --strict-live flag is registered on optimize."""
    result = subprocess.run(
        [sys.executable, "-m", "runner", "optimize", "--help"],
        capture_output=True, text=True, cwd=".",
    )
    assert result.returncode == 0
    assert "--strict-live" in result.stdout


def test_build_help_lists_strict_live():
    """Smoke: --strict-live flag is registered on build run."""
    result = subprocess.run(
        [sys.executable, "-m", "runner", "build", "run", "--help"],
        capture_output=True, text=True, cwd=".",
    )
    assert result.returncode == 0
    assert "--strict-live" in result.stdout


def test_strict_live_policy_raises_mock_fallback_for_proposer_mock_mode():
    """The optimize command should emit a warning of this shape when
    proposer.use_mock is True and --strict-live is set, then exit 12."""
    policy = StrictLivePolicy(enabled=True)
    with pytest.raises(MockFallbackError):
        policy.record_mock_warning(
            "optimize: proposer is in mock mode (no provider key configured)"
        )


def test_strict_live_policy_raises_for_build_pattern_fallback():
    """The build command should emit a warning of this shape when
    live_artifact is None and --strict-live is set."""
    policy = StrictLivePolicy(enabled=True)
    with pytest.raises(MockFallbackError):
        policy.record_mock_warning(
            "build: live LLM unavailable (HTTP 403), used pattern fallback"
        )


def test_exit_code_constant():
    assert EXIT_MOCK_FALLBACK == 12
