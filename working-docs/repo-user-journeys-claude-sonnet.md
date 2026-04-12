# AgentLab Repo Audit — User & Operator Journeys
**Audit date:** 2026-04-12  
**Auditor:** Claude Sonnet 4.6  
**Branch:** audit/full-repo-understanding-claude-sonnet

---

## Journey Overview

AgentLab supports two primary actor types:

- **User** — an AI engineer or product manager who wants to improve an agent
- **Operator** — same person in a supervisory/governance role, reviewing proposals and monitoring loop health

The main workflow is: `BUILD → EVAL → OPTIMIZE → REVIEW → DEPLOY`

All journeys are accessible via:
- **Web console** (`http://localhost:5173`) — primary UX
- **CLI** (`agentlab <command>`) — power user / automation
- **API** (`http://localhost:8000/api/`) — programmatic / CI/CD

---

## Journey 1: New User Setup

**Goal:** Go from zero to a working agent workspace with a configured provider.

### Web path
1. Opens `http://localhost:5173` → redirected to `/build`
2. Navigates to `/setup` if prompted or if health check shows mock mode
3. **Setup page** (`Setup.tsx`):
   - Enters API keys (OpenAI, Anthropic, Google)
   - `POST /api/settings/keys` → writes to `.env` file
   - `POST /api/settings/test-key` → validates each key
   - Selects mode: mock / auto / live
   - Sees "Workspace found" or "No workspace found" status
4. If no workspace: told to run `agentlab init` in terminal then refresh

### CLI path
```bash
agentlab init          # creates workspace structure
agentlab doctor        # checks keys, providers, readiness
agentlab new my-agent --template customer-support --demo  # seeds workspace
```

### Backend services
- `api/routes/setup.py` → `cli.workspace.discover_workspace()`, `cli.workspace_env.collect_provider_api_key_statuses()`
- Mode stored in `agentlab.yaml` or env var

### Friction and gaps
- **Hard CLI handoff:** If no workspace exists, the UI cannot create one. The only action is a toast message telling the user to run `agentlab init` in a terminal. There is no workspace creation flow in the web UI.
- **Silent key failure:** `hasWorkingProvider` in Setup logic is set `true` if mode is `"live"` even before any key is confirmed working. Users may advance through setup believing they have live mode, but still run in mock.
- **No persistent API key status:** Once the user leaves the Setup page, there is no persistent warning if they're in mock mode. The `/api/health` endpoint does report `mock_mode: bool` but the main navigation doesn't surface it prominently unless the user checks.

---

## Journey 2: Build — Create an Agent Config

**Goal:** Turn a natural-language description or transcript archive into an agent configuration.

### Three entry paths

#### 2a. Prompt-led Build
1. `/build` → Studio workspace with "Prompt" tab
2. User writes a description in the prompt box
3. `POST /api/intelligence/generate-agent` → `TranscriptIntelligenceService`
4. Agent config rendered in preview panel
5. Iterative refinement via `POST /api/intelligence/chat`
6. "Save to Workspace" → `POST /api/agents` → `ConfigVersionManager` writes `configs/vNNN.yaml`

#### 2b. Transcript-led Build
1. `/build` → "Transcript" tab
2. Upload JSONL archive → `POST /api/intelligence/archive`
3. Report generated → `POST /api/intelligence/generate-agent?transcript_report_id=...`
4. Config rendered, saved same as above

#### 2c. Builder Chat (Workbench)
1. `/workbench` or "Builder Chat" tab in Build
2. Natural language turn → `POST /api/workbench/build/stream` (SSE)
3. Harness runs Plan→Execute→Reflect→Present
4. Events arrive as SSE: `plan.ready`, `task.started`, `artifact.updated`, `task.completed`, `build.completed`
5. Artifacts rendered in two-pane workbench (plan tree left, artifact viewer right)
6. Follow-up iterations via `POST /api/workbench/build/iterate`

### Backend services
- `TranscriptIntelligenceService` for prompt/transcript paths
- `WorkbenchService` + `HarnessExecutionEngine` for builder chat
- `ConfigVersionManager` for config persistence
- `BuildArtifactStore` for artifact metadata

### State persisted
- Agent config: `configs/vNNN.yaml` (durable)
- Build artifacts: `.agentlab/build_artifacts.json` (durable)
- Workbench projects: `workbench.json` (durable)
- Builder chat sessions: **in-memory only** — lost on server restart

### CLI path
```bash
agentlab build "customer support agent for order tracking"
agentlab instruction show
agentlab instruction edit
```

