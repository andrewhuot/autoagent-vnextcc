# API Reference

All endpoints are served under `/api/`. The server runs on `http://localhost:8000` by default.

Start the server:

```bash
autoagent server
```

---

## Eval

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/eval/run` | Start an eval run as a background task |
| `GET` | `/api/eval/runs` | List all eval runs |
| `GET` | `/api/eval/runs/{id}` | Get a specific eval run by ID |
| `GET` | `/api/eval/runs/{id}/cases` | Get individual case results for a run |
| `GET` | `/api/eval/history` | List eval history entries |
| `GET` | `/api/eval/history/{id}` | Get a specific history entry |

### POST `/api/eval/run`

```json
// Request
{
  "config_path": "configs/v002.yaml",
  "category": "happy_path",
  "dataset_path": "data/eval_set.jsonl",
  "split": "test"
}

// Response (202 Accepted)
{
  "task_id": "task_abc123",
  "status": "running"
}
```

### GET `/api/eval/runs/{id}`

```json
// Response
{
  "run_id": "run_abc123",
  "quality": 0.89,
  "safety": 1.0,
  "latency": 0.92,
  "cost": 0.95,
  "composite": 0.91,
  "safety_failures": 0,
  "total_cases": 50,
  "passed_cases": 45,
  "completed_at": "2026-03-24T10:30:00Z"
}
```

---

## Optimize

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/optimize/run` | Start an optimization cycle |
| `GET` | `/api/optimize/history` | List optimization history |
| `GET` | `/api/optimize/history/{id}` | Get a specific optimization result |
| `GET` | `/api/optimize/pareto` | Get the Pareto frontier of optimization results |

### POST `/api/optimize/run`

```json
// Request
{
  "cycles": 3
}

// Response (202 Accepted)
{
  "task_id": "task_opt_456",
  "status": "running"
}
```

---

## Loop

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/loop/start` | Start the optimization loop |
| `POST` | `/api/loop/stop` | Stop the optimization loop |
| `GET` | `/api/loop/status` | Get current loop status |

### GET `/api/loop/status`

```json
// Response
{
  "running": true,
  "cycle": 12,
  "max_cycles": 100,
  "schedule": "continuous",
  "last_heartbeat": 1711276800.0
}
```

---

## Control

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/control/state` | Get current human control state |
| `POST` | `/api/control/pause` | Pause the optimization loop |
| `POST` | `/api/control/resume` | Resume the optimization loop |
| `POST` | `/api/control/pin/{surface}` | Pin a configuration surface |
| `POST` | `/api/control/unpin/{surface}` | Unpin a configuration surface |
| `POST` | `/api/control/reject/{id}` | Reject an experiment |
| `POST` | `/api/control/inject` | Inject a manual configuration change |

### GET `/api/control/state`

```json
// Response
{
  "paused": false,
  "pinned_surfaces": ["safety_instructions"],
  "immutable_surfaces": ["safety_instructions"]
}
```

---

## Deploy

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/deploy/deploy` | Deploy a config version |
| `GET` | `/api/deploy/status` | Get current deployment status |
| `POST` | `/api/deploy/rollback` | Roll back to previous version |

### POST `/api/deploy/deploy`

```json
// Request
{
  "config_version": 3,
  "strategy": "canary"
}
```

---

## Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health/ready` | Lightweight readiness probe |
| `GET` | `/api/health` | Full health report with metrics and anomalies |
| `GET` | `/api/health/system` | Operational health (loop, watchdog, dead letters) |
| `GET` | `/api/health/cost` | Spend trend and budget posture |
| `GET` | `/api/health/eval-set` | Eval set health diagnostics |
| `GET` | `/api/health/scorecard` | 2-gate + 4-metric scorecard |

### GET `/api/health/scorecard`

```json
// Response
{
  "gates": {
    "safety": { "passed": true, "safety_violation_rate": 0.0 },
    "regression": { "passed": true, "latest_attempt_status": "promoted" }
  },
  "metrics": {
    "task_success_rate": 0.92,
    "response_quality": 0.92,
    "latency_p95_ms": 1250.0,
    "cost_per_conversation": 0.032
  },
  "diagnostics": {
    "tool_correctness": 0.97,
    "routing_accuracy": 0.95,
    "handoff_fidelity": 0.98,
    "failure_buckets": { "tool_failure": 2, "routing_error": 1 }
  }
}
```

---

## Events

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/events` | Server-Sent Events stream for real-time updates |

Connect via EventSource for live loop progress, eval results, and deploy notifications.

---

## Config

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/config/list` | List all config versions |
| `GET` | `/api/config/show/{version}` | Get a specific config version |
| `GET` | `/api/config/diff` | Diff two config versions |
| `GET` | `/api/config/active` | Get the currently active config |

### GET `/api/config/diff`

```
GET /api/config/diff?v1=2&v2=3
```

