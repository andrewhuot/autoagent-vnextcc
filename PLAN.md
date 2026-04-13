# PLAN — End-to-End Golden Path: FAQ Bot from Build → Deploy

## Goal
Walk a brand-new user (us, simulating a real customer) through the agentlab golden path:
**Build → Workbench → Evals → Optimize/Improve → Deploy** — using a real Gemini API key
(`GOOGLE_API_KEY from local .env`) in live mode, building a **Customer FAQ Support Chat Agent**.

For every step, drive the actual UI via the Chrome browser MCP (`mcp__claude-in-chrome__*`)
against `http://localhost:5173`. Capture screenshots, console errors, and network failures.
Each iteration: **walk one stage, document gaps in `findings/<stage>.md`, fix one or two
high-impact issues, re-walk to verify, then move on.**

Pro mode is **out of scope** — stay in the standard/simple flow.

## Ground Rules (for every iteration)
- Always start/verify backend + frontend via `./start.sh`. If services already running, reuse.
- Use **live mode** with the Gemini key above. Never fall back to mock unless explicitly testing mock.
- Persist findings in `findings/` as markdown. One file per stage, append-only with timestamps.
- Each fix gets a regression e2e test in `web/tests/golden-path-faq-bot.spec.ts`.
- Conventional commits. Feature branch only. Never push.
- After each fix: `npm run test` (web), Playwright spec, then move on.
- Stop after 3 failed attempts at the same fix and write the blocker to `findings/blockers.md`.

---

## Phase 0 — Setup & Baseline

- [ ] Create `findings/` directory and write `findings/README.md` describing the format (stage, severity, repro, expected, actual, screenshot path, fix proposal).
- [ ] Create `web/tests/golden-path-faq-bot.spec.ts` skeleton — one Playwright `describe` per stage (build, workbench, evals, optimize, deploy) with `test.skip()` placeholders.
- [ ] Verify `./start.sh` brings up backend (8000) + frontend (5173). Capture any startup errors to `findings/00-startup.md`. If backend fails, fix the smallest blocker.
- [ ] Set Gemini API key in user settings via UI (or POST to `/api/settings`). Verify it persists by re-reading. Record path in `findings/00-setup.md`.

## Phase 1 — Build Stage (create FAQ bot)

- [ ] Browser-walk `/build`: take screenshot, list every interactive control, document the user's first decision-points in `findings/01-build.md`. Note any confusing copy, missing affordances, dead buttons.
- [ ] Attempt to create a "Customer FAQ Support" agent in `/build` end-to-end. Use a realistic prompt (e.g., support for a SaaS billing tool, FAQ-only). Document every step and friction in `findings/01-build.md`.
- [ ] Verify created agent persists: refresh page, navigate away and back. Confirm it appears in any registry/list. Document any data-loss in `findings/01-build.md`.
- [ ] Fix the **top 2 build-stage issues** by severity (broken > confusing > cosmetic). Add Playwright regression tests for each in `golden-path-faq-bot.spec.ts`.

## Phase 2 — Workbench Stage (modify the agent)

- [ ] Browser-walk `/workbench` with the FAQ bot loaded. Test prompt edits, model swap, instruction tweaks, and any tool/skill toggles. Capture findings in `findings/02-workbench.md`.
- [ ] Run a live conversation with the FAQ bot in workbench using the Gemini key. Confirm tokens stream, billing/cost displays sane, errors surface clearly. Document in `findings/02-workbench.md`.
- [ ] Save a workbench change and confirm it propagates to the underlying agent config (re-open Build, verify diff). Document config-sync gaps in `findings/02-workbench.md`.
- [ ] Fix the **top 2 workbench-stage issues**. Add Playwright regression tests.

## Phase 3 — Evals Stage

- [ ] Browser-walk `/evals`. Generate or import a small eval set (~5 cases) for the FAQ bot. Document the eval-creation flow in `findings/03-evals.md` — note any required-but-unexplained fields, confusing terminology, missing examples.
- [ ] Run the eval against the FAQ bot in **live mode** with the Gemini key. Confirm it completes, scores render, per-case drill-down works. Document in `findings/03-evals.md`.
- [ ] Compare two runs (baseline vs. a small prompt change). Confirm `/compare` or equivalent works and shows meaningful diffs. Document in `findings/03-evals.md`.
- [ ] Fix the **top 2 eval-stage issues**. Add Playwright regression tests.

## Phase 4 — Optimize / Improve Stage

- [ ] Browser-walk `/optimize` and `/improvements` (and `/agent-improver` if exposed). Identify which is the canonical "make my agent better" entry point — document confusion in `findings/04-optimize.md`.
- [ ] Run an optimization pass (or improvement suggestion) against the FAQ bot using the eval set from Phase 3. Confirm it produces concrete proposed changes (prompt diffs, config diffs). Document in `findings/04-optimize.md`.
- [ ] Apply one accepted improvement back to the agent config. Confirm the change persists and the eval score improves on re-run. Document in `findings/04-optimize.md`.
- [ ] Fix the **top 2 optimize-stage issues**. Add Playwright regression tests.

## Phase 5 — Deploy Stage

- [ ] Browser-walk `/deploy` (and `/cx-deploy` / `/adk-deploy` if relevant for FAQ-style agents). Document deployment options, required inputs, and any unexplained jargon in `findings/05-deploy.md`.
- [ ] Attempt a real deployment (or simulated deployment to a local target) of the FAQ bot. Confirm the deploy artifact/output exists and is invokable. Document in `findings/05-deploy.md`.
- [ ] Verify post-deploy: surface a deployment status, a way to invoke the deployed agent, and a rollback path. Document gaps in `findings/05-deploy.md`.
- [ ] Fix the **top 2 deploy-stage issues**. Add Playwright regression tests.

## Phase 6 — Cross-cutting & Wrap-up

- [ ] Walk the full golden path top-to-bottom one more time as a "fresh user" (clear local state). Time it. Record total clicks, total time, and friction events to `findings/06-cross-cutting.md`.
- [ ] Triage all `findings/*.md` into a prioritized backlog at `findings/BACKLOG.md` (P0/P1/P2). Mark which were fixed in this loop, which remain.
- [ ] Run the full Playwright suite (`cd web && npx playwright test`) and `pytest` (root). Fix any regressions introduced by this loop's changes. If a flake is unrelated, document in `findings/blockers.md` and skip-with-reason.