### Friction and gaps
- **Builder chat sessions lost on restart:** `BuilderChatService._sessions` is a plain Python dict. No SQLite persistence. All unsaved sessions disappear on restart. `AgentImprover` page has client-side session recovery; core `Build.tsx` workbench does not.
- **Server CWD dependency invisible to UI:** `persist_generated_config()` calls `discover_workspace()` from the server process CWD. If the server is not started from a workspace directory, Save fails with a 400 error. No recovery path in UI.
- **Cache key split:** After generate (but before save), config is in artifact store but not agent library. `['build-artifacts']` and `['agents']` are separate React Query keys with no cross-invalidation.

---

## Journey 3: Eval — Run and Inspect

**Goal:** Run the test suite against the current agent config, inspect results, compare runs.

### Web path
1. Navigate to `/evals` (or click "Run Eval" after saving agent)
2. Select agent from dropdown → auto-populated from `/api/agents`
3. Click "Run Eval" → `POST /api/eval/run` → 202 response with `task_id`
4. Page polls `/api/tasks/{task_id}` every 2s
5. WebSocket broadcasts `eval_complete` event when done → toast with score
6. Click into run → `/evals/:id` (`EvalDetail.tsx`) — shows 9-dimension scores, per-agent breakdowns, case-level results
7. Navigate to `/results/:runId` (`ResultsExplorer.tsx`) — filter failures, annotate, export

### Eval generation
1. "Generate Eval Suite" button → `POST /api/eval/generate`
2. Suite stored in `EvalSetManager`, visible in generated evals list
3. Accept suite → `POST /api/eval/generated/{id}/accept` → becomes runnable

### Comparison
1. `/compare` page → select two run IDs → `POST /api/compare` → pairwise diff

### Backend services
- `EvalRunner` (background via `TaskManager`)
- `EvalResultsStore` for durable result persistence
- WebSocket broadcast on completion
- `EvalCacheStore` for result caching (SHA256 of config + case)

### State persisted
- Task status: **in-memory** (TaskManager) — lost on restart
- Results: SQLite `eval_results.db` — durable
- Cache: SQLite `eval_cache.db` — durable

### CLI path
```bash
agentlab eval run
agentlab eval show latest
agentlab eval compare --run-a <id> --run-b <id>
```

### Friction and gaps
- **TaskManager is ephemeral:** After server restart, the EvalRuns page shows empty state even though results are durably stored. `ResultsExplorer` reads the durable store but is a separate page users must discover.
- **Agent path coupling:** `useStartEval()` sends `config_path` as an absolute filesystem path. For imported agents (ADK/CX) whose configs are in non-default directories, this path resolves incorrectly if the server runs from a different working directory.
- **No auto-navigate on completion:** `eval_complete` WebSocket event only triggers a toast and query refetch. The user must manually click into the new run.
- **Generated eval suite UI gap:** After accepting a generated suite, there is no immediate path to run it. The user must navigate back to the main eval run UI and manually select it.

---

## Journey 4: Optimize — Improve the Agent

**Goal:** Run one or more optimization cycles to find and test config changes.

### Web path
1. Navigate to `/optimize`
2. Select optimization mode: Standard (simple proposer) / Advanced (hybrid search) / Research (full search + Pareto)
3. Click "Run Optimization" → `POST /api/optimize/run` → background task
4. Page polls task status + polls `GET /api/optimize/pending` for review items
5. WebSocket broadcasts `optimize_complete` or `optimize_pending_review`
6. If result is pending review: review panel appears with diff and scores
7. Operator clicks Approve → `POST /api/optimize/pending/{id}/approve` → deploys config
8. Operator clicks Reject → `POST /api/optimize/pending/{id}/reject` → discards

### Continuous loop
1. `/loop` page → `POST /api/loop/start` → background continuous loop
2. Checkpoint persistence to `.agentlab/loop_checkpoint.json`
3. Dead letters tracked in `.agentlab/dead_letters.db`
4. `LoopWatchdog` marks stale tasks as failed after 30 min

### Backend services
- `Optimizer` → `Observer` → `Proposer` / `HybridSearchOrchestrator` → `EvalRunner` → `Deployer`
- `PendingReviewStore` for proposals awaiting human approval (file-backed JSON)
- `OptimizationMemory` for accepted/rejected history (SQLite)
- `ExperimentStore` for full experiment records (SQLite)

### State persisted
- Pending reviews: `workspace/pending_reviews/` (file-backed, no expiry)
- Optimization history: `optimizer_memory.db` (SQLite, durable)
- Experiment records: `.agentlab/experiments.db` (SQLite, durable)

### CLI path
```bash
agentlab optimize --cycles 1
agentlab optimize --continuous
agentlab review list
agentlab review apply <id>
agentlab review reject <id>
```

