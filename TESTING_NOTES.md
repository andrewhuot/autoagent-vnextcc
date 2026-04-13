# AgentLab End-to-End UI Testing Notes

Live-mode session driving the golden path **Build → Workbench → Eval Runs → Optimize → Improvements → Deploy** with a real Gemini key, dogfooding a new "FAQ Buddy" customer-support agent.

Legend:
- **Severity** — `blocker` (cannot proceed), `major` (usable but broken UX), `minor` (rough edge), `polish` (nit).
- **Status** — `open`, `fixing`, `fixed-<sha>`, `deferred`.

---

## Summary (filled in at end)

_(Populated in the final sweep.)_

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

### #B2 — Observations (for orientation, not issues)
- Page layout (after load): journey strip ("Step 1 of 6 — Build the draft"), "Next: create a draft" banner, four start modes (Prompt / Transcript / Builder Chat / Saved Artifacts), a big textarea "Describe the agent you want to build…", example-prompt buttons, optional Agent Details + XML Instruction Studio accordions, and a "Generate Agent" CTA at bottom. Good IA.
- Example prompts include a ready-made customer-support seed which matches FAQ Buddy's target domain — convenient.

