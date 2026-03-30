# AutoAgent Quick Start Guide

Get from zero to a deployed agent in under 10 minutes.

## 1. Install AutoAgent

```bash
pip install autoagent
```

Requirements: Python 3.11+, macOS / Linux / WSL.

> **From Source**: Clone the repo, then `pip install -e .` inside a virtualenv.

## 2. Create a Workspace

```bash
autoagent new my-project --template customer-support --demo
cd my-project
autoagent status
```

You should see the status home screen:

```
AutoAgent Status
━━━━━━━━━━━━━━━━━
  Workspace:  my-project
  Mode:       MOCK
  Config:     v001 — gemini-2.0-flash | You are AutoAgent, a customer support...
  Eval score: n/a (never)
  Safety:     0.117
  Pending:    1 review card(s), 1 autofix proposal(s)
  Deployment: active v001
  Models:     openai:gpt-4o | anthropic:claude-sonnet-4-5
  MCP:        0 server(s)
  Memory:     1 active source(s)

  Next step:  autoagent quickstart
```

**Mock vs Live**: AutoAgent starts in **mock mode** — all LLM calls are simulated so you can explore without API keys. Switch to live mode when you are ready:

```bash
autoagent mode set live   # requires OPENAI_API_KEY or equivalent
autoagent mode show       # verify current mode and provider status
```

Your workspace looks like this:

```
my-project/
├── autoagent.yaml          # runtime config (models, budgets, loop settings)
├── AUTOAGENT.md            # agent instructions (editable project memory)
├── configs/
│   ├── v001.yaml           # versioned agent config (active)
│   └── v001_base.yaml      # base config snapshot
├── evals/
│   └── cases/              # eval test cases
└── .autoagent/
    ├── workspace.json      # workspace state (mode, metadata)
    ├── settings.json        # permission mode and CLI settings
    └── sessions/            # shell session history
```

**Glossary**:
- **Workspace** — a project directory with configs, evals, and state
- **Config** — a versioned YAML file defining agent behavior
- **Eval suite** — test cases that score your agent
- **Trace** — a recorded agent conversation with timing and tool calls
- **Review card** — a proposed change awaiting approval
- **Release** — a promoted config snapshot ready for deployment

## 3. Build Your First Agent

```bash
autoagent build "Build a customer support agent for order tracking, refunds, and cancellations"
```

You should see:

```
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
  Config:   configs/v002_built_from_prompt.yaml
  Evals:    evals/cases/generated_build.yaml
  Artifact: .autoagent/build_artifact_latest.json

Next step:
  autoagent eval run
```

Inspect the build output:

```bash
autoagent build show latest
```

**What gets created**: The `build` command generates a config file (the agent definition) and an eval suite (test cases). The build artifact is metadata — the config is what matters.

**Starting points**: You can build from a prompt (shown above), from transcripts (`intelligence import` then `intelligence generate-agent`), or by importing an existing config (`config import my-config.yaml`).

## 4. Run Evals

```bash
autoagent eval run
```

You should see:

```
✦ Running the gauntlet. Truth comes from test cases.

Full eval suite
  Cases: 53/55 passed
  Quality:   0.9764  (95% CI 0.9400..1.0000)
  Safety:    0.9818 (1 failures)
  Latency:   0.9756
  Cost:      0.8472
  Composite: 0.9582  (95% CI 0.9363..0.9739)
  Tokens:    16804  |  Est. USD: $0.000000

  Mood: Flying

  Next actions:
    → autoagent optimize --cycles 3
    → autoagent status
```

Show results again anytime:

```bash
autoagent eval show latest
```

The **composite score** (0.0–1.0) blends quality, safety, latency, and cost. Higher is better. A score above 0.85 is production-ready for most use cases.

## 5. Improve the Agent

### One-shot improvement

```bash
autoagent improve
```

This runs the full improvement loop in one command:

1. **Evaluate** — run the current eval suite
2. **Diagnose** — cluster recent failures by type
3. **Propose** — generate a fix targeting the top failure
4. **Prompt** — asks whether to apply the top proposal (use `--auto` to skip the prompt)

You should see:

```
✦ Improve

Eval composite: 0.9582
AutoAgent Diagnosis
───────────────────
Found 6 failure cluster(s) across 11 total failures.

  1. safety_violation — 7 failures (11.7% impact)
  2. timeout — 2 failures (3.3% impact)
  3. unhelpful_response — 2 failures (3.3% impact)

Suggested fixes: 1
  Top proposal: abc12345 (few_shot_edit, risk=low, expected_lift=50.0%)

Apply the top proposal now (abc12345)? [y/N]:
```

### Multi-cycle optimization

```bash
autoagent optimize --cycles 5
```

This runs multiple rounds of diagnose-propose-evaluate-accept/reject. Each accepted change bumps the config version.

### Compare candidates side by side

```bash
autoagent compare candidates
```

## 6. Review and Deploy

### Quick ship (review + canary deploy in one step)

```bash
autoagent ship --yes
```

### Step by step

```bash
autoagent review show pending       # inspect the top pending review card
autoagent review apply pending      # accept it
autoagent deploy canary --yes       # deploy as canary (10% traffic)
```

You should see:

