# Cohesive Product Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the newly-landed remediation work into a cohesive, trustworthy product by closing the remaining end-to-end UX gaps, tightening truthfulness, and smoothing the main BUILD → EVAL → OPTIMIZE → REVIEW → DEPLOY journey.

**Architecture:** Build on the seven landed branches rather than inventing new surfaces. The next wave should focus on one coherent product spine: explicit workspace state, evidence-backed Workbench output, typed Eval/Optimize handoff, unified review, durable events/tasks, and a guided operator flow across those states. Prefer incremental hardening of existing routes/pages/stores over adding more one-off features.

**Tech Stack:** FastAPI, Python, SQLite-backed stores, React, TypeScript, React Query, Vitest, Playwright, pytest.

---

## Outcome to Optimize For

A first-time operator should be able to:
1. start the server correctly or recover if it starts incorrectly,
2. build an agent draft,
3. save/materialize it,
4. run evals,
5. hand off into optimize,
6. review proposals in one place,
7. deploy and promote,
8. restart the server,
9. still see the durable state/history,
10. never be lied to by the UI about what is or is not actually complete.

---

## Item 1: Make the main operator journey explicit and guided

**Why this is first:** The product now has many of the right building blocks, but the user journey still risks feeling like a collection of adjacent pages. This item makes the core flow feel like one intentional product.

**Files:**
- Modify: `web/src/pages/Build.tsx`
- Modify: `web/src/pages/AgentWorkbench.tsx`
- Modify: `web/src/pages/Optimize.tsx`
- Modify: `web/src/pages/Improvements.tsx`
- Modify: `web/src/pages/Deploy.tsx`
- Modify: `web/src/lib/api.ts`
- Modify: `web/src/lib/types.ts`
- Modify: `web/src/components/Sidebar.tsx`
- Modify: `api/routes/workbench.py`
- Modify: `api/routes/eval.py`
- Modify: `api/routes/optimize.py`
- Test: `web/src/pages/Build.test.tsx`
- Test: `web/src/pages/AgentWorkbench.test.tsx`
- Test: `web/src/pages/Optimize.test.tsx`
- Test: `web/src/pages/Improvements.test.tsx`
- Test: `web/src/pages/Deploy.test.tsx`
- Create: `web/tests/operator-main-journey.spec.ts`

### Task 1.1: Define the journey-state contract

**Step 1: Write the failing test**

Add a route/state-level test that expects each core page to expose the next recommended operator action and link target.

**Step 2: Run test to verify it fails**

Run: `cd /Users/andrew/Desktop/agentlab/web && npm run test -- src/pages/Build.test.tsx src/pages/AgentWorkbench.test.tsx src/pages/Optimize.test.tsx`

Expected: FAIL because pages do not yet present a coherent shared next-step contract.

**Step 3: Write minimal implementation**

Add a shared TypeScript type like:
- `OperatorJourneyStep`
- `OperatorNextAction`
- `JourneyStatusSummary`

Thread it through existing API payloads where already available from Workbench/eval/optimize/review/deploy state.

**Step 4: Run test to verify it passes**

Run the same command and expect the targeted tests to pass.

**Step 5: Commit**

```bash
git add web/src/lib/types.ts web/src/lib/api.ts web/src/pages/*.tsx web/src/pages/*.test.tsx
git commit -m "feat: add shared operator journey state contract"
```

### Task 1.2: Add guided next-step cards to the core pages

**Step 1: Write the failing test**

Add UI tests that expect:
- Build/Workbench to say “Next: run eval” only when materialized and ready.
- Optimize to say “Next: review proposals” only when proposals exist.
- Deploy to say “Next: promote canary” only when a canary is active.

**Step 2: Run test to verify it fails**

Run targeted Vitest for the touched pages.

**Step 3: Write minimal implementation**

Add a lightweight, reusable next-step banner/card component used across the main pages. Reuse existing route information and typed handoff state; do not invent new backend-only states unless necessary.

**Step 4: Run test to verify it passes**

Re-run targeted Vitest suite.

**Step 5: Commit**

```bash
git add web/src/pages/*.tsx web/src/pages/*.test.tsx web/src/components
git commit -m "feat: guide core operator journey with next-step cards"
```

### Task 1.3: Validate the full flow in browser automation

**Step 1: Write the failing test**

Create `web/tests/operator-main-journey.spec.ts` that walks the expected happy path across Build/Workbench/Eval/Optimize/Review/Deploy with mocked API state.

**Step 2: Run test to verify it fails**

Run: `cd /Users/andrew/Desktop/agentlab/web && npx playwright test tests/operator-main-journey.spec.ts`

**Step 3: Write minimal implementation**

Tighten route linking, CTA labels, and empty-state messaging until the flow is sequential and non-ambiguous.

**Step 4: Run test to verify it passes**

Re-run Playwright test.

