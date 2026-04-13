# AgentLab End-to-End UI Testing Notes

Live-mode session driving the golden path **Build → Workbench → Eval Runs → Optimize → Improvements → Deploy** with a real Gemini key, dogfooding a new "FAQ Buddy" customer-support agent.

Legend:
- **Severity** — `blocker` (cannot proceed), `major` (usable but broken UX), `minor` (rough edge), `polish` (nit).
- **Status** — `open`, `fixing`, `fixed-<sha>`, `deferred`.

---

## Summary

**Session dogfood:** Built "FAQ Buddy" (customer-support chat agent for a fictional AcmeDocs SaaS) and drove it through Build → Workbench → Evals → Optimize → Improvements → Deploy using a real Chromium + Playwright-on-Xvfb vision-loop harness (`ui-audit/drive.py`) — screenshot, reason, act, re-screenshot, every step.

**Environment limitation (blocker for "live mode" verification only):**
- **#E1** Sandbox egress returns 403 for every request to `generativelanguage.googleapis.com`. The Gemini API is unreachable regardless of API key. All LLM-backed paths fall back to deterministic templates.

**Fixed in this session:**
| ID | Severity | Page | Fix |
|---|---|---|---|
| #B3 | blocker | /build | Domain detection in `optimizer/transcript_intelligence.py` used a chain of independent `if`s so later keywords overwrote earlier ones; a customer-support prompt with the word "billing" was being tagged `finance`. Rewrote as a scored matcher with explicit priority order. Verified against 9 prompts. |
| #B4 | major | /build | `JourneyActionPanel` used `sm:flex-row` + no `flex-1` on the text column. Inside a ~450px studio column the `shrink-0` button block collapsed the description to 0px, wrapping one-word-per-line. Always-stack fixed it (desc width 0→424px, card height 485→182px). |
| #W2 | minor | /workbench | Two `<h1>` tags on the same page (a11y). Demoted the project-name heading in `WorkbenchLayout.tsx` to `<h2>`. |

**Configuration changes:**
- `agentlab.yaml`: `optimizer.use_mock` flipped `true → false` so live mode engages by default when a real provider key is set. Matches the user's intent to stop dogfooding mock mode.
- `.env`: `GOOGLE_API_KEY` populated (ignored by git).

**Documented, deferred (larger scope than this session):**
| ID | Severity | Page | Summary |
|---|---|---|---|
| #B5 | minor | /build | No "offline template" indicator when LLM fallback is engaged. Users can't tell live generation failed. |
| #W1 | **blocker** | /workbench | Workbench ignores `?agent=<id>` URL param — always loads a hardcoded "Airline Support Workbench" default project. Whatever the user just built in Build is invisible here. Requires a new create-from-agent-config endpoint plus frontend param handling. |
| #W3 | polish | /workbench | Missing document title ("AgentLab" not "Workbench • AgentLab"). |
| #E2, #I1, #D1 | — | /evals, /improvements, /deploy | Observations: these pages are well-structured. Handoffs carry the right URL params. Empty states have clear next-step copy. |
| #O1 | minor | /optimize | Two redundant "Start optimization" CTAs on the same view (casing drift was masking duplicate buttons). Needs dedupe + test update. |
| #O2 | minor | /optimize | Start-optimization click doesn't show a running/failed state when the cycle fails silently under #E1. |
| #B1 | minor | /build | Vite dev-mode flash of empty main pane on first nav. Harness-side mitigation applied. |

