# AgentLab UI Quick Start Guide

This guide gets you from zero to a working AgentLab session in the browser using the current web console.

It is based on the routes and page labels that ship in this repo today.

## Before You Start

Make sure you already ran the project setup steps from [README.md](../README.md).

You need:

- Python dependencies installed in `.venv`
- frontend dependencies installed in `web/node_modules`

## 1. Start the App

The easiest way to start both backend and frontend is:

```bash
./start.sh
```

Manual alternative:

```bash
# terminal 1
agentlab server

# terminal 2
cd web
npm run dev
```

Open:

- UI: `http://localhost:5173/dashboard`
- App root: `http://localhost:5173` and it redirects to `/build`
- API docs: `http://localhost:8000/docs`

## 2. Learn the Main Navigation

In simple mode, the main sidebar shows the current day-one workflow:

- `Dashboard`
- `Setup`
- `Build`
- `Workbench`
- `Eval Runs`
- `Results Explorer`
- `Compare`
- `Optimize Studio`
- `Optimize`
- `Improvements`
- `Deploy`
- `Docs`

That list is the fastest way to understand how the product is currently organized.

Import and integration routes such as `Connect`, `CX Studio`, and `ADK Import` are available from the broader navigation.

## 3. Check Setup First

Open **Setup** before you build, eval, or optimize anything.

The current page includes these cards:

- **Workspace**
- **Mode**
- **Doctor Findings**
- **Data Stores**
- **MCP Clients**
- **CLI Shortcuts**

What to look for:

- the page header says **Setup**
- the status pill says **Workspace Detected** or **Initialization Required**
- provider rows show whether credentials are configured
- missing API keys are acceptable if you are intentionally working in mock mode

Closest CLI surfaces:

```bash
agentlab status
agentlab doctor
agentlab mode show
agentlab mcp status
```

## 4. Use Build to Create or Refine a Config

Open **Build** for the main authoring workflow.

The current Build page has four tabs:

- **Prompt**
- **Transcript**
- **Builder Chat**
- **Saved Artifacts**

It also includes the **XML Instruction Studio** inside the build workflow.

### Fastest first run

1. Stay on **Prompt**
2. Enter a brief such as:

```text
Build a customer support agent for order tracking, refunds, and cancellations.
```

3. Click **Generate Agent**
4. Review the generated config
5. Use one of the next actions such as **Generate Evals** or **Run Eval**

Closest CLI surfaces:

```bash
agentlab build "customer support agent for order tracking, refunds, and cancellations"
agentlab build show latest
agentlab instruction show
agentlab instruction validate
```

## 5. Use Workbench for an Inspectable Candidate Build

Open **Workbench** when you want to watch an agent candidate take shape before Eval.

Workbench is useful when you want:

- a live plan and task feed
- generated artifacts and source previews
- validation and compatibility evidence
- a review gate and session handoff
- a guided **Save candidate and open Eval** or **Open Eval with this candidate** action

Workbench does not run Eval or Optimize itself. It prepares and materializes the candidate, then hands that candidate to Eval Runs.

Closest API surfaces:

```bash
GET /api/workbench/projects/default
GET /api/workbench/projects/{project_id}/plan
POST /api/workbench/build/stream
POST /api/workbench/projects/{project_id}/bridge/eval
```

See [Workbench Feature Deep Dive](features/workbench.md) for the full workflow and readiness states.

## 6. Use Connect When You Already Have a Runtime

Open **Connect** if you are importing an existing runtime instead of starting from scratch.

The current adapters are:

- **OpenAI Agents**
- **Anthropic**
- **HTTP**
- **Transcript**

The page is titled **Connect Existing Runtime** and creates a fresh AgentLab workspace from the selected source.

Closest CLI surfaces:

```bash
agentlab connect openai-agents --path /path/to/project
agentlab connect anthropic --path /path/to/project
agentlab connect http --url https://agent.example.com
agentlab connect transcript --file conversations.jsonl
```

## 7. Run an Eval

Open **Eval Runs** to launch and monitor evaluation runs.

The current page has two primary actions:

- **Generate Evals**
- **New Eval Run**

The page lets you:

- choose a config version
- optionally filter by category
- start an eval
- monitor status and scores

Closest CLI surfaces:

```bash
agentlab eval run
agentlab eval list
agentlab eval show latest
agentlab eval generate
```

## 8. Use Results Explorer for Case-Level Debugging

Open **Results Explorer** after you have at least one eval run.

This is the place for:

- filtering pass and fail cases
- searching examples
- inspecting failure reasons
- adding annotations
- exporting a run as JSON, CSV, or Markdown
- diffing one run against another

