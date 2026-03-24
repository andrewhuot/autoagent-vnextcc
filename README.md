# AutoAgent VNextCC

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB)
![1131 tests](https://img.shields.io/badge/tests-1131_passing-22C55E)
![License](https://img.shields.io/badge/license-Apache%202.0-111827)

Continuous evaluation and optimization for AI agents. Trace every invocation, diagnose failures, search for improvements, evaluate with statistical rigor, gate on hard constraints, deploy with canaries, learn from outcomes. Repeat.

CLI-first. Gemini-first, multi-model capable. Research-grade.

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB)
![1131 tests](https://img.shields.io/badge/tests-1131_passing-22C55E)
![License](https://img.shields.io/badge/license-Apache%202.0-111827)

---

## How It Works

AutoAgent runs a closed-loop optimization cycle over your agent:

```
1. TRACE     → Collect structured events from agent invocations
2. DIAGNOSE  → Cluster failures, score opportunities
3. SEARCH    → Generate typed mutations, rank by lift/risk/novelty
4. EVAL      → Replay with side-effect isolation, grade with judge stack
5. GATE      → Hard constraints first, then optimize objectives
6. DEPLOY    → Canary with experiment card tracking
7. LEARN     → Record what worked, avoid what didn't
8. REPEAT
```

Each cycle produces a reviewable experiment card. Hard safety gates are never traded off against performance. The loop runs unattended for days, or you intervene at any point.

---

## Quickstart

```bash
pip install -e ".[dev]"
autoagent init
autoagent eval run --output results.json
autoagent server  # → http://localhost:8000
autoagent loop --max-cycles 20 --stop-on-plateau
```

---

## Key Features

### 4-Layer Metric Hierarchy

Every decision flows through four layers, evaluated in order:

| Layer | What | Role |
|-------|------|------|
| **Hard Gates** | Safety, authorization, state integrity, P0 regressions | Must pass — binary |
| **North-Star Outcomes** | Task success, groundedness, user satisfaction | Optimized |
| **Operating SLOs** | Latency (p50/p95/p99), token cost, escalation rate | Constrained |
| **Diagnostics** | Tool correctness, routing accuracy, handoff fidelity, judge disagreement | Diagnosis only |

A mutation that improves task success by 12% but trips a safety gate is rejected.

### Typed Mutations

9 built-in mutation operators, each with a risk class:

- **Low risk (auto-deploy eligible):** `instruction_rewrite`, `example_swap`, `temperature_nudge`
- **Medium risk:** `tool_hint`, `routing_rule`, `policy_patch`
- **High risk (human review required):** `model_swap`, `topology_change`, `callback_patch`

Plus Google Prompt Optimizer stubs and experimental topology operators.

### Experiment Cards

Every optimization attempt produces a reviewable card:

- Hypothesis and target surfaces
- Config SHA and risk classification
- Statistical significance (bootstrap CI, permutation test)
- Diff summary and rollback instructions

### Search Strategies

| Strategy | Behavior |
|----------|----------|
| `simple` | Single best mutation per cycle, greedy |
| `adaptive` | Bandit-guided (UCB1/Thompson) operator selection |
| `full` | Multi-hypothesis + curriculum learning + holdout rotation |
| `pro` | Real prompt optimization (MIPROv2, BootstrapFewShot, GEPA, SIMBA) |

### Pro-Mode Prompt Optimization

Four research-grade algorithms for prompt search:

- **MIPROv2** — Multi-prompt instruction proposal with Bayesian search over (instruction, example_set) space
- **BootstrapFewShot** — DSPy-inspired teacher-student demonstration bootstrapping
- **GEPA** — Gradient-free evolutionary prompt adaptation with tournament selection
- **SIMBA** — Simulation-based iterative hill-climbing optimization

### AutoFix Copilot

AI-driven failure analysis produces constrained improvement proposals. Each proposal includes root cause, suggested mutation, expected lift, and risk assessment. Review before apply.

### Judge Ops

Versioned judges with drift monitoring, human feedback calibration, and agreement tracking. Tiered grading pipeline:

1. Deterministic checks (regex, state invariants, confidence=1.0)
2. Similarity scoring (token-overlap Jaccard)
3. Binary rubric (4 yes/no questions, LLM judge)
4. Audit judge (cross-family LLM for promotions)
5. Calibration suite (agreement, drift, position bias, verbosity bias)

### Context Engineering Workbench

Context window diagnostics for agent conversations:

- Growth pattern detection and utilization analysis
- Failure correlation with context state
- Compaction simulation (aggressive / balanced / conservative)
- Handoff scoring

### Modular Registry

Versioned CRUD for skills, policies, tool contracts, and handoff schemas. SQLite-backed with import/export, search, and version diffing.

### Trace Grading + Blame Map

Span-level grading with 7 pluggable graders:

- Routing accuracy, tool selection, tool arguments
- Retrieval quality, handoff quality, memory use
- Final outcome

Blame map clusters failures by `(grader, agent_path, reason)` with impact scoring and trend detection.

### NL Scorer Generation

Natural language to structured eval rubrics. Describe what good looks like in plain English, get a typed scorer. Refine iteratively, test against real traces.

### Human Escape Hatches

```bash
autoagent pause                    # Pause the optimization loop
autoagent resume                   # Resume
autoagent pin <surface>            # Lock a surface from mutation
autoagent unpin <surface>          # Unlock
autoagent reject <experiment-id>   # Reject and rollback an experiment
```

### Cost Controls

SQLite-backed per-cycle and daily budget tracking. The loop halts when spend limits are hit. Diminishing returns detection stops wasting cycles when the Pareto frontier stalls.

### Anti-Goodhart Guards

- **Holdout rotation** — tuning/validation/holdout partitions rotate periodically
- **Drift detection** — monitors tuning vs. validation gap, flags overfitting
- **Judge variance estimation** — accounts for LLM judge noise in significance testing

---

## CLI Reference

```
autoagent <group> <command> [options]
```

| Group | Commands |
|-------|----------|
| `eval` | `run`, `history`, `compare`, `export` |
| `optimize` | `run`, `status`, `history` |
| `loop` | `start`, `stop`, `status`, `--max-cycles`, `--stop-on-plateau` |
| `autofix` | `analyze`, `propose`, `apply`, `status` |
| `judges` | `list`, `create`, `calibrate`, `drift-check` |
| `context` | `analyze`, `simulate`, `report` |
| `registry` | `list`, `add`, `update`, `delete`, `import`, `export`, `diff` |
| `trace` | `list`, `grade`, `blame-map` |
| `scorer` | `create`, `test`, `list`, `refine` |
| `config` | `show`, `diff`, `promote`, `rollback` |
| `deploy` | `canary`, `promote`, `rollback`, `status` |
| `server` | Start the web console and API |
| `status` | Current loop and system status |
| `logs` | Tail structured logs |
| `pause` / `resume` | Human control over the loop |
| `pin` / `unpin` | Lock/unlock surfaces from mutation |
| `reject` | Reject and rollback an experiment |

---

## Web Console

19 pages served at `http://localhost:8000`:

| Page | Purpose |
|------|---------|
| Dashboard | 2 hard gates + 4 primary metrics, cost controls, event timeline |
| Eval Runs | Sortable table of all evaluations |
| Eval Detail | Per-case results with pass/fail breakdown |
| Optimize | Trigger optimization, view attempt history |
| Experiments | Reviewable experiment cards with hypothesis and diff |
| Opportunities | Ranked optimization opportunity queue |
| Traces | ADK event traces and spans |
| Blame Map | Span-level failure clustering and root cause |
| Configs | Version list, YAML diff viewer |
| Conversations | Browse logged agent conversations |
| Deploy | Canary status, promote/rollback controls |
| Loop Monitor | Live loop status, cycle history, watchdog health |
| Event Log | Append-only system event timeline |
| AutoFix | Improvement proposals with apply/reject |
| Judge Ops | Judge versions, drift, calibration |
| Context Workbench | Context analysis, compaction simulation |
| Registry | Skills, policies, tools, handoff schemas |
| Scorer Studio | NL scorer creation and testing |
| Settings | Runtime configuration |

---

## API

75 endpoints across 18 route modules. Representative endpoints:

```
GET    /api/health                        Health check
POST   /api/eval/run                      Trigger evaluation run
GET    /api/eval/history                  List past evaluations
GET    /api/eval/{run_id}                 Get evaluation detail
POST   /api/optimize/run                  Trigger optimization
GET    /api/experiments                    List experiment cards
POST   /api/experiments/{id}/approve       Approve experiment for deploy
POST   /api/deploy/canary                 Start canary deployment
GET    /api/traces                        List traces
GET    /api/traces/{id}/blame-map         Get blame map for trace
GET    /api/judges                        List judge versions
GET    /api/registry/{type}               List registry entries by type
POST   /api/scorers/generate              Generate scorer from NL description
GET    /api/loop/status                   Current loop state
POST   /api/control/pause                 Pause the loop
```

Full route modules: `health`, `eval`, `optimize`, `experiments`, `opportunities`, `deploy`, `config`, `control`, `traces`, `conversations`, `events`, `loop`, `autofix`, `judges`, `context`, `registry`, `scorers`.

---

## Configuration

Everything is driven by `autoagent.yaml`:

```yaml
optimizer:
  use_mock: true
  strategy: round_robin
  search_strategy: simple          # simple | adaptive | full | pro
  bandit_policy: thompson          # ucb1 | thompson
  search_max_candidates: 10
  search_max_eval_budget: 5
  search_max_cost_dollars: 1.0
  search_time_budget_seconds: 300
  holdout_tolerance: 0.0
  holdout_rotation_interval: 5
  drift_threshold: 0.12
  max_judge_variance: 0.03
  retry:
    max_attempts: 3
    base_delay_seconds: 0.5
    max_delay_seconds: 8.0
    jitter_seconds: 0.25
  models:
    - provider: google
      model: gemini-2.5-pro
      api_key_env: GOOGLE_API_KEY
      requests_per_minute: 120
      input_cost_per_1k_tokens: 0.00125
      output_cost_per_1k_tokens: 0.005
    - provider: openai
      model: gpt-4o
      api_key_env: OPENAI_API_KEY
    - provider: anthropic
      model: claude-sonnet-4-5
      api_key_env: ANTHROPIC_API_KEY

loop:
  schedule_mode: continuous
  interval_minutes: 5.0
  cron: "*/5 * * * *"
  checkpoint_path: .autoagent/loop_checkpoint.json
  dead_letter_db: .autoagent/dead_letters.db
  watchdog_timeout_seconds: 300
  resource_warn_memory_mb: 2048
  resource_warn_cpu_percent: 90
  structured_log_path: .autoagent/logs/backend.jsonl
  log_max_bytes: 5000000
  log_backup_count: 5

eval:
  history_db_path: eval_history.db
  dataset_path:
  dataset_split: test
  significance_alpha: 0.05
  significance_min_effect_size: 0.005
  significance_iterations: 2000

budget:
  per_cycle_dollars: 1.0
  daily_dollars: 10.0
  stall_threshold_cycles: 5
  tracker_db_path: .autoagent/cost_tracker.db

human_control:
  immutable_surfaces: ["safety_instructions"]
  state_path: .autoagent/human_control.json
```

---

## Multi-Model Support

| Provider | Models | Notes |
|----------|--------|-------|
| **Google** | Gemini 2.5 Pro, Gemini 2.5 Flash | Default provider |
| **OpenAI** | GPT-4o, GPT-4o-mini, o1, o3 | |
| **Anthropic** | Claude Sonnet 4.5, Claude Haiku 3.5 | |
| **OpenAI-compatible** | Any endpoint matching the OpenAI API | Custom base URL |
| **Mock** | Deterministic responses for testing | No API key needed |

Configure multiple models in `autoagent.yaml`. The optimizer uses them for judge diversity, mutation generation, and A/B evaluation.

---

## Architecture

```
agent/          Agent framework, config, tools, specialists
api/            FastAPI server, 75 endpoints across 18 route modules
context/        Context Engineering Workbench (analyzer, simulator, metrics)
control/        Governance wrapper for promotion decisions
core/           10 first-class domain objects
data/           Protocol-based repositories, event log
deployer/       Canary deployment, release manager, config versioning
evals/          Runner, scorer, data engine, replay, anti-Goodhart, statistics, NL scorer
graders/        Tiered grading pipeline (deterministic, similarity, binary rubric)
judges/         Judge subsystem (versioning, drift, calibration, human feedback)
logger/         Structured logging
observer/       Traces, anomaly detection, failure clustering, blame map, trace grading
optimizer/      Loop, search, mutations, bandit, Pareto, cost tracker, prompt_opt/
registry/       Modular registry (skills, policies, tool contracts, handoff schemas)
web/            React console, 19 pages, 29 components
```

---

## By the Numbers

| | |
|---|---|
| Test suite | **1,131 tests** |
| Python backend | ~46,600 lines |
| React frontend | ~8,800 lines |
| API endpoints | 75 |
| Frontend pages | 19 |
| Reusable components | 29 |
| Judge/grader modules | 9 |
| Python packages | 14 |
| Test files | 59 |

---

## What This Is (and Isn't)

AutoAgent VNextCC is a research-grade platform for continuous agent optimization. It implements the full trace-to-deploy loop with real statistical gating, real canary deployments, and multi-day unattended operation.

It is **not** a hosted product. There is no auth, no multi-tenancy, no billing. It runs on your machine, optimizes your agent, and gets out of the way.

---

## Documentation

- [Architecture Overview](ARCHITECTURE_OVERVIEW.md)
- [Getting Started](docs/getting-started.md)
- [Concepts](docs/concepts.md)
- [CLI Reference](docs/cli-reference.md)
- [API Reference](docs/api-reference.md)
- Features: [AutoFix](docs/features/autofix.md) | [Judge Ops](docs/features/judge-ops.md) | [Context Workbench](docs/features/context-workbench.md) | [Prompt Optimization](docs/features/prompt-optimization.md) | [Registry](docs/features/registry.md) | [Trace Grading](docs/features/trace-grading.md) | [NL Scorer](docs/features/nl-scorer.md)

---

## Tech Stack

- **Backend:** Python 3.11+, FastAPI, Uvicorn, SQLite
- **CLI:** Click
- **Frontend:** React, Vite, TypeScript, Tailwind CSS
- **Tests:** pytest (1,131 passing)

---

## License

Apache 2.0
