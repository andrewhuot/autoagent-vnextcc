# Web App Guide

This guide walks through the AutoAgent VNextCC web console and explains what each page is for, what data it uses, and how operators typically use it in practice.

The app is served by the FastAPI server at `http://localhost:8000` when you run:

```bash
autoagent server
```

## Route Map

| Page | Route | Primary job |
|---|---|---|
| Dashboard | `/` | System health snapshot and recent optimization activity |
| Eval Runs | `/evals` | Start eval runs and compare run-level outcomes |
| Eval Detail | `/evals/:id` | Investigate one run at per-case granularity |
| Optimize | `/optimize` | Trigger optimization cycles and inspect gate outcomes |
| Configs | `/configs` | Browse versioned configs, inspect YAML, diff versions |
| Conversations | `/conversations` | Explore user conversations, filters, and tool traces |
| Deploy | `/deploy` | Manage active/canary versions, rollback, and history |
| Loop Monitor | `/loop` | Run/stop continuous loop and watch cycle-by-cycle progress |
| Settings | `/settings` | Operator shortcuts and runtime path reference |

## Global UX

### Layout and Navigation

- Left sidebar includes all 9 pages and highlights the active route.
- Sidebar collapses into a mobile drawer on smaller screens.
- Header includes page title plus breadcrumbs:
  - Example: `Eval Runs / Run <id>` on `/evals/:id`.

### Command Palette

Open the global command palette with `Cmd+K` (or `Ctrl+K` on Windows/Linux).

It includes:
- Static actions (new eval, optimize, deploy, dashboard, conversations)
- Recent eval runs
- Recent config versions
- Recent conversations

### Keyboard Shortcuts

Global shortcuts (ignored while typing in form fields):
- `n` -> open new eval flow (`/evals?new=1`)
- `o` -> open optimize flow (`/optimize?new=1`)
- `d` -> open deploy flow (`/deploy?new=1`)

### Toast Notifications

Asynchronous operations show toast feedback for start/success/failure:
- Eval started/completed
- Optimization started/completed/failed
- Deploy and rollback results
- Loop start/stop results

### Real-Time WebSocket Updates

The app maintains a persistent WebSocket connection to:

```text
ws://<host>/ws
```

Message types used by the UI:
- `eval_complete`
- `optimize_complete`
- `loop_cycle`

## Page Walkthrough

## Dashboard (`/`)

Purpose: quickly answer “is the system healthy right now?”

### What you see

- Health ring score (derived from success/error/safety/latency)
- Metric cards:
  - success rate
  - average latency
  - error rate
  - safety violation rate
  - average cost
  - total conversations
- Score trajectory chart from optimization history
- Recent optimization timeline entries

### Data sources

- `GET /api/health`
- `GET /api/optimize/history`

### Typical actions

- Run a fresh eval (`New Eval`)
- Jump to optimization history/details
- Refresh health data

## Eval Runs (`/evals`)

Purpose: create and track eval runs, then compare run outcomes.

### What you see

- “Start New Evaluation” form:
  - optional config version
  - optional category filter
- Runs table with status/progress/score/case counts
- Comparison mode for any two runs side-by-side

### Data sources

- `GET /api/eval/runs`
- `GET /api/config/list`
- `POST /api/eval/run`
- WebSocket `eval_complete`

### Typical actions

- Launch a run against active config
- Launch a category-specific run (`safety`, etc.)
- Compare two completed runs before choosing a deploy candidate

## Eval Detail (`/evals/:id`)

Purpose: inspect one eval run deeply.

### What you see

- Run header with status, timestamp, pass count, and safety failure callout
- Composite score block
- Score bars for quality/safety/latency/cost
- Per-case table with:
  - category filter
  - pass/fail filter
  - sorting (quality, latency, case id)
- Expandable case row for deeper details

### Data sources

- `GET /api/eval/runs/{run_id}`
- If run is still active (`409`), UI falls back to task data from `GET /api/eval/runs`

### Typical actions

- Diagnose failing cases
- Identify regression signatures before optimizing/deploying

