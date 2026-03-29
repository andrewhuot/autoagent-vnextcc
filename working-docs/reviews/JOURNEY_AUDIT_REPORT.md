# JOURNEY_AUDIT_REPORT

## Executive Summary

### Overall cohesion score
**1.9 / 5** (current web product experience)

### What is working
- The **CLI golden path** is usable and fast in a fresh project sandbox.
- A few UI surfaces are strong on interaction design even without backend data, especially:
  - `web/src/pages/AgentStudio.tsx`
  - `web/src/pages/Optimize.tsx`
  - `web/src/pages/Notifications.tsx` (form UX only)

### What is broken (top 5)
1. **P0: Backend server startup crash blocks real web functionality**
- Root issue: schema collision on `skills` table during app startup.
- Error observed repeatedly: `sqlite3.OperationalError: no such column: kind`.
- Impact: most API calls in web return 404, so core journeys fail at execution time.
- Relevant files:
  - `api/server.py` (initializes both `RegistryStore` and `ExecutableSkillStore` against same DB path)
  - `registry/store.py` (creates `skills` table with old schema: `name, version, data...`)
  - `core/skills/store.py` (expects `skills.kind`, `skills.domain`, `skills.status`)

2. **P0: Core web actions submit to endpoints that 404**
- Confirmed with Playwright network probes:
  - `POST /api/eval/run` -> 404
  - `POST /api/optimize/run` -> 404
  - `POST /api/notifications/slack` -> 404
  - `POST /api/agent-skills/analyze` -> 404
- User sees action-level failure toasts/alerts after clicking CTAs.

3. **P0: Four promised journeys have no frontend routes at all**
- Missing routes in `web/src/App.tsx`:
  - `/sandbox`
  - `/knowledge`
  - `/what-if`
  - `/reviews`
- Result: blank main panel with generic title (`AutoAgent`).

4. **P1: Navigation and naming consistency are fractured**
- `/notifications` renders page title as `AutoAgent` (missing title mapping in `Layout.tsx`).
- Labeling drift: `Changes` in sidebar vs `Change Review` page title/route.
- Mixed “new run” labels (`New Eval Run`, `Create Eval Run`, `Start New Evaluation`) in one flow.

5. **P1: Visual language is inconsistent across major modules**
- App-wide shell is light/neutral, while several pages use dark navy card blocks:
  - `CxImport`
  - `Notifications`
- These look like a different product module embedded in the same shell.

---

## Test Setup and Evidence

### Environment setup executed
- Playwright check and browser install:
  - `npx playwright --version` -> `1.58.0`
  - `npx playwright install chromium`
- Frontend server launched at `http://127.0.0.1:5173`.
- Attempted backend startup via:
  - `python -m uvicorn api.server:app --port ...`
  - `python runner.py server --port ...`
- Backend startup failed with schema error (`no such column: kind`).

### Artifacts generated
- Main screenshot set (47 images):
  - `~/Desktop/AutoAgent-Journey-Screenshots/`
- Structured journey log:
  - `~/Desktop/AutoAgent-Journey-Screenshots/journey_audit_results.json`
- Long-wait validation set (post-load states):
  - `~/Desktop/AutoAgent-Journey-Screenshots/longwait_checks/`
- Action-level click/submit checks:
  - `~/Desktop/AutoAgent-Journey-Screenshots/action_checks/`
  - `~/Desktop/AutoAgent-Journey-Screenshots/action_checks/action_checks.json`

### Extra CLI-first journey coverage (real execution)
Executed in scratch dir: `/tmp/autoagent_journey_cli.q2oZnt`
- `python runner.py quickstart ... --verbose`
- `python runner.py eval run -j`
- `python runner.py diagnose -j`
- `python runner.py edit "..." -j`
- `python runner.py deploy --strategy canary`

Result: CLI loop is functional in isolation; web/API runtime is not.

---

## Journey-by-Journey Analysis

## 1) First Run — `autoagent init` -> first eval -> first diagnosis -> first fix -> deploy
**What I tested**
- Real CLI golden-path equivalent via `quickstart` + explicit `eval`, `diagnose`, `edit`, `deploy` commands.
- Real web counterpart pages: `/`, `/evals`, `/assistant`, `/deploy`.

**Observed behavior**
- CLI path works and is clear for day-1 users.
- Web path fails to execute backend actions because API endpoints return 404.

**Friction points**
- Web and CLI feel like two different maturity levels.
- Dashboard empty-state pushes CLI (`autoagent quickstart`) instead of giving first-run in-product action.

**Evidence**
- `01_001_dashboard-entry-dashboard.png`
- `01_002_first-eval-form-eval-form.png`
- `action_checks/evals_start_attempt.png`

**Rating**
- Simplicity: 3/5
- Cohesion: 2/5
- Delight: 2/5

