# Live UI Golden Path — Fixes Applied

**Date:** 2026-04-13
**Branch:** feat/live-ui-golden-path-claude-opus

## Fix 1: Build page — "Save to Workspace" button prominence (ISSUE-1)

**File:** `web/src/pages/Build.tsx`
**Change:** Changed the "Save to Workspace" button from a secondary outline style (`border border-gray-300 bg-white text-gray-700`) to a prominent dark style (`bg-gray-900 text-white hover:bg-gray-800`).
**Impact:** The save action now has visual parity with primary actions instead of looking like a secondary/optional step.

## Fix 2: Build page — Post-save navigation banner (ISSUE-2)

**File:** `web/src/pages/Build.tsx`
**Change:** Added a persistent emerald-green save-success banner between the agent stats section and the DraftInsightsPanel. When `saveResult && savedAgent` is truthy, shows "Saved to workspace — ready for the next step" with "Continue to Workbench" and "Continue to Eval" buttons above the fold.
**Impact:** After saving, the next-step actions are immediately visible without scrolling to the preview area.

## Fix 3: Eval Runs — Disabled button guidance (ISSUE-3)

**File:** `web/src/pages/EvalRuns.tsx`
**Change:** Added a tooltip on the disabled "Start Eval" button explaining "Select an agent from the library above to enable this button", plus an amber helper message below the button when no agent is selected.
**Impact:** Users who land on Eval without an agent selected now see clear guidance about what to do.

## Fix 4: Workbench — Send button discoverability (ISSUE-4)

**File:** `web/src/components/workbench/ChatInput.tsx`
**Change:** Replaced the fixed 8x8 icon-only send button with a wider button that shows a "Send" text label when the input has content. The button uses padding-based sizing instead of fixed dimensions.
**Impact:** The send button is now visible and labeled when the user types, making it much easier to discover. Before: tiny icon, after: labeled button.

## Test fixes

**File:** `web/tests/builder-flow.spec.ts`
- Fixed URL pattern assertion that was too strict (rejected `evalCasesPath` param)
- Added `/api/health :: net::ERR_ABORTED` to the ignorable patterns (health polling during page transitions)

**File:** `web/src/pages/Build.test.tsx`
- Updated assertion for "Continue to Eval" button to handle the new duplicate (appears in both the new banner and the original location)

## New test files

- `web/tests/live-golden-path.spec.ts` — Automated golden path test for each page
- `web/tests/live-golden-path-deep.spec.ts` — End-to-end flow test (Build → Workbench → Eval → Optimize → Improvements → Deploy)
- `web/tests/verify-fixes.spec.ts` — Targeted verification of UX fixes

## Verification

- TypeScript: passes (`tsc --noEmit`)
- Unit tests: 392/392 pass (`vitest run`)
- Playwright tests: 3/3 pass (operator-main-journey, builder-flow x2)
- Live golden path: passes (full flow end-to-end)
