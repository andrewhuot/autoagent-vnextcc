"""Tests for UX audit ADK contract fixes (Track 1)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Test the importer accepts no parser/mapper args (UX-001)
def test_importer_no_parser_mapper_args():
    """Test AdkImporter() accepts no parser/mapper constructor args."""
    from adk import AdkImporter

    # Should accept no args (uses internal implementations)
    importer = AdkImporter()
    assert importer is not None

    # Should also accept mapper for backwards compatibility
    from adk import AdkMapper
    importer_with_mapper = AdkImporter(mapper=AdkMapper())
    assert importer_with_mapper is not None


# Test the exporter accepts no parser/mapper args (UX-001)
def test_exporter_no_parser_mapper_args():
    """Test AdkExporter() accepts no parser/mapper constructor args."""
    from adk import AdkExporter

    # Should accept no args (uses internal implementations)
    exporter = AdkExporter()
    assert exporter is not None


# Test parse_agent_directory is a module function (UX-001)
def test_parse_agent_directory_is_function():
    """Test parse_agent_directory is a module-level function, not a class method."""
    from adk import parse_agent_directory
    import inspect

    # Should be a function, not a class
    assert inspect.isfunction(parse_agent_directory)


# Test AdkAgentTree uses .agent not .root (UX-001)
def test_agent_tree_uses_agent_field(tmp_path):
    """Test AdkAgentTree has .agent field instead of .root."""
    from adk import parse_agent_directory
    from adk.types import AdkAgent, AdkAgentTree

    # Create minimal agent directory
    agent_dir = tmp_path / "test_agent"
    agent_dir.mkdir()
    (agent_dir / "__init__.py").write_text("")
    (agent_dir / "agent.py").write_text("""
from google import genai

agent = genai.Agent(
    name="test",
    model="gemini-2.0-flash",
    instruction="Test instruction",
)
""")

    tree = parse_agent_directory(agent_dir)

    # Should have .agent field, not .root
    assert hasattr(tree, "agent")
    assert isinstance(tree.agent, AdkAgent)
    assert tree.agent.name == "test"


# Test AdkExportResult has changes list (UX-004)
def test_export_result_has_changes():
    """Test ExportResult has changes field."""
    from adk.types import ExportResult

    result = ExportResult(
        output_path="/tmp/output",
        changes=[{"file": "agent.py", "field": "instruction", "action": "update"}],
        files_modified=1,
    )

    assert isinstance(result.changes, list)
    assert len(result.changes) == 1
    assert result.changes[0]["file"] == "agent.py"


# Test deploy uses correct enum values (UX-002)
def test_deploy_target_enum_values():
    """Test DeployResult uses cloud-run/vertex-ai enum values."""
    from adk.types import DeployResult

    # Should accept cloud-run
    result1 = DeployResult(
        target="cloud-run",
        url="https://example.run.app",
        status="deployed",
    )
    assert result1.target == "cloud-run"

    # Should accept vertex-ai
    result2 = DeployResult(
        target="vertex-ai",
        url="https://example.vertex.ai",
        status="deployed",
    )
    assert result2.target == "vertex-ai"


# Test AdkExporter.preview_changes returns changes with action field (UX-004)
def test_preview_changes_returns_changes_with_action(tmp_path):
    """Test preview_changes returns list of changes with action field."""
    from adk import AdkExporter

    # Create snapshot directory
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "__init__.py").write_text("")
    (snapshot / "agent.py").write_text("""
from google import genai

agent = genai.Agent(
    name="test",
    model="gemini-2.0-flash",
    instruction="Original instruction",
)
""")

    exporter = AdkExporter()
    config = {
        "instructions": {
            "root": "Updated instruction"
        }
    }

    changes = exporter.preview_changes(config, str(snapshot))

    # Should return list of changes
    assert isinstance(changes, list)
    assert len(changes) > 0
    # Each change should have action field
    for change in changes:
        assert "action" in change
        assert "field" in change
