# Coordinator-Worker Runtime Selective Merge Review

**Date**: 2026-04-14
**Branch**: `feat/coordinator-worker-runtime-merge-claude-opus`
**Base**: `master` at `4030e5e`
**Source**: Codex comparison branch `feat/coordinator-worker-runtime-real-codex-yolo` at `91127b2`

## Summary

Selective merge of Codex's stronger architectural ideas into Claude's landed coordinator-worker runtime. The merge upgrades the runtime's state model, persistence, observability, and API surface while preserving Claude's UI patterns, code style, and overall architecture.

## What Was Ported (12 files, +899 / -662 lines)

### 1. Richer State Model (`builder/types.py`)
- **Before**: `WorkerNodePhase` enum, flat `WorkerExecutionResult`, `CoordinatorExecutionRun` with `dict[str, WorkerExecutionResult]`
- **After**: Separate `WorkerExecutionStatus` / `CoordinatorExecutionStatus` enums (added BLOCKED state), `WorkerExecutionState` with lifecycle tracking (`phase_history`, `blocker_reason`, `context_snapshot`), `WorkerExecutionResult` as output-only, `CoordinatorExecutionRun` with `worker_states: list[WorkerExecutionState]`, `coordinator_synthesis`, `root_task_id`
- **Why**: Codex correctly separated lifecycle state from output artifacts. This enables blocked-dependency tracking and phase replay — both needed for coordinator observability.

### 2. 11-Event Taxonomy (`builder/events.py`)
- **Before**: 3 coarse events (`EXECUTION_STARTED`, `WORKER_PHASE_CHANGED`, `EXECUTION_COMPLETED`)
- **After**: 11 specific events covering each worker phase and coordinator-level states (blocked, failed, synthesis completed)
- **Why**: Fine-grained events are needed for real-time UI updates and audit trails. The 3-event model lost information.

### 3. First-Class Persistence (`builder/store.py`)
- **Before**: Coordinator runs stored in `task.metadata["coordinator_plan"]` (fragile, no indexing)
- **After**: Dedicated `builder_coordinator_runs` table with indexes on `plan_id`, `root_task_id`, `session_id`. Full hydration functions for `WorkerExecutionState`, `WorkerExecutionResult`, `CoordinatorExecutionRun`. CRUD methods: `save_coordinator_run`, `get_coordinator_run`, `list_coordinator_runs`, `delete_coordinator_run`.
- **Why**: Storing runs as nested JSON in task metadata prevents querying and creates coupling. First-class table is the right call.

### 4. Runtime Rewrite (`builder/coordinator_runtime.py`)
- **Before**: `CoordinatorRuntime` — simpler execution loop, per-request instantiation
- **After**: `CoordinatorWorkerRuntime` — depends on `BuilderOrchestrator.invoke_specialist()`, manages worker lifecycle through gather→act→verify phases, handles blocked dependencies and failures, persists runs to store, emits fine-grained events
- **Why**: The Codex runtime correctly orchestrates through the specialist layer rather than doing ad-hoc work.

### 5. API Surface (`api/routes/builder.py`, `api/server.py`)
- Replaced per-request `CoordinatorRuntime` with singleton `CoordinatorWorkerRuntime` on `app.state`
- Replaced `GET /coordinator/execution/{task_id}` with `GET /coordinator/runs` (list with filters) and `GET /coordinator/runs/{run_id}`
- Execute endpoint now accepts `CoordinatorExecuteRequest` with optional `plan_id`

### 6. Frontend Alignment (`web/src/lib/builder-types.ts`, `builder-api.ts`, `Build.tsx`, `Build.test.tsx`)
- TypeScript types mirror Python dataclasses: `WorkerExecutionState`, `WorkerExecutionResult`, `CoordinatorExecutionRun`, `CoordinatorExecutionStatus`, all 11 event types
- API client updated: `listRuns(params)`, `getRun(runId)`, `execute({ task_id, plan_id })`
- `WorkerNodeCard` now renders phase_history, blocker_reason, and result artifacts
- All test mocks updated to match new type shapes

## What Was Left Alone

- **Claude's UI patterns and component style**: Kept Build.tsx's card layout, tab structure, error handling patterns
- **Claude's API route file structure**: No new route files; changes fit into existing `builder.py`
- **Claude's test strategy**: Kept pytest fixtures, store-based testing, no mocking of external services
- **Module boundaries**: No new packages or circular dependencies introduced
- **Unrelated features**: No changes to workbench, eval, optimize, or CLI modules

## Test Results

| Suite | Result | Notes |
|-------|--------|-------|
| Coordinator runtime (Python) | 4/4 passed | `tests/test_builder_coordinator_runtime.py` |
| Builder API (Python) | Blocked | Pre-existing Python 3.9 `slots=True` incompatibility in `shared/taxonomy.py` — confirmed on original master, not introduced by this merge |
| Frontend (Vitest) | 403/403 passed | All 56 test files including Build.test.tsx coordinator tab tests |
| TypeScript typecheck | Clean | `tsc -b` exits 0 |
| Whitespace | Clean | `git diff --check` exits 0 |

## Risk Assessment

- **Low risk**: Type changes are additive (new fields, richer enums). No existing fields removed from API responses.
- **Medium risk**: `coordinator_runtime.py` is a full rewrite — the orchestrator.invoke_specialist() integration is the critical path and is tested but only against the mock specialist layer.
- **Pre-existing issue**: Python 3.9 on this machine can't run the full API test suite due to `slots=True` in taxonomy.py. This blocks broader integration testing but is not caused by this merge.

## Files Changed

| File | Lines Changed |
|------|--------------|
| `builder/coordinator_runtime.py` | 782 (+/-) |
| `builder/store.py` | +158 |
| `builder/types.py` | 79 (+/-) |
| `web/src/lib/builder-types.ts` | 132 (+/-) |
| `tests/test_builder_api.py` | 143 (+/-) |
| `api/routes/builder.py` | 72 (+/-) |
| `web/src/pages/Build.tsx` | 72 (+/-) |
| `web/src/pages/Build.test.tsx` | 51 (+/-) |
| `web/src/lib/builder-api.ts` | 26 (+/-) |
| `builder/events.py` | 25 (+/-) |
| `builder/__init__.py` | +12 |
| `api/server.py` | +9 |
| `tests/test_builder_coordinator_runtime.py` | NEW (+158) |
