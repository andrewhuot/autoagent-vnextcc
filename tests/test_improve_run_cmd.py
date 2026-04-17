"""agentlab improve run <config> — canonical orchestration."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from runner import cli


def test_improve_run_zero_args_in_workspace_uses_active_config(
    tmp_path, monkeypatch
):
    """Zero-arg improve should resolve the workspace active config, not legacy autofix."""
    workspace = tmp_path / "workspace"
    init_result = CliRunner().invoke(
        cli,
        ["init", "--dir", str(workspace), "--no-synthetic-data"],
    )
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)
    captured: dict[str, str] = {}

    def fake_eval(**kwargs):
        captured["eval"] = kwargs["config_path"]

    def fake_optimize(**kwargs):
        captured["optimize"] = kwargs["config_path"]
        return {}

    with patch("cli.commands.improve._run_eval_step", side_effect=fake_eval), \
         patch("cli.commands.improve._run_optimize_step", side_effect=fake_optimize), \
         patch("cli.commands.improve._present_top_attempt"), \
         patch("cli.commands.improve._invoke_legacy_autofix") as legacy:
        result = CliRunner().invoke(cli, ["improve", "run", "--auto"])

    assert result.exit_code == 0, result.output
    assert captured["eval"].endswith("configs/v001.yaml")
    assert captured["optimize"].endswith("configs/v001.yaml")
    assert "autofix" not in result.output.lower()
    assert "deprecated" not in result.output.lower()
    legacy.assert_not_called()


def test_improve_run_zero_args_outside_workspace_fails_clearly(tmp_path, monkeypatch):
    """Zero-arg improve should fail nonzero when no config can be resolved."""
    monkeypatch.chdir(tmp_path)

    with patch("cli.commands.improve._invoke_legacy_autofix") as legacy:
        result = CliRunner().invoke(cli, ["improve", "run", "--auto"])

    assert result.exit_code != 0
    assert "workspace" in result.output.lower() or "config" in result.output.lower()
    assert "autofix" not in result.output.lower()
    legacy.assert_not_called()


def test_improve_run_with_config_invokes_eval_then_optimize():
    """Happy path: eval → optimize in that order."""
    call_order = []

    def fake_eval(**kwargs):
        call_order.append("eval")

    def fake_optimize(**kwargs):
        call_order.append("optimize")

    with patch("cli.commands.improve._run_eval_step", side_effect=fake_eval) as _eval, \
         patch("cli.commands.improve._run_optimize_step", side_effect=fake_optimize) as _opt, \
         patch("cli.commands.improve._present_top_attempt"):
        r = CliRunner().invoke(cli, ["improve", "run", "configs/my.yaml"])
    assert r.exit_code == 0, r.output
    assert call_order == ["eval", "optimize"]


def test_improve_run_propagates_strict_live():
    """--strict-live must be forwarded to both eval and optimize steps."""
    captured = {}

    def fake_eval(**kw):
        captured["eval_strict_live"] = kw.get("strict_live")

    def fake_optimize(**kw):
        captured["opt_strict_live"] = kw.get("strict_live")

    with patch("cli.commands.improve._run_eval_step", side_effect=fake_eval), \
         patch("cli.commands.improve._run_optimize_step", side_effect=fake_optimize), \
         patch("cli.commands.improve._present_top_attempt"):
        CliRunner().invoke(cli, ["improve", "run", "configs/my.yaml", "--strict-live"])
    assert captured["eval_strict_live"] is True
    assert captured["opt_strict_live"] is True


def test_improve_run_forwards_cycles_and_mode():
    captured = {}
    def fake_optimize(**kw):
        captured.update(kw)
    with patch("cli.commands.improve._run_eval_step"), \
         patch("cli.commands.improve._run_optimize_step", side_effect=fake_optimize), \
         patch("cli.commands.improve._present_top_attempt"):
        CliRunner().invoke(cli, [
            "improve", "run", "configs/my.yaml",
            "--cycles", "3", "--mode", "advanced",
        ])
    assert captured.get("cycles") == 3
    assert captured.get("mode") == "advanced"


def test_improve_run_json_output_envelope():
    """--json (alias -j) returns a JSON envelope with the top attempt id."""
    with patch("cli.commands.improve._run_eval_step"), \
         patch("cli.commands.improve._run_optimize_step") as opt:
        opt.return_value = {"top_attempt_id": "abc12345", "score": 0.85}
        r = CliRunner().invoke(cli, [
            "improve", "run", "configs/my.yaml", "--json",
        ])
    assert r.exit_code == 0
    import json as _json
    parsed = _json.loads(r.output.strip().split("\n")[-1])
    # Envelope shape is flexible; at minimum top_attempt_id must surface:
    assert "abc12345" in r.output


def test_improve_run_auto_keeps_workspace_eval_suite(
    tmp_path, monkeypatch
):
    """`improve run --auto` should use workspace config + cases instead of package autofix defaults."""
    workspace = tmp_path / "workspace"
    init_result = CliRunner().invoke(
        cli,
        ["init", "--dir", str(workspace), "--no-synthetic-data"],
    )
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)

    eval_result = CliRunner().invoke(cli, ["eval", "run"])
    assert eval_result.exit_code == 0, eval_result.output

    optimize_result = CliRunner().invoke(cli, ["optimize", "--cycles", "1"])
    assert optimize_result.exit_code == 0, optimize_result.output

    improve_result = CliRunner().invoke(cli, ["improve", "run", "--auto"])
    assert improve_result.exit_code == 0, improve_result.output
    assert "autofix" not in improve_result.output.lower()
    assert "deprecated" not in improve_result.output.lower()

    latest = json.loads(
        (workspace / ".agentlab" / "eval_results_latest.json").read_text(
            encoding="utf-8"
        )
    )
    assert latest["config_path"].endswith("configs/v001.yaml")
    assert latest["total"] == 3
    assert {item["case_id"] for item in latest["results"]} == {
        "cs_happy_001",
        "cs_happy_002",
        "cs_safe_001",
    }


def test_improve_run_is_no_longer_hidden():
    """Un-hidden: appears in `agentlab improve --help`."""
    r = CliRunner().invoke(cli, ["improve", "--help"])
    assert r.exit_code == 0
    assert "\n  run " in r.output or "Commands:" in r.output
    # The subcommand listing should mention 'run':
    assert " run " in r.output
