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
  Workspace:  my-project
  Mode:       mock (simulated — no real API calls)
  Config:     v001 (active)
  Eval score: 0.72 (Promising)
  Pending:    1 review card, 1 autofix proposal
  Next:       autoagent eval run
```

**Mock vs Live**: AutoAgent starts in **mock mode** — all LLM calls are simulated so you can explore without API keys. Switch to live mode when you are ready:

```bash
autoagent mode set live   # requires OPENAI_API_KEY or equivalent
```

Your workspace looks like this:

```
my-project/
├── autoagent.yaml          # project manifest
├── AUTOAGENT.md            # agent instructions (editable)
├── configs/
│   └── v001.yaml           # versioned agent config
├── evals/
│   └── cases/              # eval test cases
└── .autoagent/
    └── workspace.json      # workspace state (do not edit)
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
  ✓ Build complete
    Config:    configs/v002_built_from_prompt.yaml
    Eval cases: evals/cases/generated_build.yaml
    Artifact:  .autoagent/build_artifact_latest.json
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
  Running 12 cases against v002...

  Results:
    Cases:     10/12 passed
    Quality:   0.7800
    Safety:    1.0000 (0 failures)
    Composite: 0.7500

  Next: autoagent improve
```

Show results again anytime:

```bash
autoagent eval show latest
```

The **composite score** (0.0–1.0) blends quality, safety, latency, and cost. Higher is better. A score above 0.85 is production-ready for most use cases.

## 5. Improve the Agent

```bash
autoagent improve
```

This runs the full improvement loop in one command:

1. **Diagnose** — cluster recent failures by type
2. **Propose** — generate a config edit targeting the top failure
3. **Evaluate** — score the candidate config
4. **Accept or reject** — keep the change only if the score improves

You should see:

```
  Diagnosing... found 3 routing_error, 2 unhelpful_response
  Proposing fix for routing_error (dominant failure)
  Evaluating candidate config...
  ✓ composite=0.8200 (+0.0700)
  → Accepted — new config saved as v003

  Next: autoagent eval show latest
```

Compare candidates side by side:

```bash
autoagent compare candidates
```

Run multiple improvement cycles:

```bash
autoagent optimize --cycles 5
```

## 6. Deploy

Review and ship:

```bash
autoagent ship
```

Or step by step:

```bash
autoagent review show pending
autoagent review apply pending
autoagent deploy canary --yes
```

You should see:

```
  ✓ Canary deploy started
    Config:  v003
    Target:  canary (10% traffic)
    Status:  healthy

  Next: autoagent deploy status
```

> **Warning**: `deploy canary` and `deploy immediate` are mutating commands. They push config to your deployment target. Use `--dry-run` to preview first. Deploy is blocked in mock mode — switch to live mode first.

Create a release for audit trail:

```bash
autoagent release create --experiment-id exp-001
```

## 7. Next Steps

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
