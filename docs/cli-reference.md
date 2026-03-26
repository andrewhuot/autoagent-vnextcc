# CLI Reference

Complete reference for all 87 `autoagent` commands. All commands support `--help` for inline documentation.

Quick index: `init`, `server`, `mcp-server`, `full-auto`, `status`, `doctor`, `logs`, `eval`, `optimize`, `config`, `deploy`, `loop`, `pause`, `resume`, `pin`, `unpin`, `reject`, `autofix`, `judges`, `context`, `registry`, `trace`, `scorer`, `quickstart`, `demo`, `edit`, `explain`, `diagnose`, `replay`, `review`, `runbook`, `memory`, `skill`, `cx`, `adk`.

**New in this release:**
- `full-auto` — Dangerous full-auto mode with auto-promotion gates
- `mcp-server` — Model Context Protocol server for AI coding tool integration
- `edit`, `explain`, `diagnose` — Natural language intelligence layer with `--json` output modes
- `cx` group — Dialogflow CX Agent Studio bidirectional integration
- `adk` group — Google Agent Development Kit Python source integration
- All major commands now support `--json` flag for structured output

## Core Commands

### `autoagent init`

Scaffold a new AutoAgent project.

```bash
autoagent init [--template customer-support|minimal] [--dir PATH]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--template` | `customer-support` | Project template to scaffold |
| `--dir` | `.` | Target directory |

Creates `configs/`, `evals/cases/`, and `agent/config/` with starter files.

### `autoagent server`

Start the API server and web console.

```bash
autoagent server [--host HOST] [--port PORT] [--reload]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | `127.0.0.1` | Bind address |
| `--port` | `8000` | Port |
| `--reload` | off | Auto-reload on code changes |

Serves 31 web pages and 131 API endpoints at `http://localhost:8000`.

### `autoagent full-auto`

**DANGEROUS:** Run full autonomous optimization with auto-promotion gates. Requires explicit acknowledgment flag.

```bash
autoagent full-auto [--cycles N] [--max-loop-cycles N] [--acknowledge]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--cycles` | `3` | Initial optimization cycles |
| `--max-loop-cycles` | `10` | Maximum loop cycles |
| `--acknowledge` | required | Must pass to confirm you understand risks |

This mode runs optimize → eval → auto-promote → loop with minimal human oversight. Only use in safe, sandboxed environments.

### `autoagent status`

Show current system status -- active config version, loop state, recent eval scores, and budget usage.

```bash
autoagent status [--db PATH] [--configs-dir DIR] [--memory-db PATH] [--json]
```

| Flag | Description |
|------|-------------|
| `--db` | Conversation database path |
| `--configs-dir` | Config versions directory |
| `--memory-db` | Optimizer memory database path |
| `--json` | Output structured JSON for integration |

**Example output:**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Agent Status
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Overall Score:     0.87 ███████████░░░  GOOD
Safety Score:      1.00 ██████████████  ✓
Routing Accuracy:  0.94 █████████████░  ✓
Avg Latency:       2.1s ██████████████  ✓
Resolution Rate:   0.88 ████████████░░

Active Config:     v12 (deployed 2h ago)
Loop Status:       Running (cycle 4/20)
Budget Used:       $2.40 / $10.00 daily

Failure Breakdown:
  tool_timeout:    █░░░░░░░░░ 8%
  routing_error:   ░░░░░░░░░░ 2%

→ Next: Continue monitoring loop progress
  autoagent loop --max-cycles 20
