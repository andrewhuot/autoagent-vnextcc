# Eval Screens Audit & UX Review

**Date:** 2026-04-10
**Branch:** `audit/eval-screens-ux-plan-claude`
**Auditor:** Claude Opus 4.6
**Scope:** All eval-related surfaces — EvalRuns, EvalDetail, ResultsExplorer, Compare, generated eval review, builder-to-eval handoff, and supporting components.

---

## Executive Summary

The eval surfaces are **feature-complete and architecturally sound**. The Build → Eval → Optimize journey is well-wired with proper state handoff, WebSocket real-time updates, and context-preserving navigation. The component library is consistent and the API layer is thorough.

**The main risks are UX polish issues, not structural ones.** The biggest single problem is a conflicting step-numbering system that will confuse first-time users. There are also several correctness bugs (wrong label on in-progress runs, missing back-navigation from detail pages) and density/discoverability issues that accumulate into a "wall of cards" feeling on the EvalRuns page.

**Bottom line:** Ship-ready for power users today, but needs a polish pass before a broader audience. No blocking correctness issues — the two bugs found are cosmetic-misleading rather than data-corrupting.

---

## What Works Well

1. **Builder → Eval handoff is seamless.** `navigateToEvalWorkflow()` carries agent context via URL params + navigation state, pre-opens the eval form, and the "first run journey" banner gives clear guidance. The active-agent Zustand store with sessionStorage persistence means the selection survives page refreshes.

2. **Real-time eval completion.** WebSocket `eval_complete` events fire toast notifications with composite score and pass count, then auto-refetch the runs list. The "Ready for Optimize" banner with one-click carry-forward is genuinely good UX.

3. **Results Explorer is the standout screen.** Score distributions, failure pattern badges, run-to-run diff, search, threshold filtering, annotation workflow, and multi-format export — all in one page that doesn't feel overloaded thanks to the two-column layout.

4. **Generated eval review is thorough.** Category-grouped cases with inline editing, difficulty/behavior badges, safety probe indicators, and accept-all workflow. The `CaseEditor` component preserves the right fields.

5. **Compare page has the right bones.** Statistical significance badge, confidence level, p-value, per-case drill-down with side-by-side variant panels, winner reasoning, and severity/winner/metric filtering.

6. **Empty states are consistently good.** Every page has a purpose-built `EmptyState` with icon, description, CLI hint, and action button. The "Pick an agent to start evaluating" → "Open Build" flow is the right fallback.

7. **Error handling is present everywhere.** `isError` states, retry buttons, toast error messages on mutation failures, and 404/503 handling in the API layer.

8. **API design is clean.** Background task pattern for eval runs, proper 202 responses, structured result models, pagination support, and export endpoints.

---

## Bugs & Correctness Issues

### BUG-1: EvalDetail says "Completed" for in-progress runs (Severity: Medium)

**File:** `web/src/pages/EvalDetail.tsx:91`

```tsx
Completed {formatTimestamp(result.timestamp)} · {result.passed_cases}/{result.total_cases} passed
```

This line always says "Completed" regardless of `result.status`. When an eval is still `running` or has `failed`, the user sees "Completed" with a timestamp, which is misleading. The in-progress banner above (line 76-79) does show the correct status, but the header below it contradicts it.

**Fix:** Use status-aware text: `{result.status === 'completed' ? 'Completed' : 'Started'} {formatTimestamp(result.timestamp)}`.

### BUG-2: Conflicting step numbering will confuse new users (Severity: High-Medium)

**Files:**
- `web/src/components/Layout.tsx:90` — Global journey strip says **"Step 2 of 5"** on `/evals`
- `web/src/pages/EvalRuns.tsx:268,576` — First-run journey says **"Step 3 of 3"**

Both can appear simultaneously. The global journey strip is 5-step (Build → Eval → Optimize → Review → Deploy), while the EvalRuns first-run banner is 3-step (Build → Save → Eval). A new user arriving from Build sees both and has to reconcile "Step 2 of 5" in the header with "Step 3 of 3" in the body.

