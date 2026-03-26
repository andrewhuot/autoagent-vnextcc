"""Tests for core.skills.store.SkillStore."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

import pytest

from core.skills.store import SkillStore
from core.skills.types import (
    EffectivenessMetrics,
    EvalCriterion,
    MutationOperator,
    Policy,
    Skill,
    SkillDependency,
    SkillKind,
    TestCase,
    ToolDefinition,
    TriggerCondition,
)


@pytest.fixture
def temp_db():
    """Provide a temporary database file for each test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


@pytest.fixture
def store(temp_db):
    """Provide a fresh SkillStore instance."""
    s = SkillStore(db_path=temp_db)
    yield s
    s.close()


@pytest.fixture
def sample_build_skill():
    """Sample build-time skill for testing."""
    return Skill(
        id="",
        name="keyword_expansion",
        kind=SkillKind.BUILD,
        version="1.0.0",
        description="Expand keywords in instructions to improve clarity",
        capabilities=["instruction_enhancement", "clarity"],
        mutations=[
            MutationOperator(
                name="append_keywords",
                description="Append keyword list to instructions",
                target_surface="instruction",
                operator_type="append",
                template="Keywords: {keywords}",
                parameters={"keywords": ["precise", "detailed", "accurate"]},
                risk_level="low",
            )
        ],
        triggers=[
            TriggerCondition(
                failure_family="vague_instructions",
                metric_name="clarity_score",
                threshold=0.7,
                operator="lt",
            )
        ],
        eval_criteria=[
            EvalCriterion(
                metric="clarity_score",
                target=0.85,
                operator="gte",
                weight=1.0,
            )
        ],
        tags=["instruction", "clarity"],
        domain="general",
        status="active",
    )


@pytest.fixture
def sample_runtime_skill():
    """Sample run-time skill for testing."""
    return Skill(
        id="",
        name="order_lookup",
        kind=SkillKind.RUNTIME,
        version="1.0.0",
        description="Look up customer orders by order ID",
        capabilities=["order_retrieval", "customer_support"],
        tools=[
            ToolDefinition(
                name="get_order",
                description="Retrieve order details by ID",
                parameters={
                    "type": "object",
                    "properties": {
                        "order_id": {"type": "string"}
                    },
                    "required": ["order_id"],
                },
                returns={"type": "object"},
                implementation="api.orders.get_order",
                sandbox_policy="read_only",
            )
        ],
        instructions="Use get_order tool to retrieve order details. Always verify order belongs to customer.",
        policies=[
            Policy(
                name="verify_ownership",
                description="Verify order belongs to authenticated customer",
                rule_type="require",
                condition="order.customer_id == auth.customer_id",
                action="reject",
                severity="high",
            )
        ],
        dependencies=[
            SkillDependency(
                skill_id="auth_skill_id",
                version_constraint=">=1.0",
                optional=False,
            )
        ],
        test_cases=[
            TestCase(
                name="valid_lookup",
                description="Test successful order lookup",
                input={"order_id": "ORD-123"},
                expected_output={"status": "success"},
                assertions=["output.status == 'success'"],
            )
        ],
        tags=["customer_support", "orders"],
        domain="customer-support",
        status="active",
    )


# ------------------------------------------------------------------
# Core CRUD Tests
# ------------------------------------------------------------------


def test_create_skill_generates_id(store, sample_build_skill):
    """Test that create generates an ID if not provided."""
    assert sample_build_skill.id == ""
    skill_id = store.create(sample_build_skill)
    assert skill_id != ""
    assert len(skill_id) == 36  # UUID format


def test_create_skill_preserves_existing_id(store, sample_build_skill):
    """Test that create preserves provided ID."""
    sample_build_skill.id = "custom-id-123"
    skill_id = store.create(sample_build_skill)
    assert skill_id == "custom-id-123"


def test_create_duplicate_name_version_fails(store, sample_build_skill):
    """Test that creating duplicate (name, version) fails."""
    store.create(sample_build_skill)

    # Try to create another skill with same name and version
    duplicate = Skill(
        id="",
        name=sample_build_skill.name,
        kind=SkillKind.BUILD,
        version=sample_build_skill.version,
        description="Different description",
    )

    with pytest.raises(ValueError, match="already exists"):
        store.create(duplicate)


