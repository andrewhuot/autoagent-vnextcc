# Fixes From PM/Engineering Review

**Reviewer:** Claude Sonnet 4.6
**Date:** 2026-03-29
**Scope:** Full codebase audit for broken imports, dead code, missing routes, crashes

---

## Summary

The codebase is in good shape. All 47 route modules import cleanly, all 2,938 tests pass, and `api.server` initializes without errors. No broken routes, no missing module files, no import crashes found.

One stale comment was corrected. The remaining gaps identified are product-level (missing features, architectural limitations) captured in the roadmap, not code-level bugs.

---

## Code Fix Applied

### Fix 1: Stale TODO comment in `api/routes/skills.py`

**File:** `api/routes/skills.py:50–52`

**Problem:** The comment read:
```python
# For now, create a store on demand. In production, initialize in lifespan.
# TODO: Add to api.server.py lifespan as app.state.core_skill_store
```
This was misleading — `app.state.core_skill_store` **is** already initialized in `api/server.py` lifespan (line 263: `app.state.core_skill_store = skill_store`). The TODO was a false alarm left over from an earlier iteration.

**Fix:**
```python
# app.state.core_skill_store is initialized in api.server.py lifespan.
# Fall back to on-demand creation only in tests or standalone use.
store = getattr(request.app.state, "core_skill_store", None)
```

**Impact:** Low (comment only). Eliminates false signal for future contributors who might try to "fix" the TODO by adding a duplicate initialization.

---

## Issues Found (Not Code Bugs — Product Gaps)

These are architectural limitations or missing features, not fixable with a single-file edit. They are captured as P0/P1 items in `PM_ROADMAP_REPORT_CC.md`.

### Gap 1: EvalRunner defaults to mock agent function
**File:** `evals/runner.py:70`
```python
self.agent_fn = agent_fn or mock_agent_response
```
The eval runner uses `mock_agent_response` when no real agent is wired. All eval scores in the web UI are simulated unless a caller explicitly passes an `agent_fn`. The server startup code at `api/server.py:162–163` even adds a warning message:
```python
eval_runner.mock_mode_messages = [
    "Eval harness is using mock_agent_response, so eval scores remain simulated..."
]
```
**Status:** Known, acknowledged in code. Roadmap item #1.

### Gap 2: Mock mode is default with no visible UI warning
**Files:** `autoagent.yaml`, `optimizer/proposer.py:93`
```yaml
optimizer:
  use_mock: true  # default
```
The `Proposer` defaults to `use_mock=True`. No banner or warning appears on optimization-adjacent UI pages (Dashboard, Live Optimize, Experiments) when mock mode is active. A demo without API keys produces realistic-looking but entirely synthetic optimization results.
**Status:** UX gap. Roadmap item #2.

### Gap 3: Transcript intelligence uses keyword-based intent classification
**File:** `optimizer/transcript_intelligence.py:21–27`
```python
INTENT_KEYWORDS: dict[str, list[str]] = {
    "order_tracking": ["where is my order", "track my order", ...],
    "cancellation": ["cancel my order", ...],
}
```
Intent classification in the Intelligence Studio is regex/keyword matching rather than LLM-powered. Works for the demo corpus but is fragile on real customer data.
**Status:** Product gap. Roadmap item #3.

### Gap 4: No authentication middleware
**File:** `api/server.py` — no auth middleware present
Zero authentication on the FastAPI server. All 200+ endpoints are accessible without credentials.
**Status:** Critical for enterprise. Roadmap item #4.

### Gap 5: SQLite only — no Postgres support
**File:** `api/server.py:76–78`
```python
CONVERSATIONS_DB = os.environ.get("AUTOAGENT_DB", "conversations.db")
```
Eight SQLite databases with direct `sqlite3` module usage. No ORM, no connection string abstraction, no Postgres support.
**Status:** Scale blocker. Roadmap item #8.

---

## Verification Commands Run

```bash
# All tests pass
pytest tests/ -q --tb=no
# Result: 2938 passed, 10 warnings in 118.27s

# Server imports clean
python -c "import api.server"
# Result: no output (success)

# All 47 route modules import cleanly
python -c "from api.routes import a2a, adk, agent_skills, ..."
# Result: All route imports OK

# 47 routers registered in server.py
grep "app.include_router" api/server.py | wc -l
# Result: 47
```

---

## No Issues Found In

- All 47 route module imports ✅
- All `app.include_router` registrations ✅
- All `app.state.*` assignments in lifespan ✅
- Core optimizer loop imports and initialization ✅
- Builder workspace services initialization ✅
- Skills system (core + registry) initialization ✅
- Notification manager, registry store, runbook store ✅
- AutoFix engine, judge stack, context workbench ✅
