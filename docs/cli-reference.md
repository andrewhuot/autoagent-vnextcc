# CLI Reference

AutoAgent shows 15 commands by default (8 primary + 7 secondary). Run `autoagent advanced` to see all commands.

All commands support `--help`. Major commands support `--json` for structured output.

---

## Primary Commands

### `autoagent new`

Create a new starter workspace and print the first three commands to run.

```
Usage: autoagent new [OPTIONS] NAME

Options:
  --template [customer-support|it-helpdesk|sales-qualification|healthcare-intake]
                                  Starter template.  [default: customer-support]
  --demo / --no-demo              Seed a reviewable demo workspace.  [default: no-demo]
  --mode [mock|live|auto]         Runtime mode for the generated workspace.
                                  Explicit `auto` uses API-key detection.
                                  [default: auto]
```

**Example:**
```bash
autoagent new my-agent --template customer-support
```

---

### `autoagent build`

Build agent artifacts or inspect the latest build output.

```
Usage: autoagent build [OPTIONS] COMMAND [ARGS]...

Commands:
  show    Show build output.
```

**Examples:**
```bash
autoagent build "Build a support agent for order tracking"
autoagent build show latest
```

---

### `autoagent eval`

Evaluate agent configs against test suites.

```
Usage: autoagent eval [OPTIONS] COMMAND [ARGS]...

Commands:
  run         Run eval suite against a config.
  show        Show eval results.
  list        List recent eval runs.
  compare     Show a side-by-side comparison of two eval runs.
  breakdown   Show score breakdown bars and failure clusters.
  generate    AI-generate a comprehensive eval suite from agent config.
  results     View eval results from a previous run.
```

**Examples:**
```bash
autoagent eval run
autoagent eval show latest
autoagent eval compare left.json right.json
autoagent eval generate --config configs/v001.yaml --output generated_eval_suite.json
```

---

### `autoagent optimize`

Run optimization cycles to improve agent config. Replaces the old `improve` and `loop` commands.

```
Usage: autoagent optimize [OPTIONS]

Options:
  --cycles INTEGER                Number of optimization cycles.  [default: 1]
  --continuous                    Loop indefinitely until Ctrl+C.
  --mode [standard|advanced|research]
                                  Optimization mode (replaces --strategy).
  --db TEXT                       Conversation store DB.  [default: conversations.db]
  --configs-dir TEXT              Configs directory.  [default: configs]
  --memory-db TEXT                Optimizer memory DB.  [default: optimizer_memory.db]
  --full-auto                     Danger mode: auto-promote accepted configs
                                  without manual review.
  --dry-run                       Preview without mutating state.
  --max-budget-usd FLOAT          Stop when spend reaches this amount.
  --output-format [text|json|stream-json]
                                  Render text, a final JSON envelope, or
                                  stream JSON progress events.  [default: text]
  -j, --json                      Output as JSON.
```

**Examples:**
```bash
autoagent optimize                        # Single cycle
autoagent optimize --cycles 5             # Five cycles
autoagent optimize --continuous           # Loop until Ctrl+C (replaces `autoagent loop`)
autoagent optimize --mode advanced        # Advanced search strategy
```

---

### `autoagent deploy`

Deploy a config version with canary, release, and rollback workflows. Use `--auto-review` to apply pending review cards before deploying (replaces the old `ship` command).

```
Usage: autoagent deploy [OPTIONS] [[canary|immediate|release|rollback|status]]

Options:
  --config-version INTEGER        Config version to deploy.
  --strategy [canary|immediate]   Deployment strategy.  [default: canary]
  --configs-dir TEXT              Configs directory.  [default: configs]
  --db TEXT                       Conversation store DB.  [default: conversations.db]
  --target [autoagent|cx-studio]  Deployment target.  [default: autoagent]
  --project TEXT                  GCP project ID (required for CX push).
  --location TEXT                 CX agent location.  [default: global]
  --agent-id TEXT                 CX agent ID (required for CX push).
  --snapshot TEXT                 CX snapshot JSON path from `autoagent cx import`.
  --credentials TEXT              Path to service account JSON for CX calls.
  --output TEXT                   Output path for CX export package JSON.
  --push / --no-push              Push to CX now (otherwise package only).
                                  [default: no-push]
  --dry-run                       Preview without mutating state.
  --yes                           Skip interactive confirmation.
  -j, --json                      Output as JSON.
  --output-format [text|json|stream-json]
                                  Render text, a final JSON envelope, or
                                  stream JSON progress events.  [default: text]
  --auto-review                   Apply pending review cards and create a
                                  release before deploying (replaces ship).
```

**Examples:**
```bash
autoagent deploy canary                   # Canary deploy latest accepted config
autoagent deploy --config-version 5       # Deploy specific version
autoagent deploy --strategy immediate     # Immediate (no canary)
autoagent deploy canary --yes             # Skip confirmation
autoagent deploy --auto-review            # Review + deploy (replaces `autoagent ship`)
```

---

### `autoagent status`

Show system health, config versions, and recent activity.

```
Usage: autoagent status [OPTIONS]

Options:
  --db TEXT           Conversation store DB.  [default: conversations.db]
  --configs-dir TEXT  Configs directory.  [default: configs]
  --memory-db TEXT    Optimizer memory DB.  [default: optimizer_memory.db]
  -j, --json          Output as JSON.
  -v, --verbose       Show extra details (conversations, cycles, token usage).
```

---

### `autoagent doctor`

Check system health and configuration. Reports on API keys, mode, data stores, eval cases, and config versions.

