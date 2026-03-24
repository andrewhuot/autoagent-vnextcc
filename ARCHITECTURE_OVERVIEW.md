# AutoAgent VNextCC — Architecture & Implementation Overview

**What it is:** A product-grade platform that continuously evaluates and optimizes AI agents in production. Point it at an ADK agent, and it will run an autonomous loop — eval, observe, propose improvements, gate on statistical significance, deploy via canary, repeat — for days or weeks without human intervention.

**What it looks like:** OpenAI Evals meets Vercel's design system. Headless-first (90% CLI/API), with a clean React console for visual insight.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Operator Interfaces                       │
│   CLI (autoagent ...)    REST API (/api/*)    Web Console   │
└──────────────────────────┬──────────────────────────────────┘
                           │
                    ┌──────▼──────┐
                    │  FastAPI    │  api/server.py
                    │  + TaskMgr  │  Background task orchestration
                    └──────┬──────┘
                           │
    ┌──────────┬───────────┼───────────┬──────────┐
    │          │           │           │          │
┌───▼───┐ ┌───▼───┐  ┌────▼───┐ ┌────▼───┐ ┌───▼────┐
│ Eval  │ │Observe│  │Optimize│ │ Deploy │ │ Logger │
│Runner │ │  r    │  │  r     │ │  er    │ │        │
└───┬───┘ └───┬───┘  └────┬───┘ └────┬───┘ └───┬────┘
    │         │            │          │          │
    │    ┌────▼────┐  ┌────▼────┐ ┌───▼────┐    │
    │    │Anomaly  │  │Provider │ │Canary  │    │
    │    │Detector │  │ Router  │ │Manager │    │
    │    │Classifier│ │(LLM)   │ │Version │    │
    │    └─────────┘  └────┬────┘ │Manager │    │
    │                      │      └────────┘    │
    └──────────────────────┼────────────────────┘
                           │
              ┌────────────▼────────────┐
              │     Persistence Layer    │
              │  SQLite (conversations,  │
              │  optimizer memory, eval  │
              │  history, dead letters)  │
              │  YAML (configs, versions)│
              │  JSON (checkpoints, logs)│
              └─────────────────────────┘
```

---

## The Core Loop

The system runs one loop continuously:

```
1. OBSERVE  → Compute health metrics from recent conversations
2. DETECT   → Anomaly detection (2σ), failure classification
3. PROPOSE  → LLM generates a config improvement (via provider router)
4. VALIDATE → Schema validation, safety checks, noop detection
5. EVAL     → Run eval suite against candidate config
6. GATE     → Safety gate → Improvement gate → Regression gate → Significance gate
7. DEPLOY   → Canary deployment with traffic splitting
8. CHECKPOINT → Save loop state for crash recovery
9. WAIT     → Sleep per schedule (continuous / interval / cron)
10. REPEAT
```

Each cycle is wrapped in exception handling. Failures go to a dead letter queue — the loop never crashes.

---

## Key Subsystems

### Multi-Model Provider Router (`optimizer/providers.py`, 479 lines)

The optimizer's LLM calls go through an abstract router that supports any provider:

| Provider | Models | Auth |
|----------|--------|------|
| **Google** (default) | Gemini 2.5 Pro, Flash | `GOOGLE_API_KEY` |
| **OpenAI** | GPT-4o, GPT-5, o3 | `OPENAI_API_KEY` |
| **Anthropic** | Claude Sonnet, Opus | `ANTHROPIC_API_KEY` |
| **OpenAI-compatible** | Any local model | Custom `base_url` |
| **Mock** | Deterministic test proposer | No key needed |

**Routing strategies:**
- `single` — Use one model (default: Gemini 2.5 Pro)
- `round_robin` — Rotate through configured models
- `ensemble` — Run all models, compare proposals (opt-in)

Each provider includes: retry with exponential backoff + jitter, per-provider rate limiting, cost tracking (input/output tokens), and timeout handling.

**Design principle:** Single model works great out of the box. Ensemble is there if you want multiple perspectives on the same agent — Gemini for fast screening, Claude for deep analysis, GPT for creative proposals.

### Statistical Significance Gating (`evals/statistics.py`)

Improvements must pass a paired bootstrap significance test before deployment:

- Paired per-case comparison (not just aggregate scores)
- Configurable α (default 0.05), minimum effect size (0.005), bootstrap iterations (2,000)
- Prevents deploying noise as "improvement"

### Long-Running Reliability (`optimizer/reliability.py`, 324 lines)

Built to run for days without intervention:

| Feature | Implementation |
|---------|---------------|
| **Graceful shutdown** | SIGTERM/SIGINT handlers; finishes current cycle before exiting |
| **Checkpoint/resume** | JSON checkpoint after every cycle; `--resume` flag restarts from last position |
| **Dead letter queue** | SQLite-backed; failed cycles are logged, not lost |
| **Watchdog** | Heartbeat-based stall detection; alerts if cycle exceeds timeout |
| **Resource monitoring** | Memory/CPU sampling per cycle; warns at configurable thresholds |
| **Structured logging** | JSON log with rotation (5MB × 5 backups) |
| **Scheduling** | Continuous, interval (every N minutes), or cron (5-field UTC) |

### Eval Pipeline (`evals/runner.py`, `evals/history.py`)

- **YAML fixtures** — Built-in test cases across 4 categories (happy path, edge cases, safety, regression)
- **Dataset loaders** — JSONL/CSV with train/test split support
- **Custom evaluators** — Python callables for domain-specific scoring
- **Built-in metrics** — Quality (LLM-as-judge ready), safety, latency, cost, tool-use accuracy, custom scores
- **Provenance** — Every eval run records: judge model, prompt, dataset, split, timestamp
- **History** — SQLite-backed eval history with full per-case results

### Web Console (`web/src/`, 4,509 lines)

React + Vite + TypeScript + Tailwind. 9 pages, 20 reusable components.

**Design language:** Apple/OpenAI aesthetic — Inter font, neutral grays, one accent color, generous whitespace, no gradients, no heavy shadows. Linear-style Cmd+K command palette.

| Page | Purpose |
|------|---------|
| Dashboard | Hero metrics + recent eval runs |
| Eval Runs | Sortable table of all evaluations |
| Eval Detail | Per-case results with pass/fail breakdown |
| Optimize | Trigger optimization, view attempt history with significance stats |
| Configs | Version list, YAML diff viewer |
| Conversations | Browse logged agent conversations |
| Deploy | Canary status, promote/rollback controls |
| Loop Monitor | Live loop status, cycle history, watchdog/DLQ health |
| Settings | Runtime configuration |

### CLI (`runner.py`, 1,148 lines)

```bash
autoagent init              # Scaffold project
autoagent eval run          # Run eval suite (--dataset, --split, --category)
autoagent eval results      # Inspect results
autoagent eval list         # List eval history
autoagent optimize          # Run optimization cycles
autoagent loop              # Start autonomous loop (--schedule, --resume, --cron)
autoagent config list       # List config versions
autoagent config diff V1 V2 # Diff two versions
autoagent deploy            # Deploy config (--strategy canary|immediate)
autoagent status            # System health overview
autoagent logs              # View structured logs
autoagent server            # Start API + web console
```

### REST API

Full CRUD for every subsystem. Key endpoints:

```
POST   /api/eval/run          — Start eval (async, returns task ID)
GET    /api/eval/history       — Persisted eval runs with provenance
POST   /api/optimize/run       — Trigger optimization cycle
GET    /api/optimize/history    — Attempt history with significance stats
POST   /api/loop/start         — Start autonomous loop
GET    /api/loop/status         — Loop health + cycle history
GET    /api/health              — Agent health metrics + anomalies
GET    /api/health/system       — Operational health (watchdog, DLQ, uptime)
POST   /api/deploy              — Deploy config version
GET    /api/conversations       — Browse conversation logs
GET    /api/config/list         — Config version history
```

---

## Configuration

Everything is driven by `autoagent.yaml`:

```yaml
optimizer:
  use_mock: true              # false to use real LLM providers
  strategy: single            # single | round_robin | ensemble
  models:
    - provider: google
      model: gemini-2.5-pro
      api_key_env: GOOGLE_API_KEY

loop:
  schedule_mode: continuous   # continuous | interval | cron
  checkpoint_path: .autoagent/loop_checkpoint.json
  watchdog_timeout_seconds: 300

eval:
  significance_alpha: 0.05
  significance_min_effect_size: 0.005
```

---

## By the Numbers

| Metric | Value |
|--------|-------|
| Python backend | 9,529 lines |
| React frontend | 4,509 lines |
| Documentation | 2,849 lines |
| Test suite | 76 tests passing |
| New modules added | 6 (providers, reliability, statistics, history, structured logging, runtime config) |
| Reusable React components | 20 |
| Frontend pages | 9 |
| API endpoints | 18 |
| CLI commands | 12 |
| Playwright visual QA tests | 11 |
| Screenshots captured | 11 |

---

## What Makes This Different

1. **It actually works.** Not a prototype — the eval→optimize→deploy loop runs end-to-end with real scoring, real gating, real deployment.

2. **It doesn't crash.** Graceful shutdown, checkpoint/resume, dead letter queues, watchdog monitoring. Built for multi-day unattended operation.

3. **It doesn't deploy noise.** Statistical significance testing prevents accepting improvements that aren't real.

4. **It's model-agnostic.** Gemini by default, but swap to Claude, GPT, or a local model with one config change. Or run all of them in ensemble mode.

5. **It looks like a product.** Not a research notebook. Clean CLI, comprehensive API, polished web console.

---

*Built with Claude Code (Opus) + Codex (GPT-5.3) in parallel. CC handled frontend visual QA and Apple-grade polish. Codex handled backend architecture review and production hardening.*

*Repository: https://github.com/andrewhuot/autoagent-vnextcc*
