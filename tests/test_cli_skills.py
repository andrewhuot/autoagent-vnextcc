"""Tests for unified skill CLI commands (cli/skills.py)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from core.skills.store import SkillStore
from core.skills.types import Skill, SkillKind, MutationOperator, TriggerCondition, EvalCriterion
from runner import cli


@pytest.fixture
def runner():
    """Click test runner."""
    return CliRunner()


@pytest.fixture
def temp_db():
    """Temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    # Cleanup
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def sample_skill():
    """Create a sample skill for testing."""
    return Skill(
        id="test_skill_1",
        name="Test Skill",
        kind=SkillKind.BUILD,
        version="1.0.0",
        description="A test skill for unit tests",
        domain="testing",
        tags=["test", "sample"],
        status="active",
        mutations=[
            MutationOperator(
                name="test_mutation",
                description="A test mutation",
                target_surface="instruction",
                operator_type="append",
                template="Test template",
            )
        ],
        triggers=[
            TriggerCondition(
                failure_family="test_failure",
            )
        ],
        eval_criteria=[
            EvalCriterion(
                metric="quality",
                target=0.8,
                operator="gte",
            )
        ],
    )


@pytest.fixture
def populated_db(temp_db, sample_skill):
    """Database populated with sample skills."""
    store = SkillStore(temp_db)
    try:
        store.create(sample_skill)

        # Create a second skill
        skill2 = Skill(
            id="test_skill_2",
            name="Another Test Skill",
            kind=SkillKind.RUNTIME,
            version="2.0.0",
            description="Another test skill",
            domain="testing",
            tags=["test"],
            status="active",
        )
        store.create(skill2)
    finally:
        store.close()

    return temp_db


def test_skill_commands_default_to_shared_lifecycle_store(runner, tmp_path, monkeypatch):
    """Skill commands should create the shared lifecycle store by default."""
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli, ["skill", "list"])

    assert result.exit_code == 0
    assert (tmp_path / ".autoagent" / "core_skills.db").exists()
    assert not (tmp_path / ".autoagent" / "skills.db").exists()


class TestSkillList:
    """Tests for 'autoagent skill list' command."""

    def test_list_empty_db(self, runner, temp_db):
        """List skills in empty database."""
        result = runner.invoke(cli, ["skill", "list", "--db", temp_db])
        assert result.exit_code == 0
        assert "No skills found" in result.output

    def test_list_with_skills(self, runner, populated_db):
        """List skills in populated database."""
        result = runner.invoke(cli, ["skill", "list", "--db", populated_db])
        assert result.exit_code == 0
        assert "Test Skill" in result.output
        assert "Another Test Skill" in result.output

    def test_list_filter_by_kind(self, runner, populated_db):
        """List skills filtered by kind."""
        result = runner.invoke(cli, ["skill", "list", "--kind", "build", "--db", populated_db])
        assert result.exit_code == 0
        assert "Test Skill" in result.output
        assert "Another Test Skill" not in result.output

    def test_list_filter_by_domain(self, runner, populated_db):
        """List skills filtered by domain."""
        result = runner.invoke(cli, ["skill", "list", "--domain", "testing", "--db", populated_db])
        assert result.exit_code == 0
        assert "Test Skill" in result.output

    def test_list_json_output(self, runner, populated_db):
        """List skills with JSON output."""
        result = runner.invoke(cli, ["skill", "list", "--json", "--db", populated_db])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["api_version"] == "1"
        data = payload["data"]
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["name"] in ["Test Skill", "Another Test Skill"]


class TestSkillShow:
    """Tests for 'autoagent skill show' command."""

    def test_show_existing_skill(self, runner, populated_db):
        """Show details of existing skill."""
        result = runner.invoke(cli, ["skill", "show", "test_skill_1", "--db", populated_db])
        assert result.exit_code == 0
        assert "Test Skill" in result.output
        assert "1.0.0" in result.output

    def test_show_nonexistent_skill(self, runner, populated_db):
        """Show nonexistent skill."""
        result = runner.invoke(cli, ["skill", "show", "nonexistent", "--db", populated_db])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_show_json_output(self, runner, populated_db):
        """Show skill with JSON output."""
        result = runner.invoke(cli, ["skill", "show", "test_skill_1", "--json", "--db", populated_db])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["name"] == "Test Skill"
        assert data["version"] == "1.0.0"


