# PRD v3 Gap Analysis — AgentLab

**Date:** 2026-04-12
**Branch:** `feat/prd-p0-gap-claude`
**Analyst:** Claude Opus (with backend-hardening, frontend-systems, prd-gap-analyst, eval-risk-reviewer agents)

---

## Executive Summary

The current implementation is a comprehensive agent-building platform with strong foundations in evaluation, optimization, trace collection, and multi-platform integration (ADK, CX). The builder workspace has a well-defined type system, SQLite persistence for first-class objects, and a streaming event architecture.

However, the PRD's core thesis — that the builder should feel like "Claude Code for agent building" with durable sessions, honest state, and structured handoffs — exposes five critical gaps where the implementation diverges from what the PRD treats as foundational.

---

## Gap Matrix

### 1. Durable Session Event Log — **P0 CRITICAL**

| Aspect | PRD Expectation | Current State |
|--------|----------------|---------------|
| Session events | Durable, append-only, queryable log outside model context | **In-memory only** (`deque(maxlen=2000)` in `EventBroker`) |
| Persistence | Survives server restarts | **Lost on restart** — events disappear completely |
| System events | Unified event log across builder, eval, optimizer | **Two disconnected systems**: `EventBroker` (builder, in-memory) and `EventLog` (optimizer/eval, SQLite) |
| API | Session event history endpoint | `GET /api/builder/events` reads from in-memory broker — **empty after restart** |

**Impact:** This is the most critical gap. Without durable events, the system cannot provide session history, debugging of failed builds, or cross-session continuity. The PRD's "decouple brain from durable session log" principle is violated.

**Files:** `builder/events.py` (EventBroker), `data/event_log.py` (system EventLog), `api/routes/builder.py:584-619`

### 2. Release Candidate API Surface — **P0 HIGH**

| Aspect | PRD Expectation | Current State |
|--------|----------------|---------------|
| API routes | CRUD + lifecycle operations for release candidates | **Zero API endpoints** — type and store exist but no routes |
| Lifecycle | Draft → Reviewed → Candidate → Staging → Production → Archived | Only `draft | approved | deployed | rolled_back` |
| Provenance | Eval evidence, approver, deploy target, rollback target | Partial — `eval_bundle_id`, `artifact_ids` exist but no `approver`, no `promotion_evidence` |

**Impact:** The promotion/review flow — which the PRD treats as a core safety mechanism — is inaccessible from the frontend or any API consumer. The store infrastructure (`BuilderStore.save_release()`, `get_release()`, etc.) is implemented but dark.

**Files:** `builder/types.py:352-397` (ReleaseCandidate), `builder/store.py:877+` (persistence), `api/routes/builder.py` (no release routes)

### 3. Builder Task Crash Recovery — **P0 HIGH**

| Aspect | PRD Expectation | Current State |
|--------|----------------|---------------|
| Stale task recovery | Tasks interrupted by crashes are detected and marked failed | **No recovery** — BuilderTasks left in `running`/`paused` will stay stuck forever |
| Workbench runs | Same | ✅ Implemented via `_recover_stale_runs()` with 30-min threshold |
| Checkpoint resume | Build can resume from checkpoint after interruption | Checkpoints are persisted (`HarnessCheckpoint`) but **never consumed** for resume |

**Impact:** After any server restart, tasks in active states become zombies. The workbench has this solved for its own runs but the BuilderTask system does not.

**Files:** `builder/execution.py`, `builder/workbench.py:_recover_stale_runs()`, `builder/harness.py` (checkpoints)

### 4. Builder-to-System Event Bridge — **P0 MEDIUM**

| Aspect | PRD Expectation | Current State |
|--------|----------------|---------------|
| Unified events | Single event model spanning builder, eval, optimizer, live | Builder events (`BuilderEventType`) and system events (`VALID_EVENT_TYPES`) are completely separate |
| Cross-system queries | Query events by source, session, time range | Each system has its own query API with no cross-reference |
| Event types | Builder lifecycle events in the system log | Builder events (task.started, task.completed, etc.) are **not** written to the system event log |

**Impact:** An operator cannot get a unified view of what happened across a session that involved building, evaluating, and optimizing. The PRD's "unified trace schema" vision starts with unified events.

**Files:** `builder/events.py`, `data/event_log.py`

### 5. Session Handoff / Progress Artifact — **P0 MEDIUM**

| Aspect | PRD Expectation | Current State |
|--------|----------------|---------------|
| Progress file | `agentlab-progress.json` as structured cross-session handoff | **Does not exist** — zero references in codebase |
| Session summary | Structured summary for iterator sessions to resume from | Sessions have metadata dict but no structured summary schema |
| Handoff notes | Explicit notes for the next session | Not implemented |