---

## 2) Assistant Flow — open `/assistant` -> describe -> diagnose -> approve fix
**What I tested**
- Typed real prompts and submitted.

**Observed behavior**
- Assistant UI renders and input/send interaction works.
- Model response fails with explicit card error: `Error: Failed to complete the request.`

**Friction points**
- The core value prop page fails at first real interaction.
- No recovery CTA beyond trying again.

**Evidence**
- `02_007_assistant-open-open.png`
- `02_008_assistant-problem-description-after-send.png`

**Rating**
- Simplicity: 2/5
- Cohesion: 2/5
- Delight: 1/5

---

## 3) Build Agent — `/assistant` upload/describe -> generated config -> run baseline
**What I tested**
- Upload toggle + transcript fixture + prompt submit.
- Followed into `/agent-studio` and executed `Queue update` and `Simulate`.

**Observed behavior**
- Assistant side fails (same backend request failure).
- Agent Studio itself is polished and interactive.

**Friction points**
- Flow breaks right at handoff point between assistant and studio.
- User has to context-switch from broken NL flow to manual Studio flow.

**Evidence**
- `03_011_assistant-with-upload-assistant-after-upload-send.png`
- `03_012_agent-studio-baseline-agent-studio-open.png`
- `03_014_agent-studio-baseline-simulate-attempt.png`

**Rating**
- Simplicity: 3/5
- Cohesion: 2/5
- Delight: 2/5

---

## 4) Daily Health Check — `/dashboard` -> issues -> fix
**What I tested**
- Loaded dashboard, looked for health drill-down and fix CTA.

**Observed behavior**
- Dashboard lands in no-data empty-state.
- No inline route to issue remediation from this view.

**Friction points**
- “First action” path is CLI-heavy instead of web-native.
- No obvious one-click “run first eval from here” in current no-data state.

**Evidence**
- `longwait_checks/root.png`
- `04_015_dashboard-health-overview-dashboard-simple.png`

**Rating**
- Simplicity: 2/5
- Cohesion: 2/5
- Delight: 1/5

---

## 5) Diagnose & Fix — `/traces` or `/assistant` -> root cause -> apply fix
**What I tested**
- `/traces` filters + expansion attempt.
- Assistant fix prompt.

**Observed behavior**
- Traces page eventually resolves to explicit error banner: `Failed to load traces.`
- Assistant returns request failure.

**Friction points**
- No fallback path from traces error to a guided diagnosis route.
- Root-cause chain unavailable in the UI while underlying CLI diagnose is functional.

**Evidence**
- `longwait_checks/traces.png`
- `05_020_traces-open-and-filter-trace-expand-attempt.png`
- `05_021_assistant-fix-request-assistant-fix-proposal.png`

**Rating**
- Simplicity: 1/5
- Cohesion: 1/5
- Delight: 1/5

---

## 6) Optimize Loop — `/optimize` -> run optimization -> review -> approve -> deploy
**What I tested**
- Start optimization CTA.
- Transition to `/experiments`.

**Observed behavior**
- Optimize page UI loads and controls are clear.
- Clicking start shows toast: `Failed to start optimization - Not Found`.
- Experiments page shows `Failed to load experiments`.

**Friction points**
- High-quality UI shell with non-functional backend undermines trust fast.

**Evidence**
- `longwait_checks/optimize.png`
- `action_checks/optimize_start_attempt.png`
- `longwait_checks/experiments.png`

**Rating**
- Simplicity: 2/5
- Cohesion: 2/5
- Delight: 1/5

---

## 7) Deploy & Monitor — `/deploy` -> deploy candidate -> monitor canary
**What I tested**
- Deploy page baseline state.

**Observed behavior**
- Page resolves to `No deployment status` with only `Refresh` action.
- No clear first-time deploy creation flow from this state.

**Friction points**
- Empty state dead-end for new users.
- First deploy requires user to infer another page/CLI path.

**Evidence**
- `longwait_checks/deploy.png`

**Rating**
- Simplicity: 1/5
- Cohesion: 1/5
- Delight: 1/5

---

## 8) Import Agent — `/cx/import` or `/adk/import` -> import -> first eval
**What I tested**
- CX import project/agent listing step.
- ADK import parse step with non-existent path.

**Observed behavior**
- Both pages render forms and wizard framing.
- Both settle into loading/skeleton-like intermediate panels under API failures.

**Friction points**
- Inconsistent feedback quality: loading placeholders persist where error messaging is expected.
- Visual style differs sharply from rest of app (dark panels).

**Evidence**
- `08_029_cx-import-attempt-cx-import-open.png`
- `08_030_cx-import-attempt-cx-import-list-attempt.png`
- `08_032_adk-import-attempt-adk-parse-attempt.png`

**Rating**
- Simplicity: 2/5
- Cohesion: 2/5
- Delight: 1/5

