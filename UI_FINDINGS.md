# AgentLab UI — End-to-End Golden Path Findings

**Date:** 2026-04-13
**Scenario:** Brand-new user tries to build a lawn & garden store chat agent
(Greenleaf) and carry it from Build → Workbench → Eval → Optimize / Improve →
Deploy.
**API Key Used:** Live `GOOGLE_API_KEY` / `GEMINI_API_KEY`.

## Summary

The core plumbing works. Live Gemini generation, Build→Eval handoff, and
page-to-page agent-context persistence all function after the mock-mode flag
is turned off. But a new user hits several friction walls that make it
"nearly impossible" to ride the golden path in one sitting.

---

## Critical Issues

### 1. Default workspace traps new users in mock mode

**File:** `agentlab.yaml` line 2 (`optimizer.use_mock: true`)

The repo ships with `use_mock: true` baked in. Even when a user exports
`GOOGLE_API_KEY`, the backend prints `"Mock mode explicitly enabled by
optimizer.use_mock"` and the UI bannerizes "Preview mode is on".

The only way a user discovers this is by reading source code or the verbose
banner. There is no obvious toggle in the UI — Setup shows provider cards and
a Mock/Live pill but that pill doesn't actually flip the yaml value.

**Impact:** Even a correctly-credentialed user thinks the product is doing
real inference when it's playing back deterministic strings.

**Fix:** Default `use_mock: false` in the shipped `agentlab.yaml`. When keys
are missing the `providers.py` fallback will auto-drop into mock mode and
surface the reason honestly.

### 2. Optimize cycle silently rejects proposals; Improvements page stays empty

After a full optimize run the backend stores an `optimize/history` attempt
with `status: "rejected_constraints"`. The REST surfaces `/api/opportunities`
and `/api/autofix/proposals` both return empty lists, so the Improvements
page says "No open opportunities". There is zero feedback on the UI explaining
why the cycle produced nothing for the user to review.

**Impact:** A user runs Optimize, sees "cycle complete", walks over to
Improvements, and concludes the product is broken because there's nothing to
accept.

**Fix:** When the optimize history has rejected attempts, Improvements should
surface them as "Tried but rejected" cards with the rejection reason so the
user can understand _why_ no new change is being proposed.

### 3. `Generate Evals` panel doesn't close / auto-refresh cleanly

When a user on a fresh Eval Runs page clicks "Generate Evals", a right panel
opens with an agent name field + config JSON preview + **Generate Eval Suite**
button. This is obscure — most users expect the button to _immediately_ start
generation from the active agent config. Instead they have to understand the
panel and click an inner button.

Once generated, the panel doesn't auto-close and the newly generated set is
not scrolled into view. The user wonders what happened.

**Fix:** Make **Generate Evals** (the top-right CTA) either kick off
generation directly with defaults, or have the inner panel start with a clear
primary action and auto-dismiss on success.

---

## High-Friction Issues

### 4. No "Save Agent" action surfaced after the first build

After `Generate Agent` the right-hand column shows the draft config and
next-step CTAs like "Save & Run Eval" / "Save & Generate Evals". There is no
stand-alone "Save to Library" button. First-time users who want to save
without immediately running eval have to either pick a Save-and-jump CTA or
discover the `Builder Chat` tab.

**Fix:** Add a small secondary "Save agent" link next to "Save & Run Eval"
that simply persists the candidate to the library and stays on Build.

### 5. Workbench page is confusing after a Build

Navigating to `/workbench` right after generating an agent on Build drops the
user into a second chat-style brief pane: "Describe the agent you want to
build." The user already described it on Build. There's no obvious "Continue
with current draft" or "Import draft from Build".

**Fix:** When the Build session has a live draft, Workbench should open with
that draft loaded and the brief pre-populated, or present a one-click
"Import from Build" button above the composer.

### 6. Setup shows API Key inputs that say "Pending" even when env keys exist

The **API Keys & Models** panel lists Google/OpenAI/Anthropic rows with
"Save & Test" buttons and a "Pending" badge. When `GOOGLE_API_KEY` is already
exported in the shell, the UI still shows the key as "Pending" and only
updates after a manual `Save & Test`. That's inconsistent with the backend,
which already treats it as a configured credential.

**Fix:** Render env-provided credentials as "Detected from environment" +
show the provider as green without requiring user action.

### 7. Evals "No eval sets yet" for every new agent

Freshly-built agents have no generated eval cases so the user lands in a
quiet state. There's a helper line ("generate one from your agent config") but
no primary CTA explicitly labelled e.g. "Generate eval suite for
BuildGreenleafLawnAgent". A 1-click path would be useful.

### 8. Deploy "Deploy Version" dialog is hard to reason about

