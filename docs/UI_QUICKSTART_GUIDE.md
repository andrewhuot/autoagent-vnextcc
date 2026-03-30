# AutoAgent UI Quick Start Guide

Get from zero to a working AutoAgent session in the browser.

This guide matches the current web app as shipped:

- The app root currently opens **Build** by default
- For first-time setup, start in **Setup**
- The recommended first run is still **mock mode**

## 0. Start the App

The easiest way to start both backend and frontend is:

```bash
./start.sh
```

Manual alternative:

```bash
# terminal 1
autoagent server

# terminal 2
cd web
npm run dev
```

Then open:

- UI: `http://localhost:5173`
- API docs: `http://localhost:8000/docs`

## 1. Check Setup

Click **Setup** in the sidebar under **Home**.

You should see six cards:

| Card | What it shows | Related CLI surface |
|------|---------------|---------------------|
| **Workspace** | Detected workspace path, runtime config path, active config | `autoagent status` |
| **Mode** | Effective mode, preferred mode, provider readiness | `autoagent mode show` |
| **Doctor Findings** | Readiness issues and API-key status | `autoagent doctor` |
| **Data Stores** | Local persistence paths and row counts | `autoagent doctor` |
| **MCP Clients** | Installed MCP-aware client configs | `autoagent mcp status` |
| **CLI Shortcuts** | Recommended next terminal commands | `autoagent status` / `autoagent doctor` |

What to look for:

- The page header says **Setup**
- The pill in the header says either **Workspace Detected** or **Initialization Required**
- Status pills use labels like **Configured** / **Missing**
- In mock mode, missing provider credentials are fine

## 2. Check the Dashboard

Click **Dashboard** in the sidebar under **Home**.

The sidebar label is **Dashboard**, but the page header currently reads **Karpathy Loop Scorecard**.

This page combines:

- **Agent Health** pulse
- **Hard Gates** for safety and regression
- **Primary metrics** for task success, error rate, latency, and cost
- **Optimization Journey** when history exists
- **Score Trajectory** when history exists

The page actions are:

- **Builder**
- **Run Eval**
- **Refresh**

Some workspaces also show a demo banner with **Explore Demo**.

Related CLI surfaces:

- `autoagent status`
- `autoagent usage`
- `autoagent eval show latest`

## 3. Build Your First Agent

Click **Build** in the sidebar.

The Build page is a single tabbed workspace with four tabs:

| Tab | Purpose | Related CLI surface |
|-----|---------|---------------------|
| **Prompt** | Build from a natural-language description | `autoagent build "..."` |
| **Transcript** | Build from uploaded conversation archives | `autoagent intelligence import` + `autoagent intelligence generate-agent` |
| **Builder Chat** | Conversational refinement | `autoagent shell` |
| **Saved Artifacts** | Previously generated build outputs | `autoagent build show latest` |

### Quick path: Prompt tab

1. Stay on the **Prompt** tab
2. Paste a prompt like:

```text
Build a customer support agent for order tracking, refunds, and cancellations.
```

3. Click **Generate Agent**
4. Review the **Live YAML Config** panel
5. Use one of the next actions in that panel:
   - **Generate Evals**
   - **Export**
   - **Run Eval**

What gets created:

- A versioned config
- A build artifact
- An eval draft you can run immediately

### Transcript tab

The **Transcript** tab accepts ZIP, JSON, JSONL, CSV, TXT, and Markdown transcript inputs. After upload, it surfaces extracted intents, pattern signals, and FAQs before you click **Generate Agent**.

## 4. Run Evals

Click **Eval Runs** in the sidebar under **Eval**.

There are two prominent actions at the top:

- **Generate Evals**
- **New Eval Run**

You can also press `N` to open the new-eval flow.

### Quick path

1. Click **New Eval Run**
2. Pick a config version, or leave it on the latest active config
3. Optionally filter by category
4. Click **Start Eval**

When a run completes, you can inspect:

- Composite score
- Passed / total cases
- Status
- Timestamp

