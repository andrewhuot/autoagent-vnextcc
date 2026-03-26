"""Sandbox API endpoints for synthetic conversation generation and stress testing."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from simulator.sandbox import SimulationSandbox

router = APIRouter(prefix="/api/sandbox", tags=["sandbox"])

# In-memory storage for generated conversation sets and results
_conversation_sets: dict[str, list[dict[str, Any]]] = {}
_test_results: dict[str, dict[str, Any]] = {}


class GenerateRequest(BaseModel):
    """Request to generate synthetic conversations."""

    domain: str = Field(..., description="Domain context (e.g., 'customer-support')")
    count: int = Field(100, ge=1, le=10000, description="Number of conversations to generate")
    difficulty_distribution: dict[str, float] | None = Field(
        None, description="Distribution of difficulty levels (normal, edge_case, adversarial)"
    )
    intents: list[str] | None = Field(None, description="List of intents the agent handles")
    tools: list[str] | None = Field(None, description="List of available tools")


class TestRequest(BaseModel):
    """Request to run stress test."""

    config: dict[str, Any] = Field(..., description="Agent configuration to test")
    conversation_set_id: str = Field(..., description="ID of generated conversation set")
    config_id: str = Field("test-config", description="Identifier for the config")


class CompareRequest(BaseModel):
    """Request to A/B compare two configs."""

    config_a: dict[str, Any] = Field(..., description="First configuration")
    config_b: dict[str, Any] = Field(..., description="Second configuration")
    conversation_set_id: str = Field(..., description="ID of generated conversation set")
    config_a_id: str = Field("config-a", description="Identifier for first config")
    config_b_id: str = Field("config-b", description="Identifier for second config")


@router.post("/generate")
async def generate_conversations(request: Request, req: GenerateRequest) -> dict[str, Any]:
    """
    Generate synthetic conversation set.

    Returns:
        conversation_set_id and list of generated conversations
    """
    sandbox = SimulationSandbox(intents=req.intents, tools=req.tools)

    conversations = sandbox.generate_conversations(
        domain=req.domain,
        count=req.count,
        difficulty_distribution=req.difficulty_distribution,
    )

    # Store conversation set
    conversation_set_id = f"convset-{uuid.uuid4().hex[:8]}"
    _conversation_sets[conversation_set_id] = [
        {
            "conversation_id": conv.conversation_id,
            "domain": conv.domain,
            "difficulty": conv.difficulty,
            "persona": conv.persona,
            "user_message": conv.user_message,
            "expected_intent": conv.expected_intent,
            "expected_specialist": conv.expected_specialist,
            "expected_tools": conv.expected_tools,
            "context": conv.context,
        }
        for conv in conversations
    ]

    # Calculate distribution
    difficulty_counts = {"normal": 0, "edge_case": 0, "adversarial": 0}
    for conv in conversations:
        difficulty_counts[conv.difficulty] = difficulty_counts.get(conv.difficulty, 0) + 1

    return {
        "conversation_set_id": conversation_set_id,
        "count": len(conversations),
        "domain": req.domain,
        "difficulty_distribution": {
            k: v / len(conversations) for k, v in difficulty_counts.items()
        },
        "conversations": _conversation_sets[conversation_set_id][:10],  # Preview first 10
    }


@router.get("/conversations/{conversation_set_id}")
async def get_conversation_set(conversation_set_id: str) -> dict[str, Any]:
    """
    Retrieve a generated conversation set.

    Args:
        conversation_set_id: ID of the conversation set

    Returns:
        Full conversation set
    """
    if conversation_set_id not in _conversation_sets:
        raise HTTPException(status_code=404, detail="Conversation set not found")

    conversations = _conversation_sets[conversation_set_id]
    return {
        "conversation_set_id": conversation_set_id,
        "count": len(conversations),
        "conversations": conversations,
    }


@router.post("/test")
async def run_stress_test(request: Request, req: TestRequest) -> dict[str, Any]:
    """
    Run stress test against a config.

    Returns:
        test_id for retrieving results
    """
    if req.conversation_set_id not in _conversation_sets:
        raise HTTPException(status_code=404, detail="Conversation set not found")

    # Convert stored conversations back to SyntheticConversation objects
    from simulator.sandbox import SyntheticConversation

    conversations = [
        SyntheticConversation(
            conversation_id=conv["conversation_id"],
            domain=conv["domain"],
            difficulty=conv["difficulty"],
            persona=conv["persona"],
            user_message=conv["user_message"],
            expected_intent=conv["expected_intent"],
            expected_specialist=conv["expected_specialist"],
            expected_tools=conv["expected_tools"],
            context=conv["context"],
        )
        for conv in _conversation_sets[req.conversation_set_id]
    ]

    sandbox = SimulationSandbox()
    result = sandbox.stress_test(
        config=req.config,
        conversations=conversations,
        config_id=req.config_id,
    )

    # Store result
    _test_results[result.test_id] = {
        "test_id": result.test_id,
        "config_id": result.config_id,
        "total_conversations": result.total_conversations,
        "passed": result.passed,
        "failed": result.failed,
        "pass_rate": result.pass_rate,
        "failures_by_category": result.failures_by_category,
        "failure_examples": result.failure_examples,
        "avg_latency_ms": result.avg_latency_ms,
        "timestamp": result.timestamp,
    }

    return {"test_id": result.test_id, "status": "completed", "results": _test_results[result.test_id]}


@router.post("/compare")
async def compare_configs(request: Request, req: CompareRequest) -> dict[str, Any]:
    """
    A/B compare two configs on same conversation set.

    Returns:
        comparison_id and results
    """
    if req.conversation_set_id not in _conversation_sets:
        raise HTTPException(status_code=404, detail="Conversation set not found")

    # Convert stored conversations back to SyntheticConversation objects
    from simulator.sandbox import SyntheticConversation

    conversations = [
        SyntheticConversation(
            conversation_id=conv["conversation_id"],
            domain=conv["domain"],
            difficulty=conv["difficulty"],
            persona=conv["persona"],
            user_message=conv["user_message"],
            expected_intent=conv["expected_intent"],
            expected_specialist=conv["expected_specialist"],
            expected_tools=conv["expected_tools"],
            context=conv["context"],
        )
        for conv in _conversation_sets[req.conversation_set_id]
    ]

    sandbox = SimulationSandbox()
    result = sandbox.compare(
        config_a=req.config_a,
        config_b=req.config_b,
        conversations=conversations,
        config_a_id=req.config_a_id,
        config_b_id=req.config_b_id,
    )

    # Store result
    comparison_result = {
        "comparison_id": result.comparison_id,
        "config_a_id": result.config_a_id,
        "config_b_id": result.config_b_id,
        "total_conversations": result.total_conversations,
        "config_a_score": result.config_a_score,
        "config_b_score": result.config_b_score,
        "winner": result.winner,
        "score_delta": result.score_delta,
        "category_breakdown": result.category_breakdown,
        "timestamp": result.timestamp,
    }

    _test_results[result.comparison_id] = comparison_result

    return {"comparison_id": result.comparison_id, "status": "completed", "results": comparison_result}


@router.get("/results/{result_id}")
async def get_results(result_id: str) -> dict[str, Any]:
    """
    Get test or comparison results.

    Args:
        result_id: Test ID or comparison ID

    Returns:
        Test or comparison results
    """
    if result_id not in _test_results:
        raise HTTPException(status_code=404, detail="Results not found")

    return _test_results[result_id]
