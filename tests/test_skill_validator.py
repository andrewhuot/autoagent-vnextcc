"""Tests for skill validator."""

import pytest
from core.skills.types import (
    Skill,
    SkillKind,
    MutationOperator,
    TriggerCondition,
    EvalCriterion,
    ToolDefinition,
    Policy,
    TestCase,
    SkillDependency,
)
from core.skills.validator import SkillValidator, ValidationResult


class TestValidationResult:
    """Test ValidationResult class."""

    def test_validation_result_init(self):
        """Test ValidationResult initialization."""
        result = ValidationResult(is_valid=True)
        assert result.is_valid is True
        assert result.errors == []
        assert result.warnings == []
        assert result.test_results is None

    def test_add_error(self):
        """Test adding errors."""
        result = ValidationResult(is_valid=True)
        result.add_error("Test error")
        assert result.is_valid is False
        assert result.errors == ["Test error"]

    def test_add_warning(self):
        """Test adding warnings."""
        result = ValidationResult(is_valid=True)
        result.add_warning("Test warning")
        assert result.is_valid is True
        assert result.warnings == ["Test warning"]

    def test_merge(self):
        """Test merging validation results."""
        result1 = ValidationResult(is_valid=True)
        result1.add_warning("Warning 1")

        result2 = ValidationResult(is_valid=False)
        result2.add_error("Error 1")
        result2.test_results = {"test1": True}

        result1.merge(result2)
        assert result1.is_valid is False
        assert result1.errors == ["Error 1"]
        assert result1.warnings == ["Warning 1"]
        assert result1.test_results == {"test1": True}

    def test_to_dict(self):
        """Test conversion to dictionary."""
        result = ValidationResult(is_valid=True)
        result.add_error("Error")
        result.add_warning("Warning")
        result.test_results = {"test1": True}

        data = result.to_dict()
        assert data == {
            "is_valid": False,
            "errors": ["Error"],
            "warnings": ["Warning"],
            "test_results": {"test1": True},
        }


