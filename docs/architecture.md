# Architecture

This document describes how AutoAgent VNextCC is composed at runtime and how data moves through CLI, API, optimizer, deployer, and web UI.

## System Topology

```text
┌──────────────────────────────────────────────────────────────────┐
│                       Operator Interfaces                        │
│  CLI (`autoagent ...`)   REST (`/api/*`)   Web UI (`/`)         │
└───────────────────────────────┬──────────────────────────────────┘
                                │
                         ┌──────▼──────┐
                         │ FastAPI App │  `api/server.py`
                         │  + TaskMgr  │
                         └──────┬──────┘
                                │
     ┌───────────────┬──────────┼───────────┬───────────────┐
     │               │          │           │               │
┌────▼────┐    ┌─────▼────┐ ┌───▼────┐ ┌────▼────┐    ┌────▼────┐
│Observer │    │Optimizer │ │Evals   │ │Deployer │    │Logger   │
│health   │    │gates+LLM │ │runner  │ │versions │    │SQLite   │
└────┬────┘    └─────┬────┘ └───┬────┘ └────┬────┘    └────┬────┘
     │               │          │           │               │
     └───────────────┴──────────┴───────────┴───────────────┘
                                │
                    ┌───────────▼───────────┐
                    │ Persistent State       │
                    │ conversations.db       │
                    │ optimizer_memory.db    │
                    │ configs/*.yaml         │
                    │ configs/manifest.json  │
                    └────────────────────────┘
```

## Runtime Boundaries

## 1. Control Plane

- CLI entrypoint: `runner.py`
- API entrypoint: `api/server.py`
- Web UI: `web/dist` (served by FastAPI) or `web` dev server in Vite mode

The control plane triggers tasks and surfaces results; core optimization logic lives in backend modules.

## 2. Execution Plane

Core behavior modules:
- `observer/` -> health metrics + anomalies + failure classification
- `optimizer/` -> proposal generation, config validation, eval, gates, attempt logging
- `evals/` -> case runner + scoring
- `deployer/` -> config versioning + canary lifecycle
- `logger/` -> conversation persistence and retrieval

## 3. Persistence Plane

- Conversation records: `conversations.db`
- Optimization attempt memory: `optimizer_memory.db`
- Versioned configs + metadata: `configs/` and `configs/manifest.json`

## FastAPI Composition

`api/server.py` builds a single FastAPI app and attaches shared services to `app.state` during lifespan startup:

- `conversation_store`
- `optimization_memory`
- `version_manager`
- `observer`
- `eval_runner`
- `optimizer`
- `deployer`
- `task_manager`
- `ws_manager`

Routers:
- `/api/eval/*`
- `/api/optimize/*`
- `/api/config/*`
- `/api/health`
- `/api/conversations/*`
- `/api/deploy/*`
- `/api/loop/*`
- generic task endpoints: `/api/tasks` and `/api/tasks/{task_id}`

WebSocket endpoint:
- `/ws`

SPA serving behavior:
- if `web/dist` exists, static assets and client routes are served by FastAPI
- if not, root path returns a minimal “frontend not built” HTML message

## Background Task Model

Long operations run through `api/tasks.py`.

- Each task gets a short ID (`uuid4` prefix, 12 chars)
- Tasks run in daemon threads
- Status lifecycle: `pending -> running -> completed|failed`
- Progress is integer 0-100
- Result payload is stored on completion
- Errors include traceback text for diagnostics

Task types used today:
- `eval`
- `optimize`
- `loop`

## WebSocket Event Model

The API broadcasts JSON messages to connected clients for real-time UI updates.

### `eval_complete`

```json
{
  "type": "eval_complete",
  "task_id": "abc123def456",
  "composite": 0.8515,
  "passed": 45,
  "total": 50
}
```

### `optimize_complete`

```json
{
  "type": "optimize_complete",
  "task_id": "abc123def456",
  "accepted": true,
  "status": "ACCEPTED: All gates passed..."
}
```

### `loop_cycle`

```json
{
  "type": "loop_cycle",
  "task_id": "abc123def456",
  "cycle": 3,
  "total_cycles": 20,
  "success_rate": 0.81,
  "optimized": true
}
```

Ping/pong is also supported (`{"type":"ping"}` -> `{"type":"pong"}`).

## Core Data Flow

```text
Conversation traffic logged -> Observer computes health
                         -> If unhealthy: Optimizer proposes candidate
                         -> Eval runner scores baseline + candidate
                         -> Gates decide accept/reject
                         -> Accepted candidates are deployed as canary
                         -> Canary verdict promotes or rolls back
```

### Observer Decision Rules

`Observer.observe(window=100)` marks `needs_optimization` when any condition is true:
- anomalies detected by baseline deviation logic
- `success_rate < 0.80`
- `error_rate > 0.15`
- `safety_violation_rate > 0.02`

### Optimizer Gate Rules

`optimizer/gates.py` enforces this order:
1. Safety hard gate (`safety_failures > 0` -> reject)
2. Composite must improve
3. No per-metric regression beyond threshold (default 5%)

Attempt statuses written to memory include:
- `accepted`
- `rejected_invalid`
- `rejected_safety`
- `rejected_no_improvement`
- `rejected_regression`
- `rejected_noop`

## Deploy and Canary Semantics

Version manager (`deployer/versioning.py`):
- writes immutable YAML files `vNNN.yaml`
- updates `manifest.json`
- tracks `active_version` and `canary_version`

Canary manager (`deployer/canary.py`):
- routes ~10% traffic to canary by default
- waits for minimum canary sample size (`min_canary_conversations=10`)
- compares canary success rate against baseline
- promote threshold: canary >= 95% of baseline success
- timeout fallback (`max_canary_duration_s=3600`): promote if decent data, otherwise rollback

## Persistence Model

## `conversations.db`

```sql
CREATE TABLE conversations (
    conversation_id  TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL,
    user_message     TEXT NOT NULL,
    agent_response   TEXT NOT NULL,
    tool_calls       TEXT NOT NULL DEFAULT '[]',
    latency_ms       REAL NOT NULL DEFAULT 0.0,
    token_count      INTEGER NOT NULL DEFAULT 0,
    outcome          TEXT NOT NULL DEFAULT 'unknown',
    safety_flags     TEXT NOT NULL DEFAULT '[]',
    error_message    TEXT NOT NULL DEFAULT '',
    specialist_used  TEXT NOT NULL DEFAULT '',
    config_version   TEXT NOT NULL DEFAULT '',
    timestamp        REAL NOT NULL
);
```

## `optimizer_memory.db`

```sql
CREATE TABLE attempts (
    attempt_id         TEXT PRIMARY KEY,
    timestamp          REAL NOT NULL,
    change_description TEXT NOT NULL,
    config_diff        TEXT NOT NULL,
    config_section     TEXT NOT NULL DEFAULT '',
    status             TEXT NOT NULL,
    score_before       REAL DEFAULT 0.0,
    score_after        REAL DEFAULT 0.0,
    health_context     TEXT DEFAULT ''
);
```

## `configs/manifest.json`

Tracks all saved versions and pointers:

```json
{
  "versions": [
    {
      "version": 3,
      "config_hash": "45fd2b491a90",
      "filename": "v003.yaml",
      "timestamp": 1711239000.0,
      "scores": { "composite": 0.84 },
      "status": "active"
    }
  ],
  "active_version": 3,
  "canary_version": null
}
```

## Frontend Architecture

The web app (`web/src`) is React + TypeScript + Vite with a thin API client layer.

Key patterns:
- React Query drives all server state (`web/src/lib/api.ts`)
- API client normalizes backend payloads into UI-friendly shapes
- Task polling is centralized (`useTaskStatus`)
- Global WebSocket client powers real-time updates + toasts
- Layout owns global concerns (breadcrumbs, command palette, keyboard shortcuts)

The frontend does not own business logic gates; it visualizes server decisions.

## Error-Handling Strategy

- API routes return explicit HTTP errors (`404`, `409`, `400`) where appropriate
- Long-running failures are surfaced through task status `failed` + traceback text
- UI shows structured empty/error/loading states for every major page
- Deploy rollback path is explicit and operator-invoked

## Extension Points

## 1. Agent and tools

- Add specialists under `agent/specialists/`
- Add tools under `agent/tools/`
- Extend config schema in `agent/config/schema.py`

## 2. Eval behavior

- Add YAML cases in `evals/cases/`
- Replace/mock `agent_fn` in `EvalRunner`
- Adjust weights and normalization in `evals/scorer.py`

## 3. Proposal strategy

- Swap proposer implementation in `optimizer/proposer.py`
- Keep optimizer contract: return valid config + change description

## 4. Storage backend migration

Repository currently uses SQLite adapters.
To move to Postgres, replace store/memory persistence implementations behind current interfaces.

## 5. Integrations

- Hook external control planes through API endpoints
- Use CLI for scripted pipelines
- Use WebSocket events for real-time dashboards

## Security and Operational Notes

- API currently has no built-in authn/authz middleware
- CORS is open by default for development (`allow_origins=["*"]`)
- Production deployments should add an auth boundary (ingress/IAP/API gateway)
- Secrets are not required for local core loop, but any external LLM/provider integration must use environment-managed credentials

