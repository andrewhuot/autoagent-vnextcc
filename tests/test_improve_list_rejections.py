"""CLI e2e tests for R1.8: reason column & --reason filter in improve list."""
from __future__ import annotations

import os
import subprocess
import sys


def _run_improve_list(*args: str, env_override: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if env_override:
        env.update(env_override)
    return subprocess.run(
        [sys.executable, "-m", "runner", "improve", "list", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )


def test_improve_group_is_visible_in_help():
    result = subprocess.run(
        [sys.executable, "-m", "runner", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "improve" in result.stdout.lower()


def test_improve_list_header_includes_reason_column():
    result = _run_improve_list(
        "--json",
        env_override={"AGENTLAB_TEST_FORCE_REJECTION": "regression_detected"},
    )
    assert result.returncode == 0, result.stderr
    assert '"reason"' in result.stdout
    assert '"regression_detected"' in result.stdout


def test_improve_list_text_shows_reason():
    result = _run_improve_list(
        env_override={"AGENTLAB_TEST_FORCE_REJECTION": "safety_violation"},
    )
    assert result.returncode == 0, result.stderr
    assert "REASON" in result.stdout
    assert "safety_violation" in result.stdout


def test_improve_list_reason_filter_matches():
    result = _run_improve_list(
        "--reason", "regression_detected", "--json",
        env_override={"AGENTLAB_TEST_FORCE_REJECTION": "regression_detected"},
    )
    assert result.returncode == 0
    assert '"regression_detected"' in result.stdout


def test_improve_list_reason_filter_excludes():
    result = _run_improve_list(
        "--reason", "safety_violation", "--json",
        env_override={"AGENTLAB_TEST_FORCE_REJECTION": "regression_detected"},
    )
    assert result.returncode == 0
    # Forced rejection has reason=regression_detected, filter asks for safety_violation,
    # so no match — either empty items list or "No improvements found."
    assert '"regression_detected"' not in result.stdout


def test_improve_list_reason_filter_invalid_value():
    result = _run_improve_list("--reason", "totally_bogus")
    assert result.returncode == 1
    assert "totally_bogus" in result.stderr or "totally_bogus" in result.stdout
    # Should list valid values in error message
    assert "regression_detected" in (result.stderr + result.stdout)


def test_forced_rejection_invalid_env_ignored():
    """Invalid AGENTLAB_TEST_FORCE_REJECTION should be silently ignored."""
    result = _run_improve_list(
        "--json",
        env_override={"AGENTLAB_TEST_FORCE_REJECTION": "not_a_real_reason"},
    )
    # Should not crash; just not inject a forced row
    assert result.returncode == 0
