"""Tests for core/skills/composer.py - skill composition and dependency resolution."""

import pytest

from core.skills.types import (
    Skill,
    SkillKind,
    SkillDependency,
    MutationOperator,
    ToolDefinition,
    Policy,
)
from core.skills.composer import (
    SkillComposer,
    SkillSet,
    CompositionConflict,
    ConflictType,
    ConflictSeverity,
    ResolutionStrategy,
)


# Mock skill store for testing
class MockSkillStore:
    """Mock skill store for testing dependency resolution."""

    def __init__(self):
        self.skills: dict[str, Skill] = {}

    def add(self, skill: Skill) -> None:
        """Add a skill to the store."""
        self.skills[skill.id] = skill

    def get(self, name: str, version: int | None = None) -> Skill | None:
        """Get a skill by ID (name is actually ID in this mock)."""
        return self.skills.get(name)


@pytest.fixture
def composer():
    """Create a SkillComposer instance."""
    return SkillComposer(conflict_strategy=ResolutionStrategy.FAIL)


@pytest.fixture
def mock_store():
    """Create a mock skill store."""
    return MockSkillStore()


@pytest.fixture
def simple_runtime_skill():
    """Create a simple run-time skill."""
    return Skill(
        id="skill_1",
        name="Simple Skill",
        kind=SkillKind.RUNTIME,
        version="1.0.0",
        description="A simple test skill",
        tools=[
            ToolDefinition(
                name="test_tool",
                description="A test tool",
                parameters={"param": {"type": "string"}},
            )
        ],
        instructions="Use the test tool to perform actions.",
    )


@pytest.fixture
def simple_build_skill():
    """Create a simple build-time skill."""
    return Skill(
        id="skill_build_1",
        name="Build Skill",
        kind=SkillKind.BUILD,
        version="1.0.0",
        description="A build-time skill",
        mutations=[
            MutationOperator(
                name="add_instruction",
                description="Add an instruction",
                target_surface="instruction",
                operator_type="append",
            )
        ],
    )


class TestSkillSetValidation:
    """Test SkillSet validation and YAML export."""

    def test_empty_skillset_is_valid(self):
        """Empty skill set should be valid."""
        skillset = SkillSet(
            id="test_1",
            name="Empty Set",
            description="Empty skill set",
        )
        assert skillset.validate()

    def test_skillset_with_error_conflict_is_invalid(self):
        """Skill set with error-level conflict should be invalid."""
        skillset = SkillSet(
            id="test_2",
            name="Conflicted Set",
            description="Has conflicts",
            conflicts=[
                CompositionConflict(
                    type=ConflictType.CIRCULAR_DEPENDENCY,
                    severity=ConflictSeverity.ERROR,
                    skill_ids=["s1", "s2"],
                    description="Circular dependency",
                )
            ],
        )
        assert not skillset.validate()

    def test_skillset_with_warning_conflict_is_valid(self):
        """Skill set with warning-level conflict should still be valid."""
        skillset = SkillSet(
            id="test_3",
            name="Warning Set",
            description="Has warnings",
            conflicts=[
                CompositionConflict(
                    type=ConflictType.SURFACE_MUTATION,
                    severity=ConflictSeverity.WARNING,
                    skill_ids=["s1", "s2"],
                    description="Surface conflict",
                )
            ],
        )
        assert skillset.validate()

    def test_skillset_with_inactive_skill_is_invalid(self):
        """Skill set with inactive skill should be invalid."""
        inactive_skill = Skill(
            id="inactive",
            name="Inactive",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Inactive skill",
            status="deprecated",
        )
        skillset = SkillSet(
            id="test_4",
            name="Inactive Set",
            description="Has inactive skill",
            skills=[inactive_skill],
        )
        assert not skillset.validate()

    def test_skillset_to_yaml(self, simple_runtime_skill):
        """Test YAML export."""
        skillset = SkillSet(
            id="test_5",
            name="YAML Test",
            description="Test YAML export",
            skills=[simple_runtime_skill],
            tags=["test", "yaml"],
        )
        yaml_str = skillset.to_yaml()
        assert "YAML Test" in yaml_str
        assert "Simple Skill" in yaml_str
        assert "runtime" in yaml_str