### Friction and gaps
- **Two separate review queues with no unified view:** `PendingReviewStore` (optimizer proposals, visible in Optimize page) and `ChangeCardStore` (transcript intelligence proposals, visible in Improvements page) are independent. No page shows both.
- **Pending reviews have no expiry:** File-backed proposals can accumulate indefinitely with no notification after the tab is closed.
- **Optimize page only polls reviews while a task is running:** Prior-session pending reviews are fetched once then stop polling.
- **`search_strategy` from `agentlab.yaml` is not forwarded to `Optimizer`:** Server always initializes `Optimizer` with `SearchStrategy.SIMPLE` regardless of config file setting (`api/server.py:245-260`). The mode selector in the UI controls strategy correctly via the API payload; the config file setting is silently ignored.
- **Research mode maps to `SearchStrategy.FULL`, not `PRO`:** `ModeRouter._MODE_STRATEGY_MAP` maps `research → SearchStrategy.FULL`. The advanced prompt algorithms (MIPROv2, GEPA, SIMBA) require `SearchStrategy.PRO`, which is not reachable from the UI or config file.

---

## Journey 5: Deploy — Canary, Promote, Rollback

**Goal:** Ship an approved config change through canary validation to production.

### Web path
1. Navigate to `/deploy`
2. See: active version, canary version (if any), canary metrics
3. "Deploy" button → select strategy (canary/immediate) → `POST /api/deploy`
4. Canary section shows success rate, verdict, estimated promotion/rollback time
5. "Rollback" button → `POST /api/deploy/rollback`
6. **Missing:** No "Promote Canary" button — only CLI or timeout auto-promotion

### CLI path
```bash
agentlab deploy --auto-review --yes   # full pipeline
agentlab deploy canary               # start canary
agentlab deploy status               # show canary metrics
agentlab deploy promote              # promote canary to active
agentlab deploy rollback             # rollback canary
```

### Backend services
- `Deployer.deploy()` → `ConfigVersionManager` + `CanaryManager`
- `CanaryManager` — in-memory canary state (10% traffic, 10 conv minimum, 1hr timeout)
- `ConfigVersionManager` — manifest.json + `configs/vNNN.yaml` versioned files

### State persisted
- Config versions: `configs/manifest.json` + `configs/vNNN.yaml` (durable)
- Canary state: **in-memory** in `CanaryManager` — lost on restart

### Friction and gaps
- **Canary promote is CLI-only in web:** The Deploy page has no "Promote" button. Production canary workflows require CLI for the promotion step.
- **Canary state is ephemeral:** Server restart mid-canary loses all traffic metrics. Manifest still shows canary version, but no traffic data.
- **`useDeploy()` does a double roundtrip:** Fetches full config from `/api/config/show/{version}` then POSTs body to `/api/deploy`. Race condition possible if version is updated between the two calls.

---

## Journey 6: Connect — Import Existing Agent

**Goal:** Import an existing OpenAI Agents, ADK, HTTP, or transcript-backed agent into AgentLab.

### Web path (Generic)
1. `/connect` page → select provider (OpenAI Agents / Anthropic / HTTP / Transcript)
2. Fill in credentials/endpoint
3. `POST /api/connect/import` → creates new workspace directory
4. Result panel shows created paths, links to `/evals` and `/configs`

### Web path (ADK)
1. `/adk/import` page → enter ADK project path
2. `GET /api/adk/status?path=` → validate structure
3. `POST /api/adk/import` → write config + snapshot to output directory

### Web path (CX)
1. `/cx/import` page (or `/cx/studio`) → authenticate → list agents
2. Select agent → `POST /api/cx/import` → write snapshot to output directory

### Backend services
- `adapters/workspace_builder.py:create_connected_workspace()` — creates workspace dir tree
- `adk/importer.py` — parses ADK project → writes canonical config
- `cx_studio/importer.py` — imports CX agent → writes snapshot

### Critical gap
- **Connect creates isolated workspace that isn't tracked by the running server.** The running server's `ConfigVersionManager` points to a single `configs/` directory. Imported agents are written to a new directory. After import, `useCxImport()` / `useAdkImport()` invalidate `['configs']` cache, but the new configs are not in the server's `configs/` directory. The agent library (`/api/agents`) will NOT show imported agents until the server is restarted from the new workspace. The Connect result panel links to `/evals` and `/configs`, but neither will show the imported agent.

---

## Journey 7: CX Studio — Dialogflow CX Agent Management

**Goal:** Import, diff, edit, sync, and deploy Google Dialogflow CX agents.

### Web path
1. `/cx/studio` → authenticate with GCP credentials
2. List CX agents → select agent
3. Import snapshot → diff local vs cloud
4. Edit config in AgentLab
5. Sync changes back → `POST /api/cx/sync`
6. Deploy → `/cx/deploy` page → preflight check → deploy to CX environment

