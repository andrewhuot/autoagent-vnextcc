# Model Harness Engineering Implementation Plan - Codex

Date: 2026-04-12
Branch: `feat/model-harness-engineering-codex`

## Goal

Add durable, operator-trustworthy progress and handoff contracts to the existing AgentLab model harness, then close one practical fake-progress gap in the broader Builder task engine.

## Architecture

Keep the Workbench JSON project store as the materialized state for this pass. Add a compact `handoff` manifest to each durable Workbench run and mirror the latest one into `project["harness_state"]["latest_handoff"]`. Continue storing raw events for replay, but give operators and future agents a stable summary that answers "where are we, what happened, what verified, and what next?"

For Builder task progress, keep the existing API shape. Change `progress_task()` so progress updates cannot display terminal-looking 100% unless the task is actually completed through `complete_task()`.

## Task 1: Backend Workbench Handoff Manifest

Files:

- Modify `builder/workbench.py`
- Update `tests/test_workbench_streaming.py`
- Update `tests/test_harness.py`

Steps:

1. Add helper functions to build and update a run handoff manifest:
   - phase/status
   - run/turn/iteration IDs
   - current task ID/title
   - completed/total task counts
   - latest artifact ID/name/category
   - last event name/sequence/time
   - validation status/check counts
   - budget breach/failure/cancel/recovery reason
   - recent checkpoint summary
   - next action

2. Initialize `run["handoff"]` in `_start_run()`.

3. Update `_record_run_event()` to refresh `run["handoff"]` after each event.

4. When `harness.metrics` arrives, persist it to `project["harness_state"]["last_metrics"]`.

5. Update `_harness_state_summary()` to expose:
   - `checkpoint_count`
   - `recent_checkpoints`
   - `last_metrics`
   - `latest_handoff`

6. Ensure `_recover_stale_runs()` updates handoff details after writing `run.recovered`.

7. Include `handoff` in `build_run_completion_payload()`.

8. Add tests proving:
   - streamed runs persist a handoff with progress counts, last event, next action, and validation summary
   - `harness.metrics` is surfaced through `harness_state.last_metrics`
   - snapshots expose recent checkpoints and latest handoff
   - stale recovery records recovery/failure details in the handoff

## Task 2: Frontend Types and Store Hydration

Files:

- Modify `web/src/lib/workbench-api.ts`
- Modify `web/src/lib/workbench-store.ts`
- Update `web/src/lib/workbench-store.test.ts`

Steps:

1. Add a `WorkbenchRunHandoff` TypeScript interface.

2. Add optional `handoff` to `WorkbenchRun`.

3. Add optional `handoff` to terminal run payload handling in the store.

4. Preserve handoff information when merging partial run events.

5. Add snapshot `harness_state` typing and hydrate persisted `last_metrics` into the store.

6. Add store tests that dispatch `run.completed` with handoff data and hydrate persisted metrics.

No visual component is required in this pass because the Trace and Activity views already read `activeRun` and `harness_state` is primarily a backend/snapshot contract. This keeps the UI diff small.

## Task 3: Evidence-Safe Builder Progress

Files:

- Modify `builder/execution.py`
- Update `tests/test_builder_execution.py`

Steps:

1. Add a small helper that determines whether a `BuilderTask` has completion evidence:
   - artifact IDs
   - proposal IDs
   - approval IDs
   - sandbox run ID
   - metadata `validation_result`
   - metadata `eval_bundle_id`
   - metadata `verified_no_artifact_reason`

2. In `progress_task()`, if requested progress is >= 100 and the task is not terminal, clamp to 99 unless there is completion evidence.

3. Record metadata:
   - `progress_clamped_from`
   - `completion_blocked_reason`

4. Publish those fields on the progress event payload.

5. Keep `complete_task()` as the only path that sets status `completed` and progress 100 without relying on progress updates.

6. Update tests:
   - replace the old "progress capped at 100" assertion with "running task clamps terminal-looking progress to 99 without evidence"
   - add a test where evidence allows progress 100
   - ensure `complete_task()` still sets progress 100

## Verification Plan

Run targeted checks first:

- `.venv/bin/python -m pytest tests/test_workbench_streaming.py tests/test_harness.py tests/test_builder_execution.py -q`
- `cd web && npm test -- src/lib/workbench-store.test.ts`

Then run broader meaningful checks:

- `.venv/bin/python -m pytest tests/test_workbench_api.py tests/test_workbench_streaming.py tests/test_workbench_multi_turn.py tests/test_harness.py tests/test_builder_execution.py -q`
- `cd web && npm test -- src/lib/workbench-store.test.ts src/components/workbench/HarnessMetricsBar.test.tsx src/pages/AgentWorkbench.test.tsx`
- `git diff --check`

If environment constraints block `.venv`, use `/opt/homebrew/bin/uv run --extra dev python -m pytest ...` as the repo's prior working fallback.

## Non-Goals

- No broad Workbench rewrite.
- No migration from JSON persistence to SQLite in this pass.
- No full auto-iterate correction loop in this pass.
- No visual redesign.
- No provider-specific live model behavior changes.
