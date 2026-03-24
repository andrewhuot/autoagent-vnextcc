"""Comprehensive tests for the modular registry system.

Covers RegistryStore, SkillRegistry, PolicyRegistry, ToolContractRegistry,
HandoffSchemaRegistry, importer, and MutationSurface additions.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from registry.store import RegistryStore
from registry.skills import SkillRegistry
from registry.policies import PolicyRegistry
from registry.tool_contracts import ToolContractRegistry
from registry.handoff_schemas import HandoffSchemaRegistry
from registry.importer import import_from_file
from optimizer.mutations import MutationSurface, create_default_registry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path: object) -> RegistryStore:
    """Create a fresh in-memory RegistryStore for each test."""
    db_path = os.path.join(str(tmp_path), "test_registry.db")
    return RegistryStore(db_path=db_path)


@pytest.fixture
def skill_reg(store: RegistryStore) -> SkillRegistry:
    return SkillRegistry(store)


@pytest.fixture
def policy_reg(store: RegistryStore) -> PolicyRegistry:
    return PolicyRegistry(store)


@pytest.fixture
def tc_reg(store: RegistryStore) -> ToolContractRegistry:
    return ToolContractRegistry(store)


@pytest.fixture
def hs_reg(store: RegistryStore) -> HandoffSchemaRegistry:
    return HandoffSchemaRegistry(store)


# ===================================================================
# RegistryStore tests
# ===================================================================

class TestRegistryStore:
    """Tests for the SQLite-backed RegistryStore."""

    def test_init_creates_tables(self, store: RegistryStore) -> None:
        """Store initialisation creates all four tables."""
        cursor = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row["name"] for row in cursor.fetchall()}
        assert "skills" in tables
        assert "policies" in tables
        assert "tool_contracts" in tables
        assert "handoff_schemas" in tables

    def test_insert_and_get(self, store: RegistryStore) -> None:
        """Basic insert then get round-trip."""
        store._insert("skills", "greet", 1, {"instructions": "say hi"}, "2024-01-01T00:00:00Z")
        item = store._get("skills", "greet", 1)
        assert item is not None
        assert item["name"] == "greet"
        assert item["version"] == 1
        assert item["data"]["instructions"] == "say hi"

    def test_get_latest_version(self, store: RegistryStore) -> None:
        """_get_latest_version returns 0 when empty, correct version otherwise."""
        assert store._get_latest_version("skills", "nope") == 0
        store._insert("skills", "x", 1, {"v": 1}, "t1")
        store._insert("skills", "x", 2, {"v": 2}, "t2")
        assert store._get_latest_version("skills", "x") == 2

    def test_get_none_version_returns_latest(self, store: RegistryStore) -> None:
        """Passing version=None returns the latest version."""
        store._insert("skills", "x", 1, {"v": 1}, "t1")
        store._insert("skills", "x", 2, {"v": 2}, "t2")
        item = store._get("skills", "x")
        assert item is not None
        assert item["version"] == 2

    def test_get_nonexistent(self, store: RegistryStore) -> None:
        """Getting a nonexistent item returns None."""
        assert store._get("skills", "nope") is None
        assert store._get("skills", "nope", 1) is None

    def test_list(self, store: RegistryStore) -> None:
        """_list returns all non-deprecated items."""
        store._insert("skills", "a", 1, {}, "t")
        store._insert("skills", "b", 1, {}, "t")
        items = store._list("skills")
        assert len(items) == 2

    def test_list_excludes_deprecated(self, store: RegistryStore) -> None:
        """_list without include_deprecated excludes deprecated items."""
        store._insert("skills", "a", 1, {}, "t")
        store._deprecate("skills", "a", 1)
        assert len(store._list("skills", include_deprecated=False)) == 0
        assert len(store._list("skills", include_deprecated=True)) == 1

    def test_deprecate(self, store: RegistryStore) -> None:
        """Deprecating an item marks it as deprecated."""
        store._insert("skills", "a", 1, {}, "t")
        assert store._deprecate("skills", "a", 1) is True
        item = store._get("skills", "a", 1)
        assert item is not None
        assert item["deprecated"] is True

    def test_deprecate_nonexistent(self, store: RegistryStore) -> None:
        """Deprecating a nonexistent item returns False."""
        assert store._deprecate("skills", "nope", 1) is False

    def test_search(self, store: RegistryStore) -> None:
        """_search finds items by name or data substring."""
        store._insert("skills", "order_handler", 1, {"instructions": "handle orders"}, "t")
        store._insert("skills", "greet", 1, {"instructions": "say hello"}, "t")
        results = store._search("skills", "order")
        assert len(results) == 1
        assert results[0]["name"] == "order_handler"

    def test_search_in_data(self, store: RegistryStore) -> None:
        """_search matches within JSON data."""
        store._insert("skills", "x", 1, {"instructions": "handle refunds"}, "t")
        results = store._search("skills", "refund")
        assert len(results) == 1

    def test_diff(self, store: RegistryStore) -> None:
        """_diff returns changes between two versions."""
        store._insert("skills", "x", 1, {"a": 1, "b": 2}, "t1")
        store._insert("skills", "x", 2, {"a": 1, "b": 3, "c": 4}, "t2")
        result = store._diff("skills", "x", 1, 2)
        assert result["v1"]["a"] == 1
        assert result["v2"]["b"] == 3
        changes = {c["field"]: c for c in result["changes"]}
        assert "b" in changes
        assert "c" in changes
        assert "a" not in changes


# ===================================================================
# SkillRegistry tests
# ===================================================================

class TestSkillRegistry:
    """Tests for SkillRegistry."""

    def test_register(self, skill_reg: SkillRegistry) -> None:
        name, version = skill_reg.register("greet", instructions="say hi")
        assert name == "greet"
        assert version == 1

    def test_register_auto_increments(self, skill_reg: SkillRegistry) -> None:
        skill_reg.register("greet", instructions="v1")
        _, v2 = skill_reg.register("greet", instructions="v2")
        assert v2 == 2

    def test_get(self, skill_reg: SkillRegistry) -> None:
        skill_reg.register("greet", instructions="hello")
        item = skill_reg.get("greet")
        assert item is not None
        assert item["data"]["instructions"] == "hello"

    def test_get_specific_version(self, skill_reg: SkillRegistry) -> None:
        skill_reg.register("greet", instructions="v1")
        skill_reg.register("greet", instructions="v2")
        item = skill_reg.get("greet", version=1)
        assert item is not None
        assert item["data"]["instructions"] == "v1"

    def test_list(self, skill_reg: SkillRegistry) -> None:
        skill_reg.register("a", instructions="x")
        skill_reg.register("b", instructions="y")
        items = skill_reg.list()
        assert len(items) == 2

    def test_update_creates_new_version(self, skill_reg: SkillRegistry) -> None:
        skill_reg.register("greet", instructions="old")
        name, version = skill_reg.update("greet", instructions="new")
        assert version == 2
        item = skill_reg.get("greet")
        assert item is not None
        assert item["data"]["instructions"] == "new"

    def test_update_nonexistent_raises(self, skill_reg: SkillRegistry) -> None:
        with pytest.raises(ValueError, match="not found"):
            skill_reg.update("nope", instructions="x")

    def test_deprecate(self, skill_reg: SkillRegistry) -> None:
        skill_reg.register("greet", instructions="hi")
        assert skill_reg.deprecate("greet", 1) is True
        items = skill_reg.list()
        assert len(items) == 0

    def test_diff(self, skill_reg: SkillRegistry) -> None:
        skill_reg.register("greet", instructions="v1")
        skill_reg.update("greet", instructions="v2")
        result = skill_reg.diff("greet", 1, 2)
        assert len(result["changes"]) > 0

    def test_search(self, skill_reg: SkillRegistry) -> None:
        skill_reg.register("order_handler", instructions="handle orders")
        skill_reg.register("greet", instructions="say hi")
        results = skill_reg.search("order")
        assert len(results) == 1

    def test_export(self, skill_reg: SkillRegistry) -> None:
        skill_reg.register("greet", instructions="hello", metadata={"author": "test"})
        exported = skill_reg.export("greet")
        assert exported["name"] == "greet"
        assert exported["version"] == 1
        assert exported["instructions"] == "hello"

    def test_export_nonexistent(self, skill_reg: SkillRegistry) -> None:
        assert skill_reg.export("nope") == {}

    def test_register_with_all_fields(self, skill_reg: SkillRegistry) -> None:
        name, version = skill_reg.register(
            "full",
            instructions="do stuff",
            examples=[{"input": "hi", "output": "hello"}],
            tool_requirements=["search"],
            constraints=["be polite"],
            metadata={"author": "test"},
        )
        item = skill_reg.get("full")
        assert item is not None
        data = item["data"]
        assert data["examples"] == [{"input": "hi", "output": "hello"}]
        assert data["tool_requirements"] == ["search"]
        assert data["constraints"] == ["be polite"]


# ===================================================================
# PolicyRegistry tests
# ===================================================================

class TestPolicyRegistry:
    """Tests for PolicyRegistry."""

    def test_register(self, policy_reg: PolicyRegistry) -> None:
        name, version = policy_reg.register("safety", rules=["no harm"])
        assert name == "safety"
        assert version == 1

    def test_get(self, policy_reg: PolicyRegistry) -> None:
        policy_reg.register("safety", rules=["no harm"], enforcement="hard")
        item = policy_reg.get("safety")
        assert item is not None
        assert item["data"]["enforcement"] == "hard"

    def test_list(self, policy_reg: PolicyRegistry) -> None:
        policy_reg.register("a", rules=["r1"])
        policy_reg.register("b", rules=["r2"])
        assert len(policy_reg.list()) == 2

    def test_update(self, policy_reg: PolicyRegistry) -> None:
        policy_reg.register("safety", rules=["r1"])
        _, v2 = policy_reg.update("safety", rules=["r1", "r2"])
        assert v2 == 2

    def test_deprecate(self, policy_reg: PolicyRegistry) -> None:
        policy_reg.register("safety", rules=["r1"])
        assert policy_reg.deprecate("safety", 1) is True
        assert len(policy_reg.list()) == 0

    def test_diff(self, policy_reg: PolicyRegistry) -> None:
        policy_reg.register("safety", rules=["r1"])
        policy_reg.update("safety", rules=["r1", "r2"])
        result = policy_reg.diff("safety", 1, 2)
        assert len(result["changes"]) > 0

    def test_search(self, policy_reg: PolicyRegistry) -> None:
        policy_reg.register("safety_core", rules=["no harm"])
        policy_reg.register("billing_policy", rules=["charge correctly"])
        results = policy_reg.search("billing")
        assert len(results) == 1


# ===================================================================
# ToolContractRegistry tests
# ===================================================================

class TestToolContractRegistry:
    """Tests for ToolContractRegistry."""

    def test_register(self, tc_reg: ToolContractRegistry) -> None:
        name, version = tc_reg.register("order_lookup", description="look up orders")
        assert name == "order_lookup"
        assert version == 1

    def test_get(self, tc_reg: ToolContractRegistry) -> None:
        tc_reg.register("order_lookup", side_effect_class="read_only")
        item = tc_reg.get("order_lookup")
        assert item is not None
        assert item["data"]["side_effect_class"] == "read_only"

    def test_list(self, tc_reg: ToolContractRegistry) -> None:
        tc_reg.register("a")
        tc_reg.register("b")
        assert len(tc_reg.list()) == 2

    def test_update(self, tc_reg: ToolContractRegistry) -> None:
        tc_reg.register("order_lookup", description="v1")
        _, v2 = tc_reg.update("order_lookup", description="v2")
        assert v2 == 2

    def test_deprecate(self, tc_reg: ToolContractRegistry) -> None:
        tc_reg.register("order_lookup")
        assert tc_reg.deprecate("order_lookup", 1) is True
        assert len(tc_reg.list()) == 0

    def test_get_agents_using_empty(self, tc_reg: ToolContractRegistry) -> None:
        assert tc_reg.get_agents_using("order_lookup") == []

    def test_get_agents_using(self, tc_reg: ToolContractRegistry) -> None:
        tc_reg.register("order_lookup")
        tc_reg.register_agent_usage("order_lookup", "billing_agent")
        tc_reg.register_agent_usage("order_lookup", "support_agent")
        tc_reg.register_agent_usage("order_lookup", "billing_agent")  # duplicate
        agents = tc_reg.get_agents_using("order_lookup")
        assert agents == ["billing_agent", "support_agent"]

    def test_register_with_schemas(self, tc_reg: ToolContractRegistry) -> None:
        tc_reg.register(
            "order_lookup",
            input_schema={"type": "object", "properties": {"order_id": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"status": {"type": "string"}}},
        )
        item = tc_reg.get("order_lookup")
        assert item is not None
        assert "order_id" in str(item["data"]["input_schema"])


# ===================================================================
# HandoffSchemaRegistry tests
# ===================================================================

class TestHandoffSchemaRegistry:
    """Tests for HandoffSchemaRegistry."""

    def test_register(self, hs_reg: HandoffSchemaRegistry) -> None:
        name, version = hs_reg.register(
            "support_to_billing",
            from_agent="support",
            to_agent="billing",
            required_fields=["goal", "order_id"],
        )
        assert name == "support_to_billing"
        assert version == 1

    def test_get(self, hs_reg: HandoffSchemaRegistry) -> None:
        hs_reg.register("s2b", from_agent="s", to_agent="b", required_fields=["goal"])
        item = hs_reg.get("s2b")
        assert item is not None
        assert item["data"]["from_agent"] == "s"

    def test_list(self, hs_reg: HandoffSchemaRegistry) -> None:
        hs_reg.register("a", from_agent="x", to_agent="y", required_fields=[])
        hs_reg.register("b", from_agent="x", to_agent="z", required_fields=[])
        assert len(hs_reg.list()) == 2

    def test_validate_handoff_valid(self, hs_reg: HandoffSchemaRegistry) -> None:
        hs_reg.register("s2b", from_agent="s", to_agent="b", required_fields=["goal", "order_id"])
        valid, errors = hs_reg.validate_handoff("s2b", {"goal": "refund", "order_id": "123"})
        assert valid is True
        assert errors == []

    def test_validate_handoff_missing_fields(self, hs_reg: HandoffSchemaRegistry) -> None:
        hs_reg.register("s2b", from_agent="s", to_agent="b", required_fields=["goal", "order_id"])
        valid, errors = hs_reg.validate_handoff("s2b", {"goal": "refund"})
        assert valid is False
        assert len(errors) == 1
        assert "order_id" in errors[0]

    def test_validate_handoff_schema_not_found(self, hs_reg: HandoffSchemaRegistry) -> None:
        valid, errors = hs_reg.validate_handoff("nope", {"goal": "x"})
        assert valid is False
        assert "not found" in errors[0]

    def test_validate_handoff_with_type_rules(self, hs_reg: HandoffSchemaRegistry) -> None:
        hs_reg.register(
            "typed",
            from_agent="a",
            to_agent="b",
            required_fields=["goal"],
            validation_rules={"goal": {"type": "string", "min_length": 3}},
        )
        valid, errors = hs_reg.validate_handoff("typed", {"goal": "hi"})
        assert valid is False
        assert any("min_length" in e or "length" in e for e in errors)

    def test_validate_handoff_type_mismatch(self, hs_reg: HandoffSchemaRegistry) -> None:
        hs_reg.register(
            "typed",
            from_agent="a",
            to_agent="b",
            required_fields=["count"],
            validation_rules={"count": {"type": "integer"}},
        )
        valid, errors = hs_reg.validate_handoff("typed", {"count": "not_a_number"})
        assert valid is False
        assert any("type" in e for e in errors)


# ===================================================================
# Importer tests
# ===================================================================

class TestImporter:
    """Tests for bulk import from JSON/YAML."""

    def test_import_from_json(self, store: RegistryStore, tmp_path: object) -> None:
        data = {
            "skills": [
                {"name": "greet", "instructions": "say hi"},
                {"name": "order", "instructions": "handle orders"},
            ],
            "policies": [
                {"name": "safety", "rules": ["no harm"]},
            ],
        }
        path = os.path.join(str(tmp_path), "import.json")
        with open(path, "w") as f:
            json.dump(data, f)

        counts = import_from_file(path, store)
        assert counts["skills"] == 2
        assert counts["policies"] == 1

        # Verify data actually landed in the store
        sr = SkillRegistry(store)
        assert sr.get("greet") is not None
        assert sr.get("order") is not None

    def test_import_partial(self, store: RegistryStore, tmp_path: object) -> None:
        """Import with only some sections present."""
        data = {"tool_contracts": [{"tool_name": "search", "description": "search stuff"}]}
        path = os.path.join(str(tmp_path), "partial.json")
        with open(path, "w") as f:
            json.dump(data, f)

        counts = import_from_file(path, store)
        assert counts.get("tool_contracts") == 1
        assert "skills" not in counts

    def test_import_handoff_schemas(self, store: RegistryStore, tmp_path: object) -> None:
        data = {
            "handoff_schemas": [
                {
                    "name": "s2b",
                    "from_agent": "support",
                    "to_agent": "billing",
                    "required_fields": ["goal"],
                },
            ],
        }
        path = os.path.join(str(tmp_path), "hs.json")
        with open(path, "w") as f:
            json.dump(data, f)

        counts = import_from_file(path, store)
        assert counts["handoff_schemas"] == 1

    def test_import_all_types(self, store: RegistryStore, tmp_path: object) -> None:
        data = {
            "skills": [{"name": "s1", "instructions": "do"}],
            "policies": [{"name": "p1", "rules": ["r"]}],
            "tool_contracts": [{"tool_name": "t1"}],
            "handoff_schemas": [{"name": "h1", "from_agent": "a", "to_agent": "b", "required_fields": []}],
        }
        path = os.path.join(str(tmp_path), "all.json")
        with open(path, "w") as f:
            json.dump(data, f)

        counts = import_from_file(path, store)
        assert counts["skills"] == 1
        assert counts["policies"] == 1
        assert counts["tool_contracts"] == 1
        assert counts["handoff_schemas"] == 1


# ===================================================================
# MutationSurface tests
# ===================================================================

class TestMutationSurfaceExtensions:
    """Tests for the 4 new MutationSurface values and operators."""

    def test_new_surfaces_exist(self) -> None:
        assert MutationSurface.skill.value == "skill"
        assert MutationSurface.policy.value == "policy"
        assert MutationSurface.tool_contract.value == "tool_contract"
        assert MutationSurface.handoff_schema.value == "handoff_schema"

    def test_new_operators_registered(self) -> None:
        registry = create_default_registry()
        assert registry.get("skill_rewrite") is not None
        assert registry.get("policy_edit") is not None
        assert registry.get("tool_contract_edit") is not None
        assert registry.get("handoff_schema_edit") is not None

    def test_skill_rewrite_apply(self) -> None:
        registry = create_default_registry()
        op = registry.get("skill_rewrite")
        assert op is not None
        result = op.apply({}, {"name": "greet", "instructions": "say hi"})
        assert result["skills"]["greet"]["instructions"] == "say hi"

    def test_policy_edit_apply(self) -> None:
        registry = create_default_registry()
        op = registry.get("policy_edit")
        assert op is not None
        result = op.apply({}, {"name": "safety", "rules": ["no harm"]})
        assert result["policies"]["safety"]["rules"] == ["no harm"]

    def test_tool_contract_edit_apply(self) -> None:
        registry = create_default_registry()
        op = registry.get("tool_contract_edit")
        assert op is not None
        result = op.apply({}, {"tool_name": "search", "description": "find stuff"})
        assert result["tool_contracts"]["search"]["description"] == "find stuff"

    def test_handoff_schema_edit_apply(self) -> None:
        registry = create_default_registry()
        op = registry.get("handoff_schema_edit")
        assert op is not None
        result = op.apply({}, {"name": "s2b", "required_fields": ["goal"]})
        assert result["handoff_schemas"]["s2b"]["required_fields"] == ["goal"]

    def test_operator_surfaces_correct(self) -> None:
        registry = create_default_registry()
        assert registry.get("skill_rewrite").surface == MutationSurface.skill
        assert registry.get("policy_edit").surface == MutationSurface.policy
        assert registry.get("tool_contract_edit").surface == MutationSurface.tool_contract
        assert registry.get("handoff_schema_edit").surface == MutationSurface.handoff_schema

    def test_total_operator_count(self) -> None:
        registry = create_default_registry()
        assert len(registry.list_all()) == 13
