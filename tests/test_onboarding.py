"""Tests for cli/onboarding.py — guided onboarding."""

from __future__ import annotations

from unittest.mock import patch

from cli.onboarding import run_onboarding


def test_onboarding_demo_choice() -> None:
    with patch("click.prompt", return_value="1"):
        assert run_onboarding() == "demo"


def test_onboarding_empty_choice() -> None:
    with patch("click.prompt", return_value="2"):
        assert run_onboarding() == "empty"


def test_onboarding_exit_choice() -> None:
    with patch("click.prompt", return_value="3"):
        assert run_onboarding() is None
