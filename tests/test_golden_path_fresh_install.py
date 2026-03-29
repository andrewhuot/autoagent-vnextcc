"""Smoke test for the fresh-install golden path."""

from __future__ import annotations

import os

from click.testing import CliRunner

from runner import cli


def _env_without_api_keys() -> dict[str, str]:
    env = dict(os.environ)
    env["OPENAI_API_KEY"] = ""
    env["ANTHROPIC_API_KEY"] = ""
    env["GOOGLE_API_KEY"] = ""
    return env


def test_golden_path_fresh_install() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        init_result = runner.invoke(cli, ["init", "--dir", "."])
        assert init_result.exit_code == 0, init_result.output

        build_result = runner.invoke(cli, ["build", "Build a support agent for refunds and order tracking"])
        assert build_result.exit_code == 0, build_result.output

        eval_result = runner.invoke(cli, ["eval", "run"], env=_env_without_api_keys())
        assert eval_result.exit_code == 0, eval_result.output

        improve_result = runner.invoke(cli, ["improve", "optimize", "--cycles", "1"], env=_env_without_api_keys())
        assert improve_result.exit_code == 0, improve_result.output

        deploy_result = runner.invoke(cli, ["deploy", "canary", "--yes"])
        assert deploy_result.exit_code == 0, deploy_result.output