def test_get_skill_by_id(store, sample_build_skill):
    """Test retrieving a skill by ID."""
    skill_id = store.create(sample_build_skill)

    retrieved = store.get(skill_id)
    assert retrieved is not None
    assert retrieved.id == skill_id
    assert retrieved.name == sample_build_skill.name
    assert retrieved.kind == SkillKind.BUILD


def test_get_nonexistent_skill_returns_none(store):
    """Test that getting nonexistent skill returns None."""
    result = store.get("nonexistent-id")
    assert result is None


def test_get_by_name_latest_version(store, sample_build_skill):
    """Test get_by_name returns latest version when version not specified."""
    # Create v1.0.0
    store.create(sample_build_skill)

    # Create v2.0.0
    v2 = Skill(
        id="",
        name=sample_build_skill.name,
        kind=SkillKind.BUILD,
        version="2.0.0",
        description="Version 2",
    )
    time.sleep(0.01)  # Ensure different timestamp
    store.create(v2)

    # Get latest (should be v2)
    latest = store.get_by_name(sample_build_skill.name)
    assert latest is not None
    assert latest.version == "2.0.0"


def test_get_by_name_specific_version(store, sample_build_skill):
    """Test get_by_name with specific version."""
    store.create(sample_build_skill)

    # Create v2.0.0
    v2 = Skill(
        id="",
        name=sample_build_skill.name,
        kind=SkillKind.BUILD,
        version="2.0.0",
        description="Version 2",
    )
    store.create(v2)

    # Get v1 specifically
    v1 = store.get_by_name(sample_build_skill.name, version="1.0.0")
    assert v1 is not None
    assert v1.version == "1.0.0"


def test_update_skill(store, sample_build_skill):
    """Test updating an existing skill."""
    skill_id = store.create(sample_build_skill)

    # Modify and update
    skill = store.get(skill_id)
    assert skill is not None
    skill.description = "Updated description"
    skill.status = "deprecated"

    success = store.update(skill)
    assert success is True

    # Verify changes
    updated = store.get(skill_id)
    assert updated is not None
    assert updated.description == "Updated description"
    assert updated.status == "deprecated"


def test_update_nonexistent_skill_returns_false(store, sample_build_skill):
    """Test updating nonexistent skill returns False."""
    sample_build_skill.id = "nonexistent-id"
    success = store.update(sample_build_skill)
    assert success is False


def test_update_without_id_raises_error(store, sample_build_skill):
    """Test that update without ID raises error."""
    with pytest.raises(ValueError, match="without an ID"):
        store.update(sample_build_skill)


def test_delete_skill(store, sample_build_skill):
    """Test deleting a skill."""
    skill_id = store.create(sample_build_skill)

    # Delete
    success = store.delete(skill_id)
    assert success is True

    # Verify deletion
    result = store.get(skill_id)
    assert result is None


def test_delete_nonexistent_skill_returns_false(store):
    """Test deleting nonexistent skill returns False."""
    success = store.delete("nonexistent-id")
    assert success is False


def test_delete_cascades_to_outcomes(store, sample_build_skill):
    """Test that deleting skill cascades to outcomes."""
    skill_id = store.create(sample_build_skill)

    # Record some outcomes
    store.record_outcome(skill_id, 0.15, True)
    store.record_outcome(skill_id, 0.10, True)

    # Delete skill
    store.delete(skill_id)

    # Verify outcomes are deleted (check with raw SQL)
    conn = sqlite3.connect(store.db_path)
    count = conn.execute(
        "SELECT COUNT(*) FROM skill_outcomes WHERE skill_id = ?",
        (skill_id,),
    ).fetchone()[0]
    conn.close()

    assert count == 0


# ------------------------------------------------------------------
# Listing and Filtering Tests
# ------------------------------------------------------------------


