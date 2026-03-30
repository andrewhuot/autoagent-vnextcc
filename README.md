# AutoAgent

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB)
![Tests](https://img.shields.io/badge/tests-1131%2B%20passing-22C55E)
![License](https://img.shields.io/badge/license-Apache%202.0-111827)

AutoAgent is a continuous optimization platform for AI agents. It traces agent behavior, diagnoses failures, generates improvements, evaluates them with statistical rigor, and deploys winners — in an automated loop.

Point it at a broken agent. Get a better one back.

```
TRACE → DIAGNOSE → SEARCH → EVAL → GATE → DEPLOY → LEARN → REPEAT
```

The CLI now uses a workspace-first UX:

- `autoagent init --name my-project --demo` bootstraps a self-sufficient workspace
- `autoagent status` is the home screen for the active workspace
- Commands auto-discover the nearest workspace, so you can run them from any subdirectory
- `autoagent import config ...` turns plain files into managed config history
- `autoagent intelligence ...`, `autoagent mcp ...`, and `autoagent mode ...` are first-class command groups

> **[Platform overview](docs/platform-overview.md)** — Full walkthrough of every subsystem and feature
>
> **[Architecture and process diagrams](docs/architecture-diagram.md)** — Visual guide to system design and data flow
>
> **[Quick Start](docs/QUICKSTART_GUIDE.md)** — Get a working agent in 2 minutes. See the [Detailed Guide](docs/DETAILED_GUIDE.md) for the full walkthrough.

---

## Workspace-first CLI quick start

If you want the CLI flow without starting the full web stack, this is the fastest path:

```bash
python3 -m pip install -e .
autoagent init --name my-project --demo
cd my-project
autoagent status
autoagent build "Build a customer support agent for order tracking, refunds, and cancellations"
```

From there you can stay entirely inside the workspace:

```bash
autoagent eval run
autoagent review
autoagent deploy canary
```

The full walkthrough, including config import, selectors, `--json`, transcript intelligence, MCP setup, and mode control, lives in [docs/DETAILED_GUIDE.md](docs/DETAILED_GUIDE.md).

## Full repo quick start

```bash
git clone <repo-url> autoagent-vnextcc
cd autoagent-vnextcc
./setup.sh   # one-time setup (≈2 min)
./start.sh   # start everything + open browser
```

That's it. No manual venv activation, no config editing required — it works in mock mode with no API keys.

### Prerequisites

| Tool | Version | How to get it |
|------|---------|--------------|
| Python | 3.11+ | [python.org/downloads](https://python.org/downloads) |
| Node.js | 18+ | [nodejs.org](https://nodejs.org) |

> **Never used Python virtual environments?** No problem — `setup.sh` handles the venv for you automatically.

---

### What each script does

**`./setup.sh`** — Run once when you first clone the repo:
- Checks Python 3.11+ and Node 18+ are installed (with clear errors if not)
- Creates a `.venv` Python virtual environment
- Installs all Python and frontend (npm) dependencies
- Copies `.env.example` to `.env`
- Seeds demo data (conversations, traces, optimization history)
- Prints next steps when done

**`./start.sh`** — Run every time you want to use AutoAgent:
- Activates the venv and starts the FastAPI backend (port 8000)
- Starts the Vite frontend dev server (port 5173)
- Waits for both to be healthy before reporting ready
- Opens `http://localhost:5173` in your browser automatically
- Handles Ctrl+C cleanly — kills both processes

**`./stop.sh`** — Shut everything down:
- Stops backend and frontend processes
- Falls back to killing by port if pid files are missing

---

### What you'll see on first run

```
  ┌─────────────────────────────────────────────────────────┐
  │   AutoAgent  ·  Agent Optimization Platform             │
  │   First-time setup                                      │
  └─────────────────────────────────────────────────────────┘

  ◆ Checking Python version
  ✓  Python 3.11.9
  ◆ Checking Node.js version
  ✓  Node.js v20.11.0
  ◆ Setting up Python virtual environment
  ✓  Created .venv
  ◆ Installing Python dependencies
  ✓  Python dependencies installed
  ◆ Installing frontend dependencies
  ✓  Frontend dependencies installed
  ◆ Configuring environment
  ✓  Created .env from .env.example
  ◆ Seeding demo data
  ✓  Demo data seeded

  ✓  Setup complete in 47s

  What's next:
    ./start.sh   Start AutoAgent (backend + frontend)
```

Then `./start.sh` opens the dashboard automatically. You'll land on a dashboard pre-loaded with synthetic agent conversations, failure traces, and an optimization history — ready to explore without any real API keys.

---

### API keys (optional)

The platform runs in **mock mode** by default — all optimization cycles use deterministic mock responses. To run live optimization, add at least one key to `.env`:

```bash
ANTHROPIC_API_KEY=sk-ant-...   # Claude models
OPENAI_API_KEY=sk-...          # GPT models
GOOGLE_API_KEY=AI...           # Gemini models
```

---

### Troubleshooting

**`./setup.sh: Permission denied`**
```bash
chmod +x setup.sh start.sh stop.sh
./setup.sh
```

**`Python 3.11+ required`**
macOS ships with Python 3.9. Install a newer version:
```bash
brew install python@3.12   # Homebrew
# or download from https://python.org/downloads
```

**`Node.js 18+ required`**
```bash
brew install node          # Homebrew
# or use nvm: nvm install 20 && nvm use 20
```

**Port already in use**
```bash
./stop.sh           # kills previous AutoAgent processes
./start.sh          # start fresh
```

**Backend starts but frontend doesn't load**
```bash
cat .autoagent/frontend.log   # check for npm errors
cd web && npm install         # reinstall deps if needed
```

**`ModuleNotFoundError` on backend start**
```bash
source .venv/bin/activate
pip install -e '.[dev]'
```

---

### Or try the 5-minute demo

```bash
source .venv/bin/activate
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

Seven evaluation modes (deterministic, similarity, rubric-based, LLM-judged, audit judge, multi-set, and adversarial) with support for training, validation, holdout, and adversarial splits. Bootstrap confidence intervals and sequential testing provide statistical rigor. Anti-Goodhart guards — holdout rotation, drift detection, variance bounds — prevent overfitting to your eval set.

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

Versioned CRUD for skills, policies, tool contracts, and handoff schemas. SQLite-backed with import/export, search, and version diffing. Skills are defined in Markdown, vector-indexed for search, and composable.

### Intelligence studio

Upload transcript archives (ZIP with JSON/CSV/TXT) and get automatic analytics: intent classification, transfer reason analysis, procedure extraction, FAQ generation, and Q&A over conversation data. One-click agent generation from conversation patterns.

### Assistant builder

Chat-based agent building from natural language descriptions. Supports multi-modal ingestion (transcripts, SOPs, audio, images), intent extraction, journey mapping, and auto-generated tools and escalation logic. Output includes a full agent config, eval pack, and skill set.

### Curriculum learning

Automatically generate training curricula from failure patterns. Use `curriculum generate` to build targeted test cases from observed failure clusters, then `curriculum apply` to add them to your active eval set.

### Adversarial simulation

Stress-test agents against synthetic attack vectors before promoting mutations. The adversarial harness generates persona-driven hostile inputs and tracks maximum tolerable performance drops per cycle.

### Reward engineering

Define reward functions from plain English descriptions and learn from human preference signals. The reward studio supports preference collection, multi-objective scalarization, and reward auditing to detect misaligned signals before they corrupt the optimization target.

### Reinforcement learning pipeline

End-to-end RL training loop: `rl train` to kick off a run, `rl jobs` to monitor progress, `rl eval` to benchmark trained checkpoints, `rl promote` to push a winner, `rl rollback` for safety, and `rl canary` for staged RL rollouts.

### Human escape hatches

```bash
autoagent pause                    # Pause the optimization loop
autoagent resume                   # Resume
autoagent pin <surface>            # Lock a surface from mutation
autoagent unpin <surface>          # Unlock
autoagent reject <experiment-id>   # Reject and rollback an experiment
autoagent full-auto --yes          # Fully autonomous mode (no confirmation gates)
```

### Cost controls

Per-cycle and daily budget tracking. The loop halts when spend limits are hit. Diminishing returns detection stops wasting cycles when the Pareto frontier stalls.

### Multi-tenancy and access control

Teams, environments, and role-based access control (RBAC). Each team gets isolated config history, traces, and registry namespaces. Audit trails log every mutation, deploy, and human override.

---

## Integrations

### Google CX Agent Studio

Bidirectional integration — import CX agents, optimize, export back:

```bash
autoagent cx list                                          # Browse CX agents
autoagent cx import --project my-project --location us-central1
autoagent optimize --cycles 10
autoagent cx export
autoagent cx deploy --environment PROD
autoagent cx status                                        # Check deployment health
autoagent cx widget                                        # Generate embed widget
```

### Google Agent Development Kit (ADK)

Import ADK agents from Python source via AST parsing. Export patches back while preserving developer style and comments. Deploy to Cloud Run or Vertex AI.

```bash
autoagent adk import ./my_agent
autoagent adk diff                  # Preview changes before export
autoagent adk export
autoagent adk deploy
autoagent adk status
```

### MCP server

Model Context Protocol integration for agentic coding tools like Claude Code, Codex, Cursor, and Windsurf.

```bash
# Installed CLI
autoagent mcp-server

# Repo-local fallback
python3 -m mcp_server

# Streamable HTTP mode
python3 -m mcp_server --host 127.0.0.1 --port 8765
```

The live MCP surface now exposes 22 tools, plus prompts and read-only resources. Older docs in this repo that mentioned 10 tools were stale and have been corrected.

Full setup guide:

- [Connecting AutoAgent to Agentic Coding Tools](docs/guides/agentic-coding-tools.md)

Project-scoped Claude Code example (`.mcp.json`):

```json
{
  "mcpServers": {
    "autoagent": {
      "command": "python3",
      "args": ["-m", "mcp_server"]
    }
  }
}
```

### CI/CD

Embed AutoAgent into your existing pipeline via the `cicd` route module. Trigger eval runs on PR, gate deploys on score thresholds, and post experiment cards as PR comments.

### Agent-to-agent (A2A)

AutoAgent speaks the A2A protocol. Route tasks between specialized agents and trace multi-agent conversations as first-class objects.

---

## Web console

Start the server and open `http://localhost:5173`. The console includes 44 pages:

**Observe** — Dashboard with health pulse, journey timeline, and recommendations. Traces viewer with span-level detail. Blame map for failure clustering. Conversation browser with outcome filtering. Event log with real-time SSE stream.

**Optimize** — Trigger optimization cycles, view experiment cards, stream live progress via SSE. AutoFix proposals with apply/reject workflow. Opportunity queue ranked by impact. Change review board with side-by-side diffs.

**Evaluate** — Eval run history with comparison mode. Per-case results with pass/fail breakdown. Judge calibration and drift monitoring. NL scorer studio. Adversarial simulation sandbox.

**Build** — Agent Studio for natural language config edits. Intelligence Studio for transcript-to-agent pipelines. Assistant for chat-based agent building. Builder workspace and demo mode. Knowledge base management.

**Manage** — Config versions with YAML viewer and side-by-side diffs. Registry browser for skills, policies, tools, and handoff schemas. Deploy with canary controls. Loop monitor with watchdog health. Settings.

**Advanced** — What-if scenario analysis. Policy candidates browser. Reward studio and reward audit. Preference inbox. Project memory browser. ADK and CX import/deploy flows. Skills marketplace. Runbooks catalog.

---

## CLI reference

```
autoagent <command> [options]
```

All commands support `--help`. Major commands support `--json` for structured output.

### Core commands

| Command | Purpose |
|---------|---------|
| `init` | Scaffold a new project |
| `build` | Build an agent interactively |
| `quickstart` | Run the full golden path |
| `server` | Start the API server and web console |
| `mcp-server` | Start the MCP server for AI coding assistants |
| `status` | Health check with metrics |
| `doctor` | Diagnose installation and config issues |
| `full-auto --yes` | Fully autonomous optimization (no gates) |

### Optimization

| Command | Purpose |
|---------|---------|
| `optimize` | Run optimization cycles |
| `loop` | Start continuous optimization |
| `pause` / `resume` | Human control over the loop |
| `pin <surface>` / `unpin` | Lock/unlock config surfaces |
| `reject <id>` | Reject and rollback an experiment |
| `edit` | Apply a natural language config edit |
| `explain` | Explain current agent config in plain English |

### Evaluation

| Command | Purpose |
|---------|---------|
| `eval run` | Run an evaluation suite |
| `eval results [--run-id ID]` | Get results for a specific run |
| `eval list` | List all eval runs |
| `replay` | Replay a trace against the current agent |
| `diagnose` | Interactive failure diagnosis |
| `benchmark run` | Run a benchmark dataset |

### Trace analysis

| Command | Purpose |
|---------|---------|
| `trace grade <id>` | Grade spans in a trace |
| `trace blame [--window 24h]` | Failure clustering with root cause |
| `trace graph <id>` | Dependency graph visualization |
| `trace promote <id>` | Promote a high-quality trace to eval set |
| `logs [--limit N] [--outcome fail]` | View conversation logs |

### Deployment and config

| Command | Purpose |
|---------|---------|
| `deploy` | Deploy a config version (canary or immediate) |
| `config list/show/diff/migrate` | Manage config versions |
| `release list/create` | Release management |
| `changes list/show/approve/reject/export` | Propose and review changes |
| `review list/show/apply/reject/export` | Experiment card review |

### Subsystems

| Command | Purpose |
|---------|---------|
| `autofix suggest/apply/history` | AI-powered failure fixes |
| `judges list/calibrate/drift` | Judge stack operations |
| `context analyze/simulate/report` | Context window diagnostics |
| `scorer create/list/show/refine/test` | NL scorer generation |
| `skill list/create/compose/export-md/import-md` | Executable optimization strategies |
| `runbook list/show/apply/create` | Curated fix bundles |
| `registry list/show/add/diff/import` | Skills, policies, tools, handoffs |
| `curriculum generate/list/apply` | Curriculum learning from failures |
| `memory show/add` | Project optimization memory |

### Data and learning

| Command | Purpose |
|---------|---------|
| `dataset create/list/stats` | Dataset management |
| `outcomes import` | Import outcome labels |
| `reward create/list/test` | Reward function engineering |
| `rl train/jobs/eval/promote/rollback/dataset/canary` | Reinforcement learning pipeline |
| `pref collect/export` | Human preference collection |

### Integrations

| Command | Purpose |
|---------|---------|
| `cx compat/list/import/export/deploy/widget/status` | CX Agent Studio |
| `adk import/export/deploy/status/diff` | Google ADK |

### Run group (pipeline shortcuts)

| Command | Purpose |
|---------|---------|
| `run agent` | Run agent on a single input |
| `run eval` | Run eval suite inline |
| `run observe` | Run agent and capture trace |
| `run optimize` | Run one optimization cycle |
| `run loop` | Start the full optimization loop |
| `run status` | Show current loop status |

See [docs/cli-reference.md](docs/cli-reference.md) for the full reference.

### Demo commands

| Command | Purpose |
|---------|---------|
| `demo vp [--company NAME] [--web]` | 5-minute executive demo |
| `demo quickstart [--dir PATH]` | Guided quickstart walkthrough |

---

## API

200+ endpoints across 47 route modules. OpenAPI docs are served at `/docs`.

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
POST   /api/rewards/create             Create a reward function
GET    /api/curriculum/list            List curriculum sets
POST   /api/sandbox/run                Run adversarial simulation
GET    /api/what-if/analyze            What-if scenario analysis
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
  bandit_policy: thompson             # thompson | ucb1
  search_max_candidates: 10          # Mutations evaluated per cycle
  search_max_cost_dollars: 1.0       # Per-cycle LLM budget
  holdout_rotation_interval: 5       # Rotate holdout every N cycles
  drift_threshold: 0.12              # Judge drift detection threshold
  adversarial_simulation_enabled: true
  adversarial_simulation_cases: 30
  skill_autolearn_enabled: true

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
  cron: "*/5 * * * *"
  checkpoint_path: .autoagent/loop_checkpoint.json
  watchdog_timeout_seconds: 300

eval:
  significance_alpha: 0.05
  significance_iterations: 2000
  cache_enabled: true

human_control:
  immutable_surfaces: ["safety_instructions"]
```

### Environment variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `GOOGLE_API_KEY` | For Gemini models | Google AI API key |
| `OPENAI_API_KEY` | For OpenAI models | OpenAI API key |
| `ANTHROPIC_API_KEY` | For Anthropic models | Anthropic API key |
| `AUTOAGENT_DB` | Optional | Conversation store path |
| `AUTOAGENT_TRACE_DB` | Optional | Trace database path |
| `AUTOAGENT_REGISTRY_DB` | Optional | Registry database path |
| `AUTOAGENT_MEMORY_DB` | Optional | Optimization memory path |

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
├── agent_skills/    Agent-specific skill generation and gap analysis
├── api/             FastAPI server (47 route modules, 200+ endpoints)
├── assistant/       Chat-based agent builder with card rendering
├── adk/             Google ADK integration (21 modules, AST-based import/export)
├── builder/         Agent builder orchestration and workspace
├── cicd/            CI/CD pipeline integration
├── cli/             CLI command modules
├── collaboration/   Team collaboration features
├── context/         Context engineering workbench (7 modules)
├── control/         Human control gates and governance
├── core/            Shared domain types and skills system
├── cx_studio/       Google CX Agent Studio integration (12 modules)
├── deployer/        Canary deployment and release management
├── evals/           Evaluation runner, scoring, datasets, replay (25 modules)
├── graders/         Tiered grading pipeline
├── judges/          Judge stack with versioning and calibration (15 modules)
├── logger/          Conversation persistence and structured logging
├── mcp_server/      Model Context Protocol server (8 modules)
├── multi_agent/     Agent-to-agent (A2A) coordination
├── notifications/   Alert and notification delivery
├── observer/        Trace analysis, blame maps, anomaly detection (18 modules)
├── optimizer/       Optimization loop, mutations, search strategies (40+ modules)
├── policy_opt/      Policy search and evaluation
├── registry/        Versioned skills, policies, tools, handoffs (17 modules)
├── rewards/         Reward engineering and preference learning
├── simulator/       Adversarial simulation sandbox (5 modules)
├── tests/           Test suite (179 files, 1131+ tests)
├── web/             React + TypeScript frontend (44 pages)
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
- **Testing**: pytest (179 files, 1131+ tests), Playwright (E2E)
- **Observability**: OpenTelemetry (OTEL) for distributed tracing

---

## Documentation

**Start here:**
- [Platform Overview](docs/platform-overview.md) — Full walkthrough of every subsystem and feature
- [Architecture and Process Diagrams](docs/architecture-diagram.md) — Visual guide to system design and data flow

**Guides:**
- [Getting Started](docs/getting-started.md)
- [Quick Start](docs/QUICKSTART_GUIDE.md) | [Detailed Guide](docs/DETAILED_GUIDE.md)
- [Agentic Coding Tools Guide](docs/guides/agentic-coding-tools.md)
- [Concepts](docs/concepts.md)
- [CLI Reference](docs/cli-reference.md)
- [API Reference](docs/api-reference.md)
- [Deployment Guide](docs/deployment.md)

**Feature deep dives:** [AutoFix](docs/features/autofix.md) | [Judge Ops](docs/features/judge-ops.md) | [Context Workbench](docs/features/context-workbench.md) | [Prompt Optimization](docs/features/prompt-optimization.md) | [Registry](docs/features/registry.md) | [Trace Grading](docs/features/trace-grading.md) | [NL Scorer](docs/features/nl-scorer.md)

**Integrations:** [CX Agent Studio](docs/cx-agent-studio.md) | [MCP Integration](docs/mcp-integration.md) | [Agentic Coding Tools](docs/guides/agentic-coding-tools.md)

---

## License

Apache 2.0