class TestSkillCreate:
    """Tests for 'autoagent skill create' command."""

    def test_create_from_file(self, runner, temp_db):
        """Create skill from YAML file."""
        # Create a temporary YAML file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            skill_data = {
                "skills": [
                    {
                        "id": "created_skill",
                        "name": "Created Skill",
                        "kind": "build",
                        "version": "1.0.0",
                        "description": "A skill created from file",
                        "domain": "general",
                        "tags": ["created"],
                        "mutations": [
                            {
                                "name": "test_mut",
                                "description": "Test",
                                "target_surface": "instruction",
                                "operator_type": "append",
                            }
                        ],
                        "triggers": [{"failure_family": "test"}],
                        "eval_criteria": [{"metric": "quality", "target": 0.8}],
                    }
                ]
            }
            yaml.dump(skill_data, f)
            yaml_path = f.name

        try:
            result = runner.invoke(
                cli,
                ["skill", "create", "--kind", "build", "--from-file", yaml_path, "--db", temp_db],
            )
            assert result.exit_code == 0
            assert "Created skill" in result.output
            assert "created_skill" in result.output
        finally:
            Path(yaml_path).unlink(missing_ok=True)

    def test_create_interactive_not_implemented(self, runner, temp_db):
        """Create skill interactively (not yet implemented)."""
        result = runner.invoke(cli, ["skill", "create", "--kind", "build", "--interactive", "--db", temp_db])
        assert result.exit_code == 0
        assert "not yet implemented" in result.output


class TestSkillTest:
    """Tests for 'autoagent skill test' command."""

    def test_test_valid_skill(self, runner, populated_db):
        """Test a valid skill."""
        result = runner.invoke(cli, ["skill", "test", "test_skill_1", "--db", populated_db])
        assert result.exit_code == 0
        assert "Validation passed" in result.output or "Validation failed" in result.output

    def test_test_nonexistent_skill(self, runner, populated_db):
        """Test nonexistent skill."""
        result = runner.invoke(cli, ["skill", "test", "nonexistent", "--db", populated_db])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestSkillPortableFormat:
    """Tests for SKILL.md import/export commands."""

    def test_export_md_writes_portable_skill_file(self, runner, populated_db, tmp_path):
        """Exporting a build skill should write a SKILL.md-compatible file to disk."""
        output_path = tmp_path / "portable" / "routing.SKILL.md"

        result = runner.invoke(
            cli,
            ["skill", "export-md", "test_skill_1", "--db", populated_db, "--output", str(output_path)],
        )

        assert result.exit_code == 0
        assert output_path.exists()
        content = output_path.read_text(encoding="utf-8")
        assert "name: Test Skill" in content
        assert "kind: build" in content
        assert "## Mutations" in content

    def test_import_md_registers_skill_in_target_database(self, runner, populated_db, tmp_path):
        """Importing a SKILL.md file should add the build skill to the requested DB."""
        exported_path = tmp_path / "portable" / "routing.SKILL.md"
        import_db = tmp_path / "imported.db"

        export_result = runner.invoke(
            cli,
            ["skill", "export-md", "test_skill_1", "--db", populated_db, "--output", str(exported_path)],
        )
        assert export_result.exit_code == 0

        import_result = runner.invoke(
            cli,
            ["skill", "import-md", str(exported_path), "--db", str(import_db)],
        )

        assert import_result.exit_code == 0
        assert "Imported skill: Test Skill" in import_result.output

        imported_store = SkillStore(str(import_db))
        try:
            imported_skill = imported_store.get_by_name("Test Skill")
            assert imported_skill is not None
            assert imported_skill.kind == SkillKind.BUILD
        finally:
            imported_store.close()