class TestDependencyResolution:
    """Test dependency resolution."""

    def test_resolve_simple_dependency(self, composer, mock_store):
        """Test resolving a simple dependency chain."""
        skill_a = Skill(
            id="skill_a",
            name="Skill A",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Depends on B",
            dependencies=[SkillDependency(skill_id="skill_b")],
        )
        skill_b = Skill(
            id="skill_b",
            name="Skill B",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="No dependencies",
        )

        mock_store.add(skill_b)

        resolved = composer.resolve_dependencies([skill_a], mock_store)
        assert len(resolved) == 2
        assert skill_b in resolved
        assert skill_a in resolved

    def test_resolve_transitive_dependencies(self, composer, mock_store):
        """Test resolving transitive dependencies (A -> B -> C)."""
        skill_a = Skill(
            id="skill_a",
            name="Skill A",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Depends on B",
            dependencies=[SkillDependency(skill_id="skill_b")],
        )
        skill_b = Skill(
            id="skill_b",
            name="Skill B",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Depends on C",
            dependencies=[SkillDependency(skill_id="skill_c")],
        )
        skill_c = Skill(
            id="skill_c",
            name="Skill C",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="No dependencies",
        )

        mock_store.add(skill_b)
        mock_store.add(skill_c)

        resolved = composer.resolve_dependencies([skill_a], mock_store)
        assert len(resolved) == 3
        assert all(s in resolved for s in [skill_a, skill_b, skill_c])

    def test_resolve_missing_required_dependency_fails(self, composer, mock_store):
        """Test that missing required dependency raises error."""
        skill_a = Skill(
            id="skill_a",
            name="Skill A",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Depends on missing B",
            dependencies=[SkillDependency(skill_id="skill_b", optional=False)],
        )

        with pytest.raises(ValueError, match="Required dependency"):
            composer.resolve_dependencies([skill_a], mock_store)

    def test_resolve_missing_optional_dependency_succeeds(self, composer, mock_store):
        """Test that missing optional dependency is skipped gracefully."""
        skill_a = Skill(
            id="skill_a",
            name="Skill A",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Optionally depends on B",
            dependencies=[SkillDependency(skill_id="skill_b", optional=True)],
        )

        resolved = composer.resolve_dependencies([skill_a], mock_store)
        assert len(resolved) == 1
        assert resolved[0] == skill_a

    def test_resolve_duplicate_dependencies(self, composer, mock_store):
        """Test that duplicate dependencies are handled correctly."""
        skill_common = Skill(
            id="common",
            name="Common",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Common dependency",
        )
        skill_a = Skill(
            id="skill_a",
            name="Skill A",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Depends on common",
            dependencies=[SkillDependency(skill_id="common")],
        )
        skill_b = Skill(
            id="skill_b",
            name="Skill B",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Also depends on common",
            dependencies=[SkillDependency(skill_id="common")],
        )

        mock_store.add(skill_common)

        resolved = composer.resolve_dependencies([skill_a, skill_b], mock_store)
        # Should have 3 skills: A, B, and common (not duplicated)
        assert len(resolved) == 3
        assert len([s for s in resolved if s.id == "common"]) == 1