**Step 5: Commit**

```bash
git add web/tests/operator-main-journey.spec.ts web/src/pages web/src/components
git commit -m "test: validate primary operator journey end to end"
```

---

## Item 2: Finish the Workbench → Eval → Optimize experience, not just the typed bridge

**Why this matters:** The typed bridge is now real, but it still needs to feel like a product feature rather than an implementation detail.

**Files:**
- Modify: `builder/workbench.py`
- Modify: `builder/workbench_bridge.py`
- Modify: `api/routes/workbench.py`
- Modify: `api/routes/eval.py`
- Modify: `api/routes/optimize.py`
- Modify: `web/src/lib/workbench-api.ts`
- Modify: `web/src/lib/workbench-store.ts`
- Modify: `web/src/components/workbench/ArtifactViewer.tsx`
- Modify: `web/src/pages/AgentWorkbench.tsx`
- Modify: `web/src/pages/Optimize.tsx`
- Test: `tests/test_workbench_multi_turn.py`
- Test: `tests/test_workbench_eval_optimize_bridge.py`
- Test: `web/src/components/workbench/ArtifactViewer.test.tsx`
- Test: `web/src/pages/AgentWorkbench.test.tsx`
- Test: `web/src/pages/Optimize.test.tsx`

### Task 2.1: Tighten readiness states for the bridge

**Step 1: Write the failing test**

Add tests that distinguish these states explicitly:
- draft only
- structurally valid but not materialized
- ready for eval
- eval run complete and ready for optimize
- blocked with clear reasons

**Step 2: Run test to verify it fails**

Run targeted Python + Vitest bridge tests.

**Step 3: Write minimal implementation**

Extend the bridge contract with explicit display-oriented readiness states and user-safe reason strings. Avoid backend magic; make the state machine more explicit.

**Step 4: Run test to verify it passes**

Re-run targeted bridge tests.

**Step 5: Commit**

```bash
git add builder/workbench_bridge.py api/routes/workbench.py tests/test_workbench_eval_optimize_bridge.py web/src/lib/workbench-api.ts web/src/components/workbench/ArtifactViewer.test.tsx
git commit -m "feat: clarify workbench bridge readiness states"
```

### Task 2.2: Add a one-click guided handoff from Workbench to Eval

**Step 1: Write the failing test**

Add a UI test that expects a clear CTA on AgentWorkbench when the candidate is eval-ready, with prefilled request context.

**Step 2: Run test to verify it fails**

Run AgentWorkbench/Optimize tests.

**Step 3: Write minimal implementation**

Use the existing materialization/bridge endpoint to provide a direct “Open Eval with this candidate” action that carries the candidate identity and relevant prefill state.

**Step 4: Run test to verify it passes**

Re-run the targeted tests.

**Step 5: Commit**

```bash
git add web/src/pages/AgentWorkbench.tsx web/src/pages/AgentWorkbench.test.tsx web/src/pages/Optimize.tsx web/src/pages/Optimize.test.tsx
git commit -m "feat: add guided eval handoff from workbench"
```

### Task 2.3: Make optimize entry conditions explicit and humane

**Step 1: Write the failing test**

Add tests that require Optimize to explain why a candidate is not yet optimizable (e.g. missing eval run) instead of appearing inert.

**Step 2: Run test to verify it fails**

Run Optimize tests.

**Step 3: Write minimal implementation**

Show blocking reasons from the bridge contract in Optimize and link back to the exact prerequisite step.

**Step 4: Run test to verify it passes**

Re-run Optimize tests.

**Step 5: Commit**

```bash
git add web/src/pages/Optimize.tsx web/src/pages/Optimize.test.tsx
git commit -m "feat: make optimize preconditions explicit"
```

---

## Item 3: Finish trustfulness and “no fake progress” across the remaining weak surfaces

**Why this matters:** The product still has a few places where the UI can imply more confidence or completion than the underlying evidence warrants.

**Files:**
- Modify: `api/routes/judges.py`
- Modify: `api/routes/context.py`
- Modify: `api/routes/autofix.py`
- Modify: `api/routes/optimize.py`
- Modify: `judges/drift_monitor.py`
- Modify: `context/analyzer.py`
- Modify: `web/src/pages/AutoFix.tsx`
- Modify: `web/src/pages/Optimize.tsx`
- Modify: `web/src/lib/types.ts`
- Test: `tests/test_truth_surface_wiring.py`
- Test: `tests/test_api.py`
- Test: `web/src/pages/AutoFix.test.tsx`
- Test: `web/src/pages/Optimize.test.tsx`

### Task 3.1: Finish drift truthfulness

**Step 1: Write the failing test**

Add a regression test that requires drift APIs to expose whether they are operating on real verdict history versus empty/default inputs.

**Step 2: Run test to verify it fails**

Run targeted pytest for judges/truth-surface wiring.

