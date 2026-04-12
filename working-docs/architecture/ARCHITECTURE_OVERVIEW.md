# AgentLab VNextCC — Architecture & Implementation Overview

**What it is:** A product-grade platform that continuously evaluates and optimizes AI agents in production. Point it at an ADK agent, and it will run an autonomous loop — trace, diagnose, search for improvements, gate on statistical significance, deploy via canary, repeat — for days or weeks without human intervention.

**What it looks like:** OpenAI Evals meets Vercel's design system. Headless-first (90% CLI/API), with a clean React console for visual insight.

---

## System Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                            Operator Interfaces                                │
│   CLI (agentlab ...)       REST API (/api/*)        Web Console (39 pages)   │
└──────────────────────────────────────┬───────────────────────────────────────┘
                                       │
                         ┌─────────────▼─────────────┐
                         │  FastAPI + TaskManager     │
                         │  200+ endpoints, 39 modules│
                         └─────────────┬─────────────┘
                                       │
     ┌──────────┬──────────┬───────────┼───────────┬──────────┬──────────┐
     │          │          │           │           │          │          │
┌────▼───┐ ┌───▼────┐ ┌───▼─────┐ ┌──▼────┐ ┌────▼───┐ ┌───▼────┐ ┌──▼──────┐
│ Trace  │ │Opport- │ │ Search  │ │Deploy │ │ Replay │ │Context │ │Registry │
│Collect-│ │unity   │ │ Engine  │ │er     │ │Harness │ │Work-   │ │(Skills, │
│or +    │ │Queue   │ │(Multi-  │ │(Can-  │ │        │ │bench   │ │Policies,│
│Grading │ │        │ │ hyp. +  │ │ary)   │ │        │ │(Anal-  │ │Tools,   │
│+ Blame │ │        │ │ Pro-    │ │       │ │        │ │yzer,   │ │Handoff  │
│Map     │ │        │ │ mode)   │ │       │ │        │ │Sim)    │ │Schemas) │
└────┬───┘ └───┬────┘ └───┬─────┘ └──┬────┘ └────┬───┘ └───┬────┘ └──┬──────┘
     │         │           │          │           │         │          │
     │   ┌─────▼──────┐ ┌─▼──────────┐ ┌────▼───┐         │          │
     │   │ Failure    │ │ Mutation   │ │Constr- │         │          │
     │   │ Clustering │ │ Operator   │ │ained  │         │          │
     │   │            │ │ Registry   │ │Gates + │         │          │
     │   └────────────┘ └──────┬─────┘ │Stats   │         │          │
     │                         │       └────────┘         │          │
     │                  ┌──────▼────────┐                  │          │
     │                  │ Experiment    │                  │          │
     │                  │ Cards         │                  │          │
     │                  └──────┬────────┘                  │          │
     │                         │                           │          │
     └─────────────────────────┼───────────────────────────┘──────────┘
                               │
                 ┌─────────────▼─────────────┐
                 │  Eval Data Engine          │
                 │  (trace→eval, 4 set types, │
                 │   7 evaluation modes)       │
                 │  + NL Scorer Generation     │
                 └─────────────┬─────────────┘
                               │
                 ┌─────────────▼─────────────┐
                 │   Persistence Layer        │
                 │  SQLite: traces, evals,    │
                 │  experiments, opportunities,│
                 │  optimizer memory, dead ltrs│
                 │  registry, blame clusters,  │
                 │  judge versions, scorers    │
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

## Package Map

```
agentlab/
├── agent/                  — ADK agent wrapper, graph construction
├── agent_skills/           — Agent-specific skill templates, generators, gap analyzer
├── api/                    — FastAPI app, 39 route modules, 200+ endpoints
├── assistant/              — Assistant builder, file processor, intelligence pipeline
├── adk/                    — Google Agent Development Kit integration (import/export/deploy)
├── cicd/                   — CI/CD gate integration for GitHub Actions
├── cli/                    — Modular CLI commands (skills, registry, etc.)
├── collaboration/          — Team collaboration features
├── context/                — Context Engineering Studio (analyzer, simulator, metrics)
├── control/                — Human escape hatches, governance wrapper
├── core/                   — First-class domain objects, unified skills system
├── cx_studio/              — Google Cloud Contact Center AI bidirectional integration
├── data/                   — Repositories, event log, persistence layer
├── deployer/               — Canary deployment, release manager
├── evals/                  — Data engine, replay harness, scorer, statistics
│   └── nl_scorer.py        — NL Scorer Generation (natural language → ScorerSpec)
├── graders/                — Deterministic, similarity, binary rubric judges
├── judges/                 — Grader stack, calibration, audit judge
├── logger/                 — Structured logging, conversation store, event tracking
├── mcp_server/             — Model Context Protocol server for AI coding tools
├── multi_agent/            — Multi-agent orchestration
├── notifications/          — Notification system and channels
├── observer/               — Trace engine, opportunity queue, knowledge mining
│   ├── blame_map.py        — Blame Map (cluster impact scoring, trend detection)
│   └── trace_grading.py    — Trace Grading (7 span-level graders)
├── optimizer/              — Mutations, search, experiments, cost, reliability
│   ├── prompt_opt/         — Pro-mode (MIPROv2, BootstrapFewShot, GEPA, SIMBA)
│   └── transcript_intelligence.py — Ghostwriter-competitive features (multi-modal ingestion, autonomous loop)
├── registry/               — Modular Registry (skills, policies, tool contracts, handoff schemas)
├── simulator/              — Simulation sandbox, persona generation, stress testing
└── web/                    — React console, 39 pages, TypeScript + Tailwind CSS
```

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

### Trace Grading (`observer/trace_grading.py`)

Seven span-level graders that score individual trace spans for fine-grained diagnosis:

| Grader | What it scores |
|--------|---------------|
| `routing` | Was the correct specialist agent selected? |
| `tool_selection` | Was the right tool chosen for the task? |
| `tool_argument` | Were tool arguments correct and complete? |
| `retrieval_quality` | Did retrieval return relevant, sufficient context? |
| `handoff_quality` | Was context preserved across agent handoffs? |
| `memory_use` | Was memory read/written appropriately? |
| `final_outcome` | Did the span achieve its intended result? |

Each grader returns a span-level score with evidence, enabling pinpoint diagnosis of where an agent went wrong within a trace.

### Blame Map (`observer/blame_map.py`)

Aggregates span-level grades into actionable clusters:
- `BlameCluster`: groups related failures by root cause
- Impact scoring: ranks clusters by frequency × severity × business impact
- Trend detection: identifies worsening failure patterns over time
- Feeds directly into the opportunity queue for targeted optimization

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

### NL Scorer Generation (`evals/nl_scorer.py`)

Converts natural language descriptions into structured scoring specifications:
- Input: plain English description of what "good" looks like
- Output: `ScorerSpec` with named dimensions, rubric criteria, and weight distribution
- Dimensions are auto-extracted from the description and validated for completeness
- Generated scorers integrate directly into the eval pipeline

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

### Pro-mode Prompt Optimization (`optimizer/prompt_opt/`)

Four research-grade prompt optimization algorithms, orchestrated by `ProSearchStrategy`:

| Algorithm | Approach | Best for |
|-----------|----------|----------|
| `MIPROv2` | Multi-instruction proposal optimization with Bayesian surrogate | Instruction tuning with large search spaces |
| `BootstrapFewShot` | Bootstraps successful examples as few-shot demonstrations | Few-shot example selection and curation |
| `GEPA` | Genetic/evolutionary prompt search with population-based selection | Exploring diverse prompt structures |
| `SIMBA` | Simulation-based optimization with model-approximated evaluation | Reducing eval cost via surrogate models |

`ProSearchStrategy` selects the right algorithm based on the failure family and available eval budget, then manages the optimization lifecycle.

### AutoFix Copilot (`optimizer/autofix.py`)

Constrained improvement proposer that generates targeted fix suggestions:
- Analyzes blame map clusters and trace grades to identify fixable issues
- Generates concrete proposals with diffs and expected impact
- Proposals are gated — never auto-applied without eval validation
- History tracking for all suggestions, applied or rejected

### Judge Ops (`judges/`)

Production-grade judge lifecycle management:
- **Versioning**: `GraderVersionStore` tracks every judge configuration change with full lineage
- **Drift monitoring**: `DriftMonitor` detects when judge behavior shifts over time (score distribution changes, agreement rate drops)
- **Human feedback**: `HumanFeedbackStore` captures operator corrections to judge decisions, feeding back into calibration
- **Calibration**: continuous agreement rate, position bias, and verbosity bias tracking

### Context Engineering Studio (`context/`)

Tools for understanding and optimizing what goes into the agent's context window:
- **ContextAnalyzer**: breaks down context composition — instructions, examples, retrieved content, conversation history — with token counts and relevance scores
- **CompactionSimulator**: simulates context compaction strategies and measures information loss
- **ContextMetrics**: tracks context utilization, waste ratio, and relevance distribution over time
- **GrowthPattern detection**: identifies context growth patterns (linear, exponential, sawtooth) and predicts when limits will be hit
- **Handoff scoring**: evaluates context preservation quality across agent handoffs

### Modular Registry (`registry/`)

Centralized, versioned store for all reusable agent components:

| Registry | What it stores |
|----------|---------------|
| `SkillRegistry` | Versioned instruction bundles, script assets, prompt templates |
| `PolicyRegistry` | Safety rules, guardrail configs, authorization policies |
| `ToolContractRegistry` | Tool schemas, replay modes, validators, sandbox policies |
| `HandoffSchemaRegistry` | Structured handoff definitions with goal/constraint/evidence specs |

All registries share a common `RegistryStore` backend with search, diff, import/export, and version history. Components are reusable across agents and environments.

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

React + Vite + TypeScript + Tailwind. Apple/Linear-inspired design. **39 pages total**.

**Core Pages:**
| Page | Purpose |
|------|---------|
| Dashboard | Hero metrics, health pulse, journey timeline, recommendations |
| AgentStudio | Interactive chat interface for agent building in natural language |
| IntelligenceStudio | Transcript archive ingestion, analytics, Q&A, autonomous loop |
| Assistant | Chat-based assistant for agent building |

**Analysis & Diagnostics:**
| Page | Purpose |
|------|---------|
| Traces | ADK event traces and spans with filtering |
| BlameMap | Span-level failure clustering and root cause attribution |
| EventLog | Append-only system event timeline |
| LoopMonitor | Live loop status, cycle-by-cycle progress |
| AutoFix | AI-generated improvement proposals |

**Quality & Evaluation:**
| Page | Purpose |
|------|---------|
| Eval Runs | Sortable table of all evaluations |
| Eval Detail | Per-case results with pass/fail breakdown |
| Experiments | Reviewable experiment cards with hypothesis and diff |
| Sandbox | Synthetic conversation generation and stress testing |
| JudgeOps | Judge versioning, calibration, drift monitoring |

**Skills & Registry:**
| Page | Purpose |
|------|---------|
| Skills | Skill marketplace with search and filtering |
| AgentSkills | Agent-specific skill assignment |
| Registry | Browse/search/import registry components |

**Deployment & Integration:**
| Page | Purpose |
|------|---------|
| Deploy | Canary status, promote/rollback controls |
| CxDeploy | Google Cloud Contact Center AI deployment |
| AdkDeploy | Agent Development Kit deployment |
| CxImport | Import from Dialogflow CX |
| AdkImport | Import from ADK Python source |

**Plus:** Knowledge, Configs, Conversations, ProjectMemory, ContextWorkbench, ScorerStudio, ChangeReview, Runbooks, WhatIf, Reviews, Demo, Notifications, Settings

### REST API

200+ endpoints across 39 route modules.

```
# Core
POST   /api/eval/run              — Start eval (async)
GET    /api/eval/history           — Persisted eval runs
POST   /api/optimize/run           — Trigger optimization cycle
GET    /api/optimize/history        — Attempt history
POST   /api/loop/start             — Start autonomous loop
GET    /api/loop/status             — Loop health
GET    /api/health                  — Agent health metrics
GET    /api/health/system           — Operational health
POST   /api/deploy                  — Deploy config version
GET    /api/conversations           — Browse conversation logs
GET    /api/config/list             — Config version history

# Traces (8 endpoints)
GET    /api/traces/recent           — Recent trace events
GET    /api/traces/{trace_id}       — Full trace with spans
GET    /api/traces/search           — Search events by type/path/time
GET    /api/traces/errors           — Recent error events
GET    /api/traces/blame            — Blame map for a trace
GET    /api/traces/grades           — Span-level grades
GET    /api/traces/graph            — Trace graph visualization data
GET    /api/traces/stats            — Trace statistics

# Opportunities
GET    /api/opportunities           — Ranked opportunity queue
POST   /api/opportunities/{id}/status — Update opportunity status

# Experiments
GET    /api/experiments             — Experiment cards
GET    /api/experiments/{id}        — Single experiment card
GET    /api/experiments/stats       — Experiment counts by status
GET    /api/experiments/archive     — Elite Pareto archive with named roles
GET    /api/experiments/judge-calibration — Judge calibration metrics

# Human Control
GET    /api/control/state           — Human control state
POST   /api/control/pause           — Pause optimization
POST   /api/control/resume          — Resume optimization
POST   /api/control/pin/{s}         — Pin immutable surface
POST   /api/control/unpin/{s}       — Unpin immutable surface
POST   /api/control/reject/{id}     — Reject experiment + rollback canary
POST   /api/control/inject          — Inject manual mutation

# System
GET    /api/events                  — Append-only system event log
GET    /api/health/cost             — Cost tracking and budget posture
GET    /api/health/eval-set         — Eval set health diagnostics
GET    /api/health/scorecard        — 2-gate + 4-metric scorecard

# AutoFix (4 endpoints)
POST   /api/autofix/suggest         — Generate fix suggestions from blame clusters
GET    /api/autofix/proposals        — List pending fix proposals
POST   /api/autofix/apply           — Apply a fix proposal (triggers eval)
GET    /api/autofix/history          — History of all suggestions and outcomes

# Judges (4 endpoints)
GET    /api/judges/list              — List judge configurations and versions
POST   /api/judges/feedback          — Submit human feedback on judge decisions
GET    /api/judges/calibration       — Judge calibration metrics and bias stats
GET    /api/judges/drift             — Judge drift detection results

# Context (3 endpoints)
POST   /api/context/analysis         — Analyze context composition and utilization
POST   /api/context/simulate         — Simulate compaction strategy
GET    /api/context/report           — Context health report with growth patterns

# Registry (6 endpoints)
GET    /api/registry/search          — Search across all registry types
POST   /api/registry/import          — Import registry components
GET    /api/registry/list            — List components by type
GET    /api/registry/diff            — Diff two component versions
GET    /api/registry/{type}/{id}     — Get specific component
POST   /api/registry/create          — Create new registry component

# Scorers (5 endpoints)
POST   /api/scorers/create           — Create scorer from natural language
GET    /api/scorers/list             — List all generated scorers
GET    /api/scorers/{id}             — Get scorer spec and dimensions
POST   /api/scorers/refine           — Refine scorer based on feedback
POST   /api/scorers/test             — Test scorer against sample data
```

---

## Configuration

Everything is driven by `agentlab.yaml`:

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
  checkpoint_path: .agentlab/loop_checkpoint.json
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

# New (Three-Way Merge)
budget:
  per_cycle_dollars: 1.0
  daily_dollars: 10.0
  stall_threshold_cycles: 5
  tracker_db_path: .agentlab/cost_tracker.db

human_control:
  immutable_surfaces: ["safety_instructions"]
  state_path: .agentlab/human_control.json
```

---

## By the Numbers

| Metric | Value |
|--------|-------|
| Python backend | ~46,600 lines |
| React frontend | ~8,800 lines |
| Test suite | 1,131 tests passing |
| Core domain objects | 10 (AgentGraphVersion, SkillVersion, ToolContractVersion, PolicyPackVersion, EnvironmentSnapshot, GraderBundle, EvalCase, CandidateVariant, ArchiveEntry, HandoffArtifact) |
| Judge subsystem | 9 modules (deterministic, rule_based, llm_judge, audit_judge, calibration, grader_stack + binary_rubric, similarity, deterministic_grader) |
| Python packages | 14 (agent, api, context, control, core, data, deployer, evals, graders, judges, observer, optimizer, optimizer/prompt_opt, registry) |
| Reusable React components | 29 |
| Frontend pages | 19 |
| API endpoints | 75 |
| Route modules | 18 |
| Test files | 59 |

---

## v4 Research Port

The v4 port brings research-grade optimization techniques into the production loop. All features are additive and backward-compatible -- existing configs and workflows continue to work unchanged.

### 9-Dimension Evaluation (G1-G9)

Replaces the 4-metric composite score with a 9-dimension scoring vector:

| Dimension | ID | Description |
|-----------|----|-------------|
| Task Success Rate | G1 | End-to-end task completion |
| Response Quality | G2 | LLM-judged response quality |
| Safety Compliance | G3 | Policy and safety adherence |
| Latency (p50/p95/p99) | G4a-c | Latency percentiles |
| Token Cost | G5 | Normalized token expenditure |
| Tool Correctness | G6 | Correct tool selection and usage |
| Routing Accuracy | G7 | Correct specialist routing |
| Handoff Fidelity | G8 | Context preservation across handoffs |
| User Satisfaction Proxy | G9 | Composite user satisfaction estimate |

Per-agent scores decompose the system-level metrics to individual agent paths for targeted diagnosis.

### Constrained Pareto Archive

Instead of collapsing all objectives into a single weighted score, the Pareto archive maintains a set of non-dominated configurations across the full objective vector. A candidate is on the frontier if no other candidate is better on every objective simultaneously.

- **Feasibility gating**: hard constraints (safety, P0 regression) must pass before a candidate enters the archive
- **Recommended selection**: the archive recommends the candidate closest to a reference point (balanced across all objectives)
- **Experiment linkage**: each candidate tracks its source experiment for full provenance

### Hybrid Search Orchestrator

Three search strategies, selectable via `optimizer.search_strategy`:

| Strategy | Behavior | When to use |
|----------|----------|-------------|
| `simple` (default) | Single best mutation per cycle, greedy selection | Early optimization, small eval budgets |
| `adaptive` | Bandit-guided operator selection, automatic exploration/exploitation balance | Steady-state optimization |
| `full` | Multi-hypothesis search + curriculum learning + holdout rotation | Research-grade optimization with large eval budgets |

### Bandit Selection (UCB1 / Thompson Sampling)

Mutation operators are modeled as bandit arms, with reward defined as the improvement delta when applied to a failure family. The bandit policy (`optimizer.bandit_policy`) selects which operator to try next:

- **UCB1**: Upper Confidence Bound -- balances mean reward with exploration bonus
- **Thompson Sampling**: Bayesian posterior sampling -- naturally adapts exploration to uncertainty

### Curriculum Learning

When `optimizer.curriculum_enabled` is true, eval cases are tiered into easy/medium/hard. The optimizer starts with easy cases and advances only after demonstrating competence at each tier. This prevents wasting eval budget on hard cases before basic issues are resolved.

### Anti-Goodhart Mechanisms

Three mechanisms prevent the optimizer from overfitting to the eval set:

1. **Holdout Rotation** (`optimizer.holdout_rotation`): The eval set is split into tuning/validation/holdout partitions. The holdout set is never used for optimization decisions -- only for final validation. Partitions rotate periodically to prevent memorization.

2. **Drift Detection** (`optimizer.drift_detection_window`, `optimizer.drift_threshold`): Monitors the gap between tuning and validation scores. If the gap exceeds the threshold over a sliding window, the system flags potential overfitting and can trigger holdout rotation.

3. **Judge Variance Estimation**: LLM judges are noisy. The statistical layer estimates judge variance and accounts for it in significance testing, preventing acceptance of changes that only appear better due to judge noise.

### Configuration

All v4 features are controlled by the `optimizer` section of `AgentConfig`:

```yaml
optimizer:
  search_strategy: simple       # simple | adaptive | full
  bandit_policy: ucb1           # ucb1 | thompson
  holdout_rotation: false
  holdout_tuning_fraction: 0.6
  holdout_validation_fraction: 0.2
  holdout_holdout_fraction: 0.2
  holdout_rotation_interval: 10
  drift_detection_window: 5
  drift_threshold: 0.03
  curriculum_enabled: false
  curriculum_min_experiments_per_tier: 3
  curriculum_stall_threshold: 0.01
```

All fields have sensible defaults. The `simple` strategy with defaults is equivalent to v3 behavior.

---

## Researcher-Advised Refactor (v5)

The v5 refactor transforms AgentLab from a prompt optimizer into **CI/CD for agents**, based on AI researcher feedback. The moat: "we can faithfully replay, grade, and safely improve real enterprise agent workflows."

### New First-Class Domain Objects (`core/`)

| Object | Purpose |
|--------|---------|
| `AgentGraphVersion` | Framework-neutral IR for agent systems (typed nodes + edges) |
| `SkillVersion` | Versioned instruction/script/asset bundles |
| `ToolContractVersion` | Tool schema + replay mode + validator + sandbox policy |
| `PolicyPackVersion` | Safety rules, guardrail thresholds, authorization policies |
| `EnvironmentSnapshot` | Captured external system state for end-state evaluation |
| `GraderBundle` | Ordered grader stack per eval case |
| `EvalCase` | Enriched eval case with end-state + grader bundle + diagnostics |
| `CandidateVariant` | Versioned diff against an AgentGraphVersion |
| `ArchiveEntry` | Pareto archive entry with named role |
| `HandoffArtifact` | Structured handoff with goal, constraints, evidence refs |

### 4-Layer Metric Hierarchy (replaces flat 9-dimension)

| Layer | Metrics | Role |
|-------|---------|------|
| **Hard Gates** | safety_compliance, authorization_privacy, state_integrity, p0_regressions | Must pass — binary |
| **North-Star Outcomes** | task_success_rate, groundedness, user_satisfaction_proxy | Optimized |
| **Operating SLOs** | latency (p50/p95/p99), token_cost, escalation_rate | Constrained |
| **Diagnostics** | tool_correctness, routing_accuracy, handoff_fidelity, recovery_rate, clarification_quality, judge_disagreement_rate | Diagnosis only |

The optimizer searches Layer 2 (outcomes) within Layer 1 (gates), subject to Layer 3 (SLOs). Layer 4 is never optimized directly.

### Judge Subsystem (`judges/`)

Replaces the utility-function LLM judge with a full grader stack:

1. **Deterministic** — regex, state checks, business invariants (confidence=1.0)
2. **Rule-based** — format, length, required fields (confidence=1.0)
3. **LLM Judge** — frozen primary judge with evidence spans
4. **Audit Judge** — cross-family judge for promotions (different model family than proposer)
5. **Calibration Suite** — agreement rate, drift, position bias, verbosity bias, disagreement rate

Every judge returns `JudgeVerdict` with score, passed, evidence_spans, failure_reasons, confidence.

### Eval Compiler Enhancements (`evals/data_engine.py`)

- PII scrubbing before storage
- Near-duplicate detection and dedup
- Business impact scoring
- Root-cause tagging (auto-categorize failure type)
- Negative control generation
- Five eval suite types: contract_regression, capability, adversarial, discovery, judge_calibration

### 5-Mode Replay Matrix (replaces 4-class side effects)

| Mode | Behavior |
|------|----------|
| `deterministic_stub` | Cached response (pure tools) |
| `recorded_stub_with_freshness` | Cached if fresh, else live |
| `live_sandbox_clone` | Always live in sandbox |
| `simulator` | Cached with simulation flag |
| `forbidden` | Skip, return error marker |

Plus `EnvironmentSnapshot` capture/restore for end-state evaluation.

### Elite Pareto Archive with Named Roles

| Role | Selection Criterion |
|------|-------------------|
| `quality_leader` | Best on task success |
| `cost_leader` | Lowest token cost |
| `latency_leader` | Lowest latency |
| `safety_leader` | Best safety score |
| `cluster_specialist` | Non-dominated on a sub-population |
| `incumbent` | Currently deployed |

New candidates can branch from any archive entry, not just incumbent.

### Training Escalation (`optimizer/training_escalation.py`)

When a failure family is stable and high-volume with low prompt-fix rate, recommends SFT/DPO/RFT instead of endless prompt patching.

### Release Manager (`deployer/release_manager.py`)

Full promotion pipeline: hard gates → hidden holdout → slice checks → canary → rollback-ready release. Each stage produces an auditable `PromotionRecord`.

---

## Final Three-Way Merge (v6 — Simplicity Thesis)

The v6 merge folds production-critical features from Codex R2 (simplicity thesis) and structural improvements from Codex R1 (repository pattern, governance) into the CC Opus backbone. Guiding principle: **iteration speed over sophistication** — the Karpathy loop as default, 4+2 scoring, binary rubric judges, human escape hatches, cost controls.

### Production Cost Controls (`optimizer/cost_tracker.py`)

- SQLite-backed per-cycle and daily budget tracking
- Diminishing returns (stall) detection — pauses loop when N consecutive cycles show no improvement
- Cost-per-improvement ROI metrics
- API endpoint: `GET /api/health/cost`

### Human Escape Hatches (`optimizer/human_control.py`, `api/routes/control.py`)

| Action | CLI | API | Dashboard |
|--------|-----|-----|-----------|
| Pause/resume optimization | `agentlab pause/resume` | `POST /api/control/pause` | Button |
| Pin immutable surface | `agentlab pin <surface>` | `POST /api/control/pin/{surface}` | Input + tags |
| Reject experiment + rollback | `agentlab reject <id>` | `POST /api/control/reject/{id}` | Input + button |
| Inject manual mutation | — | `POST /api/control/inject` | — |

### Append-Only Event Log (`data/event_log.py`, `api/routes/events.py`)

14 event types: `eval_started`, `eval_completed`, `candidate_proposed`, `candidate_promoted`, `candidate_rejected`, `rollback_triggered`, `budget_exceeded`, `stall_detected`, `human_pause`, `human_resume`, `human_reject`, `human_inject`, `loop_started`, `loop_stopped`.

- SQLite append-only storage
- API: `GET /api/events` with type filtering
- Dashboard: Event Timeline + dedicated Event Log page

### Binary Rubric Judges (`graders/llm_judge.py`)

4 yes/no rubric questions for routine evaluation (fast, cheap). Full evidence-span judges reserved for promotion only.
- Heuristic fallback mode for no-LLM operation
- Model-family conflict detection (judge must differ from proposer)
- Optional 3x majority voting

### Tiered Grading Pipeline (`graders/`)

1. `DeterministicGrader` — strict assertion checks (contains, tool_called, status_code)
2. `SimilarityGrader` — token-overlap Jaccard similarity
3. `BinaryRubricJudge` — LLM yes/no rubric (see above)

### Protocol-Based Repositories (`data/repositories.py`)

- `TraceRepository` and `ArtifactRepository` — Python Protocol interfaces
- `SQLiteTraceRepository` and `SQLiteArtifactRepository` — concrete implementations
- Postgres-ready: swap implementation without changing consumers

### Governance Wrapper (`control/governance.py`)

Thin delegation to `ReleaseManager.run_full_pipeline()` for promotion decisions.

### Eval Enhancements

- **Coherence Detection** (`evals/data_engine.py`): scans trace events for repeated questions, self-contradictions, "I already told you" patterns
- **Difficulty Scoring**: categorizes eval cases as saturated (<5% fail), unsolvable (>95% fail), or high-leverage (30-70% fail)
- **Pipeline Eval Mode**: end-to-end multi-agent evaluation via `eval_mode="pipeline"`
- **Graph Validation**: duplicate node detection, dangling edge detection

### Simplicity-First Dashboard (`web/src/pages/Dashboard.tsx`)

Replaced the 9-dimension dashboard with R2's simplicity-first design:
- 2 hard gates (safety + regression) + 4 primary metrics (task success, quality, latency p95, cost/conversation)
- Collapsible "Why? Diagnostic Signals" section
- Score trajectory chart
- Cost controls panel with spend tracking
- Human escape hatches panel (pause/resume, pin surface, reject experiment)
- Event Timeline with link to full Event Log page

### Statistical Refinements

- Power-based sample adequacy (replaces n>=30 rule)
- Safety severity tiers (P0-P3) with one-sided upper bounds
- Full promotion criteria chain: zero P0 on red-team → P1 upper bound below threshold → no slice regressions → holdout winner → canary survives

---

## What Makes This Different

1. **It actually works.** Not a prototype — the trace→diagnose→search→eval→deploy loop runs end-to-end with real scoring, real gating, real deployment.

2. **It doesn't crash.** Graceful shutdown, checkpoint/resume, dead letter queues, watchdog monitoring. Built for multi-day unattended operation.

3. **It doesn't deploy noise.** Clustered bootstrap, sequential testing, and multiple-hypothesis correction prevent accepting improvements that aren't real.

4. **It learns.** The search engine tracks which mutation operators work for which failure families and gets smarter over time. Pro-mode algorithms (MIPROv2, BootstrapFewShot, GEPA, SIMBA) bring research-grade optimization when you need it.

5. **It's reviewable.** Every optimization attempt produces an experiment card with hypothesis, diff, scores, and significance — not just "config v17."

6. **It's model-agnostic.** Gemini by default, but swap to Claude, GPT, or a local model with one config change. Or run all of them in ensemble mode.

7. **It looks like a product.** Not a research notebook. Clean CLI, 75 API endpoints across 18 route modules, polished web console with 19 pages — from dashboard to blame maps to scorer studio.

8. **It diagnoses precisely.** Seven span-level trace graders pinpoint exactly where an agent went wrong. Blame maps aggregate failures into actionable clusters with impact scores and trend detection.

9. **It manages the full lifecycle.** Registry for reusable components, judge versioning with drift detection, Context Engineering Studio, NL scorer generation — not just optimization, but the entire agent operations workflow.

---

*Repository: https://github.com/andrewhuot/autoagent-vnextcc*