class TestTopologicalSort:
    """Test topological sorting for dependency ordering."""

    def test_topological_sort_simple(self, composer):
        """Test simple topological sort (A depends on B)."""
        skill_a = Skill(
            id="skill_a",
            name="Skill A",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Depends on B",
            dependencies=[SkillDependency(skill_id="skill_b")],
        )
        skill_b = Skill(
            id="skill_b",
            name="Skill B",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="No dependencies",
        )

        sorted_skills = composer._topological_sort([skill_a, skill_b])
        # B should come before A
        assert sorted_skills.index(skill_b) < sorted_skills.index(skill_a)

    def test_topological_sort_complex(self, composer):
        """Test complex dependency graph."""
        # D -> B -> A
        # D -> C -> A
        skill_a = Skill(id="a", name="A", kind=SkillKind.RUNTIME, version="1.0.0", description="Base")
        skill_b = Skill(
            id="b",
            name="B",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Depends on A",
            dependencies=[SkillDependency(skill_id="a")],
        )
        skill_c = Skill(
            id="c",
            name="C",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Depends on A",
            dependencies=[SkillDependency(skill_id="a")],
        )
        skill_d = Skill(
            id="d",
            name="D",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Depends on B and C",
            dependencies=[
                SkillDependency(skill_id="b"),
                SkillDependency(skill_id="c"),
            ],
        )

        sorted_skills = composer._topological_sort([skill_d, skill_c, skill_b, skill_a])

        # A should be first
        assert sorted_skills[0] == skill_a
        # B and C should come after A but before D
        assert sorted_skills.index(skill_b) > sorted_skills.index(skill_a)
        assert sorted_skills.index(skill_c) > sorted_skills.index(skill_a)
        # D should be last
        assert sorted_skills[-1] == skill_d


class TestCircularDependencyDetection:
    """Test circular dependency detection."""

    def test_detect_simple_circular_dependency(self, composer):
        """Test detection of A -> B -> A."""
        skill_a = Skill(
            id="skill_a",
            name="Skill A",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Depends on B",
            dependencies=[SkillDependency(skill_id="skill_b")],
        )
        skill_b = Skill(
            id="skill_b",
            name="Skill B",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Depends on A",
            dependencies=[SkillDependency(skill_id="skill_a")],
        )

        cycle = composer._detect_circular_dependencies([skill_a, skill_b])
        assert cycle is not None
        assert len(cycle) >= 2

    def test_detect_no_circular_dependency(self, composer):
        """Test that acyclic graph returns None."""
        skill_a = Skill(
            id="skill_a",
            name="Skill A",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Depends on B",
            dependencies=[SkillDependency(skill_id="skill_b")],
        )
        skill_b = Skill(
            id="skill_b",
            name="Skill B",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="No dependencies",
        )

        cycle = composer._detect_circular_dependencies([skill_a, skill_b])
        assert cycle is None

    def test_detect_self_dependency(self, composer):
        """Test detection of self-dependency (A -> A)."""
        skill_a = Skill(
            id="skill_a",
            name="Skill A",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Depends on itself",
            dependencies=[SkillDependency(skill_id="skill_a")],
        )

        cycle = composer._detect_circular_dependencies([skill_a])
        assert cycle is not None


