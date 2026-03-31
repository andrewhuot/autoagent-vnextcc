# API Reference

This document summarizes the current FastAPI surface under `/api/*`.

Base URL:

- `http://localhost:8000`

Recommended startup:

```bash
./start.sh
```

Backend-only alternative:

```bash
autoagent server
```

Live generated schema:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

The generated OpenAPI docs are the canonical source for full request and response schemas. This page focuses on the route families operators are most likely to use.

## Current Route Families

The backend currently registers route families for:

- setup and health
- build and builder workflows
- connect, CX, and ADK integrations
- eval runs, generated evals, structured results, and pairwise compare
- optimize, control, deploy, and loop operations
- conversations, traces, events, blame/context, and diagnostics
- runbooks, skills, registry, scorers, judges, memory, and notifications
- datasets, outcomes, preferences, rewards, sandbox, what-if, and RL workflows

## Setup and Health

| Method | Path | What it is for |
|--------|------|----------------|
| `GET` | `/api/setup/overview` | Workspace readiness, doctor summary, MCP client status, and recommended commands |
| `GET` | `/api/health` | Current top-level metrics and optimization posture |
| `GET` | `/api/health/ready` | Lightweight readiness probe |
| `GET` | `/api/health/system` | Operational health details |
| `GET` | `/api/health/cost` | Spend and cost trend view |
| `GET` | `/api/health/eval-set` | Eval-set health diagnostics |
| `GET` | `/api/health/scorecard` | Scorecard-oriented summary for the dashboard |

### Example: `GET /api/setup/overview`

Returns:

- `workspace`
- `doctor`
- `mcp_clients`
- `recommended_commands`

Representative shape:

```json
{
  "workspace": {
    "found": true,
    "path": "/path/to/workspace",
    "runtime_config_path": "/path/to/autoagent.yaml",
    "active_config_version": 1
  },
  "doctor": {
    "effective_mode": "mock",
    "preferred_mode": "mock",
    "issues": [
      "CLI is currently running in mock mode."
    ]
  },
  "mcp_clients": [
    {
      "name": "codex",
      "configured": true,
      "path": "/Users/you/.codex/config.toml"
    }
  ],
  "recommended_commands": [
    "autoagent init",
    "autoagent doctor",
    "autoagent mode show",
    "autoagent mcp status"
  ]
}
```

## Build, Config, and Authoring

| Method | Path | What it is for |
|--------|------|----------------|
| `GET` | `/api/builder/artifacts` | Builder artifact listing |
| `GET` | `/api/builder/artifacts/{artifact_id}` | One build artifact |
| `POST` | `/api/builder/chat` | Builder chat messages |
| `POST` | `/api/builder/export` | Export builder output |
| `GET` | `/api/builder/projects` | Builder projects |
| `GET` | `/api/builder/sessions` | Builder chat sessions |
| `GET` | `/api/config/list` | List config versions |
| `GET` | `/api/config/show/{version}` | Show one config version |
| `GET` | `/api/config/diff` | Diff two config versions |
| `GET` | `/api/config/active` | Get active config metadata |
| `POST` | `/api/config/activate` | Activate a config version |
| `POST` | `/api/config/import` | Import a config into the workspace |
| `POST` | `/api/config/migrate` | Migrate config format |
| `GET` | `/api/memory` | Read project memory |
| `PUT` | `/api/memory` | Replace project memory |
| `POST` | `/api/memory/note` | Append a memory note |

## Connect and Import Surfaces

| Method | Path | What it is for |
|--------|------|----------------|
| `GET` | `/api/connect` | List supported Connect adapters |
| `POST` | `/api/connect/import` | Create a workspace from an imported runtime |
| `POST` | `/api/intelligence/archive` | Upload transcript archive for analysis |
| `GET` | `/api/intelligence/reports` | List transcript reports |
| `GET` | `/api/intelligence/reports/{report_id}` | One transcript report |
| `POST` | `/api/intelligence/reports/{report_id}/ask` | Ask questions over a report |
| `POST` | `/api/intelligence/reports/{report_id}/apply` | Apply a transcript-derived insight |
| `POST` | `/api/intelligence/generate-agent` | Generate an agent from transcript analysis |

### Example: `GET /api/connect`