def test_list_all_skills(store, sample_build_skill, sample_runtime_skill):
    """Test listing all skills."""
    store.create(sample_build_skill)
    store.create(sample_runtime_skill)

    all_skills = store.list()
    assert len(all_skills) == 2


def test_list_filter_by_kind(store, sample_build_skill, sample_runtime_skill):
    """Test filtering by skill kind."""
    store.create(sample_build_skill)
    store.create(sample_runtime_skill)

    build_skills = store.list(kind=SkillKind.BUILD)
    assert len(build_skills) == 1
    assert build_skills[0].kind == SkillKind.BUILD

    runtime_skills = store.list(kind=SkillKind.RUNTIME)
    assert len(runtime_skills) == 1
    assert runtime_skills[0].kind == SkillKind.RUNTIME


def test_list_filter_by_domain(store, sample_build_skill, sample_runtime_skill):
    """Test filtering by domain."""
    store.create(sample_build_skill)
    store.create(sample_runtime_skill)

    customer_support = store.list(domain="customer-support")
    assert len(customer_support) == 1
    assert customer_support[0].name == "order_lookup"


def test_list_filter_by_status(store, sample_build_skill):
    """Test filtering by status."""
    store.create(sample_build_skill)

    # Create deprecated skill
    deprecated = Skill(
        id="",
        name="deprecated_skill",
        kind=SkillKind.BUILD,
        version="1.0.0",
        description="Old skill",
        status="deprecated",
    )
    store.create(deprecated)

    active = store.list(status="active")
    assert len(active) == 1
    assert active[0].status == "active"

    deprecated_list = store.list(status="deprecated")
    assert len(deprecated_list) == 1
    assert deprecated_list[0].status == "deprecated"


def test_list_filter_by_tags(store, sample_build_skill, sample_runtime_skill):
    """Test filtering by tags."""
    store.create(sample_build_skill)
    store.create(sample_runtime_skill)

    # Find skills with "customer_support" tag
    support_skills = store.list(tags=["customer_support"])
    assert len(support_skills) == 1
    assert "customer_support" in support_skills[0].tags

    # Find skills with "instruction" tag
    instruction_skills = store.list(tags=["instruction"])
    assert len(instruction_skills) == 1
    assert "instruction" in instruction_skills[0].tags


def test_list_filter_all_tags_required(store):
    """Test that tag filtering requires ALL tags to match."""
    skill = Skill(
        id="",
        name="multi_tag",
        kind=SkillKind.BUILD,
        version="1.0.0",
        description="Multiple tags",
        tags=["tag1", "tag2", "tag3"],
    )
    store.create(skill)

    # Should match
    result = store.list(tags=["tag1", "tag2"])
    assert len(result) == 1

    # Should not match (tag4 not present)
    result = store.list(tags=["tag1", "tag4"])
    assert len(result) == 0


def test_list_combined_filters(store, sample_build_skill, sample_runtime_skill):
    """Test combining multiple filters."""
    store.create(sample_build_skill)
    store.create(sample_runtime_skill)

    # Filter by kind AND domain
    result = store.list(kind=SkillKind.RUNTIME, domain="customer-support")
    assert len(result) == 1
    assert result[0].name == "order_lookup"

    # Filter with no matches
    result = store.list(kind=SkillKind.BUILD, domain="customer-support")
    assert len(result) == 0


# ------------------------------------------------------------------
# Search Tests
# ------------------------------------------------------------------


def test_search_by_name(store, sample_build_skill):
    """Test searching by skill name."""
    store.create(sample_build_skill)

    results = store.search("keyword")
    assert len(results) == 1
    assert results[0].name == "keyword_expansion"


def test_search_by_description(store, sample_build_skill):
    """Test searching by description."""
    store.create(sample_build_skill)

    results = store.search("clarity")
    assert len(results) == 1


def test_search_case_insensitive(store, sample_build_skill):
    """Test that search is case-insensitive."""
    store.create(sample_build_skill)

    results = store.search("KEYWORD")
    assert len(results) == 1


def test_search_partial_match(store, sample_build_skill):
    """Test partial string matching."""
    store.create(sample_build_skill)

    results = store.search("key")
    assert len(results) == 1