class TestSkillValidator:
    """Test SkillValidator class."""

    def test_validator_init(self):
        """Test validator initialization."""
        validator = SkillValidator()
        assert validator is not None

    def test_validate_schema_valid_build_skill(self):
        """Test schema validation for valid build-time skill."""
        skill = Skill(
            id="test-skill",
            name="Test Skill",
            kind=SkillKind.BUILD,
            version="1.0.0",
            description="A test skill for validation",
            mutations=[
                MutationOperator(
                    name="test_mutation",
                    description="Test mutation",
                    target_surface="instruction",
                    operator_type="append",
                )
            ],
            triggers=[
                TriggerCondition(
                    failure_family="test_failure",
                )
            ],
            eval_criteria=[
                EvalCriterion(
                    metric="success_rate",
                    target=0.9,
                )
            ],
        )

        validator = SkillValidator()
        result = validator.validate_schema(skill)
        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_validate_schema_missing_required_fields(self):
        """Test schema validation catches missing required fields."""
        skill = Skill(
            id="",
            name="",
            kind=SkillKind.BUILD,
            version="",
            description="",
        )

        validator = SkillValidator()
        result = validator.validate_schema(skill)
        assert result.is_valid is False
        assert len(result.errors) > 0
        assert any("ID is required" in e for e in result.errors)
        assert any("name is required" in e for e in result.errors)
        assert any("version is required" in e for e in result.errors)

    def test_validate_schema_invalid_id(self):
        """Test schema validation catches invalid skill ID."""
        skill = Skill(
            id="Invalid Skill ID!",
            name="Test",
            kind=SkillKind.BUILD,
            version="1.0.0",
            description="Test description",
        )

        validator = SkillValidator()
        result = validator.validate_schema(skill)
        assert result.is_valid is False
        assert any("lowercase letters" in e for e in result.errors)

    def test_validate_schema_invalid_version(self):
        """Test schema validation catches invalid version."""
        skill = Skill(
            id="test-skill",
            name="Test",
            kind=SkillKind.BUILD,
            version="invalid",
            description="Test description",
        )

        validator = SkillValidator()
        result = validator.validate_schema(skill)
        assert result.is_valid is False
        assert any("not valid semver" in e for e in result.errors)

    def test_validate_schema_short_description_warning(self):
        """Test schema validation warns on short description."""
        skill = Skill(
            id="test-skill",
            name="Test",
            kind=SkillKind.BUILD,
            version="1.0.0",
            description="Short",
        )

        validator = SkillValidator()
        result = validator.validate_schema(skill)
        assert any("very short" in w for w in result.warnings)

    def test_validate_schema_invalid_mutation(self):
        """Test schema validation catches invalid mutations."""
        skill = Skill(
            id="test-skill",
            name="Test",
            kind=SkillKind.BUILD,
            version="1.0.0",
            description="Test description",
            mutations=[
                MutationOperator(
                    name="",
                    description="",
                    target_surface="invalid_surface",
                    operator_type="invalid_type",
                    risk_level="invalid_level",
                )
            ],
        )

        validator = SkillValidator()
        result = validator.validate_schema(skill)
        assert result.is_valid is False
        assert any("name is required" in e for e in result.errors)
        assert any("invalid target_surface" in e for e in result.errors)
        assert any("invalid operator_type" in e for e in result.errors)
        assert any("invalid risk_level" in e for e in result.errors)

    def test_validate_schema_invalid_trigger(self):
        """Test schema validation catches invalid triggers."""
        skill = Skill(
            id="test-skill",
            name="Test",
            kind=SkillKind.BUILD,
            version="1.0.0",
            description="Test description",
            triggers=[
                TriggerCondition(
                    operator="invalid_op",
                )
            ],
        )

        validator = SkillValidator()
        result = validator.validate_schema(skill)
        assert result.is_valid is False
        assert any("must have at least one of" in e for e in result.errors)
        assert any("invalid operator" in e for e in result.errors)

    def test_validate_schema_metric_trigger_needs_threshold(self):
        """Test that metric-based triggers require threshold."""
        skill = Skill(
            id="test-skill",
            name="Test",
            kind=SkillKind.BUILD,
            version="1.0.0",
            description="Test description",
            triggers=[
                TriggerCondition(
                    metric_name="success_rate",
                    threshold=None,
                )
            ],
        )

        validator = SkillValidator()
        result = validator.validate_schema(skill)
        assert result.is_valid is False
        assert any("must have threshold" in e for e in result.errors)

    def test_validate_schema_invalid_eval_criterion(self):
        """Test schema validation catches invalid eval criteria."""
        skill = Skill(
            id="test-skill",
            name="Test",
            kind=SkillKind.BUILD,
            version="1.0.0",
            description="Test description",
            eval_criteria=[
                EvalCriterion(
                    metric="",
                    target=0.9,
                    operator="invalid_op",
                    weight=-1.0,
                )
            ],
        )

        validator = SkillValidator()
        result = validator.validate_schema(skill)
        assert result.is_valid is False
        assert any("metric is required" in e for e in result.errors)
        assert any("invalid operator" in e for e in result.errors)
        assert any("weight must be positive" in e for e in result.errors)

    def test_validate_schema_invalid_tool(self):
        """Test schema validation catches invalid tools."""
        skill = Skill(
            id="test-skill",
            name="Test",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Test description",
            tools=[
                ToolDefinition(
                    name="",
                    description="",
                    parameters="not_a_dict",  # type: ignore
                    sandbox_policy="invalid_policy",
                )
            ],
        )

        validator = SkillValidator()
        result = validator.validate_schema(skill)
        assert result.is_valid is False
        assert any("name is required" in e for e in result.errors)
        assert any("parameters must be a dict" in e for e in result.errors)
        assert any("invalid sandbox_policy" in e for e in result.errors)

    def test_validate_schema_invalid_policy(self):
        """Test schema validation catches invalid policies."""
        skill = Skill(
            id="test-skill",
            name="Test",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Test description",
            policies=[
                Policy(
                    name="",
                    description="",
                    rule_type="invalid_type",
                    condition="",
                    action="",
                    severity="invalid_severity",
                )
            ],
        )

        validator = SkillValidator()
        result = validator.validate_schema(skill)
        assert result.is_valid is False
        assert any("name is required" in e for e in result.errors)
        assert any("invalid rule_type" in e for e in result.errors)
        assert any("condition is required" in e for e in result.errors)
        assert any("invalid severity" in e for e in result.errors)

    def test_validate_schema_invalid_test_case(self):
        """Test schema validation catches invalid test cases."""
        skill = Skill(
            id="test-skill",
            name="Test",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Test description",
            test_cases=[
                TestCase(
                    name="",
                    description="",
                    input="not_a_dict",  # type: ignore
                )
            ],
        )

        validator = SkillValidator()
        result = validator.validate_schema(skill)
        assert result.is_valid is False
        assert any("name is required" in e for e in result.errors)
        assert any("input must be a dict" in e for e in result.errors)

    def test_validate_build_time_skill(self):
        """Test build-time skill validation."""
        skill = Skill(
            id="test-skill",
            name="Test",
            kind=SkillKind.BUILD,
            version="1.0.0",
            description="Test description",
        )

        validator = SkillValidator()
        result = validator.validate_build_time_skill(skill)
        assert result.is_valid is False
        assert any("at least one mutation" in e for e in result.errors)
        assert any("at least one trigger" in e for e in result.errors)
        assert any("at least one eval criterion" in e for e in result.errors)

    def test_validate_build_time_skill_warnings(self):
        """Test build-time skill validation warnings."""
        skill = Skill(
            id="test-skill",
            name="Test",
            kind=SkillKind.BUILD,
            version="1.0.0",
            description="Test description",
            mutations=[
                MutationOperator(
                    name="high_risk",
                    description="Test",
                    target_surface="instruction",
                    operator_type="append",
                    risk_level="high",
                )
            ],
            triggers=[TriggerCondition(failure_family="test")],
            eval_criteria=[EvalCriterion(metric="test", target=0.9)],
        )

        validator = SkillValidator()
        result = validator.validate_build_time_skill(skill)
        assert any("no examples" in w for w in result.warnings)
        assert any("no guardrails" in w for w in result.warnings)
        assert any("high-risk mutation" in w for w in result.warnings)

    def test_validate_runtime_skill(self):
        """Test run-time skill validation."""
        skill = Skill(
            id="test-skill",
            name="Test",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Test description",
        )

        validator = SkillValidator()
        result = validator.validate_runtime_skill(skill)
        assert result.is_valid is False
        assert any("at least one tool or instructions" in e for e in result.errors)

    def test_validate_runtime_skill_with_tools(self):
        """Test run-time skill validation with tools."""
        skill = Skill(
            id="test-skill",
            name="Test",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Test description",
            tools=[
                ToolDefinition(
                    name="test_tool",
                    description="Test",
                    parameters={},
                )
            ],
        )

        validator = SkillValidator()
        result = validator.validate_runtime_skill(skill)
        assert result.is_valid is True

    def test_validate_runtime_skill_with_instructions(self):
        """Test run-time skill validation with instructions."""
        skill = Skill(
            id="test-skill",
            name="Test",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Test description",
            instructions="Do something useful",
        )

        validator = SkillValidator()
        result = validator.validate_runtime_skill(skill)
        assert result.is_valid is True

    def test_validate_runtime_skill_warnings(self):
        """Test run-time skill validation warnings."""
        skill = Skill(
            id="test-skill",
            name="Test",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Test description",
            tools=[
                ToolDefinition(
                    name="dangerous_tool",
                    description="Test",
                    parameters={},
                    sandbox_policy="write_irreversible",
                )
            ],
        )

        validator = SkillValidator()
        result = validator.validate_runtime_skill(skill)
        assert any("no test cases" in w for w in result.warnings)
        assert any("no policies" in w for w in result.warnings)
        assert any("write_irreversible" in w for w in result.warnings)

    def test_run_tests(self):
        """Test test execution."""
        skill = Skill(
            id="test-skill",
            name="Test",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Test description",
            test_cases=[
                TestCase(
                    name="test1",
                    description="Test 1",
                    input={"key": "value"},
                    expected_output={"result": "success"},
                ),
                TestCase(
                    name="test2",
                    description="Test 2",
                    input={"key": "value"},
                ),
            ],
        )

        validator = SkillValidator()
        result = validator.run_tests(skill)
        assert result.is_valid is True
        assert result.test_results is not None
        assert result.test_results["test1"] is True
        assert result.test_results["test2"] is True
        assert any("no expected output" in w for w in result.warnings)

    def test_run_tests_no_input(self):
        """Test test execution catches missing input."""
        skill = Skill(
            id="test-skill",
            name="Test",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Test description",
            test_cases=[
                TestCase(
                    name="test1",
                    description="Test 1",
                    input=None,  # type: ignore
                )
            ],
        )

        validator = SkillValidator()
        result = validator.run_tests(skill)
        assert result.is_valid is False
        assert any("no input defined" in e for e in result.errors)
        assert result.test_results["test1"] is False

    def test_validate_full(self):
        """Test full validation."""
        skill = Skill(
            id="test-skill",
            name="Test Skill",
            kind=SkillKind.BUILD,
            version="1.0.0",
            description="A comprehensive test skill",
            mutations=[
                MutationOperator(
                    name="test_mutation",
                    description="Test mutation",
                    target_surface="instruction",
                    operator_type="append",
                )
            ],
            triggers=[TriggerCondition(failure_family="test")],
            eval_criteria=[EvalCriterion(metric="success_rate", target=0.9)],
        )

        validator = SkillValidator()
        result = validator.validate_full(skill, store=None)
        assert result.is_valid is True

    def test_semver_validation(self):
        """Test semver validation."""
        validator = SkillValidator()

        # Valid versions
        assert validator._is_valid_semver("1.0.0")
        assert validator._is_valid_semver("0.1.0")
        assert validator._is_valid_semver("1.2.3")
        assert validator._is_valid_semver("1.0.0-alpha")
        assert validator._is_valid_semver("1.0.0-alpha.1")
        assert validator._is_valid_semver("1.0.0+build.123")

        # Invalid versions
        assert not validator._is_valid_semver("1.0")
        assert not validator._is_valid_semver("1")
        assert not validator._is_valid_semver("v1.0.0")
        assert not validator._is_valid_semver("invalid")

    def test_version_compatibility_wildcard(self):
        """Test version compatibility with wildcards."""
        validator = SkillValidator()

        assert validator._is_version_compatible("1.0.0", "*")
        assert validator._is_version_compatible("2.5.3", "*")
        assert validator._is_version_compatible("1.2.3", "1.*")
        assert validator._is_version_compatible("1.5.0", "1.*")
        assert not validator._is_version_compatible("2.0.0", "1.*")
        assert validator._is_version_compatible("1.2.5", "1.2.*")
        assert not validator._is_version_compatible("1.3.0", "1.2.*")

    def test_version_compatibility_exact(self):
        """Test exact version matching."""
        validator = SkillValidator()

        assert validator._is_version_compatible("1.0.0", "1.0.0")
        assert not validator._is_version_compatible("1.0.1", "1.0.0")

    def test_version_compatibility_caret(self):
        """Test caret version constraints."""
        validator = SkillValidator()

        # ^1.2.3 allows >=1.2.3 and <2.0.0
        assert validator._is_version_compatible("1.2.3", "^1.2.3")
        assert validator._is_version_compatible("1.2.4", "^1.2.3")
        assert validator._is_version_compatible("1.3.0", "^1.2.3")
        assert not validator._is_version_compatible("1.2.2", "^1.2.3")
        assert not validator._is_version_compatible("2.0.0", "^1.2.3")

        # ^0.2.3 allows >=0.2.3 and <0.3.0
        assert validator._is_version_compatible("0.2.3", "^0.2.3")
        assert validator._is_version_compatible("0.2.4", "^0.2.3")
        assert not validator._is_version_compatible("0.3.0", "^0.2.3")

    def test_version_compatibility_tilde(self):
        """Test tilde version constraints."""
        validator = SkillValidator()

        # ~1.2.3 allows >=1.2.3 and <1.3.0
        assert validator._is_version_compatible("1.2.3", "~1.2.3")
        assert validator._is_version_compatible("1.2.4", "~1.2.3")
        assert not validator._is_version_compatible("1.2.2", "~1.2.3")
        assert not validator._is_version_compatible("1.3.0", "~1.2.3")

    def test_version_compatibility_operators(self):
        """Test version comparison operators."""
        validator = SkillValidator()

        assert validator._is_version_compatible("1.2.3", ">=1.0.0")
        assert validator._is_version_compatible("1.0.0", ">=1.0.0")
        assert not validator._is_version_compatible("0.9.9", ">=1.0.0")

        assert validator._is_version_compatible("0.9.9", "<1.0.0")
        assert not validator._is_version_compatible("1.0.0", "<1.0.0")

        assert validator._is_version_compatible("1.2.3", ">1.0.0")
        assert not validator._is_version_compatible("1.0.0", ">1.0.0")

        assert validator._is_version_compatible("0.9.9", "<=1.0.0")
        assert validator._is_version_compatible("1.0.0", "<=1.0.0")

    def test_version_compatibility_range(self):
        """Test version range constraints."""
        validator = SkillValidator()

        assert validator._is_version_compatible("1.5.0", ">=1.0.0,<2.0.0")
        assert validator._is_version_compatible("1.0.0", ">=1.0.0,<2.0.0")
        assert not validator._is_version_compatible("0.9.9", ">=1.0.0,<2.0.0")
        assert not validator._is_version_compatible("2.0.0", ">=1.0.0,<2.0.0")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