```json
{
  "adapters": [
    { "id": "openai-agents", "label": "OpenAI Agents", "source_field": "path" },
    { "id": "anthropic", "label": "Anthropic", "source_field": "path" },
    { "id": "http", "label": "HTTP", "source_field": "url" },
    { "id": "transcript", "label": "Transcript", "source_field": "file" }
  ],
  "count": 4
}
```

## Eval Runs, Results, and Compare

AutoAgent now exposes three related but separate eval route families.

### Eval runs

| Method | Path | What it is for |
|--------|------|----------------|
| `POST` | `/api/eval/run` | Start an eval run |
| `GET` | `/api/eval/runs` | List eval tasks/runs |
| `GET` | `/api/eval/runs/{run_id}` | Get one eval run result |
| `GET` | `/api/eval/runs/{run_id}/cases` | Get per-case results for one run |
| `GET` | `/api/eval/history` | Historical eval entries |
| `GET` | `/api/eval/history/{run_id}` | One historical eval entry |

### Generated evals

| Method | Path | What it is for |
|--------|------|----------------|
| `POST` | `/api/eval/generate` | Generate evals via the singular route family |
| `GET` | `/api/eval/generated/{suite_id}` | Fetch one generated suite |
| `POST` | `/api/eval/generated/{suite_id}/accept` | Accept a generated suite |
| `POST` | `/api/evals/generate` | Generate evals via the plural route family used by newer UI flows |
| `GET` | `/api/evals/generated` | List generated suites |
| `GET` | `/api/evals/generated/{suite_id}` | Fetch one generated suite |
| `POST` | `/api/evals/generated/{suite_id}/accept` | Accept a generated suite |

### Structured results

| Method | Path | What it is for |
|--------|------|----------------|
| `GET` | `/api/evals/results` | List recent structured result runs |
| `GET` | `/api/evals/results/{run_id}` | Full structured run payload |
| `GET` | `/api/evals/results/{run_id}/summary` | Aggregate summary for one run |
| `GET` | `/api/evals/results/{run_id}/examples` | Paginated example results |
| `GET` | `/api/evals/results/{run_id}/examples/{example_id}` | One result example |
| `POST` | `/api/evals/results/{run_id}/examples/{example_id}/annotate` | Add a human annotation |
| `GET` | `/api/evals/results/{run_id}/diff` | Diff two structured result runs |
| `GET` | `/api/evals/results/{run_id}/export` | Export a run as JSON, CSV, or Markdown |

### Pairwise compare

| Method | Path | What it is for |
|--------|------|----------------|
| `GET` | `/api/evals/compare` | List recent pairwise comparisons |
| `POST` | `/api/evals/compare` | Run and persist a pairwise comparison |
| `GET` | `/api/evals/compare/{comparison_id}` | Fetch one comparison |

### Example: `GET /api/evals/results`

Returns a list of structured result runs:

```json
{
  "runs": [
    {
      "run_id": "44c3dc5b-321",
      "mode": "mock",
      "summary": {
        "total": 1,
        "passed": 1,
        "failed": 0
      }
    }
  ],
  "count": 1
}
```

## Optimize, Control, Loop, and Deploy

| Method | Path | What it is for |
|--------|------|----------------|
| `POST` | `/api/optimize/run` | Start an optimization cycle |
| `GET` | `/api/optimize/history` | Optimization attempt history |
| `GET` | `/api/optimize/history/{attempt_id}` | One optimize attempt |
| `GET` | `/api/optimize/pareto` | Pareto/frontier view |
| `GET` | `/api/optimize/stream` | Stream optimize updates |
| `GET` | `/api/control/state` | Human control state |
| `POST` | `/api/control/pause` | Pause loop activity |
| `POST` | `/api/control/resume` | Resume loop activity |
| `POST` | `/api/control/pin/{surface}` | Pin a config surface |
| `POST` | `/api/control/unpin/{surface}` | Unpin a config surface |
| `POST` | `/api/control/reject/{experiment_id}` | Reject an experiment |
| `POST` | `/api/control/inject` | Inject a manual change |
| `POST` | `/api/deploy` | Deploy a config version or config payload |
| `GET` | `/api/deploy/status` | Current deployment status |
| `POST` | `/api/deploy/rollback` | Roll back an active canary |
| `POST` | `/api/loop/start` | Start the loop |
| `GET` | `/api/loop/status` | Loop status |
| `POST` | `/api/loop/stop` | Stop the loop |

Important note:

