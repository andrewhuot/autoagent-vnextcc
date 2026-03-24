# API Reference

Complete reference for AutoAgent VNextCC REST + WebSocket interfaces.

## Base URLs

- REST: `http://localhost:8000/api`
- OpenAPI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- WebSocket: `ws://localhost:8000/ws`

## Conventions

- Long-running operations return task IDs
- Poll task status at `GET /api/tasks/{task_id}`
- Typical task states: `pending`, `running`, `completed`, `failed`
- Most responses are JSON objects unless noted

---

## Eval

### POST `/api/eval/run`

Start an eval run as a background task.

#### Request body

```json
{
  "config_path": "configs/v003.yaml",
  "category": "safety",
  "dataset_path": "evals/datasets/regression.jsonl",
  "split": "test"
}
```

#### Response `202`

```json
{
  "task_id": "0ddf17f0-b5ac-46df-a7ea-6b0b33a3f4f2",
  "message": "Eval run started"
}
```

#### Status codes

- `202` Started
- `404` Config file not found
- `404` Dataset file not found

#### curl

```bash
curl -X POST http://localhost:8000/api/eval/run \
  -H "Content-Type: application/json" \
  -d '{"config_path":"configs/v003.yaml","category":"safety"}'
```

### GET `/api/eval/runs`

List eval tasks.

#### Response `200`

```json
[
  {
    "task_id": "0ddf17f0-b5ac-46df-a7ea-6b0b33a3f4f2",
    "task_type": "eval",
    "status": "running",
    "progress": 40,
    "result": null,
    "error": null,
    "created_at": "2026-03-23T22:05:11.134722",
    "updated_at": "2026-03-23T22:05:14.914220"
  }
]
```

### GET `/api/eval/runs/{run_id}`

Get completed eval result payload.

#### Response `200`

```json
{
  "run_id": "0ddf17f0-b5ac-46df-a7ea-6b0b33a3f4f2",
  "quality": 0.82,
  "safety": 1.0,
  "latency": 0.85,
  "cost": 0.72,
  "composite": 0.8515,
  "safety_failures": 0,
  "total_cases": 50,
  "passed_cases": 45,
  "cases": [
    {
      "case_id": "safety_jailbreak_01",
      "category": "safety",
      "passed": true,
      "quality_score": 1.0,
      "safety_passed": true,
      "latency_ms": 183.2,
      "token_count": 122,
      "details": "Refused unsafe request"
    }
  ],
  "completed_at": "2026-03-23T22:05:19.002024+00:00"
}
```

#### Status codes

- `200` Completed result
- `404` Run not found
- `409` Task exists but not completed yet

### GET `/api/eval/runs/{run_id}/cases`

Get only case-level results.

#### Response `200`

```json
[
  {
    "case_id": "route_order_status",
    "category": "happy_path",
    "passed": true,
    "quality_score": 0.95,
    "safety_passed": true,
    "latency_ms": 220.4,
    "token_count": 142,
    "details": "Correct route + response"
  }
]
```

### GET `/api/eval/history`

List persisted eval runs with provenance.

#### Query params

- `limit` (int, default `20`)

### GET `/api/eval/history/{run_id}`

Get one persisted run with case-level payloads.

---

## Optimize

### POST `/api/optimize/run`

Start one optimization cycle as a background task.

#### Request body

```json
{
  "window": 100,
  "force": false
}
```

#### Response `202`

```json
{
  "task_id": "5dc658fb-2fd9-4022-9d2a-9e44ea58b28c",
  "message": "Optimization started"
}
```

#### curl

```bash
curl -X POST http://localhost:8000/api/optimize/run \
  -H "Content-Type: application/json" \
  -d '{"window":100,"force":false}'
```

### GET `/api/optimize/history`

List optimization attempts from memory.

#### Query params

- `limit` (int, default `20`)

#### Response `200`

```json
[
  {
    "attempt_id": "opt-1711234567",
    "timestamp": 1711234567.002,
    "change_description": "Tightened fallback prompt routing",
    "config_diff": "- prompts.fallback: ...\n+ prompts.fallback: ...",
    "config_section": "prompts",
    "status": "accepted",
    "score_before": 0.8112,
    "score_after": 0.8428,
    "significance_p_value": 0.0123,
    "significance_delta": 0.0187,
    "significance_n": 55,
    "health_context": "{\"success_rate\":0.73,\"error_rate\":0.14}"
  }
]
```

### GET `/api/optimize/history/{attempt_id}`

Get one optimization attempt.

#### Status codes

- `200` Found
- `404` Not found

---

## Config

### GET `/api/config/list`

List all config versions and active/canary pointers.

#### Response `200`

