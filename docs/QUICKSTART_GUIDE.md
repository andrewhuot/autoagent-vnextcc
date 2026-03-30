# AutoAgent Quick Start Guide

Get from zero to a working AutoAgent workspace in under 10 minutes.

This guide follows the most reliable first-run path:

- Stay in **mock mode** while you learn the workflow
- Build, eval, optimize, review, and deploy locally
- Switch to **live mode** only after the basics make sense

If you want the one-command version of this flow, run `autoagent quickstart`.

## 1. Install AutoAgent

From this repository:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Requirements: Python 3.11+, macOS / Linux / WSL.

## 2. List the Starter Templates

AutoAgent ships with bundled starter templates:

```bash
autoagent template list
```

You should see:

```text
Starter templates
=================
- customer-support: Handle order questions, support troubleshooting, and product recommendations.
- it-helpdesk: Triage employee IT support requests, device issues, and access problems.
- sales-qualification: Qualify inbound leads, identify urgency, and route to the right sales motion.
- healthcare-intake: Collect patient intake information safely before clinical follow-up.
```

## 3. Create a Workspace

Create a starter workspace with seeded demo data:

```bash
autoagent new my-project --template customer-support --demo
cd my-project
autoagent status
```

You should see a status screen similar to:

```text
AutoAgent Status
━━━━━━━━━━━━━━━━━
  Workspace:  my-project
  Path:       /path/to/my-project
  Mode:       MOCK
  Config:     v001 — gemini-2.0-flash | You are AutoAgent, a customer support assistant...
  Eval score: n/a (never)
  Safety:     0.117
  Pending:    1 review card(s), 1 autofix proposal(s)
  Deployment: active v001
  Models:     openai:gpt-4o | anthropic:claude-sonnet-4-5
  MCP:        0 server(s)
  Memory:     1 active source(s)

  Next step:  autoagent eval run
```

`--demo` seeds a friendlier first workspace:

- Starter eval cases and scorer specs
- Sample traces
- One pending review card
- One pending autofix proposal

### Mock vs Live

AutoAgent starts in **mock mode**. That is the intended way to learn the product because:

- All model calls are simulated
- The CLI is deterministic
- You do not need credentials to complete the walkthrough below

The rest of this guide assumes you stay in mock mode.

When you are ready to use real providers, configure them explicitly:

```bash
autoagent provider configure
export OPENAI_API_KEY=sk-...
autoagent provider test
autoagent mode set live
autoagent mode show
```

Notes:

- `provider configure` writes `.autoagent/providers.json` and updates `autoagent.yaml`
- The model prompt defaults to the bare model name like `gpt-4o`
- Fully qualified input like `openai:gpt-4o` also works
- `provider test` checks that the required environment variable is set
- `mode set live` fails when no configured provider credential is available

Your workspace looks like this:

```text
my-project/
├── autoagent.yaml           # runtime config (models, budgets, loop settings)
├── AUTOAGENT.md             # project memory / agent instructions
├── configs/
│   ├── v001.yaml            # active versioned config
│   └── v001_base.yaml       # base config snapshot
├── evals/
│   └── cases/               # eval case files
└── .autoagent/
    ├── workspace.json       # workspace metadata + mode preference
    ├── settings.json        # permissions + model overrides
    ├── sessions/            # shell session history
    └── providers.json       # optional provider registry
```

## 4. Build Your First Agent

Generate a config and eval draft from a natural-language prompt:

```bash
autoagent build "Build a customer support agent for order tracking, refunds, and cancellations"
```

You should see:

```text
✦ AutoAgent Build
Prompt: Build a customer support agent for order tracking, refunds, and cancellations
Connectors: None

Artifact coverage
  Intents:               2
  Tools:                 0
  Guardrails:            2
  Skills:                2
  Integration templates: 1

Generated handoff files
  Config:   /path/to/my-project/configs/v002.yaml
  Active:   v002
  Evals:    /path/to/my-project/evals/cases/generated_build.yaml
  Artifact: /path/to/my-project/.autoagent/build_artifact_latest.json

Next step:
  autoagent eval run
```

