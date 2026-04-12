# AgentLab Model Harness UI/UX Analysis

Date: 2026-04-12
Branch: `feat/model-harness-ui-ux-codex`

## Summary

The Workbench model harness already has a strong backend contract for the core journey:
durable runs, turn records, streaming plan/task/artifact events, reflection, validation,
presentation, review gates, handoff context, cancellation, budget telemetry, and stale-run
recovery. The highest-value UI/UX opportunity is not a new product surface. It is making
that state legible and coherent in the existing `/workbench` journey.

The current frontend contains most of the necessary pieces, but several important states are
hidden, generic, or misleading:

- Review-gate and handoff data exists, but the primary header CTA is disabled.
- Reflecting and presenting are tracked in state, but the active journey can look idle or ready
  before the run is terminal.
- Cancellation, failure, and stale recovery all flow through one generic `error` bucket.
- Refresh can recover stale runs on the backend while the frontend clears the recovered error text.
- Harness checkpoint/last-metrics data exists in snapshots, but the UI does not hydrate it.
- The empty artifact panel says "Processes paused, click to wake up" even though nothing is paused
  and clicking does not start anything.

## Journey Findings

### 1. Starting A New Run

`AgentWorkbench` hydrates the default project, then `ChatInput` posts a natural-language brief to
`/api/workbench/build/stream`. The store optimistically adds the user message and consumes SSE
events into the live plan, artifacts, and run state.

Risk: when a project already has prior artifacts, the backend routes a new brief to follow-up
iteration semantics. The UI does label the composer as a follow-up after turns exist, but pending
untagged messages can disappear until `turn.started` arrives.

### 2. Progress / Plan / Heartbeat / Stall State

Plan and task lifecycle events render well through `PlanTreeView`. `HarnessMetricsBar` shows phase,
steps, tokens, cost, elapsed time, execution mode, and token budget usage.

Risks:

- Metrics are rendered inside the top header row, which competes with project identity and review
  actions.
- Metrics visibility is tied mainly to `starting` and `running`, not all active statuses.
- Snapshot `harness_state.last_metrics` is not typed or hydrated, so reload loses the last known
  heartbeat even though the backend sends it.

### 3. Reflection / Validation / Presentation

Backend streams `reflect.started`, `reflect.completed`, `validation.ready`, `present.ready`,
`turn.completed`, and `run.completed`. The store handles these statuses and persists validation
and presentation.

Risks:

- The feed has no compact phase notice for reflecting/presenting, so the user may not understand
  why a completed build is still active.
- `ChatInput` only treats `starting` and `running` as in-flight, so follow-up messages can be sent
  during reflection/presentation before the candidate is terminal.
- Reflection score display assumes a 0-100 scale even though harness events may emit normalized
  scores such as `0.85`.

### 4. Artifacts And Source Outputs

Artifacts render inline in the feed and in the right-side workspace. Source exports render in a
separate Source Code tab, with ADK/CX file toggles and diff support after iterations.

Risks:

- Category tabs omit valid backend categories like `callback`, `deployment`, `api_call`, `plan`, and
  `note`, so those artifacts are reachable only through "All."
- The empty right pane has fake "paused/wake" copy.

### 5. Follow-Up Iteration

The backend supports `/build/iterate`, the store tracks multi-turn state, and `IterationControls`
support history and diff selection. The main chat also becomes a follow-up composer.

Risk: there are two composer entry points: the main chat and the mini "Iterate" textarea. This can
fragment the mental model. This pass should avoid expanding the iteration UI and keep the main chat
as the primary path.

### 6. Cancel / Failure / Stale Recovery

Backend cancellation and stale recovery are durable. Snapshot hydration can mark stale runs as
failed with `failure_reason=stale_interrupted` and a `run.recovered` event.

Risks:

- Frontend hydration clears `error` even when the snapshot's `active_run` is failed/cancelled.
- Cancelled and recovered states display through the same red error treatment as true failures.
- Turn status styling does not classify `failed` and `cancelled`, so terminal turn labels can look
unclassified.

### 7. Refresh / Reload / Hydration Continuity

The snapshot endpoint includes conversation, turns, active run, artifacts, events, and harness
state. The frontend hydrates conversation and turns, which is good.

Risks:

- Last harness metrics are not hydrated.
- Recovered or cancelled terminal reasons are not derived from `active_run`.
- Review gate/handoff are present under `active_run.presentation`, `active_run.review_gate`, and
  `active_run.handoff`, but the top-level CTA does not use them after refresh.

### 8. Candidate-Ready / Review-Gate / Handoff

Backend terminal payloads expose `presentation.review_gate` and `presentation.handoff`.
`ArtifactViewer` can render this in Activity.

Risk: the visible primary CTA says "Review candidate" but is always disabled with "Coming soon."
This is the largest trust gap in the terminal experience.

### 9. Operator Honesty

The current implementation has good raw data, but a few labels imply behavior that is not true:

- "Processes paused, click to wake up" in an inert panel.
- Disabled review CTA despite existing review state.
- Generic red errors for operator cancellation and recovery.
- Possible score scale mismatch.

## Highest-Value Improvements

1. Make active statuses consistent across layout, input, metrics, and feed.
2. Split the header into a project/action row and a metrics row.
3. Enable a stateful review-gate CTA that opens Activity when review/handoff data exists.
4. Hydrate and display snapshot last metrics and terminal recovery/cancel reasons.
5. Add feed notices for reflecting, presenting, cancelled, recovered, and failed states.
6. Replace fake empty artifact copy and expose "Other" artifact categories.
7. Normalize reflection scores for 0-1 and 0-100 inputs.
8. Add focused tests around these improvements.
