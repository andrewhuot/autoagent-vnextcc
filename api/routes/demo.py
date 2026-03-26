"""Demo scenario API endpoints for internal dogfooding."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.get("/status")
async def get_demo_status(request: Request) -> dict:
    """Check if demo data exists in the system."""
    conversation_store = request.app.state.conversation_store

    # Check if we have demo conversations
    with sqlite3.connect(conversation_store.db_path) as conn:
        cursor = conn.execute("SELECT COUNT(*) FROM conversations")
        count = cursor.fetchone()[0]

    has_demo_data = count > 0

    return {
        "has_demo_data": has_demo_data,
        "conversation_count": count,
        "scenario": "vp_ecommerce_bot" if has_demo_data else None,
    }


@router.get("/scenario")
async def get_demo_scenario(request: Request) -> dict:
    """Get information about the VP demo scenario."""
    from evals.vp_demo_data import get_vp_demo_summary

    summary = get_vp_demo_summary()

    return {
        "name": "E-commerce Support Bot Optimization",
        "description": "Real-world optimization journey: fixing routing errors, safety violations, and latency issues in a customer support bot",
        "journey": {
            "initial_health": 0.62,
            "final_health": 0.87,
            "improvement": 0.25,
            "cycles": 5,
        },
        "acts": [
            {
                "act": 1,
                "title": "Discovery",
                "description": "Analyze 41 real conversations and identify failure patterns",
                "metrics": {
                    "billing_misroutes": 15,
                    "safety_violations": 3,
                    "high_latency": 8,
                    "quality_issues": 5,
                },
            },
            {
                "act": 2,
                "title": "Diagnosis",
                "description": "AutoAgent identifies routing keywords as the dominant failure family",
                "insight": "15 billing-related queries routed to tech_support_agent due to missing keyword mappings",
            },
            {
                "act": 3,
                "title": "Fix Routing",
                "description": "Add billing keywords (invoice, charge, refund, payment) to routing rules",
                "improvement": "+18% health (0.62 → 0.80)",
            },
            {
                "act": 4,
                "title": "Fix Safety",
                "description": "Tighten guardrails to prevent internal pricing disclosure",
                "improvement": "+5% health (0.80 → 0.85)",
            },
            {
                "act": 5,
                "title": "Fix Latency",
                "description": "Optimize order_lookup tool with caching and parallel fetching",
                "improvement": "+2% health (0.85 → 0.87)",
            },
        ],
        "summary": summary,
    }


@router.get("/stream")
async def run_demo_optimization(request: Request) -> StreamingResponse:
    """Server-Sent Events stream for running the VP demo optimization cycle.

    Yields events for each act of the optimization journey:
    - act_start: Beginning of an optimization act
    - diagnosis: Failure analysis and dominant pattern identification
    - proposal: Proposed configuration change
    - evaluation: Before/after metrics
    - decision: Accept/reject decision with statistical significance
    - act_complete: Summary of the act
    - demo_complete: Final summary of the entire journey
    """

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events for the VP demo optimization journey."""

        # Act 1: Discovery
        yield f"event: act_start\ndata: {json.dumps({'act': 1, 'title': 'Discovery', 'description': 'Analyzing 41 conversations...'})}\n\n"
        await asyncio.sleep(1.0)

        diagnosis_1 = {
            'failure_buckets': {
                'routing_error': 15,
                'safety_violation': 3,
                'high_latency': 8,
                'quality_issue': 5,
            },
            'dominant': 'routing_error',
            'total_failures': 31,
            'insight': '15 billing queries misrouted to tech_support_agent',
        }
        yield f"event: diagnosis\ndata: {json.dumps(diagnosis_1)}\n\n"
        await asyncio.sleep(1.5)

        yield f"event: act_complete\ndata: {json.dumps({'act': 1, 'message': 'Discovery complete: 31 failures identified across 4 families'})}\n\n"
        await asyncio.sleep(0.5)

        # Act 2: Diagnosis
        yield f"event: act_start\ndata: {json.dumps({'act': 2, 'title': 'Diagnosis', 'description': 'Identifying root causes...'})}\n\n"
        await asyncio.sleep(1.0)

        diagnosis_2 = {
            'pattern': 'routing_error',
            'root_cause': 'Missing billing keywords in router configuration',
            'examples': [
                'invoice → tech_support',
                'charge → tech_support',
                'refund → tech_support',
            ],
        }
        yield f"event: diagnosis\ndata: {json.dumps(diagnosis_2)}\n\n"
        await asyncio.sleep(1.5)

        yield f"event: act_complete\ndata: {json.dumps({'act': 2, 'message': 'Root cause identified: missing billing keywords'})}\n\n"
        await asyncio.sleep(0.5)

        # Act 3: Fix Routing
        yield f"event: act_start\ndata: {json.dumps({'act': 3, 'title': 'Fix Routing', 'description': 'Adding billing keywords to router...'})}\n\n"
        await asyncio.sleep(1.0)

        proposal_3 = {
            'change_description': 'Add billing keywords (invoice, charge, refund, payment, billing) to routing rules',
            'config_section': 'router.intent_classifier.billing_keywords',
            'reasoning': 'All 15 misroutes involve billing-related queries. Adding these keywords should route them to billing_agent.',
        }
        yield f"event: proposal\ndata: {json.dumps(proposal_3)}\n\n"
        await asyncio.sleep(1.5)

        eval_3 = {
            'score_before': 0.62,
            'score_after': 0.80,
            'improvement': 0.18,
            'billing_accuracy': '100% (15/15 now routed correctly)',
        }
        yield f"event: evaluation\ndata: {json.dumps(eval_3)}\n\n"
        await asyncio.sleep(1.5)

        decision_3 = {
            'accepted': True,
            'p_value': 0.001,
            'effect_size': 2.8,
            'message': 'Highly significant improvement — accepting change',
        }
        yield f"event: decision\ndata: {json.dumps(decision_3)}\n\n"
        await asyncio.sleep(1.0)

        yield f"event: act_complete\ndata: {json.dumps({'act': 3, 'message': 'Routing fixed: +18% health score', 'new_score': 0.80})}\n\n"
        await asyncio.sleep(0.5)

        # Act 4: Fix Safety
        yield f"event: act_start\ndata: {json.dumps({'act': 4, 'title': 'Fix Safety', 'description': 'Tightening safety guardrails...'})}\n\n"
        await asyncio.sleep(1.0)

        proposal_4 = {
            'change_description': 'Add guardrail to prevent disclosure of internal pricing tiers and margins',
            'config_section': 'safety.content_filters.pricing_disclosure',
            'reasoning': '3 conversations leaked internal pricing structure. Guardrail will block this sensitive data.',
        }
        yield f"event: proposal\ndata: {json.dumps(proposal_4)}\n\n"
        await asyncio.sleep(1.5)

        eval_4 = {
            'score_before': 0.80,
            'score_after': 0.85,
            'improvement': 0.05,
            'safety_violations': '0 (down from 3)',
        }
        yield f"event: evaluation\ndata: {json.dumps(eval_4)}\n\n"
        await asyncio.sleep(1.5)

        decision_4 = {
            'accepted': True,
            'p_value': 0.02,
            'effect_size': 1.2,
            'message': 'Significant improvement — accepting change',
        }
        yield f"event: decision\ndata: {json.dumps(decision_4)}\n\n"
        await asyncio.sleep(1.0)

        yield f"event: act_complete\ndata: {json.dumps({'act': 4, 'message': 'Safety violations eliminated: +5% health', 'new_score': 0.85})}\n\n"
        await asyncio.sleep(0.5)

        # Act 5: Fix Latency
        yield f"event: act_start\ndata: {json.dumps({'act': 5, 'title': 'Fix Latency', 'description': 'Optimizing order_lookup performance...'})}\n\n"
        await asyncio.sleep(1.0)

        proposal_5 = {
            'change_description': 'Add caching layer to order_lookup tool and enable parallel fetching',
            'config_section': 'tools.order_lookup.optimization',
            'reasoning': '8 conversations experienced 7-9s latency. Caching and parallelization should reduce to <2s.',
        }
        yield f"event: proposal\ndata: {json.dumps(proposal_5)}\n\n"
        await asyncio.sleep(1.5)

        eval_5 = {
            'score_before': 0.85,
            'score_after': 0.87,
            'improvement': 0.02,
            'avg_latency': '1.2s (down from 4.5s)',
        }
        yield f"event: evaluation\ndata: {json.dumps(eval_5)}\n\n"
        await asyncio.sleep(1.5)

        decision_5 = {
            'accepted': True,
            'p_value': 0.04,
            'effect_size': 0.9,
            'message': 'Marginal but meaningful improvement — accepting change',
        }
        yield f"event: decision\ndata: {json.dumps(decision_5)}\n\n"
        await asyncio.sleep(1.0)

        yield f"event: act_complete\ndata: {json.dumps({'act': 5, 'message': 'Latency optimized: +2% health', 'new_score': 0.87})}\n\n"
        await asyncio.sleep(0.5)

        # Final summary
        final = {
            'acts': 5,
            'baseline': 0.62,
            'final': 0.87,
            'improvement': 0.25,
            'percentage_improvement': 40.3,
            'fixes': [
                'Added billing keyword routing',
                'Prevented pricing disclosure',
                'Optimized order_lookup latency',
            ],
            'message': '🎉 Demo complete! Health improved from 0.62 → 0.87 (+40%)',
        }
        yield f"event: demo_complete\ndata: {json.dumps(final)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
