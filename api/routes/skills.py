"""Skills API routes - unified build-time and run-time skills management.

This module provides comprehensive REST API for the core.skills system:
- CRUD operations for skills with versioning
- Skill composition and dependency resolution
- Marketplace integration for discovery and installation
- Validation and testing
- Effectiveness metrics and analytics
- Search and filtering

All endpoints use core.skills.SkillStore as the backend.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from api.models import (
    SkillCreateRequest,
    SkillUpdateRequest,
    SkillComposeRequest,
    SkillInstallRequest,
    SkillSearchRequest,
)
from core.skills import (
    Skill,
    SkillKind,
    SkillStore,
    SkillComposer,
    SkillMarketplace,
    SkillValidator,
    ValidationResult,
)

router = APIRouter(prefix="/api/skills", tags=["skills"])


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _get_skill_store(request: Request) -> SkillStore:
    """Get the skill store from app state.

    Note: This gets the core.skills.SkillStore, NOT the registry.skill_store
    which is for executable skills. The core.skills system is the unified
    build-time + run-time skill management layer.
    """
    # For now, create a store on demand. In production, initialize in lifespan.
    # TODO: Add to api.server.py lifespan as app.state.core_skill_store
    store = getattr(request.app.state, "core_skill_store", None)
    if store is None:
        store = SkillStore(db_path=".autoagent/core_skills.db")
        request.app.state.core_skill_store = store
    return store


def _get_skill_marketplace(request: Request) -> SkillMarketplace:
    """Get the skill marketplace from app state."""
    marketplace = getattr(request.app.state, "skill_marketplace", None)
    if marketplace is None:
        marketplace = SkillMarketplace()
        request.app.state.skill_marketplace = marketplace
    return marketplace


def _get_skill_composer(request: Request) -> SkillComposer:
    """Get the skill composer from app state."""
    composer = getattr(request.app.state, "skill_composer", None)
    if composer is None:
        composer = SkillComposer()
        request.app.state.skill_composer = composer
    return composer


def _get_skill_validator(request: Request) -> SkillValidator:
    """Get the skill validator from app state."""
    validator = getattr(request.app.state, "skill_validator", None)
    if validator is None:
        validator = SkillValidator()
        request.app.state.skill_validator = validator
    return validator


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_skills(
    request: Request,
    kind: str | None = Query(None, description="Filter by kind: build or runtime"),
    domain: str | None = Query(None, description="Filter by domain"),
    tags: str | None = Query(None, description="Comma-separated tags (must have ALL)"),
    status: str | None = Query(None, description="Filter by status: active, draft, deprecated"),
) -> dict[str, Any]:
    """List all skills with optional filters.

    Returns skills sorted by most recently updated first.
    All filters are AND-ed together.

    Query Parameters:
        kind: Filter by skill kind (build/runtime)
        domain: Filter by domain (e.g., customer-support, sales)
        tags: Comma-separated tags - skill must have ALL tags
        status: Filter by status (active, draft, deprecated)

    Returns:
        {
            "skills": [skill_dict, ...],
            "count": int,
            "filters": {...}
        }
    """
    store = _get_skill_store(request)

    # Parse kind
    kind_enum = None
    if kind:
        try:
            kind_enum = SkillKind.BUILD if kind.lower() == "build" else SkillKind.RUNTIME
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid kind: {kind}. Must be 'build' or 'runtime'"
            )

    # Parse tags
    tags_list = None
    if tags:
        tags_list = [t.strip() for t in tags.split(",") if t.strip()]

    skills = store.list(
        kind=kind_enum,
        domain=domain,
        tags=tags_list,
        status=status,
    )

    return {
        "skills": [s.to_dict() for s in skills],
        "count": len(skills),
        "filters": {
            "kind": kind,
            "domain": domain,
            "tags": tags_list,
            "status": status,
        }
    }


@router.get("/{skill_id}")
async def get_skill(
    request: Request,
    skill_id: str,
) -> dict[str, Any]:
    """Get a specific skill by ID.

    Args:
        skill_id: The unique skill identifier

    Returns:
        {"skill": skill_dict}

    Raises:
        HTTPException: 404 if skill not found
    """
    store = _get_skill_store(request)
    skill = store.get(skill_id)

    if skill is None:
        raise HTTPException(
            status_code=404,
            detail=f"Skill not found: {skill_id}"
        )

    return {"skill": skill.to_dict()}


@router.post("")
async def create_skill(
    request: Request,
    body: SkillCreateRequest,
) -> dict[str, Any]:
    """Create a new skill.

    Validates the skill schema before creation.

    Request Body:
        skill: Skill definition as dict (see core.skills.Skill)

    Returns:
        {
            "skill_id": str,
            "message": str,
            "validation": ValidationResult
        }

    Raises:
        HTTPException: 400 if validation fails or skill already exists
    """
    store = _get_skill_store(request)
    validator = _get_skill_validator(request)

    try:
        # Parse skill from dict
        skill = Skill.from_dict(body.skill)
    except (KeyError, ValueError) as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid skill definition: {str(e)}"
        )

    # Validate schema
    validation = validator.validate_schema(skill)
    if not validation.is_valid:
        raise HTTPException(
            status_code=400,
            detail=f"Skill validation failed: {', '.join(validation.errors)}"
        )

    # Create skill
    try:
        skill_id = store.create(skill)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "skill_id": skill_id,
        "message": f"Skill '{skill.name}' created successfully",
        "validation": validation.to_dict(),
    }


@router.put("/{skill_id}")
async def update_skill(
    request: Request,
    skill_id: str,
    body: SkillUpdateRequest,
) -> dict[str, Any]:
    """Update an existing skill.

    Validates the updated skill schema.

    Args:
        skill_id: The skill ID to update

    Request Body:
        skill: Updated skill definition as dict

    Returns:
        {
            "success": bool,
            "message": str,
            "validation": ValidationResult
        }

    Raises:
        HTTPException: 400 if validation fails, 404 if skill not found
    """
    store = _get_skill_store(request)
    validator = _get_skill_validator(request)

    # Verify skill exists
    existing = store.get(skill_id)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail=f"Skill not found: {skill_id}"
        )

    try:
        # Parse updated skill
        skill = Skill.from_dict(body.skill)
        # Ensure ID matches
        skill.id = skill_id
    except (KeyError, ValueError) as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid skill definition: {str(e)}"
        )

    # Validate schema
    validation = validator.validate_schema(skill)
    if not validation.is_valid:
        raise HTTPException(
            status_code=400,
            detail=f"Skill validation failed: {', '.join(validation.errors)}"
        )

    # Update skill
    success = store.update(skill)

    return {
        "success": success,
        "message": f"Skill '{skill.name}' updated successfully",
        "validation": validation.to_dict(),
    }


@router.delete("/{skill_id}")
async def delete_skill(
    request: Request,
    skill_id: str,
) -> dict[str, Any]:
    """Delete a skill by ID.

    This cascades to all effectiveness tracking data.

    Args:
        skill_id: The skill ID to delete

    Returns:
        {
            "success": bool,
            "message": str,
            "skill_id": str
        }

    Raises:
        HTTPException: 404 if skill not found
    """
    store = _get_skill_store(request)

    # Verify skill exists
    skill = store.get(skill_id)
    if skill is None:
        raise HTTPException(
            status_code=404,
            detail=f"Skill not found: {skill_id}"
        )

    # Delete skill
    success = store.delete(skill_id)

    return {
        "success": success,
        "message": f"Skill '{skill.name}' deleted successfully",
        "skill_id": skill_id,
    }


# ---------------------------------------------------------------------------
# Testing and validation
# ---------------------------------------------------------------------------

@router.post("/{skill_id}/test")
async def test_skill(
    request: Request,
    skill_id: str,
) -> dict[str, Any]:
    """Run tests for a skill.

    Executes all test cases defined in the skill and returns results.
    For build-time skills, validates mutations and triggers.
    For run-time skills, executes test cases.

    Args:
        skill_id: The skill ID to test

    Returns:
        {
            "skill_id": str,
            "validation": ValidationResult with test results
        }

    Raises:
        HTTPException: 404 if skill not found
    """
    store = _get_skill_store(request)
    validator = _get_skill_validator(request)

    # Get skill
    skill = store.get(skill_id)
    if skill is None:
        raise HTTPException(
            status_code=404,
            detail=f"Skill not found: {skill_id}"
        )

    # Validate skill
    validation = validator.validate(skill)

    return {
        "skill_id": skill_id,
        "skill_name": skill.name,
        "validation": validation.to_dict(),
    }


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

@router.post("/compose")
async def compose_skills(
    request: Request,
    body: SkillComposeRequest,
) -> dict[str, Any]:
    """Compose multiple skills into a skill set.

    Resolves dependencies, detects conflicts, and creates an ordered skill set.

    Request Body:
        skill_ids: List of skill IDs to compose
        name: Name for the composed skill set
        description: Description of the skill set
        resolve_conflicts: Whether to attempt automatic conflict resolution

    Returns:
        {
            "skillset": SkillSet dict,
            "valid": bool,
            "conflicts": [conflict_dict, ...],
            "message": str
        }

    Raises:
        HTTPException: 400 if composition fails with unresolvable conflicts
    """
    store = _get_skill_store(request)
    composer = _get_skill_composer(request)

    # Load skills by IDs
    skills: list[Skill] = []
    for skill_id in body.skill_ids:
        skill = store.get(skill_id)
        if skill is None:
            raise HTTPException(
                status_code=404,
                detail=f"Skill not found: {skill_id}"
            )
        skills.append(skill)

    try:
        # Compose skills
        skillset = composer.compose(
            skills=skills,
            store=store,
            name=body.name,
            description=body.description,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Composition failed: {str(e)}"
        )

    # Check if valid
    is_valid = skillset.validate()

    if not is_valid and not body.resolve_conflicts:
        raise HTTPException(
            status_code=400,
            detail=f"Skill set has unresolved conflicts. Set resolve_conflicts=true to attempt resolution."
        )

    return {
        "skillset": skillset.to_dict(),
        "valid": is_valid,
        "conflicts": [c.to_dict() for c in skillset.conflicts],
        "message": f"Composed {len(skillset.skills)} skills into '{body.name}'"
    }


# ---------------------------------------------------------------------------
# Marketplace
# ---------------------------------------------------------------------------

@router.get("/marketplace")
async def browse_marketplace(
    request: Request,
    kind: str | None = Query(None, description="Filter by kind: build or runtime"),
    domain: str | None = Query(None, description="Filter by domain"),
    tags: str | None = Query(None, description="Comma-separated tags"),
) -> dict[str, Any]:
    """Browse available skills in the marketplace.

    Returns skill metadata (not full definitions) for efficient browsing.

    Query Parameters:
        kind: Filter by skill kind (build/runtime)
        domain: Filter by domain
        tags: Comma-separated tags (skill must have at least ONE)

    Returns:
        {
            "skills": [metadata_dict, ...],
            "count": int,
            "filters": {...}
        }
    """
    marketplace = _get_skill_marketplace(request)

    # Parse kind
    kind_enum = None
    if kind:
        try:
            kind_enum = SkillKind.BUILD if kind.lower() == "build" else SkillKind.RUNTIME
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid kind: {kind}. Must be 'build' or 'runtime'"
            )

    # Parse tags
    tags_list = None
    if tags:
        tags_list = [t.strip() for t in tags.split(",") if t.strip()]

    skills = marketplace.browse(
        kind=kind_enum,
        domain=domain,
        tags=tags_list,
    )

    return {
        "skills": skills,
        "count": len(skills),
        "filters": {
            "kind": kind,
            "domain": domain,
            "tags": tags_list,
        }
    }


@router.post("/install")
async def install_skill(
    request: Request,
    body: SkillInstallRequest,
) -> dict[str, Any]:
    """Install a skill from the marketplace.

    Downloads the skill from the marketplace and installs it into the local store.
    Source can be:
    - Skill ID in marketplace (e.g., "keyword_expansion")
    - URL to YAML file (e.g., "https://example.com/skills/my_skill.yaml")
    - Local file path (e.g., "/path/to/skill.yaml")

    Request Body:
        skill_id: Marketplace skill ID, URL, or file path

    Returns:
        {
            "success": bool,
            "skill_id": str,
            "skill_name": str,
            "version": str,
            "message": str
        }

    Raises:
        HTTPException: 404 if skill not found in marketplace, 400 if installation fails
    """
    from core.skills.marketplace import MarketplaceError

    marketplace = _get_skill_marketplace(request)
    store = _get_skill_store(request)

    try:
        # Install from marketplace (supports ID, URL, or file path)
        skill = marketplace.install(body.skill_id, store)
    except MarketplaceError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        else:
            raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Skill not found: {body.skill_id}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Installation failed: {str(e)}"
        )

    return {
        "success": True,
        "skill_id": skill.id,
        "skill_name": skill.name,
        "version": skill.version,
        "message": f"Installed '{skill.name}' v{skill.version}"
    }


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

@router.get("/{skill_id}/effectiveness")
async def get_effectiveness(
    request: Request,
    skill_id: str,
) -> dict[str, Any]:
    """Get effectiveness metrics for a skill.

    Returns historical performance data including:
    - Times applied
    - Success rate
    - Average improvement
    - Total improvement
    - Last applied timestamp

    Args:
        skill_id: The skill ID

    Returns:
        {
            "skill_id": str,
            "skill_name": str,
            "effectiveness": EffectivenessMetrics dict
        }

    Raises:
        HTTPException: 404 if skill not found
    """
    store = _get_skill_store(request)

    # Get skill
    skill = store.get(skill_id)
    if skill is None:
        raise HTTPException(
            status_code=404,
            detail=f"Skill not found: {skill_id}"
        )

    # Get effectiveness metrics
    effectiveness = store.get_effectiveness(skill_id)

    return {
        "skill_id": skill_id,
        "skill_name": skill.name,
        "effectiveness": effectiveness.to_dict(),
    }


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@router.post("/search")
async def search_skills(
    request: Request,
    body: SkillSearchRequest,
) -> dict[str, Any]:
    """Search skills by text query.

    Searches across skill name, description, capabilities, and tags.

    Request Body:
        query: Search query text
        kind: Optional filter by kind (build/runtime)
        domain: Optional filter by domain
        tags: Optional comma-separated tags filter

    Returns:
        {
            "skills": [skill_dict, ...],
            "count": int,
            "query": str
        }
    """
    store = _get_skill_store(request)

    # Parse kind
    kind_enum = None
    if body.kind:
        try:
            kind_enum = SkillKind.BUILD if body.kind.lower() == "build" else SkillKind.RUNTIME
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid kind: {body.kind}. Must be 'build' or 'runtime'"
            )

    # Search skills
    skills = store.search(
        query=body.query,
        kind=kind_enum,
    )

    # Apply additional filters if specified
    if body.domain:
        skills = [s for s in skills if s.domain == body.domain]

    if body.tags:
        tags_list = [t.strip() for t in body.tags.split(",") if t.strip()]
        skills = [s for s in skills if any(tag in s.tags for tag in tags_list)]

    return {
        "skills": [s.to_dict() for s in skills],
        "count": len(skills),
        "query": body.query,
    }


# ---------------------------------------------------------------------------
# Extraction stubs (for future implementation)
# ---------------------------------------------------------------------------

@router.post("/from-conversation")
async def extract_from_conversation(
    request: Request,
) -> dict[str, Any]:
    """Extract a skill from a conversation.

    STUB: Not yet implemented.

    This will analyze a conversation and extract a reusable skill pattern.
    """
    raise HTTPException(
        status_code=501,
        detail="Skill extraction from conversations not yet implemented"
    )


@router.post("/from-optimization")
async def extract_from_optimization(
    request: Request,
) -> dict[str, Any]:
    """Extract a skill from an optimization cycle.

    STUB: Not yet implemented.

    This will analyze a successful optimization and extract it as a reusable skill.
    """
    raise HTTPException(
        status_code=501,
        detail="Skill extraction from optimizations not yet implemented"
    )
