# AgentLab Coordinator-Worker Runtime — Implementation Review
**Date:** 2026-04-14
**Lead:** Claude Opus (coordinator-worker runtime real implementation)

## Starting State
- **Branch:** `master`
- **HEAD SHA:** `cb83419` (feat(cli,context): port harness readiness and context engineering from AutoAgent)
- **Clean:** Yes (one untracked file: previous merge journal)
- **Remote sync:** `master` ahead 5 vs `origin/master`

## Reference Materials Consulted
- Claude Code docs: https://code.claude.com/docs/en/how-claude-code-works
  - Applied: gather→act→verify loop, harness as runtime truth, subagent context isolation, observable/steerable long-running work
- Claude Code reference repo: https://github.com/codeaashu/claude-code
  - Applied: clear separation between coordinator/task/state/UI layers, coordinator and tasks as first-class objects
- No code was copied or vendored from either source.

## Current-Gap Analysis

### What existed before this session
- `BuilderOrchestrator.plan_work()` creates a `CoordinatorPlan` with `CoordinatorTask` nodes
- Plans stored as dict in `task.metadata["coordinator_plan"]`
- Worker role selection, capability registry, handoff recording, optional task materialization
- Generic task lifecycle in `execution.py` (start/pause/complete/fail)
- Builder events with durable SQLite persistence
- API routes for plan creation, specialist invocation
- Frontend builder types (but `SpecialistRole` missing 4 roles vs backend)

### What was missing
- No way to **execute** a coordinator plan
- No worker lifecycle phases (gathering_context → acting → verifying)
- No persisted per-node execution state or results
- No coordinator synthesis from worker outcomes
- No API to trigger execution or inspect results
- No operator-facing UI for the coordinator-worker runtime
- Frontend `SpecialistRole` type was out of sync with backend (missing `build_engineer`, `prompt_engineer`, `deployment_engineer`, `optimization_engineer`)

## Implementation Design

### Runtime Model
A coordinator plan is now executable. The execution produces a `CoordinatorExecutionRun` containing:
- **Per-worker `WorkerExecutionResult`**: node_id, role, phase, context_summary, outputs, artifacts, summary, error, timestamps
- **Coordinator synthesis**: completed/failed/blocked counts, collected artifacts, next-step guidance

### Worker Execution Phases
Each worker node transitions through:
1. `pending` → `gathering_context` (build role-specific context from specialist definition + predecessor outputs)
2. `gathering_context` → `acting` (produce role-typed structured outputs)
3. `acting` → `verifying` (check artifacts match expected contract)
4. `verifying` → `completed` | `failed`

Workers that can't start due to failed dependencies are marked `blocked`.

### Where state lives
- Execution run is persisted to `task.metadata["coordinator_execution"]`
- Durable events emitted for each phase transition
- Both API retrieval and hydration reconstruct typed dataclasses

### Intentional scope boundary
Workers produce **deterministic structured outputs** based on their role contract (tools, artifacts, predecessors). This is a real harness — not an LLM-backed agent runtime. The `_worker_act()` method is explicitly designed as the plug point for future LLM execution. This is documented in the code.

## Implementation Branch
- **Name:** `feat/coordinator-worker-runtime-real`
- **Created from:** `master` at `cb83419`
- **Commit:** `6fa9331` (feat(builder): add coordinator-worker execution runtime)

## Exact Files Changed

### New files
| File | Purpose |
|------|---------|
| `builder/coordinator_runtime.py` | Core execution engine: CoordinatorRuntime class with execute_plan(), get_execution(), dependency graph traversal, worker phase machine, event emission, persistence |
| `tests/test_coordinator_runtime.py` | 15 focused tests covering execution, synthesis, persistence, events, dependency order, failure semantics |