**Fix:** The EvalRuns first-run banner should not use step numbering, or should use the same 5-step system. Simplest fix: change "Step 3 of 3" to a label like "Saved draft from Build" (which is already partially there at line 574).

---

## UX/Design Issues (Ranked by Severity)

### UX-1: No back-navigation from EvalDetail (Severity: High)

`EvalDetail.tsx` has no breadcrumb, back button, or link to `/evals`. Once a user clicks "View" on a run, they must use browser back or the sidebar. This is the most-visited drill-down page and should have a clear "← Back to Eval Runs" link.

### UX-2: EvalRuns page is a "wall of cards" (Severity: High)

The page stacks 4-5 sections vertically without hierarchy:
1. Agent Selector
2. Optimize banner (conditional)
3. Generator panel (conditional)
4. Eval Sets section
5. Curriculum section
6. Create form (conditional)
7. Comparison mode (conditional)
8. Runs table / Empty state

A new user doesn't know where to look first. The Curriculum section and Eval Sets section compete for attention when the primary action is "start an eval run."

**Recommendation:** Move Curriculum into a collapsible accordion or tab within Eval Sets. Keep the primary run launch and runs table as the dominant visual flow.

### UX-3: Run ID display is cryptic (Severity: Medium)

Run IDs are UUIDs shown as `run_id.slice(0, 8)` (e.g., `a3f2c91d`). In the Results Explorer, full UUIDs are shown in the summary card and run selector. Users can't distinguish runs by these IDs.

**Recommendation:** Show timestamp + category as the primary run label, with truncated ID as secondary. E.g., "safety · 2h ago (a3f2c91d)" instead of just "a3f2c91d".

### UX-4: Comparison mode in EvalRuns is hidden (Severity: Medium)

Users must check exactly 2 checkboxes in the runs table to enter comparison mode. There's no label, tooltip, or hint explaining this. The checkbox column header says "Compare" but the behavior is non-obvious — checking a third shows a toast but doesn't explain the limit upfront.

**Recommendation:** Add a small hint below the table header: "Select two runs to compare side-by-side." Or add a dedicated "Compare 2 Runs" button that enters a selection mode.

### UX-5: Results Explorer auto-selects first example on filter change (Severity: Medium)

`ResultsExplorer.tsx:91-100` — When filters change and the current selection becomes invisible, it auto-selects `filteredExamples[0]`. This means changing a filter jumps the detail panel to a different example. Users may not notice the panel content changed.

**Recommendation:** Clear selection instead of auto-selecting, or add a visual indicator that the selection changed.

### UX-6: Compare page config selector uses raw filenames (Severity: Medium)

Config A/B dropdowns show raw YAML filenames like `agent-v2.yaml`. No model name, no description, no preview of what differs between configs. Users must remember which filename is which.

**Recommendation:** Show `filename (model: claude-sonnet-4-20250514)` or similar enriched labels.

### UX-7: EvalGenerator requires manual JSON editing (Severity: Low-Medium)

When the agent config is auto-loaded from the selected agent, the user sees a large JSON textarea. Most users won't need to edit this — the main action is just "generate from current config." The textarea creates unnecessary friction.

**Recommendation:** Show the config as a read-only preview by default with an "Edit config" toggle for power users.

### UX-8: No pagination on Results Explorer examples list (Severity: Low-Medium)

`ResultsExplorer.tsx:449-493` renders all `filteredExamples` as buttons in a single list. For runs with hundreds of examples, this creates a very long scrolling list.

**Recommendation:** Add virtual scrolling or simple pagination (e.g., show 25 at a time with "Load more").

### UX-9: Score display inconsistency across pages (Severity: Low)

- EvalRuns table: `composite_score.toFixed(1)` → e.g., "82.3"
- EvalRuns toast: `(data.composite * 100).toFixed(1)` → e.g., "82.3"
- Results Explorer: `compositeMean.toFixed(3)` → e.g., "0.823"
- Compare: `variant.composite_score.toFixed(3)` → e.g., "0.823"

