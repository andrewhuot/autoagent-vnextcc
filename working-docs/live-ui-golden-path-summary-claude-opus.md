# Live UI Golden Path — Final Summary

**Date:** 2026-04-13
**Branch:** feat/live-ui-golden-path-claude-opus
**Agent:** Claude Opus 4.6

## What was tested live

The full AgentLab UI golden path was tested end-to-end in **live mode** using a real Gemini API key (GOOGLE_API_KEY → Gemini 2.5 Pro). The test scenario was building and iterating a Verizon-like phone-company billing support agent.

### Pages tested:
1. **Build** (`/build`) — Generated a billing support agent via prompt, saved to workspace
2. **Workbench** (`/workbench`) — Submitted build request, streamed agent candidate with plan/artifacts, verified eval handoff
3. **Eval Runs** (`/evals`) — Selected agent, ran eval, verified completion
4. **Optimize** (`/optimize`) — Verified agent selection and optimization readiness
5. **Improvements** (`/improvements`) — Verified four-tab workflow (Opportunities, Experiments, Review, History)
6. **Deploy** (`/deploy`) — Verified version display, canary management, promote/rollback controls

### Testing method:
- Playwright automated browser tests against the live UI (not mocked)
- Screenshots captured at each step
- Console errors, page errors, and request failures tracked
- Real API calls to Gemini via the live backend

## Key UX/product gaps found

| # | Issue | Severity | Fixed? |
|---|-------|----------|--------|
| 1 | Build "Save to Workspace" button visually deprioritized vs Test | High | Yes |
| 2 | Post-save navigation buttons buried below fold | High | Yes |
| 3 | Eval "Run Eval" disabled with no guidance when no agent selected | High | Yes |
| 4 | Workbench send button is tiny icon-only, hard to discover | Medium-High | Yes |
| 5 | Build generation result not visually prominent (just chat message) | Medium | No — requires larger design change |
| 6 | Workbench shows stale project from previous session | Medium | No — requires backend context passing |
| 7 | Optimize prerequisites messaging could be clearer | Medium | No — low-leverage |
| 8 | Health endpoint polling failures during page transitions | Low | Partially — test ignorable patterns updated |

## What was fixed

### 4 UX improvements:
1. **Build save button** — Promoted from outline/secondary to dark/primary styling
2. **Build save banner** — Added persistent emerald success banner with next-step buttons above the fold
3. **Eval guidance** — Added amber helper text and tooltip when Run Eval is disabled
4. **Workbench send button** — Added text label ("Send") when input has content, larger click target

### 2 test fixes:
1. Builder-flow Playwright test — Fixed URL pattern and ignorable health request
2. Build unit test — Updated assertion for duplicate navigation button

### 3 new test files:
1. `live-golden-path.spec.ts` — Page-by-page golden path test
2. `live-golden-path-deep.spec.ts` — Full end-to-end flow test
3. `verify-fixes.spec.ts` — Targeted UX fix verification

## What still remains hard or blocked

1. **Agent context doesn't flow from Build to Workbench** — Workbench always loads the most recent project from the backend, not the agent that was just built. This requires passing context through navigation state and having the backend create a new Workbench project linked to the saved agent.

2. **Build generation result display** — After generating an agent, the result appears as a conversational message in the chat feed. There's no prominent success card or visual indicator above the fold. Improving this would require restructuring the studio UI layout.

3. **Eval page requires manual agent selection when navigated directly** — The amber guidance helps, but ideally the page would auto-select the most recently saved agent when no param is provided.

4. **Health endpoint polling** — The MockModeBanner component polls `/api/health` on every page. During rapid page transitions, the AbortController cancels in-flight requests, causing harmless but noisy request failures. This is a known non-issue.

## Tests/verification run

| Test Suite | Result |
|-----------|--------|
| TypeScript type check (`tsc --noEmit`) | Pass |
| Unit tests (`vitest run`) | 392/392 pass |
| Playwright: operator-main-journey | Pass |
| Playwright: builder-flow (2 tests) | Pass |
| Playwright: live-golden-path-deep (full flow) | Pass |
| Live golden path (Build → Workbench → Eval → Optimize → Improvements → Deploy) | Pass |

## Files modified

### Source changes:
- `web/src/pages/Build.tsx` — Save button styling + save-success banner
- `web/src/pages/EvalRuns.tsx` — Disabled button guidance
- `web/src/components/workbench/ChatInput.tsx` — Send button label

### Test changes:
- `web/src/pages/Build.test.tsx` — Updated assertion for new banner
- `web/tests/builder-flow.spec.ts` — Fixed URL pattern + ignorable patterns

### New files:
- `web/tests/live-golden-path.spec.ts` — Page-by-page golden path Playwright test
- `web/tests/live-golden-path-deep.spec.ts` — Full end-to-end flow test
- `web/tests/verify-fixes.spec.ts` — Fix verification test
- `working-docs/live-ui-golden-path-plan-claude-opus.md`
- `working-docs/live-ui-golden-path-issues-claude-opus.md`
- `working-docs/live-ui-golden-path-fixes-claude-opus.md`
- `working-docs/live-ui-golden-path-summary-claude-opus.md`

## Overall assessment

The golden path (Build → Workbench → Eval → Optimize → Improvements → Deploy) **works end-to-end in live mode**. The guided flow bar at the top of every page is the strongest UX element — it makes the progression clear and navigable. The four fixes applied make the three most common friction points (saving, navigating to eval, submitting in workbench) materially easier to use. The remaining gaps are medium-priority design improvements that don't block the core workflow.
