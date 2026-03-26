"""Tests for skill validator dependency resolution.

These tests validate dependency checking when a SkillStore is available.
"""

import pytest
from core.skills.types import (
    Skill,
    SkillKind,
    SkillDependency,
    ToolDefinition,
)
from core.skills.validator import SkillValidator, ValidationResult


class MockSkillStore:
    """Mock skill store for testing dependency validation."""

    def __init__(self):
        self.skills = {}

    def add_skill(self, skill: Skill):
        """Add a skill to the mock store."""
        self.skills[skill.id] = skill

    def get_skill(self, skill_id: str) -> Skill | None:
        """Get a skill by ID."""
        return self.skills.get(skill_id)


class TestValidateDependencies:
    """Test dependency validation."""

    def test_validate_dependencies_all_present(self):
        """Test dependency validation when all dependencies exist."""
        # Create dependency skills
        dep1 = Skill(
            id="dep1",
            name="Dependency 1",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Test dependency 1",
            tools=[ToolDefinition(name="tool1", description="Test", parameters={})],
        )

        dep2 = Skill(
            id="dep2",
            name="Dependency 2",
            kind=SkillKind.RUNTIME,
            version="2.5.0",
            description="Test dependency 2",
            tools=[ToolDefinition(name="tool2", description="Test", parameters={})],
        )

        # Create main skill with dependencies
        skill = Skill(
            id="main-skill",
            name="Main Skill",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Test skill with dependencies",
            instructions="Do something",
            dependencies=[
                SkillDependency(skill_id="dep1", version_constraint="^1.0.0"),
                SkillDependency(skill_id="dep2", version_constraint=">=2.0.0,<3.0.0"),
            ],
        )

        # Create store and add dependencies
        store = MockSkillStore()
        store.add_skill(dep1)
        store.add_skill(dep2)

        # Validate
        validator = SkillValidator()
        result = validator.validate_dependencies(skill, store)
        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_validate_dependencies_missing_required(self):
        """Test dependency validation when required dependency is missing."""
        skill = Skill(
            id="main-skill",
            name="Main Skill",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Test skill with missing dependency",
            instructions="Do something",
            dependencies=[
                SkillDependency(skill_id="missing-dep", version_constraint="*"),
            ],
        )

        store = MockSkillStore()

        validator = SkillValidator()
        result = validator.validate_dependencies(skill, store)
        assert result.is_valid is False
        assert any("not found" in e for e in result.errors)

    def test_validate_dependencies_missing_optional(self):
        """Test dependency validation when optional dependency is missing."""
        skill = Skill(
            id="main-skill",
            name="Main Skill",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Test skill with optional dependency",
            instructions="Do something",
            dependencies=[
                SkillDependency(
                    skill_id="optional-dep",
                    version_constraint="*",
                    optional=True
                ),
            ],
        )

        store = MockSkillStore()

        validator = SkillValidator()
        result = validator.validate_dependencies(skill, store)
        assert result.is_valid is True
        assert any("Optional dependency" in w for w in result.warnings)

    def test_validate_dependencies_version_mismatch(self):
        """Test dependency validation when version doesn't match."""
        dep = Skill(
            id="dep",
            name="Dependency",
            kind=SkillKind.RUNTIME,
            version="2.0.0",
            description="Test dependency",
            tools=[ToolDefinition(name="tool", description="Test", parameters={})],
        )

        skill = Skill(
            id="main-skill",
            name="Main Skill",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Test skill",
            instructions="Do something",
            dependencies=[
                SkillDependency(skill_id="dep", version_constraint="^1.0.0"),
            ],
        )

        store = MockSkillStore()
        store.add_skill(dep)

        validator = SkillValidator()
        result = validator.validate_dependencies(skill, store)
        assert result.is_valid is False
        assert any("does not satisfy constraint" in e for e in result.errors)

    def test_validate_dependencies_circular(self):
        """Test detection of circular dependencies."""
        skill = Skill(
            id="self-dep",
            name="Self Dependent",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Test skill that depends on itself",
            instructions="Do something",
            dependencies=[
                SkillDependency(skill_id="self-dep", version_constraint="*"),
            ],
        )

        store = MockSkillStore()
        store.add_skill(skill)

        validator = SkillValidator()
        result = validator.validate_dependencies(skill, store)
        assert result.is_valid is False
        assert any("Circular dependency" in e for e in result.errors)

    def test_validate_full_with_dependencies(self):
        """Test full validation including dependency checking."""
        dep = Skill(
            id="base-skill",
            name="Base Skill",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Base skill",
            tools=[ToolDefinition(name="base_tool", description="Test", parameters={})],
        )

        skill = Skill(
            id="extended-skill",
            name="Extended Skill",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Skill that extends base",
            tools=[ToolDefinition(name="extended_tool", description="Test", parameters={})],
            dependencies=[
                SkillDependency(skill_id="base-skill", version_constraint="^1.0.0"),
            ],
        )

        store = MockSkillStore()
        store.add_skill(dep)

        validator = SkillValidator()
        result = validator.validate_full(skill, store=store)
        assert result.is_valid is True

    def test_validate_full_without_store(self):
        """Test full validation without dependency store."""
        skill = Skill(
            id="skill",
            name="Skill",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Test skill",
            instructions="Do something",
            dependencies=[
                SkillDependency(skill_id="some-dep", version_constraint="*"),
            ],
        )

        validator = SkillValidator()
        result = validator.validate_full(skill, store=None)
        # Should pass schema validation but skip dependency checks
        assert result.is_valid is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
