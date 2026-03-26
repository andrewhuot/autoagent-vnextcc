"""Tests for skills API routes.

Comprehensive test suite for the unified skills API endpoints.
Tests CRUD operations, composition, marketplace, validation, and search.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.server import app
from core.skills import Skill, SkillKind, MutationOperator, ToolDefinition


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def sample_build_skill():
    """Create a sample build-time skill."""
    return Skill(
        id="test-build-skill",
        name="Test Build Skill",
        kind=SkillKind.BUILD,
        version="1.0.0",
        description="A test build-time skill for keyword expansion",
        domain="customer-support",
        tags=["routing", "keywords"],
        mutations=[
            MutationOperator(
                name="add_keywords",
                description="Add billing keywords to routing",
                target_surface="routing",
                operator_type="append",
                template="keywords: ['billing', 'invoice', 'payment']",
            )
        ],
    )


@pytest.fixture
def sample_runtime_skill():
    """Create a sample run-time skill."""
    return Skill(
        id="test-runtime-skill",
        name="Test Runtime Skill",
        kind=SkillKind.RUNTIME,
        version="1.0.0",
        description="A test run-time skill for order lookup",
        domain="customer-support",
        tags=["order", "lookup"],
        tools=[
            ToolDefinition(
                name="lookup_order",
                description="Look up an order by ID",
                parameters={"order_id": {"type": "string", "required": True}},
                sandbox_policy="read_only",
            )
        ],
        instructions="Use lookup_order when customer asks about order status.",
    )


# ---------------------------------------------------------------------------
# CRUD Tests
# ---------------------------------------------------------------------------

def test_create_build_skill(client, sample_build_skill):
    """Test creating a build-time skill."""
    response = client.post(
        "/api/skills",
        json={"skill": sample_build_skill.to_dict()}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["skill_id"] == sample_build_skill.id
    assert "validation" in data
    assert data["validation"]["is_valid"] is True


def test_create_runtime_skill(client, sample_runtime_skill):
    """Test creating a run-time skill."""
    response = client.post(
        "/api/skills",
        json={"skill": sample_runtime_skill.to_dict()}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["skill_id"] == sample_runtime_skill.id
    assert "validation" in data


def test_create_invalid_skill(client):
    """Test creating an invalid skill."""
    response = client.post(
        "/api/skills",
        json={"skill": {"name": "Invalid", "description": "Too short"}}
    )
    assert response.status_code == 400
    assert "validation failed" in response.json()["detail"].lower()


def test_get_skill(client, sample_build_skill):
    """Test retrieving a skill by ID."""
    # Create skill first
    client.post("/api/skills", json={"skill": sample_build_skill.to_dict()})

    # Get skill
    response = client.get(f"/api/skills/{sample_build_skill.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["skill"]["id"] == sample_build_skill.id
    assert data["skill"]["name"] == sample_build_skill.name


def test_get_nonexistent_skill(client):
    """Test retrieving a skill that doesn't exist."""
    response = client.get("/api/skills/nonexistent-skill")
    assert response.status_code == 404


def test_list_skills(client, sample_build_skill, sample_runtime_skill):
    """Test listing all skills."""
    # Create skills
    client.post("/api/skills", json={"skill": sample_build_skill.to_dict()})
    client.post("/api/skills", json={"skill": sample_runtime_skill.to_dict()})

    # List all skills
    response = client.get("/api/skills")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] >= 2
    assert len(data["skills"]) >= 2


def test_list_skills_filtered_by_kind(client, sample_build_skill, sample_runtime_skill):
    """Test listing skills filtered by kind."""
    # Create skills
    client.post("/api/skills", json={"skill": sample_build_skill.to_dict()})
    client.post("/api/skills", json={"skill": sample_runtime_skill.to_dict()})

    # List build skills
    response = client.get("/api/skills?kind=build")
    assert response.status_code == 200
    data = response.json()
    assert all(s["kind"] == "build" for s in data["skills"])

    # List runtime skills
    response = client.get("/api/skills?kind=runtime")
    assert response.status_code == 200
    data = response.json()
    assert all(s["kind"] == "runtime" for s in data["skills"])


