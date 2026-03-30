# AutoAgent UI Quick Start Guide

Get from zero to a deployed agent in under 10 minutes — entirely in the browser.

> **Prerequisite**: The AutoAgent server must be running. Start it with `autoagent serve` (or `python -m server.main`) and open `http://localhost:5173`.

## 1. Check Your Setup

Click **Setup** in the sidebar (under **Home**).

You should see four cards:

| Card              | What it shows                                           | CLI equivalent            |
|-------------------|---------------------------------------------------------|---------------------------|
| **Workspace**     | Detected workspace path, active config version          | `autoagent status`        |
| **Mode**          | Effective mode (MOCK/LIVE), provider readiness           | `autoagent mode show`     |
| **Doctor Findings** | Blocking issues, API key status                        | `autoagent doctor`        |
| **Data Stores**   | SQLite databases and their row counts                    | `autoagent doctor`        |
| **MCP Clients**   | Connected MCP tools                                      | `autoagent mcp list`      |

**What to look for**: All status tags should show "Ready". If you see "Pending" on provider credentials, you are in mock mode — that is fine for now.

> **Mock vs Live**: AutoAgent starts in mock mode. All LLM calls are simulated so you can explore without API keys. Switch to live mode from the CLI when ready: `autoagent mode set live`.

## 2. Check the Dashboard

Click **Dashboard** in the sidebar (under **Home**).

This is your command center — the UI equivalent of `autoagent status`. You should see:

- **Health score** with a pulse indicator (starts at 0.0 before any evals)
- **Hard gates**: Safety score and regression check (pass/fail)
- **Primary metrics**: Task success rate, error rate, latency, cost
- **Score history chart** (empty until you run evals)
- **Journey timeline** tracking optimization progress

A welcome banner offers quick actions: **Run Demo**, **Start Building**, **Run Eval**. Use these or follow the steps below.

## 3. Build Your First Agent

Click **Build** in the sidebar.

You'll land on a tabbed workspace with four modes:

| Tab                | Purpose                                    | CLI equivalent                      |
|--------------------|--------------------------------------------|-------------------------------------|
| **Prompt Studio**  | Build from a natural language description  | `autoagent build "..."`             |
| **Transcript Studio** | Build from conversation transcripts     | `autoagent intelligence generate-agent` |
| **Builder Chat**   | Conversational refinement                  | `autoagent shell` (interactive)     |
| **Saved Artifacts**| Previously generated build outputs          | `autoagent build show latest`       |

### Quick path: Prompt Studio

1. Type a description in the prompt field. Example:
   ```
   Build a customer support agent for order tracking, refunds, and cancellations.
   ```
2. Click **Generate**
3. Watch the artifact coverage appear: intents, tools, guardrails, skills, integration templates
4. Review the generated YAML config on the right panel
5. Click **Save & Continue** to persist the build artifact

**What gets created**: A versioned config file (the agent definition) and an eval suite (test cases). Same as the CLI `build` command.

> **Tip**: Click example prompts below the input to try pre-built scenarios like IT helpdesk, healthcare intake, or sales qualification.

## 4. Run Evals

Click **Eval Runs** in the sidebar (under **Eval**).

1. Click the **+ New Eval** button (or press `N`)
2. Select a config version from the dropdown (your latest build appears automatically)
3. Click **Start Eval**

You should see a run appear in the table with status "running". When it completes:

- **Composite score** (0.0–1.0) blending quality, safety, latency, and cost
- **Pass/fail count** for individual test cases
- **Score breakdown** by dimension

Click a run row to drill into **Eval Detail** — see per-case results, filter by category or outcome, expand individual cases to see quality/latency/safety metrics.

**Compare two runs**: Check the boxes on two eval runs to see a side-by-side comparison.

> A composite score above **0.85** is production-ready for most use cases.

## 5. Optimize the Agent

Click **Optimize** in the sidebar.

The Optimize page is a tabbed hub with five views:

| Tab             | Purpose                                           | CLI equivalent                  |
|-----------------|---------------------------------------------------|---------------------------------|
| **Run**         | Launch optimization cycles                        | `autoagent optimize --cycles 5` |
| **Live**        | Watch optimization happen in real time             | `autoagent optimize` (streaming)|
| **Experiments** | Browse generated experiment candidates             | `autoagent compare candidates`  |
| **Review**      | Review proposed changes (diffs, metrics, gates)    | `autoagent review show pending` |
| **Opportunities**| See diagnosed failure clusters ranked by impact   | `autoagent improve` (diagnosis) |

### Quick path: Run tab

1. Choose a mode: **Standard** (default, safe), **Advanced** (adaptive bandit), or **Research** (full algorithm control)
2. Set the number of cycles (3 is a good start)
3. Click **Start Optimization**
4. Switch to the **Live** tab to watch progress in real time

Each cycle: diagnose failures, propose a fix, evaluate it, accept or reject based on gates.

## 6. Review Changes

Click **Change Review** in the sidebar (under **Review**).

Review cards show:
- **Diff preview** of proposed config changes (hunk-by-hunk)
- **Metrics delta**: before vs after scores
- **Confidence score** and gate results (safety, regression)
- **Timeline** of the change lifecycle

For each hunk you can **Accept** or **Reject** individually. Or accept the full card.

> This is the UI equivalent of `autoagent review show pending` + `autoagent review apply pending`.

## 7. Deploy

