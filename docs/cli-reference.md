# CLI Reference

AgentLab groups the default CLI into **Primary** and **Secondary** commands. Run `agentlab advanced` to see the broader hidden command set.

Helpful starting points:

```bash
agentlab --help
agentlab advanced
agentlab <command> --help
```

Notes:

- many top-level commands support `--quiet` / `--no-banner`
- many major commands support `--json` or `--output-format`; check the command help for the exact surface
- selectors like `latest`, `active`, and `pending` are supported on several review, eval, and config commands

---

## Primary Commands

### `agentlab new`

Create a new starter workspace.

```bash
agentlab new my-agent --template customer-support --demo
```

Key options:

- `--template [customer-support|it-helpdesk|sales-qualification|healthcare-intake]`
- `--demo / --no-demo`
- `--mode [mock|live|auto]`

### `agentlab build`

Generate build artifacts from a natural-language prompt, or inspect the latest build output.

Common commands:

```bash
agentlab build "Build a support agent for order tracking"
agentlab build show latest
```

Subcommands:

- `show` — show the latest or selected build artifact

### `agentlab workbench`

Build, inspect, iterate, and materialize a Workbench candidate from the terminal.

Common commands:

```bash
agentlab workbench build "Build a support agent for refund escalations"
agentlab workbench show
agentlab workbench status
agentlab workbench iterate "Add a PII guardrail and missing-order regression eval"
agentlab workbench save
agentlab workbench handoff --json
```

Subcommands:

- `build` — run the Workbench build loop for a natural-language brief
- `show` — show the candidate card, artifacts, validation, readiness, and next step
- `status` — compact readiness view for the latest or selected Workbench project
- `iterate` — apply a follow-up turn to the latest or selected Workbench project
- `save` — materialize the candidate into `configs/` and generated eval cases
- `handoff` — print the typed Workbench Eval/Optimize bridge

Useful options:

- `--project-id TEXT`
- `--target [portable|adk|cx]`
- `--environment TEXT`
- `--mock`
- `--auto-iterate / --no-auto-iterate`
- `--max-iterations INTEGER`
- `--max-seconds INTEGER`
- `--max-tokens INTEGER`
- `--max-cost-usd FLOAT`
- `--json`
- `--output-format [text|json|stream-json]`

`workbench save` writes the generated Workbench candidate into the normal AgentLab workspace, updates the active local config, writes `evals/cases/generated_build.yaml`, and returns an Eval request plus an Optimize request template. It does **not** start Eval, Optimize, AutoFix, review approval, or deployment.

### `agentlab eval`

Run evals, inspect results, compare runs, and generate eval suites.

Common commands:

```bash
agentlab eval run
agentlab eval show latest
agentlab eval list
agentlab eval compare --left-run left.json --right-run right.json
agentlab eval generate --config configs/v001.yaml --output generated_eval_suite.json
agentlab eval results --run-id eval-123
```

Subcommands:

- `run` — run the eval suite against a config
- `show` — show one eval run
- `list` — list recent eval runs
- `compare` — compare run files or run a pairwise config comparison
- `breakdown` — show score bars and failure clusters for the latest run
- `generate` — generate an eval suite from a config
- `results` — inspect structured results, annotate examples, diff runs, or export a run

Useful `eval run` options:

- `--config TEXT`
- `--suite TEXT`
- `--dataset TEXT`
- `--split [train|test|all]`
- `--category TEXT`
- `--output TEXT`
- `--instruction-overrides TEXT`
- `--real-agent`
- `--require-live`
- `--json`
- `--output-format [text|json|stream-json]`

Useful `eval compare` options:

- `--config-a TEXT`
- `--config-b TEXT`
- `--left-run TEXT`
- `--right-run TEXT`
- `--dataset TEXT`
- `--split [train|test|all]`
- `--label-a TEXT`
- `--label-b TEXT`
- `--judge [metric_delta|llm_judge|human_preference]`

Useful `eval results` subcommands:

```bash
agentlab eval results --run-id eval-123 --failures
agentlab eval results diff eval-122 eval-123
agentlab eval results export eval-123 --format markdown
agentlab eval results annotate example_001 --run-id eval-123 --type note --comment "Needs human review"
```

### `agentlab optimize`

Run optimization cycles to improve the current agent config.

```bash
agentlab optimize
agentlab optimize --cycles 5
agentlab optimize --continuous
agentlab optimize --mode advanced
```

Key options:

- `--cycles INTEGER`
- `--continuous`
- `--mode [standard|advanced|research]`
- `--full-auto`
- `--dry-run`
- `--max-budget-usd FLOAT`
- `--json`
- `--output-format [text|json|stream-json]`

### `agentlab deploy`

Deploy a version locally via canary, immediate release, rollback, or auto-review.

```bash
agentlab deploy canary
agentlab deploy status
agentlab deploy --config-version 5 --strategy immediate
agentlab deploy --auto-review --yes
```

Key options:

- `--config-version INTEGER`
- `--strategy [canary|immediate]`
- `--target [agentlab|cx-studio]`
- `--project TEXT`
- `--location TEXT`
- `--agent-id TEXT`
- `--snapshot TEXT`
- `--credentials TEXT`
- `--output TEXT`
- `--push / --no-push`
- `--dry-run`
- `--yes`
- `--json`
- `--output-format [text|json|stream-json]`
- `--auto-review`

### `agentlab status`

Show workspace health, versions, and recommended next steps.

```bash
agentlab status
agentlab status --json
agentlab status --verbose
```

Key options:

- `--db TEXT`
- `--configs-dir TEXT`
- `--memory-db TEXT`
- `--json`
- `--verbose`

### `agentlab doctor`

Run readiness checks for providers, data stores, eval assets, and workspace health.

