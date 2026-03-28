# AutoAgent

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB)
![Tests](https://img.shields.io/badge/tests-1131%2B%20passing-22C55E)
![License](https://img.shields.io/badge/license-Apache%202.0-111827)

AutoAgent is a continuous optimization platform for AI agents. It traces agent behavior, diagnoses failures, generates improvements, evaluates them with statistical rigor, and deploys winners — in an automated loop.

Point it at a broken agent. Get a better one back.

```
TRACE → DIAGNOSE → SEARCH → EVAL → GATE → DEPLOY → LEARN → REPEAT
```

> **[Platform overview](docs/platform-overview.md)** — Full walkthrough of every subsystem and feature
>
> **[Architecture and process diagrams](docs/architecture-diagram.md)** — Visual guide to system design and data flow

---

## Quick start

```bash
# Install
pip install -e ".[dev]"

# Configure
cp .env.example .env   # Add at least one API key (or skip for mock mode)

# Run
autoagent init
autoagent server       # Web console at http://localhost:8000
```

Start an optimization loop:

```bash
autoagent loop --max-cycles 20 --stop-on-plateau
```

Or try the 5-minute demo:

```bash
autoagent demo vp --company "Acme Corp" --web
```

The demo walks through a broken e-commerce support bot (misrouted billing queries, data leaks, high latency) and fixes all three issues in three optimization cycles — improving health from 0.62 to 0.87.

---

## How it works

Each optimization cycle follows eight steps:

| Step | What happens |
|------|-------------|
| **Trace** | Collect structured telemetry from agent invocations |
| **Diagnose** | Cluster failures, score opportunities, identify root causes |
| **Search** | Generate typed mutations ranked by expected lift, risk, and novelty |
| **Eval** | Replay mutations against test suites with side-effect isolation |
| **Gate** | Hard safety constraints first, then optimize objectives |
| **Deploy** | Promote winners via canary rollout with experiment card tracking |
| **Learn** | Record what worked and what didn't for future searches |
| **Repeat** | Loop autonomously until plateau or human intervention |

Every cycle produces a reviewable **experiment card** with a hypothesis, config diff, statistical significance, and rollback instructions. Hard safety gates are never traded off against performance.

---

## Core concepts

### Metric hierarchy

Every decision flows through four layers, evaluated in order:

| Layer | Role | Example |
|-------|------|---------|
| **Hard gates** | Must pass — binary | Safety violations, auth failures, state corruption |
| **North-star outcomes** | Optimized | Task success rate, groundedness, user satisfaction |
| **Operating SLOs** | Constrained | p95 latency, token cost, escalation rate |
| **Diagnostics** | Observed | Tool correctness, routing accuracy, handoff fidelity |

A mutation that improves task success by 12% but trips a safety gate is rejected.

### Typed mutations

Nine built-in mutation operators, each with a risk class:

- **Low risk** (auto-deploy eligible): `instruction_rewrite`, `example_swap`, `temperature_nudge`
- **Medium risk**: `tool_hint`, `routing_rule`, `policy_patch`
- **High risk** (human review required): `model_swap`, `topology_change`, `callback_patch`

### Search strategies

| Strategy | Behavior |
|----------|----------|
| `simple` | Single best mutation per cycle, greedy |
| `adaptive` | Bandit-guided operator selection (UCB1 / Thompson sampling) |
| `full` | Multi-hypothesis search with curriculum learning and holdout rotation |
| `pro` | Research-grade prompt optimization (MIPROv2, BootstrapFewShot, GEPA, SIMBA) |

### Experiment cards

Every optimization attempt produces a reviewable card with:

- Hypothesis and target surfaces
- Config SHA and risk classification
- Statistical significance (bootstrap CI, permutation test)
- Diff summary and rollback instructions

---

## Features

### Evaluation engine

Seven evaluation modes (deterministic, similarity, rubric-based, LLM-judged, and more) with multi-set support across training, validation, holdout, and adversarial splits. Bootstrap confidence intervals and sequential testing provide statistical rigor. Anti-Goodhart guards — holdout rotation, drift detection, variance bounds — prevent overfitting to your eval set.

### Trace analysis and blame maps

Span-level grading with seven pluggable graders: routing accuracy, tool selection, tool arguments, retrieval quality, handoff quality, memory use, and final outcome. The blame map clusters failures by `(grader, agent_path, reason)` with impact scoring and trend detection.

### Judge stack

Tiered grading pipeline: deterministic checks (regex, invariants) → similarity scoring → binary rubric (LLM judge) → audit judge (cross-family LLM). Includes versioning, drift monitoring, human feedback calibration, and agreement tracking.

### AutoFix copilot

AI-driven failure analysis that produces constrained improvement proposals. Each proposal includes root cause, suggested mutation, expected lift, and risk assessment. Review before apply.

### NL scorer generation

Describe what good looks like in plain English, get a typed eval scorer. Refine iteratively, test against real traces.

### Context engineering workbench

Context window diagnostics: growth pattern detection, utilization analysis, failure correlation, and compaction simulation across aggressive, balanced, and conservative strategies.

### Modular registry

Versioned CRUD for skills, policies, tool contracts, and handoff schemas. SQLite-backed with import/export, search, and version diffing.

### Intelligence studio

Upload transcript archives (ZIP with JSON/CSV/TXT) and get automatic analytics: intent classification, transfer reason analysis, procedure extraction, FAQ generation, and Q&A over conversation data. One-click agent generation from conversation patterns.

### Assistant builder

Chat-based agent building from natural language descriptions. Supports multi-modal ingestion (transcripts, SOPs, audio, images), intent extraction, journey mapping, and auto-generated tools and escalation logic.

### Human escape hatches

```bash
autoagent pause                    # Pause the optimization loop
autoagent resume                   # Resume
autoagent pin <surface>            # Lock a surface from mutation
autoagent unpin <surface>          # Unlock
autoagent reject <experiment-id>   # Reject and rollback an experiment
```

### Cost controls

Per-cycle and daily budget tracking. The loop halts when spend limits are hit. Diminishing returns detection stops wasting cycles when the Pareto frontier stalls.

---

## Integrations

### Google CX Agent Studio

Bidirectional integration — import CX agents, optimize, export back:

```bash
autoagent cx import --project my-project --location us-central1
autoagent optimize --cycles 10
autoagent cx export
autoagent cx deploy --environment PROD
```

### Google Agent Development Kit (ADK)

Import ADK agents from Python source via AST parsing. Export patches back while preserving developer style and comments. Deploy to Cloud Run or Vertex AI.

```bash
autoagent adk import ./my_agent
autoagent adk export
autoagent adk deploy
```

### MCP server

Model Context Protocol integration for AI coding assistants (Claude Code, Cursor, Windsurf):

```bash
autoagent mcp-server
```

Add to `~/.claude/mcp.json`:

```json
{
  "mcpServers": {
    "autoagent": {
      "command": "autoagent",
      "args": ["mcp-server"]
    }
  }
}
```

Exposes 10 tools: `status`, `eval_run`, `optimize`, `config_list`, `config_show`, `config_diff`, `deploy`, `conversations_list`, `trace_grade`, `memory_show`.

---

## Web console

Start the server and open `http://localhost:8000`. The console includes 39 pages:

**Observe** — Dashboard with health pulse, journey timeline, and recommendations. Traces viewer with span-level detail. Blame map for failure clustering. Conversation browser with outcome filtering.

**Optimize** — Trigger optimization cycles, view experiment cards, stream live progress via SSE. AutoFix proposals with apply/reject workflow. Opportunity queue ranked by impact.

**Evaluate** — Eval run history with comparison mode. Per-case results with pass/fail breakdown. Judge calibration and drift monitoring. NL scorer studio.

**Build** — Agent Studio for natural language config edits. Intelligence Studio for transcript-to-agent pipelines. Assistant for chat-based agent building.

**Manage** — Config versions with YAML viewer and side-by-side diffs. Registry browser for skills, policies, tools, and handoff schemas. Deploy with canary controls. Loop monitor with watchdog health.

---

## CLI reference

```
autoagent <command> [options]
```

| Command | Purpose |
|---------|---------|
| `init` | Scaffold a new project |
| `quickstart` | Run the full golden path |
| `server` | Start the API server and web console |
| `status` | Health check with metrics |
| `eval run` | Run an evaluation suite |
| `optimize` | Run optimization cycles |
| `loop` | Start continuous optimization |
| `deploy` | Deploy a config version (canary or immediate) |
| `config list/show/diff` | Manage config versions |
| `trace grade/blame/graph` | Trace analysis |
| `autofix suggest/apply` | AI-powered failure fixes |
| `judges list/calibrate/drift` | Judge operations |
| `context analyze/simulate` | Context window diagnostics |
| `registry list/show/add` | Manage skills, policies, tools, handoffs |
| `scorer create/test/refine` | NL scorer generation |
| `skill list/create/compose` | Executable optimization strategies |
| `runbook list/apply` | Curated fix bundles |
| `cx import/export/deploy` | CX Agent Studio integration |
| `adk import/export/deploy` | ADK integration |
| `edit` | Natural language config edits |
| `diagnose` | Interactive failure diagnosis |
| `pause` / `resume` | Human control over the loop |
| `pin` / `unpin` | Lock config surfaces from mutation |
| `demo vp` | 5-minute VP demo |

All commands support `--help`. Major commands support `--json` for structured output.

See [docs/cli-reference.md](docs/cli-reference.md) for the full reference.

---

## API

200+ endpoints across 39 route modules. OpenAPI docs are served at `/docs`.

```http
GET    /api/health                     Health check with scorecard
POST   /api/eval/run                   Trigger evaluation
GET    /api/eval/history               List past evaluations
POST   /api/optimize/run               Run optimization cycles
GET    /api/optimize/stream            SSE stream for live progress
GET    /api/experiments                List experiment cards
GET    /api/traces/blame               Failure clustering
POST   /api/deploy/deploy              Deploy config (canary or immediate)
GET    /api/config/list                List config versions
POST   /api/scorers/create             Generate scorer from NL description
POST   /api/edit                       Apply natural language config edit
POST   /api/intelligence/archive       Import transcript archive
POST   /api/cx/import                  Import CX Agent Studio agent
POST   /api/adk/import                 Import ADK agent from source
WS     /ws                             WebSocket for real-time updates
GET    /api/events                     Server-Sent Events stream
```

See [docs/api-reference.md](docs/api-reference.md) for the full endpoint list.

---

## Configuration

AutoAgent is configured through `autoagent.yaml`:

```yaml
optimizer:
  use_mock: true                      # Use mock providers (no API key needed)
  search_strategy: simple             # simple | adaptive | full | pro
  models:
    - provider: google
      model: gemini-2.5-pro
      api_key_env: GOOGLE_API_KEY
    - provider: openai
      model: gpt-4o
      api_key_env: OPENAI_API_KEY
    - provider: anthropic
      model: claude-sonnet-4-5
      api_key_env: ANTHROPIC_API_KEY

budget:
  per_cycle_dollars: 1.0
  daily_dollars: 10.0

loop:
  schedule_mode: continuous           # continuous | interval | cron
  interval_minutes: 5.0
  checkpoint_path: .autoagent/loop_checkpoint.json

eval:
  significance_alpha: 0.05
  significance_iterations: 2000

human_control:
  immutable_surfaces: ["safety_instructions"]
```

### Environment variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `GOOGLE_API_KEY` | For Gemini models | Google AI API key |
| `OPENAI_API_KEY` | For OpenAI models | OpenAI API key |
| `ANTHROPIC_API_KEY` | For Anthropic models | Anthropic API key |

At least one API key is required for non-mock optimization. For testing with mock providers, no keys are needed.

### Multi-model support

| Provider | Models |
|----------|--------|
| Google | Gemini 2.5 Pro, Gemini 2.5 Flash |
| OpenAI | GPT-4o, GPT-4o-mini, o1, o3 |
| Anthropic | Claude Sonnet 4.5, Claude Haiku 3.5 |
| OpenAI-compatible | Any endpoint matching the OpenAI API |
| Mock | Deterministic responses for testing |

---

## Deploy

### Docker

```bash
docker build -t autoagent .
docker run -p 8000:8000 --env-file .env autoagent
```

Persist data across restarts:

```bash
docker run -p 8000:8000 -v autoagent-data:/app/data --env-file .env autoagent
```

Or use Docker Compose:

```bash
docker compose up --build -d
```

### Google Cloud Run

```bash
# Set your project
export PROJECT_ID="your-project-id"
export REGION="us-central1"

# Enable required APIs
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com

# Deploy
chmod +x deploy/deploy.sh
./deploy/deploy.sh $PROJECT_ID $REGION
```

The script creates an Artifact Registry repo, builds and pushes the Docker image, and deploys to Cloud Run. See [docs/deployment.md](docs/deployment.md) for detailed GCP setup, secret management, custom domains, and troubleshooting.

### Fly.io

```bash
fly launch --name autoagent --region ord --no-deploy
fly secrets set GOOGLE_API_KEY="your-key"
fly deploy
```

---

## Project structure

```
autoagent-vnextcc/
├── agent/           Agent framework, config, tools, specialists
├── api/             FastAPI server (39 route modules, 200+ endpoints)
├── assistant/       Chat-based agent builder
├── adk/             Google ADK integration
├── cli/             CLI command modules
├── context/         Context engineering workbench
├── core/            Shared domain types and skills system
├── cx_studio/       Google CX Agent Studio integration
├── deployer/        Canary deployment and release management
├── evals/           Evaluation runner, scoring, datasets, replay
├── graders/         Tiered grading pipeline
├── judges/          Judge stack with versioning and calibration
├── mcp_server/      Model Context Protocol server
├── observer/        Trace analysis, blame maps, anomaly detection
├── optimizer/       Optimization loop, mutations, search strategies
├── registry/        Versioned skills, policies, tools, handoffs
├── simulator/       Simulation sandbox and stress testing
├── tests/           Test suite (131 files, 1131+ tests)
├── web/             React + TypeScript frontend (39 pages)
├── runner.py        CLI entry point
├── autoagent.yaml   Configuration
└── Dockerfile
```

---

## Development

```bash
# Set up a virtual environment
make setup

# Run the dev server
make dev

# Run tests
make test

# Lint and format
make lint
make fmt
```

### Tech stack

- **Backend**: Python 3.11+, FastAPI, SQLite, Click
- **Frontend**: React 19, TypeScript, Vite, Tailwind CSS
- **Testing**: pytest, Playwright

---

## Documentation

**Start here:**
- [Platform Overview](docs/platform-overview.md) — Full walkthrough of every subsystem and feature
- [Architecture and Process Diagrams](docs/architecture-diagram.md) — Visual guide to system design and data flow

**Guides:**
- [Getting Started](docs/getting-started.md)
- [Concepts](docs/concepts.md)
- [CLI Reference](docs/cli-reference.md)
- [API Reference](docs/api-reference.md)
- [Deployment Guide](docs/deployment.md)

**Feature deep dives:** [AutoFix](docs/features/autofix.md) | [Judge Ops](docs/features/judge-ops.md) | [Context Workbench](docs/features/context-workbench.md) | [Prompt Optimization](docs/features/prompt-optimization.md) | [Registry](docs/features/registry.md) | [Trace Grading](docs/features/trace-grading.md) | [NL Scorer](docs/features/nl-scorer.md)

---

## License

Apache 2.0
