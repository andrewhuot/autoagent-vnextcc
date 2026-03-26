"""Tests for agent skill runtime manager."""

import pytest
import tempfile
from pathlib import Path

from agent.skill_runtime import (
    SkillRuntime,
    SkillReference,
    SkillConfig,
)
from core.skills.store import SkillStore
from core.skills.types import (
    Skill,
    SkillKind,
    ToolDefinition,
    Policy,
    TestCase,
    SkillDependency,
)
from core.skills.composer import ResolutionStrategy


@pytest.fixture
def temp_store():
    """Create a temporary skill store."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    store = SkillStore(db_path=db_path)
    yield store
    store.close()
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def sample_skills(temp_store):
    """Create sample runtime skills for testing."""
    # Skill 1: Order Lookup
    order_lookup = Skill(
        id="order_lookup",
        name="order_lookup",
        kind=SkillKind.RUNTIME,
        version="1.2.0",
        description="Look up customer orders",
        capabilities=["order_search", "order_details"],
        tools=[
            ToolDefinition(
                name="get_order",
                description="Retrieve order details by ID",
                parameters={
                    "type": "object",
                    "properties": {
                        "order_id": {"type": "string"}
                    },
                    "required": ["order_id"]
                },
                sandbox_policy="read_only",
            )
        ],
        instructions="Use get_order to retrieve order information. Always verify the order ID first.",
        policies=[
            Policy(
                name="verify_order_ownership",
                description="Verify customer owns the order before showing details",
                rule_type="require",
                condition="customer_id matches order.customer_id",
                action="deny_access",
                severity="high",
            )
        ],
        test_cases=[
            TestCase(
                name="test_valid_order",
                description="Test retrieving a valid order",
                input={"order_id": "ORD-123"},
                expected_output={"status": "success"},
            )
        ],
        domain="customer-support",
        tags=["orders", "lookup"],
        status="active",
    )
    temp_store.create(order_lookup)

    # Skill 2: Refund Processing
    refund = Skill(
        id="refund_processing",
        name="refund_processing",
        kind=SkillKind.RUNTIME,
        version="1.0.0",
        description="Process customer refunds",
        capabilities=["refund_initiation", "refund_status"],
        tools=[
            ToolDefinition(
                name="initiate_refund",
                description="Initiate a refund for an order",
                parameters={
                    "type": "object",
                    "properties": {
                        "order_id": {"type": "string"},
                        "amount": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": ["order_id", "amount"]
                },
                sandbox_policy="write_reversible",
            )
        ],
        instructions="Use initiate_refund to process refunds. Check refund policy limits first.",
        policies=[
            Policy(
                name="refund_amount_limit",
                description="Limit refund amounts based on config",
                rule_type="limit",
                condition="amount <= max_refund_amount",
                action="require_supervisor",
                severity="medium",
            )
        ],
        dependencies=[
            SkillDependency(
                skill_id="order_lookup",
                version_constraint=">=1.0.0",
                optional=False,
            )
        ],
        domain="customer-support",
        tags=["refunds", "payments"],
        status="active",
    )
    temp_store.create(refund)

    # Skill 3: Identity Verification
    identity = Skill(
        id="identity_verification",
        name="identity_verification",
        kind=SkillKind.RUNTIME,
        version="2.1.0",
        description="Verify customer identity",
        capabilities=["id_check", "security_questions"],
        tools=[
            ToolDefinition(
                name="verify_identity",
                description="Verify customer identity using multiple factors",
                parameters={
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "string"},
                        "verification_method": {"type": "string"},
                    },
                    "required": ["customer_id", "verification_method"]
                },
                sandbox_policy="read_only",
            )
        ],
        instructions="Always verify customer identity before sensitive operations.",
        domain="security",
        tags=["identity", "security"],
        status="active",
    )
    temp_store.create(identity)

    # Build-time skill (should not be loaded as runtime)
    build_skill = Skill(
        id="keyword_expansion",
        name="keyword_expansion",
        kind=SkillKind.BUILD,
        version="1.0.0",
        description="Expand keywords in prompts",
        domain="optimization",
        status="active",
    )
    temp_store.create(build_skill)

    return {
        "order_lookup": order_lookup,
        "refund": refund,
        "identity": identity,
        "build": build_skill,
    }


class TestSkillReference:
    """Test skill reference parsing."""

    def test_parse_with_version(self):
        ref = SkillReference.parse("order_lookup@1.2.0")
        assert ref.name == "order_lookup"
        assert ref.version == "1.2.0"

    def test_parse_without_version(self):
        ref = SkillReference.parse("order_lookup")
        assert ref.name == "order_lookup"
        assert ref.version == "*"

    def test_parse_with_caret(self):
        ref = SkillReference.parse("order_lookup@^1.2")
        assert ref.name == "order_lookup"
        assert ref.version == "^1.2"

    def test_parse_invalid_empty(self):
        with pytest.raises(ValueError, match="Invalid skill reference"):
            SkillReference.parse("@1.0")

    def test_parse_invalid_multiple_at(self):
        with pytest.raises(ValueError):
            SkillReference.parse("skill@@1.0")

    def test_str_representation(self):
        ref = SkillReference(name="test", version="1.0")
        assert str(ref) == "test@1.0"


class TestSkillConfig:
    """Test skill configuration."""

    def test_default_enabled(self):
        config = SkillConfig()
        assert config.enabled is True
        assert config.should_enable() is True

    def test_disabled(self):
        config = SkillConfig(enabled=False)
        assert config.should_enable() is False

    def test_ab_test_always_enable(self):
        config = SkillConfig(ab_test_percentage=1.0)
        assert config.should_enable() is True

    def test_ab_test_never_enable(self):
        config = SkillConfig(ab_test_percentage=0.0)
        assert config.should_enable() is False

    def test_parameters(self):
        config = SkillConfig(parameters={"max_refund": 500})
        assert config.parameters["max_refund"] == 500


class TestSkillRuntime:
    """Test skill runtime manager."""

    def test_init(self, temp_store):
        runtime = SkillRuntime(temp_store)
        assert runtime.store == temp_store
        assert runtime.validator is not None
        assert runtime.composer is not None

    def test_load_single_skill(self, temp_store, sample_skills):
        runtime = SkillRuntime(temp_store)
        skills = runtime.load_skills(["order_lookup@1.2.0"])

        assert len(skills) == 1
        assert skills[0].name == "order_lookup"
        assert skills[0].version == "1.2.0"

    def test_load_multiple_skills(self, temp_store, sample_skills):
        runtime = SkillRuntime(temp_store)
        skills = runtime.load_skills([
            "order_lookup@1.2.0",
            "refund_processing@1.0.0",
        ])

        assert len(skills) == 2
        assert {s.name for s in skills} == {"order_lookup", "refund_processing"}

    def test_load_skill_wildcard_version(self, temp_store, sample_skills):
        runtime = SkillRuntime(temp_store)
        skills = runtime.load_skills(["order_lookup"])

        assert len(skills) == 1
        assert skills[0].name == "order_lookup"

    def test_load_skill_not_found(self, temp_store):
        runtime = SkillRuntime(temp_store)
        with pytest.raises(ValueError, match="Skill not found"):
            runtime.load_skills(["nonexistent@1.0"])

    def test_load_build_skill_raises(self, temp_store, sample_skills):
        runtime = SkillRuntime(temp_store)
        with pytest.raises(ValueError, match="not a runtime skill"):
            runtime.load_skills(["keyword_expansion@1.0.0"])

    def test_load_with_ab_config_disabled(self, temp_store, sample_skills):
        runtime = SkillRuntime(temp_store)
        configs = {
            "order_lookup": SkillConfig(enabled=False),
        }
        skills = runtime.load_skills(["order_lookup@1.2.0"], skill_configs=configs)

        assert len(skills) == 0

    def test_load_with_ab_config_percentage(self, temp_store, sample_skills):
        runtime = SkillRuntime(temp_store)
        configs = {
            "order_lookup": SkillConfig(ab_test_percentage=1.0),
        }
        skills = runtime.load_skills(["order_lookup@1.2.0"], skill_configs=configs)

        assert len(skills) == 1

    def test_validate_skills_success(self, temp_store, sample_skills):
        runtime = SkillRuntime(temp_store)
        skills = runtime.load_skills(["order_lookup@1.2.0"])

        agent_config = {
            "prompts": {"root": "Test"},
            "tools": {},
        }

        result = runtime.validate_skills(skills, agent_config)
        assert result.is_valid is True

    def test_validate_skills_with_dependencies(self, temp_store, sample_skills):
        runtime = SkillRuntime(temp_store)
        skills = runtime.load_skills([
            "order_lookup@1.2.0",
            "refund_processing@1.0.0",
        ])

        agent_config = {
            "prompts": {"root": "Test"},
            "tools": {},
        }

        result = runtime.validate_skills(skills, agent_config)
        # Should pass since order_lookup dependency is satisfied
        assert result.is_valid is True

    def test_validate_skills_missing_sections(self, temp_store, sample_skills):
        runtime = SkillRuntime(temp_store)
        skills = runtime.load_skills(["order_lookup@1.2.0"])

        agent_config = {}  # Missing prompts and tools

        result = runtime.validate_skills(skills, agent_config)
        assert len(result.warnings) >= 2  # Should warn about missing sections

    def test_extract_tools(self, temp_store, sample_skills):
        runtime = SkillRuntime(temp_store)
        skills = runtime.load_skills([
            "order_lookup@1.2.0",
            "refund_processing@1.0.0",
        ])

        tools = runtime.extract_tools(skills)

        assert len(tools) == 2
        tool_names = {t["name"] for t in tools}
        assert tool_names == {"get_order", "initiate_refund"}

    def test_extract_instructions(self, temp_store, sample_skills):
        runtime = SkillRuntime(temp_store)
        skills = runtime.load_skills([
            "order_lookup@1.2.0",
            "refund_processing@1.0.0",
        ])

        instructions = runtime.extract_instructions(skills)

        assert "order_lookup" in instructions
        assert "refund_processing" in instructions
        assert "get_order" in instructions
        assert "initiate_refund" in instructions

    def test_extract_policies(self, temp_store, sample_skills):
        runtime = SkillRuntime(temp_store)
        skills = runtime.load_skills([
            "order_lookup@1.2.0",
            "refund_processing@1.0.0",
        ])

        policies = runtime.extract_policies(skills)

        assert len(policies) == 2
        policy_names = {p["name"] for p in policies}
        assert policy_names == {"verify_order_ownership", "refund_amount_limit"}

    def test_apply_to_config_basic(self, temp_store, sample_skills):
        runtime = SkillRuntime(temp_store)
        skills = runtime.load_skills(["order_lookup@1.2.0"])

        base_config = {
            "prompts": {"root": "You are a helpful agent."},
            "tools": {},
            "model": "gemini-2.0-flash",
        }

        enriched = runtime.apply_to_config(skills, base_config)

        # Should have tools
        assert "get_order" in enriched["tools"]

        # Should have enhanced prompt
        assert "Skills" in enriched["prompts"]["root"]
        assert "order_lookup" in enriched["prompts"]["root"]

        # Should have policies
        assert "policies" in enriched
        assert len(enriched["policies"]) == 1

        # Should have metadata
        assert "metadata" in enriched
        assert "applied_skills" in enriched["metadata"]
        assert len(enriched["metadata"]["applied_skills"]) == 1

    def test_apply_to_config_multiple_skills(self, temp_store, sample_skills):
        runtime = SkillRuntime(temp_store)
        skills = runtime.load_skills([
            "order_lookup@1.2.0",
            "refund_processing@1.0.0",
        ])

        base_config = {
            "prompts": {"root": "You are a helpful agent."},
            "tools": {},
        }

        enriched = runtime.apply_to_config(skills, base_config)

        # Should have both tools
        assert "get_order" in enriched["tools"]
        assert "initiate_refund" in enriched["tools"]

        # Should have both policies
        assert len(enriched["policies"]) == 2

        # Should have metadata for both skills
        assert len(enriched["metadata"]["applied_skills"]) == 2

    def test_apply_to_config_preserves_base(self, temp_store, sample_skills):
        runtime = SkillRuntime(temp_store)
        skills = runtime.load_skills(["order_lookup@1.2.0"])

        base_config = {
            "prompts": {"root": "Base prompt"},
            "tools": {"existing_tool": {"name": "existing"}},
            "model": "gemini-2.0-flash",
            "thresholds": {"confidence": 0.8},
        }

        enriched = runtime.apply_to_config(skills, base_config)

        # Should preserve base config
        assert enriched["model"] == "gemini-2.0-flash"
        assert enriched["thresholds"]["confidence"] == 0.8
        assert "existing_tool" in enriched["tools"]

        # Should add new content
        assert "get_order" in enriched["tools"]

    def test_apply_to_config_with_ab_config(self, temp_store, sample_skills):
        runtime = SkillRuntime(temp_store)
        skills = runtime.load_skills([
            "order_lookup@1.2.0",
            "refund_processing@1.0.0",
        ])

        base_config = {
            "prompts": {"root": "Test"},
            "tools": {},
        }

        # Disable refund skill
        skill_configs = {
            "refund_processing": SkillConfig(enabled=False),
        }

        enriched = runtime.apply_to_config(skills, base_config, skill_configs)

        # Should only have order_lookup tool
        assert "get_order" in enriched["tools"]
        assert "initiate_refund" not in enriched["tools"]

        # Should only have one skill in metadata
        assert len(enriched["metadata"]["applied_skills"]) == 1
        assert enriched["metadata"]["applied_skills"][0]["name"] == "order_lookup"

    def test_apply_to_config_empty_skills(self, temp_store):
        runtime = SkillRuntime(temp_store)
        base_config = {"prompts": {"root": "Test"}}

        enriched = runtime.apply_to_config([], base_config)

        # Should return copy of base config
        assert enriched == base_config
        assert enriched is not base_config  # Different object

    def test_integration_full_workflow(self, temp_store, sample_skills):
        """Test complete workflow: load, validate, apply."""
        runtime = SkillRuntime(temp_store)

        # Define agent config with skill references
        skill_refs = [
            "order_lookup@1.2.0",
            "refund_processing@1.0.0",
            "identity_verification@2.1.0",
        ]

        skill_configs = {
            "refund_processing": SkillConfig(
                parameters={"max_refund_amount": 500}
            ),
        }

        # Load skills
        skills = runtime.load_skills(skill_refs, skill_configs)
        assert len(skills) == 3

        # Validate
        agent_config = {
            "prompts": {"root": "You are a customer support agent."},
            "tools": {},
            "model": "gemini-2.0-flash",
        }

        result = runtime.validate_skills(skills, agent_config)
        assert result.is_valid is True

        # Apply to config
        enriched = runtime.apply_to_config(skills, agent_config, skill_configs)

        # Verify enrichment
        assert len(enriched["tools"]) == 3
        assert "get_order" in enriched["tools"]
        assert "initiate_refund" in enriched["tools"]
        assert "verify_identity" in enriched["tools"]

        assert len(enriched["policies"]) == 2

        assert "Skills" in enriched["prompts"]["root"]

        assert len(enriched["metadata"]["applied_skills"]) == 3

    def test_conflict_resolution_prefer_first(self, temp_store):
        """Test conflict resolution with PREFER_FIRST strategy."""
        # Create two skills with same tool name
        skill1 = Skill(
            id="skill1",
            name="skill1",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Skill 1",
            tools=[
                ToolDefinition(
                    name="shared_tool",
                    description="Tool from skill 1",
                    parameters={},
                )
            ],
            status="active",
        )
        skill2 = Skill(
            id="skill2",
            name="skill2",
            kind=SkillKind.RUNTIME,
            version="1.0.0",
            description="Skill 2",
            tools=[
                ToolDefinition(
                    name="shared_tool",
                    description="Tool from skill 2",
                    parameters={},
                )
            ],
            status="active",
        )

        temp_store.create(skill1)
        temp_store.create(skill2)

        runtime = SkillRuntime(
            temp_store,
            conflict_strategy=ResolutionStrategy.PREFER_FIRST,
        )

        skills = runtime.load_skills(["skill1@1.0.0", "skill2@1.0.0"])
        tools = runtime.extract_tools(skills)

        # Should only have one tool (first one)
        assert len(tools) == 1
        assert tools[0]["description"] == "Tool from skill 1"


class TestSkillRuntimeYAMLIntegration:
    """Test integration with YAML agent configs."""

    def test_yaml_config_format(self, temp_store, sample_skills):
        """Test that enriched config matches expected YAML format."""
        runtime = SkillRuntime(temp_store)

        # Simulate YAML-loaded config
        agent_config = {
            "model": "gemini-2.0-flash",
            "routing": {
                "rules": [
                    {
                        "specialist": "support",
                        "keywords": ["help", "issue"],
                    }
                ]
            },
            "prompts": {
                "root": "You are AutoAgent, a helpful customer service assistant.",
                "support": "You are a customer support specialist.",
            },
            "tools": {
                "catalog": {"enabled": True, "timeout_ms": 5000},
            },
            "thresholds": {
                "confidence_threshold": 0.6,
                "max_turns": 20,
            },
        }

        skills = runtime.load_skills(["order_lookup@1.2.0"])
        enriched = runtime.apply_to_config(skills, agent_config)

        # Verify structure is preserved
        assert "routing" in enriched
        assert "thresholds" in enriched
        assert enriched["model"] == "gemini-2.0-flash"

        # Verify skills are added
        assert "get_order" in enriched["tools"]
        assert "Skills" in enriched["prompts"]["root"]
        assert "policies" in enriched
