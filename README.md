# AgentLab

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB)
![Test Suite](https://img.shields.io/badge/test%20suite-pytest%20%2B%20vite-22C55E)
![License](https://img.shields.io/badge/license-Apache%202.0-111827)

AgentLab is a local-first toolkit for iterating on AI agent configurations. Give it an agent, define eval cases that describe what "good" looks like, and AgentLab runs an inspectable Build -> Workbench -> Eval -> Compare -> Optimize -> Review -> Deploy loop. It works with agents you import (OpenAI Agents, Anthropic, HTTP endpoints, Google CX) and agents you build from scratch.

```text
BUILD -> WORKBENCH -> EVAL -> COMPARE -> OPTIMIZE -> REVIEW -> DEPLOY
```

> **[Workbench Guide](docs/WORKBENCH_GUIDE.md)** — End-to-end walkthrough of the Claude-Code-style Workbench (build → eval → optimize → deploy, plan mode, checkpoints, multi-turn memory, /diff and /accept)
>
> **[Quick Start](docs/QUICKSTART_GUIDE.md)** — Get a workspace running in minutes
>
> **[Detailed Guide](docs/DETAILED_GUIDE.md)** — Full CLI walkthrough, including XML instructions and deployment
>
> **[Claude-Style Auto Mode](docs/guides/claude-style-auto-mode.md)** — Live terminal harness, queued input, permissions, and full-auto workflows
>
> **[UI Quick Start](docs/UI_QUICKSTART_GUIDE.md)** — Browser walkthrough for the current web console
>
> **[Platform Overview](docs/platform-overview.md)** — Product and architecture map

---

## How It Works

AgentLab centers everything around a closed improvement loop:

1. **Build** — create or refine agent configs (prompts, tools, guardrails) and starter evals
2. **Workbench** — inspect a candidate build as a live plan, artifacts, validation, and Eval handoff
3. **Eval** — run the current config against a suite of test cases and score the results
4. **Compare** — inspect run-to-run deltas and case-level changes
5. **Optimize** — generate and test targeted prompt/config changes to improve scores
6. **Review** — accept or reject proposed changes before they go live
7. **Deploy** — canary, release, rollback, or push through an integration target

The CLI, API, and web console all work off the same local workspace state, so you can move between surfaces without losing context.

---

## Install

```bash
git clone https://github.com/andrewhuot/agentlab.git agentlab
cd agentlab
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

> **Note:** Older `autoagent-vnextcc` clone URLs currently resolve to the same repository, but `agentlab` is the canonical repo name for new installs.

### Prerequisites

| Tool | Version | Why you need it |
|------|---------|-----------------|
| Python | 3.11+ | CLI, API, eval, and optimization runtime |
| Node.js | 20+ | Web console dev mode (`./start.sh`, `npm run dev`, `npm run build`) |
| `gcloud` | optional | CX / Google Cloud integration flows |
| `google-auth` | optional Python package | Required only for CX commands such as `agentlab cx auth` and `agentlab cx list` |

### API keys

AgentLab is live-first. New workspaces default to live runtime mode, and provider-backed workflows use real LLM providers once a key is available. Save a key through the CLI:

```bash
agentlab provider configure --provider openai --model gpt-4o --api-key sk-...
```

Or set provider keys in your shell:


```bash
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export GOOGLE_API_KEY=AI...
```

Mock mode remains available when you want deterministic offline exploration:

```bash
agentlab init --mode mock
agentlab mode set mock
```

Run `agentlab doctor` to verify the current mode and provider readiness.

---

## Quick Start

```bash
agentlab new my-agent --template customer-support --demo
cd my-agent
agentlab instruction show
agentlab build "customer support agent for order tracking, refunds, and cancellations"
agentlab eval run
agentlab optimize --cycles 1
agentlab deploy --auto-review --yes
```

Notes:

- `--demo` seeds a friendlier first workspace with review and autofix data so the full loop is exercisable on day one.
- New workspaces start with an XML root instruction by default. XML instructions are a structured prompt format that makes agent instructions machine-editable — the optimizer can make targeted changes to specific sections without rewriting the whole prompt.
- If the starter eval already passes cleanly, `agentlab optimize --cycles 1` may say `Latest eval passed; no optimization needed.` That is expected.
- `agentlab deploy --auto-review --yes` applies pending review items and creates a release. In the demo workspace, seeded review data makes this path exercisable immediately.
- **No API keys?** The Quick Start still works in mock mode. You'll see the full workflow with synthetic scores. Add real API keys later for meaningful results.

If `agentlab` is not found after install, make sure your virtualenv is activated (`source .venv/bin/activate`).

---

## CLI

Default help groups the CLI into **Primary** and **Secondary** commands. Run `agentlab advanced` to see the broader hidden command set.

### Primary commands

| Command | Purpose |
|---------|---------|
| `new` | Create a new workspace from a starter template |
| `build` | Generate or inspect build artifacts |
| `workbench` | Build, inspect, iterate, and materialize a Workbench candidate |
| `eval` | Run evals, inspect results, compare runs, and generate eval suites |
| `optimize` | Run optimization cycles (`--continuous` for loop mode) |
| `deploy` | Canary, release, rollback, or auto-review-and-deploy |
| `status` | Show workspace health, versions, and recommended next steps |
| `doctor` | Check configuration, providers, data stores, and readiness |
| `shell` | Launch the interactive AgentLab shell (legacy; also invoked by `agentlab --classic`) |

### Secondary commands

| Command | Purpose |
|---------|---------|
| `config` | List, diff, import, edit, resolve, rollback, and activate configs |
| `connect` | Import OpenAI Agents, Anthropic, HTTP, or transcript-backed runtimes |
| `instruction` | Show, validate, edit, generate, or migrate XML instructions |
| `memory` | Manage `AGENTLAB.md` project memory |
| `mode` | Show or set mock/live/auto execution mode |
| `model` | Inspect or override proposer/evaluator model preferences |
| `provider` | Configure, list, and test provider profiles |
| `review` | Review, apply, reject, or export proposed config diffs |
| `template` | List and apply bundled starter templates |

All commands support `--help`. See [docs/cli-reference.md](docs/cli-reference.md) for the full reference, including the advanced surface.

### Interactive Workbench (default)

Running `agentlab` with no subcommand launches the **Workbench**, a Claude-Code-style interactive REPL with a live status line, structured terminal panes, streaming transcript, slash-command surface (`/eval`, `/optimize`, `/build`, `/deploy`, `/skills`, `/help`, `/status`, `/model`, `/resume`, `/clear`, …), autocomplete popup, and session persistence. Ctrl-C cancels the active tool call; a second press exits cleanly.

```bash
agentlab            # interactive Workbench (default)
agentlab --classic  # opt out: run the legacy shell REPL (deprecated, one more release)
```

See [docs/cli/workbench.md](docs/cli/workbench.md) for the full slash-command catalog and keyboard reference. The non-interactive `agentlab status` path is still used automatically when stdin is not a TTY (CI, pipes, redirects).

### Claude-style auto mode

Long-running interactive text commands default to `--ui auto`, which opens a Claude Code-inspired live harness in a real terminal and falls back to classic text in CI, pipes, redirects, and structured output modes. Use it for `agentlab shell`, `agentlab optimize`, `agentlab loop run`, and `agentlab full-auto` when you want to watch progress, queue follow-up input, and see the current permission mode while work runs.

See [docs/guides/claude-style-auto-mode.md](docs/guides/claude-style-auto-mode.md) for the end-to-end workflow.

### CLI Workbench

Use the terminal Workbench when you want the Workbench candidate loop without opening the web console:

```bash
agentlab workbench create "Build a refund support agent with PII guardrails"
agentlab workbench build "Build a refund support agent with PII guardrails"
agentlab workbench show
agentlab workbench iterate "Add regression evals for missing-order cases"
agentlab workbench save
agentlab eval run --config <saved-config-path>
```

`agentlab workbench save` materializes the candidate into the normal workspace config path, writes generated eval cases, and sets the saved candidate as the active local config. It does not start Eval or Optimize; Eval still measures the candidate, and Optimize still waits for completed eval evidence.

---

## Key Features

### Core loop

- **Build workspace** — Prompt, transcript, builder chat, and saved artifacts in one place
- **[Agent Builder Workbench](docs/features/workbench.md)** — Live candidate-building harness with plan progress, artifacts, validation, review gate, and Eval handoff
- **Eval runs** — Run suites, inspect historical runs, and drill into case-level results
- **Results Explorer** — Filter failures, annotate examples, export runs, and compare outcomes
- **Compare** — Run or inspect pairwise config comparisons with significance summaries
- **Optimize** — Generate and test targeted prompt/config changes to improve eval scores
- **Improvements** — One review workflow for opportunities, experiments, approvals, and history

### Ecosystem and integrations

- **Connect** — Import existing OpenAI Agents, Anthropic, HTTP, and transcript-backed runtimes
- **CX Studio** — Auth, import, diff, export, and sync Google CX agents from one surface
- **Google ADK** — Import ADK agents, inspect diffs, export patches, deploy
- **MCP server** — 22 tools plus prompts/resources for Claude Code, Codex, Cursor, Windsurf, and other MCP clients
- **XML instructions** — Structured prompt format that makes agent instructions machine-editable for the optimizer
- **NL scorer** — Define eval scoring criteria in natural language instead of code
- **Context workbench** — Inspect token context usage and compaction tradeoffs for agents with large prompts
- **Registry and skills** — Manage reusable skills, policies, tools, and handoffs

---

## Web Console

For the combined app:

```bash
agentlab server
```

Then open `http://localhost:8000`.

For hot-reload local development:

```bash
./start.sh
```

`start.sh` activates the virtualenv, starts the backend, and installs frontend dependencies (`npm install`) automatically if needed.

Then open:

- UI: `http://localhost:5173` (defaults to the Build page; `start.sh` opens the Dashboard)
- API docs: `http://localhost:8000/docs`

The web console has two sidebar modes:

**Simple mode** (default) shows the core loop:

- `Dashboard` — `Setup` — `Build` — `Workbench` — `Eval Runs` — `Results Explorer` — `Compare` — `Optimize Studio` — `Optimize` — `Improvements` — `Deploy` — `Docs`

**Pro mode** adds import/connect surfaces, observability (traces, events, blame map), governance (configs, judge ops, registry, scorer studio), and integration targets (CX, ADK, sandbox, what-if).

Toggle between modes in the sidebar. See [docs/UI_QUICKSTART_GUIDE.md](docs/UI_QUICKSTART_GUIDE.md) for the current browser walkthrough.

---

## Deploy

```bash
# Docker
docker compose up --build -d

# Cloud Run helper
./deploy/deploy.sh "$PROJECT_ID" "$REGION"

# Fly.io
fly launch --name agentlab --region ord && fly deploy
```

See [docs/deployment.md](docs/deployment.md) for local, container, and Cloud Run details.

---

## Documentation

**Start here:**

- [Quick Start](docs/QUICKSTART_GUIDE.md) — Get running in minutes
- [Concepts](docs/concepts.md) — Core terminology and mental model
- [CLI Reference](docs/cli-reference.md) — Full command reference
- [FAQ](docs/faq.md) — Common questions and troubleshooting

**Guides:**

- [Detailed Guide](docs/DETAILED_GUIDE.md) — Full CLI walkthrough
- [CLI Workbench](docs/cli/workbench.md) — Interactive Workbench (default `agentlab` entry), slash-command catalog, and keyboard reference
- [Claude-Style Auto Mode](docs/guides/claude-style-auto-mode.md) — Live terminal harness, queued input, permissions, and full-auto workflows
- [UI Quick Start](docs/UI_QUICKSTART_GUIDE.md) — Browser walkthrough
- [Agentic Coding Tools](docs/guides/agentic-coding-tools.md) — MCP and coding agent setup

**Reference and deep dives:**

- [Platform Overview](docs/platform-overview.md) | [Architecture](docs/architecture.md) | [API Reference](docs/api-reference.md)
- [XML Instructions](docs/xml-instructions.md) | [CX Studio](docs/cx-studio-integration.md) | [MCP Integration](docs/mcp-integration.md) | [Deployment](docs/deployment.md)
- Feature deep dives: [Workbench](docs/features/workbench.md) | [AutoFix](docs/features/autofix.md) | [Judge Ops](docs/features/judge-ops.md) | [Context Workbench](docs/features/context-workbench.md) | [Prompt Optimization](docs/features/prompt-optimization.md) | [Registry](docs/features/registry.md) | [Trace Grading](docs/features/trace-grading.md) | [NL Scorer](docs/features/nl-scorer.md)

---

## License

Apache 2.0
