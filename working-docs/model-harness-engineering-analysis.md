# Model Harness Engineering Analysis

**Date**: 2026-04-12
**Branch**: `feat/model-harness-engineering-claude`
**Scope**: AgentLab Workbench harness — `builder/workbench.py`, `builder/harness.py`, `builder/workbench_agent.py`, frontend store, API routes

## What the Current Harness Does Well

The existing harness is significantly more mature than a typical first-pass implementation. Recent work has already addressed many fundamentals:

1. **Durable run lifecycle** — Explicit state machine with `queued → running → reflecting → presenting → completed/failed/cancelled`. Terminal states are always persisted before the stream ends.

2. **Server-authoritative budgets** — Enforced at four granularities (iterations, wall-clock, estimated tokens, estimated cost). Breaches produce terminal events with structured reasons.

3. **Cooperative cancellation** — Server-side `cancel_run()` with `cancel_requested_at` flag. Stream loops poll cancellation state by re-reading from the store, so external cancellation requests are honored at event boundaries.

4. **Stale run recovery** — `_recover_stale_runs()` marks in-flight runs older than `AGENTLAB_WORKBENCH_STALE_RUN_SECONDS` as failed during snapshot hydration, preventing ghost runs.

5. **Structured telemetry** — Every durable event carries a telemetry envelope with run/turn/iteration IDs, phase, status, provider/model, duration, tokens, cost, and failure reasons.

6. **Live/mock honesty** — `build_default_agent_with_readiness()` makes mode selection explicit and durable. Mock fallback reasons are surfaced to operators.

7. **Multi-turn conversation management** — `_compact_conversation()` and `_summarize_prior_turns()` keep planner prompts bounded while preserving dialogue context.

8. **Graceful degradation** — `LiveWorkbenchBuilderAgent` catches all exceptions and falls back to `MockWorkbenchBuilderAgent`, so the UI always receives a coherent event stream.

9. **Checkpointing** — `HarnessCheckpoint` snapshots are persisted after each leaf task completes, providing a foundation for resumability.

10. **Rich frontend contract** — Zustand store handles 15+ event types with proper state transitions, metrics display, and multi-turn grouping.

## Most Important Engineering Gaps

### Gap 1: Stream Handler Duplication (Severity: HIGH)

`run_build_stream._stream()` (lines 739–914) and `run_iteration_stream._stream()` (lines 1017–1192) contain ~150 lines of nearly identical event processing:

- `plan.ready` → parse plan tree, persist
- `message.delta` → append message, persist
- `task.started` → update task status, persist
- `task.progress` → append log, persist
- `artifact.updated` → upsert artifact, update turn, persist
- `task.completed` → mark done, apply operations, persist
- `build.completed` → version bump, activity log, persist
- error/budget/cancellation handling

The only differences are: (a) the `build.completed` summary text, (b) the iteration lifecycle owns `iteration.started` filtering in the iteration path, and (c) the initial-build path clears `project["artifacts"]` on `plan.ready` while the iteration path preserves prior artifacts.

**Risk**: Every new cross-cutting concern (heartbeat, verification, context tracking) must be added in two places. Past work has already introduced subtle divergence (e.g., `iteration.started` filtering only in iteration path).

### Gap 2: No Heartbeat / Liveness Signal (Severity: HIGH)

During long-running steps (LLM calls, complex artifact generation), the SSE stream can go silent for 10–60+ seconds. Neither the operator nor the frontend can distinguish "working" from "stalled." The only progress signal is `harness.metrics` emitted every 3 steps — which means the first 2 steps produce zero feedback.

**Impact**: Operators lose trust in long-running sessions. The frontend's stop button is the only escape hatch, and operators don't know when to use it.

### Gap 3: No Progress Verification (Severity: HIGH)

The harness tracks `steps_completed` but never verifies that completed steps produced meaningful output. An agent could:
- Complete a step with no artifact and no operation
- Produce an artifact identical to a prior version
- Emit duplicate artifacts across iterations

None of these would be detected or surfaced. The `reflection.completed` event includes a quality score, but it's computed from artifact counts and template heuristics, not from comparing actual output to prior state.

**Impact**: Fake progress in long-running autonomous loops goes undetected until an operator manually reviews artifacts.

### Gap 4: Context Budget Not Tracked (Severity: MEDIUM)

The `context/` module has `ContextAnalyzer`, `FreshnessTracker`, `MemoryManager`, and `RetentionPolicy` — none of which are wired into the harness. The harness tracks estimated output tokens for cost budgets, but doesn't track:
- Total context size (conversation + plan + artifacts + model)
- Context growth rate across turns
- Proximity to context window limits

**Impact**: Long-running multi-turn sessions accumulate context without bounds. The `_compact_conversation(limit=16)` and `_summarize_prior_turns(limit=6)` caps help, but the underlying project state (artifacts, runs, events) grows monotonically.

### Gap 5: No Structured Run Summary (Severity: MEDIUM)

When a run completes, the `run.completed` event carries the full run object plus presentation manifest. But there's no compact, operator-oriented summary that answers: "What did this run accomplish? What changed? What's the validation status? What's the recommended next action?"

**Impact**: Operator handoff between sessions requires manual review. Cross-session memory can't capture run outcomes without structured summaries. The frontend shows raw metrics but not actionable insights.

### Gap 6: Checkpoint Resume Not Wired (Severity: MEDIUM-LOW)

`HarnessCheckpoint` objects are persisted in `harness_state.checkpoints` but never loaded during run startup. The harness always starts from scratch. When a stale run is recovered, the work is lost — only the terminal state is preserved.

**Impact**: Crashes during long builds lose all progress. Recovery is terminal-only, not resumable.

## Highest-Value Improvements to Implement Now

### 1. Unify Stream Event Processing

Extract the duplicated event handler into `_process_agent_event()`. This is the **foundation** for all other improvements because it provides a single insertion point for cross-cutting concerns.

### 2. Add Heartbeat / Liveness Events

Inject `harness.heartbeat` events at regular intervals during the stream. The heartbeat carries a timestamp and the current phase, enabling the frontend to detect stalls.

### 3. Add Progress Verification

After each `task.completed` event, verify that the step produced meaningful output. Surface `progress.stall` events when steps complete without artifacts or operations, or when artifacts are duplicates of prior versions.

### 4. Add Context Budget Tracking

Wire the existing `context/` modules to compute context utilization metrics. Include context pressure in `harness.metrics` events so operators see when sessions are approaching limits.

### 5. Add Structured Run Summary

Build `build_run_summary()` that produces a compact handoff document from any run (completed, failed, or in-progress). Surface it in the `run.completed` and snapshot payloads.