class TestConflictDetection:
    """Test conflict detection."""

    def test_detect_surface_mutation_conflict(self, composer):
        """Test detection of multiple skills mutating same surface."""
        skill_1 = Skill(
            id="skill_1",
            name="Skill 1",
            kind=SkillKind.BUILD,
            version="1.0.0",
            description="Mutates instruction",
            mutations=[
                MutationOperator(
                    name="mut1",
                    description="Mutation 1",
                    target_surface="instruction",
                    operator_type="append",
                )
            ],
        )
        skill_2 = Skill(
            id="skill_2",
            name="Skill 2",
            kind=SkillKind.BUILD,
            version="1.0.0",
            description="Also mutates instruction",
            mutations=[
                MutationOperator(
                    name="mut2",
                    description="Mutation 2",
                    target_surface="instruction",
                    operator_type="replace",
                )
            ],
        )

        conflicts = composer.detect_conflicts([skill_1, skill_2])
        surface_conflicts = [c for c in conflicts if c.type == ConflictType.SURFACE_MUTATION]
        assert len(surface_conflicts) == 1
        assert surface_conflicts[0].surface == "instruction"

    def test_detect_tool_collision(self, composer):
        """Test detection of multiple skills defining same tool."""
        skill_1 = Skill(
            id="skill_1",
            name="Skill 1",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Defines tool_a",
            tools=[
                ToolDefinition(
                    name="tool_a",
                    description="Tool A",
                    parameters={},
                )
            ],
        )
        skill_2 = Skill(
            id="skill_2",
            name="Skill 2",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Also defines tool_a",
            tools=[
                ToolDefinition(
                    name="tool_a",
                    description="Different Tool A",
                    parameters={},
                )
            ],
        )

        conflicts = composer.detect_conflicts([skill_1, skill_2])
        tool_conflicts = [c for c in conflicts if c.type == ConflictType.TOOL_COLLISION]
        assert len(tool_conflicts) == 1
        assert tool_conflicts[0].severity == ConflictSeverity.ERROR

    def test_detect_policy_collision(self, composer):
        """Test detection of conflicting policies."""
        skill_1 = Skill(
            id="skill_1",
            name="Skill 1",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Allows action",
            policies=[
                Policy(
                    name="allow_delete",
                    description="Allow delete",
                    rule_type="allow",
                    condition="action == 'delete'",
                    action="permit",
                )
            ],
        )
        skill_2 = Skill(
            id="skill_2",
            name="Skill 2",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Denies same action",
            policies=[
                Policy(
                    name="deny_delete",
                    description="Deny delete",
                    rule_type="deny",
                    condition="action == 'delete'",
                    action="reject",
                )
            ],
        )

        conflicts = composer.detect_conflicts([skill_1, skill_2])
        policy_conflicts = [c for c in conflicts if c.type == ConflictType.POLICY_COLLISION]
        assert len(policy_conflicts) == 1


