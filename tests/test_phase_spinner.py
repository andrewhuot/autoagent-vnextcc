"""Tests for cli.progress.PhaseSpinner — long-running op loading indicator."""

from __future__ import annotations

import io
import os
import sys
import time

import pytest

from cli.progress import PhaseSpinner, _spinner_enabled


class _FakeTTY(io.StringIO):
    """StringIO that claims to be a TTY so spinner activates under test."""

    def isatty(self) -> bool:
        return True

    @property
    def encoding(self) -> str:  # noqa: D401
        return "utf-8"


def test_spinner_disabled_for_non_text_output_format() -> None:
    assert _spinner_enabled("json") is False
    assert _spinner_enabled("stream-json") is False


def test_spinner_disabled_when_stdout_is_not_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    assert _spinner_enabled("text") is False


def test_spinner_respects_agentlab_no_spinner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTLAB_NO_SPINNER", "1")
    monkeypatch.setattr(sys, "stdout", _FakeTTY())
    assert _spinner_enabled("text") is False


def test_spinner_disabled_in_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")
    monkeypatch.setattr(sys, "stdout", _FakeTTY())
    assert _spinner_enabled("text") is False


def test_spinner_prints_final_check_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """When enabled, a successful phase ends with a green check and elapsed time."""
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("AGENTLAB_NO_SPINNER", raising=False)
    fake = _FakeTTY()
    monkeypatch.setattr(sys, "stdout", fake)

    with PhaseSpinner("Demo phase", output_format="text") as spinner:
        spinner.update("Demo phase step 2")
        time.sleep(0.15)

    output = fake.getvalue()
    assert "Demo phase step 2" in output
    assert "✓" in output
    assert "s)" in output  # elapsed seconds rendered


def test_spinner_no_output_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """When disabled (non-TTY), PhaseSpinner is a silent no-op."""
    monkeypatch.setattr(sys, "stdout", io.StringIO())

    out = io.StringIO()
    # Redirect during the with-block only; after exit, stdout is already fake.
    monkeypatch.setattr(sys, "stdout", out)
    with PhaseSpinner("Silent phase", output_format="text"):
        time.sleep(0.05)
    assert out.getvalue() == ""


def test_spinner_marks_failure_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the phase raises, PhaseSpinner ends with a red ✗ and still cleans up."""
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("AGENTLAB_NO_SPINNER", raising=False)
    fake = _FakeTTY()
    monkeypatch.setattr(sys, "stdout", fake)

    with pytest.raises(RuntimeError):
        with PhaseSpinner("Will fail", output_format="text"):
            raise RuntimeError("boom")

    assert "✗" in fake.getvalue()