This is different from Eval Runs:

- **Eval Runs** answers "what happened overall?"
- **Results Explorer** answers "where exactly did it fail?"

Closest CLI surfaces:

```bash
agentlab eval results
agentlab eval results export RUN_ID --format markdown
```

## 9. Use Compare for Head-to-Head Decisions

Open **Compare** when you want to compare two versions directly.

The current page lets you:

- choose config A and config B
- optionally provide a dataset path
- choose a judge strategy
- run a pairwise comparison
- inspect recent comparisons

This is the decision surface for "which version is better?" rather than the diagnosis surface for "why did this fail?"

Closest CLI surfaces:

```bash
agentlab compare candidates
agentlab eval compare --config-a configs/v001.yaml --config-b configs/v002.yaml
```

## 10. Optimize, Then Review in Improvements

Open **Optimize** to launch optimization cycles.

The current page exposes two tabs:

- **Run**
- **Live**

Current visible optimization modes:

- `standard`
- `advanced`
- `research`

When an optimization cycle produces something reviewable, move to **Improvements**.

The **Improvements** page is the current review workflow and has four tabs:

- **Opportunities**
- **Experiments**
- **Review**
- **History**

This replaces the older "Change Review" framing in the main UI.

Closest CLI surfaces:

```bash
agentlab optimize --cycles 1
agentlab review list
agentlab review show pending
agentlab review apply pending
```

## 11. Deploy Safely

Open **Deploy** when you are ready to ship a version.

The current page shows:

- **Active Version**
- **Canary Version**
- **Version Count**
- deployment history
- a **Deploy Version** action
- rollback controls when a canary is active

Closest CLI surfaces:

```bash
agentlab deploy --strategy canary --yes
agentlab deploy status
agentlab deploy rollback --yes
```

If you want review and deploy in one CLI step, this also works:

```bash
agentlab deploy --auto-review --yes
```

## 12. Explore the Pro and Integration Surfaces

When you switch into the broader navigation, you will see additional routes for observation, governance, and integrations.

Examples:

- **Conversations**
- **Traces**
- **Event Log**
- **Blame Map**
- **Context**
- **Loop Monitor**
- **Configs**
- **Judge Ops**
- **Runbooks**
- **Skills**
- **Memory**
- **Registry**
- **Scorer Studio**
- **CX Studio**
- **CX Import / CX Deploy**
- **ADK Import / ADK Deploy**

These pages are real routes in the current app, but they are not required for a first successful build and eval cycle.

## 13. Keyboard Shortcuts

The current app supports these global shortcuts:

| Key | Action |
|-----|--------|
| `Cmd+K` | Open command palette |
| `N` | Open the new eval flow |
| `O` | Open Optimize |
| `D` | Open Deploy |

The command palette also exposes navigation shortcuts and recent items.

## 14. Recommended Daily Loop

Once the workspace is healthy, the usual operating rhythm is:

1. **Setup** to confirm readiness
2. **Build** or **Connect** to create the next version
3. **Workbench** when you want an inspectable candidate build and Eval handoff
4. **Eval Runs** to score it
5. **Results Explorer** to inspect failures
6. **Compare** if you need a head-to-head decision
7. **Optimize** to generate candidates
8. **Improvements** to approve or reject changes
9. **Deploy** to canary or promote the winning version

Closest CLI loop:

```bash
agentlab status
agentlab build "describe the next refinement"
agentlab eval run
agentlab eval show latest
agentlab compare candidates
agentlab optimize --cycles 1
agentlab review list
agentlab deploy --auto-review --yes
agentlab deploy status
```

## Troubleshooting

### The UI opens on Dashboard or Build depending on how I started it

That is expected.

- `./start.sh` prints the dashboard URL
- the frontend app root `/` redirects to `/build`

### Setup shows missing credentials

That is fine if you are using mock mode.

To inspect or change the current mode:

```bash
agentlab mode show
agentlab mode set live
agentlab provider list
agentlab provider test
```

### Results Explorer is empty

Run an eval first:

```bash
agentlab eval run
```

### Compare has nothing to compare

You need at least two distinct config versions or comparison-ready runs.

### Optimize did not create a candidate

That can be normal. On a healthy workspace, the CLI may report:

```text
Latest eval passed; no optimization needed.
```

### Deploy feels local

That is expected for the default AgentLab deployment target. External deployment targets such as CX use separate integration flows.

## Next Steps

- [Detailed Guide](DETAILED_GUIDE.md)
- [Workbench Feature Deep Dive](features/workbench.md)
- [Platform Overview](platform-overview.md)
- [App Guide](app-guide.md)
- [CX Studio Integration](cx-studio-integration.md)