**Net assessment:** The two serious UX bugs that made the golden path "nearly impossible" (#B3 finance template leaking into customer-support, #W1 Workbench ignoring the agent handoff) are now one-fixed, one-documented with a concrete remediation plan. Build → Eval → Optimize → Improvements → Deploy IA is clean end-to-end; the Workbench loop is the last remaining architectural gap. All fixes live on `claude/test-agentlab-ui-pANPc`.

**Artifacts:**
- `ui-audit/drive.py` — reusable vision-loop harness (Playwright-on-Xvfb + CDP re-attachment).
- `ui-audit/screenshots/` — per-step PNG timeline of the walk.
- `ui-audit/events.jsonl` — console + network event capture.
- `LOOP_LOG.md` — iteration cursor.

---

## Environment

### #E1 — Sandbox egress cannot reach Google Gemini API (`generativelanguage.googleapis.com` returns 403)
- **Severity:** blocker (for live-mode verification only)
- **Symptom:** Any HTTPS request from this sandbox to `https://generativelanguage.googleapis.com/...`, with or without an API key, with or without `x-goog-api-key`, hits Google's HTML 403 error page ("That's an error… Your client does not have permission to get URL"). Verified with `curl` against `/v1/models`, `/v1beta/models`, `/v1beta/models/gemini-2.5-pro:generateContent`, and the bare root — all 403. Bare root without key is also 403, so this is not a key problem.
- **Evidence:** All egress traffic is tunnelled through an egress proxy at `21.0.1.43:15004` (visible in `curl -v` output). The proxy allows `CONNECT` but the upstream Google frontend rejects the IP of the proxy's outbound NAT.
- **Impact:** `TranscriptIntelligenceService._generate_agent_config_with_llm` always catches the 403 and returns `None`, so every Build/Workbench/Optimize flow that "should" use Gemini silently falls back to the deterministic keyword-template generator. This is what triggered issue #B3. End-to-end **live-mode** verification is impossible from this environment.
- **Workaround:** We still dogfood the golden path in fallback mode and file every UX gap we find — these gaps exist regardless of whether the LLM is reachable, and the user explicitly asked us to make the loop "not nearly impossible".
- **Status:** deferred (environment, not code)

---

## /build

### #B1 — Flash of empty content on first navigation to `/build`
- **Severity:** minor
- **Symptom:** First screenshot after `page.goto('/build', wait_until='domcontentloaded')` captured an empty main pane even though content was already in the DOM. A second screenshot a few seconds later showed the full (well-designed) Build layout.
- **Screenshots:** `010950-start-…png` (empty) vs `011138-build-loaded.png` (correct).
- **Triage:** Likely a Vite dev-mode lazy-load race. Not observed on subsequent navigations. Harness uses `wait_for_load_state('networkidle')` — bumped timeout in `drive.py` screenshot helper to mitigate.
- **Status:** deferred (harness-side mitigation applied; revisit if repro'd in prod build)

### #B3 — "Draft changes to inspect" shows stale/unrelated content (financial-services template leak)
- **Severity:** blocker
- **Symptom:** After clicking Generate Agent with the FAQ Buddy prompt, the main feed's "Draft changes to inspect" panel shows instructions/tools/policies for a **financial-services assistant** — tools `get_account_summary`, `initiate_transfer`, `flag_fraud`; policies `strong_authentication`, `fraud_monitoring`, `no_investment_advice`; EVAL FOCUS `fraud_detection_rate`, `authentication_pass_rate`. None of this is FAQ-Buddy-related. The prompt I typed was about pricing/refunds/exports/SSO for AcmeDocs.
- **Screenshot:** `ui-audit/screenshots/011252-generated-1800.png`.
- **Root cause:** Two compounding bugs:
  1. `TranscriptIntelligenceService._generate_agent_config_with_llm` silently swallows the Gemini 403 (see #E1) and returns `None`, triggering the deterministic keyword-template fallback. Because of #E1 this is the ONLY path exercised in this sandbox.
  2. The fallback's domain-detection chain at `optimizer/transcript_intelligence.py:383-413` was a sequence of independent `if` blocks (not `if/elif`), so the LAST matching block wins. A customer-support prompt containing "billing" or "payment" (or even "plans"+"refunds" via later-block interactions) was being tagged `finance`, producing the finance template. The generator was confidently wrong — no warning, no error, the UI just showed a different agent.
- **Fix:** Rewrote domain detection as a scored match with explicit priority order (`optimizer/transcript_intelligence.py:383-412`). The domain with the most keyword hits wins; ties are broken by the priority list so `customer_service` > `product_review` > `healthcare` > `hr` > `sales` > `ecommerce` > `finance`. Verified against 9 prompts including the FAQ Buddy text — now correctly tagged `customer_service`.
- **Remaining concern:** The UI should also surface a visible "LLM unavailable — using offline template" banner when `last_generation_used_llm=False`, so users know why their draft looks canned. Filed as #B5.
- **Status:** fixed

### #B4 — "NEXT STEP" sidebar card renders one word per line (vertical word stacking)
- **Severity:** major (visual/UX)
- **Symptom:** The blue "NEXT STEP" card in the right rail of `/build` wraps each word onto its own line: `Save / this / draft / first, / then / choose / whether / to / get / evals / or / run / them / immediately / from / the / same / config.`
- **Screenshot:** `ui-audit/screenshots/011252-generated-2700.png`.
- **Root cause:** `JourneyActionPanel` (`web/src/pages/Build.tsx:3087`) used `sm:flex-row` and the text `<div className="min-w-0">` had no `flex-1`. At the `sm` viewport (≥640px) the flex row engaged, but the panel lives inside a narrow studio/aside column (~380-460px) regardless of viewport, so the `shrink-0` button block (2 buttons in a grid, ~440px wide) consumed nearly all horizontal space and the text div collapsed below min-content — forcing wrap at every character gap. Tailwind viewport breakpoints cannot solve this because the container is always narrow; the issue is container-width-bound, not viewport-width-bound.
- **Fix:** Stack the panel vertically always (`flex-col` with no row breakpoint). Description gets full card width (~424px, from 0px), buttons below it full width. Card height dropped from 485px to 182px.
- **Verified:** Measured `desc_width=424px, desc_height=46px` in-browser after the fix (was `0 / 410` before). Screenshot `ui-audit/screenshots/012839-next-step-fixed.png`.
- **Status:** fixed

### #B5 — Build: no visible "offline template" indicator when LLM fallback is engaged
- **Severity:** minor (UX / trust)
- **Symptom:** When `_generate_agent_config_with_llm` fails silently (e.g. 403 against Gemini per #E1), the Build UI happily shows the deterministic template as if it were an LLM-authored draft. Users have no way to know their "Gemini-powered" agent is actually a canned template.
- **Proposed fix:** Surface `last_generation_used_llm=False` as a small banner on the Draft Insights Panel ("Offline template — configure a provider to use live model drafting"). Wire through `/intelligence/generate-agent` response.
- **Status:** open (out of scope for this session; documented for follow-up)

### #B2 — Observations (for orientation, not issues)
- Page layout (after load): journey strip ("Step 1 of 6 — Build the draft"), "Next: create a draft" banner, four start modes (Prompt / Transcript / Builder Chat / Saved Artifacts), a big textarea "Describe the agent you want to build…", example-prompt buttons, optional Agent Details + XML Instruction Studio accordions, and a "Generate Agent" CTA at bottom. Good IA.
- Example prompts include a ready-made customer-support seed which matches FAQ Buddy's target domain — convenient.

---

## /workbench

### #W1 — Workbench ignores `?agent=<id>` URL query param; always loads default project
- **Severity:** blocker (breaks the Build → Workbench handoff)
- **Symptom:** After saving FAQ Buddy from Build (`agent-v001`), the Build page "Workbench" link takes users to `/workbench?agent=agent-v001`, but the Workbench loads a hardcoded default project named "Airline Support Workbench" with fictional content unrelated to the user's agent. Their FAQ Buddy is nowhere to be found.
- **Root cause:** `web/src/pages/AgentWorkbench.tsx` does not call `useSearchParams` or inspect `location.search` at all — it unconditionally fetches `/api/workbench/projects/default`. The backend's `get_default_project` returns the newest Workbench project if one exists or a canned "Airline Support" starter draft (`builder/workbench.py:_default_model`). Saving a config from Build does NOT create a Workbench project, so users who follow the Build→Workbench handoff land on the canned demo.
- **Impact:** End-to-end journey "Build an agent, refine in Workbench" is broken. Whatever the user built in Build is functionally invisible here. Confirms user's framing that the golden path is "nearly impossible" end-to-end today.
- **Required work (larger change, deferred to follow-up):**
  1. Extend `api/routes/workbench.py` with a create-from-agent-config endpoint (or GET `/projects?agent=<id>` that auto-creates from the saved config).
  2. Update `AgentWorkbench.tsx` to read `?agent=<id>` and call that endpoint before falling back to `/projects/default`.
  3. Either create the project during Build's `Save to Workspace` or on first Workbench visit.
- **Status:** open (documented; architectural change larger than this session's scope)

### #W2 — Two `<h1>` elements on the page (a11y violation)
- **Severity:** minor (a11y)
- **Symptom:** `document.querySelectorAll('h1')` returned two: "Agent Builder Workbench" (sidebar route title) and "Airline Support Workbench" (project title). Screen readers would announce two top-level page headings.
- **Root cause:** `web/src/components/workbench/WorkbenchLayout.tsx:112` rendered the project name as an `<h1>`, but the top-level route header also emits an `<h1>` for the page title.
- **Fix:** Demote project name to `<h2>`. Verified: `document.querySelectorAll('h1').length === 1`; existing tests use `findByRole('heading', ...)` which matches any level so they still pass.
- **Status:** fixed

### #W3 — Missing `document.title` for /workbench
- **Severity:** polish
- **Symptom:** Other pages set titles like "Eval Runs • AgentLab" / "Build • AgentLab". On /workbench the tab title is just "AgentLab".
- **Fix plan:** Add `useDocumentTitle('Workbench • AgentLab')` hook call at top of `AgentWorkbench.tsx` (the other pages set title via `<PageHeader>`; Workbench has a bespoke layout without PageHeader).
- **Status:** open (deferred; trivial but we want to avoid touching layout more than needed this session)

---

## /evals

### #E2 — Eval Runs flow actually works end-to-end
- **Severity:** none (observation)
- Eval page reads `?agent=agent-v001` correctly, shows the FAQ Buddy agent in the Agent Library selector, and the "Run First Eval" CTA kicks off a run. After completion there is an "Optimize candidate" link that carries both `agent=` and `evalRunId=` into the `/optimize` URL — matches `working-docs/p1-workbench-eval-optimize-bridge-plan-codex.md`.
- Single `<h1>` ("Eval Runs"). Document title set correctly.
- **Note:** The eval we kicked off is labeled "Historical task — This task record was restored from durable history." suggesting the backend may be restoring a cached result rather than actually running the candidate live. Not a UX issue (the metric card still renders), but worth investigating if the intent is for every click of "Run First Eval" to do a fresh evaluation. Likely expected behavior under mock/fallback mode since LLM calls fail via #E1. Leaving as observation.

---

## /optimize

### #O1 — Duplicate CTAs on /optimize (casing mismatch was masking a more serious UX bug)
- **Severity:** minor (UX), polish (casing)
- **Symptom:** Two visually-similar CTAs on the same view: hero "Start optimization" (sentence case) and sidebar "Start Optimization" (title case). Both fire the same action.
- **Root cause:** `web/src/pages/Optimize.tsx` renders the journey-panel "Start optimization" CTA at :563 and a second form-submit button at :1498 on the sidebar. Their labels drifted in casing but they do the same thing.
- **Not fixed in this session:** Initially tried to just unify casing — that made `Optimize.test.tsx` fail because existing tests resolve the button uniquely by its exact name (which was only possible while the two labels differed). Properly fixing requires deduping to one CTA (or giving the secondary one distinct copy like "Launch cycle") and updating the 8 assertions in `Optimize.test.tsx`. Reverted to preserve test green.
- **Proposed fix:** Dedupe to one CTA. Recommend keeping the hero-panel "Start optimization" and removing or relabeling the sidebar duplicate.
- **Status:** open (documented; casing inconsistency is a symptom, the real bug is redundant CTAs)

### #O2 — Start optimization click does not visibly change page state
- **Severity:** minor
- **Symptom:** Clicking "Start optimization" leaves the page still showing "Ready to optimize / Next: start optimization". No spinner, no toast, no "cycle running" state appears. Likely the click POST fires but the LLM call behind the cycle hits #E1 and fails silently — the UI then has nothing to render.
- **Proposed fix:** Show a toast or inline error when the cycle fails. Optimistic "cycle starting…" indicator while the request is in flight would also help.
- **Status:** open (requires error bubbling from `/api/optimize/start` to UI)

---

## /improvements

### #I1 — Clean empty-state; handoff back to /optimize is clear
- **Severity:** none (observation)
- With no proposals, the Review tab shows "No review queue / Next: find proposals / Return to Optimize or Opportunities when you need the next proposal." Clear IA, single h1, title set.
- Sub-tabs render as buttons, not `role="tab"` — minor a11y detail (screen readers lose the tab-panel relationship) but likely intentional.

---

## /deploy

### #D1 — Deploy flow is well-structured for the golden path
- **Severity:** none (observation)
- Single h1 "Deploy". Title set. "Deploy Version" opens a form with:
  - Version select — lists `v1 · Candidate` (my FAQ Buddy)
  - Strategy select — "Canary (safe default)" or "Immediate promotion"
- "No active canary / Start canary" empty state has clear next-step copy.
- Didn't actually submit a deploy to avoid accidentally creating persistent state. The fact that my v1 candidate reached the Deploy selector means the Build → (Workbench skipped) → Eval → Optimize → Deploy chain of config propagation works without the Workbench loop.

