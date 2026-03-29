# Builder Workspace UX Report

Date: 2026-03-28
Tester: Codex (Playwright CLI)
Frontend: http://localhost:5173
Backend: http://localhost:8000
Screenshots directory: `/Users/andrew/Desktop/BuilderWorkspace-Screenshots/`

## Summary

- Completed all 10 requested phases and all 39 checklist steps.
- Captured 49 artifacts (initial phase captures plus post-fix verification evidence).
- Overall status: **Pass after remediation (all P0/P1 resolved; one P2 remains)**.
- Key blocking issues discovered:
  - P0: Backend default startup fails with `sqlite3.OperationalError: no such column: skill_id` when using default `registry.db`.
  - P0: Frontend module-load crash due missing API hook exports (fixed during test run to unblock execution).
  - P1: Slash command menu does not appear when typing `/` in composer.
  - P1: Builder layout does not collapse gracefully at `1024x768` (composer controls clip/truncate).
  - P1: `/experiments` triggers 404s for `/api/experiments/pareto`.

## Bugs Found

| ID | Severity | Status | Description | Evidence |
|---|---|---|---|---|
| UX-P0-001 | P0 | Resolved | Backend failed to start with default DB schema (`registry.db`) using requested uvicorn command; startup aborted on `skill_outcomes.skill_id` missing. Fixed and re-verified with default startup command. | Terminal startup trace (`sqlite3.OperationalError: no such column: skill_id`) |
| UX-P0-002 | P0 | Fixed in-session | Frontend crashed on initial load because `src/lib/api.ts` did not export required hooks (`useDeepResearchReport`, `useKnowledgeAsset`, `useRunAutonomousLoop`, notification hooks). | Console error: `The requested module '/src/lib/api.ts' does not provide an export named 'useDeepResearchReport'` |
| UX-P1-001 | P1 | Resolved | Slash command dropdown/menu was missing when user types `/` in composer. Fixed and re-verified with menu rendering. | `phase04_composer_slash_menu_full.png`, `phase04_composer_slash_menu_panel.png`, `fixcheck_slash_menu_visible.png` |
| UX-P1-002 | P1 | Resolved | At `1024x768`, layout remained 3-column and clipped composer controls. Fixed with compact auto-collapse behavior and re-verified. | `phase10_1024x768_full.png`, `fixcheck_1024x768_compact.png` |
| UX-P1-003 | P1 | Resolved | Experiments page performed failed API requests (`/api/experiments/pareto` 404). Fixed by adding backend route and re-verified with HTTP 200 payload. | `phase08_experiments_full.png`, console log `.playwright-cli/console-2026-03-28T22-32-32-157Z.log`, `fixcheck_experiments_after.png` |
| UX-P2-001 | P2 | Open | Dashboard/Optimize chart containers emit Recharts width/height warnings (`-1` dimensions). | Console logs `.playwright-cli/console-2026-03-28T22-32-28-655Z.log`, `.playwright-cli/console-2026-03-28T22-32-30-508Z.log` |

## Pass/Fail Matrix (All Requested Steps)