def test_list_skills_filtered_by_domain(client, sample_build_skill):
    """Test listing skills filtered by domain."""
    # Create skill
    client.post("/api/skills", json={"skill": sample_build_skill.to_dict()})

    # List by domain
    response = client.get("/api/skills?domain=customer-support")
    assert response.status_code == 200
    data = response.json()
    assert all(s["domain"] == "customer-support" for s in data["skills"])


def test_list_skills_filtered_by_tags(client, sample_build_skill):
    """Test listing skills filtered by tags."""
    # Create skill
    client.post("/api/skills", json={"skill": sample_build_skill.to_dict()})

    # List by tags
    response = client.get("/api/skills?tags=routing,keywords")
    assert response.status_code == 200
    data = response.json()
    # Skills must have ALL specified tags
    for skill in data["skills"]:
        assert "routing" in skill["tags"]
        assert "keywords" in skill["tags"]


def test_update_skill(client, sample_build_skill):
    """Test updating a skill."""
    # Create skill
    client.post("/api/skills", json={"skill": sample_build_skill.to_dict()})

    # Update skill
    updated = sample_build_skill.to_dict()
    updated["description"] = "Updated description for the test skill"
    response = client.put(
        f"/api/skills/{sample_build_skill.id}",
        json={"skill": updated}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True

    # Verify update
    response = client.get(f"/api/skills/{sample_build_skill.id}")
    data = response.json()
    assert data["skill"]["description"] == "Updated description for the test skill"


def test_update_nonexistent_skill(client, sample_build_skill):
    """Test updating a skill that doesn't exist."""
    response = client.put(
        "/api/skills/nonexistent-skill",
        json={"skill": sample_build_skill.to_dict()}
    )
    assert response.status_code == 404


def test_delete_skill(client, sample_build_skill):
    """Test deleting a skill."""
    # Create skill
    client.post("/api/skills", json={"skill": sample_build_skill.to_dict()})

    # Delete skill
    response = client.delete(f"/api/skills/{sample_build_skill.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True

    # Verify deletion
    response = client.get(f"/api/skills/{sample_build_skill.id}")
    assert response.status_code == 404


def test_delete_nonexistent_skill(client):
    """Test deleting a skill that doesn't exist."""
    response = client.delete("/api/skills/nonexistent-skill")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Testing and Validation Tests
# ---------------------------------------------------------------------------

def test_test_skill(client, sample_build_skill):
    """Test running tests on a skill."""
    # Create skill
    client.post("/api/skills", json={"skill": sample_build_skill.to_dict()})

    # Test skill
    response = client.post(f"/api/skills/{sample_build_skill.id}/test")
    assert response.status_code == 200
    data = response.json()
    assert "validation" in data
    assert data["skill_id"] == sample_build_skill.id


def test_test_nonexistent_skill(client):
    """Test running tests on a skill that doesn't exist."""
    response = client.post("/api/skills/nonexistent-skill/test")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Composition Tests
# ---------------------------------------------------------------------------

def test_compose_skills(client, sample_build_skill, sample_runtime_skill):
    """Test composing multiple skills."""
    # Create skills
    client.post("/api/skills", json={"skill": sample_build_skill.to_dict()})
    client.post("/api/skills", json={"skill": sample_runtime_skill.to_dict()})

    # Compose skills
    response = client.post(
        "/api/skills/compose",
        json={
            "skill_ids": [sample_build_skill.id, sample_runtime_skill.id],
            "name": "Test Skill Set",
            "description": "A test composition of skills",
            "resolve_conflicts": True,
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "skillset" in data
    assert data["skillset"]["name"] == "Test Skill Set"
    assert len(data["skillset"]["skills"]) == 2


def test_compose_nonexistent_skill(client, sample_build_skill):
    """Test composing with a skill that doesn't exist."""
    # Create one skill
    client.post("/api/skills", json={"skill": sample_build_skill.to_dict()})

    # Try to compose with nonexistent skill
    response = client.post(
        "/api/skills/compose",
        json={
            "skill_ids": [sample_build_skill.id, "nonexistent-skill"],
            "name": "Test Skill Set",
            "description": "Will fail",
            "resolve_conflicts": True,
        }
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Marketplace Tests
# ---------------------------------------------------------------------------

def test_browse_marketplace(client):
    """Test browsing marketplace skills."""
    response = client.get("/api/skills/marketplace")
    assert response.status_code == 200
    data = response.json()
    assert "skills" in data
    assert "count" in data
    assert "filters" in data


def test_browse_marketplace_filtered(client):
    """Test browsing marketplace with filters."""
    response = client.get("/api/skills/marketplace?kind=build&domain=customer-support")
    assert response.status_code == 200
    data = response.json()
    assert data["filters"]["kind"] == "build"
    assert data["filters"]["domain"] == "customer-support"


def test_install_skill_stub(client):
    """Test installing a skill from marketplace.

    Note: This is a stub test since we don't have actual marketplace content.
    """
    response = client.post(
        "/api/skills/install",
        json={"skill_id": "test-marketplace-skill"}
    )
    # Will likely fail since marketplace is empty, but should handle gracefully
    assert response.status_code in [200, 404, 400]


# ---------------------------------------------------------------------------
# Analytics Tests
# ---------------------------------------------------------------------------

def test_get_effectiveness(client, sample_build_skill):
    """Test getting effectiveness metrics for a skill."""
    # Create skill
    client.post("/api/skills", json={"skill": sample_build_skill.to_dict()})

    # Get effectiveness
    response = client.get(f"/api/skills/{sample_build_skill.id}/effectiveness")
    assert response.status_code == 200
    data = response.json()
    assert "effectiveness" in data
    assert data["skill_id"] == sample_build_skill.id
    # Default metrics should be zero
    assert data["effectiveness"]["times_applied"] == 0
    assert data["effectiveness"]["success_rate"] == 0.0


def test_get_effectiveness_nonexistent_skill(client):
    """Test getting effectiveness for a skill that doesn't exist."""
    response = client.get("/api/skills/nonexistent-skill/effectiveness")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Search Tests
# ---------------------------------------------------------------------------

def test_search_skills(client, sample_build_skill):
    """Test searching skills by text."""
    # Create skill
    client.post("/api/skills", json={"skill": sample_build_skill.to_dict()})

    # Search by name
    response = client.post(
        "/api/skills/search",
        json={"query": "Test Build"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] >= 1
    assert any(s["name"] == sample_build_skill.name for s in data["skills"])


def test_search_skills_with_filters(client, sample_build_skill):
    """Test searching skills with additional filters."""
    # Create skill
    client.post("/api/skills", json={"skill": sample_build_skill.to_dict()})

    # Search with filters
    response = client.post(
        "/api/skills/search",
        json={
            "query": "keyword",
            "kind": "build",
            "domain": "customer-support"
        }
    )
    assert response.status_code == 200
    data = response.json()
    # Should only return build-time customer-support skills matching "keyword"
    for skill in data["skills"]:
        assert skill["kind"] == "build"
        assert skill["domain"] == "customer-support"


# ---------------------------------------------------------------------------
# Extraction Stub Tests
# ---------------------------------------------------------------------------

def test_extract_from_conversation_stub(client):
    """Test conversation extraction endpoint (stub)."""
    response = client.post("/api/skills/from-conversation", json={})
    assert response.status_code == 501  # Not implemented


def test_extract_from_optimization_stub(client):
    """Test optimization extraction endpoint (stub)."""
    response = client.post("/api/skills/from-optimization", json={})
    assert response.status_code == 501  # Not implemented


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------

def test_full_lifecycle(client, sample_build_skill):
    """Test complete skill lifecycle: create, read, update, test, delete."""
    # Create
    response = client.post("/api/skills", json={"skill": sample_build_skill.to_dict()})
    assert response.status_code == 200
    skill_id = response.json()["skill_id"]

    # Read
    response = client.get(f"/api/skills/{skill_id}")
    assert response.status_code == 200
    assert response.json()["skill"]["name"] == sample_build_skill.name

    # Test
    response = client.post(f"/api/skills/{skill_id}/test")
    assert response.status_code == 200

    # Get effectiveness
    response = client.get(f"/api/skills/{skill_id}/effectiveness")
    assert response.status_code == 200

    # Update
    updated = sample_build_skill.to_dict()
    updated["description"] = "Updated lifecycle test skill"
    response = client.put(f"/api/skills/{skill_id}", json={"skill": updated})
    assert response.status_code == 200

    # Delete
    response = client.delete(f"/api/skills/{skill_id}")
    assert response.status_code == 200

    # Verify deletion
    response = client.get(f"/api/skills/{skill_id}")
    assert response.status_code == 404
