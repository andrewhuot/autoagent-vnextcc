"""Tests for core.skills.loader module."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from core.skills.loader import SkillLoadError, SkillLoader
from core.skills.store import SkillStore
from core.skills.types import (
    EvalCriterion,
    MutationOperator,
    Skill,
    SkillKind,
    TriggerCondition,
)


@pytest.fixture
def loader() -> SkillLoader:
    """Create a SkillLoader instance."""
    return SkillLoader()


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_skill_yaml() -> str:
    """Sample single skill YAML."""
    return """
id: test-skill-001
name: test_skill
kind: build
version: "1.0"
description: A test skill for unit tests
capabilities:
  - keyword_expansion
  - routing_optimization
mutations:
  - name: expand_keywords
    description: Add missing keywords
    target_surface: routing
    operator_type: append
    template: "Add semantically related keywords"
    parameters:
      max_keywords: 10
    risk_level: low
triggers:
  - failure_family: routing_error
    metric_name: routing_accuracy
    threshold: 0.85
    operator: lt
eval_criteria:
  - metric: routing_accuracy
    target: 0.90
    operator: gt
    weight: 1.0
tags:
  - routing
  - keywords
domain: customer-support
author: test-author
status: active
"""


@pytest.fixture
def sample_skill_pack_yaml() -> str:
    """Sample skill pack YAML with multiple skills."""
    return """
skills:
  - id: skill-001
    name: keyword_expansion
    kind: build
    version: "1.0"
    description: Expand routing keywords
    mutations:
      - name: add_keywords
        description: Add keywords
        target_surface: routing
        operator_type: append
    triggers:
      - failure_family: routing_error
    tags: [routing]

  - id: skill-002
    name: instruction_hardening
    kind: build
    version: "1.0"
    description: Strengthen instructions
    mutations:
      - name: add_rules
        description: Add explicit rules
        target_surface: instruction
        operator_type: append
    triggers:
      - failure_family: instruction_gap
    tags: [quality]
"""


@pytest.fixture
def sample_python_module() -> str:
    """Sample Python module with skills."""
    return """
from core.skills.types import (
    Skill,
    SkillKind,
    MutationOperator,
)

SKILLS = [
    Skill(
        id="python-skill-001",
        name="python_skill_1",
        kind=SkillKind.BUILD,
        version="1.0",
        description="First Python skill",
        mutations=[
            MutationOperator(
                name="test_mutation",
                description="Test mutation",
                target_surface="routing",
                operator_type="append",
            )
        ],
    ),
    Skill(
        id="python-skill-002",
        name="python_skill_2",
        kind=SkillKind.RUNTIME,
        version="1.0",
        description="Second Python skill",
        instructions="Test instructions",
    ),
]
"""


class TestYAMLLoading:
    """Test YAML file loading."""

    def test_load_single_skill(self, loader: SkillLoader, temp_dir: Path, sample_skill_yaml: str):
        """Test loading a single skill from YAML."""
        skill_file = temp_dir / "skill.yaml"
        skill_file.write_text(sample_skill_yaml)

        skills = loader.load_from_yaml(str(skill_file))

        assert len(skills) == 1
        skill = skills[0]
        assert skill.id == "test-skill-001"
        assert skill.name == "test_skill"
        assert skill.kind == SkillKind.BUILD
        assert skill.version == "1.0.0"  # Version normalized to semver
        assert skill.description == "A test skill for unit tests"
        assert len(skill.mutations) == 1
        assert len(skill.triggers) == 1
        assert len(skill.eval_criteria) == 1
        assert "routing" in skill.tags

    def test_load_skill_pack(self, loader: SkillLoader, temp_dir: Path, sample_skill_pack_yaml: str):
        """Test loading a skill pack with multiple skills."""
        pack_file = temp_dir / "pack.yaml"
        pack_file.write_text(sample_skill_pack_yaml)

        skills = loader.load_pack(str(pack_file))

        assert len(skills) == 2
        assert skills[0].name == "keyword_expansion"
        assert skills[1].name == "instruction_hardening"
        assert all(skill.kind == SkillKind.BUILD for skill in skills)

    def test_load_nonexistent_file(self, loader: SkillLoader):
        """Test loading from a file that doesn't exist."""
        with pytest.raises(SkillLoadError, match="File not found"):
            loader.load_from_yaml("/nonexistent/path/skill.yaml")

    def test_load_invalid_yaml(self, loader: SkillLoader, temp_dir: Path):
        """Test loading invalid YAML."""
        invalid_file = temp_dir / "invalid.yaml"
        invalid_file.write_text("invalid: yaml: content: [unclosed")

        with pytest.raises(SkillLoadError, match="Invalid YAML"):
            loader.load_from_yaml(str(invalid_file))

    def test_load_empty_yaml(self, loader: SkillLoader, temp_dir: Path):
        """Test loading empty YAML file."""
        empty_file = temp_dir / "empty.yaml"
        empty_file.write_text("")

        with pytest.raises(SkillLoadError, match="Empty YAML"):
            loader.load_from_yaml(str(empty_file))

    def test_load_yaml_with_missing_required_fields(self, loader: SkillLoader, temp_dir: Path):
        """Test loading YAML with missing required fields."""
        minimal_yaml = """
name: test
kind: build
# Missing version and description
"""
        yaml_file = temp_dir / "minimal.yaml"
        yaml_file.write_text(minimal_yaml)

        # Should load without raising, but validation will catch missing fields
        skills = loader.load_from_yaml(str(yaml_file))
        assert len(skills) == 1


