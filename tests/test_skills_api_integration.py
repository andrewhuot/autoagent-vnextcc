"""Integration test for skills API - tests core functionality without HTTP.

This test validates the skills API logic by directly calling the route functions
without the FastAPI framework overhead.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from core.skills import Skill, SkillKind, SkillStore, MutationOperator
from api.routes.skills import (
    _get_skill_store,
    _get_skill_marketplace,
    _get_skill_composer,
    _get_skill_validator,
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def mock_request(temp_db):
    """Create a mock FastAPI request with app state."""
    from core.skills import SkillValidator, SkillComposer, SkillMarketplace

    request = Mock()
    request.app.state = Mock()
    store = SkillStore(db_path=temp_db)
    request.app.state.core_skill_store = store
    request.app.state.skill_validator = SkillValidator()
    request.app.state.skill_composer = SkillComposer()
    request.app.state.skill_marketplace = SkillMarketplace()
    return request


@pytest.fixture
def sample_skill():
    """Create a sample skill for testing."""
    return Skill(
        id="test-skill-1",
        name="Test Skill",
        kind=SkillKind.BUILD,
        version="1.0.0",
        description="A test skill for integration testing",
        domain="customer-support",
        tags=["routing", "keywords"],
        mutations=[
            MutationOperator(
                name="add_keywords",
                description="Add billing keywords",
                target_surface="routing",
                operator_type="append",
            )
        ],
    )


def test_get_skill_store(mock_request):
    """Test getting skill store from request."""
    store = _get_skill_store(mock_request)
    assert isinstance(store, SkillStore)


def test_get_skill_marketplace(mock_request):
    """Test getting skill marketplace from request."""
    marketplace = _get_skill_marketplace(mock_request)
    assert marketplace is not None


def test_get_skill_composer(mock_request):
    """Test getting skill composer from request."""
    composer = _get_skill_composer(mock_request)
    assert composer is not None


def test_get_skill_validator(mock_request):
    """Test getting skill validator from request."""
    validator = _get_skill_validator(mock_request)
    assert validator is not None


def test_skill_crud_operations(mock_request, sample_skill):
    """Test CRUD operations on skills."""
    store = _get_skill_store(mock_request)

    # Create
    skill_id = store.create(sample_skill)
    assert skill_id == sample_skill.id

    # Read
    retrieved = store.get(skill_id)
    assert retrieved is not None
    assert retrieved.name == sample_skill.name
    assert retrieved.version == sample_skill.version

    # Update
    sample_skill.description = "Updated description"
    success = store.update(sample_skill)
    assert success is True

    updated = store.get(skill_id)
    assert updated.description == "Updated description"

    # Delete
    deleted = store.delete(skill_id)
    assert deleted is True

    # Verify deletion
    assert store.get(skill_id) is None


def test_skill_listing_and_filtering(mock_request, sample_skill):
    """Test listing and filtering skills."""
    store = _get_skill_store(mock_request)

    # Create test skills
    skill1 = sample_skill
    store.create(skill1)

    skill2 = Skill(
        id="test-skill-2",
        name="Another Skill",
        kind=SkillKind.RUNTIME,
        version="2.0.0",
        description="A runtime skill",
        domain="sales",
        tags=["order", "lookup"],
    )
    store.create(skill2)

    # List all
    all_skills = store.list()
    assert len(all_skills) >= 2

    # Filter by kind
    build_skills = store.list(kind=SkillKind.BUILD)
    assert all(s.kind == SkillKind.BUILD for s in build_skills)
    assert any(s.id == skill1.id for s in build_skills)

    runtime_skills = store.list(kind=SkillKind.RUNTIME)
    assert all(s.kind == SkillKind.RUNTIME for s in runtime_skills)
    assert any(s.id == skill2.id for s in runtime_skills)

    # Filter by domain
    support_skills = store.list(domain="customer-support")
    assert all(s.domain == "customer-support" for s in support_skills)

    # Filter by tags
    routing_skills = store.list(tags=["routing"])
    assert all("routing" in s.tags for s in routing_skills)


def test_skill_search(mock_request, sample_skill):
    """Test skill search functionality."""
    store = _get_skill_store(mock_request)

    # Create skill
    store.create(sample_skill)

    # Search by name
    results = store.search("Test Skill")
    assert len(results) >= 1
    assert any(s.name == sample_skill.name for s in results)

    # Search by description
    results = store.search("integration testing")
    assert len(results) >= 1

    # Search with kind filter
    results = store.search("test", kind=SkillKind.BUILD)
    assert all(s.kind == SkillKind.BUILD for s in results)


def test_skill_effectiveness_tracking(mock_request, sample_skill):
    """Test effectiveness metrics tracking."""
    store = _get_skill_store(mock_request)

    # Create skill
    store.create(sample_skill)

    # Get initial effectiveness (should be zero)
    effectiveness = store.get_effectiveness(sample_skill.id)
    assert effectiveness.times_applied == 0
    assert effectiveness.success_rate == 0.0

    # Record outcomes
    store.record_outcome(sample_skill.id, improvement=0.15, success=True)
    store.record_outcome(sample_skill.id, improvement=0.10, success=True)
    store.record_outcome(sample_skill.id, improvement=-0.05, success=False)

    # Get updated effectiveness
    effectiveness = store.get_effectiveness(sample_skill.id)
    assert effectiveness.times_applied == 3
    assert effectiveness.success_count == 2
    assert effectiveness.success_rate == pytest.approx(2/3, abs=0.01)
    # Average of successful improvements only: (0.15 + 0.10) / 2 = 0.125
    assert effectiveness.avg_improvement == pytest.approx(0.125, abs=0.01)


def test_skill_validation(mock_request, sample_skill):
    """Test skill validation."""
    validator = _get_skill_validator(mock_request)

    # Validate valid skill
    result = validator.validate_schema(sample_skill)
    assert result.is_valid is True
    assert len(result.errors) == 0

    # Test invalid skill (missing required field)
    invalid_skill = Skill(
        id="",  # Empty ID
        name="Invalid",
        kind=SkillKind.BUILD,
        version="1.0.0",
        description="This skill has an empty ID",
    )
    result = validator.validate_schema(invalid_skill)
    assert result.is_valid is False
    assert len(result.errors) > 0


def test_skill_composition(mock_request, sample_skill):
    """Test skill composition."""
    store = _get_skill_store(mock_request)
    composer = _get_skill_composer(mock_request)

    # Create skills
    skill1 = sample_skill
    store.create(skill1)

    skill2 = Skill(
        id="test-skill-2",
        name="Another Skill",
        kind=SkillKind.BUILD,
        version="1.0.0",
        description="Another test skill",
        domain="customer-support",
    )
    store.create(skill2)

    # Compose skills
    skillset = composer.compose(
        skills=[skill1, skill2],
        store=store,
        name="Test Composition",
        description="Testing skill composition",
    )

    assert skillset.name == "Test Composition"
    assert len(skillset.skills) == 2
    assert skillset.validate() is True


def test_marketplace_browse(mock_request):
    """Test marketplace browsing."""
    marketplace = _get_skill_marketplace(mock_request)

    # Browse all skills (may be empty)
    skills = marketplace.browse()
    assert isinstance(skills, list)

    # Browse with filters
    build_skills = marketplace.browse(kind=SkillKind.BUILD)
    assert isinstance(build_skills, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
