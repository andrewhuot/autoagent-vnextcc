# Context Workbench

Analyze context window usage, simulate compaction strategies, and optimize how your agent uses its token budget.

## Overview

Large context windows are expensive and can degrade quality when filled with irrelevant content. The Context Workbench gives you tools to understand growth patterns, identify waste, and simulate optimization strategies before applying them.

Looking for the agent-building Workbench instead? See [Agent Builder Workbench](workbench.md).

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
- **Handoff scoring** -- Information retention during agent-to-agent transitions (word overlap fidelity metric)

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
- Handoff fidelity (when agent transitions are detected)

## CLI commands

```bash
# Analyze a specific trace
agentlab context analyze --trace trace_abc123

# Simulate compaction strategies
agentlab context simulate --strategy balanced

# Check aggregate report (returns available data or defaults if no traces analyzed)
agentlab context report
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/context/analysis/{id}` | Context analysis for a trace (fully functional) |
| `POST` | `/api/context/simulate` | Simulate compaction strategy (fully functional) |
| `GET` | `/api/context/report` | Aggregate context health (returns defaults when no traces are available) |

## Example workflow

```bash
# 1. Analyze a specific trace
agentlab context analyze --trace trace_abc123
# → Pattern: exponential
# → Peak: 12,400 tokens (82% of window)
# → Handoff fidelity: 0.73
# → Cause: tool output from order lookup not compacted

# 2. Simulate a fix
agentlab context simulate --strategy balanced
# → Estimated savings: 3,200 tokens
# → Quality impact: -0.5%
# → Recommendation: Safe to apply

# 3. Check aggregate health (requires prior per-trace analyses)
agentlab context report
```

> **Note:** The aggregate report endpoint (`/api/context/report`) currently returns default values when no trace analyses have been performed. Run per-trace analysis first to populate the system with data. The per-trace analysis and compaction simulator are fully functional.