class TestPythonModuleLoading:
    """Test Python module loading."""

    def test_load_from_python_module(self, loader: SkillLoader, temp_dir: Path, sample_python_module: str):
        """Test loading skills from a Python module."""
        module_file = temp_dir / "test_module.py"
        module_file.write_text(sample_python_module)

        skills = loader.load_from_python(str(module_file))

        assert len(skills) == 2
        assert skills[0].name == "python_skill_1"
        assert skills[1].name == "python_skill_2"
        assert skills[0].kind == SkillKind.BUILD
        assert skills[1].kind == SkillKind.RUNTIME

    def test_load_python_with_get_skills_function(self, loader: SkillLoader, temp_dir: Path):
        """Test loading from module with get_skills() function."""
        module_content = """
from core.skills.types import Skill, SkillKind

def get_skills():
    return [
        Skill(
            id="func-skill-001",
            name="function_skill",
            kind=SkillKind.BUILD,
            version="1.0",
            description="Skill from function",
        )
    ]
"""
        module_file = temp_dir / "func_module.py"
        module_file.write_text(module_content)

        skills = loader.load_from_python(str(module_file))

        assert len(skills) == 1
        assert skills[0].name == "function_skill"

    def test_load_python_nonexistent_module(self, loader: SkillLoader):
        """Test loading from nonexistent Python module."""
        with pytest.raises(SkillLoadError, match="Module file not found"):
            loader.load_from_python("/nonexistent/module.py")

    def test_load_python_invalid_syntax(self, loader: SkillLoader, temp_dir: Path):
        """Test loading Python module with syntax errors."""
        invalid_module = temp_dir / "invalid.py"
        invalid_module.write_text("def invalid syntax here")

        with pytest.raises(SkillLoadError, match="Failed to load skills"):
            loader.load_from_python(str(invalid_module))

    def test_load_python_no_skills(self, loader: SkillLoader, temp_dir: Path):
        """Test loading Python module with no skills."""
        empty_module = temp_dir / "empty.py"
        empty_module.write_text("# No skills here\nx = 42")

        skills = loader.load_from_python(str(empty_module))

        assert len(skills) == 0


class TestStoreLoading:
    """Test loading from SkillStore."""

    def test_load_from_store(self, loader: SkillLoader, temp_dir: Path):
        """Test loading skills from SkillStore."""
        db_path = temp_dir / "test_skills.db"
        store = SkillStore(str(db_path))

        # Create test skills
        skill1 = Skill(
            id="store-skill-001",
            name="store_skill_1",
            kind=SkillKind.BUILD,
            version="1.0",
            description="Skill from store",
        )
        skill2 = Skill(
            id="store-skill-002",
            name="store_skill_2",
            kind=SkillKind.RUNTIME,
            version="1.0",
            description="Another skill from store",
        )

        store.create(skill1)
        store.create(skill2)

        # Load from store
        skills = loader.load_from_store(["store-skill-001", "store-skill-002"], store)

        assert len(skills) == 2
        assert skills[0].id == "store-skill-001"
        assert skills[1].id == "store-skill-002"

        store.close()

    def test_load_from_store_partial_match(self, loader: SkillLoader, temp_dir: Path):
        """Test loading when some IDs don't exist."""
        db_path = temp_dir / "test_skills.db"
        store = SkillStore(str(db_path))

        skill = Skill(
            id="existing-skill",
            name="existing",
            kind=SkillKind.BUILD,
            version="1.0",
            description="Exists",
        )
        store.create(skill)

        # Load with one existing and one non-existing ID
        skills = loader.load_from_store(["existing-skill", "nonexistent-skill"], store)

        assert len(skills) == 1
        assert skills[0].id == "existing-skill"

        store.close()

    def test_load_from_store_empty_ids(self, loader: SkillLoader, temp_dir: Path):
        """Test loading with empty ID list."""
        db_path = temp_dir / "test_skills.db"
        store = SkillStore(str(db_path))

        skills = loader.load_from_store([], store)

        assert len(skills) == 0
        store.close()