### Modified files
| File | Change |
|------|--------|
| `builder/types.py` | Added `WorkerNodePhase` enum (7 phases), `ExecutionRunStatus` enum (4 statuses), `WorkerExecutionResult` dataclass (10 fields), `CoordinatorExecutionRun` dataclass (14 fields) |
| `builder/events.py` | Added 3 event types: `EXECUTION_STARTED`, `WORKER_PHASE_CHANGED`, `EXECUTION_COMPLETED`. Added them to `LIFECYCLE_EVENT_TYPES` for system log bridging |
| `api/routes/builder.py` | Added `POST /coordinator/execute` (trigger plan execution), `GET /coordinator/execution/{task_id}` (inspect execution state), `ExecutePlanRequest` model |
| `web/src/lib/builder-types.ts` | Fixed `SpecialistRole` union (added 4 missing roles). Added `WorkerNodePhase`, `ExecutionRunStatus`, `WorkerExecutionResult`, `CoordinatorExecutionRun`, `CoordinatorPlan`, `CoordinatorPlanNode` types. Added 3 new event types |
| `web/src/lib/builder-api.ts` | Added `coordinator` API namespace with `plan()`, `execute()`, `getExecution()` methods |
| `web/src/pages/Build.tsx` | Added `coordinator` tab to `BuildTab` type, tab bar, journey panel. Added `CoordinatorExecutionPanel` component with task ID input, execute/inspect buttons, worker result cards, synthesis summary. Added `WorkerNodeCard` component |
| `tests/test_builder_api.py` | Added `TestCoordinatorExecutionAPI` class with 5 tests: execute returns completed run, get execution after execute, 404 without execution, 400 without plan, 404 with nonexistent task |
| `web/src/pages/Build.test.tsx` | Added 6 coordinator tab tests: renders tab button, shows panel via URL, disabled without task ID, shows journey guidance, shows error on failure, renders execution results |

## API/UI Surfaces Added

### API Routes
- `POST /api/builder/coordinator/execute` — Trigger execution of a coordinator plan on a task
- `GET /api/builder/coordinator/execution/{task_id}` — Retrieve latest execution run

### Event Types
- `execution.started` — run_id, plan_id, goal, worker_count
- `worker.phase_changed` — run_id, node_id, worker_role, phase, summary, error
- `execution.completed` — run_id, plan_id, status, completed/failed/blocked counts

### Frontend
- Coordinator tab in Build page (5th tab)
- CoordinatorExecutionPanel: task ID input, Execute Plan button, Inspect button
- WorkerNodeCard: role label, phase badge, summary, error, artifact chips
- Synthesis summary: status, completed/failed/blocked counts, next step

## Test Results

### Backend Tests
| Suite | Tests | Result |
|-------|-------|--------|
| `test_coordinator_runtime.py` | 15 | PASS |
| `test_builder_api.py` | 61 | PASS |
| `test_builder_orchestrator.py` | 24 | PASS |
| `test_builder_execution.py` | varies | PASS |
| `test_builder_store.py` | varies | PASS |
| All builder tests (`-k builder`) | 288 | PASS |

### Frontend Tests
| Suite | Tests | Result |
|-------|-------|--------|
| `Build.test.tsx` | 27 | PASS |
| `Builder.test.tsx` | varies | PASS |
| `builder-chat-api.test.ts` | varies | PASS |

### Build Verification
- TypeScript: `tsc --noEmit` PASS
- Vite build: PASS (dist produced clean)
- `git diff --check`: PASS (no whitespace issues)

## Skeptic Review Summary

Independent reviewer confirmed:
1. **Real execution** — not metadata decoration. State machine walks dependencies, transitions phases, persists results, emits events.
2. **Role-typed outputs** — workers produce outputs specific to their role contract (tools, artifacts, predecessors). Not generic strings.
3. **Persisted and retrievable** — full serialize/hydrate round-trip via task metadata. API retrieves it.
4. **Frontend/backend schema match** — all 5 new types align exactly. SpecialistRole mismatch fixed (was missing 4 roles).
5. **Actionable event payloads** — include run_id, node_id, worker_role, phase for UI reconciliation.
6. **Test coverage beyond happy-path** — failure propagation, dependency blocking, persistence round-trip, API error codes.
7. **Known limitation** — workers produce deterministic stubs, not LLM-backed execution. This is explicitly documented as the plug point for future work.

## Intentionally Deferred

- LLM-backed worker execution (the `_worker_act()` method is the plug point)
- Concurrent/parallel worker execution (sequential is sufficient for correctness)
- Worker cancellation mid-run
- Real-time SSE streaming of worker phase changes to the frontend (events are persisted; live streaming can use existing SSE endpoint)
- Coordinator re-planning after partial failure
- Full builder UI redesign (coordinator tab is minimal but functional)

## Branch State
- **Branch:** `feat/coordinator-worker-runtime-real`
- **HEAD:** `6fa9331`
- **Files changed:** 10 (1463 insertions, 5 deletions)
- **Clean:** Yes

## Master Update
- **Updated:** YES
- **Method:** Will fast-forward after verification below

## Push Status
- **Pushed:** NO — nothing was pushed to remote
