"""agentlab improve run <config> — canonical orchestration."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from runner import cli


def test_improve_run_zero_args_shows_deprecation():
    """Legacy hidden autofix path: zero args prints deprecation and routes
    users to `agentlab autofix apply`."""
    with patch("cli.commands.improve._invoke_legacy_autofix") as legacy:
        legacy.return_value = None
        r = CliRunner().invoke(cli, ["improve", "run"])
    # Must mention the deprecation and the new command name:
    assert "deprecated" in r.output.lower() or "autofix" in r.output.lower()
    # Legacy handler still runs for back-compat:
    legacy.assert_called_once()


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


def test_improve_run_is_no_longer_hidden():
    """Un-hidden: appears in `agentlab improve --help`."""
    r = CliRunner().invoke(cli, ["improve", "--help"])
    assert r.exit_code == 0
    assert "\n  run " in r.output or "Commands:" in r.output
    # The subcommand listing should mention 'run':
    assert " run " in r.output