Inspect the latest build artifact:

```bash
autoagent build show latest
```

What the build step creates:

- A new versioned config file
- A generated eval case file
- A build artifact JSON file for inspection/debugging

Advanced entry points:

- Import transcripts, then generate from them:

```bash
autoagent intelligence import /path/to/transcripts.zip
autoagent intelligence report list
autoagent intelligence generate-agent <report-id> --output configs/v003_transcript.yaml
```

- Import an existing config:

```bash
autoagent config import /path/to/config.yaml
```

## 5. Run Evals

Evaluate the active config:

```bash
autoagent eval run
```

In mock mode, you will see a note that scores are simulated. A successful run looks like:

```text
✦ Running the gauntlet. Truth comes from test cases.

Eval plan
  1. Load active runtime + config
  2. Run eval suite against selected scope
  3. Summarize scores and suggested follow-up
Evaluating active config: /path/to/my-project/configs/v002.yaml
⚠ Eval harness is using mock_agent_response, so eval scores remain simulated until a real agent_fn is wired in.

Full eval suite
  Cases: 53/55 passed
  Quality:   0.9764
  Safety:    0.9818 (1 failures)
  Latency:   0.9751
  Cost:      0.8586
  Composite: 0.9598
  Tokens:    15554  |  Est. USD: $0.000000

  Mood: Flying

  Next actions:
    → autoagent optimize --cycles 3
    → autoagent status
```

Show the latest results again any time:

```bash
autoagent eval show latest
```

The **composite score** (0.0–1.0) blends quality, safety, latency, and cost. Higher is better.

## 6. Improve the Agent

### One-shot improvement

```bash
autoagent improve
```

`improve` does four things in one pass:

1. Evaluates the current agent
2. Diagnoses the biggest failure clusters
3. Generates a top fix proposal
4. Prompts you to apply it now or inspect it later

Typical output:

```text
✦ Improve

Eval composite: 0.9598
AutoAgent Diagnosis
───────────────────
Found 6 failure cluster(s) across 11 total failures.

  1. safety_violation — 7 failures (11.7% impact)
  2. timeout — 2 failures (3.3% impact)
  3. unhelpful_response — 2 failures (3.3% impact)

Suggested fixes: 1
  Top proposal: e41d1cf8cab1 (few_shot_edit, risk=low, expected_lift=50.0%)

Apply the top proposal now (e41d1cf8cab1)? [y/N]:
```

### Multi-cycle optimization

Run multiple optimization cycles:

```bash
autoagent optimize --cycles 5
```

Each cycle:

1. Diagnoses the dominant failure
2. Proposes a change
3. Evaluates the candidate
4. Accepts or rejects it based on the result

### Optional: compare candidate-like versions

```bash
autoagent compare candidates
```

This command only shows versions whose status is already `candidate`, `canary`, `imported`, or `evaluated`. If it prints `No candidate configs found.`, that is expected in many normal mock-mode runs.

## 7. Review and Deploy

### Step by step

Inspect and apply the top pending review card:

```bash
autoagent review show pending
autoagent review apply pending
```

Mark the latest version as canary and inspect rollout state:

```bash
autoagent deploy canary --yes
autoagent deploy status
```

### Quick ship

If you want release creation and canary deployment in one command:

```bash
autoagent ship --yes
```

Typical `ship` output:

```text
✦ Ship
  Pending review items: 0
Applied: created release rel-abc12345
  Deploying: v002 from configs/v002.yaml
  Target:    autoagent canary
Applied: deployed v002 as canary
```

### Create a release object explicitly

```bash
autoagent release create --experiment-id exp-001
```

Important clarification:

- `deploy canary`, `deploy status`, and `ship` update AutoAgent's local rollout/version state
- External deployment targets are separate flows, for example `autoagent deploy --target cx-studio`

## 8. Use the Interactive Shell

Launch the workspace shell:

```bash
autoagent shell
```

You will see:

```text
AutoAgent Shell
[my-project | v002]
Type /help for commands, or enter free text.

autoagent>
```