| Step | Check | Result | Status | Evidence |
|---|---|---|---|---|
| 1 | Navigate to `/` | Landed successfully | PASS | `phase01_landing_full.png` |
| 2 | Full-page screenshot + 5-region layout | All 5 regions present (top bar, left rail, center pane, right inspector, bottom composer) | PASS | `phase01_landing_full.png` |
| 3 | Verify dark theme + Inter + typography | Dark theme and consistent typography visible; Inter not programmatically asserted | PASS | `phase01_landing_full.png` |
| 4 | Broken layout/overflow/missing elements on landing | No major breakage at desktop default | PASS | `phase01_landing_full.png` |
| 5 | Screenshot top bar controls | Captured | PASS | `phase02_topbar_controls.png` |
| 6 | Mode selector Ask/Draft/Apply/Delegate clickable | All four clickable and state toggles visible | PASS | `phase02_mode_ask.png`, `phase02_mode_draft.png`, `phase02_mode_apply.png`, `phase02_mode_delegate.png` |
| 7 | Environment dropdown dev/staging/prod | All three selectable | PASS | `phase02_env_dev.png`, `phase02_env_staging.png`, `phase02_env_prod.png` |
| 8 | Pause/Resume button renders | Pause->Resume->Pause transition confirmed | PASS | `phase02_pause_clicked.png`, `phase02_resume_toggled.png` |
| 9 | Permission indicator renders | `0 approvals` badge present | PASS | `phase02_topbar_controls.png` |
| 10 | Left rail expanded screenshot | Captured | PASS | `phase03_leftrail_expanded.png` |
| 11 | Left rail collapse/expand functionality | Collapse and re-expand both work | PASS | `phase03_leftrail_collapsed_full.png`, `phase03_leftrail_reexpanded.png` |
| 12 | Left rail sections present | Projects, Sessions, Tasks, Notifications visible | PASS | `phase03_leftrail_expanded.png` |
| 13 | Empty states in left rail | Empty notifications present; sections show fallback cards | PASS | `phase03_leftrail_expanded.png` |
| 14 | Composer screenshot | Captured | PASS | `phase04_composer_default.png` |
| 15 | Typing in input area | Input updates correctly | PASS | `phase04_composer_typed.png` |
| 16 | Slash command menu appears on `/` | No dropdown/menu shown | FAIL | `phase04_composer_slash_menu_full.png`, `phase04_composer_slash_menu_panel.png` |
| 17 | Composer mode selector present | Ask/Draft/Apply/Delegate present in composer | PASS | `phase04_composer_default.png` |
| 18 | Attachment button presence | Attach button present | PASS | `phase04_composer_default.png` |
| 19 | Conversation pane screenshot | Captured | PASS | `phase05_conversation_empty_state.png` |
| 20 | Empty-state message helpful | "Start Building" guidance is clear | PASS | `phase05_conversation_empty_state.png` |
| 21 | Auto-scroll behavior | After send, latest activity and newest cards remain visible | PASS | `phase05_conversation_after_send.png` |
| 22 | Inspector panel screenshot | Captured | PASS | `phase06_inspector_overview.png` |
| 23 | Inspector tabs test | Required tabs all clickable | PASS | `phase06_inspector_overview.png`, `phase06_inspector_diff.png`, `phase06_inspector_evals.png`, `phase06_inspector_traces.png`, `phase06_inspector_skills.png`, `phase06_inspector_guardrails.png`, `phase06_inspector_files.png`, `phase06_inspector_config.png` |
| 24 | Screenshot each inspector tab | Captured | PASS | same as above |
| 25 | Empty states per inspector tab | Empty-state copy appears in each tab tested | PASS | phase06_* screenshots |
| 26 | Task drawer toggle | Close and reopen path verified (reopen via task selection) | PASS | `phase07_task_drawer_closed_full.png`, `phase07_task_drawer_reopen_attempt.png` |
| 27 | Task drawer open screenshot | Captured | PASS | `phase07_task_drawer_open.png` |
| 28 | Running/Approvals/Completed sections visible | Sections visible; currently all show `None` | PASS | `phase07_task_drawer_open.png` |
| 29 | `/dashboard` renders | Renders | PASS | `phase08_dashboard_full.png` |
| 30 | `/optimize` renders | Renders (with chart size warnings) | PASS | `phase08_optimize_full.png` |
| 31 | `/experiments` renders | UI renders but API 404 errors present | FAIL | `phase08_experiments_full.png` + console log |
| 32 | `/traces` renders | Renders | PASS | `phase08_traces_full.png` |
| 33 | `/settings` renders | Renders | PASS | `phase08_settings_full.png` |
| 34 | Sidebar navigation to Builder Workspace | Works; route lands on `/builder` | PASS | `phase09_sidebar_to_builder_full.png` |
| 35 | `/builder` path routing | Root and nested builder paths route correctly | PASS | `phase09_builder_route_root.png`, `phase09_builder_route_nested.png` |
| 36 | Browser back/forward | Works as expected | PASS | `phase09_back_navigation.png`, `phase09_forward_navigation.png` |
| 37 | Responsive 1920x1080 | Looks correct | PASS | `phase10_1920x1080_full.png` |
| 38 | Responsive 1440x900 | Looks correct | PASS | `phase10_1440x900_full.png` |
| 39 | Responsive 1024x768 panel collapse | No graceful collapse; clipping/truncation visible | FAIL | `phase10_1024x768_full.png` |