## Optimize (`/optimize`)

Purpose: run one optimize cycle and inspect gate decisions.

### What you see

- Optimization controls:
  - observation window
  - `force` toggle
- Active task progress (polling `/api/tasks/{id}`)
- Score trajectory chart across historical attempts
- Timeline of attempts with status badges
- Diff/details panel for selected attempt

### Data sources

- `GET /api/optimize/history`
- `POST /api/optimize/run`
- `GET /api/tasks/{task_id}`
- WebSocket `optimize_complete`

### Typical actions

- Trigger a cycle from current traffic state
- Confirm whether rejection reason is safety/no-improvement/regression/invalid/noop
- Review config diffs before deployment decisions

## Configs (`/configs`)

Purpose: understand exactly what changed between config versions.

### What you see

- Version list with status/hash/composite/timestamp
- YAML viewer for selected version
- Compare mode with side-by-side diff for two versions

### Data sources

- `GET /api/config/list`
- `GET /api/config/show/{version}`
- `GET /api/config/diff?a={a}&b={b}`

### Typical actions

- Validate accepted optimizer changes
- Confirm active/canary lineage before deploy

## Conversations (`/conversations`)

Purpose: inspect real conversations and tool traces.

### What you see

- Overview stats (visible total, success rate, avg latency, avg tokens)
- Filters: outcome, limit, search
- Conversation table with expandable detail panel
- Detailed conversation view with:
  - user and agent turns
  - tool call summaries
  - safety flags and error messages

### Data sources

- `GET /api/conversations`

### Typical actions

- Find failure examples to guide optimization
- Confirm specialist routing and tool behavior

## Deploy (`/deploy`)

Purpose: promote stable configs safely.

### What you see

- Active version card
- Canary version card + canary verdict block
- Deploy form:
  - version selection
  - strategy (`canary` or `immediate`)
- Deployment history table
- Rollback action for active canary

### Data sources

- `GET /api/deploy/status`
- `POST /api/deploy`
- `POST /api/deploy/rollback`
- `GET /api/config/list`

### Typical actions

- Deploy a candidate as canary
- Monitor verdict and rates
- Roll back immediately when canary underperforms

## Loop Monitor (`/loop`)

Purpose: run continuous observe -> optimize -> deploy cycles.

### What you see

- Loop control form (cycles, delay, window)
- Running/idle status and progress counters
- Success-rate trajectory chart
- Per-cycle cards with optimization/deploy/canary outcomes

### Data sources

- `GET /api/loop/status`
- `POST /api/loop/start`
- `POST /api/loop/stop`
- WebSocket `loop_cycle`

### Typical actions

- Launch overnight iterative runs
- Stop loop when degradation appears
- Review cycle-level acceptance/rejection cadence

## Settings (`/settings`)

Purpose: operational quick-reference.

### What you see

- Key project file paths (config, evals, storage)
- Keyboard shortcut reference
- Links to API docs (`/docs`, `/redoc`)

This page is informational and does not mutate system state.

## Practical Operator Flows

## Flow A: Baseline a new config

1. Open **Eval Runs** and launch a run for the target version.
2. Open **Eval Detail** and inspect failed cases + score distribution.
3. Open **Configs** and diff against active version.

## Flow B: Improve reliability

1. Open **Conversations** and filter to `fail`/`error`.
2. Open **Optimize** and run a cycle with appropriate window.
3. Review attempt status and diff.
4. Open **Deploy** and canary deploy accepted versions.

## Flow C: Continuous overnight iteration

1. Open **Loop Monitor**.
2. Start loop with target cycles and delay.
3. Monitor cycle cards and trajectory.
4. Stop loop if severe degradation appears.

## Troubleshooting UI Data

- Dashboard empty: confirm conversation data exists (`autoagent status` / eval runs).
- Eval detail stuck in running: check task state via `GET /api/tasks/{task_id}`.
- Deploy history empty: ensure at least one deployment has occurred.
- No real-time updates: verify WebSocket connectivity to `/ws`.

