"""CLI contract tests for runner.py."""

from __future__ import annotations

from click.testing import CliRunner

from runner import cli


def test_cli_exposes_run_group_with_expected_subcommands() -> None:
    """CLI should expose `run` group with all required workflow commands."""
    run_group = cli.commands.get("run")
    assert run_group is not None
    expected = {"agent", "observe", "optimize", "loop", "eval", "status"}
    assert expected.issubset(set(run_group.commands.keys()))


def test_run_status_command_executes_with_empty_state(tmp_path) -> None:
    """`run status` should succeed even with fresh DB/config/memory files."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run",
            "status",
            "--db",
            str(tmp_path / "conversations.db"),
            "--configs-dir",
            str(tmp_path / "configs"),
            "--memory-db",
            str(tmp_path / "memory.db"),
        ],
    )
    assert result.exit_code == 0
    assert "Conversations:" in result.output
