"""Test for the --explain-strategy flag on `agentlab optimize` (R3.5)."""

from __future__ import annotations

from click.testing import CliRunner

from optimizer import proposer as prop_mod
from optimizer.proposer import StrategyExplanation
from runner import cli


def test_explain_strategy_prints_formatted_lines(monkeypatch, tmp_path) -> None:
    """With --explain-strategy, we echo one rationale line per ranked strategy.

    We use --dry-run to short-circuit the full optimize pipeline and seed the
    module-level `_LAST_EXPLANATION` slot so the CLI has data to render
    without needing a live reflection engine.
    """
    fake_explanations = [
        StrategyExplanation(
            strategy="tighten_prompt",
            surface="prompting",
            effectiveness=0.70,
            samples=12,
            explored=False,
        ),
        StrategyExplanation(
            strategy="add_tool",
            surface="tools",
            effectiveness=0.05,
            samples=3,
            explored=False,
        ),
    ]
    monkeypatch.setattr(prop_mod, "_LAST_EXPLANATION", fake_explanations)

    cli_runner = CliRunner()
    with cli_runner.isolated_filesystem(temp_dir=str(tmp_path)):
        result = cli_runner.invoke(
            cli,
            ["optimize", "--dry-run", "--explain-strategy"],
        )

    assert result.exit_code == 0, result.output
    assert "selected mutation tighten_prompt" in result.output
    assert "effectiveness=0.70" in result.output
    assert "n=12 samples" in result.output
    assert "selected mutation add_tool" in result.output
    assert "effectiveness=0.05" in result.output


def test_explain_strategy_empty_message(monkeypatch, tmp_path) -> None:
    """When no explanation data is available, we print an informative fallback."""
    monkeypatch.setattr(prop_mod, "_LAST_EXPLANATION", [])

    cli_runner = CliRunner()
    with cli_runner.isolated_filesystem(temp_dir=str(tmp_path)):
        result = cli_runner.invoke(
            cli,
            ["optimize", "--dry-run", "--explain-strategy"],
        )

    assert result.exit_code == 0, result.output
    assert "No strategy explanation available" in result.output


def test_without_flag_no_explanation_output(monkeypatch, tmp_path) -> None:
    """Without --explain-strategy, no rationale lines are printed."""
    monkeypatch.setattr(
        prop_mod,
        "_LAST_EXPLANATION",
        [
            StrategyExplanation(
                strategy="tighten_prompt",
                surface="prompting",
                effectiveness=0.70,
                samples=12,
                explored=False,
            )
        ],
    )

    cli_runner = CliRunner()
    with cli_runner.isolated_filesystem(temp_dir=str(tmp_path)):
        result = cli_runner.invoke(cli, ["optimize", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "selected mutation" not in result.output
