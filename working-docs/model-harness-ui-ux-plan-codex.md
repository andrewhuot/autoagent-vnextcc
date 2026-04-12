# AgentLab Model Harness UI/UX Implementation Plan

Date: 2026-04-12
Branch: `feat/model-harness-ui-ux-codex`

## Goal

Improve the current Workbench model harness journey without building a new product surface.
The plan focuses on making existing backend state trustworthy and legible in the current UI.

## Non-Goals

- Do not build a full new review product, deploy flow, or aspirational tab set.
- Do not rewrite the Workbench architecture.
- Do not change provider execution semantics.
- Do not remove existing multi-turn, artifact, source, or trace capabilities.

## Implementation Bundle

### 1. Shared Active-Run Semantics

- Add a small exported helper for active build statuses:
  `starting`, `queued`, `running`, `reflecting`, and `presenting`.
- Use it in:
  - `ChatInput` submit/stop state
  - `ConversationFeed` active-turn rendering
  - `HarnessMetricsBar` visibility
  - status copy where appropriate

Why: reflection and presentation are still part of the run. The UI should not allow a new brief
or hide progress until the terminal event arrives.

### 2. Header And Review Gate

- Split `WorkbenchLayout` header into:
  - top row: project identity, status, progress counter, theme toggle, review CTA
  - second row: `HarnessMetricsBar` when visible
- Make the review CTA stateful:
  - Disabled only when there is no review gate or handoff yet.
  - "Review required" when the gate is ready.
  - "Review blocked" when the gate has blocking reasons.
  - Clicking opens the Activity workspace so the review gate and handoff are visible.

Why: candidate-ready/review-gate/handoff data is already produced; the primary CTA should route
operators to it instead of pretending it is future work.

### 3. Hydration Continuity

- Extend `WorkbenchPlanSnapshot` typing for `harness_state`.
- Map `harness_state.last_metrics` into `harnessMetrics` during hydration.
- Derive terminal notices from `activeRun` during hydration:
  - failed/stale recovery should keep an actionable error/recovery message
  - cancelled runs should keep cancellation reason
- Preserve existing store behavior for live events.

Why: reload is the recovery moment for stale runs. Hydration must not erase the reason.

### 4. Conversation Feed State Notices

- Add a compact notice near the active/latest turn for:
  - waiting for plan
  - running task
  - validating generated outputs
  - preparing review handoff
  - cancelled by operator
  - recovered stale/interrupted run
  - true failure
- Style cancellation/recovery as warning/neutral, not generic red failure.
- Classify turn status labels for `failed` and `cancelled`.
- Render pending untagged user messages so a failed stream before `turn.started` does not hide the user's request.

Why: the feed is the user's main mental model of what happened.

### 5. Artifact Review Honesty

- Replace "Processes paused, click to wake up" with honest artifact-empty copy.
- Add an `Other` category tab for valid backend categories not shown as first-class tabs.

Why: the right side should never imply fake paused processes, and all produced artifacts should be discoverable.

### 6. Reflection Score Normalization

- Normalize reflection scores for display:
  - `0 <= score <= 1` becomes `score * 100`
  - other values are clamped to 0-100
- Use the normalized score for ring color and score text.

Why: `0.85/100` is misleading if the backend emits normalized quality scores.

## Tests

Frontend targeted tests:

- `workbench-store.test.ts`
  - hydrate last metrics from `harness_state`
  - hydrate stale/cancelled terminal notices from `activeRun`
  - exported active-status helper
- `AgentWorkbench.test.tsx`
  - updated honest empty artifact copy
  - review CTA opens Activity/review gate after hydrated terminal presentation
- `ChatInput` coverage through page or component test for reflecting/presenting as in-flight
- `ArtifactViewer.test.tsx`
  - Other category discovers omitted artifact categories
- `ReflectionCard.test.tsx`
  - normalized score `0.85` renders as `85/100`

Backend tests are not expected unless frontend work exposes a missing contract. Current backend tests
already cover review gate, handoff, stale recovery, cancellation, telemetry, and snapshot harness state.

## Verification

Run focused checks first, then broader checks:

1. `cd web && npm test -- src/lib/workbench-store.test.ts src/pages/AgentWorkbench.test.tsx src/components/workbench/ArtifactViewer.test.tsx src/components/workbench/ReflectionCard.test.tsx src/components/workbench/HarnessMetricsBar.test.tsx`
2. `cd web && npm run build`
3. Targeted backend if contracts change:
   `/opt/homebrew/bin/uv run --extra dev python -m pytest tests/test_workbench_streaming.py tests/test_workbench_p0_hardening.py tests/test_harness.py -q`

## Rollout Risk

- Most changes are presentational and state-derivation only.
- The main behavioral change is disabling submission through reflection/presentation, which aligns UI with backend run lifecycle.
- Review CTA remains a routing affordance into existing Activity content; it does not claim promotion has happened.
