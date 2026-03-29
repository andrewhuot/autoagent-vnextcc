"""Smoke test for import -> eval -> deploy."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from click.testing import CliRunner

from runner import cli


def _env_without_api_keys() -> dict[str, str]:
    env = dict(os.environ)
    env["OPENAI_API_KEY"] = ""
    env["ANTHROPIC_API_KEY"] = ""
    env["GOOGLE_API_KEY"] = ""
    return env


def test_golden_path_import() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        source_config = Path("importable.yaml")
        source_config.write_text(
            yaml.safe_dump(
                {
                    "prompts": {"root": "You are a support agent."},
                    "routing": {"rules": []},
                    "tools": {},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        import_result = runner.invoke(cli, ["import", "config", str(source_config)])
        assert import_result.exit_code == 0, import_result.output

        eval_result = runner.invoke(cli, ["eval", "run"], env=_env_without_api_keys())
        assert eval_result.exit_code == 0, eval_result.output

        deploy_result = runner.invoke(cli, ["deploy", "canary", "--yes"])
        assert deploy_result.exit_code == 0, deploy_result.output

