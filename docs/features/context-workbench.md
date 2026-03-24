# Context Workbench

Analyze context window usage, simulate compaction strategies, and optimize how your agent uses its token budget.

## Overview

Large context windows are expensive and can degrade quality when filled with irrelevant content. The Context Workbench gives you tools to understand growth patterns, identify waste, and simulate optimization strategies before applying them.

## ContextAnalyzer

The `ContextAnalyzer` processes trace data and classifies context growth into four patterns:

| Pattern | Description |
|---------|-------------|
| **linear** | Context grows proportionally with conversation turns. Normal for simple conversations. |
| **exponential** | Context grows faster than turn count. Usually indicates unbounded tool output or memory accumulation. |
| **sawtooth** | Context grows then drops repeatedly. Indicates compaction is already active but may be suboptimal. |
| **stable** | Context stays roughly constant. Ideal -- compaction is working well. |

The analyzer also computes:

- **Utilization** -- Percentage of context window actually used
- **Failure correlations** -- Whether context size correlates with failure rates
- **Handoff scoring** -- How efficiently context is transferred between agents during handoffs

## CompactionSimulator

The `CompactionSimulator` lets you test compaction strategies without modifying your agent:

| Strategy | Behavior |
|----------|----------|
| **aggressive** | Remove all non-essential context. Maximizes token savings, may lose some useful context. |
| **balanced** | Remove low-value context while preserving key information. Best general-purpose choice. |
| **conservative** | Only remove clearly redundant content. Minimal risk, smaller savings. |

Each simulation returns estimated token savings and quality impact.

## ContextMetrics

The `ContextMetrics` data class captures per-trace measurements:

- Token count at each turn
- Growth rate
- Peak utilization
- Compaction events
- Handoff efficiency

## CLI commands

```bash
# Analyze a specific trace
autoagent context analyze --trace trace_abc123

# Simulate compaction strategies
autoagent context simulate --strategy balanced

# Generate a full context health report
autoagent context report
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/context/analysis/{id}` | Context analysis for a trace |
| `POST` | `/api/context/simulate` | Simulate compaction strategy |
| `GET` | `/api/context/report` | Context health report |

## Example workflow

```bash
# 1. Get a high-level report
autoagent context report
# → Growth pattern: exponential (3 agents)
# → Average utilization: 78%
# → Failure correlation: moderate (r=0.42)

# 2. Drill into a problematic trace
autoagent context analyze --trace trace_abc123
# → Pattern: exponential
# → Peak: 12,400 tokens (82% of window)
# → Cause: tool output from order lookup not compacted

# 3. Simulate a fix
autoagent context simulate --strategy balanced
# → Estimated savings: 3,200 tokens
# → Quality impact: -0.5%
# → Recommendation: Safe to apply
```