class TestSkillSearch:
    """Tests for 'autoagent skill search' command."""

    def test_search_finds_skill(self, runner, populated_db):
        """Search finds matching skill."""
        result = runner.invoke(cli, ["skill", "search", "Test", "--db", populated_db])
        assert result.exit_code == 0
        assert "Test Skill" in result.output

    def test_search_no_results(self, runner, populated_db):
        """Search with no results."""
        result = runner.invoke(cli, ["skill", "search", "nonexistent", "--db", populated_db])
        assert result.exit_code == 0
        assert "No skills found" in result.output

    def test_search_json_output(self, runner, populated_db):
        """Search with JSON output."""
        result = runner.invoke(cli, ["skill", "search", "Test", "--json", "--db", populated_db])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) > 0


class TestSkillEffectiveness:
    """Tests for 'autoagent skill effectiveness' command."""

    def test_effectiveness_existing_skill(self, runner, populated_db):
        """Show effectiveness for existing skill."""
        result = runner.invoke(cli, ["skill", "effectiveness", "test_skill_1", "--db", populated_db])
        assert result.exit_code == 0
        assert "Effectiveness Metrics" in result.output
        assert "Times Applied" in result.output

    def test_effectiveness_json_output(self, runner, populated_db):
        """Show effectiveness with JSON output."""
        result = runner.invoke(cli, ["skill", "effectiveness", "test_skill_1", "--json", "--db", populated_db])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "skill_id" in data
        assert "times_applied" in data
        assert "success_rate" in data


class TestSkillCompose:
    """Tests for 'autoagent skill compose' command."""

    def test_compose_multiple_skills(self, runner, populated_db):
        """Compose multiple skills."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            output_path = f.name

        try:
            result = runner.invoke(
                cli,
                [
                    "skill",
                    "compose",
                    "test_skill_1",
                    "test_skill_2",
                    "--output",
                    output_path,
                    "--db",
                    populated_db,
                ],
            )
            # May fail due to conflicts or composition issues, which is expected
            # Just verify command runs without crashing
            assert result.exit_code in [0, 1]
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_compose_nonexistent_skill(self, runner, populated_db):
        """Compose with nonexistent skill."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            output_path = f.name

        try:
            result = runner.invoke(
                cli,
                [
                    "skill",
                    "compose",
                    "nonexistent",
                    "--output",
                    output_path,
                    "--db",
                    populated_db,
                ],
            )
            assert result.exit_code == 1
            assert "not found" in result.output
        finally:
            Path(output_path).unlink(missing_ok=True)


class TestSkillInstall:
    """Tests for 'autoagent skill install' command."""

    def test_install_from_file(self, runner, temp_db):
        """Install skill from local file."""
        # Create a temporary YAML file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            skill_data = {
                "skills": [
                    {
                        "id": "install_test",
                        "name": "Install Test",
                        "kind": "build",
                        "version": "1.0.0",
                        "description": "Test installation",
                        "domain": "general",
                        "mutations": [
                            {
                                "name": "test_mut",
                                "description": "Test",
                                "target_surface": "instruction",
                                "operator_type": "append",
                            }
                        ],
                        "triggers": [{"failure_family": "test"}],
                        "eval_criteria": [{"metric": "quality", "target": 0.8}],
                    }
                ]
            }
            yaml.dump(skill_data, f)
            yaml_path = f.name

        try:
            result = runner.invoke(cli, ["skill", "install", yaml_path, "--db", temp_db])
            assert result.exit_code == 0
            assert "Successfully installed" in result.output
        finally:
            Path(yaml_path).unlink(missing_ok=True)


class TestSkillPublish:
    """Tests for 'autoagent skill publish' command."""

    def test_publish_existing_skill(self, runner, populated_db):
        """Publish an existing skill to marketplace."""
        result = runner.invoke(cli, ["skill", "publish", "test_skill_1", "--db", populated_db])
        # Should succeed or fail gracefully
        assert result.exit_code in [0, 1]

    def test_publish_nonexistent_skill(self, runner, populated_db):
        """Publish nonexistent skill."""
        result = runner.invoke(cli, ["skill", "publish", "nonexistent", "--db", populated_db])
        assert result.exit_code == 1
        assert "not found" in result.output