### Overlapping surfaces
- **`/cx/studio` and `/cx/import` both import CX agents** with no visible link between them
- `/cx/studio` requires a snapshot path from a prior import — if opened fresh, diff/sync/export buttons are silently disabled
- No persistent snapshot path across browser sessions

---

## Journey 8: Improvements / Review — Review Proposed Changes

**Goal:** Operator reviews pending optimization proposals, experiment results, and intelligence-derived insights.

### Web path
1. `/improvements` (tabbed)
2. **Opportunities tab** — ranked failure clusters from `OpportunityQueue`
3. **Experiments tab** — experiment records from `ExperimentStore` (populated only when experiments flow is used)
4. **Review tab** — `ChangeCardStore` items from transcript intelligence flow
5. **History tab** — past accepted/rejected experiments

### Friction and gaps
- **Review tab shows only ChangeCardStore items, not optimizer proposals:** Optimizer proposals live in `PendingReviewStore` and are only visible in the Optimize page. An operator using Improvements as the review hub misses these.
- **History tab shows ExperimentStore entries only:** Optimizer `OptimizationMemory` entries (accepted/rejected cycles) are not surfaced in Improvements history.
- **Stale backup files present:** `ChangeReview.tsx.backup`, `EvalRuns.tsx.backup` — likely from a refactor, should be cleaned up.
- **No Deploy action in Improvements:** The Improvements page has a "Deploy" link to `/deploy`, but applying a change card (via `POST /api/changes/{id}/apply`) does not trigger deployment. The operator must separately initiate a deploy.

---

## CLI vs UI Equivalence Map

| Action | CLI | UI | Gap |
|--------|-----|----|-----|
| Create workspace | `agentlab init` | Not available | UI requires CLI for init |
| Build agent | `agentlab build "..."` | `/build` → `/workbench` | Equivalent |
| Run eval | `agentlab eval run` | `/evals` → Run Eval | Equivalent |
| View results | `agentlab eval show` | `/results` | UI ResultsExplorer reads same DB |
| Optimize | `agentlab optimize` | `/optimize` | Equivalent; CLI skips human approval by default |
| Review proposals | `agentlab review list/apply/reject` | `/optimize` (optimizer) + `/improvements` (intelligence) | **Split queues — no unified UI** |
| Deploy (canary start) | `agentlab deploy canary` | `/deploy` → Deploy button | Equivalent |
| Deploy (canary promote) | `agentlab deploy promote` | **NOT available** | **UI missing promote action** |
| Deploy (rollback) | `agentlab deploy rollback` | `/deploy` → Rollback | Equivalent |
| View opportunities | `agentlab status` | `/improvements` → Opportunities | Equivalent |
| Run loop | `agentlab optimize --continuous` | `/loop` → Start Loop | Equivalent |
| Import ADK | `agentlab connect --adk` | `/adk/import` | Equivalent; both create new workspace dir |
| Import CX | `agentlab connect --cx` | `/cx/import` | Equivalent |
| CX diff/sync | `agentlab cx diff/sync` | `/cx/studio` | Equivalent |
| Registry CRUD | `agentlab registry add/list/show` | `/registry` | Equivalent |
| MCP server | `agentlab mcp serve` | Not in UI | CLI-only |
| Scorer create | `agentlab scorer create` | `/scorer-studio` | Equivalent |

---

## Cross-Cutting Journey Issues

### Issue 1: Server CWD as invisible dependency
Multiple journeys (Build save, Optimize, Deploy) depend on the server process running from within an AgentLab workspace directory. This is documented in the CLI guide but invisible in the web UI. Any user running the server from an arbitrary directory will hit 400 errors with no in-page recovery.

### Issue 2: Two review queues with no unified view
`PendingReviewStore` (optimizer) and `ChangeCardStore` (intelligence) are independent, persisted to different stores, and shown on different pages. No operator can see all pending decisions in one place.

### Issue 3: TaskManager is ephemeral
Both eval runs and optimization tasks are tracked in in-memory `TaskManager`. After any server restart, task lists are empty even when results were durably persisted. Users expect `/evals` to show their recent runs; they won't after a restart until they navigate to `ResultsExplorer`.

### Issue 4: Connect import does not register with running server
Imported agents from Connect/ADK/CX end up in new workspace directories that aren't tracked by the running server's `ConfigVersionManager`. The linked result panel paths (`/evals`, `/configs`) do not show the imported agent.

### Issue 5: Deploy promote missing from UI
Canary deployment workflows require CLI for the promotion step. This is a real operational gap for teams running entirely in the web console.

### Issue 6: Builder chat not persistent
Unsaved builder chat sessions are lost on server restart. The in-memory `BuilderChatService._sessions` has no persistence layer.
