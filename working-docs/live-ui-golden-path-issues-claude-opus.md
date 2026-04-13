# Live UI Golden Path — Issues Found

**Date:** 2026-04-13
**Branch:** feat/live-ui-golden-path-claude-opus
**Test mode:** Live (GOOGLE_API_KEY active, Gemini 2.5 Pro)

## Critical Issues (Block or seriously degrade golden path)

### ISSUE-1: Build page — "Save to Workspace" button buried in refine phase
**Severity:** High
**Page:** Build (`/build`)
**Description:** After generating an agent from a prompt, the result is shown in a "refine" phase with a chat-like refinement UI. The "Save to Workspace" button is placed below the fold, alongside a "Test Agent" button, inside a Preview/Test section. A first-time user who generates an agent sees a chat message saying the agent was drafted but has no clear, prominent "Save" CTA above the fold. The save action is visually deprioritized relative to the Test action.
**Impact:** Users may not realize they need to save before proceeding to Eval. The Playwright test couldn't find a button matching `/^save/i` because the button text is "Save to Workspace" which doesn't start with just "Save" in isolation.
**Fix:** Add a more prominent save CTA in the generation result area, or auto-scroll to the save action after generation.

### ISSUE-2: Build page — Post-save navigation buttons only appear after scrolling
**Severity:** High
**Page:** Build (`/build`)
**Description:** After saving, "Continue to Workbench" and "Continue to Eval" buttons appear but only below the SaveResultCard, which is itself below the Preview/Test area. Users must scroll down to see these navigation buttons. The journey card at the top does update with "Run eval" but the inline continuation buttons are hidden.
**Impact:** Users who save may not notice the next-step buttons and get stuck wondering what to do next.
**Fix:** Auto-scroll to the SaveResultCard after save, or show a persistent banner at the top with next-step navigation.

### ISSUE-3: Eval Runs page — "Run Eval" button disabled without clear guidance
**Severity:** High
**Page:** Eval Runs (`/evals`)
**Description:** When navigating to `/evals` without URL params, the "Run Eval" button is disabled because no agent is selected. The agent selector shows "No agent selected" but the connection between selecting an agent and enabling the button isn't obvious. The user sees a disabled "Run Eval" button with no tooltip or explanation of why it's disabled.
**Impact:** Users who navigate to Eval directly (not via Build's "Continue to Eval") get stuck.
**Fix:** Add a disabled-state tooltip or inline message explaining "Select an agent first" when the button is disabled.

### ISSUE-4: Workbench — Send button is a tiny icon with no text label
**Severity:** Medium-High
**Page:** Workbench (`/workbench`)
**Description:** The chat input's Send button is an 8x8 icon button (Lucide Send icon) with no text label. When the input is empty, it's rendered in a muted gray that's nearly invisible. The first Playwright test couldn't find it by text because it has no text — only `aria-label="Send"` and `title="Send (⌘↵)"`.
**Impact:** Users may not notice the submit button and miss the keyboard shortcut. Tested: it works when found, but discoverability is poor.
**Fix:** Add a text label or increase the visual prominence of the send button.

## Medium Issues (Friction but not blocking)

### ISSUE-5: Build page — Agent generation result not visually prominent
**Severity:** Medium
**Page:** Build (`/build`)
**Description:** After generating an agent, the result appears as a chat message ("I drafted **Agent Name** on **model** with N tools...") in a conversation-like UI. The config itself is shown in a collapsed details view. There's no clear visual "success" state — just the chat message and a toast notification that disappears quickly.
**Impact:** Users may not realize generation succeeded, especially if they weren't watching.

### ISSUE-6: Workbench — Shows stale project from previous session
**Severity:** Medium
**Page:** Workbench (`/workbench`)
**Description:** The Workbench page hydrates the latest project on load. If the user has previously built something (e.g. "Hotel Reservation Workbench"), that project is shown regardless of what was just built on the Build page. There's no connection between what was saved in Build and what Workbench shows.
**Impact:** Users who go Build → Workbench expect to see the agent they just built.

### ISSUE-7: Optimize page — "Start Optimize" requires prior eval but doesn't clearly link to it
**Severity:** Medium
**Page:** Optimize (`/optimize`)
**Description:** When an agent is selected but no eval has been run, the Optimize page shows "Run an eval first, or Optimize has evidence" but the messaging could be clearer about exactly what's needed.
**Impact:** Minor confusion about prerequisites.

### ISSUE-8: Health endpoint polling failures during page transitions
**Severity:** Low
**Page:** All pages
**Description:** The MockModeBanner polls `/api/health` which goes through the Vite proxy. During page transitions, these requests sometimes fail. Six failures were captured during the test.
**Impact:** No user-visible impact (banner handles failures gracefully), but adds noise to error tracking.

## UX Observations (Not bugs, but improvement opportunities)

### OBS-1: Journey progress bar is excellent
The "Guided flow" bar at the top of every page (Build → Workbench → Eval → Optimize → Review → Deploy) is very well done. It shows the current step, next step, and provides direct navigation. This is one of the strongest UX elements.

### OBS-2: Agent Library selector on Eval/Optimize is clear when used
When an agent IS selected (via URL params or manual selection), the Eval and Optimize pages show the agent name, model, and status clearly. The issue is only with the default empty state.

### OBS-3: Deploy page is clean and functional
Shows active version, canary version, promote/rollback buttons, and deployment history. No issues found.

### OBS-4: Improvements page four-tab workflow is well organized
Opportunities, Experiments, Review, and History tabs are clear and descriptive.

### OBS-5: Workbench build streaming works well
When the send button is found and clicked, the streaming build works smoothly. Plan progress, artifacts, and the eval handoff panel all work correctly. The "Save candidate and open Eval" button works.