```
✦ Ship
  Pending review items: 1
Applied: created release rel-abc12345
  Deploying: v001 from configs/v001.yaml
  Target:    autoagent canary
Applied: deployed v001 as canary
```

> **Warning**: `deploy canary` and `deploy immediate` are mutating commands. They push config to your deployment target. Use `--dry-run` to preview first. Deploy is blocked in mock mode — switch to live mode first.

Create a release for audit trail:

```bash
autoagent release create --experiment-id exp-001
```

## 7. Interactive Shell

Launch an interactive shell session inside your workspace:

```bash
autoagent shell
```

You'll see a status bar and prompt:

```
  AutoAgent Shell
  [my-project | v001 | 1 reviews]
  Type /help for commands, or enter free text.

autoagent>
```

**Slash commands** inside the shell:

| Command     | Action                          |
|-------------|---------------------------------|
| `/status`   | Show workspace status           |
| `/config`   | Show active config info         |
| `/memory`   | Show AUTOAGENT.md contents      |
| `/doctor`   | Run workspace diagnostics       |
| `/review`   | Show pending review cards       |
| `/mcp`      | Show MCP integration status     |
| `/compact`  | Save session summary to disk    |
| `/resume`   | Resume the most recent session  |
| `/exit`     | Exit the shell                  |

**Free-text input** is routed automatically — type "evaluate my agent" and it runs `autoagent eval run`. Type "deploy" and it routes to the deploy flow.

### Sessions

Sessions are persisted automatically. Resume a previous session:

```bash
autoagent continue              # resume the most recent session
autoagent session list           # list all sessions
autoagent session delete <id>    # delete a session
```

## 8. Models, Usage, and Providers

### See which models are active

```bash
autoagent model show
```

```
Effective models
  Proposer:  openai:gpt-4o
  Evaluator: anthropic:claude-sonnet-4-5
```

### Override the proposer or evaluator model

```bash
autoagent model list                           # see available models
autoagent model set proposer anthropic:claude-sonnet-4-5
```

### Monitor spending

```bash
autoagent usage
```

```
AutoAgent Usage
━━━━━━━━━━━━━━━
Last eval: tokens=16804 cost=$0.00
Last optimize: n/a
Workspace spend: $0.00
Configured budget: $10.00
Budget remaining: $10.00
```

### Configure providers

```bash
autoagent provider configure    # interactive provider setup
autoagent provider list         # show configured providers
```

## 9. MCP Integration

Connect workspace-scoped MCP servers for tool use:

```bash
autoagent mcp add my-tool --command "npx" --arg "-y" --arg "@my/tool-server"
autoagent mcp list              # list configured MCP servers
autoagent mcp inspect my-tool   # inspect a specific server
autoagent mcp remove my-tool    # remove a server
```

## 10. Diagnostics

Run `doctor` to check workspace health:

```bash
autoagent doctor
autoagent doctor --fix          # auto-repair fixable issues
```

Doctor checks: workspace structure, config state, API keys, mock/live mode, memory sources, MCP runtime, data stores, and eval history.

## 11. Permissions

AutoAgent supports permission modes that control which actions require confirmation:

| Mode          | Behavior                                                     |
|---------------|--------------------------------------------------------------|
| `plan`        | Blocks all writes — read-only exploration                    |
| `default`     | Prompts before deploy, review apply, MCP, and model changes  |
| `acceptEdits` | Auto-allows config/memory/model writes, prompts for deploys  |
| `dontAsk`     | Allows everything without prompting                          |

View or change the permission mode in `.autoagent/settings.json`:

```json
{
  "permissions": {
    "mode": "default"
  }
}
```

## 12. Next Steps

- **[Skills & Registry Guide](guides/skills-and-registry.md)** — install and manage reusable agent skills
- **[Scoring & Judges Guide](guides/scoring-and-judges.md)** — create custom scorers and calibrate judges
- **[Transcript Intelligence Guide](guides/transcript-intelligence.md)** — learn from real conversations
- **[MCP Integration Guide](guides/mcp-integration.md)** — connect to Claude Code, Cursor, Codex
- **[Context Engineering Guide](guides/context-engineering.md)** — optimize token usage and context windows
- **[Continuous Optimization Guide](guides/continuous-optimization.md)** — run overnight improvement loops
- **[Command Reference](COMMAND_REFERENCE.md)** — every command with examples

## Troubleshooting

**"No workspace found"**
You are outside a workspace directory. Run `autoagent init --name my-project` or `cd` into an existing workspace.

**"No active config"**
No config version is set as active. Run `autoagent config list` to see versions, then `autoagent config set-active <version>`.

**"Provider credentials missing"**
You are in live mode but no API key is set. Export `OPENAI_API_KEY` or run `autoagent mode set mock` to use simulated mode.

**"No pending review card"**
No changes are waiting for approval. Run `autoagent optimize --cycles 1` to generate a candidate, or `autoagent autofix suggest`.

**"Deploy blocked in mock mode"**
Switch to live mode first: `autoagent mode set live`. Deploy requires real API credentials.

**Selectors**: Commands that accept a position argument support these selectors:
- `latest` — the most recently created item
- `active` — the currently active item (configs only)
- `pending` — the first item awaiting action (review cards, autofix proposals)
