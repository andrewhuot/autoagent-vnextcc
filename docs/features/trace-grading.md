# Trace Grading + Blame Map

Span-level quality grading and failure cluster analysis. Understand exactly where and why your agent is failing, down to individual spans.

## TraceGrader

The `TraceGrader` evaluates individual spans within a trace using seven specialized graders:

| Grader | What it evaluates |
|--------|-------------------|
| `routing` | Was the conversation routed to the correct specialist agent? |
| `tool_selection` | Did the agent select the right tool for the task? |
| `tool_argument` | Were the tool arguments correct and complete? |
| `retrieval_quality` | Did retrieval return relevant, sufficient results? |
| `handoff_quality` | Was context preserved correctly during agent handoffs? |
| `memory_use` | Did the agent use memory/context effectively? |
| `final_outcome` | Did the conversation achieve the user's goal? |

Each grader produces a grade (pass/fail/partial) with a reason string and confidence score.

### Usage

```bash
# Grade all spans in a trace
autoagent trace grade trace_abc123
```

Output:

```
Trace: trace_abc123
  Span 1 [routing]         PASS  (confidence: 0.95)
  Span 2 [tool_selection]  PASS  (confidence: 0.88)
  Span 3 [tool_argument]   FAIL  "Missing required parameter: order_id"
  Span 4 [final_outcome]   FAIL  "User goal not achieved"
```

## BlameMap

The `BlameMap` aggregates span-level grades across many traces to identify systematic failure patterns. It clusters failures by three dimensions:

- **Grader** -- Which grader flagged the failure
- **Agent path** -- Which agent in the routing tree
- **Reason** -- The failure reason string (clustered by similarity)

Each cluster includes:

| Field | Description |
|-------|-------------|
| `count` | Number of failures in the cluster |
| `impact_score` | Weighted severity (0-1) based on failure type and downstream effects |
| `trend` | Whether the cluster is `increasing`, `decreasing`, or `stable` over time |

### Usage

```bash
# Build a blame map over the last 24 hours
autoagent trace blame --window 24h --top 10
```

Output:

```
Top failure clusters (last 24h):

1. tool_selection / support     (count: 15, impact: 0.85, trend: increasing)
   "Wrong tool selected for order status lookup"

2. tool_argument / orders       (count: 8, impact: 0.72, trend: stable)
   "Missing customer_id in refund request"

3. handoff_quality / support→orders  (count: 5, impact: 0.65, trend: decreasing)
   "Order context lost during handoff"
```

### Trace graph

Visualize a trace as a span dependency graph:

```bash
autoagent trace graph trace_abc123
```

## CLI commands

```bash
autoagent trace grade <trace_id> [--db PATH]
autoagent trace blame [--window 24h] [--top N] [--db PATH]
autoagent trace graph <trace_id> [--db PATH]
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/traces/blame` | Blame map of failure clusters |
| `GET` | `/api/traces/{id}/grades` | Span-level grades for a trace |
| `GET` | `/api/traces/{id}/graph` | Trace dependency graph |
| `GET` | `/api/traces/{id}` | Raw trace data |
| `GET` | `/api/traces/recent` | Recent traces |
| `GET` | `/api/traces/search` | Search traces |
| `GET` | `/api/traces/errors` | Error traces |

## How it connects to optimization

Blame map clusters feed directly into the optimization loop:

1. **BlameMap** identifies the highest-impact failure cluster
2. The **optimizer** generates a mutation targeting that cluster's grader and agent path
3. The mutation is evaluated, and the blame map is recalculated to verify the fix

This creates a targeted feedback loop: the system finds its worst failure mode, fixes it, and verifies the fix reduced the cluster's count and impact.
