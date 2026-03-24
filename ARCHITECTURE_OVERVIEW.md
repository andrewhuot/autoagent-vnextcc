# AutoAgent VNextCC — Architecture & Implementation Overview

**What it is:** A product-grade platform that continuously evaluates and optimizes AI agents in production. Point it at an ADK agent, and it will run an autonomous loop — trace, diagnose, search for improvements, gate on statistical significance, deploy via canary, repeat — for days or weeks without human intervention.

**What it looks like:** OpenAI Evals meets Vercel's design system. Headless-first (90% CLI/API), with a clean React console for visual insight.

---

## System Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         Operator Interfaces                          │
│   CLI (autoagent ...)      REST API (/api/*)      Web Console        │
└─────────────────────────────────┬────────────────────────────────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │  FastAPI + TaskManager     │
                    └─────────────┬─────────────┘
                                  │
     ┌────────────┬───────────────┼───────────────┬────────────┐
     │            │               │               │            │
┌────▼─────┐ ┌───▼────┐   ┌──────▼──────┐  ┌─────▼─────┐ ┌───▼────┐
│  Trace   │ │Opport- │   │  Search     │  │  Deploy   │ │ Replay │
│Collector │ │unity   │   │  Engine     │  │  er       │ │Harness │
│(Events)  │ │Queue   │   │(Multi-hyp.) │  │(Canary)   │ │        │
└────┬─────┘ └───┬────┘   └──────┬──────┘  └─────┬─────┘ └───┬────┘
     │           │               │                │            │
     │     ┌─────▼──────┐  ┌────▼──────────┐ ┌───▼──────┐     │
     │     │ Failure    │  │ Mutation      │ │Constrained│    │
     │     │ Clustering │  │ Operator      │ │Gates +    │    │
     │     │            │  │ Registry      │ │Stats Layer│    │
     │     └────────────┘  └──────┬────────┘ └──────────┘     │
     │                            │                            │
     │                    ┌───────▼────────┐                   │
     │                    │ Experiment     │                   │
     │                    │ Cards          │                   │
     │                    └───────┬────────┘                   │
     │                            │                            │
     └────────────────────────────┼────────────────────────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │  Eval Data Engine          │
                    │  (trace→eval, 4 set types, │
                    │   7 evaluation modes)       │
                    └─────────────┬─────────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │   Persistence Layer        │
                    │  SQLite: traces, evals,    │
                    │  experiments, opportunities,│
                    │  optimizer memory, dead ltrs│
                    │  YAML: configs, versions   │
                    │  JSON: checkpoints, logs   │
                    └───────────────────────────┘
```

---

## The Core Loop (v2)

```
1. TRACE     → Collect structured events from agent invocations
2. DIAGNOSE  → Anomaly detection, failure clustering, trace analysis
3. QUEUE     → Rank optimization opportunities by severity/prevalence/impact
4. SEARCH    → Multi-hypothesis: generate diverse mutations, rank by lift/risk/novelty
5. REPLAY    → Shadow evaluation with tool I/O replay for safe candidates
6. GATE      → Hard constraints (safety, P0 regression) → Objectives (quality, cost, latency)
7. STATS     → Clustered bootstrap, sequential testing, multiple-hypothesis correction
8. DEPLOY    → Canary deployment with experiment card tracking
9. LEARN     → Record which operators work for which failure families
10. REPEAT
```

Each cycle is wrapped in exception handling. Failures go to a dead letter queue — the loop never crashes.

---

## Key Subsystems

### Typed Mutation Registry (`optimizer/mutations.py`)

Operators are first-class objects with typed surfaces, risk classes, and validators:

| Operator | Surface | Risk | Auto-deploy |
|----------|---------|------|-------------|
| `instruction_rewrite` | instruction | low | yes |
| `few_shot_edit` | few_shot | low | yes |
| `tool_description_edit` | tool_description | medium | yes |
| `model_swap` | model | high | no |
| `generation_settings` | generation_settings | low | yes |
| `callback_patch` | callback | high | no |
| `context_caching` | context_caching | medium | yes |
| `memory_policy` | memory_policy | medium | yes |
| `routing_edit` | routing | medium | yes |

Plus Google Prompt Optimizer stubs (zero-shot, few-shot, data-driven) and experimental topology operators.

### Experiment Cards (`optimizer/experiments.py`)

Every optimization attempt produces a reviewable experiment card:
- `hypothesis`, `touched_surfaces`, `diff_summary`
- `baseline_sha` / `candidate_sha` for reproducibility
- `risk_class`, `deployment_policy`, `rollback_handle`
- `significance_p_value`, `significance_delta`
- SQLite-backed with status lifecycle: pending → running → accepted/rejected

### Trace Engine (`observer/traces.py`)

Structured event collection replacing shallow conversation-level metrics:
- `TraceEvent`: tool calls, responses, state deltas, errors, agent transfers, model calls
- `TraceSpan`: hierarchical span tree for latency analysis
- `TraceCollector`: high-level recording API
- `TraceStore`: SQLite with indexes on trace_id, session_id, agent_path

### Ranked Opportunity Queue (`observer/opportunities.py`)

Replaces `needs_optimization: bool` with a priority-scored queue:
- `OptimizationOpportunity`: cluster_id, failure_family, severity, prevalence, recency, business_impact
- `priority_score = 0.3*severity + 0.3*prevalence + 0.2*recency + 0.2*business_impact`
- `FailureClusterer`: maps failure buckets → opportunities with recommended operators
- Three queues: drift, new failures, cost/latency optimization

### Eval Data Engine (`evals/data_engine.py`)

Trace-to-eval pipeline with 4 eval set types and 7 evaluation modes:
- **Set types**: golden, rolling_holdout, challenge/adversarial, live_failure_queue
- **Modes**: target_response, target_tool_trajectory, rubric_quality, rubric_tool_use, hallucination, safety, user_simulation
- `TraceToEvalConverter`: bad production traces → eval cases automatically

### Replay Harness (`evals/replay.py`)

Safe evaluation with side-effect classification:
- Tools classified as: `pure`, `read_only_external`, `write_external_reversible`, `write_external_irreversible`
- Only `pure` and `read_only_external` eligible for automatic replay
- Baseline tool I/O recorded and stubbed on replay

### Constrained Scoring (`evals/scorer.py`)

Separates hard constraints from optimization objectives:
- **Constraints** (binary gate): zero safety failures, no P0 regression
- **Objectives** (continuous): quality (55%), latency (25%), cost (20%)
- Three modes: `weighted` (backwards compat), `constrained`, `lexicographic`

### Statistical Layer (`evals/statistics.py`)

Beyond paired bootstrap:
- Clustered bootstrap by conversation/user
- Sequential testing (O'Brien-Fleming alpha spending)
- Multiple-hypothesis correction (Holm-Bonferroni)
- Minimum sample-size requirements
- Judge-variance estimation
- Effect size, confidence interval, power estimate stored per run

### Multi-Hypothesis Search Engine (`optimizer/search.py`)

Replaces single-proposal-per-cycle with budget-aware search:
1. Cluster failures from opportunity queue
2. Generate diverse candidate mutations from registry
3. Rank by predicted lift / risk / novelty
4. Evaluate top K under fixed budget
5. Learn which operators work for which failure families
6. Memory of failed ideas prevents re-running bad changes

### Multi-Model Provider Router (`optimizer/providers.py`)

| Provider | Models | Auth |
|----------|--------|------|
| **Google** (default) | Gemini 2.5 Pro, Flash | `GOOGLE_API_KEY` |
| **OpenAI** | GPT-4o, GPT-5, o3 | `OPENAI_API_KEY` |
| **Anthropic** | Claude Sonnet, Opus | `ANTHROPIC_API_KEY` |
| **OpenAI-compatible** | Any local model | Custom `base_url` |
| **Mock** | Deterministic test proposer | No key needed |

### Long-Running Reliability (`optimizer/reliability.py`)

| Feature | Implementation |
|---------|---------------|
| **Graceful shutdown** | SIGTERM/SIGINT handlers; finishes current cycle before exiting |
| **Checkpoint/resume** | JSON checkpoint after every cycle; `--resume` flag |
| **Dead letter queue** | SQLite-backed; failed cycles are logged, not lost |
| **Watchdog** | Heartbeat-based stall detection |
| **Resource monitoring** | Memory/CPU sampling per cycle |
| **Structured logging** | JSON log with rotation (5MB × 5 backups) |
| **Scheduling** | Continuous, interval, or cron (5-field UTC) |

### Web Console (`web/src/`)

React + Vite + TypeScript + Tailwind. Apple/Linear-inspired design.

| Page | Purpose |
|------|---------|
| Dashboard | Hero metrics + recent eval runs |
| Eval Runs | Sortable table of all evaluations |
| Eval Detail | Per-case results with pass/fail breakdown |
| Optimize | Trigger optimization, view attempt history |
| Configs | Version list, YAML diff viewer |
| Conversations | Browse logged agent conversations |
| Deploy | Canary status, promote/rollback controls |
| Loop Monitor | Live loop status, cycle history, watchdog/DLQ health |
| **Opportunities** | Ranked optimization opportunity queue |
| **Experiments** | Reviewable experiment cards with hypothesis and diff |
| **Traces** | ADK event traces and spans for diagnosis |
| Settings | Runtime configuration |

### REST API

```
# Existing
POST   /api/eval/run          — Start eval (async)
GET    /api/eval/history       — Persisted eval runs
POST   /api/optimize/run       — Trigger optimization cycle
GET    /api/optimize/history    — Attempt history
POST   /api/loop/start         — Start autonomous loop
GET    /api/loop/status         — Loop health
GET    /api/health              — Agent health metrics
GET    /api/health/system       — Operational health
POST   /api/deploy              — Deploy config version
GET    /api/conversations       — Browse conversation logs
GET    /api/config/list         — Config version history

# New (P0 overhaul)
GET    /api/traces/recent       — Recent trace events
GET    /api/traces/{trace_id}   — Full trace with spans
GET    /api/traces/search       — Search events by type/path/time
GET    /api/traces/errors       — Recent error events
GET    /api/opportunities       — Ranked opportunity queue
POST   /api/opportunities/{id}/status — Update opportunity status
GET    /api/experiments         — Experiment cards
GET    /api/experiments/{id}    — Single experiment card
GET    /api/experiments/stats   — Experiment counts by status
```

---

## Configuration

Everything is driven by `autoagent.yaml`:

```yaml
optimizer:
  use_mock: true
  strategy: single
  models:
    - provider: google
      model: gemini-2.5-pro
      api_key_env: GOOGLE_API_KEY

loop:
  schedule_mode: continuous
  checkpoint_path: .autoagent/loop_checkpoint.json
  watchdog_timeout_seconds: 300

eval:
  significance_alpha: 0.05
  significance_min_effect_size: 0.005

# New (P0 overhaul) — all have defaults, old configs keep working
search:
  max_candidates: 10
  max_eval_budget: 5
  scoring_mode: constrained  # weighted | constrained | lexicographic

context_caching:
  enabled: false
  threshold_tokens: 1000
  ttl_seconds: 300

memory_policy:
  preload: true
  write_back: true
  max_entries: 100
```

---

## By the Numbers

| Metric | Value |
|--------|-------|
| Python backend | ~14,000 lines |
| React frontend | ~6,000 lines |
| Test suite | 157 tests passing |
| New Python modules | 12 (mutations, experiments, search, traces, opportunities, data_engine, replay, side_effects, mutations_google, mutations_topology, scoring_v2, statistics_v2) |
| Refactored modules | 5 (gates, scorer, statistics, schema, server) |
| Reusable React components | 24 |
| Frontend pages | 12 |
| API endpoints | 28 |
| New test files | 9 |

---

## What Makes This Different

1. **It actually works.** Not a prototype — the trace→diagnose→search→eval→deploy loop runs end-to-end with real scoring, real gating, real deployment.

2. **It doesn't crash.** Graceful shutdown, checkpoint/resume, dead letter queues, watchdog monitoring. Built for multi-day unattended operation.

3. **It doesn't deploy noise.** Clustered bootstrap, sequential testing, and multiple-hypothesis correction prevent accepting improvements that aren't real.

4. **It learns.** The search engine tracks which mutation operators work for which failure families and gets smarter over time.

5. **It's reviewable.** Every optimization attempt produces an experiment card with hypothesis, diff, scores, and significance — not just "config v17."

6. **It's model-agnostic.** Gemini by default, but swap to Claude, GPT, or a local model with one config change. Or run all of them in ensemble mode.

7. **It looks like a product.** Not a research notebook. Clean CLI, comprehensive API, polished web console with 12 pages.

---

*Repository: https://github.com/andrewhuot/autoagent-vnextcc*
