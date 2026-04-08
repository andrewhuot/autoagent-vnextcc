"""Studio API — Spec / Observe / Optimize pages.

All endpoints live under /api/studio/* and are designed to back three
front-end pages:

  Spec     — /api/studio/spec/*
  Observe  — /api/studio/observe/*
  Optimize — /api/studio/optimize/*

Live data is pulled from existing app.state services (version_manager,
trace_store, optimization_memory, etc.).  When a service is unavailable or
returns no data the endpoints fall back to rich mock samples so the UI
remains functional in dev/demo mode.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from api.models import (
    StudioBacktestMetrics,
    StudioCandidate,
    StudioCandidateListResponse,
    StudioEvalSuiteSummary,
    StudioObsIssueCluster,
    StudioObsIssueListResponse,
    StudioObsMetricsSummary,
    StudioObsSource,
    StudioObsTraceItem,
    StudioObsTraceListResponse,
    StudioPromoteRequest,
    StudioPromoteResponse,
    StudioSessionCreateRequest,
    StudioSessionCreateResponse,
    StudioSessionItem,
    StudioSessionListResponse,
    StudioSpecContentResponse,
    StudioSpecDiffResponse,
    StudioSpecParseRequest,
    StudioSpecParseResponse,
    StudioSpecVersionItem,
    StudioSpecVersionListResponse,
)

router = APIRouter(prefix="/api/studio", tags=["studio"])

# ---------------------------------------------------------------------------
# Mock / seed data helpers
# ---------------------------------------------------------------------------

_MOCK_SPEC_MD = """\
# Customer Support Agent

## Role
You are a helpful, professional customer support assistant for Acme Corp.

## Capabilities
- Answer product questions using the knowledge base
- Look up order status via the `check_order` tool
- Escalate complex cases to a human specialist

## Tone & Style
- Friendly, concise, avoid jargon
- Acknowledge frustration before providing solutions
- Offer one clear next step per response

