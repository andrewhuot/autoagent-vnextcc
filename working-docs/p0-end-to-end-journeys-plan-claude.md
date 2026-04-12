# P0 End-to-End Journey Fixes — Implementation Plan

**Date:** 2026-04-12
**Author:** Claude Opus 4.6
**Branch:** feat/p0-end-to-end-journeys-claude
**Issue:** #3 — Fix broken end-to-end journeys

---

## Mission

Fix the four highest-value broken end-to-end journeys that make the product feel sloppy for real operators:

1. **Task/eval/optimize history survives restart** — TaskManager is ephemeral
2. **Canary promote available in web UI** — Deploy page missing "Promote" button
3. **Connect import registers with running server** — Imported agents invisible until restart
4. **Builder/workbench chat/session state survives restart** — BuilderChatService sessions in-memory only

---

## Fix 1: Persist TaskManager to SQLite

### Problem
`TaskManager._tasks` is a plain `dict[str, Task]` in memory. After server restart, the EvalRuns page shows empty state even though eval results are durably stored in `eval_results.db`. Users expect `/evals` to show their recent runs.

### Root Cause
- `api/tasks.py:53` — `self._tasks: dict[str, Task] = {}`
- No SQLite write on task create/update
- No SQLite read on startup

### Implementation

**File: `api/tasks.py`**
1. Add SQLite persistence with a `tasks.db` file (configurable path)
2. Create table: `tasks(task_id TEXT PK, task_type TEXT, status TEXT, progress INT, result TEXT, error TEXT, created_at TEXT, updated_at TEXT)`
3. On `create_task()` — INSERT row
4. On task status transitions (running, completed, failed) — UPDATE row
5. On `update_task()` — UPDATE row
6. On `__init__()` — load historical tasks from DB, mark any `running` tasks as `interrupted`
7. `result` stored as JSON text

**File: `api/server.py`**
- Pass `db_path` to `TaskManager()` constructor (default `.agentlab/tasks.db`)

### Risk
- Thread safety: existing `threading.Lock()` already handles concurrent access; DB writes happen inside the lock
- Migration: no existing DB to migrate; clean start

---

## Fix 2: Add Canary Promote to Deploy Page

### Problem
The Deploy page has canary start and rollback but not promotion. The final step of the deployment workflow requires CLI.

### Root Cause
- `api/routes/deploy.py` — no dedicated `/api/deploy/promote` endpoint (promotion is buried inside POST `/api/deploy` with specific param combos)
- `web/src/pages/Deploy.tsx` — no "Promote" button in the canary verdict section

### Implementation

**File: `api/routes/deploy.py`**
1. Add `POST /api/deploy/promote` endpoint
2. Accepts optional `version` param; defaults to current canary
3. Calls `vm.promote(version)`
4. Returns `DeployResponse`

**File: `web/src/lib/api.ts`**
1. Add `usePromoteCanary()` mutation hook
2. POST to `/deploy/promote`
3. Invalidate `deployStatus`, `deployHistory`, `configs` query keys

**File: `web/src/pages/Deploy.tsx`**
1. Add "Promote" button next to "Rollback" in the canary verdict section
2. Show only when canary is active and verdict is "promote" or "pending"
3. Confirm before promoting (reuse existing confirmation pattern)

### Risk
- Low: promote logic already exists in `ConfigVersionManager.promote()` and is battle-tested

---

## Fix 3: Connect Import Registers with Running Server

### Problem
Importing an agent via Connect/ADK/CX creates a workspace directory that the running server does not track. The result panel links to `/evals` and `/configs`, but neither shows the imported agent.

### Root Cause
- `adapters/workspace_builder.py:create_connected_workspace()` writes config to isolated workspace
- The API server's `ConfigVersionManager` only reads from its own `configs/` directory
- After import, no call is made to register the new config

### Implementation

**File: `api/routes/connect.py`**
1. After successful import, read the generated config from the workspace
2. Register it with `version_manager.save_version(config, scores={}, status="candidate")`
3. Accept `request: Request` to access `app.state.version_manager`
4. Return the new version number in the response

**File: `api/routes/adk.py`**
1. Same pattern: after ADK import, register config with the server's version_manager
2. Accept `request: Request` parameter

**File: `deployer/versioning.py`**
1. Add `reload()` method that refreshes manifest from disk

### Risk
- Medium: imported configs may reference paths in the new workspace, not the server's workspace. But for the agent library listing and eval running, the config content itself is what matters.

---

## Fix 4: Persist BuilderChatService Sessions to SQLite

### Problem
`BuilderChatService._sessions` is an in-memory dict. Sessions lost on server restart.

### Root Cause
- `builder/chat_service.py:41` — `self._sessions: dict[str, BuilderChatSession] = {}`
- No persistence layer for chat sessions (distinct from `BuilderStore` which handles workspace sessions)

### Implementation

**File: `builder/chat_service.py`**
1. Add SQLite persistence with a configurable db_path (default `.agentlab/builder_chat_sessions.db`)
2. Create table: `chat_sessions(session_id TEXT PK, created_at REAL, updated_at REAL, payload TEXT)`
3. `payload` is JSON-serialized full session state (messages, config, generated_config, mock_mode, etc.)
4. On `handle_message()` — upsert session after each message
5. On `_get_or_create_session()` — check DB before creating new session
6. On `__init__()` — create table if not exists
7. Add `list_sessions()` method for API discoverability

**File: `api/routes/builder.py`**
1. Add `GET /api/builder/sessions` endpoint listing available chat sessions
2. Wire `db_path` through from server initialization

**File: `api/server.py`**
1. Initialize `BuilderChatService` eagerly in lifespan with `db_path`
2. Attach to `app.state.builder_chat_service`

### Risk
- Serialization: `generated_config` is a dict, `BuilderChatSession` dataclasses have nested structures. Use `dataclasses.asdict()` for serialization and reconstruct on load.
- Session size: each session with messages could be ~10-50KB JSON. Acceptable for SQLite.

---

## Test Plan

Each fix gets a dedicated test:
1. **TaskManager**: test persist/reload cycle, interrupted task marking
2. **Deploy promote**: test API endpoint returns correct response, test promotion state change
3. **Connect import**: test that imported agent appears in version manager
4. **Builder chat sessions**: test session survives service recreation

---

## Implementation Order

All four fixes are independent — implement in parallel via agent team.