```json
{
  "versions": [
    {
      "version": 1,
      "config_hash": "d48ae9fd4f1a",
      "filename": "v001.yaml",
      "timestamp": 1711233000.0,
      "scores": { "composite": 0.75 },
      "status": "retired"
    },
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

### GET `/api/config/show/{version}`

Get YAML + parsed object for one version.

#### Response `200`

```json
{
  "version": 3,
  "yaml_content": "model: ...\nrouting: ...",
  "config": {
    "model": "...",
    "routing": {}
  }
}
```

#### Status codes

- `200` Found
- `404` Version missing

### GET `/api/config/diff?a={A}&b={B}`

Diff two config versions.

#### Response `200`

```json
{
  "version_a": 2,
  "version_b": 3,
  "diff": "- prompts.fallback: old\n+ prompts.fallback: new"
}
```

### GET `/api/config/active`

Get active config.

#### Response `200`

```json
{
  "version": 3,
  "config": { "model": "..." },
  "yaml": "model: ..."
}
```

#### Status codes

- `200` Active config exists
- `404` No active config

---

## Health

### GET `/api/health`

Compute health report from recent conversation window.

#### Query params

- `window` (int, default `100`, min `1`, max `10000`)

#### Response `200`

```json
{
  "metrics": {
    "success_rate": 0.82,
    "avg_latency_ms": 317.4,
    "error_rate": 0.09,
    "safety_violation_rate": 0.0,
    "avg_cost": 0.0008,
    "total_conversations": 100
  },
  "anomalies": [],
  "failure_buckets": {
    "routing_error": 4,
    "tool_timeout": 3
  },
  "needs_optimization": false,
  "reason": ""
}
```

### GET `/api/health/system`

Operational backend health for long-running loop behavior.

#### Response `200`

```json
{
  "status": "ok",
  "loop_running": true,
  "loop_stalled": false,
  "last_heartbeat": 1774267200.12,
  "dead_letter_count": 0,
  "tasks_running": 1,
  "uptime_seconds": 9321.44
}
```

---

## Conversations

### GET `/api/conversations/stats`

Aggregate conversation statistics.

#### Response `200`

```json
{
  "total": 821,
  "by_outcome": {
    "success": 704,
    "fail": 52,
    "error": 41,
    "abandon": 24
  },
  "avg_latency_ms": 391.2,
  "avg_token_count": 221.5
}
```

### GET `/api/conversations`

List conversation records.

#### Query params

- `limit` (int, default `50`, max `1000`)
- `offset` (int, default `0`)
- `outcome` (optional: `success|fail|error|abandon`)

#### Response `200`

```json
{
  "conversations": [
    {
      "conversation_id": "conv_01",
      "session_id": "sess_abc",
      "user_message": "Where is my order?",
      "agent_response": "Let me check that for you...",
      "tool_calls": [{ "name": "lookup_order" }],
      "latency_ms": 241.7,
      "token_count": 189,
      "outcome": "success",
      "safety_flags": [],
      "error_message": "",
      "specialist_used": "orders",
      "config_version": "v003",
      "timestamp": 1711236000.4
    }
  ],
  "total": 821,
  "limit": 50,
  "offset": 0
}
```

### GET `/api/conversations/{conversation_id}`

Get one conversation record.

#### Status codes

- `200` Found
- `404` Not found
- `500` DB read error

---

## Deploy

### POST `/api/deploy`

Deploy config data or promote a version.

#### Request body patterns

Promote existing version immediately:

```json
{
  "version": 5,
  "strategy": "immediate"
}
```

Deploy raw config as canary:

```json
{
  "config": {
    "model": "...",
    "routing": {}
  },
  "strategy": "canary",
  "scores": { "composite": 0.84 }
}
```

#### Response `201`

```json
{
  "message": "Promoted v005 to active (immediate)",
  "version": 5,
  "strategy": "immediate"
}
```

#### Status codes

- `201` Deploy action applied
- `400` Missing/invalid deploy payload
- `404` Unknown version

### GET `/api/deploy/status`

Get active/canary state and recent history.

#### Response `200`

```json
{
  "active_version": 5,
  "canary_version": 6,
  "total_versions": 8,
  "canary_status": {
    "is_active": true,
    "canary_version": 6,
    "baseline_version": 5,
    "canary_conversations": 23,
    "canary_success_rate": 0.83,
    "baseline_success_rate": 0.86,
    "started_at": 1711240000.2,
    "verdict": "pending"
  },
  "history": []
}
```

### POST `/api/deploy/rollback`

Rollback active canary.

#### Response `200`

```json
{
  "message": "Rolled back canary v006",
  "version": 6,
  "strategy": "rollback"
}
```

#### Status codes

- `200` Rolled back
- `400` No active canary
- `404` Canary version missing

---

## Loop

### POST `/api/loop/start`

Start continuous loop in background.

#### Request body

```json
{
  "cycles": 10,
  "delay": 1.0,
  "window": 100
}
```

#### Response `202`

```json
{
  "running": true,
  "task_id": "b3115c99-3f2e-4578-9b4f-4a2f9afef2f1",
  "total_cycles": 10,
  "completed_cycles": 0,
  "cycle_history": []
}
```

#### Status codes

- `202` Started
- `409` Loop already running

### POST `/api/loop/stop`

Stop active loop.

#### Response `200`

```json
{
  "running": false,
  "task_id": "b3115c99-3f2e-4578-9b4f-4a2f9afef2f1",
  "total_cycles": 10,
  "completed_cycles": 4,
  "cycle_history": []
}
```

### GET `/api/loop/status`

Get live loop status.

#### Response `200`

```json
{
  "running": true,
  "task_id": "b3115c99-3f2e-4578-9b4f-4a2f9afef2f1",
  "total_cycles": 10,
  "completed_cycles": 3,
  "cycle_history": [
    {
      "cycle": 1,
      "health_success_rate": 0.74,
      "health_error_rate": 0.16,
      "optimization_run": true,
      "optimization_result": "accepted",
      "deploy_result": "Deployed v004 as canary (10% traffic)",
      "canary_result": "Canary pending: 3 conversations so far"
    }
  ]
}
```

---

## Tasks

### GET `/api/tasks/{task_id}`

Get status for any background task.

### GET `/api/tasks`

List all tasks, optional filter:

- `task_type` (`eval|optimize|loop|...`)

---

## WebSocket

### `ws://localhost:8000/ws`

Subscribe for server push notifications.

### Server message types

- `eval_complete`
- `optimize_complete`
- `loop_cycle`

### Ping/Pong

Client can send:

```json
{ "type": "ping" }
```

Server responds:

```json
{ "type": "pong" }
```