class TestValidatedLoading:
    """Test validate_and_load functionality."""

    def test_validate_and_load_valid_skill(self, loader: SkillLoader, temp_dir: Path, sample_skill_yaml: str):
        """Test validating and loading a valid skill."""
        skill_file = temp_dir / "valid.yaml"
        skill_file.write_text(sample_skill_yaml)

        skills, errors = loader.validate_and_load(str(skill_file))

        assert len(skills) == 1
        assert len(errors) == 0

    def test_validate_and_load_invalid_skill(self, loader: SkillLoader, temp_dir: Path):
        """Test validating and loading an invalid skill."""
        invalid_yaml = """
id: invalid-skill
# Missing required fields: name, version, description
kind: build
"""
        skill_file = temp_dir / "invalid.yaml"
        skill_file.write_text(invalid_yaml)

        skills, errors = loader.validate_and_load(str(skill_file))

        assert len(skills) == 0
        assert len(errors) > 0

    def test_validate_and_load_mixed_validity(self, loader: SkillLoader, temp_dir: Path):
        """Test validating a pack with both valid and invalid skills."""
        mixed_yaml = """
skills:
  - id: valid-skill
    name: valid
    kind: build
    version: "1.0"
    description: Valid skill
    mutations:
      - name: test
        description: Test
        target_surface: routing
        operator_type: append

  - id: invalid-skill
    # Missing name, version, description
    kind: build
"""
        pack_file = temp_dir / "mixed.yaml"
        pack_file.write_text(mixed_yaml)

        skills, errors = loader.validate_and_load(str(pack_file))

        assert len(skills) == 1  # Only the valid skill
        assert len(errors) > 0  # Errors from the invalid skill

    def test_validate_and_load_unsupported_file_type(self, loader: SkillLoader):
        """Test validating unsupported file type."""
        skills, errors = loader.validate_and_load("skill.json")

        assert len(skills) == 0
        assert len(errors) == 1
        assert "Unsupported file type" in errors[0]


class TestDirectoryLoading:
    """Test loading skills from directories."""

    def test_load_directory_non_recursive(
        self,
        loader: SkillLoader,
        temp_dir: Path,
        sample_skill_yaml: str,
        sample_skill_pack_yaml: str,
    ):
        """Test loading all skill files from a directory."""
        # Create skill files
        (temp_dir / "skill1.yaml").write_text(sample_skill_yaml)
        (temp_dir / "pack1.yaml").write_text(sample_skill_pack_yaml)

        skills, errors = loader.load_directory(str(temp_dir), recursive=False)

        assert len(skills) == 3  # 1 from skill1 + 2 from pack1
        assert len(errors) == 0

    def test_load_directory_recursive(
        self,
        loader: SkillLoader,
        temp_dir: Path,
        sample_skill_yaml: str,
    ):
        """Test loading skill files recursively."""
        # Create nested structure
        (temp_dir / "skill1.yaml").write_text(sample_skill_yaml)

        subdir = temp_dir / "subdir"
        subdir.mkdir()
        (subdir / "skill2.yaml").write_text(sample_skill_yaml)

        skills, errors = loader.load_directory(str(temp_dir), recursive=True)

        assert len(skills) == 2
        assert len(errors) == 0

    def test_load_directory_nonexistent(self, loader: SkillLoader):
        """Test loading from nonexistent directory."""
        skills, errors = loader.load_directory("/nonexistent/directory")

        assert len(skills) == 0
        assert len(errors) == 1
        assert "not found" in errors[0]

    def test_load_directory_empty(self, loader: SkillLoader, temp_dir: Path):
        """Test loading from empty directory."""
        skills, errors = loader.load_directory(str(temp_dir))

        assert len(skills) == 0
        assert len(errors) == 0

    def test_load_directory_without_validation(
        self,
        loader: SkillLoader,
        temp_dir: Path,
        sample_skill_yaml: str,
    ):
        """Test loading directory without validation."""
        (temp_dir / "skill.yaml").write_text(sample_skill_yaml)

        skills, errors = loader.load_directory(str(temp_dir), validate=False)

        assert len(skills) == 1
        assert len(errors) == 0


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_skill_load_error_exception(self):
        """Test SkillLoadError exception."""
        error = SkillLoadError("Test error")
        assert str(error) == "Test error"

    def test_load_yaml_malformed_skill_dict(self, loader: SkillLoader, temp_dir: Path):
        """Test loading YAML with malformed skill data."""
        malformed_yaml = """
skills:
  - "not a dict"
  - 123
"""
        yaml_file = temp_dir / "malformed.yaml"
        yaml_file.write_text(malformed_yaml)

        with pytest.raises(SkillLoadError):
            loader.load_from_yaml(str(yaml_file))
