# API Reference

Comprehensive reference for the FastAPI surface under `/api/`. The server runs on `http://localhost:8000` by default.

Start the server:

```bash
autoagent server
```

Interactive docs: `http://localhost:8000/docs` (Swagger) or `http://localhost:8000/redoc` (ReDoc).

**Route modules (registered in `api/server.py`):** `adk`, `agent_skills`, `assistant`, `autofix`, `changes`, `cicd`, `collaboration`, `config`, `context`, `control`, `conversations`, `cx_studio`, `deploy`, `diagnose`, `edit`, `eval`, `events`, `experiments`, `health`, `impact`, `intelligence`, `judges`, `knowledge`, `loop`, `memory`, `notifications`, `opportunities`, `optimize`, `optimize_stream`, `quickfix`, `registry`, `runbooks`, `sandbox`, `scorers`, `skills`, `traces`, `what_if`.

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

---

## Change Review

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/changes` | List all change cards |
| `GET` | `/api/changes/{card_id}` | Get a specific change card |
| `POST` | `/api/changes/{card_id}/apply` | Apply a change card |
| `POST` | `/api/changes/{card_id}/reject` | Reject a change card |
| `PATCH` | `/api/changes/{card_id}/hunks` | Update hunks in a change card |

---

## Runbooks

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/runbooks` | List available runbooks |
| `GET` | `/api/runbooks/{name}` | Get a specific runbook |
| `POST` | `/api/runbooks/{name}/apply` | Apply a runbook |
| `POST` | `/api/runbooks` | Create a new runbook |

---

## Memory

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/memory` | Get project memory (AUTOAGENT.md) |
| `POST` | `/api/memory` | Add to project memory |
| `PUT` | `/api/memory` | Update project memory |

---

## Skills

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/skills` | List executable skills |
| `GET` | `/api/skills/{name}` | Get a specific skill |
| `POST` | `/api/skills/{name}/apply` | Apply a skill |
| `POST` | `/api/skills/recommend` | Get skill recommendations |
| `POST` | `/api/skills/install` | Install a skill from file |
| `POST` | `/api/skills/{name}/export` | Export a skill |
| `GET` | `/api/skills/stats` | Get skill usage statistics |
| `POST` | `/api/skills/learn` | Learn skills from patterns |

---

## CX Integration

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/cx/agents` | List CX agents in a project |
| `POST` | `/api/cx/import` | Import a CX agent |
| `POST` | `/api/cx/export` | Export config to CX |
| `POST` | `/api/cx/deploy` | Deploy to CX environment |
| `POST` | `/api/cx/widget` | Generate chat widget |
| `GET` | `/api/cx/status` | Get CX agent status |

### POST `/api/cx/import`

```json
// Request
{
  "project": "my-project",
  "location": "us-central1",
  "agent_id": "abc123",
  "output_dir": "./output",
  "include_test_cases": true
}

// Response (201 Created)
{
  "config_path": "./output/agent_config.yaml",
  "eval_path": "./output/agent_eval_cases.json",
  "snapshot_path": "./output/agent_snapshot.json",
  "agent_name": "Customer Support Bot",
  "surfaces_mapped": ["prompts", "tools", "routing"],
  "test_cases_imported": 42
}
```

---

## ADK Integration

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/adk/import` | Import an ADK agent |
| `POST` | `/api/adk/export` | Export to ADK format |
| `POST` | `/api/adk/deploy` | Deploy an ADK agent |
| `GET` | `/api/adk/status` | Get ADK agent status |
| `GET` | `/api/adk/diff` | Diff ADK agent against snapshot |

### POST `/api/adk/import`

```json
// Request
{
  "path": "./agent",
  "output": "./output/agent_config.yaml"
}

// Response (201 Created)
{
  "config_path": "./output/agent_config.yaml",
  "agent_name": "ADK Agent",
  "surfaces_imported": ["prompts", "tools"]
}
```

---

## Agent Skills

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/agent-skills/gaps` | Analyze skill gaps |
| `POST` | `/api/agent-skills/analyze` | Analyze agent capabilities |
| `POST` | `/api/agent-skills/generate` | Generate new skills |
| `GET` | `/api/agent-skills` | List agent skills |
| `GET` | `/api/agent-skills/{skill_id}` | Get a specific agent skill |

### GET `/api/agent-skills/gaps`

```json
// Response
{
  "gaps": [
    {
      "category": "order_management",
      "missing_skills": ["order_cancellation", "order_modification"],
      "impact": "high",
      "recommendation": "Add cancellation flow"
    }
  ]
}
```

---

## Natural Language & Intelligence

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/edit` | Apply natural language edits to config |
| `POST` | `/api/diagnose` | Run failure diagnosis |
| `POST` | `/api/diagnose/chat` | Chat-based diagnosis session |
| `POST` | `/api/intelligence/archive` | Import transcript archive (ZIP) |
| `GET` | `/api/intelligence/reports` | List intelligence reports |
| `GET` | `/api/intelligence/reports/{id}` | Get intelligence report details |
| `POST` | `/api/intelligence/reports/{id}/ask` | Ask questions about transcript data |
| `POST` | `/api/intelligence/reports/{id}/apply` | Apply insight to create change card |

