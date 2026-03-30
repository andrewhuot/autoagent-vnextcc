"""CLI integration tests for shell, session, continue, memory edit, config edit commands."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from runner import cli


def _make_workspace(tmp_path: Path) -> Path:
    """Scaffold a minimal workspace for CLI tests."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    autoagent_dir = workspace / ".autoagent"
    autoagent_dir.mkdir()
    (autoagent_dir / "workspace.json").write_text(
        json.dumps(
            {
                "name": "test-ws",
                "schema_version": 1,
                "active_config_version": 1,
            }
        ),
        encoding="utf-8",
    )
    configs = workspace / "configs"
    configs.mkdir()
    (configs / "v001.yaml").write_text("model: mock\n", encoding="utf-8")
    (autoagent_dir / "best_score.txt").touch()
    return workspace


def test_shell_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["shell", "--help"])
    assert result.exit_code == 0
    assert "interactive" in result.output.lower() or "shell" in result.output.lower()


def test_session_list_no_workspace(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["session", "list"])
    assert result.exit_code != 0
    assert "No" in result.output or "workspace" in result.output.lower()


def test_session_list_empty(tmp_path: Path, monkeypatch) -> None:
    workspace = _make_workspace(tmp_path)
    monkeypatch.chdir(workspace)
    runner = CliRunner()
    result = runner.invoke(cli, ["session", "list"])
    assert result.exit_code == 0
    assert "No sessions" in result.output


def test_session_list_json_empty(tmp_path: Path, monkeypatch) -> None:
    workspace = _make_workspace(tmp_path)
    monkeypatch.chdir(workspace)
    runner = CliRunner()
    result = runner.invoke(cli, ["session", "list", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == []


def test_session_delete_missing(tmp_path: Path, monkeypatch) -> None:
    workspace = _make_workspace(tmp_path)
    monkeypatch.chdir(workspace)
    runner = CliRunner()
    result = runner.invoke(cli, ["session", "delete", "nonexistent"])
    assert result.exit_code != 0


def test_session_resume_missing(tmp_path: Path, monkeypatch) -> None:
    workspace = _make_workspace(tmp_path)
    monkeypatch.chdir(workspace)
    runner = CliRunner()
    result = runner.invoke(cli, ["session", "resume", "nonexistent"])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_continue_no_workspace(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["continue"])
    assert result.exit_code != 0


def test_memory_edit_no_workspace(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["memory", "edit"])
    assert result.exit_code != 0


def test_memory_edit_no_file(tmp_path: Path, monkeypatch) -> None:
    workspace = _make_workspace(tmp_path)
    monkeypatch.chdir(workspace)
    autoagent_md = workspace / "AUTOAGENT.md"
    if autoagent_md.exists():
        autoagent_md.unlink()
    runner = CliRunner()
    result = runner.invoke(cli, ["memory", "edit"])
    assert result.exit_code != 0


def test_memory_edit_with_file(tmp_path: Path, monkeypatch) -> None:
    workspace = _make_workspace(tmp_path)
    (workspace / "AUTOAGENT.md").write_text("# Memory\n", encoding="utf-8")
    monkeypatch.chdir(workspace)
    import runner as runner_mod

    monkeypatch.setattr(runner_mod, "_open_in_editor", lambda path: None)
    runner = CliRunner()
    result = runner.invoke(cli, ["memory", "edit"])
    assert result.exit_code == 0


def test_config_edit_no_workspace(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["config", "edit"])
    assert result.exit_code != 0


def test_config_edit_with_workspace(tmp_path: Path, monkeypatch) -> None:
    workspace = _make_workspace(tmp_path)
    monkeypatch.chdir(workspace)
    import runner as runner_mod

    monkeypatch.setattr(runner_mod, "_open_in_editor", lambda path: None)
    runner = CliRunner()
    result = runner.invoke(cli, ["config", "edit"])
    assert result.exit_code == 0


def test_shell_status_slash_command_runs_embedded_cli(tmp_path: Path, monkeypatch) -> None:
    """The REPL `/status` command should render the status screen instead of an internal runner error."""
    workspace = tmp_path / "ws"
    runner = CliRunner()
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace)])
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)
    result = runner.invoke(cli, ["shell"], input="/status\n/exit\n")

    assert result.exit_code == 0, result.output
    assert "AutoAgent Status" in result.output
    assert "unexpected keyword argument 'mix_stderr'" not in result.output


def test_shell_free_text_build_routes_to_build_command(tmp_path: Path, monkeypatch) -> None:
    """Free-text build requests should execute the build command with the full prompt preserved."""
    workspace = tmp_path / "ws"
    runner = CliRunner()
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace)])
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)
    result = runner.invoke(
        cli,
        ["shell"],
        input="build a customer support agent for refunds and cancellations\n/exit\n",
    )

    assert result.exit_code == 0, result.output
    assert "AutoAgent Build" in result.output
    assert "Prompt: build a customer support agent for refunds and cancellations" in result.output
    assert "unexpected keyword argument 'mix_stderr'" not in result.output


def test_shell_free_text_deploy_routes_to_deploy_status(tmp_path: Path, monkeypatch) -> None:
    """Free-text deploy requests should show the deploy surface instead of becoming a no-op."""
    workspace = tmp_path / "ws"
    runner = CliRunner()
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace)])
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)
    result = runner.invoke(cli, ["shell"], input="deploy\n/exit\n")

    assert result.exit_code == 0, result.output
    assert "Deployment status" in result.output