Clicking **Deploy Version** opens a tiny `Select version / Strategy:` row with
3 version candidates, none marked as "recommended" or "last evaluated". A new
user doesn't know which to pick.

---

## Medium Issues

### 9. Mock banner regex captures too broadly

The `Preview mode is on` banner is shown on every page until dismissed —
including pages unrelated to execution (Docs, Settings). It persists across
navigations which can mislead users into thinking the entire app is stuck in
mock mode even after they flip to live.

### 10. No "what just happened" summary after an eval run

After the run completes, the same page just shows a row in the runs table.
There's no "Eval finished — composite 0.74 / 12 passed, 4 failed. Review →
Results Explorer" callout. The journey widget says "You're on Eval. Next up:
Optimize." but the result itself is buried.

### 11. Optimize "Request human approval" flag enabled by default

The checkbox is on by default, which means every single cycle pauses for
human approval. For a user exploring the tool, this increases friction. Make
the default "auto-apply safe changes, surface unsafe ones for approval".

### 12. Mixed nouns: "improvements" vs "proposals" vs "opportunities" vs "change cards"

All four names refer to similar things in different contexts. The UI should
pick one (probably "Improvements") and use it consistently across Review,
Improvements, Auto-fix, and Changes routes.

---

## Low Issues / Polish

### 13. `Preview mode is on` banner doesn't link to "Turn off mock mode"

The banner says "Open Setup" which just scrolls to Setup. It should link to a
clear "Turn off mock mode" toggle.

### 14. Save button hierarchy varies between Prompt and Builder Chat tabs

Prompt tab shows "Save & Run Eval"; Builder Chat tab shows different combos.
A consistent primary CTA per tab would help.

### 15. Journey/Guided-Flow side panel overlaps with the main content on narrow viewports

At 1280px and below the Journey card compresses into the sidebar, making the
already-small main column feel cramped.

---

## What Actually Works Well

- Agent generation from a natural-language brief is fast (sub-3 seconds on
  live Gemini) and produces a tailored XML instruction.
- `Save & Run Eval` handoff carries the agent ID via query string and
  correctly hydrates the Eval Runs page with the right active agent.
- Navigation from Eval → Optimize preserves the active agent in
  sessionStorage (`agentlab.active-agent.v1`).
- Optimize shows a live progress meter with phases (Observe / Analyze /
  Generate / Evaluate / Deploy).
- Deploy history shows all built candidates v1, v2, v3 etc.

---

## Fix Priorities

| # | Area | Severity | Effort | Status |
|---|---|---|---|---|
| 1 | Ship `use_mock: false` by default | High | S | Fixed |
| 2 | Surface rejected optimize proposals on Improvements | High | M | Fixed |
| 3 | One-click "Generate evals" for the active agent | High | S | Fixed |
| 4 | Workbench auto-loads Build draft | Medium | M | Fixed |
| 5 | Setup shows env-based credentials as Detected | Medium | S | Fixed |
| 6 | Deploy "Deploy Version" picks latest candidate by default | Medium | S | Fixed |
| 7 | Add "Save agent" non-jumping button on Build | Low | S | Open |
| 8 | Normalize improvements/proposals/opportunities nouns | Low | M | Open |

### Validation

`web/tests/fix-validation-smoke.spec.ts` checks all six fixes live against the
running dev server (backend on `:8000`, frontend on `:5173`). All 6 tests pass
against the current branch.

- Fix 1: `agentlab.yaml` defaults `optimizer.use_mock: false` and
  `/api/health` reports `mock_mode: false`.
- Fix 2: Improvements page renders a "Tried but rejected" panel when
  `/api/optimize/history` has rejected attempts; falls back to a combined
  empty state when neither opportunities nor rejected attempts exist.
- Fix 3: The top-right "Generate Evals" CTA now fires generation immediately
  for the active agent via `useGenerateEvals()`; the existing `<EvalGenerator>`
  panel is still reachable via a "Customize…" link.
- Fix 4: `/workbench` renders an "Import from Build" banner when the active
  agent is set but no workbench session has started.
- Fix 5: Setup shows a green "Detected from environment" badge with a
  `$GOOGLE_API_KEY` hint when the provider credential comes from the shell.
- Fix 6: Deploy picker auto-selects the latest version (top of the
  version-desc sort) and appends " (latest)" to its option label.

---

## Test Artifacts

- `web/tests/lawn-garden-golden-path.spec.ts` — breadth-first smoke test.
- `web/tests/lawn-garden-deep-probe.spec.ts` — deep friction probe.
- `web/tests/lawn-garden-handoff-probe.spec.ts` — Build→Eval handoff probe.
- `web/tests/lawn-garden-live-full.spec.ts` — full live golden path.
- Screenshots: `web/test-results/lawn-garden*`
