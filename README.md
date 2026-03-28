# AutoAgent

**Continuous optimization for AI agents.** Trace, evaluate, improve, deploy — in a loop.

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB)
![Tests](https://img.shields.io/badge/tests-2546%20passing-22C55E)
![License](https://img.shields.io/badge/license-Apache%202.0-111827)

AutoAgent watches your agent in production, diagnoses failures, proposes fixes, evaluates them with statistical rigor, and deploys improvements — automatically. Built on Google ADK, with first-class support for CX Agent Studio, Vertex AI Agent Engine, and the A2A protocol.

```
Trace → Diagnose → Search → Evaluate → Gate → Deploy → Learn → Repeat
```

---

## Quick start

```bash
# Install
pip install -e ".[dev]"

# Create a new agent project
autoagent init --template customer-support

# Start the web console
autoagent server  # → http://localhost:8000

# Run the optimization loop
autoagent loop --max-cycles 20 --stop-on-plateau
```

**See it in action** — the VP demo runs a curated scenario that takes an agent from 0.62 to 0.87 health score in three optimization cycles:

```bash
autoagent demo vp --company "Acme Corp" --web
```

---

## How it works

AutoAgent runs a closed-loop optimization cycle:

1. **Trace** — Collect structured events from every agent invocation
2. **Diagnose** — Cluster failures, detect anomalies, rank opportunities
3. **Search** — Generate typed mutations (instruction rewrites, routing fixes, tool changes)
4. **Evaluate** — Replay with side-effect isolation, grade with a multi-judge stack
5. **Gate** — Hard safety constraints first, then optimize objectives
6. **Deploy** — Canary rollout with experiment card tracking
7. **Learn** — Record what worked, retire what didn't
8. **Repeat**

Each cycle produces a reviewable experiment card. Safety gates are never traded off against performance. The loop runs unattended or you intervene at any point.

---

## Core concepts

### ADK-native runtime

Google ADK is the canonical agent model. Every agent maps to ADK types (`LlmAgent`, `SequentialAgent`, `ParallelAgent`, `LoopAgent`), and all mutations operate on ADK-native constructs: `instruction`, `tools`, `sub_agents`, `generation_config`, and callbacks.

```bash
# Scaffold a runnable ADK project
autoagent init --template customer-support

# Import an existing ADK agent
autoagent adk import ./my-agent

# Export optimized config back to ADK source
autoagent adk export --output ./my-agent
```

The internal model tracks a `cx_portable` flag on every construct, so you always know whether your agent can deploy to both ADK and CX Agent Studio.

### Dual-target deployment

Agents that stay within the CX-portable subset deploy to either target:

| Target | Command | What it does |
|--------|---------|--------------|
| **CX Agent Studio** | `autoagent cx deploy` | Maps to CX Agent resources via `ces.googleapis.com` |
| **Vertex AI Agent Engine** | `autoagent deploy vertex` | Source-file deploy with auto-scaling and Memory Bank |
| **Cloud Run** | `autoagent adk deploy --target cloud-run` | Container deployment |
| **Local** | `adk web` or `adk run` | Run directly with the ADK CLI |

```bash
# Check what's portable before you build
autoagent cx compat

# Deploy to CX Agent Studio with versioning
autoagent cx deploy --target web-widget
```

### SKILL.md portable format

Skills use the SKILL.md format — the cross-platform standard used by Claude Code, Codex, Cursor, and ADK. YAML frontmatter for machine-readable metadata, markdown body for instructions.

```bash
# Export a skill as SKILL.md
autoagent skill export-md routing-optimizer

# Import from the ecosystem
autoagent skill import-md ./skills/safety-hardening/

# Create a new skill from a description
autoagent skill create "Detect and fix billing misroutes"
```

Skills are typed as `build-time` (optimization strategies) or `run-time` (agent capabilities), with eval contracts, trust levels, and provenance tracking.

### Evaluation system

Every agent ships with a complete eval pack. AutoAgent separates trajectory evaluation (was the process correct?) from outcome evaluation (is the final state correct?):

```bash
# Run evaluations
autoagent eval run

# Run against standard benchmarks
autoagent benchmark run tau2-bench --cycles 5

# Promote a production trace to an eval case
autoagent trace promote <trace-id>
```

The trace-to-eval pipeline automatically flags interesting production traces (failures, edge cases, high latency) and converts them into regression test cases. Your eval dataset grows from production experience.

### Dataset service

All data flows through a unified dataset service with immutable version pinning:

```bash
# Create and version a dataset
autoagent dataset create --name customer-support-v1
autoagent dataset import --from-traces --last 7d

# Pin all dimensions for reproducibility
# dataset version + grader version + judge version + model version
autoagent dataset stats
```

Every experiment pins a specific dataset version, grader version, judge version, and model version. Full reproducibility.

### Permission model

Three-tier permissions replace "dangerous full-auto" with scoped autonomy:

| Tier | What it can do |
|------|---------------|
| **Inspect** | Read-only observation of traces, metrics, configs |
| **Mutate** | Propose and test changes in sandboxed environments |
| **Promote** | Deploy changes to production |

```bash
# Run with scoped autonomy
autoagent autonomous --scope dev

# Set permission profile
autoagent config set permission_profile staging
```

Permissions are enforced per-skill, per-tool, and per-environment. Eval runs never touch production APIs unless explicitly allowlisted.

---

## Observability

### OpenTelemetry native

All traces export using OTel GenAI semantic conventions (`gen_ai.*` namespace). Connect to any OTel-compatible backend:

```yaml
# autoagent.yaml
observability:
  otel_enabled: true
  otel_exporter: otlp_http
  otel_endpoint: http://localhost:4318
  otel_service_name: my-agent
```

Defaults to Cloud Trace for Vertex AI deployments. Instruments LLM calls (tokens, latency, cost), ADK session lifecycle, state deltas, callback decisions, and memory operations.

### Platform integrations

Direct export to leading observability platforms:

```yaml
observability:
  export_to: [langfuse, braintrust, wandb]
```

Bi-directional sync where supported — import eval results from external platforms back into AutoAgent.

### Business-outcome joins

Ground the optimization loop in real-world outcomes:

```bash
# Import business outcomes
autoagent outcomes import --source crm

# Webhook for real-time outcome ingestion
# POST /api/outcomes/webhook
```

Join traces to business events (CSAT, NPS, resolution rate, churn) hours or days later. Auto-recalibrate judges when their scores diverge from business outcomes.

---

## Agent-to-Agent protocol

AutoAgent implements Google's A2A protocol alongside MCP:

- **A2A server** — expose agents as discoverable services with Agent Cards at `/.well-known/agent-card.json`
- **A2A client** — discover and invoke external A2A agents from within workflows
- **MCP server** — 20 tools for AI coding assistants, plus Resources and Prompts

```bash
# Start MCP server (stdio + Streamable HTTP)
autoagent mcp-server

# A2A discovery
curl http://localhost:8000/.well-known/agent-card.json
```

The MCP server includes project file generation (`CLAUDE.md`, `AGENTS.md`) that auto-updates when your project structure changes.

---

## Guardrails

Composable guardrail primitives that run in parallel with agent execution:

```python
# Built-in guardrails
PiiDetectionGuardrail()       # Email, phone, SSN, credit card
ToxicityGuardrail()           # Configurable keyword filtering
TopicRestrictionGuardrail()   # Operator-defined topic boundaries
OutputFormatGuardrail()       # JSON validity, length, regex
PromptInjectionGuardrail()    # Jailbreak and injection patterns
```

Guardrails are attachable to any agent in the hierarchy with inheritance — parent guardrails apply to all children. They map to ADK callbacks for native enforcement.

---

## Judge governance

Multi-judge evaluation with full governance:

- **Panel judges** — multiple judges vote, with agreement metrics and tie-breaking
- **Pairwise judges** — "which response is better?" for relative ranking
- **Domain routing** — safety evaluations route to safety judges, quality to quality judges
- **Accuracy benchmarks** — continuously measure judge accuracy against human gold standards
- **Drift detection** — flag when judge scores diverge from human baselines

```bash
autoagent judges calibrate --judge safety-judge
autoagent judges drift --window 7d
```

---

## Multi-agent optimization

Optimize not just single agents, but entire multi-agent systems:

- **Topology search** — discover better agent architectures (ADAS pattern, ICLR 2025)
- **Blame maps** — attribute failures to specific agents in the hierarchy
- **Agent teams** — peer-to-peer optimization where agents share findings
- **Per-agent metrics** — routing accuracy, tool correctness, handoff fidelity per agent

---

## Signed releases

Every deployment produces an immutable, signed release object with complete lineage:

```bash
autoagent release create --sign
autoagent release verify <release-id>
autoagent release rollback <release-id>
```

Each release bundles: code diff, config diff, dataset version, eval results, grader/judge versions, risk class, approval chain, canary plan, and rollback instructions. Full lineage from requirement through to business outcome.

---

## CLI reference

113 commands across 35+ groups:

| Group | Purpose |
|-------|---------|
| `init` | Scaffold new ADK agent project with archetype templates |
| `eval` | Run evaluations, view results, manage datasets |
| `optimize` | Single-cycle or continuous optimization |
| `deploy` | Canary deployment with experiment tracking |
| `loop` | Continuous unattended optimization |
| `trace` | Trace analysis, blame maps, promotion to eval cases |
| `skill` | SKILL.md management, import/export, synthesis |
| `dataset` | Create, version, split, and manage datasets |
| `benchmark` | Run against standard benchmarks (tau2-bench, WebArena) |
| `outcomes` | Import and manage business outcomes |
| `release` | Create, sign, verify, and rollback releases |
| `cx` | CX Agent Studio import/export/deploy/compat |
| `adk` | ADK import/export/deploy |
| `autonomous` | Scoped autonomous operation |
| `scorer` | Natural language to eval scorer generation |
| `judges` | Judge calibration, drift, governance |
| `registry` | Skills, policies, tool contracts, handoff schemas |
| `review` | Change review and approval workflow |
| `runbook` | Curated fix bundles with one-click apply |
| `diagnose` | Interactive failure diagnosis with chat |
| `edit` | Natural language config edits |
| `server` | Start API + web console |
| `mcp-server` | Model Context Protocol server |

All commands support `--help`. Most support `--json` for structured output.

---

## Web console

42 pages served at `http://localhost:8000`:

| Page | What it shows |
|------|--------------|
| **Dashboard** | Health pulse, metric summary, journey timeline, recommendations |
| **Agent Studio** | Conversational agent building interface |
| **Intelligence Studio** | Transcript archive analysis and agent generation |
| **Eval Runs / Detail** | Evaluation history with per-case breakdown |
| **Live Optimize** | Real-time optimization with SSE streaming |
| **Experiments** | Reviewable experiment cards with diffs and statistics |
| **Traces / Blame Map** | Span-level trace analysis and failure clustering |
| **Configs** | Version list, YAML viewer, side-by-side diff |
| **Deploy** | Canary status, promote/rollback, deployment history |
| **Skills / Registry** | Skill management with recommendation engine |
| **Judge Ops** | Judge versions, calibration, drift monitoring |
| **Context Workbench** | Context window analysis and compaction simulation |
| **Sandbox / What-If** | Simulation and counterfactual testing |

---

## API

250+ endpoints across 43 route modules. Key endpoints:

```
POST   /api/eval/run                 Run evaluation suite
POST   /api/optimize/run             Run optimization cycle
GET    /api/optimize/stream          SSE for live optimization progress
GET    /api/experiments              List experiment cards
POST   /api/deploy/deploy            Deploy with canary strategy
GET    /api/traces/blame             Failure clustering and blame map

POST   /api/datasets                 Create dataset
POST   /api/datasets/{id}/version    Create immutable snapshot
POST   /api/outcomes                 Ingest business outcome
POST   /api/outcomes/webhook         Real-time outcome ingestion

POST   /api/adk/import               Import ADK agent
POST   /api/cx/import                Import CX Agent Studio agent
GET    /.well-known/agent-card.json  A2A agent card
POST   /api/a2a/tasks/send           A2A task submission

GET    /api/health                   Health check
WS     /ws                           Real-time updates
```

---

## Configuration

Everything is driven by `autoagent.yaml`:

```yaml
optimizer:
  strategy: round_robin           # round_robin | simple | adaptive | full
  search_strategy: simple         # simple | adaptive | full | pro
  bandit_policy: thompson         # ucb1 | thompson
  search_max_candidates: 10
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

eval:
  history_db_path: eval_history.db
  significance_alpha: 0.05

budget:
  per_cycle_dollars: 1.0
  daily_dollars: 10.0

human_control:
  permission_profile: dev         # readonly | dev | staging | production | autonomous
  side_effect_isolation: true
  immutable_surfaces: ["safety_instructions"]

observability:
  otel_enabled: false
  otel_exporter: otlp_http
  otel_endpoint: http://localhost:4318
```

---

## Deploy

### Docker

```bash
docker build -t autoagent .
docker run -p 8000:8000 -e GOOGLE_API_KEY="..." autoagent
```

### Google Cloud Run

```bash
export PROJECT_ID="your-project"
export REGION="us-central1"
./deploy/deploy.sh $PROJECT_ID $REGION
```

### Vertex AI Agent Engine

```bash
autoagent deploy vertex --project your-project --region us-central1
```

### Fly.io

```bash
fly launch --name autoagent --no-deploy
fly secrets set GOOGLE_API_KEY="..."
fly deploy
```

For detailed deployment instructions including secrets management, custom domains, and troubleshooting, see [docs/deployment.md](docs/deployment.md).

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                  Operator interfaces                  │
│           CLI  ·  REST API  ·  Web console            │
└─────────────────────────┬────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          │               │               │
    ┌─────▼─────┐  ┌──────▼──────┐  ┌─────▼─────┐
    │  Observer  │  │  Optimizer  │  │  Deployer  │
    │  traces    │  │  mutations  │  │  canary    │
    │  blame     │  │  search     │  │  releases  │
    │  anomaly   │  │  skills     │  │  versions  │
    └─────┬─────┘  └──────┬──────┘  └─────┬─────┘
          │               │               │
    ┌─────▼───────────────▼───────────────▼─────┐
    │              Evaluation layer              │
    │  judges · graders · benchmarks · datasets  │
    └─────────────────────┬─────────────────────┘
                          │
    ┌─────────────────────▼─────────────────────┐
    │             Integration layer              │
    │  ADK · CX Studio · A2A · MCP · OTel       │
    └─────────────────────┬─────────────────────┘
                          │
    ┌─────────────────────▼─────────────────────┐
    │            Persistence layer               │
    │         SQLite · YAML · JSON               │
    └───────────────────────────────────────────┘
```

### Repository structure

```
agent/              ADK agent runtime, config, tools, specialists
agent_skills/       Skill generation, gap analysis, browser skills
a2a/                Agent-to-Agent protocol (server, client, agent cards)
adk/                ADK integration (import, export, deploy, scaffold, state, identity)
api/                FastAPI server, 43 route modules, auth, billing, RBAC
assistant/          NL agent builder, archetypes, eval pack generation
cicd/               CI/CD gate integration
cli/                Click CLI commands
collaboration/      Team collaboration
configs/            Versioned agent configurations
context/            Memory management, retention, freshness, artifact browsing
control/            Permissions, governance, audit logging
core/               Domain types, guardrails, guardrail library, unified skills
cx_studio/          CX Agent Studio (import, export, deploy, versions, eval sync)
data/               Dataset service, outcomes, repositories, training export
deploy/             Docker, Cloud Run, deployment scripts
deployer/           Release objects, signing, lineage, canary
docs/               User guides, architecture, references
evals/              Runner, trajectory/outcome eval, benchmarks, trace converter
graders/            Tiered grading pipeline
judges/             Governance, panel, pairwise, routing, drift, calibration
logger/             Structured logging, conversation store
mcp_server/         MCP server (tools, resources, prompts, transport, project files)
multi_agent/        Patterns, teams, blame maps, impact analysis
notifications/      Alert system
observer/           Traces, OTel adapter, exporters, platform integrations, promoter
optimizer/          Loop, mutations, search, ADAS, distillation, constitutional AI
registry/           Skills, SKILL.md, vector store, supply chain, static analysis
simulator/          Sandbox, personas, adversarial harness, attack vectors
tests/              136 test files, 2546 tests
web/                React + TypeScript + Tailwind frontend (42 pages)
```

---

## By the numbers

| Metric | Value |
|--------|-------|
| Tests | 2,546 across 136 files |
| Python backend | ~92,000 lines |
| React frontend | ~20,500 lines |
| CLI commands | 113 |
| API endpoints | 250+ across 43 route modules |
| Web pages | 42 |
| Top-level packages | 33 |

---

## Documentation

- [Architecture Overview](ARCHITECTURE_OVERVIEW.md)
- [Getting Started](docs/getting-started.md)
- [Concepts](docs/concepts.md)
- [CLI Reference](docs/cli-reference.md)
- [API Reference](docs/api-reference.md)
- [Deployment Guide](docs/deployment.md)
- Features: [AutoFix](docs/features/autofix.md) · [Judge Ops](docs/features/judge-ops.md) · [Context Workbench](docs/features/context-workbench.md) · [Prompt Optimization](docs/features/prompt-optimization.md) · [Registry](docs/features/registry.md) · [Trace Grading](docs/features/trace-grading.md) · [NL Scorer](docs/features/nl-scorer.md)

---

## Tech stack

**Backend:** Python 3.11+, FastAPI, Uvicorn, SQLite, Click
**Frontend:** React 19, Vite, TypeScript, Tailwind CSS, Zustand, Recharts
**Integrations:** Google ADK, CX Agent Studio, Vertex AI, A2A, MCP, OpenTelemetry
**Testing:** pytest with 2,546 tests

---

## License

Apache 2.0
