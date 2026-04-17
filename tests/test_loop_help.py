"""Verify `agentlab loop` is visible in CLI help after R6.1 un-hiding.

Task C7 removes ``hidden=True`` from the loop group (and its ``run``
subcommand) so users can discover the optimization loop from plain
``agentlab --help`` instead of ``agentlab advanced``. These tests lock
in that visibility and the schedule modes exposed by ``loop run``.
"""
from __future__ import annotations

import re

import pytest
from click.testing import CliRunner

from runner import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_loop_visible_in_top_level_help(runner: CliRunner) -> None:
    """`agentlab --help` must list the loop command (no `--all` required)."""
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0, result.output
    # Match a help line like "  loop          Run the optimization loop..."
    assert re.search(r"(?m)^\s+loop\b", result.output), (
        "Expected `loop` command to appear in top-level help.\n"
        f"Output:\n{result.output}"
    )


def test_loop_group_help_renders(runner: CliRunner) -> None:
    """`agentlab loop --help` must render without error and describe the loop."""
    result = runner.invoke(cli, ["loop", "--help"])
    assert result.exit_code == 0, result.output
    assert "optimization loop" in result.output.lower()


def test_loop_run_exposes_schedule_modes(runner: CliRunner) -> None:
    """`agentlab loop run --help` must advertise the schedule modes."""
    result = runner.invoke(cli, ["loop", "run", "--help"])
    assert result.exit_code == 0, result.output
    for mode in ("continuous", "interval", "cron"):
        assert mode in result.output, (
            f"Expected schedule mode '{mode}' in loop run --help.\n"
            f"Output:\n{result.output}"
        )
