# Model Harness Engineering Integration Plan - Codex

## Goal

Integrate `origin/feat/model-harness-engineering-codex` first and
`origin/feat/model-harness-engineering-claude` second onto current `master` in
the `feat/model-harness-engineering-integration-codex` branch, preserving the
strongest semantics from current master and both engineering branches.

## Starting State

- Current branch: `feat/model-harness-engineering-integration-codex`
- Starting commit: `origin/master` / `0d3e87da407a4d1a81e72176a449753c9aa23f1f`
- Codex source: `origin/feat/model-harness-engineering-codex` /
  `9ac19611677461f8594409c0327ee331570958d5`
- Claude source: `origin/feat/model-harness-engineering-claude` /
  `ad43a7c50f41fa6d1df0eb38c94248aba4f074cb`
- Source branches share merge base
  `336bf17859fb115e5b02083ac2fac06e7a646f4a`, which predates current master
  hardening. Stale deletions from either source branch must not remove current
  master behavior unless explicitly superseded by the requested harness work.

## Integration Order

1. Merge Codex first at repo level.
2. Resolve conflicts by keeping current master hardening plus Codex durable
   continuity and progress-clamp behavior.
3. Merge Claude second at repo level.
4. Resolve overlapping files using Claude as the stream/harness runtime
   backbone, then graft the Codex handoff and harness-state durability back in.

## File-Level Strategy

### `builder/workbench.py`

Use Claude as the runtime backbone:

- Keep unified `_process_agent_events()` for initial and follow-up runs.
- Keep `_iter_with_heartbeat()` and the `_STREAM_END` iterator sentinel.
- Keep heartbeat/liveness events.
- Keep `progress.stall` detection for empty completed steps.
- Keep context budget estimation on heartbeat payloads.
- Keep `build_run_summary()` and terminal `summary` payloads.

Graft Codex durability into that backbone:

- Add durable `_refresh_run_handoff()` and `_build_run_handoff()`.
- Maintain `harness_state.latest_handoff`.
- Include `harness_state.recent_checkpoints` in snapshots.
- Persist `harness_state.last_metrics` from `harness.metrics` events.
- Refresh handoff from `_record_run_event()` so every durable event can carry
  current recovery state.
- Refresh handoff during stale-run recovery.
- Include handoff in terminal run payloads, `turn.completed`, and snapshot
  state.
- Keep current master review-gate presentation behavior; expose both the
  legacy promotion handoff and the newer durable run handoff where clients need
  them.

### `builder/execution.py`

- Keep current master crash recovery.
- Add Codex progress clamp:
  in-flight tasks cannot report 100 percent unless they have completion
  evidence or have reached a terminal lifecycle method.
- Clear progress-blocker metadata on completed, failed, and cancelled tasks.
- Publish clamp metadata in task progress events.

### `web/src/lib/workbench-api.ts`

Union API contracts:

- Add Claude `RunSummary`.
- Extend `HarnessMetrics` with `contextBudget`.
- Add heartbeat and stall stream event types.
- Add Codex `WorkbenchRunHandoff` and `WorkbenchHarnessState`.
- Preserve current master review gate / legacy `WorkbenchHandoff` types.
- Allow `WorkbenchRun` to expose both `summary` and durable `handoff`.
- Allow plan snapshots to include `harness_state` and `run_summary`.

### `web/src/lib/workbench-store.ts`

Union store behavior:

- Add heartbeat/stall state: `lastHeartbeatAt` and `stallCount`.
- Handle `harness.heartbeat` and `progress.stall` events.
- Hydrate harness metrics from persisted `harness_state.last_metrics`.
- Preserve and merge durable `handoff` and `summary` on active runs.
- Keep Codex metric hydration and latest-handoff behavior without regressing
  current master artifact, review-gate, and iteration behavior.

### `web/src/pages/AgentWorkbench.tsx`

- Keep Codex hydration improvement by passing `snapshot.harness_state` into the
  store as `harnessState`.

## Test Strategy

Preserve and run the requested backend test set:

- `tests/test_workbench_harness_eng.py`
- `tests/test_workbench_streaming.py`
- `tests/test_harness.py`
- `tests/test_workbench_p0_hardening.py`
- `tests/test_builder_execution.py`

Preserve and run the requested frontend targeted tests:

- `web/src/lib/workbench-store.test.ts`
- `web/src/pages/AgentWorkbench.test.tsx`
- `web/src/components/workbench/HarnessMetricsBar.test.tsx`

Add or update tests when a merged contract is not covered, especially:

- Terminal payloads expose both `summary` and durable `handoff`.
- Snapshot hydration exposes recent checkpoints, last metrics, and latest
  handoff.
- Store handles heartbeat/stall events and preserves handoff/summary.
- Progress clamp prevents unevidenced 100 percent active progress.

## Verification Ladder

1. Backend targeted tests listed above.
2. Frontend targeted tests listed above.
3. Full frontend test run if practical.
4. Web build.
5. `git diff --check`.

## Delivery

- Commit integrated code, tests, and this plan.
- Push `feat/model-harness-engineering-integration-codex` to origin.
- Report changed areas, test commands and outcomes, branch, commit, and risks.
- Run the required `openclaw system event` completion command.
