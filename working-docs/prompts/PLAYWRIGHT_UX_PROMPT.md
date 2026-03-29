# Builder Workspace — Playwright UX Pass

You are performing a comprehensive visual QA and UX testing pass on the newly built Builder Workspace feature using Playwright.

## Setup

The app is a Python FastAPI backend + React Vite frontend.

**Start the servers:**
1. Backend: `cd /Users/andrew/Desktop/AutoAgent-VNextCC && .venv/bin/uvicorn api.server:app --host 0.0.0.0 --port 8000`
2. Frontend: `cd /Users/andrew/Desktop/AutoAgent-VNextCC/web && npm run dev -- --port 5173`

**Screenshot directory:** Save all screenshots to `/Users/andrew/Desktop/BuilderWorkspace-Screenshots/`

## Test Plan

### Phase 1: Builder Workspace Landing (default route /)
1. Navigate to `http://localhost:5173/`
2. Screenshot the full page — verify 5-region layout:
   - Left rail (projects/sessions/tasks)
   - Center conversation pane
   - Right inspector panel
   - Bottom composer
   - Top bar (project selector, mode, model, permissions, pause)
3. Verify dark theme, Inter font, clean typography
4. Check for any broken layout, overflow, missing elements

### Phase 2: Top Bar Functionality
5. Screenshot top bar controls
6. Test mode selector (Ask/Draft/Apply/Delegate) — click each mode, screenshot
7. Test environment dropdown (dev/staging/prod)
8. Verify pause/resume button renders
9. Verify permission indicator renders

### Phase 3: Left Rail
10. Screenshot left rail expanded
11. Test collapse/expand functionality
12. Verify sections: Projects, Sessions, Tasks, Notifications
13. Check empty states

### Phase 4: Composer
14. Screenshot the bottom composer
15. Test typing in the input area
16. Test slash command menu — type "/" and screenshot the dropdown
17. Verify mode selector in composer
18. Test attachment button presence

### Phase 5: Conversation Pane
19. Screenshot center conversation pane (likely empty state)
20. Verify empty state messaging is helpful
21. Check auto-scroll behavior

### Phase 6: Inspector Panel
22. Screenshot right inspector panel
23. Test each inspector tab: Overview, Diff, Evals, Traces, Skills, Guardrails, Files, Config
24. Screenshot each tab
25. Verify empty states per tab

### Phase 7: Task Drawer
26. Test task drawer toggle
27. Screenshot task drawer open
28. Verify running tasks, approvals, completed sections

### Phase 8: Existing Pages Still Work
29. Navigate to `/dashboard` — verify Dashboard still renders
30. Navigate to `/optimize` — verify Optimize still renders
31. Navigate to `/experiments` — verify Experiments still renders
32. Navigate to `/traces` — verify Traces still renders
33. Navigate to `/settings` — verify Settings still renders

### Phase 9: Navigation
34. Navigate via sidebar — click "Builder Workspace" link
35. Verify URL routing works for /builder paths
36. Test browser back/forward

### Phase 10: Responsive Behavior
37. Set viewport to 1920x1080 — full screenshot
38. Set viewport to 1440x900 — full screenshot
39. Set viewport to 1024x768 — verify panels collapse gracefully

## Output

After all tests, create a file `BUILDER_UX_REPORT.md` in the project root with:
- Summary of all findings
- List of bugs found (with severity P0/P1/P2)
- Screenshots reference list
- Pass/fail for each test
- Recommendations for fixes

## Fixing Issues

After writing the report, fix any P0 and P1 bugs you find. Common issues to fix:
- Broken imports or missing components
- Layout overflow or misalignment
- Missing empty states
- Broken navigation/routing
- Dark theme inconsistencies
- TypeScript errors preventing render

Run `npm run build` in the web directory after fixes to verify no TS errors in builder components.

When completely finished:
```
openclaw system event --text "Done: Playwright UX pass on Builder Workspace — screenshots, report, and P0/P1 fixes applied" --mode now
```
