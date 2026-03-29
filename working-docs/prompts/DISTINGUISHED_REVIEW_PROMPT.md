# Distinguished Engineer + Technical PM Review

You are reviewing AutoAgent VNextCC as both a Distinguished Engineer and a Technical Product Manager. Your goal is to find everything that's broken, half-baked, or would embarrass us in front of a VP or customer — and fix it.

## Your Mindset

**As a Distinguished Engineer:**
- Does the architecture make sense? Are there circular dependencies, dead code, or broken abstractions?
- Do imports actually resolve? Do modules connect to each other properly?
- Are there runtime crashes hiding behind lazy imports or conditional paths?
- Is the test coverage real or are tests passing by testing mocks?
- Are there security issues (hardcoded secrets, SQL injection, missing auth)?
- Is error handling real or do exceptions just get swallowed?

**As a Technical PM:**
- Can a new user actually go from clone → running app → first optimization?
- Does every button in the UI actually do something?
- Are there features promised in the UI that don't exist in the backend?
- Is the demo actually impressive or does it fall apart on closer inspection?
- Would I be embarrassed showing this to a VP?
- Is the documentation accurate to what the code actually does?

## Systematic Review Plan

### Phase 1: Architecture Health
- Map all Python modules and their imports — find circular imports, missing modules
- Map all API routes and verify they're mounted in server.py
- Map all frontend routes and verify components exist and import cleanly
- Check for dead code (files that nothing imports)
- Run: `python3 -m py_compile` on every .py file to find syntax errors
- Run: `cd web && npx tsc --noEmit` to find TypeScript errors

### Phase 2: Integration Verification
- Verify backend boots: `python3 -c "from api.server import app"`
- Test every API endpoint returns something (not 500)
- Verify frontend compiles
- Check that frontend API hooks match actual backend endpoints
- Verify WebSocket/SSE connections are properly configured
- Check database stores don't collide

### Phase 3: User Journey Testing
Test every critical user journey end-to-end:
1. `./setup.sh` → `./start.sh` → app loads
2. Navigate every sidebar link — all pages render
3. Builder Workspace: type a message, use slash commands, switch modes
4. Dashboard: cards render with data (even mock data)
5. Optimize page: charts render without errors
6. Experiments page: table loads
7. Traces page: trace list renders
8. Settings page: all controls work
9. Skills pages: list/detail views work
10. Demo mode: guided walkthrough completes
11. CLI: `autoagent init`, `autoagent loop --help`, `autoagent server`

### Phase 4: Code Quality Sweep
- Find all `NotImplementedError` stubs in production paths
- Find all `TODO`, `FIXME`, `HACK`, `XXX` comments and assess severity
- Find all `print()` statements that should be proper logging
- Find hardcoded URLs, ports, or credentials
- Find any `except:` or `except Exception:` that swallows errors silently
- Check for proper cleanup (file handles, DB connections, background tasks)

### Phase 5: Fix Everything P0/P1
For every issue found:
- P0 (crashes, data loss, security): Fix immediately
- P1 (broken features, bad UX, wrong data): Fix immediately  
- P2 (cosmetic, minor, nice-to-have): Document but skip

## Output

Create `DISTINGUISHED_REVIEW_REPORT.md` with:

1. **Executive Summary** — Overall assessment, top 3 strengths, top 3 risks
2. **Issues Found** — Table with severity, category, description, status (fixed/documented)
3. **Architecture Assessment** — Is the architecture sound?
4. **Production Readiness Score** — Rate 1-10 with justification
5. **Recommendations** — What to do next, prioritized

## When done:
- `git add -A && git commit -m "review: Distinguished engineer + PM review — fixes and report" && git push`
- `wc -l DISTINGUISHED_REVIEW_REPORT.md`
- `openclaw system event --text "Done: Distinguished engineer review complete" --mode now`