```json
// Response
{
  "v1": 2,
  "v2": 3,
  "changes": [
    { "path": "instruction", "old": "...", "new": "..." }
  ]
}
```

---

## Conversations

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/conversations/stats` | Conversation statistics |
| `GET` | `/api/conversations/list` | List recent conversations |
| `GET` | `/api/conversations/{id}` | Get a specific conversation |

---

## Traces

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/traces/recent` | Recent trace events |
| `GET` | `/api/traces/search` | Search traces by type, agent path, or time |
| `GET` | `/api/traces/errors` | Recent error events |
| `GET` | `/api/traces/sessions/{id}` | All events for a session |
| `GET` | `/api/traces/blame` | Blame map of failure clusters |
| `GET` | `/api/traces/{id}/grades` | Span-level grades for a trace |
| `GET` | `/api/traces/{id}/graph` | Trace dependency graph |
| `GET` | `/api/traces/{id}` | Get a specific trace |

### GET `/api/traces/search`

```
GET /api/traces/search?event_type=tool_call&agent_path=support&since=1711276800&limit=50
```

### GET `/api/traces/blame`

```
GET /api/traces/blame?window=86400
```

```json
// Response
{
  "clusters": [
    {
      "grader": "tool_selection",
      "agent_path": "support",
      "reason": "wrong tool selected for order lookup",
      "count": 12,
      "impact_score": 0.85,
      "trend": "increasing"
    }
  ],
  "window_seconds": 86400
}
```

---

## Experiments

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/experiments/stats` | Experiment statistics |
| `GET` | `/api/experiments/list` | List experiments |
| `GET` | `/api/experiments/archive` | Archived experiments |
| `GET` | `/api/experiments/judge-calibration` | Judge calibration data |
| `GET` | `/api/experiments/{id}` | Get a specific experiment |

---

## Opportunities

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/opportunities/count` | Count of open optimization opportunities |
| `GET` | `/api/opportunities/list` | List optimization opportunities |
| `GET` | `/api/opportunities/{id}` | Get a specific opportunity |
| `PATCH` | `/api/opportunities/{id}/status` | Update opportunity status |

---

## AutoFix

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/autofix/suggest` | Generate fix proposals from failure analysis |
| `GET` | `/api/autofix/proposals` | List pending proposals |
| `POST` | `/api/autofix/apply/{id}` | Apply a specific proposal |
| `GET` | `/api/autofix/history` | History of applied fixes |

### POST `/api/autofix/suggest`

```json
// Response
{
  "proposals": [
    {
      "id": "fix_001",
      "surface": "instruction",
      "description": "Add explicit order lookup instructions",
      "confidence": 0.82,
      "estimated_impact": "+3% task success rate"
    }
  ]
}
```

---

## Judges

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/judges/list` | List judges and versions |
| `POST` | `/api/judges/feedback` | Submit human feedback on a judge score |
| `GET` | `/api/judges/calibration` | Judge calibration report |
| `GET` | `/api/judges/drift` | Judge drift analysis |

---

## Context

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/context/analysis/{id}` | Context analysis for a trace |
| `POST` | `/api/context/simulate` | Simulate compaction strategies |
| `GET` | `/api/context/report` | Context health report |

### POST `/api/context/simulate`

```json
// Request
{
  "strategy": "balanced"
}

// Response
{
  "strategy": "balanced",
  "estimated_token_savings": 1200,
  "estimated_quality_impact": -0.01,
  "recommendation": "Safe to apply"
}
```

---

## Registry

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/registry/search` | Search registry items |
| `POST` | `/api/registry/import` | Bulk import from file |
| `GET` | `/api/registry/{type}` | List items of a type |
| `GET` | `/api/registry/{type}/{name}/diff` | Diff versions of an item |
| `GET` | `/api/registry/{type}/{name}` | Get a specific item |
| `POST` | `/api/registry/{type}` | Create a new item |

Types: `skills`, `policies`, `tool_contracts`, `handoff_schemas`.

### GET `/api/registry/search`

```
GET /api/registry/search?q=order&type=skills
```

---

## Scorers

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/scorers/create` | Create a scorer from natural language |
| `GET` | `/api/scorers` | List all scorers |
| `GET` | `/api/scorers/{name}` | Get a scorer spec |
| `POST` | `/api/scorers/{name}/refine` | Refine a scorer with additional criteria |
| `POST` | `/api/scorers/{name}/test` | Test a scorer against eval data |

### POST `/api/scorers/create`

```json
// Request
{
  "description": "Score on empathy, accuracy, and conciseness",
  "name": "support_quality"
}

// Response
{
  "scorer": {
    "name": "support_quality",
    "dimensions": [
      { "name": "empathy", "weight": 0.33, "description": "..." },
      { "name": "accuracy", "weight": 0.34, "description": "..." },
      { "name": "conciseness", "weight": 0.33, "description": "..." }
    ]
  }
}
```