Select two runs to enter **Comparison Mode**.

Click a run row to open **Eval Detail**.

Related CLI surfaces:

- `autoagent eval run`
- `autoagent eval show latest`
- `autoagent eval list`

## 5. Optimize the Agent

Click **Optimize** in the sidebar.

The Optimize page is a tabbed hub with five tabs:

| Tab | Purpose | Related CLI surface |
|-----|---------|---------------------|
| **Run** | Launch optimization cycles | `autoagent optimize --cycles 5` |
| **Live** | Watch live optimization state | `autoagent optimize` / `autoagent loop` |
| **Experiments** | Explore experiment outputs | `autoagent compare candidates` |
| **Review** | Embedded change-review surface | `autoagent review show pending` |
| **Opportunities** | Ranked failure clusters and opportunities | `autoagent improve` |

### Quick path: Run tab

1. Stay on **Run**
2. Choose a mode:
   - **Standard**
   - **Advanced**
   - **Research**
3. Set the cycle count
4. Click **Start Optimization**
5. Switch to **Live** if you want to watch the run update in place

Important note: the **Experiments** tab can be sparse. The CLI `compare candidates` command only shows versions already marked as `candidate`, `canary`, `imported`, or `evaluated`, so it is not guaranteed to populate after every optimize run.

## 6. Review Changes

Click **Change Review** in the sidebar under **Review**.

This page shows:

- Pending change cards
- Diff previews
- Before/after metrics
- Confidence and risk labels
- Accept / Reject controls
- Per-hunk review controls

This is the closest UI match to:

```bash
autoagent review show pending
autoagent review apply pending
```

## 7. Deploy

Click **Deploy** in the sidebar or press `D`.

The top-right action is **Deploy Version**.

### Quick path

1. Click **Deploy Version**
2. Pick a version
3. Choose a strategy:
   - **Canary (safe default)**
   - **Immediate promotion**
4. Click **Deploy**

The page also shows:

- **Active Version**
- **Canary Version**
- **Version Count**
- **Canary Verdict** when a canary is active
- **Recent Deployment History**
- **Rollback** when a canary is live

Related CLI surfaces:

- `autoagent deploy canary --yes`
- `autoagent deploy status`
- `autoagent ship --yes`

## 8. Observe the System

The **Observe** section gives you six monitoring views:

| Page | What it helps you answer | Closest CLI surface |
|------|---------------------------|---------------------|
| **Conversations** | What is happening in production conversations? | `autoagent logs` |
| **Traces** | What happened inside a specific trace? | `autoagent trace show latest` / `autoagent trace blame` |
| **Event Log** | What system events have happened recently? | No exact 1:1 command; use `autoagent status`, `autoagent doctor`, and `autoagent logs` for adjacent views |
| **Blame Map** | Which failure families matter most right now? | `autoagent trace blame` |
| **Context** | How is context being used and where is it stressed? | `autoagent context report` / `autoagent context analyze` |
| **Loop Monitor** | What is the continuous loop doing? | `autoagent loop`, `autoagent loop pause`, `autoagent loop resume` |

## 9. Manage Configs and Governance

The **Govern** section contains the operational control plane:

| Page | Purpose | CLI surface |
|------|---------|-------------|
| **Configs** | Version history, compare, activate | `autoagent config list`, `autoagent config show`, `autoagent config set-active` |
| **Judge Ops** | Judge monitoring and calibration | `autoagent judges` |
| **Runbooks** | Guided operational playbooks | `autoagent runbook` |
| **Skills** | Skill discovery and management | `autoagent skill list` |
| **Memory** | Project memory in `AUTOAGENT.md` | `autoagent memory show` |
| **Registry** | Registry items and versions | `autoagent registry list` |
| **Scorer Studio** | Natural-language scorer creation and testing | `autoagent scorer` |

Several additional governance pages exist in the nav, but the table above covers the core first-run surfaces with the clearest CLI counterparts.

## 10. Keyboard Shortcuts

Global shortcuts:

