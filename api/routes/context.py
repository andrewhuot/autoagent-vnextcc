"""Context Engineering Workbench API endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request

from context.engineering import build_context_preview_from_workspace, context_profiles_payload

router = APIRouter(prefix="/api/context", tags=["context"])


@router.get("/profiles")
async def profiles() -> dict[str, Any]:
    """Return selectable context-engineering profiles for CLI/UI parity."""
    return context_profiles_payload()


@router.post("/preview")
async def preview(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    """Preview the assembled agent context without requiring trace data."""
    try:
        agent_config = body.get("agent_config") if isinstance(body.get("agent_config"), dict) else None
        project_memory = body.get("project_memory") if isinstance(body.get("project_memory"), str) else None
        token_budget = body.get("token_budget") if isinstance(body.get("token_budget"), int) else None
        pro_mode = body.get("pro_mode") if isinstance(body.get("pro_mode"), bool) else None
        config_path = body.get("config_path") if isinstance(body.get("config_path"), str) else None
        profile_name = body.get("profile") or body.get("profile_name")

        preview_result = build_context_preview_from_workspace(
            root=Path.cwd(),
            config_path=config_path,
            profile_name=str(profile_name) if profile_name else None,
            token_budget=token_budget,
            pro_mode=pro_mode,
            agent_config=agent_config,
            project_memory_text=project_memory,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return preview_result.to_dict()


@router.get("/analysis/{trace_id}")
async def analyze_trace(trace_id: str, request: Request) -> dict[str, Any]:
    """Context analysis for a specific trace."""
    analyzer = request.app.state.context_analyzer
    trace_store = request.app.state.trace_store

    events = trace_store.get_trace(trace_id=trace_id)
    if not events:
        raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")

    # Convert TraceEvent objects to dicts for analyzer
    event_dicts = []
    for e in events:
        event_dicts.append({
            "event_type": e.event_type.value if hasattr(e.event_type, "value") else str(e.event_type),
            "tokens_in": e.tokens_in,
            "tokens_out": e.tokens_out,
            "error_message": e.error_message,
            "metadata": e.metadata if isinstance(e.metadata, dict) else {},
        })

    analysis = analyzer.analyze_trace(event_dicts)
    return analysis.to_dict()


@router.post("/simulate")
async def simulate(
    request: Request,
    body: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Run compaction simulation on a trace or custom snapshots."""
    from context.simulator import CompactionSimulator, CompactionStrategy
    from context.analyzer import ContextSnapshot

    simulator = CompactionSimulator()

    strategy_data = body.get("strategy")
    if isinstance(strategy_data, dict):
        strategy = CompactionStrategy(
            name=strategy_data.get("name", "custom"),
            description=strategy_data.get("description", "Custom strategy"),
            max_tokens=strategy_data.get("max_tokens", 16000),
            compaction_trigger=strategy_data.get("compaction_trigger", 0.85),
            retention_ratio=strategy_data.get("retention_ratio", 0.6),
        )
    elif isinstance(strategy_data, str):
        strategy_aliases = {
            "truncate_tail": "aggressive",
            "sliding_window": "conservative",
            "summarize": "balanced",
        }
        strategies = {strategy.name: strategy for strategy in simulator.default_strategies()}
        strategy = strategies.get(strategy_aliases.get(strategy_data, strategy_data), simulator.default_strategies()[1])
    else:
        strategy = simulator.default_strategies()[1]  # balanced

    snapshots_data = body.get("snapshots", [])
    snapshots = [
        ContextSnapshot(
            turn_number=s.get("turn_number", i),
            tokens_used=s.get("tokens_used", 0),
            tokens_available=s.get("tokens_available", 32000),
            event_type=s.get("event_type", "model_call"),
            agent_path=s.get("agent_path", "/"),
            metadata={},
        )
        for i, s in enumerate(snapshots_data)
    ]

    if not snapshots:
        # Use default strategies comparison with empty snapshots
        results = simulator.compare_strategies(snapshots, simulator.default_strategies())
    else:
        result = simulator.simulate(snapshots, strategy)
        results = [result]

    return {
        "results": [r.to_dict() for r in results],
        "count": len(results),
    }


@router.get("/report")
async def report(request: Request) -> dict[str, Any]:
    """Aggregate context health report.

    Returns aggregate metrics across analyzed traces. When no trace analyses
    have been performed, returns defaults with a guidance note.
    """

    # TODO: Aggregate from stored per-trace analyses when a trace store is available.
    # Currently returns defaults — per-trace analysis via /api/context/analysis/{id} is
    # the functional path for context insights.
    return {
        "utilization_ratio": 0.0,
        "compaction_loss": 0.0,
        "avg_handoff_fidelity": 0.0,
        "memory_staleness": 0.0,
        "status": "no_data",
        "recommendations": [],
        "note": "No trace analyses available for aggregation. Use GET /api/context/analysis/{trace_id} to analyze individual traces first.",
    }
