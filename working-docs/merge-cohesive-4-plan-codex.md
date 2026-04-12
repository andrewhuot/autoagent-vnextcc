# Merge Plan: Cohesive Four Product Branch Landing

Date: 2026-04-12

Repo: `/Users/andrew/Desktop/agentlab-merge-cohesive-4-codex`

Integration branch: `merge/cohesive-four-codex`

Base at planning time: `origin/master` -> `2e32c26`

## Goal

Merge four cohesive product branches onto current master safely, preserve their intended product semantics, verify the combined result, and push the landed tree to `origin/master` only after green verification.

## Source Context Read

- `/Users/andrew/Desktop/agentlab/docs/plans/2026-04-12-cohesive-product-hardening.md`
- `/Users/andrew/Desktop/agentlab-workbench-harness-claude-code-audit-codex/working-docs/workbench-harness-claude-code-audit-codex.md`

The hardening plan frames the desired final product as one coherent BUILD -> WORKBENCH -> EVAL -> OPTIMIZE -> REVIEW -> DEPLOY spine, with explicit state, evidence-backed handoffs, durable restart behavior, and consistent product language.

The Workbench audit warns against overclaiming autonomy or resumability. Merge resolution should keep operator guidance explicit, but should not turn structural readiness, mock output, or interrupted state into hidden magic.

## Branches Reviewed

1. `feat/cohesive-journey-guidance-codex` @ `7414223`
   - Adds shared operator journey types/helpers, `OperatorNextStepCard`, sidebar/layout journey copy, core page next-step cards, and `web/tests/operator-main-journey.spec.ts`.
   - Main hotspots: `AgentWorkbench.tsx`, `AgentWorkbench.test.tsx`, `EvalRuns.tsx`, `Build.tsx`, `Deploy.tsx`, `Sidebar.tsx`, shared `types.ts`.

2. `feat/cohesive-workbench-eval-optimize-ux-codex` @ `cdb52d4`
   - Adds explicit Workbench bridge readiness/action metadata, Workbench materialize-to-Eval CTA, ArtifactViewer readiness copy, and Optimize guardrails for Workbench-origin candidates without `evalRunId`.
   - Main hotspots: `AgentWorkbench.tsx`, `AgentWorkbench.test.tsx`, `Optimize.tsx`, `Optimize.test.tsx`, `workbench-api.ts`, `workbench_bridge.py`.

3. `feat/cohesive-restart-continuity-codex` @ `e90bcf2`
   - Adds backend/frontend continuity metadata for tasks, eval runs, events, builder chat sessions, Workbench state, and restart/historical UI.
   - Main hotspots: `EvalRuns.tsx`, `WorkbenchLayout.tsx`, `AgentWorkbench.test.tsx`, `Build.tsx`, `Improvements.tsx`, `types.ts`, `workbench-store.ts`.

4. `feat/cohesive-product-polish-codex` @ `3dd1c12`
   - Adds shared status/empty-state language, `statusLabel`/variant helpers, richer `EmptyState`, MockModeBanner copy, page copy normalization, and `docs/plans/ui-copy-cohesion-checklist.md`.
   - Main hotspots: `Sidebar.tsx`, `Build.tsx`, `Deploy.tsx`, `WorkbenchLayout.tsx`, `AgentWorkbench.test.tsx`, `utils.ts`, `types.ts`.

## Chosen Merge Order

1. `feat/cohesive-workbench-eval-optimize-ux-codex`
2. `feat/cohesive-restart-continuity-codex`
3. `feat/cohesive-journey-guidance-codex`
4. `feat/cohesive-product-polish-codex`

## Rationale

This order lands concrete behavior and contracts before broad presentation layers:

