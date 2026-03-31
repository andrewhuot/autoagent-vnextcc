# Platform Overview

AutoAgent is a local-first platform for improving AI agents across three surfaces:

- a CLI for day-to-day build/eval/optimize/deploy work
- a FastAPI backend for automation and UI data
- a web console for exploration, review, and operations

This page focuses on the current product surface as it exists in the repo today.

---

## The core loop

The product centers on one operational loop:

```text
BUILD -> EVAL -> COMPARE -> OPTIMIZE -> REVIEW -> DEPLOY
```

What each step means in today’s product:

1. **Build** — create or refine a config from a prompt, transcripts, or builder chat
2. **Eval** — run the active or selected config against eval cases
3. **Compare** — inspect run-to-run deltas and pairwise version comparisons
4. **Optimize** — generate and test candidate changes
5. **Review** — accept or reject improvements with evidence
6. **Deploy** — canary, release, rollback, or integration-target push

The UI, CLI, and API all work from the same workspace state, so you can move between them without translating concepts.

---

## Core product surfaces

### Build

The build surface is now a unified workspace rather than a collection of separate older pages.

Current build tabs:

- **Prompt** — generate an agent from a natural-language brief
- **Transcript** — ingest transcript archives and generate from them
- **Builder Chat** — conversational refinement
- **Saved Artifacts** — inspect previous build outputs

Build is also where the **XML Instruction Studio** lives. That matters because new workspaces now default to XML root instructions and the same XML model is editable from both CLI and UI.

### Connect

`Connect` is the main import surface for existing runtimes.

Supported adapters:

- OpenAI Agents
- Anthropic SDK projects
- HTTP-backed runtimes
- transcript-backed imports

This is the product surface for “bring an existing runtime into AutoAgent” rather than rebuilding from scratch.

### Eval

The eval area now has three distinct views:

- **Eval Runs** — launch runs and inspect high-level summaries
- **Results Explorer** — inspect case-level results, annotations, exports, and failure patterns
- **Compare** — run or inspect pairwise comparisons between configs or runs

These three views are separate on purpose:

- `Eval Runs` answers “what happened?”
- `Results Explorer` answers “where did it fail?”
- `Compare` answers “which version is better?”

### Optimize

`Optimize` is the command-and-control surface for improvement cycles.

Current product behavior exposes optimizer modes as:

- `standard`
- `advanced`
- `research`

Under the hood, the codebase also contains richer search, gating, and experiment modules, but those are not all surfaced as separate user-facing “strategies” today. The docs should follow the visible product labels first.

### Review

The old standalone “Change Review” framing has been consolidated into **Improvements**.

`Improvements` is the current review workflow for:

- opportunities
- experiments
- review decisions
- outcome history

Legacy routes like `/changes`, `/review`, `/reviews`, and `/experiments` redirect into this surface.

### Deploy

Deploy tracks version rollout state:

- active version
- canary version
- deployment history
- rollback state

The deploy surface is intentionally split from review. Review is about accepting a change; deploy is about shipping it safely.

---

## Web console structure

### Simple mode

The default simple-mode navigation is the current day-one product story:

- `Dashboard`
- `Setup`
- `Build`
- `Connect`
- `Eval Runs`
- `Results Explorer`
- `Compare`
- `Optimize`
- `Improvements`
- `Deploy`

### Pro mode

Pro mode expands into the broader operator and integration surface:

- **Observe** — Conversations, Traces, Event Log, Blame Map, Context, Loop Monitor
- **Govern** — Configs, Judge Ops, Runbooks, Skills, Memory, Registry, Scorer Studio, Notifications, reward/policy workflows
- **Integrations** — CX Deploy, ADK Deploy, Agent Skills, Sandbox, What-If, Knowledge

### Route compatibility

Several older routes are still supported as redirects so bookmarks and older docs do not hard-break:

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

They now point into the current product surfaces instead of representing separate primary pages.

---

## CLI surface

The default CLI help shows two groups:

- **Primary** — `new`, `build`, `eval`, `optimize`, `deploy`, `status`, `doctor`, `shell`
- **Secondary** — `config`, `connect`, `instruction`, `memory`, `mode`, `model`, `provider`, `review`, `template`

