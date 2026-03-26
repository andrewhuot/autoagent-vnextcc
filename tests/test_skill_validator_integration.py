"""Integration tests for skill validator.

These tests demonstrate end-to-end validation workflows combining
multiple validation types and realistic skill scenarios.
"""

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
    SkillExample,
)
from core.skills.validator import SkillValidator, ValidationResult


class TestIntegration:
    """Integration tests for skill validation."""

    def test_production_build_skill_full_validation(self):
        """Test complete validation of a production-ready build-time skill."""
        skill = Skill(
            id="safety-hardening",
            name="Safety Hardening",
            kind=SkillKind.BUILD,
            version="2.1.0",
            description=(
                "Adds comprehensive safety checks and guardrails to prevent "
                "harmful outputs and ensure agent behavior stays within bounds"
            ),
            capabilities=["safety", "guardrails", "content_filtering"],
            mutations=[
                MutationOperator(
                    name="add_output_filter",
                    description="Adds output filtering for harmful content",
                    target_surface="guardrails",
                    operator_type="append",
                    template="Filter outputs for: violence, hate speech, PII",
                    risk_level="low",
                ),
                MutationOperator(
                    name="add_input_validation",
                    description="Adds input validation to detect prompt injection",
                    target_surface="instruction",
                    operator_type="insert",
                    template="Validate all user inputs for injection attempts",
                    risk_level="low",
                ),
            ],
            triggers=[
                TriggerCondition(
                    failure_family="safety_violation",
                ),
                TriggerCondition(
                    metric_name="harmful_output_rate",
                    threshold=0.01,
                    operator="gt",
                ),
            ],
            eval_criteria=[
                EvalCriterion(
                    metric="safety_score",
                    target=0.95,
                    operator="gte",
                    weight=2.0,
                ),
                EvalCriterion(
                    metric="harmful_output_rate",
                    target=0.001,
                    operator="lt",
                    weight=1.5,
                ),
            ],
            guardrails=[
                "max_output_length:1000",
                "blocked_topics:violence,hate,nsfw",
                "require_content_filter:true",
            ],
            examples=[
                SkillExample(
                    name="harmful_request",
                    description="Agent rejects harmful request",
                    before="User asks for harmful content, agent complies",
                    after="User asks for harmful content, agent politely declines",
                    improvement=1.0,
                    context="Safety testing scenario",
                )
            ],
            tags=["safety", "guardrails", "production"],
            domain="general",
            status="active",
        )

        validator = SkillValidator()
        result = validator.validate_full(skill, store=None)

        assert result.is_valid is True
        assert len(result.errors) == 0
        # May have warnings but should be valid
        result_dict = result.to_dict()
        assert result_dict["is_valid"] is True

    def test_production_runtime_skill_full_validation(self):
        """Test complete validation of a production-ready run-time skill."""
        skill = Skill(
            id="customer-refund",
            name="Customer Refund Processing",
            kind=SkillKind.RUNTIME,
            version="3.2.1",
            description=(
                "Enables the agent to process customer refund requests with "
                "proper authorization checks and transaction handling"
            ),
            capabilities=["refunds", "transactions", "customer_service"],
            tools=[
                ToolDefinition(
                    name="check_refund_eligibility",
                    description="Check if an order is eligible for refund",
                    parameters={
                        "type": "object",
                        "properties": {
                            "order_id": {"type": "string"},
                            "reason": {"type": "string"},
                        },
                        "required": ["order_id"],
                    },
                    returns={
                        "type": "object",
                        "properties": {
                            "eligible": {"type": "boolean"},
                            "reason": {"type": "string"},
                        },
                    },
                    sandbox_policy="read_only",
                ),
                ToolDefinition(
                    name="process_refund",
                    description="Process a refund for an eligible order",
                    parameters={
                        "type": "object",
                        "properties": {
                            "order_id": {"type": "string"},
                            "amount": {"type": "number"},
                            "authorization_code": {"type": "string"},
                        },
                        "required": ["order_id", "amount", "authorization_code"],
                    },
                    returns={
                        "type": "object",
                        "properties": {
                            "success": {"type": "boolean"},
                            "refund_id": {"type": "string"},
                        },
                    },
                    sandbox_policy="write_irreversible",
                ),
            ],
            instructions=(
                "When processing refunds:\n"
                "1. Always check eligibility first\n"
                "2. Verify the refund amount matches the order\n"
                "3. Require manager authorization for refunds > $500\n"
                "4. Confirm with the customer before processing\n"
                "5. Provide the refund ID to the customer"
            ),
            policies=[
                Policy(
                    name="require_manager_auth",
                    description="Require manager authorization for large refunds",
                    rule_type="require",
                    condition="amount > 500",
                    action="request_manager_authorization",
                    severity="high",
                ),
                Policy(
                    name="rate_limit",
                    description="Limit refund processing rate",
                    rule_type="rate_limit",
                    condition="always",
                    action="max_per_hour:10",
                    severity="medium",
                ),
                Policy(
                    name="verify_customer",
                    description="Verify customer identity before processing",
                    rule_type="require",
                    condition="always",
                    action="verify_customer_email",
                    severity="critical",
                ),
            ],
            test_cases=[
                TestCase(
                    name="eligible_refund",
                    description="Test processing an eligible refund",
                    input={
                        "order_id": "ORD-123",
                        "amount": 99.99,
                        "authorization_code": "AUTH-456",
                    },
                    expected_output={
                        "success": True,
                        "refund_id": "REF-789",
                    },
                ),
                TestCase(
                    name="check_eligibility",
                    description="Test checking refund eligibility",
                    input={"order_id": "ORD-123"},
                    expected_output={
                        "eligible": True,
                        "reason": "Within return window",
                    },
                ),
            ],
            dependencies=[],
            tags=["customer-support", "refunds", "transactions"],
            domain="customer-support",
            status="active",
        )

        validator = SkillValidator()
        result = validator.validate_full(skill, store=None)

        assert result.is_valid is True
        assert len(result.errors) == 0
        assert result.test_results is not None
        assert len(result.test_results) == 2
        assert all(result.test_results.values())

    def test_complex_skill_with_all_features(self):
        """Test validation of a complex skill using all available features."""
        skill = Skill(
            id="multi-capability-skill",
            name="Multi-Capability Skill",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="A comprehensive skill demonstrating all features",
            capabilities=["search", "analysis", "recommendations"],
            tools=[
                ToolDefinition(
                    name="search_tool",
                    description="Search for information",
                    parameters={"query": "string"},
                    sandbox_policy="read_only",
                )
            ],
            instructions="Use the search tool to find information",
            policies=[
                Policy(
                    name="test_policy",
                    description="Test policy",
                    rule_type="allow",
                    condition="always",
                    action="log",
                    severity="low",
                )
            ],
            test_cases=[
                TestCase(
                    name="test1",
                    description="Test case 1",
                    input={"query": "test"},
                    expected_output={"results": []},
                )
            ],
            dependencies=[
                SkillDependency(
                    skill_id="base-skill",
                    version_constraint=">=1.0.0",
                    optional=True,
                )
            ],
            tags=["test", "comprehensive"],
            domain="general",
        )

        validator = SkillValidator()

        # Run each validation type
        schema_result = validator.validate_schema(skill)
        assert schema_result.is_valid is True

        runtime_result = validator.validate_runtime_skill(skill)
        assert runtime_result.is_valid is True

        test_result = validator.run_tests(skill)
        assert test_result.is_valid is True

        # Full validation
        full_result = validator.validate_full(skill, store=None)
        assert full_result.is_valid is True

    def test_validation_result_merging(self):
        """Test that validation results merge correctly in full validation."""
        skill = Skill(
            id="test-skill",
            name="Test",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Short desc",  # Will generate warning
            tools=[
                ToolDefinition(
                    name="test",
                    description="Test",
                    parameters={},
                )
            ],
        )

        validator = SkillValidator()
        result = validator.validate_full(skill, store=None)

        # Should have warnings from multiple validators
        assert result.is_valid is True
        assert len(result.warnings) > 0
        # Check that warnings from different validators are merged
        warning_sources = set()
        for warning in result.warnings:
            if "very short" in warning:
                warning_sources.add("schema")
            if "no test cases" in warning:
                warning_sources.add("runtime")
            if "no policies" in warning:
                warning_sources.add("runtime")
        assert len(warning_sources) > 0

    def test_error_accumulation(self):
        """Test that errors accumulate from all validation stages."""
        skill = Skill(
            id="Invalid-ID",  # Invalid ID
            name="",  # Missing name
            kind=SkillKind.BUILD,
            version="bad",  # Invalid version
            description="x",  # Too short
            # Missing mutations, triggers, eval_criteria
        )

        validator = SkillValidator()
        result = validator.validate_full(skill, store=None)

        assert result.is_valid is False
        # Should have errors from both schema and build-time validation
        assert len(result.errors) >= 5
        error_types = set()
        for error in result.errors:
            if "ID" in error:
                error_types.add("id")
            if "name" in error:
                error_types.add("name")
            if "version" in error:
                error_types.add("version")
            if "mutation" in error:
                error_types.add("mutation")
        assert len(error_types) >= 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
