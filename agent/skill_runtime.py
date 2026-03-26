"""Runtime skill manager for agent configuration.

This module provides runtime integration of skills into agent configurations.
Run-time skills encode WHAT the agent can do (tools, instructions, policies).

Key Features:
- Load skills by reference (e.g., "order_lookup@1.2")
- Validate skills against agent config (dependencies, conflicts)
- Apply skills to config (merge tools, instructions, policies)
- A/B testing support (enable skills for % of conversations)
- Production-ready with comprehensive error handling
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from core.skills.composer import SkillComposer, ResolutionStrategy
from core.skills.store import SkillStore
from core.skills.types import Skill, SkillKind
from core.skills.validator import SkillValidator, ValidationResult


@dataclass
class SkillReference:
    """A reference to a skill by name and version constraint.

    Examples:
        - "order_lookup@1.2" -> name="order_lookup", version="1.2"
        - "refund_processing@1.0" -> name="refund_processing", version="1.0"
        - "identity_verification@^2.1" -> name="identity_verification", version="^2.1"
    """
    name: str
    version: str = "*"

    @classmethod
    def parse(cls, ref: str) -> SkillReference:
        """Parse a skill reference string.

        Args:
            ref: Reference string in format "name@version" or just "name"

        Returns:
            Parsed SkillReference

        Raises:
            ValueError: If reference format is invalid
        """
        if "@" in ref:
            parts = ref.split("@", 1)
            if len(parts) != 2:
                raise ValueError(f"Invalid skill reference: {ref}")
            name, version = parts
            if not name or not version:
                raise ValueError(f"Invalid skill reference: {ref}")
            # Check for multiple @ symbols (invalid format)
            if "@" in version:
                raise ValueError(f"Invalid skill reference: {ref}")
            return cls(name=name.strip(), version=version.strip())
        else:
            return cls(name=ref.strip(), version="*")

    def __str__(self) -> str:
        return f"{self.name}@{self.version}"


@dataclass
class SkillConfig:
    """Per-skill runtime configuration.

    Allows parameterizing skills at deployment time without modifying the skill itself.
    """
    enabled: bool = True
    parameters: dict[str, Any] = field(default_factory=dict)
    ab_test_percentage: float = 1.0  # 0-1, fraction of conversations to enable for

    def should_enable(self) -> bool:
        """Check if skill should be enabled for this invocation (A/B test).

        Returns:
            True if enabled and passes A/B test
        """
        if not self.enabled:
            return False

        # For deterministic behavior in tests, always enable at 1.0
        if self.ab_test_percentage >= 1.0:
            return True

        # Simple A/B test based on time hash
        # In production, you'd use a proper A/B testing framework
        import random
        return random.random() < self.ab_test_percentage


class SkillRuntime:
    """Runtime manager for skills in agent configurations.

    This manager handles:
    - Loading skills by reference from the skill store
    - Validating skills against agent config
    - Applying skills to agent config (merging tools, instructions, policies)
    - A/B testing skills
    - Dependency resolution via SkillComposer

    Example:
        ```python
        runtime = SkillRuntime(store)

        # Load skills
        skills = runtime.load_skills(["order_lookup@1.2", "refund@1.0"], store)

        # Validate
        result = runtime.validate_skills(skills, agent_config)
        if not result.is_valid:
            raise ValueError(result.errors)

        # Apply to config
        enriched_config = runtime.apply_to_config(skills, agent_config)
        ```
    """

    def __init__(
        self,
        store: SkillStore,
        conflict_strategy: ResolutionStrategy = ResolutionStrategy.FAIL,
    ) -> None:
        """Initialize the skill runtime.

        Args:
            store: SkillStore to load skills from
            conflict_strategy: Strategy for resolving skill conflicts
        """
        self.store = store
        self.validator = SkillValidator()
        self.composer = SkillComposer(conflict_strategy=conflict_strategy)
        self.conflict_strategy = conflict_strategy

    def load_skills(
        self,
        skill_refs: list[str],
        skill_configs: dict[str, SkillConfig] | None = None,
    ) -> list[Skill]:
        """Load skills by reference from the store.

        Args:
            skill_refs: List of skill references (e.g., ["order_lookup@1.2", "refund@1.0"])
            skill_configs: Optional per-skill configs for A/B testing and parameters

        Returns:
            List of loaded skills

        Raises:
            ValueError: If a skill reference cannot be resolved
        """
        skills: list[Skill] = []
        configs = skill_configs or {}

        for ref_str in skill_refs:
            try:
                ref = SkillReference.parse(ref_str)
            except ValueError as e:
                raise ValueError(f"Invalid skill reference '{ref_str}': {e}") from e

            # Check A/B test config
            config = configs.get(ref.name, SkillConfig())
            if not config.should_enable():
                continue

            # Load from store
            skill = self._resolve_skill(ref)
            if skill is None:
                raise ValueError(f"Skill not found: {ref}")

            # Validate it's a runtime skill
            if not skill.is_runtime():
                raise ValueError(
                    f"Skill '{ref}' is not a runtime skill (kind={skill.kind.value})"
                )

            skills.append(skill)

        return skills

    def validate_skills(
        self,
        skills: list[Skill],
        agent_config: dict[str, Any],
    ) -> ValidationResult:
        """Validate skills against agent config.

        Checks:
        - Individual skill validation (schema, tests)
        - Dependencies are met
        - No conflicts between skills
        - Skills are compatible with agent config

        Args:
            skills: List of skills to validate
            agent_config: Agent configuration dict

        Returns:
            ValidationResult with errors/warnings
        """
        result = ValidationResult(is_valid=True)

        if not skills:
            return result

        # Validate each skill individually
        for skill in skills:
            skill_result = self.validator.validate_full(skill, store=self.store)
            result.merge(skill_result)

        # Detect conflicts between skills
        conflicts = self.composer.detect_conflicts(skills)
        for conflict in conflicts:
            if conflict.severity.value == "error":
                result.add_error(conflict.description)
            elif conflict.severity.value == "warning":
                result.add_warning(conflict.description)

        # Validate skill compatibility with agent config
        self._validate_agent_compatibility(skills, agent_config, result)

        return result

    def apply_to_config(
        self,
        skills: list[Skill],
        agent_config: dict[str, Any],
        skill_configs: dict[str, SkillConfig] | None = None,
    ) -> dict[str, Any]:
        """Apply skills to agent config by merging tools, instructions, and policies.

        Args:
            skills: List of skills to apply
            agent_config: Base agent configuration
            skill_configs: Optional per-skill runtime configs

        Returns:
            Enhanced agent config with skills applied
        """
        if not skills:
            return agent_config.copy()

        # Filter by A/B test
        configs = skill_configs or {}
        enabled_skills = [
            s for s in skills
            if configs.get(s.name, SkillConfig()).should_enable()
        ]

        if not enabled_skills:
            return agent_config.copy()

        # Compose skills (resolve dependencies, detect conflicts, merge)
        skillset = self.composer.compose(
            enabled_skills,
            store=self.store,
            name="runtime_skillset",
            description="Runtime skills for agent configuration",
        )

        # Start with base config
        enriched = agent_config.copy()

        # Merge tools
        tools = self.extract_tools(skillset.skills)
        if tools:
            if "tools" not in enriched:
                enriched["tools"] = {}
            for tool in tools:
                tool_name = tool["name"]
                # Don't override existing tools unless conflict resolution says so
                if tool_name not in enriched["tools"]:
                    enriched["tools"][tool_name] = tool

        # Merge instructions
        instructions = self.extract_instructions(skillset.skills)
        if instructions:
            if "prompts" not in enriched:
                enriched["prompts"] = {}

            # Append skill instructions to root prompt
            root_prompt = enriched["prompts"].get("root", "")
            if root_prompt and not root_prompt.endswith("\n"):
                root_prompt += "\n"
            root_prompt += f"\n# Skills\n{instructions}"
            enriched["prompts"]["root"] = root_prompt

        # Merge policies
        policies = self.extract_policies(skillset.skills)
        if policies:
            if "policies" not in enriched:
                enriched["policies"] = []
            enriched["policies"].extend(policies)

        # Add metadata about applied skills
        if "metadata" not in enriched:
            enriched["metadata"] = {}
        enriched["metadata"]["applied_skills"] = [
            {"name": s.name, "version": s.version, "id": s.id}
            for s in enabled_skills
        ]
        enriched["metadata"]["skill_application_time"] = time.time()

        return enriched

    def extract_tools(self, skills: list[Skill]) -> list[dict[str, Any]]:
        """Extract all tools from skills.

        Args:
            skills: List of skills

        Returns:
            List of tool definitions as dicts
        """
        tools: list[dict[str, Any]] = []
        seen_names: set[str] = set()

        for skill in skills:
            if not skill.is_runtime():
                continue

            for tool in skill.tools:
                # Deduplicate by name (first one wins)
                if tool.name not in seen_names:
                    tools.append(tool.to_dict())
                    seen_names.add(tool.name)

        return tools

    def extract_instructions(self, skills: list[Skill]) -> str:
        """Extract and merge instructions from skills.

        Args:
            skills: List of skills

        Returns:
            Merged instructions string
        """
        sections: list[str] = []

        for skill in skills:
            if not skill.is_runtime():
                continue

            if skill.instructions:
                header = f"## {skill.name}"
                sections.append(f"{header}\n{skill.instructions}")

        return "\n\n".join(sections)

    def extract_policies(self, skills: list[Skill]) -> list[dict[str, Any]]:
        """Extract all policies from skills.

        Args:
            skills: List of skills

        Returns:
            List of policy definitions as dicts
        """
        policies: list[dict[str, Any]] = []
        seen_names: set[str] = set()

        for skill in skills:
            if not skill.is_runtime():
                continue

            for policy in skill.policies:
                # Deduplicate by name (first one wins)
                if policy.name not in seen_names:
                    policies.append(policy.to_dict())
                    seen_names.add(policy.name)

        return policies

    def _resolve_skill(self, ref: SkillReference) -> Skill | None:
        """Resolve a skill reference to a concrete skill.

        Args:
            ref: Skill reference to resolve

        Returns:
            Resolved skill or None if not found
        """
        # Try exact version first (if not a wildcard or constraint)
        if ref.version != "*" and not any(ref.version.startswith(c) for c in ["^", "~", ">", "<"]):
            # Try exact match
            skill = self.store.get_by_name(ref.name, version=ref.version)
            if skill:
                return skill

        # Try latest compatible version
        # For now, just get latest (full semver matching would be done by validator)
        skill = self.store.get_by_name(ref.name, version=None)

        # Verify version constraint if specified
        if skill and ref.version != "*":
            if not self._version_matches(skill.version, ref.version):
                return None

        return skill

    def _version_matches(self, version: str, constraint: str) -> bool:
        """Check if version matches constraint.

        Delegates to validator's version checking logic.
        """
        return self.validator._is_version_compatible(version, constraint)

    def _validate_agent_compatibility(
        self,
        skills: list[Skill],
        agent_config: dict[str, Any],
        result: ValidationResult,
    ) -> None:
        """Validate that skills are compatible with agent config.

        Checks:
        - Tool implementations are available
        - Required config sections exist
        """
        # Check if agent config has required sections
        if "prompts" not in agent_config:
            result.add_warning("Agent config missing 'prompts' section")

        if "tools" not in agent_config:
            result.add_warning("Agent config missing 'tools' section")

        # Check for tool implementation conflicts
        existing_tools = agent_config.get("tools", {})
        for skill in skills:
            for tool in skill.tools:
                if tool.name in existing_tools:
                    result.add_warning(
                        f"Tool '{tool.name}' from skill '{skill.name}' conflicts "
                        f"with existing tool in agent config"
                    )
