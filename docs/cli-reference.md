# CLI Reference

The `autoagent` CLI is the primary operator interface.

## Global

### `autoagent --version`

Returns installed CLI version.

### `autoagent --help`

Shows command groups and top-level commands.

---

## `autoagent init`

Scaffold project structure and starter assets.

### Synopsis

```bash
autoagent init [--template customer-support|minimal] [--dir PATH]
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--template` | choice | `customer-support` | Template preset |
| `--dir` | string | `.` | Target directory |

### Example

```bash
autoagent init --template customer-support
```

Expected output (shape):

```text
Initialized AutoAgent project in ...
  Template: customer-support
  Config:   configs/v001_base.yaml
  Evals:    evals/cases/
```

### Related

- `autoagent eval run`
- `autoagent server`

---

## `autoagent eval run`

Run eval suite against a config.

### Synopsis

```bash
autoagent eval run [--config PATH] [--suite DIR] [--category NAME] [--output FILE]
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--config` | string | active/default | Config YAML path |
| `--suite` | string | built-in suite | Eval cases directory |
| `--category` | string | all | Run only one category |
| `--output` | string | none | Write JSON result file |

### Example

```bash
autoagent eval run --config configs/v003.yaml --output results.json
```

Expected output (shape):

```text
Full eval suite
  Cases: X/Y passed
  Quality:   0.xxxx
  Safety:    0.xxxx
  Latency:   0.xxxx
  Cost:      0.xxxx
  Composite: 0.xxxx
```

### Related

- `autoagent eval results`
- `autoagent eval list`

---

## `autoagent eval results`

Display previously saved eval results.

### Synopsis

```bash
autoagent eval results [--file FILE] [--run-id ID]
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--file` | string | none | JSON results file from `eval run --output` |
| `--run-id` | string | none | Future server-backed lookup path |

### Example

```bash
autoagent eval results --file results.json
```

### Related

- `autoagent eval run`
- `autoagent eval list`

---

## `autoagent eval list`

List local result JSON files.

### Synopsis

```bash
autoagent eval list
```

### Options

No options.

### Example

```bash
autoagent eval list
```

### Related

- `autoagent eval run`

---

## `autoagent optimize`

Run one or more optimization cycles from CLI.

### Synopsis

```bash
autoagent optimize [--cycles N] [--db PATH] [--configs-dir DIR] [--memory-db PATH]
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--cycles` | int | `1` | Number of optimize cycles |
| `--db` | string | `conversations.db` | Conversation DB path |
| `--configs-dir` | string | `configs` | Config version directory |
| `--memory-db` | string | `optimizer_memory.db` | Optimization memory DB |

### Example

```bash
autoagent optimize --cycles 3
```

### Related

- `autoagent loop`
- `autoagent status`

---

## `autoagent config list`

Show version history and active/canary markers.

### Synopsis

```bash
autoagent config list [--configs-dir DIR]
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--configs-dir` | string | `configs` | Config directory |

### Example

```bash
autoagent config list
```

### Related

- `autoagent config show`
- `autoagent config diff`

---

## `autoagent config show`

Print YAML for active or specific version.

### Synopsis

```bash
autoagent config show [VERSION] [--configs-dir DIR]
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| `VERSION` | int | active | Version number |
| `--configs-dir` | string | `configs` | Config directory |

### Example

```bash
autoagent config show 3
```

### Related

- `autoagent config list`
- `autoagent config diff`

---

## `autoagent config diff`

Diff two versioned configs.

### Synopsis

```bash
autoagent config diff V1 V2 [--configs-dir DIR]
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| `V1` | int | required | Source version |
| `V2` | int | required | Target version |
| `--configs-dir` | string | `configs` | Config directory |

### Example

```bash
autoagent config diff 1 4
```

### Related

- `autoagent config list`
- `autoagent config show`

---

## `autoagent deploy`

Deploy a version via canary or immediate strategy.

### Synopsis

```bash
autoagent deploy [--config-version N] [--strategy canary|immediate] [--configs-dir DIR] [--db PATH]
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--config-version` | int | latest | Version to deploy/promote |
| `--strategy` | choice | `canary` | Rollout strategy |
| `--configs-dir` | string | `configs` | Config directory |
| `--db` | string | `conversations.db` | Conversation DB path |

### Example

```bash
autoagent deploy --config-version 5 --strategy canary
```

### Related

- `autoagent config list`
- `autoagent status`

---

## `autoagent loop`

Run continuous autoresearch loop.

### Synopsis

```bash
autoagent loop [--max-cycles N] [--stop-on-plateau] [--delay S] [--db PATH] [--configs-dir DIR] [--memory-db PATH]
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--max-cycles` | int | `50` | Max cycles to run |
| `--stop-on-plateau` | flag | off | Stop after repeated no-improvement |
| `--delay` | float | `1.0` | Delay between cycles (seconds) |
| `--db` | string | `conversations.db` | Conversation DB path |
| `--configs-dir` | string | `configs` | Config directory |
| `--memory-db` | string | `optimizer_memory.db` | Optimization memory DB |

### Example

```bash
autoagent loop --max-cycles 20 --stop-on-plateau --delay 2
```

### Related

- `autoagent optimize`
- `autoagent status`

---

## `autoagent status`

Show health, versions, and recent optimization attempts.

### Synopsis

```bash
autoagent status [--db PATH] [--configs-dir DIR] [--memory-db PATH]
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--db` | string | `conversations.db` | Conversation DB path |
| `--configs-dir` | string | `configs` | Config directory |
| `--memory-db` | string | `optimizer_memory.db` | Optimization memory DB |

### Example

```bash
autoagent status
```

### Related

- `autoagent logs`
- `autoagent optimize`

---

## `autoagent logs`

Browse recent conversation logs.

### Synopsis

```bash
autoagent logs [--limit N] [--outcome success|fail|error|abandon] [--db PATH]
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--limit` | int | `20` | Number of records |
| `--outcome` | choice | all | Filter outcome |
| `--db` | string | `conversations.db` | Conversation DB path |

### Example

```bash
autoagent logs --limit 50 --outcome fail
```

### Related

- `autoagent status`
- `autoagent eval run`

---

## `autoagent server`

Start FastAPI + web console serving.

### Synopsis

```bash
autoagent server [--host HOST] [--port PORT] [--reload]
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--host` | string | `0.0.0.0` | Bind host |
| `--port` | int | `8000` | Bind port |
| `--reload` | flag | off | Dev autoreload |

### Example

```bash
autoagent server --port 8000 --reload
```

Expected startup output:

```text
Starting AutoAgent VNextCC server on 0.0.0.0:8000
  API docs:     http://localhost:8000/docs
  Web console:  http://localhost:8000
  WebSocket:    ws://localhost:8000/ws
```

### Related

- `autoagent eval run`
- `autoagent optimize`

---

## Hidden Legacy Group

`autoagent run ...` remains for backward compatibility but should not be used for new automation.
