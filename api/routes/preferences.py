"""Preference Collection API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request

router = APIRouter(prefix="/api/preferences", tags=["preferences"])


def _get_pipeline(request: Request):
    pipeline = getattr(request.app.state, "preference_pipeline", None)
    if pipeline is None:
        from optimizer.preference_learning import PreferenceLearningPipeline
        pipeline = PreferenceLearningPipeline()
        request.app.state.preference_pipeline = pipeline
    return pipeline


def _get_store(request: Request):
    """Get or create SQLite-backed preference pair store."""
    store = getattr(request.app.state, "preference_store", None)
    if store is None:
        import sqlite3, json
        conn = sqlite3.connect("preferences.db")
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE IF NOT EXISTS preference_pairs (
                pair_id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'human_review',
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()
        request.app.state.preference_store = conn
        store = conn
    return store


# POST /api/preferences/pairs — submit preference pair
@router.post("/pairs", status_code=201)
async def submit_pair(request: Request, body: dict[str, Any] = Body(...)):
    """Submit a preference pair (chosen vs rejected)."""
    import json, uuid
    from datetime import datetime, timezone
    store = _get_store(request)
    required = {"input_text", "chosen", "rejected"}
    missing = required - set(body.keys())
    if missing:
        raise HTTPException(400, f"Missing: {sorted(missing)}")
    pair_id = str(uuid.uuid4())
    body["pair_id"] = pair_id
    store.execute(
        "INSERT INTO preference_pairs (pair_id, data, source, created_at) VALUES (?, ?, ?, ?)",
        (pair_id, json.dumps(body), body.get("source", "human_review"),
         datetime.now(timezone.utc).isoformat()),
    )
    store.commit()
    return {"ok": True, "pair_id": pair_id}


# GET /api/preferences/pairs — list pairs
@router.get("/pairs")
async def list_pairs(
    request: Request,
    source: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    import json
    store = _get_store(request)
    if source:
        rows = store.execute(
            "SELECT * FROM preference_pairs WHERE source = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (source, limit, offset),
        ).fetchall()
    else:
        rows = store.execute(
            "SELECT * FROM preference_pairs ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return {
        "pairs": [json.loads(r["data"]) for r in rows],
        "count": len(rows),
    }


# GET /api/preferences/stats — collection statistics
@router.get("/stats")
async def get_stats(request: Request):
    store = _get_store(request)
    total = store.execute("SELECT COUNT(*) as cnt FROM preference_pairs").fetchone()["cnt"]
    by_source = store.execute(
        "SELECT source, COUNT(*) as cnt FROM preference_pairs GROUP BY source"
    ).fetchall()
    return {
        "total_pairs": total,
        "by_source": {r["source"]: r["cnt"] for r in by_source},
    }


# POST /api/preferences/export — export dataset
@router.post("/export")
async def export_preferences(request: Request, body: dict[str, Any] = Body(default={})):
    """Export preference pairs as DPO dataset."""
    import json
    store = _get_store(request)
    pipeline = _get_pipeline(request)
    format = body.get("format", "vertex")
    rows = store.execute("SELECT data FROM preference_pairs ORDER BY created_at").fetchall()
    reviews = [json.loads(r["data"]) for r in rows]
    from optimizer.preference_learning import PreferencePair
    pairs = [PreferencePair.from_dict(r) for r in reviews]
    if format == "openai":
        path = pipeline.export_openai_format(pairs)
    else:
        path = pipeline.export_dpo_dataset(pairs, format=format)
    return {"ok": True, "path": path, "format": format, "n_pairs": len(pairs)}
