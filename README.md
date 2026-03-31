# AutoAgent

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB)
![Tests](https://img.shields.io/badge/tests-2986%2B%20passing-22C55E)
![License](https://img.shields.io/badge/license-Apache%202.0-111827)

AutoAgent automatically makes your AI agents better. Give it an agent, tell it what "good" looks like, and it will find failures, generate fixes, test them, and deploy the winners — all in a loop you can watch or walk away from.

```
BUILD → EVAL → OPTIMIZE → DEPLOY → REPEAT
```

> **[Quick Start](docs/QUICKSTART_GUIDE.md)** — Get a working agent in 2 minutes
>
> **[Detailed Guide](docs/DETAILED_GUIDE.md)** — Full walkthrough of every workflow
>
> **[UI Quick Start](docs/UI_QUICKSTART_GUIDE.md)** — Web console walkthrough
>
> **[Platform Overview](docs/platform-overview.md)** — Every subsystem explained

---

## Install

```bash
git clone https://github.com/andrewhuot/autoagent-vnextcc.git
cd autoagent-vnextcc
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Prerequisites

| Tool | Version | How to get it |
|------|---------|--------------|
| Python | 3.11+ | [python.org/downloads](https://python.org/downloads) |
| Node.js | 18+ | [nodejs.org](https://nodejs.org) (for web console) |

### API keys (auto-detect)

AutoAgent auto-detects your environment. If API keys are present, it uses live LLM providers. If not, it falls back to deterministic mock responses — no configuration needed.

To enable live optimization, set at least one key:

```bash
export OPENAI_API_KEY=sk-...          # GPT models
export ANTHROPIC_API_KEY=sk-ant-...   # Claude models
export GOOGLE_API_KEY=AI...           # Gemini models
```

Run `autoagent doctor` to verify your setup.

---

## Quick start

```bash
autoagent new my-agent --template customer-support --demo
cd my-agent
autoagent build "customer support agent for order tracking, refunds, and cancellations"
autoagent eval run
autoagent optimize --cycles 1
autoagent deploy --auto-review --yes
```

That's the fastest reliable first-run loop: create → build → evaluate → optimize → deploy.

`--demo` seeds extra review data so the first-run walkthrough includes review and autofix surfaces on a brand-new workspace.

---

## CLI

AutoAgent shows 16 commands by default (8 primary + 8 secondary). Run `autoagent advanced` for the full list.

### Primary commands

| Command | Purpose |
|---------|---------|
| `new` | Create a new workspace from a starter template |
| `build` | Build agent artifacts or inspect build output |
| `eval` | Evaluate agent configs against test suites |
| `optimize` | Run optimization cycles (`--continuous` for loop mode) |
| `deploy` | Deploy with canary, release, or rollback (`--auto-review` for ship mode) |
| `status` | Show system health, config versions, and recent activity |
| `doctor` | Check system health and configuration |
| `shell` | Launch the interactive AutoAgent shell |

### Secondary commands

| Command | Purpose |
|---------|---------|
| `config` | Manage config versions (list, show, diff, resolve, edit, set-active) |
| `connect` | Import existing runtimes and transcript exports into AutoAgent |
| `memory` | Manage AUTOAGENT.md persistent project context |
| `mode` | Show or set CLI execution mode |
| `model` | Inspect and override model preferences |
| `provider` | Configure and validate provider settings |
| `review` | Review proposed change cards from the optimizer |
| `template` | List and apply starter workspace templates |

All commands support `--help`. Major commands support `--json` for structured output. See [docs/cli-reference.md](docs/cli-reference.md) for the full reference.

---

## How it works

Each optimization cycle:

1. **Trace** — Collects telemetry from agent runs
2. **Diagnose** — Clusters failures, finds root causes
3. **Search** — Generates fix candidates ranked by expected impact
4. **Eval** — Tests fixes against your eval suite with side-effect isolation
5. **Gate** — Enforces hard safety constraints (never traded off for performance)
6. **Deploy** — Promotes winners via canary rollout
7. **Learn** — Records what worked for smarter future searches

Every cycle produces a reviewable **experiment card** — hypothesis, config diff, statistical significance, and rollback instructions. Run `autoagent optimize --continuous` to loop until progress plateaus.

---

## Key features

- **Eval engine** — 7 eval modes, bootstrap CI, sequential testing, anti-Goodhart guards
- **Trace analysis** — Span-level grading, blame maps, opportunity queue
- **Judge stack** — Deterministic → similarity → LLM → audit judge (tiered for cost/accuracy)
- **AutoFix** — AI-generated fix proposals you review before applying
- **NL scorer** — Describe "good" in plain English, get a typed scorer
- **Context workbench** — Diagnose context window issues, simulate compaction
- **Registry** — Version-controlled skills, policies, tools, handoff schemas
- **Intelligence studio** — Upload transcripts → analytics → auto-generate agents
- **Human controls** — Pause, resume, pin, reject, budget caps — you stay in charge
- **Multi-model** — Gemini, GPT-4o, Claude, any OpenAI-compatible provider

---

## Integrations

- **Google CX Agent Studio** — Import, optimize, export, deploy CX agents
- **Google ADK** — Import ADK agents via AST parsing, export patches, deploy to Cloud Run
- **MCP server** — 22 tools for Claude Code, Codex, Cursor, Windsurf ([setup guide](docs/guides/agentic-coding-tools.md))
- **CI/CD** — Gate deploys on eval scores, post experiment cards as PR comments

---

## Web console

Start the combined app with `autoagent server` and open `http://localhost:8000`. For hot-reload local development, run `./start.sh` and open `http://localhost:5173`.

The sidebar toggles between **Simple** and **Pro** views. Simple mode exposes the day-one entry points: Dashboard, Setup, Build, Connect, Eval Runs, Results Explorer, Compare, Optimize, Improvements, and Deploy.

- **Dashboard** — Health, recent activity, next recommended action
- **Build** — Prompt-based agent generation and saved build artifacts
- **Connect** — Import OpenAI Agents, Anthropic, HTTP, or transcript-backed runtimes
- **Eval** — Eval Runs, Results Explorer, and Compare views
- **Optimize** — Trigger cycles, inspect outcomes, and queue follow-up work
- **Review** — Improvements workflow and reviewable change cards
- **Deploy** — Canary rollout, release, rollback

See [UI Quick Start](docs/UI_QUICKSTART_GUIDE.md) for a full walkthrough.

---

## Deploy

```bash
# Docker
docker compose up --build -d

# Google Cloud Run
./deploy/deploy.sh $PROJECT_ID $REGION

# Fly.io
fly launch --name autoagent --region ord && fly deploy
```

See [docs/deployment.md](docs/deployment.md) for detailed setup.

---

## Documentation

**Guides:**
- [Quick Start](docs/QUICKSTART_GUIDE.md) | [Detailed Guide](docs/DETAILED_GUIDE.md) | [UI Quick Start](docs/UI_QUICKSTART_GUIDE.md)
- [Agentic Coding Tools](docs/guides/agentic-coding-tools.md)

**Reference:**
- [CLI Reference](docs/cli-reference.md) | [API Reference](docs/api-reference.md)
- [Concepts](docs/concepts.md) | [FAQ](docs/faq.md)
- [Architecture](docs/architecture.md) | [Diagrams](docs/architecture-diagram.md)

**Feature deep dives:**
[AutoFix](docs/features/autofix.md) | [Judge Ops](docs/features/judge-ops.md) | [Context Workbench](docs/features/context-workbench.md) | [Prompt Optimization](docs/features/prompt-optimization.md) | [Registry](docs/features/registry.md) | [Trace Grading](docs/features/trace-grading.md) | [NL Scorer](docs/features/nl-scorer.md)

**More:**
[Platform Overview](docs/platform-overview.md) | [Deployment](docs/deployment.md) | [Web App Guide](docs/app-guide.md) | [CX Integration](docs/cx-agent-studio.md) | [MCP Integration](docs/mcp-integration.md)

---

## License

Apache 2.0