## Screenshot Reference List

- `phase01_landing_full.png`
- `phase02_topbar_controls.png`
- `phase02_mode_ask.png`
- `phase02_mode_draft.png`
- `phase02_mode_apply.png`
- `phase02_mode_delegate.png`
- `phase02_env_dev.png`
- `phase02_env_staging.png`
- `phase02_env_prod.png`
- `phase02_pause_clicked.png`
- `phase02_resume_toggled.png`
- `phase03_leftrail_expanded.png`
- `phase03_leftrail_collapsed_full.png`
- `phase03_leftrail_reexpanded.png`
- `phase04_composer_default.png`
- `phase04_composer_typed.png`
- `phase04_composer_slash_menu_full.png`
- `phase04_composer_slash_menu_panel.png`
- `phase05_conversation_empty_state.png`
- `phase05_conversation_after_send.png`
- `phase06_inspector_overview.png`
- `phase06_inspector_diff.png`
- `phase06_inspector_evals.png`
- `phase06_inspector_traces.png`
- `phase06_inspector_skills.png`
- `phase06_inspector_guardrails.png`
- `phase06_inspector_files.png`
- `phase06_inspector_config.png`
- `phase07_task_drawer_open.png`
- `phase07_task_drawer_closed_full.png`
- `phase07_task_drawer_reopen_attempt.png`
- `phase08_dashboard_full.png`
- `phase08_optimize_full.png`
- `phase08_experiments_full.png`
- `phase08_traces_full.png`
- `phase08_settings_full.png`
- `phase09_sidebar_to_builder_full.png`
- `phase09_builder_route_root.png`
- `phase09_builder_route_nested.png`
- `phase09_back_navigation.png`
- `phase09_forward_navigation.png`
- `phase10_1920x1080_full.png`
- `phase10_1440x900_full.png`
- `phase10_1024x768_full.png`

## Recommendations

1. Fix backend registry DB schema migration for `skill_outcomes` (`skill_name` -> `skill_id`) so default startup command succeeds without env overrides.
2. Add slash-command suggestion menu in composer and cover with an interaction test.
3. Add responsive breakpoints for Builder layout (`<= 1024px`) to auto-collapse inspector and/or left rail and avoid composer control clipping.
4. Resolve `/api/experiments/pareto` 404 by adding backend route/alias or updating frontend endpoint mapping.
5. Address Recharts container sizing warnings on dashboard/optimize to avoid unstable chart rendering.

## Post-Fix Verification (2026-03-28)

Applied fixes after the initial pass and re-verified:

- `UX-P0-001` Backend startup schema blocker: **Resolved**
  - Verified `uvicorn api.server:app --host 0.0.0.0 --port 8000` starts cleanly with default `registry.db`.
- `UX-P0-002` Frontend missing exports crash: **Resolved**
  - Builder workspace loads normally; no module export crash.
- `UX-P1-001` Slash command menu missing: **Resolved**
  - Typing `/` now opens slash command menu.
  - Evidence: `fixcheck_slash_menu_visible.png` and snapshot `.playwright-cli/page-2026-03-28T22-41-48-368Z.yml` containing `Slash Commands`.
- `UX-P1-002` 1024 responsive clipping: **Resolved**
  - Compact layout now auto-collapses side panels at narrow widths; composer controls remain usable.
  - Evidence: `fixcheck_1024x768_compact.png`.
- `UX-P1-003` Experiments Pareto 404: **Resolved**
  - `/api/experiments/pareto` returns 200 with frontend-compatible payload.
  - Evidence: curl response `200` and `fixcheck_experiments_after.png` with no console errors.

Remaining known issue from original report:

- `UX-P2-001` Recharts warning on dashboard/optimize container sizing (non-blocking, not requested for P0/P1 remediation).
