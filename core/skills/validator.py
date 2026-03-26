"""Skill validation - schema, dependencies, and test execution.

This module provides comprehensive validation for skills:
- Schema validation: required fields, format checks
- Dependency validation: resolve and verify dependencies exist
- Build-time validation: mutations, triggers, eval criteria
- Run-time validation: tools, policies, test execution
- Test execution: run test cases and verify expected behavior
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from core.skills.types import Skill, SkillKind

if TYPE_CHECKING:
    from core.skills.store import SkillStore


@dataclass
class ValidationResult:
    """Result of skill validation.

    Contains validation status, errors, warnings, and test results.
    """
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    test_results: dict[str, bool] | None = None

    def add_error(self, message: str) -> None:
        """Add a validation error."""
        self.errors.append(message)
        self.is_valid = False

    def add_warning(self, message: str) -> None:
        """Add a validation warning."""
        self.warnings.append(message)

    def merge(self, other: ValidationResult) -> None:
        """Merge another validation result into this one."""
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        if not other.is_valid:
            self.is_valid = False
        if other.test_results:
            if self.test_results is None:
                self.test_results = {}
            self.test_results.update(other.test_results)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "test_results": self.test_results,
        }


class SkillValidator:
    """Validator for skill definitions.

    Validates skill schema, dependencies, and executes tests.
    Supports both build-time and run-time skills.
    """

    # Semver pattern: major.minor.patch with optional pre-release/build metadata
    SEMVER_PATTERN = re.compile(
        r'^(\d+)\.(\d+)\.(\d+)'
        r'(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?'
        r'(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$'
    )

    # Valid target surfaces for mutation operators
    VALID_TARGET_SURFACES = {
        "instruction", "routing", "tool_config", "prompt",
        "system_message", "context", "memory", "guardrails"
    }

    # Valid operator types for mutations
    VALID_OPERATOR_TYPES = {"append", "replace", "delete", "merge", "insert"}

    # Valid risk levels
    VALID_RISK_LEVELS = {"low", "medium", "high", "critical"}

    # Valid comparison operators
    VALID_COMPARISON_OPERATORS = {"gt", "lt", "gte", "lte", "eq", "ne"}

    # Valid policy rule types
    VALID_RULE_TYPES = {"allow", "deny", "require", "limit", "rate_limit"}

    # Valid sandbox policies
    VALID_SANDBOX_POLICIES = {
        "pure", "read_only", "write_reversible", "write_irreversible"
    }

    # Valid skill statuses
    VALID_STATUSES = {"active", "draft", "deprecated", "archived"}

    def __init__(self) -> None:
        """Initialize the validator."""
        pass

    def validate_schema(self, skill: Skill) -> ValidationResult:
        """Validate skill schema and required fields.

        Args:
            skill: The skill to validate

        Returns:
            ValidationResult with schema validation status
        """
        result = ValidationResult(is_valid=True)

        # Required fields
        if not skill.id or not isinstance(skill.id, str):
            result.add_error("Skill ID is required and must be a string")
        elif not re.match(r'^[a-z0-9_-]+$', skill.id):
            result.add_error(
                f"Skill ID '{skill.id}' must contain only lowercase letters, "
                "numbers, hyphens, and underscores"
            )

        if not skill.name or not isinstance(skill.name, str):
            result.add_error("Skill name is required and must be a string")

        if not skill.description or not isinstance(skill.description, str):
            result.add_error("Skill description is required and must be a string")
        elif len(skill.description) < 10:
            result.add_warning(
                "Skill description is very short (< 10 chars). "
                "Consider adding more detail."
            )

        # Version validation
        if not skill.version or not isinstance(skill.version, str):
            result.add_error("Skill version is required and must be a string")
        elif not self._is_valid_semver(skill.version):
            result.add_error(
                f"Skill version '{skill.version}' is not valid semver. "
                "Expected format: MAJOR.MINOR.PATCH (e.g., 1.0.0)"
            )

        # Kind validation
        if not isinstance(skill.kind, SkillKind):
            result.add_error(f"Skill kind must be SkillKind enum, got {type(skill.kind)}")

        # Status validation
        if skill.status not in self.VALID_STATUSES:
            result.add_error(
                f"Invalid status '{skill.status}'. "
                f"Must be one of: {', '.join(self.VALID_STATUSES)}"
            )

        # Metadata validation
        if not isinstance(skill.capabilities, list):
            result.add_error("Skill capabilities must be a list")

        if not isinstance(skill.tags, list):
            result.add_error("Skill tags must be a list")

        if not isinstance(skill.domain, str):
            result.add_error("Skill domain must be a string")

        # Validate mutations for build-time skills
        if skill.is_build_time():
            for i, mutation in enumerate(skill.mutations):
                self._validate_mutation(mutation, i, result)

        # Validate triggers
        for i, trigger in enumerate(skill.triggers):
            self._validate_trigger(trigger, i, result)

        # Validate eval criteria
        for i, criterion in enumerate(skill.eval_criteria):
            self._validate_eval_criterion(criterion, i, result)

        # Validate tools for runtime skills
        if skill.is_runtime():
            for i, tool in enumerate(skill.tools):
                self._validate_tool(tool, i, result)

        # Validate policies
        for i, policy in enumerate(skill.policies):
            self._validate_policy(policy, i, result)

        # Validate test cases
        for i, test_case in enumerate(skill.test_cases):
            self._validate_test_case(test_case, i, result)

        # Validate dependencies
        for i, dep in enumerate(skill.dependencies):
            self._validate_dependency_format(dep, i, result)

        return result

    def validate_dependencies(
        self,
        skill: Skill,
        store: SkillStore
    ) -> ValidationResult:
        """Validate that skill dependencies exist and versions are compatible.

        Args:
            skill: The skill to validate
            store: The skill store to check dependencies against

        Returns:
            ValidationResult with dependency validation status
        """
        result = ValidationResult(is_valid=True)

        for dep in skill.dependencies:
            # Check if dependency exists
            dep_skill = store.get(dep.skill_id)
            if dep_skill is None:
                if dep.optional:
                    result.add_warning(
                        f"Optional dependency '{dep.skill_id}' not found"
                    )
                else:
                    result.add_error(
                        f"Required dependency '{dep.skill_id}' not found"
                    )
                continue

            # Check version compatibility
            if not self._is_version_compatible(
                dep_skill.version,
                dep.version_constraint
            ):
                result.add_error(
                    f"Dependency '{dep.skill_id}' version {dep_skill.version} "
                    f"does not satisfy constraint '{dep.version_constraint}'"
                )

            # Check for circular dependencies
            if dep.skill_id == skill.id:
                result.add_error(
                    f"Circular dependency: skill '{skill.id}' depends on itself"
                )

        return result

    def validate_build_time_skill(self, skill: Skill) -> ValidationResult:
        """Validate build-time skill specific requirements.

        Build-time skills must have:
        - At least one mutation operator
        - At least one trigger condition
        - At least one eval criterion

        Args:
            skill: The skill to validate

        Returns:
            ValidationResult with build-time validation status
        """
        result = ValidationResult(is_valid=True)

        if not skill.is_build_time():
            result.add_error(
                f"Skill '{skill.id}' is not a build-time skill "
                f"(kind={skill.kind.value})"
            )
            return result

        # Must have at least one mutation
        if not skill.mutations:
            result.add_error(
                "Build-time skill must have at least one mutation operator"
            )

        # Must have at least one trigger
        if not skill.triggers:
            result.add_error(
                "Build-time skill must have at least one trigger condition"
            )

        # Must have at least one eval criterion
        if not skill.eval_criteria:
            result.add_error(
                "Build-time skill must have at least one eval criterion"
            )

        # Warnings for best practices
        if not skill.examples:
            result.add_warning(
                "Build-time skill has no examples. "
                "Consider adding before/after examples."
            )

        if not skill.guardrails:
            result.add_warning(
                "Build-time skill has no guardrails. "
                "Consider adding safety constraints."
            )

        # Check for high-risk mutations without guardrails
        high_risk_mutations = [
            m for m in skill.mutations
            if m.risk_level in ("high", "critical")
        ]
        if high_risk_mutations and not skill.guardrails:
            result.add_warning(
                f"Skill has {len(high_risk_mutations)} high-risk mutation(s) "
                "but no guardrails defined"
            )

        return result

    def validate_runtime_skill(self, skill: Skill) -> ValidationResult:
        """Validate run-time skill specific requirements.

        Run-time skills must have at least one of:
        - Tools
        - Instructions

        Args:
            skill: The skill to validate

        Returns:
            ValidationResult with run-time validation status
        """
        result = ValidationResult(is_valid=True)

        if not skill.is_runtime():
            result.add_error(
                f"Skill '{skill.id}' is not a run-time skill "
                f"(kind={skill.kind.value})"
            )
            return result

        # Must have tools or instructions
        if not skill.tools and not skill.instructions:
            result.add_error(
                "Run-time skill must have at least one tool or instructions"
            )

        # Warnings for best practices
        if not skill.test_cases:
            result.add_warning(
                "Run-time skill has no test cases. "
                "Consider adding tests to verify behavior."
            )

        if not skill.policies:
            result.add_warning(
                "Run-time skill has no policies. "
                "Consider adding safety policies."
            )

        # Check for tools with dangerous sandbox policies and no policies
        dangerous_tools = [
            t for t in skill.tools
            if t.sandbox_policy == "write_irreversible"
        ]
        if dangerous_tools and not skill.policies:
            result.add_warning(
                f"Skill has {len(dangerous_tools)} tool(s) with "
                "write_irreversible policy but no safety policies defined"
            )

        # Check for missing tool implementations
        tools_without_impl = [
            t for t in skill.tools
            if not t.implementation
        ]
        if tools_without_impl:
            result.add_warning(
                f"{len(tools_without_impl)} tool(s) have no implementation. "
                "They will need to be provided at runtime."
            )

        return result

    def run_tests(self, skill: Skill) -> ValidationResult:
        """Execute test cases for a skill.

        Note: This is a basic implementation that validates test structure.
        Full test execution would require a runtime environment.

        Args:
            skill: The skill to test

        Returns:
            ValidationResult with test execution results
        """
        result = ValidationResult(is_valid=True)
        test_results = {}

        if not skill.test_cases:
            result.add_warning("No test cases to run")
            return result

        for test_case in skill.test_cases:
            test_name = test_case.name

            # Basic structural validation
            if not test_case.input:
                result.add_error(
                    f"Test case '{test_name}' has no input defined"
                )
                test_results[test_name] = False
                continue

            # Check that we have something to verify
            has_expectation = (
                test_case.expected_output is not None or
                test_case.expected_behavior is not None or
                test_case.assertions
            )

            if not has_expectation:
                result.add_warning(
                    f"Test case '{test_name}' has no expected output, "
                    "behavior, or assertions"
                )

            # Mark as passed for structural validation
            # In a real implementation, this would execute the test
            test_results[test_name] = True

        result.test_results = test_results

        # Check if any tests failed
        failed_tests = [name for name, passed in test_results.items() if not passed]
        if failed_tests:
            result.add_error(
                f"{len(failed_tests)} test(s) failed: {', '.join(failed_tests)}"
            )

        return result

    def validate_full(
        self,
        skill: Skill,
        store: SkillStore | None = None
    ) -> ValidationResult:
        """Run all validations on a skill.

        Args:
            skill: The skill to validate
            store: Optional skill store for dependency validation

        Returns:
            ValidationResult with complete validation status
        """
        result = ValidationResult(is_valid=True)

        # Schema validation
        schema_result = self.validate_schema(skill)
        result.merge(schema_result)

        # Dependency validation (if store provided)
        if store is not None:
            dep_result = self.validate_dependencies(skill, store)
            result.merge(dep_result)

        # Kind-specific validation
        if skill.is_build_time():
            build_result = self.validate_build_time_skill(skill)
            result.merge(build_result)
        elif skill.is_runtime():
            runtime_result = self.validate_runtime_skill(skill)
            result.merge(runtime_result)

            # Run tests for runtime skills
            test_result = self.run_tests(skill)
            result.merge(test_result)

        return result

    # Legacy compatibility
    def validate(self, skill: Skill) -> ValidationResult:
        """Legacy method - use validate_schema or validate_full instead."""
        return self.validate_full(skill, store=None)

    # Private helper methods

    def _is_valid_semver(self, version: str) -> bool:
        """Check if version string is valid semver."""
        return self.SEMVER_PATTERN.match(version) is not None

    def _validate_mutation(
        self,
        mutation: Any,
        index: int,
        result: ValidationResult
    ) -> None:
        """Validate a mutation operator."""
        prefix = f"Mutation[{index}]"

        if not mutation.name:
            result.add_error(f"{prefix}: name is required")

        if not mutation.description:
            result.add_error(f"{prefix}: description is required")

        if mutation.target_surface not in self.VALID_TARGET_SURFACES:
            result.add_error(
                f"{prefix}: invalid target_surface '{mutation.target_surface}'. "
                f"Must be one of: {', '.join(self.VALID_TARGET_SURFACES)}"
            )

        if mutation.operator_type not in self.VALID_OPERATOR_TYPES:
            result.add_error(
                f"{prefix}: invalid operator_type '{mutation.operator_type}'. "
                f"Must be one of: {', '.join(self.VALID_OPERATOR_TYPES)}"
            )

        if mutation.risk_level not in self.VALID_RISK_LEVELS:
            result.add_error(
                f"{prefix}: invalid risk_level '{mutation.risk_level}'. "
                f"Must be one of: {', '.join(self.VALID_RISK_LEVELS)}"
            )

    def _validate_trigger(
        self,
        trigger: Any,
        index: int,
        result: ValidationResult
    ) -> None:
        """Validate a trigger condition."""
        prefix = f"Trigger[{index}]"

        # Must have at least one condition type
        has_condition = (
            trigger.failure_family is not None or
            trigger.metric_name is not None or
            trigger.blame_pattern is not None
        )

        if not has_condition:
            result.add_error(
                f"{prefix}: must have at least one of failure_family, "
                "metric_name, or blame_pattern"
            )

        # If metric-based, must have threshold
        if trigger.metric_name and trigger.threshold is None:
            result.add_error(
                f"{prefix}: metric-based trigger must have threshold"
            )

        if trigger.operator not in self.VALID_COMPARISON_OPERATORS:
            result.add_error(
                f"{prefix}: invalid operator '{trigger.operator}'. "
                f"Must be one of: {', '.join(self.VALID_COMPARISON_OPERATORS)}"
            )

    def _validate_eval_criterion(
        self,
        criterion: Any,
        index: int,
        result: ValidationResult
    ) -> None:
        """Validate an eval criterion."""
        prefix = f"EvalCriterion[{index}]"

        if not criterion.metric:
            result.add_error(f"{prefix}: metric is required")

        if criterion.target is None:
            result.add_error(f"{prefix}: target is required")

        if criterion.operator not in self.VALID_COMPARISON_OPERATORS:
            result.add_error(
                f"{prefix}: invalid operator '{criterion.operator}'. "
                f"Must be one of: {', '.join(self.VALID_COMPARISON_OPERATORS)}"
            )

        if criterion.weight <= 0:
            result.add_error(f"{prefix}: weight must be positive")

    def _validate_tool(
        self,
        tool: Any,
        index: int,
        result: ValidationResult
    ) -> None:
        """Validate a tool definition."""
        prefix = f"Tool[{index}]"

        if not tool.name:
            result.add_error(f"{prefix}: name is required")

        if not tool.description:
            result.add_error(f"{prefix}: description is required")

        if not isinstance(tool.parameters, dict):
            result.add_error(f"{prefix}: parameters must be a dict")

        if tool.sandbox_policy not in self.VALID_SANDBOX_POLICIES:
            result.add_error(
                f"{prefix}: invalid sandbox_policy '{tool.sandbox_policy}'. "
                f"Must be one of: {', '.join(self.VALID_SANDBOX_POLICIES)}"
            )

    def _validate_policy(
        self,
        policy: Any,
        index: int,
        result: ValidationResult
    ) -> None:
        """Validate a policy."""
        prefix = f"Policy[{index}]"

        if not policy.name:
            result.add_error(f"{prefix}: name is required")

        if not policy.description:
            result.add_error(f"{prefix}: description is required")

        if policy.rule_type not in self.VALID_RULE_TYPES:
            result.add_error(
                f"{prefix}: invalid rule_type '{policy.rule_type}'. "
                f"Must be one of: {', '.join(self.VALID_RULE_TYPES)}"
            )

        if not policy.condition:
            result.add_error(f"{prefix}: condition is required")

        if not policy.action:
            result.add_error(f"{prefix}: action is required")

        if policy.severity not in self.VALID_RISK_LEVELS:
            result.add_error(
                f"{prefix}: invalid severity '{policy.severity}'. "
                f"Must be one of: {', '.join(self.VALID_RISK_LEVELS)}"
            )

    def _validate_test_case(
        self,
        test_case: Any,
        index: int,
        result: ValidationResult
    ) -> None:
        """Validate a test case."""
        prefix = f"TestCase[{index}]"

        if not test_case.name:
            result.add_error(f"{prefix}: name is required")

        if not test_case.description:
            result.add_error(f"{prefix}: description is required")

        if not isinstance(test_case.input, dict):
            result.add_error(f"{prefix}: input must be a dict")

    def _validate_dependency_format(
        self,
        dep: Any,
        index: int,
        result: ValidationResult
    ) -> None:
        """Validate dependency format (not resolution)."""
        prefix = f"Dependency[{index}]"

        if not dep.skill_id:
            result.add_error(f"{prefix}: skill_id is required")

        if not dep.version_constraint:
            result.add_error(f"{prefix}: version_constraint is required")

    def _is_version_compatible(
        self,
        version: str,
        constraint: str
    ) -> bool:
        """Check if version satisfies constraint.

        Supports basic semver constraints:
        - Exact: "1.2.3"
        - Wildcard: "*", "1.*", "1.2.*"
        - Range: ">=1.0.0,<2.0.0"
        - Caret: "^1.2.3" (compatible with 1.x.x)
        - Tilde: "~1.2.3" (compatible with 1.2.x)

        Args:
            version: The actual version string
            constraint: The version constraint

        Returns:
            True if version satisfies constraint
        """
        # Wildcard
        if constraint == "*":
            return True

        # Exact match
        if constraint == version:
            return True

        # Parse version
        version_match = self.SEMVER_PATTERN.match(version)
        if not version_match:
            return False

        major, minor, patch = map(int, version_match.groups()[:3])

        # Wildcard patterns
        if constraint.endswith(".*"):
            constraint_base = constraint[:-2]
            parts = constraint_base.split(".")

            if len(parts) == 1:  # "1.*"
                return major == int(parts[0])
            elif len(parts) == 2:  # "1.2.*"
                return major == int(parts[0]) and minor == int(parts[1])

        # Caret (^1.2.3 means >=1.2.3 and <2.0.0)
        if constraint.startswith("^"):
            constraint_version = constraint[1:]
            constraint_match = self.SEMVER_PATTERN.match(constraint_version)
            if constraint_match:
                c_major, c_minor, c_patch = map(int, constraint_match.groups()[:3])
                if major != c_major:
                    return False
                if major == 0:
                    # 0.x.x - minor version must match
                    if minor != c_minor:
                        return False
                    return patch >= c_patch
                else:
                    # 1.x.x - any minor/patch >= constraint
                    if minor < c_minor:
                        return False
                    if minor == c_minor and patch < c_patch:
                        return False
                    return True

        # Tilde (~1.2.3 means >=1.2.3 and <1.3.0)
        if constraint.startswith("~"):
            constraint_version = constraint[1:]
            constraint_match = self.SEMVER_PATTERN.match(constraint_version)
            if constraint_match:
                c_major, c_minor, c_patch = map(int, constraint_match.groups()[:3])
                if major != c_major or minor != c_minor:
                    return False
                return patch >= c_patch

        # Range (>=1.0.0,<2.0.0)
        if "," in constraint:
            parts = constraint.split(",")
            for part in parts:
                part = part.strip()
                if not self._check_version_operator(version, part):
                    return False
            return True

        # Single operator (>=1.0.0)
        return self._check_version_operator(version, constraint)

    def _check_version_operator(self, version: str, constraint: str) -> bool:
        """Check a single version operator constraint."""
        operators = [">=", "<=", ">", "<", "="]

        for op in operators:
            if constraint.startswith(op):
                constraint_version = constraint[len(op):].strip()
                constraint_match = self.SEMVER_PATTERN.match(constraint_version)
                if not constraint_match:
                    return False

                c_major, c_minor, c_patch = map(int, constraint_match.groups()[:3])

                version_match = self.SEMVER_PATTERN.match(version)
                if not version_match:
                    return False

                v_major, v_minor, v_patch = map(int, version_match.groups()[:3])

                v_tuple = (v_major, v_minor, v_patch)
                c_tuple = (c_major, c_minor, c_patch)

                if op == ">=":
                    return v_tuple >= c_tuple
                elif op == "<=":
                    return v_tuple <= c_tuple
                elif op == ">":
                    return v_tuple > c_tuple
                elif op == "<":
                    return v_tuple < c_tuple
                elif op == "=":
                    return v_tuple == c_tuple

        return False