```bash
agentlab doctor
agentlab doctor --fix
agentlab doctor --json
```

Key options:

- `--config TEXT`
- `--fix`
- `--json`

### `agentlab shell`

Launch the interactive shell.

```bash
agentlab shell
agentlab continue
```

---

## Secondary Commands

### `agentlab config`

Manage versioned config files.

Subcommands:

- `list`
- `show`
- `diff`
- `edit`
- `import`
- `migrate`
- `resolve`
- `rollback`
- `set-active`

Examples:

```bash
agentlab config list
agentlab config show active
agentlab config diff 1 2
agentlab config set-active 3
```

### `agentlab connect`

Import existing runtimes into a new AgentLab workspace.

Subcommands:

- `openai-agents`
- `anthropic`
- `http`
- `transcript`

Examples:

```bash
agentlab connect openai-agents --path ./agent-project
agentlab connect anthropic --path ./claude-project
agentlab connect http --url https://agent.example.com
agentlab connect transcript --file ./conversations.jsonl --name imported-agent
```

### `agentlab instruction`

Inspect, validate, edit, generate, or migrate XML instructions.

Subcommands:

- `show`
- `validate`
- `edit`
- `generate`
- `migrate`

Examples:

```bash
agentlab instruction show
agentlab instruction validate
agentlab instruction generate --brief "refund support agent" --apply
agentlab instruction migrate
```

### `agentlab memory`

Manage `AGENTLAB.md` project memory.

Subcommands:

- `show`
- `add`
- `edit`
- `list`
- `summarize-session`
- `where`

### `agentlab mode`

Show or set execution mode.

Subcommands:

- `show`
- `set`

Examples:

```bash
agentlab mode show
agentlab mode set mock
agentlab mode set live
agentlab mode set auto
```

### `agentlab model`

Inspect or override model preferences.

Subcommands:

- `list`
- `show`
- `set`

Examples:

```bash
agentlab model list
agentlab model show
agentlab model set proposer openai:gpt-4o
```

### `agentlab provider`

Configure and test provider profiles.

Subcommands:

- `configure`
- `list`
- `test`

Examples:

```bash
agentlab provider configure
agentlab provider list
agentlab provider test
```

### `agentlab review`

Review change cards from the optimizer.

Subcommands:

- `list`
- `show`
- `apply`
- `reject`
- `export`

Examples:

```bash
agentlab review list
agentlab review show pending
agentlab review apply pending
agentlab review reject latest
agentlab review export pending
```

### `agentlab template`

List and apply bundled starter templates.

Subcommands:

- `list`
- `apply`

Examples:

```bash
agentlab template list
agentlab template apply customer-support
```

---

## Advanced Commands

Run `agentlab advanced` to see these in the CLI.

| Command | Description |
|---------|-------------|
| `adk` | Google Agent Development Kit integration |
| `autofix` | AutoFix Copilot workflows |
| `benchmark` | Run benchmark suites |
| `build-inspect` | Inspect build artifacts |
| `build-show` | Deprecated alias for `agentlab build show` |
| `changes` | Compatibility aliases for reviewable change cards |
| `compare` | Compare configs, eval runs, and candidate versions |
| `context` | Context Engineering Workbench |
| `continue` | Resume the most recent shell session |
| `curriculum` | Self-play curriculum generation |
| `cx` | Google Cloud CX / Dialogflow CX integration |
| `dataset` | Dataset management |
| `demo` | Demo and presentation commands |
| `diagnose` | Failure diagnosis workflows |
| `edit` | Natural-language config edits |
| `experiment` | Optimization experiment history |
| `explain` | Plain-English agent summary |
| `full-auto` | Full-auto optimization mode |
| `import` | Compatibility aliases for imports |
| `improve` | Deprecated alias; use `optimize` |
| `init` | Deprecated alias; use `new` |
| `intelligence` | Transcript intelligence workflows |
| `judges` | Judge Ops workflows |
| `logs` | Conversation log browsing |
| `loop` | Deprecated loop command; use `optimize --continuous` |
| `mcp` | MCP client and runtime setup |
| `mcp-server` | Start the MCP server |
| `outcomes` | Outcome and business metric ingestion |
| `pause` | Pause the optimization loop |
| `permissions` | Workspace permission mode controls |
| `pin` | Lock a config surface |
| `policy` | Policy optimization artifacts |
| `pref` | Preference collection/export |
| `quickstart` | Run the one-command golden path |
| `registry` | Skills, policies, tools, and handoffs registry |
| `reject` | Reject and roll back an experiment |
| `release` | Signed release objects |
| `replay` | Optimization history replay |
| `resume` | Resume a paused loop |
| `rl` | Policy optimization commands |
| `run` | Legacy run command group |
| `runbook` | Runbook management |
| `scorer` | Natural-language scorer workflows |
| `server` | Start the API server + web console |
| `session` | Shell session management |
| `ship` | Deprecated alias; use `deploy --auto-review` |
| `skill` | Skill management |
| `trace` | Trace analysis and blame maps |
| `unpin` | Remove a surface lock |
| `usage` | Eval/optimize cost and budget reporting |

---

## Common Power Commands

```bash
agentlab advanced
agentlab quickstart
agentlab compare candidates
agentlab eval results export eval-123 --format markdown
agentlab mcp status
agentlab cx auth
agentlab cx list --project PROJECT --location us-central1
```

---

## Deprecated Aliases

These older commands still exist as compatibility aliases, but the current docs use the newer forms.

| Old command | Current command |
|-------------|-----------------|
| `agentlab init` | `agentlab new` |
| `agentlab improve` | `agentlab optimize` |
| `agentlab loop` | `agentlab optimize --continuous` |
| `agentlab ship` | `agentlab deploy --auto-review` |