```

**JSON mode:**
```bash
autoagent status --json | jq '.score'
0.87
```

### `autoagent doctor`

Run diagnostics on your setup -- checks config validity, database connectivity, API keys, and eval suite integrity.

```bash
autoagent doctor [--config PATH]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--config` | `autoagent.yaml` | Config file to validate |

### `autoagent logs`

View structured logs from the optimization loop.

```bash
autoagent logs [--limit N] [--outcome fail|success]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--limit` | `20` | Number of log entries |
| `--outcome` | all | Filter by outcome |

---

## Eval Group

### `autoagent eval run`

Run the eval suite against a config.

```bash
autoagent eval run [--config PATH] [--suite DIR] [--dataset PATH] [--split train|test|all] [--category NAME] [--output FILE]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--config` | active config | Path to config YAML |
| `--suite` | `evals/cases/` | Path to eval cases directory |
| `--dataset` | none | Path to dataset file (.jsonl or .csv) |
| `--split` | `all` | Dataset split to evaluate |
| `--category` | all | Run only a specific category |
| `--output` | none | Write results to JSON file |

### `autoagent eval results`

Display results from a previous eval run.

```bash
autoagent eval results [--run-id ID] [--file PATH]
```

| Flag | Description |
|------|-------------|
| `--run-id` | Look up results by run ID from the history database |
| `--file` | Read results from a JSON file |

### `autoagent eval list`

List all historical eval runs.

```bash
autoagent eval list
```

---

## Optimize

### `autoagent optimize`

Run one or more optimization cycles.

```bash
autoagent optimize [--cycles N] [--db PATH] [--configs-dir DIR] [--memory-db PATH]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--cycles` | `1` | Number of optimization cycles |
| `--db` | `conversations.db` | Conversation database path |
| `--configs-dir` | `configs` | Config versions directory |
| `--memory-db` | `optimizer_memory.db` | Optimization memory database |

---

## Config Group

### `autoagent config list`

List all config versions.

```bash
autoagent config list [--configs-dir DIR]
```

### `autoagent config show`

Display a specific config version.

```bash
autoagent config show [VERSION] [--configs-dir DIR]
```

`VERSION` defaults to the latest active version.

### `autoagent config diff`

Diff two config versions side by side.

```bash
autoagent config diff <v1> <v2> [--configs-dir DIR]
```

---

## Deploy

### `autoagent deploy`

Promote a config version to active.

```bash
autoagent deploy [--config-version VERSION] [--strategy canary|immediate] [--configs-dir DIR] [--db PATH]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--config-version` | latest | Version to deploy |
| `--strategy` | `canary` | Deployment strategy |
| `--configs-dir` | `configs` | Config versions directory |
| `--db` | `conversations.db` | Database path |

Canary deploys route a percentage of traffic to the new config and promote after validation. Immediate deploys switch all traffic instantly.

---

## Loop

### `autoagent loop`

Run the continuous optimization loop.

```bash
autoagent loop [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--max-cycles` | `100` | Maximum cycles before stopping |
| `--stop-on-plateau` | off | Stop when improvements plateau |
| `--delay` | `0` | Delay between cycles (seconds) |
| `--schedule` | `continuous` | Schedule mode: `continuous`, `interval`, `cron` |
| `--interval-minutes` | `5.0` | Interval between cycles (interval mode) |
| `--cron` | `*/5 * * * *` | Cron expression (cron mode) |
| `--checkpoint-file` | `.autoagent/loop_checkpoint.json` | Checkpoint file path |
| `--resume` / `--no-resume` | `--resume` | Resume from checkpoint |
| `--db` | `conversations.db` | Database path |
| `--configs-dir` | `configs` | Config versions directory |
| `--memory-db` | `optimizer_memory.db` | Memory database path |

---

## Human Control

### `autoagent pause`

Pause the running optimization loop. Takes effect after the current cycle completes.

```bash
autoagent pause
```

### `autoagent resume`

Resume a paused optimization loop.

```bash
autoagent resume
```

### `autoagent pin`

Lock a configuration surface so the optimizer cannot modify it.

```bash
autoagent pin <surface>
```

Surfaces: `instruction`, `few_shot`, `tool_description`, `model`, `generation_settings`, `callback`, `context_caching`, `memory_policy`, `routing`.

### `autoagent unpin`

Unlock a previously pinned surface.

```bash
autoagent unpin <surface>
```

### `autoagent reject`

Reject a specific experiment and roll back its changes.

```bash
autoagent reject <experiment_id> [--configs-dir DIR] [--db PATH]
```

---

## AutoFix Group

### `autoagent autofix suggest`

Analyze recent failures and generate fix proposals.

```bash
autoagent autofix suggest
```

### `autoagent autofix apply`

Apply a specific fix proposal.

```bash
autoagent autofix apply <proposal_id>
```

### `autoagent autofix history`

View history of autofix proposals and their outcomes.

```bash
autoagent autofix history [--limit N]
```

---

## Judges Group

### `autoagent judges list`

List all registered judges and their versions.

```bash
autoagent judges list
```

### `autoagent judges calibrate`

Run calibration analysis comparing judge scores to human labels.

```bash
autoagent judges calibrate [--sample N] [--judge-id ID]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--sample` | `50` | Number of cases to sample |
| `--judge-id` | all | Calibrate a specific judge |

### `autoagent judges drift`

Check for judge scoring drift over time.

```bash
autoagent judges drift
```

---

## Context Group

### `autoagent context analyze`

Analyze context window usage for a specific trace.

```bash
autoagent context analyze --trace <trace_id>
```

### `autoagent context simulate`

Simulate compaction strategies and estimate impact.

```bash
autoagent context simulate [--strategy aggressive|balanced|conservative]
```

### `autoagent context report`

Generate a full context health report across recent traces.

```bash
autoagent context report
```

---

## Registry Group

### `autoagent registry list`

List registered items by type.

```bash
autoagent registry list [--type skills|policies|tools|handoffs] [--db PATH]
```

### `autoagent registry show`

Show a specific registry item with version history.

```bash
autoagent registry show <type> <name> [--version N] [--db PATH]
```

### `autoagent registry add`

Add a new item to the registry.

```bash
autoagent registry add <type> <name> --file <path> [--db PATH]
```

### `autoagent registry diff`

Diff two versions of a registry item.

```bash
autoagent registry diff <type> <name> <v1> <v2> [--db PATH]
```

### `autoagent registry import`

Bulk import registry items from a YAML/JSON file.

```bash
autoagent registry import <path> [--db PATH]
```

---

## Trace Group

### `autoagent trace grade`

Grade all spans in a trace using the 7-grader suite.

```bash
autoagent trace grade <trace_id> [--db PATH]
```

### `autoagent trace blame`

Build a blame map of failure clusters over a time window.

```bash
autoagent trace blame [--window 24h] [--top N] [--db PATH]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--window` | `24h` | Time window for analysis |
| `--top` | `10` | Number of top clusters to show |

### `autoagent trace graph`

Render a trace as a span dependency graph.

```bash
autoagent trace graph <trace_id> [--db PATH]
```

---

## Scorer Group

### `autoagent scorer create`

Create a new scorer from a natural language description.

```bash
autoagent scorer create "Score responses on empathy and accuracy" [--name my_scorer]
autoagent scorer create --from-file criteria.txt [--name my_scorer]
```

### `autoagent scorer list`

List all registered scorers.

```bash
autoagent scorer list
```

### `autoagent scorer show`

Display a scorer's spec and dimensions.

```bash
autoagent scorer show <name>
```

### `autoagent scorer refine`

Add criteria to an existing scorer.

```bash
autoagent scorer refine <name> "Also check for conciseness"
```

### `autoagent scorer test`

Test a scorer against a trace.

```bash
autoagent scorer test <name> --trace <trace_id> [--db PATH]
```

---

## Quickstart & Demo

### `autoagent quickstart`

Run the full golden path: init, seed, eval, optimize, deploy.

```bash
autoagent quickstart [--agent-name NAME] [--verbose] [--target-dir DIR] [--auto-open]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--agent-name` | `AutoAgent` | Name for the agent |
| `--verbose` | off | Show detailed output |
| `--target-dir` | `.` | Target directory |
| `--auto-open` | off | Auto-open web console after completion |

### `autoagent demo`

Demo commands for presentations.

Subcommands:
- `autoagent demo quickstart` - Quick demo setup
- `autoagent demo vp` - VP-level 5-minute demo with synthetic data

### `autoagent demo vp`

Run the VP demo with a broken agent scenario.

```bash
autoagent demo vp [--agent-name NAME] [--company NAME] [--no-pause] [--web]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--agent-name` | `Support Bot` | Agent name |
| `--company` | `Your Company` | Company name for the demo |
| `--no-pause` | off | Skip dramatic pauses |
| `--web` | off | Auto-open web console after demo |

---

## Natural Language Commands

### `autoagent edit`

Apply natural language edits to agent config using keyword-to-surface mapping.

```bash
autoagent edit [DESCRIPTION] [--interactive] [--dry-run] [--json]
```

| Flag | Description |
|------|-------------|
| `--interactive` | Interactive mode with confirmation prompts |
| `--dry-run` | Show what would change without applying |
| `--json` | Output results as JSON for piping |

**Examples:**
```bash
autoagent edit "Make the agent more empathetic in billing conversations"
autoagent edit "Add safety guardrails to prevent PII disclosure" --dry-run
autoagent edit "Reduce response latency by tuning timeouts" --json
```

The editor detects keywords (billing, safety, latency, routing, tone, etc.) and maps them to config surfaces (routing.rules, prompts.root, thresholds, tools). Changes are evaluated before applying.

### `autoagent explain`

Generate a plain-English summary of the agent's current state with health assessment.

```bash
autoagent explain [--verbose] [--json] [--db PATH] [--configs-dir DIR] [--memory-db PATH]
```

| Flag | Description |
|------|-------------|
| `--verbose` | Include detailed breakdown of all metrics |
| `--json` | Output structured JSON for integration |
| `--db` | Conversation database path |
| `--configs-dir` | Config versions directory |
| `--memory-db` | Optimizer memory database path |

**Example output:**
```
Agent Health: GOOD (0.82/1.00)

Strengths:
  ✓ Safety score is excellent (1.00)
  ✓ Routing accuracy is strong (0.94)

Weaknesses:
  ⚠ Latency is above SLA (4.2s avg, target: 3.0s)
  ⚠ 12% of conversations are abandoned

Recommendations:
  1. Reduce tool timeout from 10s to 4s
  2. Add retry logic with exponential backoff
  3. Review escalation patterns for abandonment triggers
```

### `autoagent diagnose`

Run failure diagnosis with interactive chat-based root cause exploration.

```bash
autoagent diagnose [--interactive] [--json] [--db PATH] [--configs-dir DIR] [--memory-db PATH]
```

| Flag | Description |
|------|-------------|
| `--interactive` | Interactive chat mode with fix proposals |
| `--json` | Output clusters and insights as JSON |
| `--db` | Conversation database path |
| `--configs-dir` | Config versions directory |
| `--memory-db` | Optimizer memory database path |

**Interactive mode:**
- Clusters failures by root cause
- Provides example conversations for each cluster
- Proposes fixes with confidence scores
- Applies fixes on user confirmation
- Updates AUTOAGENT.md with issue tracking

**Example workflow:**
```bash
autoagent diagnose --interactive

> Issue #1: Billing Misroutes (23 failures)
> Root cause: Missing keywords "invoice", "refund", "charge"
> Fix: Add keywords to routing.rules[billing_agent]
>
> Commands: fix | examples | next | skip
>
> You: fix
>
> ✓ Applied fix. Score: 0.62 → 0.74 (+0.12)
```

### `autoagent replay`

Show optimization history like git log --oneline.

```bash
autoagent replay [--limit N]
```

---

## Change Review

### `autoagent review list`

List pending change cards from the optimizer.

```bash
autoagent review list [--limit N]
```

### `autoagent review show`

Show details of a specific change card.

```bash
autoagent review show <card_id>
```

### `autoagent review apply`

Apply a change card.

```bash
autoagent review apply <card_id>
```

### `autoagent review reject`

Reject a change card with a reason.

```bash
autoagent review reject <card_id> --reason "reason text"
```

### `autoagent review export`

Export a change card to a file.

```bash
autoagent review export <card_id>
```

---

## Runbooks

### `autoagent runbook list`

List available runbooks.

```bash
autoagent runbook list
```

### `autoagent runbook show`

Show details of a specific runbook.

```bash
autoagent runbook show <name>
```

### `autoagent runbook apply`

Apply a runbook to the agent.

```bash
autoagent runbook apply <name>
```

### `autoagent runbook create`

Create a new runbook from a file.

```bash
autoagent runbook create <name> --file <path>
```

---

## Memory

### `autoagent memory show`

Display the project memory (AUTOAGENT.md).

```bash
autoagent memory show
```

### `autoagent memory add`

Add a note to project memory.

```bash
autoagent memory add <note> [--section SECTION]
```

---

## Executable Skills

### `autoagent skill list`

List available executable skills.

```bash
autoagent skill list [--category CAT] [--platform PLATFORM] [--json]
```

### `autoagent skill show`

Show details of a specific skill.

```bash
autoagent skill show <name> [--version N]
```

### `autoagent skill recommend`

Get skill recommendations based on failure patterns.

```bash
autoagent skill recommend [--json]
```

### `autoagent skill apply`

Apply a skill to the agent.

```bash
autoagent skill apply <name>
```

### `autoagent skill install`

Install a skill from a file.

```bash
autoagent skill install <path>
```

### `autoagent skill export`

Export a skill to a file.

```bash
autoagent skill export <name> [--output-path PATH]
```

### `autoagent skill stats`

Show skill usage statistics.

```bash
autoagent skill stats [--top N]
```

### `autoagent skill learn`

Learn new skills from recent optimization patterns.

```bash
autoagent skill learn [--limit N]
```

---

## CX Integration

### `autoagent cx list`

List CX agents in a project.

```bash
autoagent cx list --project PROJECT --location LOCATION [--credentials PATH]
```

### `autoagent cx import`

Import a CX agent into AutoAgent format.

```bash
autoagent cx import --project PROJECT --location LOCATION --agent-id AGENT_ID \
  --output-dir DIR [--credentials PATH] [--include-test-cases]
```

### `autoagent cx export`

Export optimized config back to CX Agent Studio.

```bash
autoagent cx export --project PROJECT --location LOCATION --agent-id AGENT_ID \
  --config-path CONFIG --snapshot-path SNAPSHOT [--credentials PATH] [--dry-run]
```

### `autoagent cx deploy`

Deploy agent to a CX environment.

```bash
autoagent cx deploy --project PROJECT --location LOCATION --agent-id AGENT_ID \
  --environment ENV [--credentials PATH]
```

### `autoagent cx status`

Show CX agent deployment status.

```bash
autoagent cx status --project PROJECT --location LOCATION --agent-id AGENT_ID \
  [--credentials PATH]
```

### `autoagent cx widget`

Generate a chat-messenger web widget HTML file.

```bash
autoagent cx widget --project PROJECT --location LOCATION --agent-id AGENT_ID \
  [--title TITLE] [--color COLOR] [--output-path PATH]
```

---

## ADK Integration

### `autoagent adk import`

Import an Agent Development Kit agent.

```bash
autoagent adk import --path PATH --output OUTPUT
```

### `autoagent adk export`

Export to ADK format.

```bash
autoagent adk export --path PATH [--output OUTPUT] --snapshot SNAPSHOT [--dry-run]
```

### `autoagent adk deploy`

Deploy an ADK agent.

```bash
autoagent adk deploy --path PATH --target TARGET --project PROJECT --region REGION
```

### `autoagent adk status`

Show ADK agent status.

```bash
autoagent adk status --path PATH [--json]
```

### `autoagent adk diff`

Diff an ADK agent against a snapshot.

```bash
autoagent adk diff --path PATH --snapshot SNAPSHOT
```

---

## MCP Server

### `autoagent mcp-server`

Start MCP server for AI coding tool integration.

```bash
autoagent mcp-server [--port PORT]
```

| Flag | Description |
|------|-------------|
| `--port` | HTTP/SSE port (default: stdio mode). Note: HTTP/SSE mode not yet implemented. |

By default runs in stdio mode for Claude Code, Codex, and other AI coding assistants that support the Model Context Protocol.

**Stdio mode only:** The MCP server currently only supports stdio transport. HTTP/SSE mode will be added in a future release.

**Example usage with Claude Code:**

Add to your MCP config file:

```json
{
  "mcpServers": {
    "autoagent": {
      "command": "autoagent",
      "args": ["mcp-server"]
    }
  }
}
```

---

## Config Migration

### `autoagent config migrate`

Migrate old config format to new schema.

```bash
autoagent config migrate <input_file> [--output FILE]
```

