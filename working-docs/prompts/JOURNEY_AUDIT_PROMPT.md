# Critical User Journey Audit — End-to-End Verification

You are auditing every critical user journey in AutoAgent VNextCC. For each journey, you must verify it actually works by testing it — not just reading the code. Fix any issues you find.

## Journeys to Test

### Journey 1: First-Time Setup
- Run `bash -n setup.sh` (syntax check)
- Verify `.env.example` exists and is valid
- Verify `pyproject.toml` has all required deps
- Check that `pip install -e ".[dev]"` would work (inspect deps)
- Check that `cd web && npm install` would work (inspect package.json)

### Journey 2: Server Startup
- Run `bash -n start.sh` (syntax check with /bin/bash for macOS 3.2 compat)
- Verify `api/server.py` imports cleanly: `python3 -c "from api.server import app; print('OK')"`
- Verify all API route files import cleanly
- Check that uvicorn command in start.sh matches actual server module path
- Verify frontend builds: `cd web && npx tsc --noEmit 2>&1 | head -50`

### Journey 3: CLI Golden Path
- Verify `runner.py` has all expected commands: `python3 runner.py --help`
- Test `python3 runner.py init --help` (or equivalent)
- Test `python3 runner.py loop --help`
- Verify no import errors on any CLI command

### Journey 4: Web UI — All Pages Load
- Check `web/src/App.tsx` for all route definitions
- Cross-reference routes against sidebar navigation links in ALL layout/nav components
- Find ANY navigation link that points to an undefined route (ghost routes)
- Find ANY route that's defined but not linked from navigation
- Verify every page component imports correctly: check for missing exports in `api.ts`

### Journey 5: API — All Endpoints Respond
- List ALL routes defined in `api/routes/*.py`
- Cross-reference with `api/server.py` router includes
- Check for any route file that exists but isn't mounted
- Check for any API hook in `web/src/lib/api.ts` that calls an endpoint not defined in backend
- Look for 404-prone mismatches (e.g., `/api/experiments/pareto` was missing before)

### Journey 6: Database — No Schema Collisions
- Check `api/server.py` for ALL database store instantiations
- Verify each store uses a separate DB file (after P0 fix)
- Verify no two stores create conflicting tables in the same DB
- Test: `python3 -c "from core.skills.store import SkillStore; s = SkillStore(':memory:'); print('Skills OK'); s.close()"`
- Test: `python3 -c "from registry.skill_store import RegistryStore; s = RegistryStore(':memory:'); print('Registry OK'); s.close()"` (or equivalent)

### Journey 7: Optimization Loop
- Verify `runner.py` loop command exists and has correct args
- Check that TraceCollector is wired into runner (after P0 fix)
- Check that default mutations don't include NotImplementedError stubs
- Verify autoagent.yaml default config is sane (mock mode should be off or clearly warned)

### Journey 8: Builder Workspace
- Verify `/builder` route exists in App.tsx
- Verify BuilderWorkspace.tsx imports all required components
- Check that all builder API endpoints exist in backend
- Verify demo route `/builder/demo` works

### Journey 9: Skills System
- Verify Skills, AgentSkills, and Registry pages are routed
- Check that skill store migrations work (the legacy schema fix)
- Verify skill API endpoints exist

### Journey 10: Tests Pass
- Run: `python3 -m pytest tests/ -x -q --tb=short 2>&1 | tail -30`
- If tests fail, investigate and fix the root cause
- Report pass/fail count

## Output

Create `JOURNEY_AUDIT_RESULTS.md` with a table:

| Journey | Status | Issues Found | Fixes Applied |
|---------|--------|-------------|---------------|

Fix all P0/P1 issues you find. For P2 issues, document but don't necessarily fix.

## When done:
- `git add -A && git commit -m "audit: End-to-end user journey verification + fixes" && git push`
- `openclaw system event --text "Done: Journey audit — all critical paths verified" --mode now`
