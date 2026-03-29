# Agent Builder Rebuild Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the broken multi-surface builder with a single-screen conversational builder at `/build` inside the main app shell, backed by working mock-mode builder APIs and validated with Playwright.

**Architecture:** Introduce a focused conversational builder session model and API under `/api/builder` for chat, session retrieval, export, and eval generation, while keeping the old workspace/task machinery out of the critical path. On the frontend, replace the root builder workspace with a single `Builder.tsx` page rendered inside the shared `Layout`, and redirect old builder-related routes to `/build` so the app has one canonical build entry point.

**Tech Stack:** FastAPI, Pydantic, pytest, React 19, React Router, TanStack Query, Vitest, Playwright, Tailwind CSS v4.

---

### Task 1: Restore a bootable app

**Files:**
- Modify: `api/models.py`
- Test: `tests/test_generated_evals_api.py`
- Verify: `./start.sh`

**Step 1: Write the failing backend boot regression test**

Use the existing generated eval route import surface so the missing request models fail in test first.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_generated_evals_api.py -q`
Expected: import/setup failure due to missing generated-eval request models in `api.models`.

**Step 3: Write minimal implementation**

Add the missing generated eval request/response models used by `api/routes/generated_evals.py`, including:
- `AcceptGeneratedEvalSuiteRequest`
- `GenerateEvalSuiteRequest`
- `GenerateEvalSuiteResponse`
- `GeneratedEvalCasePatchRequest`
- `GeneratedEvalListResponse`
- `GeneratedEvalSuiteResponse`
- `GeneratedEvalSuiteSummary`

Keep names and field shapes aligned with the route/test usage instead of duplicating a second incompatible model family.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_generated_evals_api.py -q`
Expected: pass.

**Step 5: Verify app startup**

Run: `./start.sh`
Expected: backend and frontend both become ready.

**Step 6: Commit**

```bash
git add api/models.py tests/test_generated_evals_api.py
git commit -m "fix(api): restore generated eval model imports"
```

### Task 2: Add failing conversational builder API tests

**Files:**
- Modify: `tests/test_builder_api.py`
- Create: `tests/test_builder_chat_api.py`
- Inspect: `api/routes/builder.py`

**Step 1: Write failing tests for the new API contract**

