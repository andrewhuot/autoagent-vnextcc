# P0 Implementation Plan — PRD Gap Closure

**Date:** 2026-04-12
**Branch:** `feat/prd-p0-gap-claude`
**Approach:** Conservative, additive changes layered onto existing architecture.

---

## Selected P0 Changes (5 workstreams)

### WS-1: Durable Session Event Log
**Priority:** CRITICAL — highest leverage single change
**Files:** `builder/events.py`, `data/event_log.py`, `builder/store.py`

1. Add a `builder_session_events` table to `BuilderStore._init_db()` with columns: `event_id`, `session_id`, `task_id`, `event_type`, `timestamp`, `payload`
2. Extend `EventBroker.publish()` to also persist events to SQLite via an injected store reference
3. Add `BuilderStore.list_session_events(session_id, task_id, event_type, limit)` query method
4. Update `GET /api/builder/events` to read from SQLite (durable) rather than in-memory deque
5. Keep the in-memory deque for streaming (SSE) — SQLite for history, deque for live

**Contract:** Events are durable after this change. The API returns the same shape but now survives restarts.

### WS-2: Release Candidate API Routes
**Priority:** HIGH — unlocks promotion flow
**Files:** `api/routes/builder.py`, `builder/types.py`

1. Add `reviewed`, `staging`, `archived` to `ReleaseCandidate.status` choices
2. Add `approver`, `promotion_evidence` fields to `ReleaseCandidate`
3. Add API routes:
   - `GET /api/builder/releases` — list releases (filterable by project_id, status)
   - `GET /api/builder/releases/{release_id}` — get single release
   - `POST /api/builder/releases` — create release candidate
   - `PATCH /api/builder/releases/{release_id}` — update (status transitions)
   - `POST /api/builder/releases/{release_id}/promote` — advance lifecycle
   - `POST /api/builder/releases/{release_id}/rollback` — rollback
4. Emit builder events on release lifecycle transitions

### WS-3: Builder Task Crash Recovery
**Priority:** HIGH — reliability
**Files:** `builder/execution.py`, `builder/store.py`

1. Add `BuilderStore.list_stale_tasks(max_age_seconds)` — finds tasks in active states older than threshold
2. Add `BuilderExecutionEngine.recover_stale_tasks()` — marks stale running/paused tasks as `failed` with reason `stale_interrupted`
3. Call recovery on engine initialization (same pattern as `_recover_stale_runs()`)
4. Emit `task.failed` event with `failure_reason: stale_interrupted`

### WS-4: Frontend State Honesty Fixes
**Priority:** HIGH — user trust
**Files:** `web/src/components/workbench/WorkbenchLayout.tsx`, `web/src/lib/workbench-store.ts`

1. Fix `StatusPill` to render all lifecycle states: `queued`, `reflecting`, `presenting`, `cancelled`
2. Remove or properly wire the "Candidate ready" button (disable + tooltip explaining it's coming)
3. Remove the duplicate `iteration.started` handler (keep the canonical one, remove the stale copy)

### WS-5: Builder-to-System Event Bridge
**Priority:** MEDIUM — unified observability
**Files:** `data/event_log.py`, `builder/events.py`

1. Add builder lifecycle event types to `VALID_EVENT_TYPES`: `builder_task_started`, `builder_task_completed`, `builder_task_failed`, `builder_session_opened`, `builder_session_closed`
2. Have `EventBroker.publish()` also write key lifecycle events to the system `EventLog` (bridging the two systems)
3. Add `session_id` column to the system event log table for cross-reference

---

## Out of Scope (Deferred)

- Full progress.json implementation (requires builder agent changes)
- Live Trace tab population during runs (requires SSE event accumulation rework)
- Run history hydration (requires store + component work beyond P0)
- Full `BuildStreamEvent.event` type narrowing
- Budget type field consolidation

---

## Test Plan

Each workstream gets targeted tests:
- WS-1: Test event persistence across store instances, list/filter queries, API endpoint returns durable data
- WS-2: Test release CRUD, lifecycle transitions, rejection of invalid transitions
- WS-3: Test stale task detection and recovery, event emission on recovery
- WS-4: Frontend component tests for StatusPill states, store dedup fix
- WS-5: Test bridge writes system events, session_id cross-reference

## Verification Ladder

1. `pytest tests/test_builder_store.py tests/test_event_log.py tests/test_builder_execution.py tests/test_harness.py -x`
2. `pytest tests/test_builder_api.py -x`
3. `cd web && npx tsc --noEmit`
4. `cd web && npx vitest run`
5. `cd web && npx vite build`
