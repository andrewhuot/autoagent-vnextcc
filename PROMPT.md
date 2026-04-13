# Ralph Loop — Project-Specific Instructions

## Mission
You are autonomously executing `PLAN.md`: walking the agentlab UI golden path
(Build → Workbench → Evals → Optimize → Deploy) end-to-end, finding gaps, and
fixing the highest-impact issues each iteration. The user we're simulating is
building a **Customer FAQ Support Chat Agent** for a SaaS billing tool.

## Each Iteration
1. Read `PLAN.md`. Find the first unchecked task.
2. Execute it. If it requires UI walking, **use the Chrome MCP** (`mcp__claude-in-chrome__*`),
   not Playwright as a first resort.
3. When you finish: check the box in `PLAN.md` and commit with a conventional message
   on a feature branch (never master).
4. If you discover a UI gap, **first** document it in the appropriate `findings/*.md`,
   **then** decide whether to fix it now (only if it's a top-2 issue for that phase).
5. Stop after 3 failed attempts at the same fix → log to `findings/blockers.md`.

## Environment
- Backend: `http://localhost:8000` — start via `./start.sh` from repo root.
- Frontend: `http://localhost:5173` — same script.
- Logs: `.agentlab/backend.log`, `.agentlab/frontend.log`.
- Stop: `./stop.sh`.

## Live Mode
- Gemini API key for testing: **`AIzaSyCT_e6LmUOCalKdL5tBIoBfi1y6IKyN_xU`**
- Always test in **live mode**. Mock mode hides real bugs — only use it if a task explicitly says so.
- Set the key via the UI's settings page if possible; otherwise via the backend's settings API.

## Testing Discipline
- Every fix gets a regression test in `web/tests/golden-path-faq-bot.spec.ts` (Playwright).
- Run `cd web && npx playwright test golden-path-faq-bot` before checking off a fix task.
- Do **not** rewrite or weaken existing tests. If an existing test fails because of
  intentional UX changes, update it with a comment explaining why.

## Commits & Branches
- Feature branch only. Suggested: `feat/golden-path-faq-bot-iteration-N`.
- Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`).
- Never push. Never merge to master/main.

## Out of Scope
- **Pro mode** UI — skip entirely.
- Backend rewrites unless a fix is impossible at the UI layer.
- New features beyond what the golden path needs.

## Findings Format
Each `findings/<phase>.md` entry:
```
### [P0|P1|P2] <short title>
- **When**: <ISO timestamp>
- **Where**: <URL or component path>
- **Repro**: <numbered steps>
- **Expected**: <what should happen>
- **Actual**: <what happened, screenshot path if any>
- **Fix**: <proposed fix or "fixed in <commit>">
```

## When to Stop the Loop
- All `PLAN.md` tasks are checked, OR
- `findings/blockers.md` has 3+ unresolvable blockers, OR
- The user interrupts.
