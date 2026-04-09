"""Curriculum generation API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from optimizer.curriculum_generator import (
    CurriculumGenerator,
    CurriculumStore,
    FailureCluster,
)
from observer.classifier import FailureClassifier
from logger import ConversationStore

router = APIRouter(prefix="/api/curriculum", tags=["curriculum"])


def _get_curriculum_store(request: Request) -> CurriculumStore:
    """Get curriculum store from app state."""
    store = getattr(request.app.state, "curriculum_store", None)
    if store is None:
        store = CurriculumStore(store_dir=".agentlab/curriculum")
        request.app.state.curriculum_store = store
    return store


def _get_conversation_store(request: Request) -> ConversationStore:
    """Get conversation store from app state."""
    store = getattr(request.app.state, "conversation_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Conversation store not configured")
    return store


@router.post("/generate")
async def generate_curriculum(request: Request) -> dict[str, Any]:
    """Generate a new curriculum batch from recent failures.

    Request body:
    {
        "limit": 10,  // max failure clusters to process
        "prompts_per_cluster": 3,  // prompts to generate per cluster
        "adversarial_ratio": 0.2  // ratio of adversarial variants
    }

    Returns:
    {
        "batch_id": "curriculum_abc123",
        "num_prompts": 45,
        "tier_distribution": {"easy": 10, "medium": 15, "hard": 10, "adversarial": 10},
        "source_clusters": ["routing_error", "tool_failure", ...],
        "generated_at": 1234567890.0
    }
    """
    body = await request.json() if request.headers.get("content-length", "0") != "0" else {}

    limit = body.get("limit", 10)
    prompts_per_cluster = body.get("prompts_per_cluster", 3)
    adversarial_ratio = body.get("adversarial_ratio", 0.2)

    # Get conversation store
    conv_store = _get_conversation_store(request)

    # Load recent failures
    recent_failures = conv_store.get_failures(limit=limit * 10)

    if not recent_failures:
        raise HTTPException(status_code=404, detail="No recent failures found")

    # Classify failures into clusters
    classifier = FailureClassifier()
    clusters_map: dict[str, list] = {}
    for record in recent_failures:
        categories = classifier.classify(record)
        for cat in categories:
            if cat not in clusters_map:
                clusters_map[cat] = []
            clusters_map[cat].append({
                "user_message": record.user_message,
                "specialist_used": record.specialist_used,
                "error": record.error_message or "",
            })

    # Convert to FailureCluster objects
    failure_clusters = []
    for family, examples in list(clusters_map.items())[:limit]:
        cluster = FailureCluster(
            failure_family=family,
            count=len(examples),
            examples=examples,
            categories=[family],
            pass_rate=0.5,  # TODO: fetch from eval history
        )
        failure_clusters.append(cluster)

    # Generate curriculum
    generator = CurriculumGenerator(
        prompts_per_cluster=prompts_per_cluster,
        adversarial_ratio=adversarial_ratio,
    )
    batch = generator.generate_curriculum(failure_clusters)

    # Save batch
    curriculum_store = _get_curriculum_store(request)
    curriculum_store.save_batch(batch)

    return {
        "batch_id": batch.batch_id,
        "num_prompts": len(batch.prompts),
        "tier_distribution": batch.tier_distribution,
        "source_clusters": batch.source_clusters,
        "generated_at": batch.generated_at,
    }


@router.get("/batches")
async def list_curriculum_batches(
    request: Request,
    limit: int = 20,
) -> dict[str, Any]:
    """List generated curriculum batches.

    Query params:
    - limit: Maximum number of batches to return (default 20)

    Returns:
    {
        "batches": [
            {
                "batch_id": "curriculum_abc123",
                "generated_at": 1234567890.0,
                "num_prompts": 45,
                "tier_distribution": {...},
                "source_clusters": [...]
            },
            ...
        ],
        "count": 5
    }
    """
    curriculum_store = _get_curriculum_store(request)
    batches = curriculum_store.list_batches(limit=limit)

    return {
        "batches": [
            {
                "batch_id": b.batch_id,
                "generated_at": b.generated_at,
                "num_prompts": len(b.prompts),
                "tier_distribution": b.tier_distribution,
                "source_clusters": b.source_clusters,
            }
            for b in batches
        ],
        "count": len(batches),
    }


@router.get("/batches/{batch_id}")
async def get_curriculum_batch(batch_id: str, request: Request) -> dict[str, Any]:
    """Get details of a specific curriculum batch.

    Returns:
    {
        "batch": {
            "batch_id": "curriculum_abc123",
            "generated_at": 1234567890.0,
            "prompts": [...],
            "tier_distribution": {...},
            "source_clusters": [...]
        }
    }
    """
    curriculum_store = _get_curriculum_store(request)
    batch = curriculum_store.load_batch(batch_id)

    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch not found: {batch_id}")

    return {"batch": batch.to_dict()}


@router.post("/apply")
async def apply_curriculum_batch(request: Request) -> dict[str, Any]:
    """Apply a curriculum batch to the active eval set.

    Request body:
    {
        "batch_id": "curriculum_abc123",
        "eval_cases_dir": "evals/cases"  // optional
    }

    Returns:
    {
        "batch_id": "curriculum_abc123",
        "eval_file": "evals/cases/curriculum_abc123.yaml",
        "num_prompts": 45
    }
    """
    body = await request.json()
    batch_id = body.get("batch_id")
    eval_cases_dir = body.get("eval_cases_dir", "evals/cases")

    if not batch_id:
        raise HTTPException(status_code=400, detail="batch_id is required")

    curriculum_store = _get_curriculum_store(request)
    batch = curriculum_store.load_batch(batch_id)

    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch not found: {batch_id}")

    try:
        eval_file = curriculum_store.apply_batch_to_eval_set(batch_id, eval_cases_dir)
        return {
            "batch_id": batch_id,
            "eval_file": eval_file,
            "num_prompts": len(batch.prompts),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to apply batch: {str(e)}")
