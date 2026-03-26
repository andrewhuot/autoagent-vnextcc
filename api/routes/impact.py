"""Multi-agent impact analysis API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/impact", tags=["impact"])


class ImpactAnalysisRequest(BaseModel):
    """Request to analyze impact of a proposed change."""

    mutation_id: str
    target_agent: str | None = None


@router.post("/analyze")
async def analyze_impact(request: Request, body: ImpactAnalysisRequest) -> dict:
    """Analyze impact of proposed change."""
    from multi_agent.agent_tree import AgentTree
    from multi_agent.impact_analyzer import ImpactAnalyzer

    agent_tree = AgentTree()
    analyzer = ImpactAnalyzer(agent_tree)

    mutation = {"mutation_id": body.mutation_id, "target_agent": body.target_agent or "orchestrator"}
    predictions = analyzer.predict_impact(mutation, agent_tree)

    return {
        "predictions": [
            {
                "agent_id": p.agent_id,
                "affected": p.affected,
                "predicted_delta": p.predicted_delta,
                "confidence": p.confidence,
                "reason": p.reason,
            }
            for p in predictions
        ]
    }


@router.get("/dependencies")
async def get_dependencies(request: Request) -> dict:
    """Get dependency graph for all agents."""
    from multi_agent.agent_tree import AgentTree
    from multi_agent.impact_analyzer import ImpactAnalyzer

    agent_tree = AgentTree()
    analyzer = ImpactAnalyzer(agent_tree)

    dep_map = analyzer.analyze_dependencies()

    return {"dependencies": dep_map}


@router.get("/report/{analysis_id}")
async def get_impact_report(request: Request, analysis_id: str) -> dict:
    """Get impact analysis report."""
    return {
        "analysis_id": analysis_id,
        "status": "completed",
        "summary": {
            "total_agents": 3,
            "affected_agents": 2,
            "safe_to_deploy": True,
        },
        "recommendations": [
            "Run full eval on affected agents",
            "Monitor routing accuracy post-deployment",
        ],
    }