Cover:
- `POST /api/builder/chat` creates a session when none is provided
- follow-up message mutates the current config rather than replacing unrelated sections
- `GET /api/builder/session/{id}` returns session state with messages, config, stats, and generated evals
- `POST /api/builder/export` returns a downloadable config payload
- mock mode responds with plausible airline-support examples

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_builder_chat_api.py -q`
Expected: 404s or schema failures because the new endpoints do not exist yet.

**Step 3: Keep existing builder workspace coverage isolated**

Do not delete the old `tests/test_builder_api.py` coverage until redirects and legacy compatibility are handled.

**Step 4: Commit**

```bash
git add tests/test_builder_chat_api.py tests/test_builder_api.py
git commit -m "test(api): add conversational builder route coverage"
```

### Task 3: Implement backend conversational builder state and routes

**Files:**
- Modify: `api/routes/builder.py`
- Modify: `api/server.py`
- Create: `builder/chat_service.py`
- Create: `builder/chat_types.py`
- Optionally modify: `builder/__init__.py`
- Test: `tests/test_builder_chat_api.py`

**Step 1: Write minimal backend session model**

Create in-memory mock-mode-friendly builder state containing:
- `session_id`
- conversation messages
- mutable config object
- counts/stats
- generated eval bundle
- timestamps

**Step 2: Implement deterministic config mutation logic**

Support at minimum:
- initial agent description generates base config
- “add a tool ...” appends tool definitions
- “make it more empathetic” updates system prompt tone
- “add a policy ...” appends a policy
- “generate evals” creates a plausible eval bundle
- “show me what this looks like” returns preview-oriented explanation without breaking state

Keep logic rule-based and deterministic in mock mode so tests stay stable.

**Step 3: Implement new focused endpoints**

Add:
- `POST /api/builder/chat`
- `GET /api/builder/session/{id}`
- `POST /api/builder/export`

Return a compact payload shaped for the new frontend:
- assistant reply
- updated config
- stats
- eval summary
- session metadata

**Step 4: Preserve only what is still needed from legacy builder routes**

Do not remove legacy routes until the frontend no longer depends on them. If needed, keep them temporarily alongside the new endpoints.

**Step 5: Run tests**

Run: `pytest tests/test_builder_chat_api.py tests/test_builder_api.py -q`
Expected: pass.

**Step 6: Commit**

```bash
git add api/routes/builder.py api/server.py builder/chat_service.py builder/chat_types.py tests/test_builder_chat_api.py
git commit -m "feat(api): add conversational builder session flow"
```

### Task 4: Add failing frontend tests for the new builder page

**Files:**
- Create: `web/src/pages/Builder.test.tsx`
- Inspect: `web/src/App.tsx`
- Inspect: `web/src/components/Layout.tsx`
- Inspect: `web/src/components/Sidebar.tsx`

**Step 1: Write failing component tests**

Cover:
- page renders chat panel and live config preview
- sending a message renders user + assistant messages
- preview stats update after API response
- responsive stack layout marker/classes render correctly
- export button triggers download/export call

Mock `fetch` or the page-level API wrapper only at the app boundary.

**Step 2: Run tests to verify they fail**

Run: `cd web && npm test -- src/pages/Builder.test.tsx`
Expected: module not found or failing expectations because page does not exist yet.

**Step 3: Commit**

```bash
git add web/src/pages/Builder.test.tsx
git commit -m "test(web): add single-screen builder page coverage"
```

### Task 5: Implement the new `/build` page inside the main shell

**Files:**
- Create: `web/src/pages/Builder.tsx`
- Create: `web/src/lib/builder-chat-api.ts`
- Optionally create: `web/src/components/builder-chat/*` for small focused pieces
- Modify: `web/src/App.tsx`
- Modify: `web/src/components/Layout.tsx`
- Modify: `web/src/components/Sidebar.tsx`
- Test: `web/src/pages/Builder.test.tsx`

**Step 1: Build a simple, in-shell layout**

Desktop:
- left chat panel roughly 60%
- right live preview roughly 40%

Mobile:
- stack vertically with preview below chat

Use the app’s existing light theme, borders, spacing, and header/sidebar patterns. Avoid introducing a separate route theme or extra chrome.

**Step 2: Implement the chat experience**

Include:
- message history
- composer
- pending/loading state
- sample starter prompt
- assistant replies with clarifying follow-ups when config is incomplete

**Step 3: Implement the live preview**

Include:
- syntax-highlighted-ish config card using semantic color accents already present in the app
- sections for prompt, tools, routing rules, policies, eval criteria
- stats footer
- `Download Config` and `Run Eval` buttons

**Step 4: Wire route cleanup**

Update:
- `/build` as canonical route
- `/` redirects to `/build` or `/dashboard` based on desired current app convention; for this rebuild prefer `/build` if builder remains primary landing page
- `/builder`, `/builder/*`, `/agent-studio`, and builder-demo routes redirect to `/build` when they represent superseded builder flows
- keep `/intelligence` as separate and visible

**Step 5: Put builder back inside the shell**

Remove builder/assistant full-width exceptions from `Layout.tsx` so the new page always renders with sidebar and header.

**Step 6: Update nav**

Make Build section:
- `Builder`
- `Intelligence Studio`

Remove scattered builder duplicates from other sections.

**Step 7: Run frontend tests**

Run: `cd web && npm test -- src/pages/Builder.test.tsx src/pages/AgentStudio.test.tsx`
Expected: pass, with `AgentStudio` either redirected/replaced or its test updated/deleted intentionally.

**Step 8: Commit**

```bash
git add web/src/pages/Builder.tsx web/src/lib/builder-chat-api.ts web/src/App.tsx web/src/components/Layout.tsx web/src/components/Sidebar.tsx web/src/pages/Builder.test.tsx
git commit -m "feat(web): add conversational builder page"
```

### Task 6: Clean legacy builder references and dead UI

**Files:**
- Modify or remove: `web/src/pages/BuilderWorkspace.tsx`
- Modify or remove: `web/src/pages/AgentStudio.tsx`
- Modify or remove: `web/src/pages/Assistant.tsx`
- Modify any lingering links in `web/src/pages/Dashboard.tsx` and related pages
- Test: route and nav coverage

**Step 1: Remove obsolete navigation references**

Search for:
- `Builder Workspace`
- `Builder Demo`
- `Agent Studio Draft`
- `Assistant Chat`
- `/builder`
- `/agent-studio`

Replace legacy builder calls-to-action with `/build` where appropriate.

**Step 2: Decide legacy page strategy**

Preferred:
- keep minimal redirect stubs instead of hard deletion during this change
- delete dead page code only when no routes/tests/imports still reference it

**Step 3: Run route-focused tests**

Run: `cd web && npm test`
Expected: all web unit tests pass after route updates.

**Step 4: Commit**

```bash
git add web/src pages tests
git commit -m "refactor(web): collapse legacy builder entry points"
```

### Task 7: Add and iterate on Playwright E2E coverage

**Files:**
- Create: `web/tests/builder-flow.spec.ts`
- Optionally modify: `web/playwright.config.ts`

**Step 1: Write Playwright coverage for the full agent build flow**

Cover:
- navigate to `/build` from sidebar
- verify chat + preview layout
- submit initial prompt
- verify assistant reply appears
- verify config preview updates
- add a tool
- add a policy
- run eval
- export config
- verify responsive/mobile layout

Mock backend responses only if necessary for stable route-level coverage, but also run at least one flow against the live local backend once boot is restored.

**Step 2: Run Playwright test and watch it fail**

Run: `cd web && npx playwright test tests/builder-flow.spec.ts --reporter=list`
Expected: initial failures until UI and routes are complete.

**Step 3: Fix issues and rerun iteratively**

Use the Playwright CLI during implementation, not just the formal Playwright test runner, to visually inspect layout and route behavior after major changes.

**Step 4: Commit**

```bash
git add web/tests/builder-flow.spec.ts web/playwright.config.ts
git commit -m "test(e2e): cover conversational builder flow"
```

### Task 8: Final verification and completion

**Files:**
- Update: `task_plan.md`
- Update: `progress.md`

**Step 1: Run backend verification**

Run:
```bash
pytest tests/test_generated_evals_api.py tests/test_builder_chat_api.py tests/test_builder_api.py -q
```

**Step 2: Run frontend verification**

Run:
```bash
cd web && npm test
cd web && npm run build
```

**Step 3: Run Playwright verification**

Run:
```bash
cd web && npx playwright test tests/builder-flow.spec.ts --reporter=list
```

**Step 4: Run app-level verification**

Run:
```bash
./start.sh
```

Use Playwright CLI to manually confirm:
- sidebar contains only the intended builder entries
- `/build` is in-shell
- old builder routes redirect cleanly
- export and eval buttons behave correctly
- mobile layout stacks vertically

**Step 5: Final completion command**

Run:
```bash
openclaw system event --text "Done: Agent Builder rebuilt — single-screen conversational builder integrated into main app shell, Playwright-validated" --mode now
```