- the current deploy endpoint is `POST /api/deploy`
- the old `/api/deploy/deploy` path is not current

## Conversations, Traces, Events, and Diagnostics

| Method | Path | What it is for |
|--------|------|----------------|
| `GET` | `/api/conversations` | List conversations |
| `GET` | `/api/conversations/stats` | Conversation statistics |
| `GET` | `/api/conversations/{conversation_id}` | One conversation |
| `GET` | `/api/traces/recent` | Recent traces |
| `GET` | `/api/traces/search` | Search traces |
| `GET` | `/api/traces/errors` | Error-focused trace view |
| `GET` | `/api/traces/blame` | Failure clustering / blame map |
| `GET` | `/api/traces/{trace_id}` | One trace |
| `GET` | `/api/traces/{trace_id}/grades` | Trace grading detail |
| `GET` | `/api/traces/{trace_id}/graph` | Trace dependency graph |
| `POST` | `/api/traces/{trace_id}/promote` | Promote trace-derived learning |
| `GET` | `/api/events` | Event stream endpoint |
| `POST` | `/api/diagnose` | Diagnose a problem |
| `POST` | `/api/diagnose/chat` | Diagnosis chat workflow |
| `GET` | `/api/context/report` | Context report |
| `GET` | `/api/context/analysis/{trace_id}` | Context analysis for one trace |
| `POST` | `/api/context/simulate` | Simulate context strategies |

Important note:

- the current conversations list endpoint is `GET /api/conversations`
- the old `/api/conversations/list` path is not current

## Improvements, Review, and Experiment Management

| Method | Path | What it is for |
|--------|------|----------------|
| `GET` | `/api/opportunities` | List opportunities |
| `GET` | `/api/opportunities/count` | Opportunity count |
| `GET` | `/api/opportunities/{opportunity_id}` | One opportunity |
| `POST` | `/api/opportunities/{opportunity_id}/status` | Update opportunity status |
| `GET` | `/api/experiments` | List experiments |
| `GET` | `/api/experiments/archive` | Archived experiments |
| `GET` | `/api/experiments/stats` | Experiment statistics |
| `GET` | `/api/experiments/pareto` | Experiment frontier view |
| `GET` | `/api/experiments/judge-calibration` | Judge-calibration-oriented experiment view |
| `GET` | `/api/experiments/{experiment_id}` | One experiment |
| `GET` | `/api/changes` | List change cards |
| `GET` | `/api/changes/{card_id}` | One change card |
| `POST` | `/api/changes/{card_id}/apply` | Apply a change card |
| `POST` | `/api/changes/{card_id}/reject` | Reject a change card |
| `PATCH` | `/api/changes/{card_id}/hunks` | Update selected hunks |
| `GET` | `/api/reviews/pending` | Pending review requests |
| `POST` | `/api/reviews/request` | Create a review request |
| `GET` | `/api/reviews/{request_id}` | One review request |
| `POST` | `/api/reviews/{request_id}/submit` | Submit a review |

Important note:

- the current experiment list route is `GET /api/experiments`
- the current opportunity list route is `GET /api/opportunities`

## Judges, Skills, Runbooks, Scorers, and Registry

| Method | Path | What it is for |
|--------|------|----------------|
| `GET` | `/api/judges` | List judges with version and agreement data |
| `POST` | `/api/judges/feedback` | Record human feedback on judge output |
| `GET` | `/api/judges/calibration` | Judge calibration view |
| `GET` | `/api/judges/drift` | Judge drift view |
| `GET` | `/api/skills` | List skills |
| `POST` | `/api/skills` | Create a skill |
| `GET` | `/api/skills/{skill_id}` | One skill |
| `PUT` | `/api/skills/{skill_id}` | Update a skill |
| `DELETE` | `/api/skills/{skill_id}` | Delete a skill |
| `POST` | `/api/skills/{skill_id}/apply` | Apply a skill |
| `POST` | `/api/skills/install` | Install a skill |
| `GET` | `/api/skills/marketplace` | Skill marketplace |
| `GET` | `/api/runbooks` | List runbooks |
| `GET` | `/api/runbooks/{name}` | One runbook |
| `POST` | `/api/runbooks/{name}/apply` | Apply a runbook |
| `GET` | `/api/scorers` | List scorers |
| `POST` | `/api/scorers/create` | Create a scorer |
| `GET` | `/api/scorers/{name}` | One scorer |
| `POST` | `/api/scorers/{name}/refine` | Refine a scorer |
| `POST` | `/api/scorers/{name}/test` | Test a scorer |
| `GET` | `/api/registry/search` | Search registry items |
| `POST` | `/api/registry/import` | Bulk import registry items |
| `GET` | `/api/registry/{item_type}` | List items of one type |
| `GET` | `/api/registry/{item_type}/{name}` | Get one registry item |
| `GET` | `/api/registry/{item_type}/{name}/diff` | Diff registry versions |
| `POST` | `/api/registry/{item_type}` | Create a registry item |