```
Usage: autoagent doctor [OPTIONS]

Options:
  --config TEXT  Path to runtime config YAML.  [default: autoagent.yaml]
  --fix          Automatically repair fixable workspace issues.
  -j, --json     Output as JSON.
```

---

### `autoagent shell`

Launch the interactive AutoAgent shell.

```
Usage: autoagent shell [OPTIONS]
```

---

## Secondary Commands

### `autoagent config`

Manage agent config versions.

```
Commands:
  list        List all config versions.
  show        Show config YAML for a version.
  diff        Diff two config versions.
  edit        Open active config in editor.
  import      Import a plain YAML/JSON into versioned store.
  migrate     Migrate old config format.
  rollback    Roll back to a prior version.
  set-active  Set workspace default config version.
```

---

### `autoagent memory`

Project memory — manage AUTOAGENT.md persistent context.

```
Commands:
  show               Show AUTOAGENT.md contents.
  add                Add a note to a section.
  edit               Edit a layered memory target.
  list               List layered memory sources.
  summarize-session  Write session summary into AUTOAGENT.md.
  where              Show memory file locations.
```

---

### `autoagent mode`

Show or set CLI execution mode.

```
Commands:
  show  Show current mode and configured providers.
  set   Persist mode preference (auto, mock, or live).
```

AutoAgent auto-detects mode based on available API keys. Use `mode set` to override.

---

### `autoagent model`

Inspect and override workspace model preferences.

```
Commands:
  list  List available runtime models.
  show  Show effective proposer and evaluator models.
  set   Persist a model override.
```

---

### `autoagent provider`

Configure and validate workspace provider settings.

```
Commands:
  configure  Interactively configure a provider profile.
  list       List configured providers.
  test       Validate provider credentials.
```

---

### `autoagent review`

Review proposed change cards from the optimizer.

```
Commands:
  list    List pending change cards.
  show    Show a specific change card.
  apply   Accept a change card.
  reject  Reject a change card with a reason.
  export  Export a change card as markdown.
```

---

### `autoagent template`

List and apply bundled starter workspace templates.

```
Commands:
  list   Show bundled starter templates.
  apply  Apply a template to the current workspace.
```

---

## Advanced Commands

Run `autoagent advanced` to see these. They are fully functional but hidden from default help.

| Command | Description |
|---------|-------------|
| `adk` | Google ADK integration — import, export, deploy |
| `autofix` | AutoFix Copilot — reviewable improvement proposals |
| `benchmark` | Run standard benchmarks |
| `build-inspect` | Inspect build artifacts |
| `build-show` | Deprecated alias for `autoagent build show` |
| `changes` | Aliases for reviewable optimizer change cards |
| `compare` | Compare configs, eval runs, and candidate versions |
| `context` | Context Engineering Workbench — diagnose and tune context |
| `continue` | Resume the most recent shell session |
| `curriculum` | Self-play curriculum generator for adversarial eval prompts |
| `cx` | Google Cloud CX Agent Studio — import, export, deploy |
| `dataset` | Manage datasets for evaluation and training |
| `demo` | Demo commands for presentations and quick trials |
| `diagnose` | Run failure diagnosis and optionally fix issues |
| `edit` | Apply natural language edits to agent config |
| `experiment` | Inspect optimization experiment history |
| `explain` | Generate plain-English summary of agent config |
| `full-auto` | Run optimization + loop in full-auto mode |
| `import` | Import configs and resources |
| `improve` | *(deprecated)* Use `optimize` instead |
| `init` | *(deprecated)* Use `new` instead |
| `intelligence` | Run transcript intelligence workflows |
| `judges` | Judge Ops — monitoring, calibration, human feedback |
| `logs` | Browse conversation logs |
| `loop` | *(deprecated)* Use `optimize --continuous` instead |
| `mcp` | Configure AutoAgent MCP integration |
| `mcp-server` | Start MCP server for AI coding tools |
| `outcomes` | Manage business outcome data |
| `pause` | Pause the optimization loop |
| `permissions` | Inspect or change workspace permission mode |
| `pin` | Lock a config surface from mutation |
| `policy` | Policy management — inspect trained policy artifacts |
| `pref` | Preference collection and export |
| `quickstart` | Run the full golden path (init → seed → eval → optimize → summary) |
| `registry` | Modular registry — skills, policies, tools, handoffs |
| `reject` | Reject and rollback an experiment |
| `release` | Manage signed release objects |
| `replay` | Show optimization history |
| `resume` | Resume the optimization loop |
| `rl` | Policy optimization commands |
| `run` | Legacy run commands |
| `runbook` | Runbooks — curated bundles of skills and policies |
| `scorer` | NL Scorer — create eval scorers from natural language |
| `server` | Start the API server + web console |
| `session` | Manage shell sessions |
| `ship` | *(deprecated)* Use `deploy --auto-review` instead |
| `skill` | Skill management — build-time and run-time skills |
| `trace` | Trace analysis — grading, blame maps, and graphs |
| `unpin` | Remove immutable marking from a config surface |
| `usage` | Show recent eval/optimize cost and budget state |

---

## Deprecated Command Migration

| Old Command | New Equivalent |
|-------------|---------------|
| `autoagent init` | `autoagent new` |
| `autoagent improve` | `autoagent optimize` |
| `autoagent loop` | `autoagent optimize --continuous` |
| `autoagent ship` | `autoagent deploy --auto-review` |

The old commands still work as aliases but are hidden from default help.
