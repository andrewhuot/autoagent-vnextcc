"""Skill composition engine with dependency resolution and conflict detection.

This module provides the ability to compose multiple skills into a SkillSet,
resolving dependencies, detecting conflicts, and optimizing execution order.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, Any

import yaml

from core.skills.types import Skill, SkillKind, SkillDependency


class ConflictType(str, Enum):
    """Type of composition conflict."""
    SURFACE_MUTATION = "surface_mutation"  # Two build-time skills mutate same surface
    TOOL_COLLISION = "tool_collision"  # Two run-time skills define same tool name
    POLICY_COLLISION = "policy_collision"  # Two run-time skills have conflicting policies
    CIRCULAR_DEPENDENCY = "circular_dependency"


class ConflictSeverity(str, Enum):
    """Severity level of a conflict."""
    ERROR = "error"  # Cannot be composed, must be resolved
    WARNING = "warning"  # Can be composed but may have issues
    INFO = "info"  # Informational, no action needed


class ResolutionStrategy(str, Enum):
    """Strategy for resolving conflicts."""
    FAIL = "fail"  # Fail composition on conflict
    SKIP = "skip"  # Skip conflicting skills
    MERGE = "merge"  # Attempt to merge conflicting elements
    PREFER_FIRST = "prefer_first"  # Keep first skill's version
    PREFER_LAST = "prefer_last"  # Keep last skill's version
    MANUAL = "manual"  # Requires manual resolution


@dataclass
class CompositionConflict:
    """Represents a conflict between skills during composition."""
    type: ConflictType
    severity: ConflictSeverity
    skill_ids: list[str]
    description: str
    surface: str | None = None  # The surface or element that conflicts
    resolution_strategy: ResolutionStrategy = ResolutionStrategy.FAIL
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "severity": self.severity.value,
            "skill_ids": self.skill_ids,
            "description": self.description,
            "surface": self.surface,
            "resolution_strategy": self.resolution_strategy.value,
            "metadata": self.metadata,
        }


class SkillStoreProtocol(Protocol):
    """Protocol for skill store implementations."""

    def get(self, name: str, version: int | None = None) -> Skill | None:
        """Get a skill by name and optional version."""
        ...


@dataclass
class SkillSet:
    """A composed set of skills with resolved dependencies and execution order.

    A SkillSet represents the final composed set of skills ready for execution.
    It contains:
    - The ordered list of skills (dependencies first)
    - Any conflicts detected during composition
    - Merged instructions and tools for run-time skills
    - Combined metadata
    """
    id: str
    name: str
    description: str
    skills: list[Skill] = field(default_factory=list)  # Ordered by dependencies
    conflicts: list[CompositionConflict] = field(default_factory=list)

    # Merged run-time content (for run-time skill sets)
    merged_instructions: str = ""
    merged_tools: dict[str, Any] = field(default_factory=dict)  # tool_name -> ToolDefinition
    merged_policies: list[Any] = field(default_factory=list)

    # Metadata
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def validate(self) -> bool:
        """Validate that the skill set is valid for execution.

        Returns:
            True if valid, False if there are blocking conflicts.
        """
        # Check for error-level conflicts
        for conflict in self.conflicts:
            if conflict.severity == ConflictSeverity.ERROR:
                return False

        # Verify no circular dependencies (should have been caught earlier)
        if any(c.type == ConflictType.CIRCULAR_DEPENDENCY for c in self.conflicts):
            return False

        # Validate each skill
        for skill in self.skills:
            if skill.status != "active":
                return False

        return True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "skills": [s.to_dict() for s in self.skills],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "merged_instructions": self.merged_instructions,
            "merged_tools": self.merged_tools,
            "merged_policies": self.merged_policies,
            "tags": self.tags,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    def to_yaml(self) -> str:
        """Export skill set to YAML format."""
        data = {
            "skillset": {
                "id": self.id,
                "name": self.name,
                "description": self.description,
                "skills": [
                    {
                        "id": s.id,
                        "name": s.name,
                        "version": s.version,
                        "kind": s.kind.value,
                    }
                    for s in self.skills
                ],
                "conflicts": [c.to_dict() for c in self.conflicts],
                "merged_instructions": self.merged_instructions if self.merged_instructions else None,
                "merged_tools": self.merged_tools if self.merged_tools else None,
                "tags": self.tags,
                "metadata": self.metadata,
                "created_at": self.created_at,
            }
        }
        return yaml.dump(data, default_flow_style=False, sort_keys=False)


class SkillComposer:
    """Main composition engine for combining multiple skills.

    The SkillComposer handles:
    - Dependency resolution and topological sorting
    - Conflict detection (surface mutations, tool collisions, etc.)
    - Merging instructions and tools from multiple run-time skills
    - Validation of composed skill sets
    """

    def __init__(self, conflict_strategy: ResolutionStrategy = ResolutionStrategy.FAIL):
        """Initialize the composer.

        Args:
            conflict_strategy: Default strategy for resolving conflicts.
        """
        self.conflict_strategy = conflict_strategy

    def compose(
        self,
        skills: list[Skill],
        store: SkillStoreProtocol | None = None,
        name: str = "composed_skillset",
        description: str = "",
    ) -> SkillSet:
        """Compose multiple skills into a validated SkillSet.

        Args:
            skills: List of skills to compose.
            store: Optional skill store for resolving dependencies.
            name: Name for the resulting skill set.
            description: Description of the skill set.

        Returns:
            A composed SkillSet with ordered skills and detected conflicts.

        Raises:
            ValueError: If composition fails due to unresolvable conflicts.
        """
        if not skills:
            return SkillSet(
                id=f"skillset_{int(time.time())}",
                name=name,
                description=description or "Empty skill set",
            )

        # Step 1: Resolve dependencies and get full skill list
        if store is not None:
            all_skills = self.resolve_dependencies(skills, store)
        else:
            all_skills = skills

        # Step 2: Detect conflicts
        conflicts = self.detect_conflicts(all_skills)

        # Step 3: Check if we have blocking conflicts
        error_conflicts = [c for c in conflicts if c.severity == ConflictSeverity.ERROR]
        if error_conflicts and self.conflict_strategy == ResolutionStrategy.FAIL:
            conflict_desc = "; ".join(c.description for c in error_conflicts)
            raise ValueError(f"Cannot compose skills due to conflicts: {conflict_desc}")

        # Step 4: Order skills by dependencies (topological sort)
        ordered_skills = self._topological_sort(all_skills)

        # Step 5: Merge run-time content if applicable
        merged_instructions = ""
        merged_tools: dict[str, Any] = {}
        merged_policies: list[Any] = []

        runtime_skills = [s for s in ordered_skills if s.is_runtime()]
        if runtime_skills:
            merged_instructions = self._merge_instructions(runtime_skills)
            merged_tools = self._merge_tools(runtime_skills, conflicts)
            merged_policies = self._merge_policies(runtime_skills)

        # Step 6: Create the skill set
        skillset = SkillSet(
            id=f"skillset_{int(time.time())}",
            name=name,
            description=description or f"Composed from {len(ordered_skills)} skills",
            skills=ordered_skills,
            conflicts=conflicts,
            merged_instructions=merged_instructions,
            merged_tools=merged_tools,
            merged_policies=merged_policies,
            tags=list(set(tag for skill in ordered_skills for tag in skill.tags)),
            metadata={
                "composition_strategy": self.conflict_strategy.value,
                "num_skills": len(ordered_skills),
                "num_conflicts": len(conflicts),
            },
        )

        return skillset

    def detect_conflicts(self, skills: list[Skill]) -> list[CompositionConflict]:
        """Detect conflicts between skills.

        Detects:
        - Surface mutation conflicts (build-time)
        - Tool name collisions (run-time)
        - Policy conflicts (run-time)
        - Circular dependencies

        Args:
            skills: List of skills to check.

        Returns:
            List of detected conflicts.
        """
        conflicts: list[CompositionConflict] = []

        # Check for circular dependencies
        circular = self._detect_circular_dependencies(skills)
        if circular:
            conflicts.append(
                CompositionConflict(
                    type=ConflictType.CIRCULAR_DEPENDENCY,
                    severity=ConflictSeverity.ERROR,
                    skill_ids=circular,
                    description=f"Circular dependency detected: {' -> '.join(circular)}",
                )
            )

        # Check build-time surface mutation conflicts
        surface_conflicts = self._detect_surface_conflicts(skills)
        conflicts.extend(surface_conflicts)

        # Check run-time tool collisions
        tool_conflicts = self._detect_tool_conflicts(skills)
        conflicts.extend(tool_conflicts)

        # Check policy conflicts
        policy_conflicts = self._detect_policy_conflicts(skills)
        conflicts.extend(policy_conflicts)

        return conflicts

    def resolve_dependencies(
        self,
        skills: list[Skill],
        store: SkillStoreProtocol,
    ) -> list[Skill]:
        """Resolve dependencies and return complete list of skills.

        This performs a breadth-first traversal of the dependency graph,
        fetching all required skills from the store.

        Args:
            skills: Starting list of skills.
            store: Skill store to fetch dependencies from.

        Returns:
            Complete list of skills including all dependencies.

        Raises:
            ValueError: If a required dependency cannot be found.
        """
        result: list[Skill] = []
        seen_ids: set[str] = set()
        queue: list[Skill] = list(skills)

        while queue:
            skill = queue.pop(0)

            if skill.id in seen_ids:
                continue

            seen_ids.add(skill.id)
            result.append(skill)

            # Fetch dependencies
            for dep in skill.dependencies:
                if dep.optional:
                    # Try to fetch but don't fail if missing
                    dep_skill = store.get(dep.skill_id)
                    if dep_skill is not None:
                        queue.append(dep_skill)
                else:
                    # Required dependency
                    dep_skill = store.get(dep.skill_id)
                    if dep_skill is None:
                        raise ValueError(
                            f"Required dependency '{dep.skill_id}' for skill '{skill.id}' not found"
                        )
                    queue.append(dep_skill)

        return result

    def _topological_sort(self, skills: list[Skill]) -> list[Skill]:
        """Sort skills by dependencies using topological sort.

        Skills with no dependencies come first, followed by skills that
        depend on them, etc.

        Args:
            skills: List of skills to sort.

        Returns:
            Topologically sorted list of skills.
        """
        # Build adjacency list and in-degree map
        skill_map = {s.id: s for s in skills}
        in_degree = {s.id: 0 for s in skills}
        adj_list: dict[str, list[str]] = {s.id: [] for s in skills}

        for skill in skills:
            for dep in skill.dependencies:
                if dep.skill_id in skill_map and not dep.optional:
                    adj_list[dep.skill_id].append(skill.id)
                    in_degree[skill.id] += 1

        # Kahn's algorithm for topological sort
        queue = [skill_id for skill_id in in_degree if in_degree[skill_id] == 0]
        result: list[Skill] = []

        while queue:
            skill_id = queue.pop(0)
            result.append(skill_map[skill_id])

            for neighbor in adj_list[skill_id]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # If result doesn't contain all skills, there's a cycle
        # (but we should have detected this earlier)
        if len(result) != len(skills):
            # Fall back to original order
            return skills

        return result

    def _detect_circular_dependencies(self, skills: list[Skill]) -> list[str] | None:
        """Detect circular dependencies using DFS.

        Args:
            skills: List of skills to check.

        Returns:
            List of skill IDs forming a cycle, or None if no cycle.
        """
        skill_map = {s.id: s for s in skills}
        visited: set[str] = set()
        rec_stack: set[str] = set()
        parent: dict[str, str] = {}

        def dfs(skill_id: str) -> list[str] | None:
            visited.add(skill_id)
            rec_stack.add(skill_id)

            skill = skill_map.get(skill_id)
            if skill is None:
                rec_stack.remove(skill_id)
                return None

            for dep in skill.dependencies:
                if dep.optional or dep.skill_id not in skill_map:
                    continue

                if dep.skill_id not in visited:
                    parent[dep.skill_id] = skill_id
                    cycle = dfs(dep.skill_id)
                    if cycle is not None:
                        return cycle
                elif dep.skill_id in rec_stack:
                    # Found a cycle - reconstruct it
                    cycle = [dep.skill_id]
                    current = skill_id
                    while current != dep.skill_id:
                        cycle.append(current)
                        current = parent.get(current, "")
                        if not current:
                            break
                    cycle.reverse()
                    return cycle

            rec_stack.remove(skill_id)
            return None

        for skill in skills:
            if skill.id not in visited:
                cycle = dfs(skill.id)
                if cycle is not None:
                    return cycle

        return None

    def _detect_surface_conflicts(self, skills: list[Skill]) -> list[CompositionConflict]:
        """Detect conflicts where multiple build-time skills mutate the same surface.

        Args:
            skills: List of skills to check.

        Returns:
            List of surface mutation conflicts.
        """
        conflicts: list[CompositionConflict] = []
        surface_map: dict[str, list[str]] = {}

        for skill in skills:
            if not skill.is_build_time():
                continue

            for mutation in skill.mutations:
                surface = mutation.target_surface
                if surface not in surface_map:
                    surface_map[surface] = []
                surface_map[surface].append(skill.id)

        # Find surfaces with multiple skills
        for surface, skill_ids in surface_map.items():
            if len(skill_ids) > 1:
                conflicts.append(
                    CompositionConflict(
                        type=ConflictType.SURFACE_MUTATION,
                        severity=ConflictSeverity.WARNING,  # Can often be merged
                        skill_ids=skill_ids,
                        description=f"Multiple skills mutate surface '{surface}'",
                        surface=surface,
                        resolution_strategy=ResolutionStrategy.MERGE,
                    )
                )

        return conflicts

    def _detect_tool_conflicts(self, skills: list[Skill]) -> list[CompositionConflict]:
        """Detect conflicts where multiple run-time skills define the same tool.

        Args:
            skills: List of skills to check.

        Returns:
            List of tool collision conflicts.
        """
        conflicts: list[CompositionConflict] = []
        tool_map: dict[str, list[str]] = {}

        for skill in skills:
            if not skill.is_runtime():
                continue

            for tool in skill.tools:
                tool_name = tool.name
                if tool_name not in tool_map:
                    tool_map[tool_name] = []
                tool_map[tool_name].append(skill.id)

        # Find tools defined by multiple skills
        for tool_name, skill_ids in tool_map.items():
            if len(skill_ids) > 1:
                conflicts.append(
                    CompositionConflict(
                        type=ConflictType.TOOL_COLLISION,
                        severity=ConflictSeverity.ERROR,  # Must be resolved
                        skill_ids=skill_ids,
                        description=f"Multiple skills define tool '{tool_name}'",
                        surface=tool_name,
                        resolution_strategy=ResolutionStrategy.PREFER_FIRST,
                    )
                )

        return conflicts

    def _detect_policy_conflicts(self, skills: list[Skill]) -> list[CompositionConflict]:
        """Detect conflicts between policies from different skills.

        Args:
            skills: List of skills to check.

        Returns:
            List of policy conflicts.
        """
        conflicts: list[CompositionConflict] = []

        # Collect all policies
        all_policies = []
        for skill in skills:
            if skill.is_runtime():
                for policy in skill.policies:
                    all_policies.append((skill.id, policy))

        # Check for conflicting allow/deny rules
        # This is a simplified check - real implementation would be more sophisticated
        allow_policies = [(sid, p) for sid, p in all_policies if p.rule_type == "allow"]
        deny_policies = [(sid, p) for sid, p in all_policies if p.rule_type == "deny"]

        for skill_id_allow, allow_policy in allow_policies:
            for skill_id_deny, deny_policy in deny_policies:
                # Simple heuristic: same condition with opposite rules
                if allow_policy.condition == deny_policy.condition:
                    conflicts.append(
                        CompositionConflict(
                            type=ConflictType.POLICY_COLLISION,
                            severity=ConflictSeverity.WARNING,
                            skill_ids=[skill_id_allow, skill_id_deny],
                            description=f"Conflicting policies: '{allow_policy.name}' vs '{deny_policy.name}'",
                            surface=allow_policy.condition,
                            resolution_strategy=ResolutionStrategy.MANUAL,
                        )
                    )

        return conflicts

    def _merge_instructions(self, skills: list[Skill]) -> str:
        """Merge instructions from multiple run-time skills.

        Args:
            skills: List of run-time skills.

        Returns:
            Merged instructions string.
        """
        sections = []
        for skill in skills:
            if skill.instructions:
                sections.append(f"# {skill.name}\n{skill.instructions}")

        return "\n\n".join(sections)

    def _merge_tools(
        self,
        skills: list[Skill],
        conflicts: list[CompositionConflict],
    ) -> dict[str, Any]:
        """Merge tools from multiple run-time skills, handling conflicts.

        Args:
            skills: List of run-time skills.
            conflicts: List of detected conflicts.

        Returns:
            Dictionary mapping tool names to ToolDefinitions.
        """
        merged: dict[str, Any] = {}

        # Get tool conflicts
        tool_conflicts = [
            c for c in conflicts if c.type == ConflictType.TOOL_COLLISION
        ]
        conflict_tools = set(c.surface for c in tool_conflicts if c.surface)

        for skill in skills:
            for tool in skill.tools:
                if tool.name in conflict_tools:
                    # Apply resolution strategy
                    if self.conflict_strategy == ResolutionStrategy.PREFER_FIRST:
                        if tool.name not in merged:
                            merged[tool.name] = tool.to_dict()
                    elif self.conflict_strategy == ResolutionStrategy.PREFER_LAST:
                        merged[tool.name] = tool.to_dict()
                    # SKIP and FAIL are handled elsewhere
                else:
                    merged[tool.name] = tool.to_dict()

        return merged

    def _merge_policies(self, skills: list[Skill]) -> list[Any]:
        """Merge policies from multiple run-time skills.

        Args:
            skills: List of run-time skills.

        Returns:
            List of merged policies.
        """
        merged = []
        seen_names = set()

        for skill in skills:
            for policy in skill.policies:
                if policy.name not in seen_names:
                    merged.append(policy.to_dict())
                    seen_names.add(policy.name)

        return merged
