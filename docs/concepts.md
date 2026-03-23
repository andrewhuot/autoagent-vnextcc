# Concepts

This document explains how AutoAgent VNextCC works as a closed-loop optimization system.

## Mental Model

AutoAgent continuously asks:
1. Is the current agent healthy?
2. If not, what should change?
3. Does the candidate improve quality without harming safety?
4. Can we deploy it safely?

That workflow is the **autoresearch loop**.

## The Autoresearch Loop

```text
┌──────────────┐
│  Observe     │  Read recent conversations, compute metrics,
│              │  detect anomalies/failure buckets
└──────┬───────┘
       │ needs optimization?
       ▼
┌──────────────┐
│  Propose     │  Optimizer proposes a config candidate based on
│              │  failure samples + health context
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  Evaluate    │  Run eval suite and compute quality/safety/
│              │  latency/cost composite score
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  Gate        │  Reject invalid/safety/regression/no-improvement
│              │  candidates; accept only safe improvements
└──────┬───────┘
       │ accepted
       ▼
┌──────────────┐
│  Deploy      │  Save version, canary rollout, promote/rollback
└──────────────┘
```

## Key Objects

### Conversation Record

Each conversation is logged with:
- `conversation_id`, `session_id`
- `user_message`, `agent_response`
- `tool_calls`
- `latency_ms`, `token_count`
- `outcome` (`success`, `fail`, `error`, `abandon`)
- `safety_flags`, `error_message`
- `config_version`, `timestamp`

### Health Report

`GET /api/health` returns:
- success rate
- error rate
- safety violation rate
- avg latency
- avg cost
- failure buckets
- optimization recommendation

### Optimization Attempt

Each attempt in `optimizer_memory.db` stores:
- `attempt_id`, `timestamp`
- `change_description`, `config_diff`, `config_section`
- `status` (`accepted`, `rejected_*`)
- `score_before`, `score_after`
- `health_context`

### Config Version

Each version in `configs/manifest.json` has:
- numeric version
- hash
- YAML filename
- score snapshot
- status (`active`, `canary`, `retired`, `rolled_back`)

## Scoring Concept

The eval system computes multiple dimensions and combines them into a composite score:
- quality
- safety
- latency
- cost

Safety is treated as a strict gate in optimization decisions. A high composite score does not override safety failures.

## Task-Based Execution

API eval/optimize/loop operations run as background tasks.

```text
POST /api/eval/run        -> { task_id }
GET  /api/tasks/{task_id} -> status/progress/result/error
```

Task states:
- `pending`
- `running`
- `completed`
- `failed`

This keeps long operations non-blocking and UI-friendly.

## Canary Concept

Canary deployment is used to reduce rollout risk:
- Deploy candidate as canary
- Observe canary vs baseline success rate
- Promote if acceptable
- Roll back if degraded

This allows optimization to remain autonomous without making unsafe full rollouts.

## Headless-First Principle

Every core workflow is available through CLI/API:
- run evals
- inspect results
- optimize
- diff configs
- deploy + rollback
- run loop

The web app exists for visibility and collaboration, not as the only control plane.

## When to Use What

- Use **CLI** for scripts, CI, and repetitive operator tasks
- Use **API** for integration into external control planes
- Use **Web** for visual debugging, comparisons, and stakeholder walkthroughs

## Failure Modes To Expect

- No conversation data yet: observer reports little signal
- Candidate rejected repeatedly: proposal quality or gate constraints too strict
- Canary stuck pending: insufficient traffic for verdict

These are expected states, not necessarily system failures.