### Slash commands

| Command | Action |
|---------|--------|
| `/status` | Show workspace status |
| `/config` | Show active config info |
| `/memory` | Show `AUTOAGENT.md` contents |
| `/doctor` | Run workspace diagnostics |
| `/review` | Show pending review cards |
| `/mcp` | Show MCP integration status |
| `/compact` | Save a session summary to `.autoagent/memory/latest_session.md` |
| `/resume` | Show the most recent saved session |
| `/exit` | Exit the shell |

### Free-text routing

Examples:

- Type `evaluate my agent` and the shell runs `autoagent eval run`
- Type `deploy` and the shell shows the deploy status surface
- Type a build request like `build a customer support agent for refunds` and the shell routes it into `autoagent build`

### Sessions

Sessions are persisted automatically.

```bash
autoagent continue
autoagent session list
autoagent session delete <id>
```

## 9. Models, Usage, and Providers

Show the effective proposer/evaluator models:

```bash
autoagent model show
```

List the available runtime models:

```bash
autoagent model list
```

Set an override using a key that appears in `autoagent model list`:

```bash
autoagent model set proposer openai:gpt-4o
```

Show spend and budget state:

```bash
autoagent usage
```

Provider helpers:

```bash
autoagent provider configure
autoagent provider list
autoagent provider test
```

## 10. MCP Integration

See both workspace MCP servers and installed client configs:

```bash
autoagent mcp status
```

Manage workspace MCP servers:

```bash
autoagent mcp add my-tool --command "npx" --arg "-y" --arg "@my/tool-server"
autoagent mcp list
autoagent mcp inspect my-tool
autoagent mcp remove my-tool
```

## 11. Diagnostics and Permissions

Run workspace diagnostics:

```bash
autoagent doctor
autoagent doctor --fix
```

Inspect or change the workspace permission mode:

```bash
autoagent permissions show
autoagent permissions set acceptEdits
```

Available permission modes:

| Mode | Behavior |
|------|----------|
| `plan` | Read-only exploration; blocks writes like deploy and review apply |
| `default` | Prompts for risky actions |
| `acceptEdits` | Auto-allows config/memory/model writes, still prompts for deploy/review/MCP |
| `dontAsk` | Auto-allows everything |
| `bypass` | Same practical effect as `dontAsk`; typically reserved for automation |

## 12. Recommended Daily Flow

Once the workspace exists, the normal loop is:

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

If you already trust the current change and want the shortcut:

```bash
autoagent ship --yes
```

## 13. Next Steps

- [CLI Reference](cli-reference.md) — full command surface
- [App Guide](app-guide.md) — how the web console maps onto the product
- [MCP Integration](mcp-integration.md) — connect coding clients and tool servers
- [AutoFix](features/autofix.md) — proposal generation and review loops
- [Prompt Optimization](features/prompt-optimization.md) — optimization concepts and workflows
- [Judge Ops](features/judge-ops.md) — calibration, drift, and human review
- [Registry](features/registry.md) — reusable configs, skills, and contracts
- [Context Workbench](features/context-workbench.md) — context-window diagnostics

## Troubleshooting

**"No workspace found"**

You are outside a workspace directory. Either `cd` into one, or create one:

```bash
autoagent new my-project --template customer-support
```

or

```bash
autoagent init --name my-project
```

**"Provider credentials missing"**

Stay in mock mode while learning:

```bash
autoagent mode set mock
```

Or finish live setup:

```bash
autoagent provider configure
autoagent provider test
autoagent mode set live
```

**"No pending review card"**

Generate fresh improvement output:

```bash
autoagent optimize --cycles 1
```

or

```bash
autoagent autofix suggest
```

**`autoagent compare candidates` prints `No candidate configs found.`**

That command only lists versions already marked as `candidate`, `canary`, `imported`, or `evaluated`. It is optional, not required for the main loop.

**Selectors**

Commands that accept a position argument support selectors such as:

- `latest` — most recently created item
- `active` — currently active item
- `pending` — the next item awaiting action
