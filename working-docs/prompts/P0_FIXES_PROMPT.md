# P0 Showstopper Fixes — Distinguished Engineer Review

You are fixing critical production-blocking issues in AutoAgent VNextCC. These are P0 showstoppers that prevent the platform from running.

## Required Fixes

### 1. DB Schema Collision on Boot (P0)
In `api/server.py`, the `RegistryStore`, `ExecutableSkillStore`, and `RunbookStore` are all directed to the same DB file (`registry.db`). They expect different schemas for the `skills` table (specifically the `kind` column), causing `sqlite3.OperationalError` on startup.

**Fix**: Give each store its own DB file (e.g., `registry.db`, `skills.db`, `runbooks.db`), OR use a single DB with proper schema migration that handles all three stores' table requirements without collision. Verify the server boots cleanly after the fix.

### 2. Trace Engine is Disconnected (P0)
The `TraceCollector` and SQLite datastore exist, plus `TracingMiddleware` is instantiated — but it's never hooked into the target agent runner (`runner.py`). Without trace data, the opportunity queue stays empty and the optimization loop breaks at step one.

**Fix**: Wire the `TraceCollector` into `runner.py`'s agent execution path so traces are actually collected during runs. Verify traces appear in the datastore after a test run.

### 3. Poisoned Registry Defaults (P0)
`optimizer/mutations_google.py` contains Google Vertex mutation stubs that raise `NotImplementedError`. These are included in the default configuration. If the search engine randomly picks one, the system crashes.

**Fix**: Either implement the mutations properly, remove them from the default config, or add a guard that skips mutations that raise `NotImplementedError`. The default config should only include working mutations.

### 4. "Mock-First" Overrides (P1)
`autoagent.yaml` ships with `use_mock: true`, which overrides the entire Proposer engine and produces deterministic fake eval scores. This destroys the new-user experience — they think they're running real optimizations but aren't.

**Fix**: Change the default to `use_mock: false`. If no API key is configured, fall back to mock mode gracefully with a clear warning banner — don't silently mock everything. The user should know when they're in mock mode vs real mode.

### 5. UI Ghost Routes (P1)
The React frontend has navigation links to `/sandbox`, `/knowledge`, `/what-if`, and `/reviews`, but these routes aren't defined in `App.tsx` — users hit dead-end empty states.

**Fix**: Either:
- Add proper route definitions with at minimum a "Coming Soon" placeholder page for each, OR
- Remove the navigation links to these routes entirely if they're not implemented yet

Prefer adding placeholder pages — it's better UX than broken links.

## Investigation Phase

Before fixing, also investigate the codebase for additional issues:
- Check ALL routes in App.tsx vs sidebar navigation links — find any other ghost routes
- Check ALL API routes vs frontend API hooks — find any 404-prone endpoints
- Check for other stores/DBs with potential schema collisions
- Check for other NotImplementedError stubs in the default execution path
- Check import errors that would crash on startup
- Run `python -c "from api.server import app"` to verify the server can actually boot
- Run `cd web && npx tsc --noEmit` to check for TypeScript errors

## Verification

After all fixes:
1. Verify backend boots: `cd /Users/andrew/Desktop/AutoAgent-VNextCC && python3 -c "from api.server import app; print('Server boots OK')"` (or equivalent)
2. Verify frontend compiles: `cd web && npx tsc --noEmit`
3. Run existing tests: `python3 -m pytest tests/ -x -q --tb=short 2>&1 | tail -20`
4. Document all changes in a `P0_FIX_REPORT.md`

## When done:
- `git add -A && git commit -m "fix: P0 showstoppers — DB collision, trace wiring, poisoned defaults, mock override, ghost routes"`
- `git push`
- `wc -l P0_FIX_REPORT.md`
- `openclaw system event --text 'Done: P0 showstopper fixes committed and pushed' --mode now`