def test_search_with_kind_filter(store, sample_build_skill, sample_runtime_skill):
    """Test search with kind filter."""
    store.create(sample_build_skill)
    store.create(sample_runtime_skill)

    # Search all
    results = store.search("order")
    assert len(results) == 1

    # Search only runtime
    results = store.search("order", kind=SkillKind.RUNTIME)
    assert len(results) == 1

    # Search only build (should find nothing)
    results = store.search("order", kind=SkillKind.BUILD)
    assert len(results) == 0


def test_search_no_results(store, sample_build_skill):
    """Test search with no matches."""
    store.create(sample_build_skill)

    results = store.search("nonexistent_query_xyz")
    assert len(results) == 0


# ------------------------------------------------------------------
# Effectiveness Tracking Tests
# ------------------------------------------------------------------


def test_record_outcome(store, sample_build_skill):
    """Test recording an outcome."""
    skill_id = store.create(sample_build_skill)

    # Record outcome
    store.record_outcome(skill_id, 0.15, True)

    # Verify metrics updated
    metrics = store.get_effectiveness(skill_id)
    assert metrics.times_applied == 1
    assert metrics.success_count == 1
    assert metrics.success_rate == 1.0
    assert metrics.avg_improvement == 0.15
    assert metrics.total_improvement == 0.15
    assert metrics.last_applied is not None


def test_record_multiple_outcomes(store, sample_build_skill):
    """Test recording multiple outcomes."""
    skill_id = store.create(sample_build_skill)

    store.record_outcome(skill_id, 0.15, True)
    store.record_outcome(skill_id, 0.10, True)
    store.record_outcome(skill_id, 0.05, False)

    metrics = store.get_effectiveness(skill_id)
    assert metrics.times_applied == 3
    assert metrics.success_count == 2
    assert metrics.success_rate == 2/3
    assert abs(metrics.avg_improvement - 0.125) < 0.001  # (0.15 + 0.10) / 2
    assert abs(metrics.total_improvement - 0.25) < 0.001


def test_record_outcome_nonexistent_skill_raises_error(store):
    """Test recording outcome for nonexistent skill raises error."""
    with pytest.raises(ValueError, match="not found"):
        store.record_outcome("nonexistent-id", 0.1, True)


def test_get_effectiveness_nonexistent_skill(store):
    """Test getting effectiveness for nonexistent skill returns default metrics."""
    metrics = store.get_effectiveness("nonexistent-id")
    assert metrics.times_applied == 0
    assert metrics.success_rate == 0.0


# ------------------------------------------------------------------
# Recommendation Engine Tests
# ------------------------------------------------------------------


def test_recommend_by_failure_family(store, sample_build_skill):
    """Test recommendation by failure family."""
    store.create(sample_build_skill)

    # Should match
    results = store.recommend(failure_family="vague_instructions", kind=SkillKind.BUILD)
    assert len(results) == 1
    assert results[0].name == "keyword_expansion"

    # Should not match
    results = store.recommend(failure_family="hallucination", kind=SkillKind.BUILD)
    assert len(results) == 0


def test_recommend_by_metric_threshold(store, sample_build_skill):
    """Test recommendation by metric threshold."""
    store.create(sample_build_skill)

    # Trigger: clarity_score < 0.7
    # Should match
    results = store.recommend(metrics={"clarity_score": 0.6}, kind=SkillKind.BUILD)
    assert len(results) == 1

    # Should not match (score above threshold)
    results = store.recommend(metrics={"clarity_score": 0.8}, kind=SkillKind.BUILD)
    assert len(results) == 0