---

## 9) Skill Management — `/skills` -> browse/install -> attach -> verify
**What I tested**
- `/skills` browse/search.
- `/agent-skills` analyze action.

**Observed behavior**
- `/skills` shows explicit error (`Failed to load skills`).
- `/agent-skills` accepts clicks but lacks visible error state despite 404 responses.

**Friction points**
- Two adjacent pages handling the same domain have different error-state behavior.
- No user-facing reason for empty gap/skill sections after analyze click.

**Evidence**
- `longwait_checks/skills.png`
- `action_checks/agent_skills_analyze_attempt.png`

**Rating**
- Simplicity: 1/5
- Cohesion: 1/5
- Delight: 1/5

---

## 10) Sandbox Testing — `/sandbox`
**Observed behavior**
- Route is missing in frontend routing; main area is blank.

**Evidence**
- `10_040_sandbox-route-sandbox-route.png`

**Rating**
- Simplicity: 1/5
- Cohesion: 1/5
- Delight: 1/5

---

## 11) Knowledge Mining — `/knowledge`
**Observed behavior**
- Route is missing in frontend routing; main area is blank.

**Evidence**
- `11_041_knowledge-route-knowledge-route.png`

**Rating**
- Simplicity: 1/5
- Cohesion: 1/5
- Delight: 1/5

---

## 12) What-If Replay — `/what-if`
**Observed behavior**
- Route is missing in frontend routing; main area is blank.

**Evidence**
- `12_042_what-if-route-what-if-route.png`

**Rating**
- Simplicity: 1/5
- Cohesion: 1/5
- Delight: 1/5

---

## 13) Collaborative Review — `/reviews`
**Observed behavior**
- Route is missing in frontend routing; main area is blank.

**Evidence**
- `13_043_reviews-route-reviews-route.png`

**Rating**
- Simplicity: 1/5
- Cohesion: 1/5
- Delight: 1/5

---

## 14) Notifications Setup — `/notifications` -> Slack webhook -> event config
**What I tested**
- Opened add-subscription form.
- Filled Slack webhook + selected events.
- Submitted form.

**Observed behavior**
- Form UX and interaction pattern are clear.
- Submit fails with alert: `Failed to add subscription: ApiRequestError: Not Found`.
- API probe confirms `POST /api/notifications/slack` -> 404.

**Friction points**
- Submission failure is a blocking error after full form completion.
- Page header title still says `AutoAgent` instead of `Notifications`.

**Evidence**
- `action_checks/notifications_form_filled.png`
- API response probe logs (`POST /api/notifications/slack` 404)

**Rating**
- Simplicity: 2/5
- Cohesion: 2/5
- Delight: 1/5

---

## Cross-Journey Issues

1. **API contract unavailable from web app**
- Cross-cutting symptom: 404s across health, eval, optimize, deploy, traces, skills, notifications, agent-skills.
- Effect: most operational journeys are blocked despite UI controls existing.

2. **Backend startup regression prevents first-party server boot**
- `python runner.py server` fails at startup with DB schema conflict.
- Root collision:
  - `registry/store.py` creates `skills` table without `kind`.
  - `core/skills/store.py` expects `skills.kind` and creates indexes on it.
  - Both use same `AUTOAGENT_REGISTRY_DB` path in `api/server.py` lifespan.

3. **Frontend/backend capability mismatch**
- Backend exposes APIs for sandbox, knowledge, what-if, collaboration (`/api/sandbox`, `/api/knowledge`, `/api/what-if`, `/api/reviews`).
- Frontend app has no corresponding routes/pages in `web/src/App.tsx`.

4. **Error-state design inconsistency**
- Good: `Skills`, `Traces`, `Eval Runs` show explicit error banners.
- Poor: `Agent Skills`, parts of import flows show sparse or loading-only states with no clear remediation.

5. **WebSocket error noise degrades perceived reliability**
- Repeated browser console errors: websocket handshake failure (`/ws` 403) while API is unavailable.

---

## Navigation Audit

### Reachability
- Sidebar exposes many routes and generally maps well to `App.tsx` routes.
- Missing journey routes (`/sandbox`, `/knowledge`, `/what-if`, `/reviews`) are not registered in frontend routing and are not reachable from navigation.

### Cross-linking quality
- `Dashboard` no-data state should route users directly to first-run eval/deploy actions; currently primarily CLI hint text.
- `Deploy` empty state has no route to create/select a deployable config.
- `Traces` failure state does not offer jump-to-assistant or jump-to-diagnose fallback.

### Sidebar organization
- Broadly logical groups (`Operate`, `Improve`, `Integrations`, `Governance`, `Analysis`) are good.
- Missing new-feature pages in sidebar reinforces roadmap-implementation mismatch.

---

## Naming Consistency Audit

