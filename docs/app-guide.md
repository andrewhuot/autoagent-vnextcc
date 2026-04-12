# Web App Guide

This guide maps the current AgentLab web console: what routes exist, what each area is for, and how the pages fit together.

It is based on the current React route map in `web/src/App.tsx` and navigation metadata in `web/src/lib/navigation.ts`.

## How to Run the App

The easiest local workflow is:

```bash
./start.sh
```

Manual alternative:

```bash
# backend
agentlab server

# frontend
cd web
npm run dev
```

Open:

- frontend: `http://localhost:5173/dashboard`
- app root: `http://localhost:5173`
- API docs: `http://localhost:8000/docs`

Important behavior:

- the frontend app root `/` redirects to `/build`
- `./start.sh` prints the dashboard URL for convenience

## Current Route Model

The console is grouped into simple-mode core routes plus broader operator and integration routes.

### Home

| Page | Route | Purpose |
|------|-------|---------|
| Dashboard | `/dashboard` | Health, scorecard, recent system state, and next actions |
| Setup | `/setup` | Workspace readiness, mode, doctor findings, data stores, MCP client status |

### Build

| Page | Route | Purpose |
|------|-------|---------|
| Build | `/build` | Prompt-led generation, transcript-led generation, builder chat, saved artifacts, and XML instruction editing |
| Workbench | `/workbench` | Live agent-candidate harness with plan progress, artifacts, validation, review gate, and Eval handoff |

### Import

| Page | Route | Purpose |
|------|-------|---------|
| Connect | `/connect` | Import an OpenAI Agents, Anthropic, HTTP, or transcript-based runtime |
| CX Studio | `/cx/studio` | Authenticate, browse, import, diff, preview, sync, and export CX agents |
| CX Import | `/cx/import` | CX-focused import workflow |
| ADK Import | `/adk/import` | Import a Google Agent Development Kit project |

### Eval

| Page | Route | Purpose |
|------|-------|---------|
| Eval Runs | `/evals` | Launch evals, monitor status, and review run summaries |
| Eval Detail | `/evals/:id` | Inspect one eval run at the per-run detail level |
| Results Explorer | `/results` | Jump into the most recent results view |
| Results Explorer | `/results/:runId` | Inspect examples, filters, annotations, exports, and run diffs |
| Compare | `/compare` | Run and inspect head-to-head comparisons between versions |

### Optimize and Review

| Page | Route | Purpose |
|------|-------|---------|
| Optimize | `/optimize` | Launch optimization cycles and inspect run history |
| Live Optimize | `/live-optimize` | Monitor active optimization work live |
| Improvements | `/improvements` | Unified review workflow for opportunities, experiments, review decisions, and history |

### Deploy

| Page | Route | Purpose |
|------|-------|---------|
| Deploy | `/deploy` | Manage active and canary versions, rollout decisions, and rollback |

### Observe

| Page | Route | Purpose |
|------|-------|---------|
| Conversations | `/conversations` | Browse recorded conversations and outcomes |
| Traces | `/traces` | Inspect trace events and trace-level detail |
| Event Log | `/events` | Review recent system events |
| Blame Map | `/blame` | Inspect failure clustering and likely root causes |
| Context | `/context` | Review context usage and analysis tools |
| Loop Monitor | `/loop` | Watch or control longer-running loop activity |

### Govern

| Page | Route | Purpose |
|------|-------|---------|
| Configs | `/configs` | Browse, diff, and activate config versions |
| Judge Ops | `/judge-ops` | Judge listing, calibration, and drift views |
| Runbooks | `/runbooks` | Explore and apply operational runbooks |
| Skills | `/skills` | Inspect and manage skills |
| Memory | `/memory` | View and edit project memory |
| Registry | `/registry` | Explore reusable registry items |
| Scorer Studio | `/scorer-studio` | Create and refine scorers from natural language |
| Notifications | `/notifications` | Notification history and subscriptions |
| Reward Studio | `/reward-studio` | Reward-related workflows |
| Preference Inbox | `/preference-inbox` | Preference data workflows |
| Policy Candidates | `/policy-candidates` | Policy candidate review |
| Reward Audit | `/reward-audit` | Reward auditing workflows |

### Integrations

| Page | Route | Purpose |
|------|-------|---------|
| CX Deploy | `/cx/deploy` | Push or manage CX deployment flows |
| ADK Deploy | `/adk/deploy` | Push ADK deployment workflows |
| Agent Skills | `/agent-skills` | Generate and manage skill suggestions from runtime gaps |
| Sandbox | `/sandbox` | Run controlled test or replay workflows |
| What-If | `/what-if` | Replay and comparison-style what-if analysis |
| Knowledge | `/knowledge` | Mine and review reusable knowledge patterns |

