# Architecture and process diagrams

Visual guide to how AutoAgent is structured and how data flows through the system.

---

## System architecture

Three interfaces sit on top of a FastAPI backend that orchestrates all subsystems. Everything persists to SQLite and YAML.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          User interfaces                                │
│                                                                         │
│   CLI                        API                   Web console          │
│   autoagent <cmd>            200+ REST endpoints   39 pages (React)     │
│                              WebSocket + SSE       TypeScript/Tailwind  │
└───────────────┬──────────────────┬──────────────────────┬───────────────┘
                │                  │                      │
                └──────────────────┼──────────────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │                             │
                    │   FastAPI application        │
                    │   api/server.py              │
                    │   39 route modules           │
                    │                             │
                    └──────────────┬──────────────┘
                                   │
        ┌──────────┬───────────┬───┴───┬───────────┬──────────┐
        │          │           │       │           │          │
   ┌────▼────┐ ┌───▼───┐ ┌────▼───┐ ┌─▼──────┐ ┌──▼───┐ ┌───▼────┐
   │Observer │ │Search │ │ Eval   │ │Deploy- │ │Judge │ │Regis- │
   │         │ │Engine │ │ Runner │ │er      │ │Stack │ │try    │
   │ Traces  │ │       │ │        │ │        │ │      │ │       │
   │ Grading │ │Mutat- │ │ Data   │ │ Canary │ │Tier- │ │Skills │
   │ Blame   │ │ions   │ │ Engine │ │ Roll-  │ │ed    │ │Polic- │
   │ Map     │ │Search │ │ Replay │ │ out    │ │Scor- │ │ies    │
   │ Opport- │ │Strat- │ │ Stats  │ │ Cards  │ │ing   │ │Tools  │
   │ unities │ │egies  │ │        │ │        │ │      │ │Hand-  │
   └────┬────┘ └───┬───┘ └────┬───┘ └─┬──────┘ └──┬───┘ │offs   │
        │          │          │       │           │     └───┬────┘
        │          │          │       │           │         │
        └──────────┴──────────┴───┬───┴───────────┴─────────┘
                                  │
                    ┌─────────────▼──────────────┐
                    │                            │
                    │   LLM Router               │
                    │   round_robin / ensemble   │
                    │                            │
                    ├────────┬──────────┬────────┤
                    │ Google │  OpenAI  │Anthro- │
                    │ Gemini │  GPT-4o  │pic     │
                    │        │          │Claude  │
                    └────────┴──────────┴────────┘
                                  │
                    ┌─────────────▼──────────────┐
                    │                            │
                    │   Persistence layer        │
                    │                            │
                    │   SQLite databases:        │
                    │    conversations.db        │
                    │    optimizer_memory.db     │
                    │    eval_history.db         │
                    │    registry.db             │
                    │    traces.db               │
                    │                            │
                    │   YAML: configs/*          │
                    │   JSON: checkpoints, logs  │
                    └────────────────────────────┘
```

---

## The optimization loop

This is the core process. Each numbered step shows what happens, what data flows in, and what comes out.

```
    ┌─────────────────────────────────────────────────────────┐
    │                                                         │
    │                   OPTIMIZATION LOOP                     │
    │                                                         │
    │   Runs autonomously. Interruptible at every step.       │
    │   Budget-capped. Checkpoint after every cycle.          │
    │                                                         │
    └─────────────────────────────────────────────────────────┘

         ┌──────────┐
         │ 1. TRACE │
         └────┬─────┘
              │  Collect structured telemetry from agent invocations.
              │  Every tool call, agent transfer, and model call recorded
              │  as hierarchical spans.
              │
              │  IN:  Live agent traffic or replayed conversations
              │  OUT: Trace spans in traces.db
              ▼
         ┌──────────────┐
         │ 2. DIAGNOSE  │
         └────┬─────────┘
              │  Grade each span with 7 graders. Cluster failures
              │  into blame maps. Rank optimization opportunities
              │  by severity, prevalence, and business impact.
              │
              │  IN:  Trace spans
              │  OUT: Blame clusters, ranked opportunity queue
              ▼
         ┌──────────┐
         │ 3. SEARCH │
         └────┬─────┘
              │  Pull top opportunity from queue. Generate candidate
              │  mutations using the configured search strategy.
              │  Each candidate targets a specific config surface.
              │
              │  IN:  Opportunity queue, current config, optimizer memory
              │  OUT: Ranked list of candidate mutations
              ▼
         ┌────────┐
         │ 4. EVAL │
         └────┬───┘
              │  Replay each candidate against the eval suite.
              │  Side effects isolated — only pure and read-only
              │  tools run live. Tool I/O stubbed from baseline.
              │  Score with the tiered judge stack.
              │
              │  IN:  Candidate configs, eval dataset
              │  OUT: Scores per candidate, per eval case
              ▼
         ┌────────┐
         │ 5. GATE │
         └────┬───┘
              │  Check the 4-layer metric hierarchy:
              │
              │  Hard gates    →  FAIL = reject immediately
              │  North-star    →  Must improve over baseline
              │  SLOs          →  Must stay within bounds
              │  Diagnostics   →  Observed, not gated
              │
              │  Statistical significance required:
              │  bootstrap CI, permutation test, p < alpha.
              │
              │  IN:  Candidate scores, baseline scores
              │  OUT: Accept or reject decision
              ▼
         ┌──────────┐
         │ 6. DEPLOY │
         └────┬─────┘
              │  Promote accepted mutation via canary rollout.
              │  Create experiment card with full audit trail:
              │  hypothesis, diff, scores, significance, rollback plan.
              │
              │  IN:  Accepted candidate config
              │  OUT: New active config version, experiment card
              ▼
         ┌─────────┐
         │ 7. LEARN │
         └────┬────┘
              │  Record which operators worked for which failure
              │  families. Update bandit weights (if adaptive search).
              │  Store in optimizer memory for future cycles.
              │
              │  IN:  Experiment outcome
              │  OUT: Updated optimizer_memory.db
              ▼
         ┌──────────┐
         │ 8. REPEAT │
         └────┬─────┘
              │  Check budget. Check stall detection. Check for
              │  human pause signal. If all clear, go to step 1.
              │
              │  STOP conditions:
              │    - Budget exhausted (per-cycle or daily)
              │    - Plateau detected (N cycles without improvement)
              │    - Human pause command
              │    - Max cycles reached
              │
              └──────► Back to TRACE
```

---

## Eval pipeline detail

How a single evaluation run works, from input to scored output.

```
    Eval Dataset                    Candidate Config
    (golden, holdout,               (mutated YAML)
     adversarial, live)
         │                               │
         └───────────┬───────────────────┘
                     │
                     ▼
            ┌────────────────┐
            │  Replay Harness │
            │                 │
            │  Classify tools: │
            │   pure          │──► Run live
            │   read_only     │──► Run live
            │   write_rev     │──► Stub from baseline recording
            │   write_irrev   │──► Stub from baseline recording
            └────────┬────────┘
                     │
                     ▼
            ┌────────────────┐
            │  Judge Stack    │
            │                 │
            │  1. Deterministic (regex, schema)
            │     ↓ if inconclusive
            │  2. Similarity (Jaccard)
            │     ↓ if inconclusive
            │  3. Binary rubric (LLM judge)
            │     ↓ if borderline
            │  4. Audit judge (cross-family LLM)
            └────────┬────────┘
                     │
                     ▼
            ┌────────────────┐
            │  Scorer         │
            │                 │
            │  Hard gates:    │──► Binary pass/fail
            │  Objectives:    │──► Weighted continuous score
            │  SLOs:          │──► Constraint check
            └────────┬────────┘
                     │
                     ▼
            ┌────────────────┐
            │  Statistics     │
            │                 │
            │  Clustered bootstrap
            │  Sequential testing
            │  Multiple-hypothesis correction
            │  Judge variance estimation
            └────────┬────────┘
                     │
                     ▼
              Scored result
              (p-value, CI, effect size,
               per-case breakdown)
```

---

## Trace grading and blame map flow

How raw traces become actionable optimization opportunities.

```
    Agent invocation
         │
         ▼
    ┌──────────────┐
    │ Trace spans   │  Hierarchical tree of events:
    │               │  tool calls, transfers, model calls,
    │               │  state deltas, errors
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ 7 Graders     │  Each span scored independently:
    │               │
    │  routing      │  "billing query → tech_support"  → FAIL
    │  tool_select  │  "used order_lookup"             → PASS
    │  tool_args    │  "missing customer_id"           → FAIL
    │  retrieval    │  "relevant docs returned"        → PASS
    │  handoff      │  "context lost on transfer"      → FAIL
    │  memory       │  "stale cache used"              → WARN
    │  outcome      │  "wrong answer delivered"        → FAIL
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ Blame Map     │  Cluster by (grader, agent_path, reason):
    │               │
    │  Cluster A:   │  routing / billing / "missing keywords"
    │    23 spans   │  impact: 0.87  trend: ▲ worsening
    │               │
    │  Cluster B:   │  tool_args / order / "missing customer_id"
    │    12 spans   │  impact: 0.54  trend: → stable
    │               │
    │  Cluster C:   │  handoff / escalation / "context dropped"
    │    8 spans    │  impact: 0.41  trend: ▼ improving
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ Opportunity   │  Ranked queue:
    │ Queue         │
    │               │  #1  Cluster A  priority: 0.91
    │               │      recommended: routing_rule mutation
    │               │
    │               │  #2  Cluster B  priority: 0.67
    │               │      recommended: tool_hint mutation
    │               │
    │               │  #3  Cluster C  priority: 0.44
    │               │      recommended: instruction_rewrite
    └───────────────┘
```

---

## Request flow

How a single API request or CLI command flows through the system.

```
    User
     │
     ├─► CLI: autoagent optimize
     │     │
     │     └─► runner.py → Click command
     │           │
     │           └─► HTTP POST /api/optimize/run
     │
     ├─► API: POST /api/optimize/run
     │     │
     │     └─► api/routes/optimize.py
     │           │
     │           └─► optimizer/loop.py
     │                 │
     │                 ├─► observer/ (trace + diagnose)
     │                 ├─► optimizer/search.py (generate mutations)
     │                 ├─► evals/runner.py (evaluate candidates)
     │                 ├─► evals/statistics.py (significance test)
     │                 ├─► deployer/ (canary deploy)
     │                 └─► data/ (persist results)
     │
     └─► Web: click "Optimize" button
           │
           └─► React → fetch POST /api/optimize/run
                 │
                 └─► SSE /api/optimize/stream for live updates
                       │
                       └─► Events: cycle_start, diagnosis, proposal,
                                   evaluation, decision, cycle_complete
```

---

## Data model

Key entities and how they relate.

```
    ┌─────────────┐         ┌──────────────┐
    │ Config       │ 1──────* │ Experiment   │
    │              │         │ Card          │
    │ version      │         │              │
    │ yaml content │         │ hypothesis   │
    │ sha          │         │ baseline_sha │
    │ created_at   │         │ candidate_sha│
    └──────┬──────┘         │ scores       │
           │                │ p_value      │
           │                │ status       │
           │                └──────────────┘
           │
    ┌──────▼──────┐         ┌──────────────┐
    │ Trace        │ 1──────* │ Trace Span   │
    │              │         │              │
    │ trace_id     │         │ span_id      │
    │ session_id   │         │ agent_path   │
    │ created_at   │         │ event_type   │
    │              │         │ grades[]     │
    └──────────────┘         └──────┬───────┘
                                    │
                             ┌──────▼───────┐
                             │ Blame        │
                             │ Cluster      │
                             │              │
                             │ grader       │
                             │ agent_path   │
                             │ reason       │
                             │ span_count   │
                             │ impact_score │
                             │ trend        │
                             └──────┬───────┘
                                    │
                             ┌──────▼───────┐
                             │ Opportunity  │
                             │              │
                             │ cluster_id   │
                             │ priority     │
                             │ recommended  │
                             │ operator     │
                             └──────────────┘

    ┌─────────────┐         ┌──────────────┐
    │ Eval Run     │ 1──────* │ Eval Case    │
    │              │         │              │
    │ run_id       │         │ input        │
    │ config_sha   │         │ expected     │
    │ dataset_type │         │ actual       │
    │ scores       │         │ score        │
    │ significance │         │ judge_tier   │
    └──────────────┘         └──────────────┘

    ┌─────────────┐
    │ Registry     │
    │ Entry        │
    │              │
    │ type (skill / policy / tool / handoff)
    │ name         │
    │ version      │
    │ content      │
    │ status       │
    └──────────────┘
```

---

## Project structure

```
autoagent-vnextcc/
│
├── runner.py              CLI entry point (autoagent command)
├── autoagent.yaml         Runtime configuration
├── Dockerfile             Container build
├── docker-compose.yaml    Multi-service compose
├── Makefile               Dev commands (setup, test, dev, deploy)
│
├── api/                   FastAPI application
│   ├── server.py          App setup, middleware, route mounting
│   └── routes/            39 route modules (eval, optimize, deploy, ...)
│
├── web/                   React frontend
│   ├── src/pages/         39 pages
│   └── src/components/    Reusable UI components
│
├── observer/              Tracing and diagnosis
│   ├── traces.py          Trace collection and storage
│   ├── trace_grading.py   7 span-level graders
│   ├── blame_map.py       Failure clustering
│   └── opportunities.py   Ranked optimization queue
│
├── optimizer/             Search and mutation
│   ├── loop.py            Core optimization loop
│   ├── mutations.py       9 typed mutation operators
│   ├── search.py          4 search strategies
│   ├── experiments.py     Experiment card lifecycle
│   ├── prompt_opt/        Pro-mode algorithms (MIPROv2, GEPA, ...)
│   └── autofix.py         AutoFix copilot
│
├── evals/                 Evaluation engine
│   ├── runner.py          Eval execution
│   ├── data_engine.py     Dataset management (4 set types)
│   ├── replay.py          Side-effect isolated replay
│   ├── scorer.py          Constrained scoring (gates + objectives)
│   ├── statistics.py      Bootstrap, sequential testing
│   └── nl_scorer.py       Natural language scorer generation
│
├── judges/                Scoring pipeline
│   ├── grader_stack.py    Tiered judge (deterministic → LLM → audit)
│   ├── versioning.py      Judge version tracking
│   └── calibration.py     Drift monitoring, human feedback
│
├── deployer/              Deployment
│   ├── deployer.py        Canary rollout
│   └── release_manager.py Version promotion and rollback
│
├── registry/              Versioned configuration
│   ├── skill_registry.py
│   ├── policy_registry.py
│   ├── tool_contract_registry.py
│   └── handoff_schema_registry.py
│
├── context/               Context engineering
│   ├── analyzer.py        Growth pattern detection
│   └── simulator.py       Compaction strategy simulation
│
├── assistant/             Chat-based agent builder
├── adk/                   Google ADK integration
├── cx_studio/             Google CX Agent Studio integration
├── mcp_server/            MCP server for AI coding tools
├── simulator/             Simulation sandbox
├── core/                  Shared types and skills system
├── data/                  Data layer and persistence
├── logger/                Structured logging
├── control/               Human escape hatches
│
├── tests/                 131 test files, 1131+ passing
├── docs/                  Documentation
└── deploy/                Cloud deployment scripts (GCP, Fly.io)
```
