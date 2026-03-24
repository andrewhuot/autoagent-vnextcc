# CLI Reference

Complete reference for every `autoagent` command. All commands support `--help` for inline documentation.

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

### `autoagent status`

Show current system status -- active config version, loop state, recent eval scores, and budget usage.

```bash
autoagent status
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