Click **Deploy** in the sidebar (or press `D`).

1. Click **+ New Deploy**
2. Select the config version to deploy
3. Choose a strategy:
   - **Canary** (default) — routes 10% of traffic to the new config
   - **Immediate** — full rollout (requires confirmation dialog)
4. Click **Deploy**

You should see:
- **Active version** and deployment status
- **Canary traffic split** (if applicable)
- **Deployment history** with timestamps
- **Rollback** button for instant revert

> **Warning**: Deploy is blocked in mock mode. Switch to live mode first: `autoagent mode set live`.

## 8. Monitor (Observe)

The **Observe** section in the sidebar gives you six monitoring views:

| Page              | Purpose                                       | CLI equivalent               |
|-------------------|-----------------------------------------------|------------------------------|
| **Conversations** | Production interaction logs with safety flags | `autoagent conversations`    |
| **Traces**        | Recorded agent conversations with timing      | `autoagent trace list`       |
| **Event Log**     | System events (deploys, evals, errors)        | `autoagent events`           |
| **Blame Map**     | Failure clusters ranked by impact, with trends | `autoagent blame`           |
| **Context**       | Token usage and context window analysis        | `autoagent context`          |
| **Loop Monitor**  | Optimization loop health and cycle tracking    | `autoagent loop status`      |

## 9. Manage Configs and Governance

The **Govern** section has your operational controls:

| Page                | Purpose                                         | CLI equivalent                     |
|---------------------|-------------------------------------------------|------------------------------------|
| **Configs**         | Version management, activate, compare, NL edit  | `autoagent config list/set-active` |
| **Judge Ops**       | Judge calibration and evaluation                | `autoagent judge-ops`              |
| **Skills**          | Manage reusable agent capabilities              | `autoagent skills list`            |
| **Memory**          | View/edit AUTOAGENT.md project memory           | `autoagent memory`                 |
| **Registry**        | Configuration registry                          | `autoagent registry`               |
| **Scorer Studio**   | Build and test custom scorers                   | `autoagent scorer`                 |

## 10. Keyboard Shortcuts

You never need to leave the keyboard:

| Key       | Action                |
|-----------|-----------------------|
| `Cmd+K`   | Open command palette  |
| `N`       | New eval run          |
| `O`       | Open Optimize page    |
| `D`       | Open Deploy page      |

The **command palette** (`Cmd+K`) searches across all pages — type any page name to navigate instantly.

## 11. Recommended Daily Flow

Once your workspace is set up, the normal loop is:

1. **Dashboard** — check health score, hard gates, recent events
2. **Build** — describe your next refinement in Prompt Studio or Builder Chat
3. **Eval Runs** — run the eval suite (`N` shortcut)
4. **Optimize** — run 3–5 cycles (`O` shortcut)
5. **Change Review** — accept or reject proposals
6. **Deploy** — ship to canary (`D` shortcut)
7. **Conversations** / **Traces** — monitor production behavior

This mirrors the CLI daily flow:
```bash
autoagent status → build → eval run → optimize --cycles 3 → review apply → deploy canary
```

## 12. Settings

Click **Settings** in the sidebar for:
- **Agent configuration paths** (base config, version manifest)
- **Evaluation suite paths** (case directory, runner, scorer)
- **Storage paths** (conversations DB, optimizer memory)
- **Keyboard shortcuts reference**
- **Links**: API docs, ReDoc, repository

## Troubleshooting

**Setup shows "Pending" on providers**
You are in mock mode. This is fine for exploration. Switch to live mode from CLI: `autoagent provider configure` then `autoagent mode set live`.

**Dashboard shows 0.0 health**
No evals have run yet. Go to **Eval Runs** and click **+ New Eval**.

**Build generates empty config**
Make sure a workspace exists. Check **Setup** — the Workspace card should show "Detected: Yes".

**Eval run stuck on "running"**
Check the server logs (`autoagent serve` terminal). WebSocket connection may have dropped — refresh the page.

**Deploy button grayed out**
Deploy is blocked in mock mode. Switch to live first.

**"No configs available" in Eval or Deploy**
Run a build first to generate a config, or import one via **CX Import** / **ADK Import**.

**Page loads but shows empty data**
The API server may not be running. Verify `http://localhost:8000/docs` loads the OpenAPI spec.

## CLI ↔ UI Cross-Reference

| CLI Command                      | UI Page            | Sidebar Section |
|----------------------------------|--------------------|-----------------|
| `autoagent status`               | Dashboard          | Home            |
| `autoagent doctor`               | Setup              | Home            |
| `autoagent build "..."`          | Build              | Build           |
| `autoagent eval run`             | Eval Runs          | Eval            |
| `autoagent eval show <id>`       | Eval Detail        | Eval            |
| `autoagent optimize --cycles N`  | Optimize → Run     | Optimize        |
| `autoagent improve`              | Optimize → Live    | Optimize        |
| `autoagent compare candidates`   | Optimize → Experiments | Optimize    |
| `autoagent review show pending`  | Change Review      | Review          |
| `autoagent review apply`         | Change Review      | Review          |
| `autoagent deploy canary`        | Deploy             | Deploy          |
| `autoagent deploy status`        | Deploy             | Deploy          |
| `autoagent config list`          | Configs            | Govern          |
| `autoagent mcp list`             | Setup (MCP card)   | Home            |
| `autoagent usage`                | Dashboard (metrics)| Home            |
