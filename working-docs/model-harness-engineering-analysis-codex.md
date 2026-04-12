# Model Harness Engineering Analysis - Codex

Date: 2026-04-12
Branch: `feat/model-harness-engineering-codex`

## Mission

Improve AgentLab's model harness for long-running agent work, context durability, session handoff, orchestration clarity, operator steerability, verification discipline, and anti-fake-progress behavior. The goal is a coherent high-leverage slice, not a broad rewrite.

## External Research Synthesis

Resources used:

- Claude Code internals and usage model: https://code.claude.com/docs/en/how-claude-code-works
- Anthropic, effective harnesses for long-running agents: https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
- Anthropic, harness design for long-running apps: https://www.anthropic.com/engineering/harness-design-long-running-apps
- Anthropic, managed agents: https://www.anthropic.com/engineering/managed-agents
- OpenAI, harness engineering: https://openai.com/index/harness-engineering/

The shared pattern across these resources is that model quality depends heavily on the harness, not only on prompts. The most relevant ideas for this repo are:

- Keep a durable progress artifact outside the model context. Long-running work should not rely on conversation history or a surviving process.
- Separate brain, hands, and session log. The planner/generator/evaluator loop needs a durable log that can be inspected, replayed, and summarized.
- Make the operator's mental model cheap. A human should see what phase the run is in, what was last done, what verification says, what blocks progress, and what action is next.
- Treat completion as a verified state, not a hopeful event. A "done" event should come after validation/evaluation, not after the generator stops streaming.
- Encode feedback loops and invariants in repo-local contracts and tests. Repeated failures should become visible tools, schemas, or guardrails.

## Current Architecture Strengths

AgentLab already has a strong Workbench harness foundation.

`builder/workbench.py` owns the durable Workbench lifecycle. `run_build_stream()` creates a run envelope, starts a turn, emits `turn.started` and `iteration.started`, consumes builder-agent events, applies structured operations to the canonical model, persists every event, runs reflection/validation, builds presentation data, and ends with `run.completed`.

Run envelopes already contain:

- `run_id`, `project_id`, status, phase, timestamps, and versions
- execution mode, provider, model, and fallback reason
- server-authoritative budget and telemetry summary
- replayable `events`
- persisted messages
- validation and presentation output

The Workbench stream no longer treats `build.completed` as real completion. `builder/workbench.py::_complete_run_stream()` runs `reflect.started`, `reflect.completed`, `validation.ready`, `present.ready`, `turn.completed`, and only then emits terminal `run.completed`. This matches the research pattern of separating generation from verification.

`builder/harness.py` provides a testable harness execution engine with plan, execute, checkpoint, reflect, present, metrics, and iteration events. It is deterministic when model credentials are absent, which keeps tests and local development reliable.

The frontend in `web/src/lib/workbench-store.ts` and `web/src/pages/AgentWorkbench.tsx` already hydrates active runs, turns, validation, presentation, metrics, cancellation, and terminal state from the backend. Existing tests assert the important `build.completed` versus `run.completed` distinction.

The older Builder Workspace stack also has useful primitives: `BuilderStore` persists projects, sessions, tasks, proposals, artifacts, worktrees, sandbox runs, eval bundles, trace bookmarks, and release candidates in SQLite. `BuilderExecutionEngine` tracks task lifecycle and progress.

## Current Gaps

### 1. Durable state exists, but no concise handoff manifest

Workbench persists detailed event arrays, turns, conversation, validation, and presentation. That is good for replay, but it is not the same as a progress file or handoff contract. A resumed harness or operator currently has to parse raw events to answer:

- What is the current phase?
- What task is active?
- What was the last meaningful event?
- How many plan tasks are done?
- What was the latest artifact?
- What verification has run?
- What should happen next?
- Was this run recovered from a stale/interrupted state?

This is exactly the kind of small, durable progress artifact the external resources recommend.

### 2. `harness_state` is too thin for recovery

`get_plan_snapshot()` returns `harness_state`, but the summary only includes `checkpoint_count` and `last_metrics`. Recent checkpoint details are not exposed. `last_metrics` is read from the project but not consistently written from `harness.metrics` events in the Workbench service path.

This makes the checkpoint feature less useful for operator review and future resumability.

### 3. Builder task progress can appear complete without evidence

The broader Builder Workspace task API can call `progress_task(..., progress=100)` while the task remains non-terminal and without an artifact, eval bundle, approval, validation result, sandbox result, or explicit completion call. That creates a fake-progress risk in any UI or orchestrator that reads progress as user-facing truth.

The safer contract is: progress updates may approach completion, but only `complete_task()` should make a task look complete. A non-terminal progress update at or above 100 should clamp to 99 and record why.

### 4. Larger gaps remain but are not the right slice here

The code advertises `auto_iterate`, but the Workbench service does not yet run a real evaluator-driven correction loop after failed validation or low reflection scores. Checkpoints are not full resumability. Workbench events live inside the mutable JSON project snapshot rather than a separate append-only event store. Final validation remains deterministic and shallow.

These are real follow-ups. They are larger than the coherent high-confidence slice chosen for this pass.

## Selected Slice

Ship a durable Workbench handoff/progress manifest plus evidence-safe task progress behavior.

This slice improves:

- long-running session legibility
- context and memory recovery
- operator visibility and steerability
- handoff trust
- anti-fake-progress behavior

It preserves the existing architecture and layers small durable contracts onto it.

## Expected Outcome

After this pass:

- Every Workbench run carries a `handoff` manifest.
- Snapshot hydration exposes `harness_state.latest_handoff`, `harness_state.recent_checkpoints`, and `harness_state.last_metrics`.
- Terminal run payloads include the handoff manifest so the UI and future agents do not need to parse raw events.
- Stale recovery updates the handoff manifest with an interrupted/recovered next action.
- `BuilderExecutionEngine.progress_task()` clamps non-terminal 100% progress to 99 and records a clear metadata reason.
- Tests lock these contracts so future harness changes cannot silently regress them.

## Deferred Follow-Ups

- Move Workbench event persistence from mutable JSON snapshots to a dedicated append-only ledger.
- Implement real evaluator-driven `auto_iterate` correction loops.
- Expand `run_workbench_validation()` to execute generated eval suites and syntax checks for emitted source previews.
- Unify Workbench run events with the older Builder Workspace `EventBroker`/SQLite event model.
- Add resumability that can continue from checkpoints rather than marking stale runs failed.