### Consistent
- Major route labels are mostly predictable (`Eval Runs`, `Optimize`, `Traces`).

### Inconsistent
- Header title fallback issue on `/notifications` -> shows `AutoAgent` due missing page title map entry.
- `Changes` (sidebar) vs `Change Review` (page title) increases cognitive overhead.
- Eval action naming drifts inside a single flow:
  - `New Eval Run`
  - `Create Eval Run`
  - `Start New Evaluation`

---

## Visual Consistency Audit

### Positive
- Global shell (sidebar/header spacing, typography, neutral palette) is cohesive.

### Inconsistent
- `CxImport` and `Notifications` use dark navy panel style unlike rest of app.
- Assistant page introduces a visually distinct chat motif and large whitespace break that feels from a separate design track.
- Empty/error/loading state language and styling differ heavily across pages.

### Result
- The app feels like multiple sub-products merged into one shell rather than one unified product system.

---

## Simplification Opportunities

1. Add a **single global “API unavailable” banner** that appears when core bootstrap endpoints fail (health/config/eval).
2. Convert dashboard no-data state into a **guided first-run wizard** (Run Eval -> Diagnose -> Optimize -> Deploy).
3. Add **actionable fallback links** on every error state (`Try again`, `Open assistant`, `Open diagnose`, `Open docs`).
4. Unify naming tokens for eval actions and page labels.
5. Normalize surface styles (either dark modules become light or vice versa) under shared design tokens.
6. Add frontend pages for promised journeys or hide those journeys from UX/docs until shipped.
7. Make `Deploy` empty-state include an onboarding CTA (`Go to Eval` / `Select Config`).
8. Harmonize error handling contract across pages (always show failure reason + next action).
9. Add backend startup self-check command and fail-fast CLI messaging when server cannot boot.
10. Add a Playwright smoke suite that asserts critical routes can load and key POST actions do not 404.

---

## Priority-Ordered Improvements (with Paths and Effort)

### P0 (must fix before relying on web console)
1. **Resolve DB schema collision causing backend boot failure**
- Files:
  - `api/server.py`
  - `registry/store.py`
  - `core/skills/store.py`
- Change:
  - Separate legacy registry tables from unified skill store table namespace, or use separate SQLite DBs.
  - Add deterministic migration guard when existing `skills` schema is legacy.
- Effort: **M (1-2 days)**

2. **Add startup integration test for server lifespan boot**
- Files:
  - `tests/` (new integration test, e.g. `tests/test_server_startup.py`)
- Change:
  - Validate `python runner.py server` can initialize app state without DB schema crashes.
- Effort: **S (0.5 day)**

3. **Block/guard frontend actions when API bootstrap is unavailable**
- Files:
  - `web/src/lib/api.ts`
  - `web/src/components/Layout.tsx`
  - `web/src/pages/EvalRuns.tsx`
  - `web/src/pages/Optimize.tsx`
  - `web/src/pages/Notifications.tsx`
- Change:
  - Add centralized API health sentinel and disable action buttons with clear messaging.
- Effort: **M (1 day)**

### P1 (major UX cohesion fixes)
4. **Implement missing promised pages or remove dead links/promises**
- Files:
  - `web/src/App.tsx`
  - New pages for `/sandbox`, `/knowledge`, `/what-if`, `/reviews` (or temporary placeholders with explicit “Coming soon”)
- Effort: **L (2-4 days)**

5. **Fix title mapping and naming drift**
- Files:
  - `web/src/components/Layout.tsx`
  - `web/src/components/Sidebar.tsx`
  - `web/src/pages/EvalRuns.tsx`
- Effort: **S (0.5 day)**

6. **Standardize error states and recovery CTAs across pages**
- Files:
  - `web/src/pages/AgentSkills.tsx`
  - `web/src/pages/CxImport.tsx`
  - `web/src/pages/AdkImport.tsx`
  - `web/src/pages/Deploy.tsx`
- Effort: **M (1-2 days)**

### P2 (polish + long-term maintainability)
7. **Visual system alignment pass across divergent modules**
- Files:
  - `web/src/pages/CxImport.tsx`
  - `web/src/pages/Notifications.tsx`
  - shared style/token files
- Effort: **M (1-2 days)**

8. **Add Playwright CI smoke for critical journeys**
- Files:
  - `web/tests/` (new e2e smoke specs)
  - CI workflow files
- Effort: **M (1-2 days)**

---

## Final Assessment (Brutally Honest)

The product has a promising information architecture and some genuinely strong surfaces, but as tested today the **web console is not production-usable for core operations** because backend integration is broken at startup and API calls are mostly 404.

The CLI experience is materially better than the web experience right now. If this product is being positioned as a unified operator console, fixing backend startup and route parity is the immediate line between “impressive demo shell” and “reliable day-to-day tool.”