def test_recommend_sorted_by_effectiveness(store):
    """Test that recommendations are sorted by effectiveness."""
    # Create two skills with different effectiveness
    skill1 = Skill(
        id="",
        name="skill1",
        kind=SkillKind.BUILD,
        version="1.0.0",
        description="Skill 1",
        triggers=[TriggerCondition(failure_family="test_family")],
    )
    skill1_id = store.create(skill1)
    store.record_outcome(skill1_id, 0.1, True)

    skill2 = Skill(
        id="",
        name="skill2",
        kind=SkillKind.BUILD,
        version="1.0.0",
        description="Skill 2",
        triggers=[TriggerCondition(failure_family="test_family")],
    )
    skill2_id = store.create(skill2)
    store.record_outcome(skill2_id, 0.5, True)
    store.record_outcome(skill2_id, 0.4, True)

    # Recommend
    results = store.recommend(failure_family="test_family", kind=SkillKind.BUILD)
    assert len(results) == 2
    # skill2 should be first (higher avg_improvement)
    assert results[0].name == "skill2"
    assert results[1].name == "skill1"


def test_recommend_only_active_skills(store, sample_build_skill):
    """Test that recommendations only include active skills."""
    sample_build_skill.status = "deprecated"
    store.create(sample_build_skill)

    results = store.recommend(failure_family="vague_instructions", kind=SkillKind.BUILD)
    assert len(results) == 0


def test_recommend_runtime_skills(store, sample_runtime_skill):
    """Test recommendation for runtime skills."""
    skill_id = store.create(sample_runtime_skill)
    store.record_outcome(skill_id, 0.2, True)

    results = store.recommend(kind=SkillKind.RUNTIME)
    assert len(results) == 1
    assert results[0].name == "order_lookup"


# ------------------------------------------------------------------
# Analytics Tests
# ------------------------------------------------------------------


def test_get_top_performers(store):
    """Test getting top performers."""
    # Create skills with varying effectiveness
    for i in range(5):
        skill = Skill(
            id="",
            name=f"skill_{i}",
            kind=SkillKind.BUILD,
            version="1.0.0",
            description=f"Skill {i}",
        )
        skill_id = store.create(skill)
        # Give different improvements
        store.record_outcome(skill_id, (i + 1) * 0.1, True)

    top3 = store.get_top_performers(n=3)
    assert len(top3) == 3
    # Should be sorted by effectiveness
    assert top3[0].name == "skill_4"  # highest improvement
    assert top3[1].name == "skill_3"
    assert top3[2].name == "skill_2"


def test_get_top_performers_excludes_unapplied(store, sample_build_skill):
    """Test that top performers excludes skills never applied."""
    skill_id = store.create(sample_build_skill)

    # Don't record any outcomes
    top = store.get_top_performers()
    assert len(top) == 0


def test_get_top_performers_filter_by_kind(store):
    """Test top performers filtered by kind."""
    # Create build skill
    build = Skill(
        id="",
        name="build_skill",
        kind=SkillKind.BUILD,
        version="1.0.0",
        description="Build",
    )
    build_id = store.create(build)
    store.record_outcome(build_id, 0.5, True)

    # Create runtime skill
    runtime = Skill(
        id="",
        name="runtime_skill",
        kind=SkillKind.RUNTIME,
        version="1.0.0",
        description="Runtime",
    )
    runtime_id = store.create(runtime)
    store.record_outcome(runtime_id, 0.3, True)

    # Get top build skills
    top_build = store.get_top_performers(kind=SkillKind.BUILD)
    assert len(top_build) == 1
    assert top_build[0].kind == SkillKind.BUILD

    # Get top runtime skills
    top_runtime = store.get_top_performers(kind=SkillKind.RUNTIME)
    assert len(top_runtime) == 1
    assert top_runtime[0].kind == SkillKind.RUNTIME


def test_get_stats(store, sample_build_skill, sample_runtime_skill):
    """Test getting overall store statistics."""
    skill1_id = store.create(sample_build_skill)
    skill2_id = store.create(sample_runtime_skill)

    store.record_outcome(skill1_id, 0.1, True)
    store.record_outcome(skill2_id, 0.2, True)
    store.record_outcome(skill2_id, 0.15, False)

    stats = store.get_stats()
    assert stats["total_skills"] == 2
    assert stats["build_skills"] == 1
    assert stats["runtime_skills"] == 1
    assert stats["active_skills"] == 2
    assert stats["total_outcomes"] == 3