The 0-100 vs 0-1 scale is mixed across pages. EvalRuns uses 0-100 (via `percent()`), but Results Explorer and Compare show raw 0-1 scores. This is technically consistent within each page but inconsistent across the eval section.

**Recommendation:** Pick one scale for user-facing composite scores. 0-100 is more intuitive.

### UX-10: Delete case has no confirmation (Severity: Low)

`GeneratedEvalReview.tsx:154-162` — Clicking the trash icon immediately fires the delete mutation. No "Are you sure?" confirmation. Given that generated cases may have been carefully reviewed, accidental deletion is a real risk.

### UX-11: Annotation author is hardcoded to "web" (Severity: Low)

`AnnotationPanel.tsx:31` — `author: 'web'` is always set. In a multi-user scenario, annotations can't be attributed to specific reviewers.

---

## Test Coverage Assessment

**Frontend tests (5 files):**
- EvalRuns: 8 tests — covers start, empty states, handoff, and form controls. Missing: WebSocket, comparison mode, curriculum.
- EvalDetail: 0 tests — no dedicated test file found.
- ResultsExplorer: 1 comprehensive test — covers filter, drill-in, annotate, diff. Missing: export, search, pagination edge cases.
- Compare: 2 tests — covers summary rendering and config validation. Missing: per-case drill-down, significance display.
- EvalGenerator/GeneratedEvalReview: 11 combined tests — good coverage of generation and review flows.

**Backend tests (10+ files):**
- Good coverage of eval pipeline, scoring, caching, contamination detection.
- Pairwise comparison has basic tests but limited statistical edge case coverage.
- Generated evals API is well-tested for CRUD operations.

**E2E tests:**
- `visual-qa.spec.ts` takes screenshots of EvalRuns and EvalDetail but doesn't test functionality.
- `builder-flow.spec.ts` tests the save-to-eval handoff.
- No dedicated e2e flow for: start eval → wait → inspect results → annotate → compare.

**Critical gap:** EvalDetail has zero frontend tests. This is the page users land on most after starting an eval.

---

## Recommended Merge/Implementation Strategy

### Phase 1: Quick Fixes (this branch or immediate follow-up)
1. Fix BUG-1: "Completed" label on in-progress runs — 1 line change
2. Fix UX-1: Add back-navigation link to EvalDetail — ~5 lines
3. Fix UX-10: Add confirmation dialog for case deletion — ~10 lines
4. Resolve step numbering conflict (BUG-2) — change "Step 3 of 3" labels

### Phase 2: UX Polish Sprint (1-2 days)
1. Restructure EvalRuns page hierarchy (UX-2) — collapse Curriculum, emphasize run launch + table
2. Enrich run labels with timestamp + category (UX-3)
3. Improve comparison mode discoverability (UX-4)
4. Normalize score display scale (UX-9)
5. Add EvalDetail test coverage

### Phase 3: Power User Features (follow-up)
1. Paginate/virtualize Results Explorer examples list (UX-8)
2. Read-only config preview in EvalGenerator (UX-7)
3. Enriched config labels in Compare (UX-6)
4. Multi-user annotation support (UX-11)
5. E2E test for full eval journey

---

## Fixes Applied on This Branch

### Fix 1: EvalDetail "Completed" label bug
**File:** `web/src/pages/EvalDetail.tsx:91`
Changed hardcoded "Completed" to status-aware text.

### Fix 2: Back-navigation link on EvalDetail
**File:** `web/src/pages/EvalDetail.tsx`
Added "← Back to Eval Runs" link at top of page.

### Fix 3: Step numbering conflict
**File:** `web/src/pages/EvalRuns.tsx:268,576`
Removed confusing "Step 3 of 3" labels, replaced with contextual text.

---

## Files Changed
- `web/src/pages/EvalDetail.tsx` — bug fix + back-nav
- `web/src/pages/EvalRuns.tsx` — step label fix
- `working-docs/reviews/2026-04-10-eval-screens-audit.md` — this report
