"""Tests for XML-first starter templates and default config instructions."""

from __future__ import annotations

import yaml
from click.testing import CliRunner

from agent.instruction_builder import validate_xml_instruction
from cli.templates import STARTER_TEMPLATE_NAMES, load_template
from runner import cli


def test_all_starter_templates_use_valid_xml_root_instructions() -> None:
    """Bundled starter templates should default to valid XML root instructions."""
    for template_name in STARTER_TEMPLATE_NAMES:
        template = load_template(template_name)
        root_instruction = str((template.starter_config.get("prompts") or {}).get("root") or "")
        validation = validate_xml_instruction(root_instruction)

        assert validation["valid"] is True, template_name
        assert validation["warnings"] == [], template_name


def test_init_writes_xml_root_instruction_to_new_workspace(tmp_path) -> None:
    """Fresh workspaces should start with an XML root instruction, not legacy plain text."""
    runner = CliRunner()
    workspace = tmp_path / "xml-default-workspace"

    result = runner.invoke(cli, ["init", "--dir", str(workspace), "--no-synthetic-data"])

    assert result.exit_code == 0, result.output
    config = yaml.safe_load((workspace / "configs" / "v001.yaml").read_text(encoding="utf-8"))
    validation = validate_xml_instruction(config["prompts"]["root"])
    assert validation["valid"] is True
    assert validation["warnings"] == []