### POST `/api/edit`

```json
// Request
{
  "description": "Make the agent more empathetic in billing conversations",
  "dry_run": false
}

// Response
{
  "changes": [
    {
      "path": "instruction",
      "old": "Handle billing queries efficiently",
      "new": "Handle billing queries with empathy and patience. Acknowledge customer concerns."
    }
  ],
  "applied": true,
  "config_version": 42
}
```

### POST `/api/intelligence/archive`

Import a transcript archive (ZIP file with JSON/CSV/TXT conversations) for analytics.

```json
// Request
{
  "archive_name": "march_2026_support_transcripts.zip",
  "archive_base64": "UEsDBBQACAAIAA..."
}

// Response (201 Created)
{
  "report_id": "rpt_abc123",
  "archive_name": "march_2026_support_transcripts.zip",
  "transcript_count": 1247,
  "language_distribution": {
    "en": 892,
    "es": 245,
    "fr": 110
  },
  "intent_distribution": {
    "order_tracking": 423,
    "refund_request": 287,
    "cancellation": 198,
    "address_change": 156,
    "product_inquiry": 183
  },
  "transfer_reasons": {
    "missing_order_number": 67,
    "requires_human_verification": 42,
    "policy_gap": 38,
    "escalation_requested": 29
  },
  "procedures_extracted": 12,
  "faqs_extracted": 18,
  "missing_intents": ["exchange_request", "warranty_claim"],
  "insights": [
    {
      "insight_id": "ins_001",
      "category": "routing",
      "severity": "high",
      "description": "42% of refund requests routed to wrong agent",
      "evidence_count": 120,
      "recommended_action": "Add 'refund' keywords to billing_agent routing rules"
    }
  ]
}
```

### POST `/api/intelligence/reports/{id}/ask`

Ask questions about transcript data with natural language Q&A.

```json
// Request
{
  "question": "Why are people transferring to live support?"
}

// Response
{
  "answer": "The top 3 reasons are: (1) Missing order numbers (67 cases) — users don't have tracking info; (2) Policy gaps (38 cases) — agent can't handle return exceptions; (3) Escalation requests (29 cases) — users ask for managers.",
  "evidence": [
    {
      "conversation_id": "conv_456",
      "excerpt": "I don't have my order number, can you look it up by email?",
      "reason": "missing_order_number"
    }
  ],
  "confidence": 0.89
}
```

### POST `/api/intelligence/reports/{id}/apply`

Apply an insight to create a change card with drafted config edits.

```json
// Request
{
  "insight_id": "ins_001"
}

// Response (201 Created)
{
  "status": "pending_review",
  "drafted_change_prompt": "Add keywords 'refund', 'reimbursement', 'money back' to billing_agent routing rules",
  "change_card": {
    "card_id": "cc_789",
    "surface": "routing.rules",
    "hypothesis": "Adding refund keywords will reduce misroutes by 42%",
    "hunks": [
      {
        "path": "routing.rules[billing_agent].keywords",
        "old": "[\"billing\", \"invoice\", \"charge\"]",
        "new": "[\"billing\", \"invoice\", \"charge\", \"refund\", \"reimbursement\", \"money back\"]"
      }
    ],
    "estimated_impact": "+42% routing accuracy"
  }
}
```

---

## Tasks

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/tasks/{task_id}` | Get task status |

Used to poll status of long-running operations like eval runs and optimization cycles.

```json
// Response
{
  "task_id": "task_abc123",
  "status": "running",
  "progress": 0.65,
  "result": null
}
```

---

## WebSocket

| Path | Description |
|------|-------------|
| `WS` `/ws` | WebSocket connection for real-time updates |

Message types:
- `eval_complete` - Eval run finished
- `optimize_complete` - Optimization cycle finished
- `loop_cycle` - Loop cycle update
- `deploy_complete` - Deployment finished

---

## Summary

Total API surface: **131 endpoints** across 30 route modules + WebSocket + SSE.

Primary categories:
- **Eval & optimization** (10 endpoints) — eval runs, optimize cycles, optimize stream (SSE)
- **Config & deploy** (7 endpoints) — config versions, diffs, canary deployments
- **Observability** (18 endpoints) — traces, health scorecard, events, blame map
- **Control & gates** (7 endpoints) — pause/resume, pin/unpin, reject, inject
- **Advanced features** (15 endpoints) — judges, context workbench, autofix proposals
- **Registry & skills** (12 endpoints) — skills, runbooks, policies, tool contracts
- **Change management** (6 endpoints) — change cards, review, apply/reject
- **Integrations** (17 endpoints) — CX Agent Studio (7), ADK (5), Agent Skills (5)
- **Natural language & intelligence** (9 endpoints) — edit, diagnose, transcript intelligence
- **Core infrastructure** (30 endpoints) — conversations, experiments, opportunities, scorers, memory

**Real-time communication:**
- WebSocket (`WS /ws`) — Real-time updates for eval_complete, optimize_complete, loop_cycle, deploy_complete
- Server-Sent Events (`GET /api/events`, `GET /api/optimize/stream`) — Event streams for live optimization progress

All endpoints return JSON. Error responses follow standard HTTP status codes with structured error bodies.
