# P1 Runtime Coherence Plan
**Date:** 2026-04-12
**Author:** Claude Opus 4.6
**Branch:** feat/p1-runtime-coherence-claude
**Issue:** #7 — Reduce user-facing runtime fragmentation

---

## Problem Statement

AgentLab has three disconnected event systems that fragment the operator experience:

1. **EventBroker** (`builder/events.py`) — In-memory deque for builder SSE streaming. Has built-in support for SQLite durability (`DurableEventStore`) and system log bridging (`_bridge_to_system_log()`), but **neither is wired** in `api/server.py:284` — instantiated as `EventBroker()` with no arguments.

2. **EventLog** (`data/event_log.py`) — SQLite-backed system-wide audit trail. 26+ event types. Written to manually by route handlers (autofix, judges, control). Builder lifecycle event types are defined (`builder_task_started`, etc.) but never receive data because the bridge isn't connected.

3. **WebSocket** (`api/websocket.py`) — In-memory broadcast to connected clients. Used for `eval_complete`, `optimize_complete`, `loop_cycle`. These events are fire-and-forget — not recorded in any durable store.

**Result:** An operator who wants to see "what happened in this session" must query three separate systems. Builder events vanish on restart. Eval/optimize completion events are never durably recorded. There is no unified timeline.

---

## Chosen Architecture Slice

**Unify event persistence and create a single query surface for all runtime events.**

This is the highest-value coherence improvement because:
- The bridge code already exists but isn't wired (low risk, high impact)
- It transforms three disconnected event flows into a single durable timeline
- It enables any future UI (dashboard, activity feed, session replay) to query one endpoint
- It's finishable in one session with tests

### What changes:

1. **Wire EventBroker with DurableEventStore + EventLog bridge** (`api/server.py`)
   - Instantiate `DurableEventStore` and pass to `EventBroker`
   - Pass `app.state.event_log` as `system_event_log` to `EventBroker`
   - Fix initialization order: EventLog must be created before EventBroker

2. **Bridge WebSocket broadcast events to EventLog** (`api/routes/eval.py`, `optimize.py`, `loop.py`)
   - After each `ws_manager.broadcast()`, also `event_log.append()` the same event
   - Add new valid event types to EventLog: `eval_completed_broadcast`, `optimize_completed_broadcast`, `loop_cycle_broadcast`
   - This ensures eval/optimize/loop lifecycle events appear in the system audit trail

3. **Create unified event query endpoint** (`api/routes/events.py`)
   - `GET /api/events/unified` merges EventLog system events + DurableEventStore builder events
   - Common response schema: `{id, timestamp, event_type, source, session_id, payload}`
   - Sorted by timestamp, with pagination support
   - Source discriminator: `"system"`, `"builder"`, or `"broadcast"`

4. **Tests**
   - EventBroker bridge wiring (durable store writes, system log receives lifecycle events)
   - WebSocket→EventLog bridge (eval/optimize/loop events appear in system log)
   - Unified endpoint query (merged results, correct ordering, filtering)

### What does NOT change:
- SSE streaming behavior (still uses in-memory buffer for low latency)
- WebSocket broadcast behavior (still fires to connected clients)
- Existing `/api/events` and `/api/builder/events` endpoints (backwards compatible)
- Frontend code (no changes needed — this is backend coherence)

---

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Initialization order — EventLog must exist before EventBroker | Move EventLog initialization earlier in lifespan function |
| DurableEventStore creates .agentlab directory | Already handled by `Path.mkdir(parents=True, exist_ok=True)` |
| Bridge failure breaks builder operations | Already handled — `_bridge_to_system_log` catches all exceptions |
| Unified endpoint performance with two DB queries | Both are SQLite with indexes on timestamp; merge in Python is fast for reasonable limits |
| Adding new event types to EventLog | VALID_EVENT_TYPES is a set — additive, no breaking changes |

---

## Files Modified

| File | Change |
|------|--------|
| `api/server.py` | Reorder init: EventLog before EventBroker. Wire DurableEventStore + system_event_log |
| `data/event_log.py` | Add new valid event types for eval/optimize/loop broadcasts |
| `api/routes/events.py` | Add `GET /api/events/unified` endpoint |
| `api/routes/eval.py` | Bridge eval_complete broadcast to EventLog |
| `api/routes/optimize.py` | Bridge optimize_complete/pending_review to EventLog |
| `api/routes/loop.py` | Bridge loop_cycle to EventLog |
| `tests/test_event_unification.py` | New: comprehensive tests for the unification |

---

## Success Criteria

1. Builder events persist to `builder_events.db` (survive restart)
2. Builder lifecycle events appear in system `event_log.db`
3. Eval/optimize/loop completion events appear in system `event_log.db`
4. `GET /api/events/unified` returns merged, time-ordered events from all sources
5. All existing tests pass (no regressions)
6. New tests cover bridge wiring, durability, and unified query