### Settings

| Page | Route | Purpose |
|------|-------|---------|
| Settings | `/settings` | Shortcut reference, path reference, and documentation links |

## Core First-Run Flow

If you are opening the UI for the first time, this is the cleanest order:

1. **Setup** to confirm the workspace and provider mode
2. **Build** or **Connect** to create the next version
3. **Workbench** when you want a transparent candidate-building session before Eval
4. **Eval Runs** to run an evaluation
5. **Results Explorer** to inspect failures
6. **Compare** when deciding between versions
7. **Optimize** to generate candidate improvements
8. **Improvements** to approve or reject proposed changes
9. **Deploy** to canary or promote a version

## What Each Main Surface Answers

### Dashboard

Use Dashboard to answer:

- Is the system healthy right now?
- Are the core metrics moving in the right direction?
- Are there obvious next actions to take?

Current UI facts:

- the page header is **System Scorecard**
- the left nav label is **Dashboard**

### Setup

Use Setup to answer:

- Did AgentLab detect a workspace?
- Which mode is effective right now?
- Are providers and data stores configured?
- Are local MCP client configs in place?

### Build

Use Build to answer:

- How do I create or refine the next version?
- What did the builder produce?
- How do I edit XML instructions without dropping into raw config files?

### Workbench

Use Workbench to answer:

- How is this agent candidate being built step by step?
- What artifacts, source previews, validation evidence, and review gate did the build produce?
- Is this candidate blocked, still a draft, ready to save for Eval, or waiting on a completed eval run before Optimize?
- What durable session or handoff state exists after refresh or restart?

### Connect

Use Connect to answer:

- How do I bring an existing runtime into AgentLab?
- What source should I import from?
- Should the resulting workspace start in mock, live, or auto mode?

### Eval Runs

Use Eval Runs to answer:

- What evals have run recently?
- How many cases passed?
- Which config did I test?
- Should I generate more eval cases?

### Results Explorer

Use Results Explorer to answer:

- Which examples failed?
- Which failure reasons are most common?
- Which examples need annotations?
- What should I export for review?

### Compare

Use Compare to answer:

- Which config won head-to-head?
- Where are the biggest differences?
- Do I have enough evidence to prefer one version?

### Optimize

Use Optimize to answer:

- Can AgentLab propose or test an improvement cycle here?
- What happened in recent optimize attempts?
- Do I need the run view or the live monitoring view?

### Improvements

Use Improvements to answer:

- What opportunities are worth addressing?
- Which experiments have evidence behind them?
- Which change cards are waiting on human review?
- What did we accept or reject recently?

### Deploy

Use Deploy to answer:

- What version is active?
- Is there a canary running?
- Should I promote, canary, or roll back?

## Legacy Route Compatibility

Several older routes still work as redirects so existing bookmarks do not break.

Current legacy redirects include:

- `/agent-studio`
- `/builder`
- `/assistant`
- `/eval`
- `/review`
- `/reviews`
- `/changes`
- `/experiments`
- `/opportunities`
- `/autofix`
- `/intelligence`

These routes now redirect into the current Build, Eval, or Improvements surfaces instead of representing separate primary pages.

## Keyboard Shortcuts and Command Palette

The current layout supports:

- `Cmd+K` for the command palette
- `N` for the new eval flow
- `O` for Optimize
- `D` for Deploy

The command palette includes navigation shortcuts and recent items instead of acting as a separate product surface.

## API Relationship

The web app is backed by the same FastAPI server the CLI uses.

Examples:

- Build pages call `/api/builder/*` and related generation routes
- Workbench calls `/api/workbench/*` for project hydration, streamed runs, iteration, cancellation, and Eval handoff
- Setup calls `/api/setup/overview`
- Eval pages call `/api/eval/*`, `/api/evals/results*`, and `/api/evals/compare*`
- Deploy uses `/api/deploy` and `/api/deploy/status`
- Connect uses `/api/connect` and `/api/connect/import`
- CX Studio uses `/api/cx/*`

For the live endpoint list, use [api-reference.md](api-reference.md) or open `http://localhost:8000/docs`.

## Next Steps

- [UI Quick Start Guide](UI_QUICKSTART_GUIDE.md)
- [Workbench Feature Deep Dive](features/workbench.md)
- [Platform Overview](platform-overview.md)
- [CLI Reference](cli-reference.md)
- [API Reference](api-reference.md)
