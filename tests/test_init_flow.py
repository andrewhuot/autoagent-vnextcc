"""Tests for the agentlab init onboarding flow."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cli.init_flow import InitFlow, InitResult


def _write_config(tmp_path: Path, name: str = "test_bot") -> Path:
    """Write a minimal config YAML and return its path."""
    config = {
        "name": name,
        "prompts": {
            "root": "You are a helpful assistant.",
            "support": "Handle support queries.",
        },
        "routing": {
            "rules": [
                {"specialist": "support", "keywords": ["help", "issue"]},
            ],
        },
        "tools": {"faq": {"description": "FAQ lookup"}},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump(config))
    return config_path


class TestInitFromYaml:
    def test_full_flow_with_yaml(self, tmp_path):
        config_path = _write_config(tmp_path, "my_bot")
        output: list[str] = []
        flow = InitFlow(workspace=tmp_path, skip_eval=True, output_fn=output.append)
        result = flow.run(str(config_path))

        assert result.agent_name == "my_bot"
        assert result.card_path != ""
        assert result.cases_generated > 0
        assert "import:yaml" in result.steps_completed
        assert "card:generated" in result.steps_completed
        assert result.error == ""

    def test_card_saved_to_disk(self, tmp_path):
        _write_config(tmp_path)
        flow = InitFlow(workspace=tmp_path, skip_eval=True, skip_generate=True, output_fn=lambda _: None)
        flow.run(str(tmp_path / "config.yaml"))

        card_path = tmp_path / ".agentlab" / "agent_card.md"
        assert card_path.is_file()
        content = card_path.read_text()
        assert "Agent Card" in content

    def test_cases_saved_to_disk(self, tmp_path):
        _write_config(tmp_path)
        flow = InitFlow(workspace=tmp_path, skip_eval=True, output_fn=lambda _: None)
        flow.run(str(tmp_path / "config.yaml"))

        cases_path = tmp_path / "evals" / "cases" / "generated_from_card.yaml"
        assert cases_path.is_file()
        data = yaml.safe_load(cases_path.read_text())
        assert "cases" in data
        assert len(data["cases"]) > 0


class TestInitAutoDetect:
    def test_detects_yaml_in_cwd(self, tmp_path):
        _write_config(tmp_path)
        # Rename to a generic name (not agentlab.yaml)
        (tmp_path / "config.yaml").rename(tmp_path / "agent_config.yaml")

        flow = InitFlow(workspace=tmp_path, skip_eval=True, skip_generate=True, output_fn=lambda _: None)
        result = flow.run()  # no explicit source

        assert result.agent_name != ""
        assert "import:yaml" in result.steps_completed

    def test_no_source_creates_starter(self, tmp_path):
        flow = InitFlow(workspace=tmp_path, skip_eval=True, skip_generate=True, output_fn=lambda _: None)
        result = flow.run()

        assert result.agent_name == "my_agent"
        assert "import:starter" in result.steps_completed

    def test_detects_configs_dir(self, tmp_path):
        configs = tmp_path / "configs"
        configs.mkdir()
        config = {"name": "versioned_bot", "prompts": {"root": "Hello"}}
        (configs / "v001.yaml").write_text(yaml.dump(config))

        flow = InitFlow(workspace=tmp_path, skip_eval=True, skip_generate=True, output_fn=lambda _: None)
        result = flow.run()

        assert result.agent_name == "versioned_bot"


class TestSkipFlags:
    def test_skip_generate(self, tmp_path):
        _write_config(tmp_path)
        flow = InitFlow(workspace=tmp_path, skip_eval=True, skip_generate=True, output_fn=lambda _: None)
        result = flow.run(str(tmp_path / "config.yaml"))

        assert result.cases_generated == 0
        assert "card:generated" in result.steps_completed

    def test_skip_eval(self, tmp_path):
        _write_config(tmp_path)
        flow = InitFlow(workspace=tmp_path, skip_eval=True, output_fn=lambda _: None)
        result = flow.run(str(tmp_path / "config.yaml"))

        # Eval step should not appear in completed steps
        assert not any("eval:ran" in s for s in result.steps_completed)


class TestCoverage:
    def test_coverage_runs_after_generation(self, tmp_path):
        _write_config(tmp_path)
        flow = InitFlow(workspace=tmp_path, skip_eval=True, output_fn=lambda _: None)
        result = flow.run(str(tmp_path / "config.yaml"))

        assert "coverage:analyzed" in result.steps_completed

    def test_gaps_filled(self, tmp_path):
        _write_config(tmp_path)
        flow = InitFlow(workspace=tmp_path, skip_eval=True, output_fn=lambda _: None)
        result = flow.run(str(tmp_path / "config.yaml"))

        # With only 1 routing rule and few tools, there should be some coverage
        assert result.cases_generated > 0


class TestResultStructure:
    def test_result_fields(self, tmp_path):
        _write_config(tmp_path)
        flow = InitFlow(workspace=tmp_path, skip_eval=True, output_fn=lambda _: None)
        result = flow.run(str(tmp_path / "config.yaml"))

        assert isinstance(result, InitResult)
        assert isinstance(result.steps_completed, list)
        assert isinstance(result.warnings, list)
        assert len(result.steps_completed) > 0
        assert "done" in result.steps_completed

    def test_output_callback_receives_messages(self, tmp_path):
        _write_config(tmp_path)
        messages: list[str] = []
        flow = InitFlow(workspace=tmp_path, skip_eval=True, output_fn=messages.append)
        flow.run(str(tmp_path / "config.yaml"))

        # Should have step markers
        assert any("[1/5]" in m for m in messages)
        assert any("[2/5]" in m for m in messages)
