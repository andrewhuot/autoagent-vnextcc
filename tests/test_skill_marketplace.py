"""Tests for core.skills.marketplace — skill discovery, installation, and publishing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.skills.marketplace import MarketplaceError, SkillMarketplace
from core.skills.store import SkillStore
from core.skills.types import Skill, SkillKind, MutationOperator, TriggerCondition, EvalCriterion


@pytest.fixture
def temp_marketplace(tmp_path: Path) -> SkillMarketplace:
    """Create a temporary marketplace for testing."""
    marketplace_dir = tmp_path / "marketplace"
    return SkillMarketplace(marketplace_dir=str(marketplace_dir))


@pytest.fixture
def temp_store(tmp_path: Path) -> SkillStore:
    """Create a temporary skill store for testing."""
    db_path = tmp_path / "skills.db"
    return SkillStore(db_path=str(db_path))


@pytest.fixture
def sample_build_skill() -> Skill:
    """Create a sample build-time skill for testing."""
    return Skill(
        id="test-build-001",
        name="test_keyword_expansion",
        kind=SkillKind.BUILD,
        version="1.0.0",
        description="Test skill for expanding routing keywords",
        capabilities=["keyword-expansion", "routing-improvement"],
        mutations=[
            MutationOperator(
                name="expand_keywords",
                description="Add related keywords to routing config",
                target_surface="routing",
                operator_type="append",
            )
        ],
        triggers=[
            TriggerCondition(
                failure_family="routing_failure",
                metric_name="routing_accuracy",
                threshold=0.8,
                operator="lt",
            )
        ],
        eval_criteria=[
            EvalCriterion(
                metric="routing_accuracy",
                target=0.9,
                operator="gt",
            )
        ],
        tags=["routing", "keywords", "test"],
        domain="general",
        author="test-author",
        status="active",
    )


@pytest.fixture
def sample_runtime_skill() -> Skill:
    """Create a sample run-time skill for testing."""
    return Skill(
        id="test-runtime-001",
        name="test_order_lookup",
        kind=SkillKind.RUNTIME,
        version="1.0.0",
        description="Test skill for looking up orders",
        capabilities=["order-lookup", "order-status"],
        tools=[],
        instructions="Look up order status using the order ID",
        tags=["orders", "lookup", "test"],
        domain="customer-support",
        author="test-author",
        status="active",
    )


# ---------------------------------------------------------------------------
# Browse and Search
# ---------------------------------------------------------------------------


class TestBrowse:
    def test_empty_marketplace_returns_empty_list(self, temp_marketplace: SkillMarketplace) -> None:
        results = temp_marketplace.browse()
        assert results == []

    def test_browse_returns_published_skill(
        self,
        temp_marketplace: SkillMarketplace,
        sample_build_skill: Skill,
    ) -> None:
        temp_marketplace.publish(sample_build_skill)
        results = temp_marketplace.browse()

        assert len(results) == 1
        assert results[0]["id"] == sample_build_skill.id
        assert results[0]["name"] == sample_build_skill.name
        assert results[0]["kind"] == SkillKind.BUILD.value

    def test_browse_with_kind_filter(
        self,
        temp_marketplace: SkillMarketplace,
        sample_build_skill: Skill,
        sample_runtime_skill: Skill,
    ) -> None:
        temp_marketplace.publish(sample_build_skill)
        temp_marketplace.publish(sample_runtime_skill)

        build_results = temp_marketplace.browse(kind=SkillKind.BUILD)
        assert len(build_results) == 1
        assert build_results[0]["id"] == sample_build_skill.id

        runtime_results = temp_marketplace.browse(kind=SkillKind.RUNTIME)
        assert len(runtime_results) == 1
        assert runtime_results[0]["id"] == sample_runtime_skill.id

    def test_browse_with_domain_filter(
        self,
        temp_marketplace: SkillMarketplace,
        sample_build_skill: Skill,
        sample_runtime_skill: Skill,
    ) -> None:
        temp_marketplace.publish(sample_build_skill)
        temp_marketplace.publish(sample_runtime_skill)

        general_results = temp_marketplace.browse(domain="general")
        assert len(general_results) == 1
        assert general_results[0]["domain"] == "general"

        support_results = temp_marketplace.browse(domain="customer-support")
        assert len(support_results) == 1
        assert support_results[0]["domain"] == "customer-support"

    def test_browse_with_tags_filter(
        self,
        temp_marketplace: SkillMarketplace,
        sample_build_skill: Skill,
        sample_runtime_skill: Skill,
    ) -> None:
        temp_marketplace.publish(sample_build_skill)
        temp_marketplace.publish(sample_runtime_skill)

        routing_results = temp_marketplace.browse(tags=["routing"])
        assert len(routing_results) == 1
        assert "routing" in routing_results[0]["tags"]

        order_results = temp_marketplace.browse(tags=["orders"])
        assert len(order_results) == 1
        assert "orders" in order_results[0]["tags"]


class TestSearch:
    def test_search_empty_marketplace(self, temp_marketplace: SkillMarketplace) -> None:
        results = temp_marketplace.search("keyword")
        assert results == []

    def test_search_by_name(
        self,
        temp_marketplace: SkillMarketplace,
        sample_build_skill: Skill,
    ) -> None:
        temp_marketplace.publish(sample_build_skill)
        results = temp_marketplace.search("keyword")

        assert len(results) == 1
        assert results[0]["name"] == sample_build_skill.name

    def test_search_by_description(
        self,
        temp_marketplace: SkillMarketplace,
        sample_runtime_skill: Skill,
    ) -> None:
        temp_marketplace.publish(sample_runtime_skill)
        results = temp_marketplace.search("looking up orders")

        assert len(results) == 1
        assert results[0]["id"] == sample_runtime_skill.id

    def test_search_by_capabilities(
        self,
        temp_marketplace: SkillMarketplace,
        sample_build_skill: Skill,
    ) -> None:
        temp_marketplace.publish(sample_build_skill)
        results = temp_marketplace.search("routing-improvement")

        assert len(results) == 1
        assert "routing-improvement" in results[0]["capabilities"]

    def test_search_by_tags(
        self,
        temp_marketplace: SkillMarketplace,
        sample_runtime_skill: Skill,
    ) -> None:
        temp_marketplace.publish(sample_runtime_skill)
        results = temp_marketplace.search("lookup")

        assert len(results) == 1
        assert "lookup" in results[0]["tags"]

    def test_search_is_case_insensitive(
        self,
        temp_marketplace: SkillMarketplace,
        sample_build_skill: Skill,
    ) -> None:
        temp_marketplace.publish(sample_build_skill)
        results = temp_marketplace.search("KEYWORD")

        assert len(results) == 1

    def test_search_with_kind_filter(
        self,
        temp_marketplace: SkillMarketplace,
        sample_build_skill: Skill,
        sample_runtime_skill: Skill,
    ) -> None:
        temp_marketplace.publish(sample_build_skill)
        temp_marketplace.publish(sample_runtime_skill)

        build_results = temp_marketplace.search("test", kind=SkillKind.BUILD)
        assert len(build_results) == 1
        assert build_results[0]["kind"] == SkillKind.BUILD.value


# ---------------------------------------------------------------------------
# Get Metadata
# ---------------------------------------------------------------------------


class TestGetMetadata:
    def test_get_metadata_not_found(self, temp_marketplace: SkillMarketplace) -> None:
        result = temp_marketplace.get_metadata("nonexistent")
        assert result is None

    def test_get_metadata_returns_skill_info(
        self,
        temp_marketplace: SkillMarketplace,
        sample_build_skill: Skill,
    ) -> None:
        temp_marketplace.publish(sample_build_skill)
        metadata = temp_marketplace.get_metadata(sample_build_skill.id)

        assert metadata is not None
        assert metadata["id"] == sample_build_skill.id
        assert metadata["name"] == sample_build_skill.name
        assert metadata["version"] == sample_build_skill.version
        assert metadata["description"] == sample_build_skill.description


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------


class TestInstall:
    def test_install_from_marketplace_id(
        self,
        temp_marketplace: SkillMarketplace,
        temp_store: SkillStore,
        sample_build_skill: Skill,
    ) -> None:
        # Publish to marketplace first
        temp_marketplace.publish(sample_build_skill)

        # Install from marketplace
        installed = temp_marketplace.install(sample_build_skill.id, temp_store)

        assert installed.id == sample_build_skill.id
        assert installed.name == sample_build_skill.name

        # Verify it's in the store
        stored = temp_store.get_by_name(sample_build_skill.name)
        assert stored is not None
        assert stored.name == sample_build_skill.name

    def test_install_from_yaml_file(
        self,
        temp_marketplace: SkillMarketplace,
        temp_store: SkillStore,
        sample_build_skill: Skill,
        tmp_path: Path,
    ) -> None:
        # Create a YAML file
        skill_file = tmp_path / "test_skill.yaml"
        import yaml

        with open(skill_file, "w") as f:
            yaml.dump({"skills": [sample_build_skill.to_dict()]}, f)

        # Install from file
        installed = temp_marketplace.install(str(skill_file), temp_store)

        assert installed.name == sample_build_skill.name

        # Verify it's in the store
        stored = temp_store.get_by_name(sample_build_skill.name)
        assert stored is not None

    def test_install_skill_not_found_raises_error(
        self,
        temp_marketplace: SkillMarketplace,
        temp_store: SkillStore,
    ) -> None:
        with pytest.raises(MarketplaceError, match="not found"):
            temp_marketplace.install("nonexistent-skill", temp_store)

    def test_install_idempotent(
        self,
        temp_marketplace: SkillMarketplace,
        temp_store: SkillStore,
        sample_build_skill: Skill,
    ) -> None:
        temp_marketplace.publish(sample_build_skill)

        # Install twice
        first = temp_marketplace.install(sample_build_skill.id, temp_store)
        second = temp_marketplace.install(sample_build_skill.id, temp_store)

        # Should return the same skill
        assert first.name == second.name

        # Should only be one in the store
        all_skills = temp_store.list()
        assert len(all_skills) == 1


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


class TestPublish:
    def test_publish_creates_yaml_file(
        self,
        temp_marketplace: SkillMarketplace,
        sample_build_skill: Skill,
    ) -> None:
        result = temp_marketplace.publish(sample_build_skill)

        assert result is True

        # Verify file exists
        skill_file = temp_marketplace.marketplace_dir / f"{sample_build_skill.id}.yaml"
        assert skill_file.exists()

    def test_publish_updates_index(
        self,
        temp_marketplace: SkillMarketplace,
        sample_build_skill: Skill,
    ) -> None:
        temp_marketplace.publish(sample_build_skill)

        # Load index and verify
        index_path = temp_marketplace.marketplace_dir / "marketplace.json"
        assert index_path.exists()

        with open(index_path) as f:
            index = json.load(f)

        assert sample_build_skill.id in index
        assert index[sample_build_skill.id]["name"] == sample_build_skill.name

    def test_publish_invalid_skill_raises_error(
        self,
        temp_marketplace: SkillMarketplace,
    ) -> None:
        # Create an invalid skill (missing required fields)
        invalid_skill = Skill(
            id="",  # Invalid: empty ID
            name="",  # Invalid: empty name
            kind=SkillKind.BUILD,
            version="1.0.0",
            description="Test",
        )

        with pytest.raises(MarketplaceError, match="validation failed"):
            temp_marketplace.publish(invalid_skill)


# ---------------------------------------------------------------------------
# Index Management
# ---------------------------------------------------------------------------


class TestIndexManagement:
    def test_rebuild_index(
        self,
        temp_marketplace: SkillMarketplace,
        sample_build_skill: Skill,
        sample_runtime_skill: Skill,
    ) -> None:
        # Publish two skills
        temp_marketplace.publish(sample_build_skill)
        temp_marketplace.publish(sample_runtime_skill)

        # Delete the index
        index_path = temp_marketplace.marketplace_dir / "marketplace.json"
        index_path.unlink()

        # Rebuild
        count = temp_marketplace.rebuild_index()

        assert count == 2

        # Verify index is recreated
        assert index_path.exists()
        results = temp_marketplace.browse()
        assert len(results) == 2


# ---------------------------------------------------------------------------
# Bulk Operations
# ---------------------------------------------------------------------------


class TestBulkOperations:
    def test_install_all(
        self,
        temp_marketplace: SkillMarketplace,
        temp_store: SkillStore,
        sample_build_skill: Skill,
        sample_runtime_skill: Skill,
    ) -> None:
        # Publish skills to marketplace
        temp_marketplace.publish(sample_build_skill)
        temp_marketplace.publish(sample_runtime_skill)

        # Install all
        count, errors = temp_marketplace.install_all(temp_store)

        assert count == 2
        assert len(errors) == 0

        # Verify they're in the store
        all_skills = temp_store.list()
        assert len(all_skills) == 2

    def test_install_all_with_kind_filter(
        self,
        temp_marketplace: SkillMarketplace,
        temp_store: SkillStore,
        sample_build_skill: Skill,
        sample_runtime_skill: Skill,
    ) -> None:
        temp_marketplace.publish(sample_build_skill)
        temp_marketplace.publish(sample_runtime_skill)

        # Install only build skills
        count, errors = temp_marketplace.install_all(temp_store, kind=SkillKind.BUILD)

        assert count == 1
        assert len(errors) == 0

        # Verify only build skill is in store
        all_skills = temp_store.list()
        assert len(all_skills) == 1
        assert all_skills[0].kind == SkillKind.BUILD

    def test_export_marketplace(
        self,
        temp_marketplace: SkillMarketplace,
        sample_build_skill: Skill,
        tmp_path: Path,
    ) -> None:
        temp_marketplace.publish(sample_build_skill)

        export_dir = tmp_path / "export"
        count = temp_marketplace.export_marketplace(str(export_dir))

        assert count == 1

        # Verify exported file exists
        exported_file = export_dir / f"{sample_build_skill.id}.yaml"
        assert exported_file.exists()

        # Verify index was exported
        index_file = export_dir / "marketplace.json"
        assert index_file.exists()

    def test_import_marketplace(
        self,
        temp_marketplace: SkillMarketplace,
        sample_build_skill: Skill,
        tmp_path: Path,
    ) -> None:
        # Create import directory with a skill file
        import_dir = tmp_path / "import"
        import_dir.mkdir()

        import yaml

        skill_file = import_dir / f"{sample_build_skill.id}.yaml"
        with open(skill_file, "w") as f:
            yaml.dump({"skills": [sample_build_skill.to_dict()]}, f)

        # Import
        count = temp_marketplace.import_marketplace(str(import_dir))

        assert count == 1

        # Verify skill is in marketplace
        results = temp_marketplace.browse()
        assert len(results) == 1
        assert results[0]["id"] == sample_build_skill.id


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


class TestStatistics:
    def test_get_stats_empty_marketplace(self, temp_marketplace: SkillMarketplace) -> None:
        stats = temp_marketplace.get_stats()

        assert stats["total_skills"] == 0
        assert stats["build_skills"] == 0
        assert stats["runtime_skills"] == 0

    def test_get_stats_with_skills(
        self,
        temp_marketplace: SkillMarketplace,
        sample_build_skill: Skill,
        sample_runtime_skill: Skill,
    ) -> None:
        temp_marketplace.publish(sample_build_skill)
        temp_marketplace.publish(sample_runtime_skill)

        stats = temp_marketplace.get_stats()

        assert stats["total_skills"] == 2
        assert stats["build_skills"] == 1
        assert stats["runtime_skills"] == 1
        assert "general" in stats["domains"]
        assert "customer-support" in stats["domains"]
        assert len(stats["top_tags"]) > 0