Run:

```bash
autoagent --help
autoagent advanced
```

The hidden/advanced surface includes operations like `compare`, `trace`, `mcp`, `cx`, `adk`, `runbook`, `skill`, `scorer`, `release`, and `quickstart`.

---

## API surface

The backend exposes the same product model through `/api/*`.

Current route families include:

- **setup and health** — `/api/setup/overview`, `/api/health`, `/api/health/*`
- **build and intelligence** — `/api/builder/*`, `/api/intelligence/*`
- **connect and integrations** — `/api/connect`, `/api/cx/*`, `/api/adk/*`
- **eval and results** — `/api/eval/*`, `/api/evals/compare*`, `/api/evals/results*`
- **review and deployment** — `/api/changes/*`, `/api/reviews/*`, `/api/deploy*`
- **observe and governance** — `/api/conversations`, `/api/traces/*`, `/api/judges*`, `/api/runbooks*`, `/api/skills*`, `/api/registry*`

Use `http://localhost:8000/docs` for the live OpenAPI schema.

---

## XML instructions

XML instructions are now part of the product, not a side feature.

They show up in:

- new workspace defaults
- `autoagent instruction *` CLI commands
- eval override support (`--instruction-overrides`)
- the Build page’s XML Instruction Studio

That means “instruction authoring” now lives inside the main build/eval loop instead of being a separate expert-only step.

---

## Results and comparisons

Two newer product surfaces are especially important:

### Results Explorer

Results Explorer is for structured eval-result inspection:

- run summaries
- example-level failures
- annotations
- exports
- run-to-run diffs

### Compare

Compare is for head-to-head decisions:

- config A vs config B
- pairwise summaries
- confidence and significance context
- recent comparison history

The split matters because one is diagnosis-oriented and the other is decision-oriented.

---

## Improvement objects

AutoAgent currently works with a few related but different improvement objects:

### Opportunities

Ranked problem areas or failure clusters worth addressing.

### Experiments

Evaluated candidate changes and their outcomes.

### Review cards / change cards

Human-decision artifacts you can apply, reject, or export.

### Deployable versions

Config versions that can be marked active, candidate, canary, imported, or otherwise tracked in rollout state.

The docs should not collapse these into one generic “experiment card” term everywhere, because the UI and CLI now expose them separately.

---

## Integrations

### CX Studio

The current CX surface is a first-class workflow:

- auth
- agent browsing
- import
- diff
- export preview
- sync
- push/export

See [cx-studio-integration.md](cx-studio-integration.md) for the exact CLI and API surface.

### ADK

ADK support includes import, diff, export, and deploy flows rather than just a one-time file conversion.

### MCP

AutoAgent ships an MCP server with:

- 22 tools
- 5 prompts
- read-only resources for configs, traces, evals, skills, and dataset stats

This is the main coding-agent integration path for Claude Code, Codex, Cursor, Windsurf, and similar clients.

---

## Eval engine and scoring

Under the hood, the repo includes:

- 7 evaluation modes
- dataset management for golden, rolling holdout, challenge, and live-failure sets
- structured results APIs
- judge calibration and drift tracking
- natural-language scorer creation
- comparison and result-export workflows

For operators, the most important takeaway is that eval is no longer “one score and done.” It now has separate surfaces for run history, case-level diagnosis, scorer authoring, and head-to-head comparison.

---

## Reliability and control

AutoAgent is designed to be human-interruptible:

- mock/live/auto execution modes
- permission modes
- review-before-apply flows
- deploy canaries and rollback
- pause/resume loop controls
- explicit config activation

The platform also includes persistence and operational state for:

- conversations
- traces
- eval history
- optimization memory
- build artifacts
- releases
- experiments

---

## Where to go next

- [Concepts](concepts.md) — mental models for workspaces, versions, modes, and improvements
- [CLI Reference](cli-reference.md) — command-by-command reference
- [UI Quick Start](UI_QUICKSTART_GUIDE.md) — walkthrough of the current browser UI
- [App Guide](app-guide.md) — route and page map
- [API Reference](api-reference.md) — route families and active endpoints