# ------------------------------------------------------------------
# Thread Safety Tests
# ------------------------------------------------------------------


def test_concurrent_creates(temp_db):
    """Test concurrent skill creation from multiple threads."""
    store = SkillStore(db_path=temp_db)
    results = []
    errors = []

    def create_skill(i):
        try:
            skill = Skill(
                id="",
                name=f"skill_{i}",
                kind=SkillKind.BUILD,
                version="1.0.0",
                description=f"Skill {i}",
            )
            skill_id = store.create(skill)
            results.append(skill_id)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=create_skill, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    store.close()

    assert len(errors) == 0
    assert len(results) == 10
    assert len(set(results)) == 10  # All unique IDs


def test_concurrent_reads_and_writes(temp_db):
    """Test concurrent reads and writes."""
    store = SkillStore(db_path=temp_db)

    # Create initial skill
    skill = Skill(
        id="",
        name="test_skill",
        kind=SkillKind.BUILD,
        version="1.0.0",
        description="Test",
    )
    skill_id = store.create(skill)

    read_results = []
    write_errors = []

    def read_skill():
        for _ in range(10):
            s = store.get(skill_id)
            if s is not None:
                read_results.append(s.name)

    def write_outcome():
        try:
            for i in range(10):
                store.record_outcome(skill_id, i * 0.01, True)
        except Exception as e:
            write_errors.append(e)

    # Start readers and writers
    readers = [threading.Thread(target=read_skill) for _ in range(3)]
    writers = [threading.Thread(target=write_outcome) for _ in range(2)]

    all_threads = readers + writers
    for t in all_threads:
        t.start()
    for t in all_threads:
        t.join()

    store.close()

    assert len(write_errors) == 0
    assert len(read_results) > 0


# ------------------------------------------------------------------
# Edge Cases and Error Handling
# ------------------------------------------------------------------


def test_empty_database(store):
    """Test operations on empty database."""
    assert store.list() == []
    assert store.search("anything") == []
    assert store.get_top_performers() == []

    stats = store.get_stats()
    assert stats["total_skills"] == 0


def test_database_path_creation(tmp_path):
    """Test that database file and parent directories are created."""
    db_path = tmp_path / "subdir" / "nested" / "skills.db"
    store = SkillStore(db_path=str(db_path))

    assert db_path.exists()
    assert db_path.parent.exists()

    store.close()


def test_skill_with_all_fields(store):
    """Test creating and retrieving a skill with all fields populated."""
    skill = Skill(
        id="custom-id",
        name="full_skill",
        kind=SkillKind.BUILD,
        version="1.0.0",
        description="Full skill with all fields",
        capabilities=["cap1", "cap2"],
        mutations=[
            MutationOperator(
                name="mut1",
                description="Mutation 1",
                target_surface="instruction",
                operator_type="append",
            )
        ],
        triggers=[TriggerCondition(failure_family="test")],
        eval_criteria=[EvalCriterion(metric="accuracy", target=0.9)],
        guardrails=["no_pii", "no_toxic"],
        tools=[],
        instructions="Test instructions",
        policies=[],
        dependencies=[],
        test_cases=[],
        tags=["tag1", "tag2"],
        domain="test-domain",
        effectiveness=EffectivenessMetrics(),
        metadata={"key": "value"},
        author="test_author",
        status="draft",
    )

    skill_id = store.create(skill)
    retrieved = store.get(skill_id)

    assert retrieved is not None
    assert retrieved.name == "full_skill"
    assert retrieved.status == "draft"
    assert retrieved.domain == "test-domain"
    assert len(retrieved.capabilities) == 2
    assert len(retrieved.mutations) == 1
    assert len(retrieved.guardrails) == 2


def test_clear_database(store, sample_build_skill):
    """Test clearing all data."""
    skill_id = store.create(sample_build_skill)
    store.record_outcome(skill_id, 0.1, True)

    assert len(store.list()) == 1

    store.clear()

    assert len(store.list()) == 0
    stats = store.get_stats()
    assert stats["total_skills"] == 0
    assert stats["total_outcomes"] == 0