**Step 3: Write minimal implementation**

If a real verdict persistence bridge is easy to wire, do it. If not, return explicit metadata indicating that auto-pause/gating is not active because real verdict history is unavailable.

**Step 4: Run test to verify it passes**

Re-run targeted pytest.

**Step 5: Commit**

```bash
git add api/routes/judges.py judges/drift_monitor.py tests/test_truth_surface_wiring.py
git commit -m "feat: make drift trust state explicit"
```

### Task 3.2: Finish context-report truthfulness in the UI

**Step 1: Write the failing test**

Add frontend tests that expect the UI to handle `status: "no_data"` honestly instead of reading zeros as healthy.

**Step 2: Run test to verify it fails**

Run relevant Vitest suite.

**Step 3: Write minimal implementation**

Update TypeScript types and UI rendering to show a meaningful “no aggregate data yet” state with guidance.

**Step 4: Run test to verify it passes**

Re-run targeted tests.

**Step 5: Commit**

```bash
git add web/src/lib/types.ts web/src/pages web/src/components tests
git commit -m "feat: render context no-data state honestly"
```

### Task 3.3: Make AutoFix and Optimize non-magical

**Step 1: Write the failing test**

Add tests that require the UI/API to distinguish proposal/apply behavior from validated/evaluated/deployed behavior.

**Step 2: Run test to verify it fails**

Run targeted AutoFix/Optimize tests.

**Step 3: Write minimal implementation**

Make button labels, status chips, and response summaries explicit about what happened and what did not happen.

**Step 4: Run test to verify it passes**

Re-run targeted frontend + pytest slices.

**Step 5: Commit**

```bash
git add api/routes/autofix.py web/src/pages/AutoFix.tsx web/src/pages/Optimize.tsx tests web/tests
git commit -m "feat: remove magical language from autofix and optimize"
```

---

## Item 4: Smooth the operational continuity story across restart, history, and event viewing

**Why this matters:** The product is more durable now, but it still needs to feel dependable after restart and during long-running use.

**Files:**
- Modify: `api/tasks.py`
- Modify: `api/routes/events.py`
- Modify: `api/routes/builder.py`
- Modify: `builder/chat_service.py`
- Modify: `api/server.py`
- Modify: `web/src/pages/Build.tsx`
- Modify: `web/src/pages/EvalRuns.tsx`
- Modify: `web/src/pages/Improvements.tsx`
- Modify: `web/src/pages/AgentWorkbench.tsx`
- Test: `tests/test_p0_journey_fixes.py`
- Test: `tests/test_event_unification.py`
- Test: `web/src/pages/Build.test.tsx`
- Test: `web/src/pages/EvalRuns.test.tsx`
- Create: `web/tests/restart-continuity.spec.ts`

### Task 4.1: Build a single “after restart” continuity test story

**Step 1: Write the failing test**

Create backend + browser tests that simulate:
- active/build session exists,
- restart occurs,
- UI reloads,
- user still sees durable sessions/history/events with honest interrupted state.

**Step 2: Run test to verify it fails**

Run targeted pytest + Playwright.

**Step 3: Write minimal implementation**

Tighten task restoration, builder session loading, event queries, and UI empty/interrupted state handling until the restart story is coherent.

**Step 4: Run test to verify it passes**

Re-run targeted suites.

**Step 5: Commit**

```bash
git add api/tasks.py api/routes/events.py builder/chat_service.py web/src/pages web/tests/restart-continuity.spec.ts tests
git commit -m "feat: make restart continuity coherent across tasks events and builder sessions"
```

### Task 4.2: Improve session/history discoverability

**Step 1: Write the failing test**

Add UI tests requiring that history pages clearly explain current live state vs durable past state.

**Step 2: Run test to verify it fails**

Run targeted page tests.

**Step 3: Write minimal implementation**

Add clear tabs/labels/chips like:
- live
- interrupted
- completed
- historical

Use existing data, not a new store unless necessary.

**Step 4: Run test to verify it passes**

Re-run targeted tests.

**Step 5: Commit**

```bash
git add web/src/pages/EvalRuns.tsx web/src/pages/Build.tsx web/src/pages/*.test.tsx
git commit -m "feat: improve live vs historical state discoverability"
```

---

## Item 5: Do one cohesive product polish pass across navigation, labels, and empty/error states

**Why this matters:** Even when architecture is better, a product can still feel stitched together if labels, badges, and empty states aren’t consistent.

