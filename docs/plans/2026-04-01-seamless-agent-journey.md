# Seamless Agent Journey Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a seamless Build → Eval → Optimize journey by introducing a shared Agent Library and a session-persistent active agent across the web app.

**Architecture:** Add a lightweight `/api/agents` aggregation layer that treats versioned workspace configs as the source of truth, with save helpers delegating to the existing builder/intelligence persistence paths. On the frontend, add a small Zustand-backed active-agent store plus a reusable `AgentSelector` that replaces manual config selection on Eval and threads the selected config into Optimize.

**Tech Stack:** FastAPI, Pydantic, React 19, React Router, TanStack Query, Zustand, Vitest, Pytest

---

### Task 1: Add failing backend tests for the Agent Library

**Files:**
- Create: `tests/test_agents_api.py`
- Reuse: `tests/test_config_api.py`

**Step 1: Write the failing test**

Cover:
- `GET /api/agents` lists existing versioned configs as agent records.
- `GET /api/agents/{id}` returns the selected config.
- `POST /api/agents` saves a generated config into the workspace and returns the new agent.

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agents_api.py -q`

Expected: FAIL because `/api/agents` does not exist yet.

**Step 3: Write minimal implementation**

Implement `api/routes/agents.py`, wire it into the FastAPI app, and reuse existing workspace/config persistence helpers.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agents_api.py -q`

Expected: PASS.

### Task 2: Add failing backend tests for config-aware optimization

**Files:**
- Modify: `tests/test_optimize_api.py`
- Modify: `api/models.py`
- Modify: `api/routes/optimize.py`

**Step 1: Write the failing test**

Add a test asserting `/api/optimize/run` accepts `config_path` and evaluates/deploys against that selected config rather than only the active config.

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_optimize_api.py -q`

Expected: FAIL because `OptimizeRequest` does not accept `config_path`.

**Step 3: Write minimal implementation**

Add `config_path` to the request model and load that config inside the optimize route before running the cycle.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_optimize_api.py -q`

Expected: PASS.

### Task 3: Add failing frontend tests for the seamless journey

**Files:**
- Modify: `web/src/pages/Build.test.tsx`
- Modify: `web/src/pages/EvalRuns.test.tsx`
- Modify: `web/src/pages/Optimize.test.tsx`
- Create: `web/src/components/AgentSelector.tsx`
- Create: `web/src/lib/active-agent.ts`

**Step 1: Write the failing test**

Cover:
- Build save flow sets up a seamless continue-to-eval CTA.
- Eval page renders an agent selector instead of a config version selector and starts evals with the selected agent config.
- Optimize page renders the same selector and starts optimization with the selected agent config.

**Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/pages/Build.test.tsx src/pages/EvalRuns.test.tsx src/pages/Optimize.test.tsx`

Expected: FAIL because the selector/store/CTA flow does not exist yet.

**Step 3: Write minimal implementation**

Add the Agent Library hooks, the active-agent store, selector UI, and the page-level route/state handoff behavior.

**Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/pages/Build.test.tsx src/pages/EvalRuns.test.tsx src/pages/Optimize.test.tsx`

Expected: PASS.

### Task 4: Add toast CTA support and generator autofill behavior

**Files:**
- Modify: `web/src/lib/toast.ts`
- Modify: `web/src/components/ToastViewport.tsx`
- Modify: `web/src/components/EvalGenerator.tsx`

**Step 1: Write the failing test**

Extend the Build/Eval tests so they expect:
- toast CTA buttons to render,
- Eval generation to use the selected agent config without manual copy/paste.

**Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/pages/Build.test.tsx src/pages/EvalRuns.test.tsx`

Expected: FAIL.

**Step 3: Write minimal implementation**

Add optional toast actions and let `EvalGenerator` accept a preloaded agent config.

**Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/pages/Build.test.tsx src/pages/EvalRuns.test.tsx`

Expected: PASS.

### Task 5: Full verification and delivery

**Files:**
- Modify: `api/server.py`
- Modify: `web/src/lib/api.ts`
- Modify: `web/src/pages/Build.tsx`
- Modify: `web/src/pages/EvalRuns.tsx`
- Modify: `web/src/pages/Optimize.tsx`
- Modify: any touched tests

**Step 1: Run focused verification**

Run:
- `python -m pytest tests/test_agents_api.py tests/test_optimize_api.py -q`
- `cd web && npx vitest run src/pages/Build.test.tsx src/pages/EvalRuns.test.tsx src/pages/Optimize.test.tsx`

**Step 2: Run project-required verification**

Run:
- `cd web && npx tsc --noEmit`
- `cd web && npx vite build`
- `cd .. && python -m pytest tests/ -x -q 2>&1 | tail -20`

**Step 3: Commit and push**

Run:
- `git add ...`
- `git commit -m "feat: seamless Build → Eval → Optimize journey with Agent Library"`
- `git push origin master`

**Step 4: Completion event**

Run:
- `openclaw system event --text "Done: Seamless agent journey — Build to Eval to Optimize with Agent Library" --mode now`