Important notes:

- the current judge list endpoint is `GET /api/judges`
- the REST registry API currently uses `skills`, `policies`, `tool_contracts`, and `handoff_schemas` as `item_type` values
- the CLI uses `skills`, `policies`, `tools`, and `handoffs`

## CX, ADK, MCP, and Other Integrations

| Method | Path | What it is for |
|--------|------|----------------|
| `POST` | `/api/cx/auth` | Validate CX credentials |
| `GET` | `/api/cx/agents` | List CX agents |
| `POST` | `/api/cx/import` | Import a CX agent |
| `POST` | `/api/cx/diff` | Diff local state against CX |
| `POST` | `/api/cx/export` | Export local state back to CX |
| `POST` | `/api/cx/sync` | Sync local and remote CX state |
| `POST` | `/api/cx/deploy` | CX deploy workflow |
| `POST` | `/api/cx/widget` | Generate CX widget assets |
| `GET` | `/api/cx/status` | CX status |
| `GET` | `/api/cx/preview` | CX preview data |
| `POST` | `/api/adk/import` | Import ADK project |
| `POST` | `/api/adk/export` | Export ADK project |
| `POST` | `/api/adk/deploy` | ADK deploy workflow |
| `GET` | `/api/adk/status` | ADK status |
| `GET` | `/api/adk/diff` | ADK diff |
| `GET` | `/api/agent-skills/` | Agent-skills listing |
| `POST` | `/api/agent-skills/analyze` | Analyze skill gaps |
| `POST` | `/api/agent-skills/generate` | Generate new skills |
| `POST` | `/api/sandbox/test` | Sandbox test run |
| `POST` | `/api/what-if/replay` | What-if replay |

## Datasets, Outcomes, Rewards, and Preferences

| Method | Path | What it is for |
|--------|------|----------------|
| `GET` | `/api/datasets` | List datasets |
| `POST` | `/api/datasets` | Create a dataset |
| `GET` | `/api/datasets/{dataset_id}` | One dataset |
| `GET` | `/api/datasets/{dataset_id}/rows` | Dataset rows |
| `GET` | `/api/datasets/{dataset_id}/stats` | Dataset stats |
| `GET` | `/api/outcomes` | List outcomes |
| `POST` | `/api/outcomes` | Record an outcome |
| `GET` | `/api/outcomes/stats` | Outcome stats |
| `GET` | `/api/preferences/pairs` | Preference pairs |
| `POST` | `/api/preferences/pairs` | Record preference pairs |
| `GET` | `/api/preferences/stats` | Preference stats |
| `GET` | `/api/rewards` | List rewards |
| `POST` | `/api/rewards` | Create a reward |
| `POST` | `/api/rewards/{name}/test` | Test a reward |
| `POST` | `/api/rewards/{name}/audit` | Audit a reward |

## Realtime Endpoints

In addition to `/api/*`, the backend also exposes realtime channels:

- `GET /api/events`
- `GET /api/optimize/stream`
- `GET /api/demo/stream`
- WebSocket: `/ws`

These are used by the web console for live updates such as eval completion, optimize completion, and loop activity.

## Practical Guidance

Use the API surface this way:

- `setup` and `health` to confirm the environment is ready
- `builder`, `connect`, and `config` to create or import versions
- `eval`, `results`, and `compare` to measure and diagnose behavior
- `changes`, `reviews`, and `deploy` to approve and ship changes safely
- `cx`, `adk`, and `mcp` adjacent docs when you are working with external systems

## Related Docs

- [CLI Reference](cli-reference.md)
- [Platform Overview](platform-overview.md)
- [UI Quick Start Guide](UI_QUICKSTART_GUIDE.md)
- [CX Studio Integration](cx-studio-integration.md)