**Files:**
- Modify: `web/src/components/Sidebar.tsx`
- Modify: `web/src/components/Layout.tsx`
- Modify: `web/src/lib/utils.ts`
- Modify: `web/src/lib/types.ts`
- Modify: `web/src/pages/Build.tsx`
- Modify: `web/src/pages/AgentWorkbench.tsx`
- Modify: `web/src/pages/Optimize.tsx`
- Modify: `web/src/pages/Improvements.tsx`
- Modify: `web/src/pages/Deploy.tsx`
- Modify: `web/src/components/MockModeBanner.tsx`
- Test: `web/src/components/Layout.test.ts`
- Test: `web/src/pages/Build.test.tsx`
- Test: `web/src/pages/Improvements.test.tsx`
- Create: `docs/plans/ui-copy-cohesion-checklist.md`

### Task 5.1: Normalize status language

**Step 1: Write the failing test**

Add tests for consistent use of status labels and variants across the key pages:
- blocked
- ready
- interrupted
- review required
- promoted
- rejected
- no data

**Step 2: Run test to verify it fails**

Run targeted frontend tests.

**Step 3: Write minimal implementation**

Centralize variant/label formatting in `web/src/lib/utils.ts` and remove page-specific ad hoc wording where possible.

**Step 4: Run test to verify it passes**

Re-run targeted frontend tests.

**Step 5: Commit**

```bash
git add web/src/lib/utils.ts web/src/pages web/src/components web/src/lib/types.ts
git commit -m "feat: normalize product status language"
```

### Task 5.2: Normalize empty/error states

**Step 1: Write the failing test**

Add tests that require every key page to explain:
- why there is no data,
- what the operator can do next,
- whether the state is expected, blocked, or degraded.

**Step 2: Run test to verify it fails**

Run targeted frontend tests.

**Step 3: Write minimal implementation**

Standardize empty-state and degraded-state copy/components. Reuse workspace invalid, no-data, blocked, and waiting states across pages.

**Step 4: Run test to verify it passes**

Re-run targeted frontend tests.

**Step 5: Commit**

```bash
git add web/src/components web/src/pages web/src/lib/types.ts
git commit -m "feat: standardize empty and degraded state UX"
```

### Task 5.3: Run a final cross-surface UX validation pass

**Step 1: Write a checklist doc**

Create `docs/plans/ui-copy-cohesion-checklist.md` with page-by-page review items for:
- label consistency
- action clarity
- blocked-state clarity
- next-step clarity
- historical vs live state clarity

**Step 2: Run UI review**

Use existing UI/browser testing skill or Playwright coverage to inspect the main pages against the checklist.

**Step 3: Apply minimal polish fixes**

Fix obvious wording, badge, layout, and CTA inconsistencies found in review.

**Step 4: Re-run tests**

Run targeted Vitest + Playwright + `npm run build`.

**Step 5: Commit**

```bash
git add docs/plans/ui-copy-cohesion-checklist.md web/src/components web/src/pages
git commit -m "chore: polish cross-surface ux language and actions"
```

---

## Suggested execution order

1. **Item 1** — make the journey explicit
2. **Item 2** — finish Workbench → Eval → Optimize UX
3. **Item 3** — eliminate remaining trust gaps
4. **Item 4** — strengthen restart/history continuity
5. **Item 5** — final coherence/polish pass

This order matters: the first four items make the product truly function as a coherent system; the fifth makes it feel intentionally designed.

---

## Final verification ladder for the full plan

### Backend
```bash
cd /Users/andrew/Desktop/agentlab
python3 -m pytest \
  tests/test_workspace_state.py \
  tests/test_api_server_startup.py \
  tests/test_truth_surface_wiring.py \
  tests/test_p0_journey_fixes.py \
  tests/test_event_unification.py \
  tests/test_unified_reviews.py \
  tests/test_workbench_multi_turn.py \
  tests/test_workbench_eval_optimize_bridge.py
```

### Frontend targeted
```bash
cd /Users/andrew/Desktop/agentlab/web
npm run test -- \
  src/pages/Build.test.tsx \
  src/pages/AgentWorkbench.test.tsx \
  src/pages/Optimize.test.tsx \
  src/pages/Improvements.test.tsx \
  src/pages/Deploy.test.tsx \
  src/components/Layout.test.ts \
  src/components/MockModeBanner.test.tsx \
  src/components/workbench/ArtifactViewer.test.tsx
```

### Frontend full
```bash
cd /Users/andrew/Desktop/agentlab/web
npm run test
npm run build
```

### Browser flow
```bash
cd /Users/andrew/Desktop/agentlab/web
npx playwright test tests/operator-main-journey.spec.ts tests/restart-continuity.spec.ts
```

### Hygiene
```bash
cd /Users/andrew/Desktop/agentlab
git diff --check
```

---

## Definition of done for this plan

The work is done when:
- the main operator journey feels like one coherent workflow,
- Workbench → Eval → Optimize feels guided rather than merely typed,
- the remaining truth gaps are explicit or genuinely closed,
- restart/history continuity feels dependable,
- status/empty/error states across major pages feel consistent,
- and a fresh user could plausibly use the product without tripping over page-boundary confusion.