- Workbench handoff first, because it creates the most specific Workbench -> Eval -> Optimize contract and the strictest Optimize guardrail: a Workbench candidate without an eval run is not optimizable.
- Restart continuity second, because it adds durable backend/API state and frontend historical/interrupted semantics that the journey UI should surface rather than infer away.
- Journey guidance third, because the shared operator journey card should wrap the now-present Workbench handoff and continuity signals instead of being merged as a generic first draft that later branches might accidentally dilute.
- Product polish last, because it is intentionally a final copy/status/empty-state normalization pass. It should apply labels and empty-state structure to the already-combined behavior without overwriting functional contracts.

## Conflict Strategy

- Preserve one canonical journey model from `web/src/lib/operator-journey.ts` once the journey branch lands.
- Preserve the Workbench-specific Eval handoff CTA and materialization path. The shared journey card answers "where am I in the product flow"; the Workbench handoff panel answers "how do I send this exact candidate to Eval."
- Preserve restart continuity distinctions: live, interrupted, completed, historical, and durable state. Product polish can normalize wording but must not erase the meaning.
- Preserve Optimize preconditions. Workbench-origin Optimize should keep requiring a completed `evalRunId`, even if journey copy says Optimize is the next broad step.
- Rebuild `web/src/pages/AgentWorkbench.test.tsx` thoughtfully if necessary; all four branches touch that harness and assertions.
- In `Sidebar.tsx`, use the canonical Build, Workbench, Eval, Optimize, Review, Deploy journey. Treat Setup as pre-journey operator environment guidance, not as a replacement for Workbench.
- In `Build.tsx`, `Deploy.tsx`, `EvalRuns.tsx`, `Improvements.tsx`, and `WorkbenchLayout.tsx`, keep both stateful product evidence and final polished labels rather than choosing one branch's half-solution.

## Expected Conflict Hotspots

- `web/src/pages/AgentWorkbench.test.tsx`
- `web/src/pages/AgentWorkbench.tsx`
- `web/src/pages/Optimize.tsx`
- `web/src/pages/EvalRuns.tsx`
- `web/src/pages/Build.tsx`
- `web/src/pages/Deploy.tsx`
- `web/src/components/Sidebar.tsx`
- `web/src/components/workbench/WorkbenchLayout.tsx`
- `web/src/lib/types.ts`
- `web/src/lib/utils.ts`
- `web/src/lib/workbench-api.ts`
- `web/src/lib/workbench-store.ts`
- `builder/workbench_bridge.py`

## Verification Ladder

Backend targeted:

```bash
.venv/bin/python -m pytest \
  tests/test_workbench_eval_optimize_bridge.py \
  tests/test_workbench_multi_turn.py \
  tests/test_p0_journey_fixes.py \
  tests/test_event_unification.py
```

Frontend targeted:

```bash
cd web
npm run test -- \
  src/lib/utils.test.ts \
  src/components/EmptyState.test.tsx \
  src/components/Layout.test.ts \
  src/components/MockModeBanner.test.tsx \
  src/components/workbench/ArtifactViewer.test.tsx \
  src/pages/AgentWorkbench.test.tsx \
  src/pages/Build.test.tsx \
  src/pages/EvalRuns.test.tsx \
  src/pages/EventLog.test.tsx \
  src/pages/Optimize.test.tsx \
  src/pages/Improvements.test.tsx \
  src/pages/Deploy.test.tsx
```

Browser flow:

```bash
cd web
npx playwright test tests/operator-main-journey.spec.ts tests/restart-continuity.spec.ts
```

Build and hygiene:

```bash
cd web
npm run test
npm run build
cd ..
git diff --check
```

## Self-Review Checklist

- No duplicate journey cards or competing Workbench handoff CTAs.
- No Optimize path that implies Workbench candidates can optimize before Eval evidence exists.
- Restart/historical/interrupted copy remains truthful.
- Sidebar and page terminology agree on Build, Workbench, Eval, Optimize, Review, Deploy.
- Empty/degraded states include state, reason, and next action where the polished component supports it.
- Search for stale terms after merge: `Improve`, `Candidate ready`, `Stopped`, `Open Improvements`, `Deploy Now`, `pending_review`, `rolled_back`, `no_data`.
