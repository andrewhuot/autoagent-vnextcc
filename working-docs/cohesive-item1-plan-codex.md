# Cohesive Item 1 Plan - Codex

## Scope

Execute only Item 1 from `docs/plans/2026-04-12-cohesive-product-hardening.md`: make the main operator journey explicit and guided across BUILD -> WORKBENCH -> EVAL -> OPTIMIZE -> REVIEW -> DEPLOY.

This session must not implement Item 3 truthfulness tasks. Any no-fake-progress or truthfulness copy changes should be limited to next-step guidance needed for Item 1.

## Current Findings

- Branch is `feat/cohesive-journey-guidance-codex` and the worktree started clean.
- No repo-local `AGENTS.md` exists in this checkout; the session-level AGENTS.md instructions are the active working agreement.
- `web/src/components/Sidebar.tsx` already has a guided flow, but it collapses Workbench and Review into broader labels and does not share a typed next-step contract with pages.
- `web/src/pages/Build.tsx` already has local journey panels and Eval handoff helpers, but the guidance is page-specific.
- `web/src/pages/AgentWorkbench.tsx` hydrates Workbench project and plan state but does not present a page-level guided next action.
- `web/src/lib/workbench-api.ts` already defines Workbench bridge/eval/optimize payload types; Item 1 should reuse them rather than inventing a parallel backend state model.
- `web/src/pages/EvalRuns.tsx` is the active EVAL page even though the source plan omitted it from the Item 1 file list. It likely needs a small next-step card so the flow is explicit across the requested EVAL step.
- `web/src/pages/Optimize.tsx`, `web/src/pages/Improvements.tsx`, and `web/src/pages/Deploy.tsx` already contain local CTAs, but their labels and prerequisites are not expressed through one shared page contract.

## Implementation Plan

### Phase 1 - Red Tests For Shared Journey Contract

1. Add shared TypeScript contract tests in the targeted page/unit test slice:
   - `Build.test.tsx`: expects Build to expose a shared next action to run Eval only after a saved/materialized candidate exists, and to show a prerequisite action before that.
   - `AgentWorkbench.test.tsx`: expects Workbench to expose Build -> Eval readiness through a shared next-step card using hydrated project state.
   - `EvalRuns.test.tsx`: expects completed Eval state to guide to Optimize with the completed run id and selected agent.
   - `Optimize.test.tsx`: expects Optimize with proposals/pending review state to guide to Review.
   - `Improvements.test.tsx`: expects Review to guide to Deploy when approved/applied improvements exist and otherwise explain Review is the current step.
   - `Deploy.test.tsx`: expects Deploy with an active canary to guide to promote canary and Deploy without canary to guide to start canary.
2. Run the targeted Vitest command and capture the expected failures.

### Phase 2 - Shared Contract And Reusable Guidance Component

1. Add shared types in `web/src/lib/types.ts`:
   - `OperatorJourneyStep`
   - `OperatorJourneyStatus`
   - `OperatorNextAction`
   - `JourneyStatusSummary`
2. Add a small implementation helper in a frontend lib module, preferably `web/src/lib/operator-journey.ts`, to keep conditions explicit and testable without bloating pages.
3. Add `web/src/components/OperatorNextStepCard.tsx` as a reusable page-level CTA card with:
   - current step label,
   - prerequisite/ready status,
   - next action label,
   - link or button target,
   - short reason text.
4. Wire the component into existing pages only; do not add a new product shell or workflow store.

### Phase 3 - Page Wiring

1. `Build.tsx`: use local saved-agent state to render:
   - prerequisite guidance while a draft is not saved,
   - `Next: run eval` when saved/materialized and ready.
2. `AgentWorkbench.tsx`: use hydrated Workbench store state and existing bridge/presentation fields where present to render:
   - build-in-progress guidance when no materialized model exists,
   - `Next: run eval` when a canonical model or evaluation bridge is ready.
3. `EvalRuns.tsx`: render:
   - setup guidance before an agent/run exists,
   - `Next: optimize candidate` after a completed eval run is available for the selected/completed agent.
4. `Optimize.tsx`: render:
   - prerequisite guidance when no completed eval/run context exists,
   - `Next: review proposals` only when pending reviews or reviewable proposal state exists.
5. `Improvements.tsx`: render:
   - review guidance when pending reviews exist,
   - `Next: deploy approved improvements` when approved/applied improvements exist.
6. `Deploy.tsx`: render:
   - `Next: start canary` when no canary is active,
   - `Next: promote canary` only when a canary is active.
7. `Sidebar.tsx`: align simple guided flow labels with BUILD -> WORKBENCH -> EVAL -> OPTIMIZE -> REVIEW -> DEPLOY.

### Phase 4 - Browser Happy Path

1. Create `web/tests/operator-main-journey.spec.ts`.
2. Mock API state at the browser level and verify the sequence:
   - Build -> Workbench -> Eval -> Optimize -> Improvements/Review -> Deploy.
3. Assert the visible next-step card label and CTA target on each page.
4. Run the Playwright test and fix only Item 1 guidance/link issues found by the test.

### Phase 5 - Verification, Commit, Push, Completion Event

1. Run targeted Vitest for touched page tests.
2. Run the new Playwright spec.
3. Run a broader frontend verification if targeted checks pass and time permits, at minimum `npm run test --` over changed test files.
4. Review `git diff` for scope drift and ensure Item 3 files/tasks were not touched.
5. Commit with a Conventional Commit message.
6. Push `feat/cohesive-journey-guidance-codex`.
7. Run:
   `openclaw system event --text "Done: Codex finished cohesive Item 1 journey guidance on feat/cohesive-journey-guidance-codex" --mode now`

## Risks And Guardrails

- Avoid backend truthfulness changes from Item 3. Only touch API route typing/normalization if the frontend cannot consume existing next-action state safely.
- Avoid duplicating Workbench bridge state. Prefer existing `WorkbenchImprovementBridge`, `WorkbenchPresentation`, and current page state.
- Keep card copy concrete and conditional. Do not say a step is ready unless the page has local evidence for the prerequisite.
- Keep tests independent with mocked page/API state.

## Status Log

- 2026-04-12: Plan created before implementation.
- 2026-04-12: RED test command initially failed because `web/node_modules` was absent and `vitest` was not installed locally. Next action: install frontend dependencies from `web/package-lock.json`, then rerun the same targeted Vitest command.
- 2026-04-12: RED test command rerun after `npm install`: targeted Vitest failed as expected with 12 missing `Operator journey` assertions and 46 existing tests passing.
- 2026-04-12: GREEN targeted Vitest after shared contract/card/page wiring: 6 files passed, 58 tests passed.
- 2026-04-12: Added browser-level `operator-main-journey.spec.ts`; final focused Playwright run passed 1/1 against local Vite on port 5175.
- 2026-04-12: Aligned shared layout journey strip to 6 steps including Workbench; focused Vitest slice passed 7 files, 76 tests.
- 2026-04-12: Final full frontend Vitest passed: 53 files, 372 tests. `npm run build` passed with the existing Vite large-chunk warning. Final browser happy path passed: 1/1 Playwright test.
- 2026-04-12: `git diff --check` passed. Full `npm run lint` still fails on existing repo lint debt outside the Item 1 guidance changes; scoped ESLint over the new guidance files and touched non-baseline-debt files passed.