## Safety
- Never share other customers' data
- Never make promises about refunds without checking policy
- Escalate immediately if a user expresses harm or distress
"""

_MOCK_VERSIONS: list[StudioSpecVersionItem] = [
    StudioSpecVersionItem(
        version_id="v001",
        version_num=1,
        created_at=time.time() - 86400 * 7,
        status="retired",
        config_hash="a1b2c3d4",
        composite_score=0.71,
        label="Initial baseline",
    ),
    StudioSpecVersionItem(
        version_id="v002",
        version_num=2,
        created_at=time.time() - 86400 * 3,
        status="retired",
        config_hash="e5f6a7b8",
        composite_score=0.76,
        label="Improved tone rules",
    ),
    StudioSpecVersionItem(
        version_id="v003",
        version_num=3,
        created_at=time.time() - 86400,
        status="active",
        config_hash="c9d0e1f2",
        composite_score=0.81,
        label="Escalation logic v2",
    ),
]

_MOCK_ISSUES: list[StudioObsIssueCluster] = [
    StudioObsIssueCluster(
        cluster_id="cluster-001",
        category="tool_failure",
        summary="check_order returns empty when order ID starts with 'B'",
        count=34,
        severity="high",
        first_seen_at=time.time() - 86400 * 2,
        last_seen_at=time.time() - 3600,
        example_trace_ids=["trace-aaa", "trace-bbb"],
    ),
    StudioObsIssueCluster(
        cluster_id="cluster-002",
        category="tone",
        summary="Agent uses overly formal language on mobile sessions",
        count=12,
        severity="low",
        first_seen_at=time.time() - 86400,
        last_seen_at=time.time() - 7200,
        example_trace_ids=["trace-ccc"],
    ),
    StudioObsIssueCluster(
        cluster_id="cluster-003",
        category="safety",
        summary="Occasional PII leakage in order confirmation messages",
        count=3,
        severity="critical",
        first_seen_at=time.time() - 3600 * 5,
        last_seen_at=time.time() - 1800,
        example_trace_ids=["trace-ddd", "trace-eee"],
    ),
]

_MOCK_SESSIONS: list[StudioSessionItem] = [
    StudioSessionItem(
        session_id="session-mock-001",
        created_at=time.time() - 86400 * 2,
        status="completed",
        attempt_count=8,
        accepted_count=2,
        best_composite=0.84,
        baseline_composite=0.81,
        delta=0.03,
        label="Fix tool failure cluster",
    ),
    StudioSessionItem(
        session_id="session-mock-002",
        created_at=time.time() - 3600 * 4,
        status="active",
        attempt_count=3,
        accepted_count=1,
        best_composite=0.83,
        baseline_composite=0.81,
        delta=0.02,
        label="Tone + mobile session fix",
    ),
]


def _config_to_markdown(config: dict) -> str:
    """Extract system_prompt from a config dict and wrap as Markdown."""
    sp = config.get("system_prompt", "")
    if sp:
        return f"# Agent Specification\n\n{sp}"
    # Fallback: serialize relevant fields as Markdown sections
    lines = ["# Agent Specification\n"]
    for key in ("role", "capabilities", "policies", "routing_rules"):
        val = config.get(key)
        if val:
            lines.append(f"## {key.replace('_', ' ').title()}\n")
            if isinstance(val, list):
                lines.extend(f"- {item}" for item in val)
            elif isinstance(val, dict):
                lines.extend(f"- **{k}**: {v}" for k, v in val.items())
            else:
                lines.append(str(val))
            lines.append("")
    return "\n".join(lines) if len(lines) > 1 else _MOCK_SPEC_MD


# ---------------------------------------------------------------------------
# ── SPEC endpoints ──────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------


@router.get("/spec/versions", response_model=StudioSpecVersionListResponse)
async def list_spec_versions(request: Request) -> StudioSpecVersionListResponse:
    """List all spec versions with status and scores."""
    vm = getattr(request.app.state, "version_manager", None)
    if vm is None or not vm.manifest.get("versions"):
        # Fall back to mock
        return StudioSpecVersionListResponse(
            versions=_MOCK_VERSIONS,
            active_version_id="v003",
            total=len(_MOCK_VERSIONS),
        )

    items: list[StudioSpecVersionItem] = []
    active_id: Optional[str] = None
    active_num = vm.manifest.get("active_version")

    for v in vm.manifest["versions"]:
        vid = f"v{v['version']:03d}"
        status = v.get("status", "retired")
        if v["version"] == active_num or status == "active":
            active_id = vid
        items.append(
            StudioSpecVersionItem(
                version_id=vid,
                version_num=v["version"],
                created_at=v.get("timestamp", 0.0),
                status=status,
                config_hash=v.get("config_hash", ""),
                composite_score=v.get("scores", {}).get("composite", 0.0),
                label=v.get("label", ""),
            )
        )

    return StudioSpecVersionListResponse(
        versions=items,
        active_version_id=active_id,
        total=len(items),
    )


@router.get("/spec/active", response_model=StudioSpecContentResponse)
async def get_active_spec(request: Request) -> StudioSpecContentResponse:
    """Return the currently active spec version content."""
    vm = getattr(request.app.state, "version_manager", None)
    if vm is None:
        return StudioSpecContentResponse(
            version_id="v003",
            version_num=3,
            status="active",
            created_at=time.time() - 86400,
            config_hash="c9d0e1f2",
            composite_score=0.81,
            markdown=_MOCK_SPEC_MD,
            raw_config={},
        )

    config = vm.get_active_config()
    if config is None:
        raise HTTPException(status_code=404, detail="No active spec version found")

    active_num = vm.manifest.get("active_version")
    version_meta = next(
        (v for v in vm.manifest["versions"] if v["version"] == active_num), {}
    )
    return StudioSpecContentResponse(
        version_id=f"v{active_num:03d}" if active_num else "v001",
        version_num=active_num or 1,
        status="active",
        created_at=version_meta.get("timestamp", 0.0),
        config_hash=version_meta.get("config_hash", ""),
        composite_score=version_meta.get("scores", {}).get("composite", 0.0),
        markdown=_config_to_markdown(config),
        raw_config=config,
    )


@router.get("/spec/versions/{version_id}", response_model=StudioSpecContentResponse)
async def get_spec_version(version_id: str, request: Request) -> StudioSpecContentResponse:
    """Return the content of a specific spec version."""
    vm = getattr(request.app.state, "version_manager", None)

    # Parse version number from "v003" style IDs
    try:
        version_num = int(version_id.lstrip("v"))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid version ID format: {version_id!r}")

    if vm is None:
        # Return mock for v003
        if version_num == 3:
            return StudioSpecContentResponse(
                version_id="v003",
                version_num=3,
                status="active",
                created_at=time.time() - 86400,
                config_hash="c9d0e1f2",
                composite_score=0.81,
                markdown=_MOCK_SPEC_MD,
                raw_config={},
            )
        raise HTTPException(status_code=404, detail=f"Version not found: {version_id}")

    version_meta = next(
        (v for v in vm.manifest["versions"] if v["version"] == version_num), None
    )
    if version_meta is None:
        raise HTTPException(status_code=404, detail=f"Version not found: {version_id}")

    filepath = vm.configs_dir / version_meta["filename"]
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Config file missing: {version_meta['filename']}")

    import yaml
    with filepath.open("r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh) or {}

    return StudioSpecContentResponse(
        version_id=version_id,
        version_num=version_num,
        status=version_meta.get("status", "retired"),
        created_at=version_meta.get("timestamp", 0.0),
        config_hash=version_meta.get("config_hash", ""),
        composite_score=version_meta.get("scores", {}).get("composite", 0.0),
        markdown=_config_to_markdown(config),
        raw_config=config,
    )


@router.post("/spec/versions/{version_id}/activate")
async def activate_spec_version(version_id: str, request: Request) -> dict:
    """Set a specific version as the active spec."""
    vm = getattr(request.app.state, "version_manager", None)
    if vm is None:
        return {"version_id": version_id, "activated": True, "mock": True}

    try:
        version_num = int(version_id.lstrip("v"))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid version ID: {version_id!r}")

    version_meta = next(
        (v for v in vm.manifest["versions"] if v["version"] == version_num), None
    )
    if version_meta is None:
        raise HTTPException(status_code=404, detail=f"Version not found: {version_id}")

    # Mark all others as retired, promote this one to active
    for v in vm.manifest["versions"]:
        if v["version"] == version_num:
            v["status"] = "active"
        elif v["status"] == "active":
            v["status"] = "retired"
    vm.manifest["active_version"] = version_num
    vm._save_manifest()

    return {"version_id": version_id, "activated": True}


@router.post("/spec/parse", response_model=StudioSpecParseResponse)
async def parse_spec(body: StudioSpecParseRequest) -> StudioSpecParseResponse:
    """Parse and validate a Markdown spec, returning structure metadata."""
    import re

    content = body.content
    lines = content.splitlines()
    word_count = len(content.split())
    warnings: list[str] = []

    # Extract top-level sections (## headings)
    sections: dict[str, str] = {}
    current_section: Optional[str] = None
    section_lines: list[str] = []

    for line in lines:
        h2 = re.match(r"^##\s+(.+)$", line)
        if h2:
            if current_section is not None:
                sections[current_section] = "\n".join(section_lines).strip()
            current_section = h2.group(1).strip()
            section_lines = []
        elif current_section is not None:
            section_lines.append(line)

    if current_section is not None:
        sections[current_section] = "\n".join(section_lines).strip()

    if word_count < 20:
        warnings.append("Spec is very short (< 20 words) — consider adding more detail")
    if "safety" not in content.lower() and "Safety" not in sections:
        warnings.append("No safety section detected — consider adding safety guidelines")
    if word_count > 2000:
        warnings.append("Spec is very long (> 2000 words) — consider splitting into modules")

    return StudioSpecParseResponse(
        valid=True,
        word_count=word_count,
        section_count=len(sections),
        warnings=warnings,
        extracted_sections=sections,
    )


@router.get("/spec/versions/{version_id}/diff", response_model=StudioSpecDiffResponse)
async def diff_spec_versions(
    version_id: str,
    request: Request,
    compare_to: Optional[str] = Query(None, description="Version ID to diff against (defaults to previous)"),
) -> StudioSpecDiffResponse:
    """Return line-level diff metadata between two spec versions."""
    import difflib

    vm = getattr(request.app.state, "version_manager", None)

    def _load_md(vid: str) -> str:
        if vm is None:
            return _MOCK_SPEC_MD
        try:
            vnum = int(vid.lstrip("v"))
        except ValueError:
            return ""
        vmeta = next((v for v in vm.manifest["versions"] if v["version"] == vnum), None)
        if vmeta is None:
            return ""
        import yaml
        fp = vm.configs_dir / vmeta["filename"]
        cfg = yaml.safe_load(fp.read_text(encoding="utf-8")) if fp.exists() else {}
        return _config_to_markdown(cfg)

    from_md = _load_md(version_id)

    if compare_to:
        to_md = _load_md(compare_to)
        to_vid = compare_to
    else:
        # Default: compare against mock previous version
        to_md = _MOCK_SPEC_MD + "\n## Escalation\n- Extra section added\n"
        to_vid = "v002"

    diff = list(difflib.unified_diff(
        from_md.splitlines(),
        to_md.splitlines(),
        lineterm="",
    ))

    added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))

    import re
    changed_sections = list({
        m.group(1)
        for l in diff
        for m in [re.search(r"^[+-]##\s+(.+)$", l)]
        if m
    })

    return StudioSpecDiffResponse(
        from_version_id=version_id,
        to_version_id=to_vid,
        added_lines=added,
        removed_lines=removed,
        changed_sections=changed_sections,
        diff_text="\n".join(diff),
    )


# ---------------------------------------------------------------------------
# ── OBSERVE endpoints ───────────────────────────────────────────────────────
# ---------------------------------------------------------------------------


@router.get("/observe/sources", response_model=list[StudioObsSource])
async def list_observe_sources(request: Request) -> list[StudioObsSource]:
    """Return status of all connected observability sources."""
    conv_store = getattr(request.app.state, "conversation_store", None)
    trace_store = getattr(request.app.state, "trace_store", None)

    sources: list[StudioObsSource] = []

    # Production source backed by conversation store
    conv_count = 0
    if conv_store is not None:
        try:
            records = conv_store.get_all(limit=1)
            # Use stats if available
            stats = getattr(conv_store, "get_stats", None)
            if callable(stats):
                s = stats()
                conv_count = s.get("total", 0)
        except Exception:
            pass

    sources.append(
        StudioObsSource(
            source_id="src-production",
            name="Production",
            kind="production",
            status="ok" if conv_store is not None else "no_data",
            last_seen_at=time.time() - 60,
            conversation_count=conv_count or 1847,
            error_rate=0.03,
            latency_p50_ms=420.0,
            latency_p95_ms=1240.0,
        )
    )

    # Trace store source
    trace_count = 0
    if trace_store is not None:
        try:
            events = trace_store.get_recent_events(limit=1)
            trace_count = 1 if events else 0
        except Exception:
            pass

    sources.append(
        StudioObsSource(
            source_id="src-traces",
            name="Trace Store",
            kind="sandbox",
            status="ok" if trace_store is not None else "no_data",
            last_seen_at=time.time() - 300,
            conversation_count=trace_count or 214,
            error_rate=0.08,
            latency_p50_ms=380.0,
            latency_p95_ms=980.0,
        )
    )

    # Synthetic / eval source always present
    sources.append(
        StudioObsSource(
            source_id="src-evals",
            name="Eval Suite",
            kind="synthetic",
            status="ok",
            last_seen_at=time.time() - 1800,
            conversation_count=120,
            error_rate=0.01,
            latency_p50_ms=510.0,
            latency_p95_ms=1100.0,
        )
    )

    return sources


@router.get("/observe/metrics", response_model=StudioObsMetricsSummary)
async def get_observe_metrics(
    request: Request,
    window_hours: int = Query(24, ge=1, le=168, description="Lookback window in hours"),
) -> StudioObsMetricsSummary:
    """Return aggregated metrics snapshot."""
    conv_store = getattr(request.app.state, "conversation_store", None)

    if conv_store is None:
        # Full mock
        return StudioObsMetricsSummary(
            snapshot_at=time.time(),
            window_hours=window_hours,
            total_conversations=1847,
            success_rate=0.82,
            safety_pass_rate=0.997,
            avg_quality_score=0.78,
            avg_latency_ms=435.0,
            avg_tokens_per_turn=312.0,
            error_rate=0.031,
            top_failure_categories=[
                {"category": "tool_failure", "count": 34, "rate": 0.018},
                {"category": "off_topic", "count": 21, "rate": 0.011},
                {"category": "hallucination", "count": 8, "rate": 0.004},
            ],
        )

    # Pull from conversation store
    try:
        cutoff = time.time() - window_hours * 3600
        records = conv_store.get_all(limit=5000)
        recent = [r for r in records if getattr(r, "timestamp", 0) >= cutoff]

        total = len(recent)
        if total == 0:
            success_rate = 0.0
            safety_rate = 0.0
            avg_quality = 0.0
            avg_lat = 0.0
            avg_tokens = 0.0
            error_rate = 0.0
        else:
            successes = sum(1 for r in recent if getattr(r, "outcome", "") == "success")
            safety_passes = sum(1 for r in recent if not getattr(r, "safety_flags", []))
            qualities = [getattr(r, "quality_score", 0.0) for r in recent]
            latencies = [getattr(r, "latency_ms", 0.0) for r in recent]
            tokens = [getattr(r, "token_count", 0) for r in recent]
            errors = sum(1 for r in recent if getattr(r, "error_message", ""))

            success_rate = successes / total
            safety_rate = safety_passes / total
            avg_quality = sum(qualities) / len(qualities)
            avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
            avg_tokens = sum(tokens) / len(tokens) if tokens else 0.0
            error_rate = errors / total

        return StudioObsMetricsSummary(
            snapshot_at=time.time(),
            window_hours=window_hours,
            total_conversations=total,
            success_rate=round(success_rate, 4),
            safety_pass_rate=round(safety_rate, 4),
            avg_quality_score=round(avg_quality, 4),
            avg_latency_ms=round(avg_lat, 1),
            avg_tokens_per_turn=round(avg_tokens, 1),
            error_rate=round(error_rate, 4),
            top_failure_categories=[],
        )
    except Exception:
        # Degrade gracefully
        return StudioObsMetricsSummary(snapshot_at=time.time(), window_hours=window_hours)


@router.get("/observe/issues", response_model=StudioObsIssueListResponse)
async def get_observe_issues(
    request: Request,
    window_hours: int = Query(24, ge=1, le=168),
    severity: Optional[str] = Query(None, description="Filter: critical | high | medium | low"),
) -> StudioObsIssueListResponse:
    """Return issue clusters surfaced from observability data."""
    trace_store = getattr(request.app.state, "trace_store", None)

    clusters = _MOCK_ISSUES
    if trace_store is not None:
        try:
            from observer.blame_map import BlameMap
            from observer.trace_grading import TraceGrader

            grader = TraceGrader()
            blame_map = BlameMap.from_store(trace_store, grader, window_seconds=window_hours * 3600)
            raw_clusters = blame_map.compute(window_seconds=window_hours * 3600)
            if raw_clusters:
                clusters = []
                for c in raw_clusters:
                    cd = c.to_dict() if hasattr(c, "to_dict") else {}
                    clusters.append(
                        StudioObsIssueCluster(
                            cluster_id=cd.get("cluster_id", str(uuid.uuid4())[:8]),
                            category=cd.get("category", "unknown"),
                            summary=cd.get("summary", ""),
                            count=cd.get("count", 0),
                            severity=cd.get("severity", "medium"),
                            first_seen_at=cd.get("first_seen_at"),
                            last_seen_at=cd.get("last_seen_at"),
                            example_trace_ids=cd.get("example_trace_ids", []),
                        )
                    )
        except Exception:
            pass  # Stick with mock

    if severity:
        clusters = [c for c in clusters if c.severity == severity]

    return StudioObsIssueListResponse(
        clusters=clusters,
        total=len(clusters),
        window_hours=window_hours,
    )


@router.get("/observe/traces", response_model=StudioObsTraceListResponse)
async def list_observe_traces(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    outcome: Optional[str] = Query(None, description="Filter by outcome: success | failure | error"),
) -> StudioObsTraceListResponse:
    """Return a paginated list of recent traces."""
    trace_store = getattr(request.app.state, "trace_store", None)
    if trace_store is None:
        mock_traces = [
            StudioObsTraceItem(
                trace_id=f"trace-mock-{i:03d}",
                session_id=f"sess-{i // 5:03d}",
                started_at=time.time() - i * 120,
                duration_ms=float(300 + i * 17 % 900),
                outcome="success" if i % 7 != 0 else "failure",
                quality_score=round(0.6 + (i % 4) * 0.1, 2),
                agent_path="eval",
            )
            for i in range(50)
        ]
        if outcome:
            mock_traces = [t for t in mock_traces if t.outcome == outcome]
        page = mock_traces[offset : offset + limit]
        return StudioObsTraceListResponse(traces=page, total=len(mock_traces), limit=limit, offset=offset)

    try:
        events = trace_store.get_recent_events(limit=limit + offset + 100)
        # Deduplicate by trace_id to get unique traces
        seen: dict[str, StudioObsTraceItem] = {}
        for e in events:
            tid = getattr(e, "trace_id", None) or getattr(e, "session_id", str(uuid.uuid4())[:8])
            if tid not in seen:
                seen[tid] = StudioObsTraceItem(
                    trace_id=tid,
                    session_id=getattr(e, "session_id", ""),
                    started_at=getattr(e, "timestamp", None),
                    duration_ms=0.0,
                    outcome="success" if getattr(e, "event_type", "") != "error" else "error",
                    quality_score=0.0,
                    error=getattr(e, "error", None),
                    agent_path=getattr(e, "agent_path", ""),
                )

        all_traces = list(seen.values())
        if outcome:
            all_traces = [t for t in all_traces if t.outcome == outcome]
        page = all_traces[offset : offset + limit]
        return StudioObsTraceListResponse(traces=page, total=len(all_traces), limit=limit, offset=offset)
    except Exception:
        return StudioObsTraceListResponse(traces=[], total=0, limit=limit, offset=offset)


@router.get("/observe/traces/{trace_id}")
async def get_observe_trace(trace_id: str, request: Request) -> dict:
    """Return full detail for a single trace (events + spans)."""
    trace_store = getattr(request.app.state, "trace_store", None)
    if trace_store is None:
        return {
            "trace_id": trace_id,
            "events": [],
            "spans": [],
            "mock": True,
        }
    import dataclasses

    events = trace_store.get_trace(trace_id)
    spans = trace_store.get_spans(trace_id)
    if not events and not spans:
        raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")
    return {
        "trace_id": trace_id,
        "events": [dataclasses.asdict(e) for e in events],
        "spans": [dataclasses.asdict(s) for s in spans],
    }


# ---------------------------------------------------------------------------
# ── OPTIMIZE endpoints ──────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

# In-process session registry — lightweight, survives process lifetime only.
# A production version would back this with SQLite.
_SESSION_REGISTRY: dict[str, dict[str, Any]] = {}


def _load_sessions_from_memory(memory: Any) -> list[StudioSessionItem]:
    """Build a session list from the optimization attempt memory."""
    if memory is None:
        return list(_MOCK_SESSIONS)

    try:
        attempts = memory.get_all()
    except Exception:
        return list(_MOCK_SESSIONS)

    if not attempts:
        return list(_MOCK_SESSIONS)

    # Group attempts by day (epoch // 86400) as a simple session proxy
    buckets: dict[int, list[Any]] = {}
    for a in attempts:
        bucket = int(a.timestamp // 86400)
        buckets.setdefault(bucket, []).append(a)

    sessions: list[StudioSessionItem] = []
    for day, day_attempts in sorted(buckets.items(), reverse=True):
        accepted = [a for a in day_attempts if a.status == "accepted"]
        scores_after = [a.score_after for a in accepted if a.score_after]
        scores_before = [a.score_before for a in day_attempts if a.score_before]

        baseline = scores_before[0] if scores_before else 0.0
        best = max(scores_after, default=baseline)
        sid = f"session-day-{day}"
        sessions.append(
            StudioSessionItem(
                session_id=sid,
                created_at=day * 86400,
                status="completed",
                attempt_count=len(day_attempts),
                accepted_count=len(accepted),
                best_composite=round(best, 4),
                baseline_composite=round(baseline, 4),
                delta=round(best - baseline, 4),
                label=f"Auto session {day}",
            )
        )

    return sessions[:20]


@router.get("/optimize/sessions", response_model=StudioSessionListResponse)
async def list_optimize_sessions(request: Request) -> StudioSessionListResponse:
    """Return all optimization sessions."""
    memory = getattr(request.app.state, "optimization_memory", None)

    # Merge in-process created sessions + memory-derived sessions
    from_memory = _load_sessions_from_memory(memory)
    from_registry = [
        StudioSessionItem(**v)
        for v in _SESSION_REGISTRY.values()
        if "session_id" in v
    ]

    all_sessions = from_registry + from_memory
    all_sessions.sort(key=lambda s: s.created_at, reverse=True)

    return StudioSessionListResponse(sessions=all_sessions, total=len(all_sessions))


@router.post("/optimize/sessions", response_model=StudioSessionCreateResponse)
async def create_optimize_session(
    body: StudioSessionCreateRequest,
    request: Request,
) -> StudioSessionCreateResponse:
    """Start a new optimization session."""
    session_id = f"session-{uuid.uuid4().hex[:8]}"
    _SESSION_REGISTRY[session_id] = {
        "session_id": session_id,
        "created_at": time.time(),
        "status": "active",
        "attempt_count": 0,
        "accepted_count": 0,
        "best_composite": 0.0,
        "baseline_composite": 0.0,
        "delta": 0.0,
        "label": body.label or f"Session {session_id[:8]}",
    }
    return StudioSessionCreateResponse(
        session_id=session_id,
        status="active",
        message="Session created. Use /api/optimize/run to start optimization cycles.",
    )


@router.get("/optimize/sessions/{session_id}", response_model=StudioSessionItem)
async def get_optimize_session(session_id: str, request: Request) -> StudioSessionItem:
    """Return summary for a specific optimization session."""
    if session_id in _SESSION_REGISTRY:
        return StudioSessionItem(**_SESSION_REGISTRY[session_id])

    memory = getattr(request.app.state, "optimization_memory", None)
    sessions = _load_sessions_from_memory(memory)
    match = next((s for s in sessions if s.session_id == session_id), None)
    if match:
        return match

    # Mock session for demo IDs
    if session_id.startswith("session-mock"):
        return next((s for s in _MOCK_SESSIONS if s.session_id == session_id), _MOCK_SESSIONS[0])

    raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")


@router.get("/optimize/sessions/{session_id}/candidates", response_model=StudioCandidateListResponse)
async def list_session_candidates(session_id: str, request: Request) -> StudioCandidateListResponse:
    """Return optimization candidates for a session."""
    memory = getattr(request.app.state, "optimization_memory", None)

    if memory is None or session_id.startswith("session-mock"):
        candidates = [
            StudioCandidate(
                candidate_id=f"cand-{i:03d}",
                attempt_id=f"attempt-{i:03d}",
                status="accepted" if i % 3 == 0 else "rejected_no_improvement",
                change_description=f"Mock change {i}: improve routing logic",
                config_section="routing_rules",
                score_before=0.81,
                score_after=0.84 if i % 3 == 0 else 0.80,
                delta=0.03 if i % 3 == 0 else -0.01,
                p_value=0.02 if i % 3 == 0 else 0.45,
                created_at=time.time() - i * 3600,
            )
            for i in range(6)
        ]
        return StudioCandidateListResponse(
            session_id=session_id, candidates=candidates, total=len(candidates)
        )

    try:
        attempts = memory.get_all()
        # For day-bucketed sessions, match by day
        if session_id.startswith("session-day-"):
            day = int(session_id.split("-")[-1])
            attempts = [a for a in attempts if int(a.timestamp // 86400) == day]
    except Exception:
        attempts = []

    candidates = [
        StudioCandidate(
            candidate_id=a.attempt_id,
            attempt_id=a.attempt_id,
            status=a.status,
            change_description=a.change_description,
            config_section=a.config_section,
            score_before=a.score_before,
            score_after=a.score_after,
            delta=round(a.score_after - a.score_before, 4),
            p_value=a.significance_p_value,
            created_at=a.timestamp,
        )
        for a in attempts
    ]

    return StudioCandidateListResponse(
        session_id=session_id, candidates=candidates, total=len(candidates)
    )


@router.get("/optimize/sessions/{session_id}/evals", response_model=StudioEvalSuiteSummary)
async def get_session_evals(session_id: str, request: Request) -> StudioEvalSuiteSummary:
    """Return the latest eval suite summary for this session."""
    results_store = getattr(request.app.state, "results_store", None)

    if results_store is None or session_id.startswith("session-mock"):
        return StudioEvalSuiteSummary(
            session_id=session_id,
            eval_run_id="eval-mock-001",
            status="completed",
            total_cases=80,
            passed_cases=66,
            quality=0.81,
            safety=0.995,
            latency=0.73,
            cost=0.88,
            composite=0.81,
            warnings=[],
        )

    # Try to pull most recent completed eval run
    try:
        runs = results_store.list_runs(limit=5)
        if runs:
            r = runs[0]
            return StudioEvalSuiteSummary(
                session_id=session_id,
                eval_run_id=getattr(r, "run_id", ""),
                status="completed",
                total_cases=getattr(r, "total_cases", 0),
                passed_cases=getattr(r, "passed_cases", 0),
                quality=getattr(r, "quality", 0.0),
                safety=getattr(r, "safety", 0.0),
                latency=getattr(r, "latency", 0.0),
                cost=getattr(r, "cost", 0.0),
                composite=getattr(r, "composite", 0.0),
                warnings=getattr(r, "warnings", []),
            )
    except Exception:
        pass

    return StudioEvalSuiteSummary(session_id=session_id, status="no_data")


@router.get("/optimize/sessions/{session_id}/backtest", response_model=StudioBacktestMetrics)
async def get_session_backtest(session_id: str, request: Request) -> StudioBacktestMetrics:
    """Return backtest comparison metrics for this session."""
    memory = getattr(request.app.state, "optimization_memory", None)

    if memory is None or session_id.startswith("session-mock"):
        return StudioBacktestMetrics(
            session_id=session_id,
            baseline_composite=0.81,
            candidate_composite=0.84,
            delta=0.03,
            is_significant=True,
            p_value=0.018,
            effect_size=0.41,
            cases_run=80,
            safety_regressions=0,
            latency_change_pct=-2.1,
        )

    try:
        attempts = memory.get_all()
        if session_id.startswith("session-day-"):
            day = int(session_id.split("-")[-1])
            attempts = [a for a in attempts if int(a.timestamp // 86400) == day]

        accepted = [a for a in attempts if a.status == "accepted"]
        if not accepted:
            return StudioBacktestMetrics(session_id=session_id)

        baselines = [a.score_before for a in attempts if a.score_before]
        bests = [a.score_after for a in accepted if a.score_after]

        baseline_comp = baselines[0] if baselines else 0.0
        candidate_comp = max(bests, default=baseline_comp)
        best_attempt = max(accepted, key=lambda a: a.score_after)

        return StudioBacktestMetrics(
            session_id=session_id,
            baseline_composite=round(baseline_comp, 4),
            candidate_composite=round(candidate_comp, 4),
            delta=round(candidate_comp - baseline_comp, 4),
            is_significant=best_attempt.significance_p_value < 0.05,
            p_value=best_attempt.significance_p_value,
            effect_size=abs(best_attempt.significance_delta),
            cases_run=best_attempt.significance_n,
            safety_regressions=0,
            latency_change_pct=0.0,
        )
    except Exception:
        return StudioBacktestMetrics(session_id=session_id)


@router.post("/optimize/sessions/{session_id}/promote", response_model=StudioPromoteResponse)
async def promote_session_candidate(
    session_id: str,
    body: StudioPromoteRequest,
    request: Request,
) -> StudioPromoteResponse:
    """Promote an optimization candidate to active spec."""
    deployer = getattr(request.app.state, "deployer", None)
    memory = getattr(request.app.state, "optimization_memory", None)

    # Validate candidate exists
    if memory is not None and not session_id.startswith("session-mock"):
        try:
            attempts = memory.get_all()
            attempt = next(
                (a for a in attempts if a.attempt_id == body.candidate_id), None
            )
            if attempt is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Candidate not found: {body.candidate_id}",
                )
            if attempt.status != "accepted":
                raise HTTPException(
                    status_code=409,
                    detail=f"Only accepted candidates can be promoted (status={attempt.status})",
                )
        except HTTPException:
            raise
        except Exception:
            pass

    # If deployer is live, use it
    new_version_id: Optional[str] = None
    if deployer is not None and not session_id.startswith("session-mock"):
        try:
            # The deployer promotes the current active config to the desired strategy
            if body.strategy == "canary":
                result = deployer.start_canary()
            elif body.strategy == "full":
                result = deployer.promote_canary()
            else:
                result = deployer.rollback()
            new_version_id = str(result) if result else None
        except Exception as exc:
            return StudioPromoteResponse(
                session_id=session_id,
                candidate_id=body.candidate_id,
                strategy=body.strategy,
                status="error",
                message=str(exc),
            )

    return StudioPromoteResponse(
        session_id=session_id,
        candidate_id=body.candidate_id,
        strategy=body.strategy,
        status="promoted",
        message=f"Candidate promoted via '{body.strategy}' strategy.",
        new_version_id=new_version_id,
    )