**Impact:** The PRD's multi-session iteration model depends on a structured progress artifact. Currently, session continuity relies on the raw session metadata and message history, which is insufficient for the "initializer + iterator" pattern.

**Files:** No existing implementation

---

## Already Implemented (Not Gaps)

| PRD Area | Status | Notes |
|----------|--------|-------|
| Agent Card & IR | ✅ Solid | `core/types.py` — AgentNode/AgentEdge graph IR |
| Builder type system | ✅ Strong | `builder/types.py` — comprehensive enums and dataclasses |
| SQLite persistence (sessions, tasks, artifacts) | ✅ Working | `builder/store.py` — full CRUD for 10 object types |
| Evaluation system | ✅ Comprehensive | `evals/` — runner, graders, replay, pairwise, statistics |
| Optimization engine | ✅ Deep | `optimizer/` — 53+ files, Pareto, bandit, curriculum |
| Trace store | ✅ Functional | `observer/traces.py` — SQLite-backed, rich event types |
| ADK integration | ✅ Rich | `adk/` — import, export, deploy, runtime, mapping |
| CX integration | ✅ Rich | `cx_studio/` — import, export, deploy, mapping |
| Builder API (sessions, tasks, proposals, artifacts) | ✅ Complete | `api/routes/builder.py` — full CRUD |
| Workbench streaming | ✅ Working | SSE + event broker for live build updates |
| Task lifecycle (pause/resume/cancel) | ✅ Implemented | `builder/execution.py` — state transitions with events |
| Approval/permission system | ✅ Working | `builder/types.py` + `builder/permissions.py` |
| Harness execution engine | ✅ Functional | `builder/harness.py` — plan→execute→reflect→present |
| Release manager (promotion pipeline) | ✅ Exists | `deployer/release_manager.py` — multi-stage promotion |
| Skill promotion workflow | ✅ Exists | `core/skills/promotion.py` |
| MCP server | ✅ Working | `mcp_server/` — 22+ tools exposed |

---

### 6. Frontend State Honesty — **P0 HIGH**

| Aspect | PRD Expectation | Current State |
|--------|----------------|---------------|
| StatusPill lifecycle | Shows all run states honestly | **4 states invisible** — `queued`, `reflecting`, `presenting`, `cancelled` all show as "Idle" |
| Candidate promotion button | Triggers review/promotion flow | **Dead button** — "Candidate ready" has no `onClick` handler |
| Live Trace tab | Shows events during a run | **Always empty** during live runs — `activeRun.events` only populated on terminal `run.completed` |
| Run history | Shows past runs across sessions | **Silently dropped** — `runs` loaded from snapshot but never read by store `hydrate` |

**Impact:** The operator sees a misleading picture of build state during the most important moments (reflecting, presenting). The "Candidate ready" button promises a promotion flow that doesn't exist. These are honesty violations that erode trust.

**Files:** `web/src/components/workbench/WorkbenchLayout.tsx:92-148`, `web/src/lib/workbench-store.ts` (hydrate + dispatchEvent), `web/src/components/workbench/ArtifactViewer.tsx:506-555`

### 7. Duplicate Event Handler — **P0 MEDIUM**

| Aspect | PRD Expectation | Current State |
|--------|----------------|---------------|
| `iteration.started` | Single handler per event | **Duplicated** at two locations in workbench-store.ts dispatchEvent |

**Impact:** Under fast-path or reorder conditions, the second handler can double-increment `iterationCount` and double-push to `iterationHistory`. A latent data corruption bug.

**Files:** `web/src/lib/workbench-store.ts` (lines ~456 and ~887)

---

## Deferred (Not P0 Now)

| PRD Area | Reason for Deferral |
|----------|-------------------|
| Full CLI rewrite | Current CLI is functional; PRD CLI spec is aspirational |
| Complete optimizer platform rebuild | Already 53+ files; PRD envisions deeper but current is strong |
| Full Workbench tab overhaul (Graph, Live, Deploy tabs) | Large UI scope; current tabs serve existing flows |
| ADK/CX fidelity preview runners | Integration exists; fidelity preview is incremental |
| Full context management (5-layer architecture) | Aspirational; current session + context model works |
| Live performance dashboards | Requires production deployment pipeline first |
| Shadow comparison before promotion | Requires live traffic routing infrastructure |
| Full secrets vault/broker/proxy pattern | Security architecture change; current model adequate for dev |
| Composer scope chips in UI | UI polish; not blocking core loops |
| Agent Card markdown compiler | Current IR/graph model works; markdown compiler is incremental |