class TestComposition:
    """Test full composition flow."""

    def test_compose_empty_list(self, composer):
        """Test composing empty skill list."""
        skillset = composer.compose([])
        assert len(skillset.skills) == 0
        assert skillset.validate()

    def test_compose_single_skill(self, composer, simple_runtime_skill):
        """Test composing single skill."""
        skillset = composer.compose([simple_runtime_skill])
        assert len(skillset.skills) == 1
        assert skillset.skills[0] == simple_runtime_skill
        assert skillset.validate()

    def test_compose_multiple_skills_no_conflicts(self, composer):
        """Test composing multiple skills without conflicts."""
        skill_1 = Skill(
            id="skill_1",
            name="Skill 1",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="First skill",
            instructions="Do task 1",
        )
        skill_2 = Skill(
            id="skill_2",
            name="Skill 2",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Second skill",
            instructions="Do task 2",
        )

        skillset = composer.compose([skill_1, skill_2])
        assert len(skillset.skills) == 2
        assert skillset.validate()
        # Check merged instructions
        assert "Skill 1" in skillset.merged_instructions
        assert "Skill 2" in skillset.merged_instructions

    def test_compose_with_dependencies(self, composer, mock_store):
        """Test composition with dependency resolution."""
        skill_a = Skill(
            id="skill_a",
            name="Skill A",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Depends on B",
            dependencies=[SkillDependency(skill_id="skill_b")],
        )
        skill_b = Skill(
            id="skill_b",
            name="Skill B",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="No dependencies",
        )

        mock_store.add(skill_b)

        skillset = composer.compose([skill_a], store=mock_store)
        assert len(skillset.skills) == 2
        # B should come before A in the ordered list
        assert skillset.skills.index(skill_b) < skillset.skills.index(skill_a)

    def test_compose_with_conflicts_fails(self, composer):
        """Test that composition with conflicts fails when strategy is FAIL."""
        skill_1 = Skill(
            id="skill_1",
            name="Skill 1",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Defines tool",
            tools=[
                ToolDefinition(name="same_tool", description="Tool 1", parameters={})
            ],
        )
        skill_2 = Skill(
            id="skill_2",
            name="Skill 2",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Defines same tool",
            tools=[
                ToolDefinition(name="same_tool", description="Tool 2", parameters={})
            ],
        )

        with pytest.raises(ValueError, match="Cannot compose skills"):
            composer.compose([skill_1, skill_2])

    def test_compose_with_conflicts_prefer_first(self):
        """Test composition with PREFER_FIRST strategy."""
        composer = SkillComposer(conflict_strategy=ResolutionStrategy.PREFER_FIRST)

        skill_1 = Skill(
            id="skill_1",
            name="Skill 1",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="First tool",
            tools=[
                ToolDefinition(
                    name="same_tool",
                    description="First description",
                    parameters={},
                )
            ],
        )
        skill_2 = Skill(
            id="skill_2",
            name="Skill 2",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Second tool",
            tools=[
                ToolDefinition(
                    name="same_tool",
                    description="Second description",
                    parameters={},
                )
            ],
        )

        skillset = composer.compose([skill_1, skill_2])
        # Should prefer first definition
        assert "same_tool" in skillset.merged_tools
        assert skillset.merged_tools["same_tool"]["description"] == "First description"

    def test_compose_merges_tools_correctly(self, composer):
        """Test that tools are merged correctly."""
        skill_1 = Skill(
            id="skill_1",
            name="Skill 1",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Has tool A",
            tools=[
                ToolDefinition(name="tool_a", description="Tool A", parameters={})
            ],
        )
        skill_2 = Skill(
            id="skill_2",
            name="Skill 2",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Has tool B",
            tools=[
                ToolDefinition(name="tool_b", description="Tool B", parameters={})
            ],
        )

        skillset = composer.compose([skill_1, skill_2])
        assert len(skillset.merged_tools) == 2
        assert "tool_a" in skillset.merged_tools
        assert "tool_b" in skillset.merged_tools

    def test_compose_mixed_build_and_runtime_skills(self, composer):
        """Test composing both build-time and run-time skills."""
        build_skill = Skill(
            id="build_1",
            name="Build Skill",
            kind=SkillKind.BUILD,
            version="1.0.0",
            description="Build-time skill",
            mutations=[
                MutationOperator(
                    name="mut1",
                    description="Mutation",
                    target_surface="instruction",
                    operator_type="append",
                )
            ],
        )
        runtime_skill = Skill(
            id="runtime_1",
            name="Runtime Skill",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Run-time skill",
            tools=[
                ToolDefinition(name="tool_1", description="Tool", parameters={})
            ],
        )

        skillset = composer.compose([build_skill, runtime_skill])
        assert len(skillset.skills) == 2
        # Should only merge runtime tools
        assert len(skillset.merged_tools) == 1


class TestSkillSetMetadata:
    """Test skill set metadata and properties."""

    def test_skillset_metadata_populated(self, composer, simple_runtime_skill):
        """Test that metadata is properly populated."""
        skillset = composer.compose([simple_runtime_skill], name="Test Set", description="Test")
        assert skillset.name == "Test Set"
        assert skillset.description == "Test"
        assert skillset.metadata["num_skills"] == 1

    def test_skillset_tags_merged(self, composer):
        """Test that tags from multiple skills are merged."""
        skill_1 = Skill(
            id="s1",
            name="S1",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Tagged",
            tags=["tag1", "tag2"],
        )
        skill_2 = Skill(
            id="s2",
            name="S2",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Also tagged",
            tags=["tag2", "tag3"],
        )

        skillset = composer.compose([skill_1, skill_2])
        assert set(skillset.tags) == {"tag1", "tag2", "tag3"}

    def test_skillset_to_dict(self, composer, simple_runtime_skill):
        """Test converting skill set to dictionary."""
        skillset = composer.compose([simple_runtime_skill])
        data = skillset.to_dict()

        assert data["id"] == skillset.id
        assert data["name"] == skillset.name
        assert len(data["skills"]) == 1
        assert "metadata" in data