| Key | Action |
|-----|--------|
| `Cmd+K` | Open command palette |
| `N` | Open the new evaluation flow |
| `O` | Open Optimize |
| `D` | Open Deploy |

The command palette searches navigation items plus recent evals, configs, and conversations.

## 11. Recommended Daily Flow

Once the workspace is healthy, the normal UI loop is:

1. **Setup** if anything looks misconfigured
2. **Dashboard** for current health and gates
3. **Build** for the next refinement
4. **Eval Runs** to score the current version
5. **Optimize** to propose and evaluate improvements
6. **Change Review** to accept or reject proposals
7. **Deploy** to mark the chosen version canary or promote it
8. **Conversations** and **Traces** to monitor behavior

Closest CLI loop:

```bash
autoagent status
autoagent build "Describe the next refinement"
autoagent eval run
autoagent optimize --cycles 3
autoagent review show pending
autoagent review apply pending
autoagent deploy canary --yes
autoagent deploy status
```

## 12. Settings

Click **Settings** in the sidebar for a compact reference page that includes:

- Agent configuration paths
- Evaluation-suite paths
- Storage paths
- Keyboard shortcuts
- Links to API docs, ReDoc, and the repository

## Troubleshooting

**The UI opens on Build, not Setup**

That is expected right now. Use the sidebar and start with **Setup** for first-run validation.

**Setup shows missing provider credentials**

That is fine in mock mode. Switch to live only when you want real provider calls:

```bash
autoagent provider configure
autoagent provider test
autoagent mode set live
```

**Dashboard looks sparse**

Run at least one eval and one optimize cycle. Several charts and timelines only become useful after there is history.

**Build generated a config but I do not know what to do next**

Use the action buttons in the **Live YAML Config** panel:

- **Generate Evals**
- **Export**
- **Run Eval**

**Evals look empty**

Build or import a config first, then click **New Eval Run**.

**Optimize has no obvious experiment candidates**

That is normal. Use **Run** first, then **Review**. The **Experiments** tab is not the primary first-run path.

**Deploy feels local, not production**

That is also expected. The current Deploy page is centered on AutoAgent's local rollout/version state. External targets are separate flows.

**The page shows empty data everywhere**

Confirm both services are running:

- UI on `http://localhost:5173`
- API on `http://localhost:8000/docs`

## CLI ↔ UI Cross-Reference

Use this as a closest-match map, not a strict one-to-one contract:

| UI Surface | Closest CLI Surface |
|------------|---------------------|
| Setup | `autoagent status`, `autoagent mode show`, `autoagent doctor`, `autoagent mcp status` |
| Dashboard | `autoagent status`, `autoagent usage`, `autoagent eval show latest` |
| Build → Prompt | `autoagent build "..."` |
| Build → Transcript | `autoagent intelligence import`, `autoagent intelligence generate-agent` |
| Build → Builder Chat | `autoagent shell` |
| Build → Saved Artifacts | `autoagent build show latest` |
| Eval Runs | `autoagent eval run`, `autoagent eval list`, `autoagent eval show latest` |
| Optimize → Run | `autoagent optimize --cycles N` |
| Optimize → Review | `autoagent review show pending`, `autoagent review apply pending` |
| Change Review | `autoagent review show pending`, `autoagent review apply pending` |
| Deploy | `autoagent deploy canary`, `autoagent deploy status`, `autoagent ship --yes` |
| Conversations | `autoagent logs` |
| Traces / Blame Map | `autoagent trace show latest`, `autoagent trace blame` |
| Context | `autoagent context report`, `autoagent context analyze` |
| Loop Monitor | `autoagent loop`, `autoagent loop pause`, `autoagent loop resume` |
| Configs | `autoagent config list`, `autoagent config show`, `autoagent config set-active` |
| Judge Ops | `autoagent judges` |
| Skills | `autoagent skill list` |
| Memory | `autoagent memory show` |
| Registry | `autoagent registry list` |
| Scorer Studio | `autoagent scorer` |
