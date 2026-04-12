# Model Harness Engineering — Implementation Plan

**Date**: 2026-04-12
**Branch**: `feat/model-harness-engineering-claude`
**Prerequisite**: Analysis at `working-docs/model-harness-engineering-analysis.md`

## Approach

Conservative, additive improvements to the existing harness. No broad rewrites. Each change is independently testable and does not alter existing event contracts or break existing tests.

## Implementation Items

### Item 1: Unify Stream Event Processing

**Files**: `builder/workbench.py`
**What**: Extract the ~150-line duplicated event handler from `run_build_stream._stream()` and `run_iteration_stream._stream()` into a single `_process_agent_event()` method.

**Design**:
- New method: `_process_agent_event(self, *, project, run, event_name, data, plan_root_ref, operations_ref, started_model, mode, brief)` → yields enriched events or terminal sequences.
- The two callers pass mode-specific parameters (`mode="initial"` vs `mode="follow_up"`, brief text for summaries).
- The method handles: plan.ready, message.delta, task.started, task.progress, artifact.updated, task.completed, build.completed, error, harness.metrics, reflection.completed.
- Returns a sentinel or raises on terminal conditions (error, budget breach, cancellation) so callers know to stop.

**Risk**: The two handlers have subtle differences that must be preserved:
- Initial builds clear `project["artifacts"]` on `plan.ready`; iterations preserve prior artifacts.
- `build.completed` summary text differs by mode.
- Iteration path filters agent-emitted `iteration.started` events.
These are handled by the `mode` parameter.

### Item 2: Heartbeat / Liveness Events

**Files**: `builder/workbench.py`, `web/src/lib/workbench-api.ts`, `web/src/lib/workbench-store.ts`
**What**: Inject `harness.heartbeat` events into the stream at regular intervals.

**Design**:
- Track `_last_event_time` in the stream loop.
- After processing each agent event, check if more than `HEARTBEAT_INTERVAL_SECONDS` (default 5s) has elapsed since the last emitted event.
- If so, emit a `harness.heartbeat` with `{timestamp, phase, status, elapsed_ms, steps_completed}`.
- Add `harness.heartbeat` to the `BuildStreamEvent.event` union type.
- Store `lastHeartbeatAt` in the frontend store. The frontend can compute "seconds since last signal" from this.

### Item 3: Progress Verification / Stall Detection

**Files**: `builder/workbench.py`
**What**: After each `task.completed` event, verify that the step produced meaningful output. Emit `progress.stall` events when steps are empty or duplicated.

**Design**:
- New method: `_verify_step_progress(self, *, event_name, data, project, run)` → optional stall event.
- Checks:
  1. `task.completed` with empty `operations` list AND the corresponding task produced no artifact → stall (type: `no_output`)
  2. `artifact.updated` with source identical to an existing artifact of the same category → stall (type: `duplicate_artifact`)
  3. Consecutive `task.completed` events where cumulative operations remain zero → stall (type: `no_progress_run`)
- Stall events carry: `{type, task_id, message, consecutive_empty_steps}`.
- Stalls are informational — they don't terminate the run, but they increment a counter. After `MAX_CONSECUTIVE_STALLS` (default 3), emit a warning-level stall.

### Item 4: Context Budget Tracking

**Files**: `builder/workbench.py`, `web/src/lib/workbench-api.ts`, `web/src/lib/workbench-store.ts`
**What**: Track context window utilization in harness metrics.

**Design**:
- New method: `_estimate_context_size(self, project, run)` → `{total_tokens, conversation_tokens, plan_tokens, artifact_tokens, model_tokens}`.
- Token estimation: `len(json.dumps(obj)) // 4` (same ballpark as existing token estimation).
- Include `context_budget` in the enriched `harness.metrics` and `harness.heartbeat` payloads.
- Add `contextBudget` field to the `HarnessMetrics` frontend type.
- No enforcement — this is observability only. Enforcement would be a future item.

### Item 5: Structured Run Summary

**Files**: `builder/workbench.py`
**What**: Add `build_run_summary()` function that produces a compact, operator-oriented summary of any run.

**Design**:
- Input: `project`, `run`
- Output: `{run_id, status, phase, mode, duration_ms, tokens_used, cost_usd, artifacts_produced, operations_applied, validation_status, validation_checks, stall_count, context_utilization, changes_summary, recommended_action}`
- `changes_summary`: list of `{category, name, action}` from operations (e.g., "added tool: lookup_flight").
- `recommended_action`: heuristic based on status + validation (e.g., "Review and approve", "Fix validation failures", "Resume interrupted run").
- Include summary in `run.completed` and `run.failed` event payloads.
- Include summary in `get_plan_snapshot()` response for page hydration.

## File Change Matrix

| File | Changes |
|------|---------|
| `builder/workbench.py` | Extract `_process_agent_event()`, add heartbeat injection, add `_verify_step_progress()`, add `_estimate_context_size()`, add `build_run_summary()`, wire into stream and snapshot |
| `web/src/lib/workbench-api.ts` | Add `harness.heartbeat` and `progress.stall` to event union, add `contextBudget` to `HarnessMetrics`, add `RunSummary` type |
| `web/src/lib/workbench-store.ts` | Handle heartbeat and stall events, track `lastHeartbeatAt`, track `stallCount` |
| `tests/test_workbench_harness_eng.py` | New test file for all new behavior |

## Test Plan

New test file: `tests/test_workbench_harness_eng.py`

1. **Stream unification**: Run a build stream and verify event sequence matches existing behavior (regression).
2. **Heartbeat**: Mock a slow agent, verify heartbeat events appear in the stream.
3. **Progress verification**: Mock an agent that emits empty task.completed events, verify stall detection.
4. **Context tracking**: Create a project with conversation history and artifacts, verify context size estimation.
5. **Run summary**: Complete a run, verify summary fields in the completed payload.

## Verification Ladder

1. New tests: `uv run --extra dev python -m pytest tests/test_workbench_harness_eng.py -v`
2. Existing workbench tests: `uv run --extra dev python -m pytest tests/test_workbench_streaming.py tests/test_workbench_multi_turn.py tests/test_workbench_p0_hardening.py tests/test_harness.py tests/test_workbench_agent_live.py -q`
3. Frontend tests: `cd web && npm test -- --run`
4. Web build: `cd web && npm run build`

## Ordering

1. Extract `_process_agent_event()` (foundation — all other items build on this)
2. Add heartbeat injection
3. Add progress verification
4. Add context tracking
5. Add run summary
6. Frontend types and store updates
7. Tests
8. Verify
