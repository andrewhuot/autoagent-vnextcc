# AutoAgent UI Quick Start Guide

This guide gets you from zero to a working AutoAgent session in the browser using the current web console.

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
autoagent server

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
- `Connect`
- `Eval Runs`
- `Results Explorer`
- `Compare`
- `Optimize`
- `Improvements`
- `Deploy`

That list is the fastest way to understand how the product is currently organized.

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
autoagent status
autoagent doctor
autoagent mode show
autoagent mcp status
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
autoagent build "customer support agent for order tracking, refunds, and cancellations"
autoagent build show latest
autoagent instruction show
autoagent instruction validate
```

## 5. Use Connect When You Already Have a Runtime

Open **Connect** if you are importing an existing runtime instead of starting from scratch.

The current adapters are:

- **OpenAI Agents**
- **Anthropic**
- **HTTP**
- **Transcript**

The page is titled **Connect Existing Runtime** and creates a fresh AutoAgent workspace from the selected source.

Closest CLI surfaces:

```bash
autoagent connect openai-agents --path /path/to/project
autoagent connect anthropic --path /path/to/project
autoagent connect http --url https://agent.example.com
autoagent connect transcript --file conversations.jsonl
```

## 6. Run an Eval

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
autoagent eval run
autoagent eval list
autoagent eval show latest
autoagent eval generate
```

## 7. Use Results Explorer for Case-Level Debugging

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
autoagent eval results
autoagent eval results export RUN_ID --format markdown
```

## 8. Use Compare for Head-to-Head Decisions

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
autoagent compare candidates
autoagent eval compare --config-a configs/v001.yaml --config-b configs/v002.yaml
```

## 9. Optimize, Then Review in Improvements

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
autoagent optimize --cycles 1
autoagent review list
autoagent review show pending
autoagent review apply pending
```

## 10. Deploy Safely

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
autoagent deploy --strategy canary --yes
autoagent deploy status
autoagent deploy rollback --yes
```

If you want review and deploy in one CLI step, this also works:

```bash
autoagent deploy --auto-review --yes
```

## 11. Explore the Pro and Integration Surfaces

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

## 12. Keyboard Shortcuts

The current app supports these global shortcuts:

| Key | Action |
|-----|--------|
| `Cmd+K` | Open command palette |
| `N` | Open the new eval flow |
| `O` | Open Optimize |
| `D` | Open Deploy |

The command palette also exposes navigation shortcuts and recent items.

## 13. Recommended Daily Loop

Once the workspace is healthy, the usual operating rhythm is:

1. **Setup** to confirm readiness
2. **Build** or **Connect** to create the next version
3. **Eval Runs** to score it
4. **Results Explorer** to inspect failures
5. **Compare** if you need a head-to-head decision
6. **Optimize** to generate candidates
7. **Improvements** to approve or reject changes
8. **Deploy** to canary or promote the winning version

Closest CLI loop:

```bash
autoagent status
autoagent build "describe the next refinement"
autoagent eval run
autoagent eval show latest
autoagent compare candidates
autoagent optimize --cycles 1
autoagent review list
autoagent deploy --auto-review --yes
autoagent deploy status
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
autoagent mode show
autoagent mode set live
autoagent provider list
autoagent provider test
```

### Results Explorer is empty

Run an eval first:

```bash
autoagent eval run
```

### Compare has nothing to compare

You need at least two distinct config versions or comparison-ready runs.

### Optimize did not create a candidate

That can be normal. On a healthy workspace, the CLI may report:

```text
Latest eval passed; no optimization needed.
```

### Deploy feels local

That is expected for the default AutoAgent deployment target. External deployment targets such as CX use separate integration flows.

## Next Steps

- [Detailed Guide](DETAILED_GUIDE.md)
- [Platform Overview](platform-overview.md)
- [App Guide](app-guide.md)
- [CX Studio Integration](cx-studio-integration.md)
