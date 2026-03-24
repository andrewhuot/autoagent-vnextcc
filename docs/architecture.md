# Architecture

This document describes the production backend architecture for AutoAgent VNextCC after backend hardening.

## System Topology

```text
┌─────────────────────────────────────────────────────────────────────┐
│                        Operator Interfaces                         │
│  CLI (`autoagent ...`)   REST (`/api/*`)   Web UI (`/`)           │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
                            ┌──────▼──────┐
                            │ FastAPI App │  `api/server.py`
                            │ + TaskMgr   │
                            └──────┬──────┘
                                   │
      ┌────────────────────────────┼───────────────────────────────┐
      │                            │                               │
┌─────▼─────┐               ┌──────▼──────┐                 ┌──────▼──────┐
│ Observer  │               │ Optimizer   │                 │ Eval Runner │
│ metrics + │               │ proposer +  │                 │ fixtures +  │
│ anomalies │               │ gates + sig │                 │ dataset pipe│
└─────┬─────┘               └──────┬──────┘                 └──────┬──────┘
      │                            │                               │
      │                    ┌───────▼────────┐                      │
      │                    │ LLM Router      │                      │
      │                    │ (single/rr/ens) │                      │
      │                    └───┬─────┬──────┘                      │
      │                        │     │                             │
      │            ┌───────────▼┐   ┌▼──────────┐         ┌────────▼────────┐
      │            │OpenAI       │   │Anthropic  │         │Google Gemini    │
      │            │compatible    │   │messages   │         │generateContent  │
      │            └──────────────┘   └───────────┘         └─────────────────┘
      │
┌─────▼─────┐               ┌──────────────┐                 ┌───────────────┐
│ Deployer  │               │ Reliability   │                 │ Logger         │
│ versions +│               │ checkpoint +  │                 │ conversations  │
│ canary    │               │ watchdog + DLQ│                 │ + JSON rotate  │
└─────┬─────┘               └──────┬───────┘                 └──────┬────────┘
      └────────────────────────────┴─────────────────────────────────┘
                                   │
                      ┌────────────▼─────────────────────────────────┐
                      │ Persistent State                             │
                      │ conversations.db                              │
                      │ optimizer_memory.db                           │
                      │ eval_history.db                               │
                      │ configs/*.yaml + manifest.json                │
                      │ .autoagent/loop_checkpoint.json               │
                      │ .autoagent/dead_letters.db                    │
                      │ .autoagent/logs/backend.jsonl (+ rotation)    │
                      └───────────────────────────────────────────────┘
```

## Runtime Configuration (`autoagent.yaml`)

`autoagent.yaml` is now the runtime control file for provider, loop reliability, and eval significance behavior.

### Key Sections

- `optimizer`
  - `use_mock`
  - `strategy`: `single`, `round_robin`, `ensemble`, `mixture`
  - `models[]`: provider/model/api-key-env/rate-limit/cost metadata
  - `retry`: max attempts + backoff + jitter
- `loop`
  - `schedule_mode`: `continuous`, `interval`, `cron`
  - `checkpoint_path`, `dead_letter_db`
  - watchdog + resource warning thresholds
  - structured log rotation settings
- `eval`
  - history DB path
  - dataset defaults
  - significance gate settings (`alpha`, `min_effect_size`, `iterations`)

## Core Services in `app.state`

`api/server.py` initializes and shares:

- `conversation_store`
- `optimization_memory`
- `version_manager`
- `observer`
- `eval_runner`
- `optimizer`
- `deployer`
- `task_manager`
- `ws_manager`
- `runtime_config`
- `dead_letter_queue`
- `checkpoint_store`
- `loop_watchdog`
- `resource_monitor`
- `structured_logger`

## Multi-Model Proposer Architecture

`optimizer/providers.py` introduces a provider abstraction:

- `LLMRequest` and `LLMResponse` are provider-neutral payloads.
- `LLMRouter` supports:
  - `single`
  - `round_robin`
  - `ensemble` (selects highest proposal score)
  - `mixture` (modeled as multi-model comparison path)
- Built-in provider clients:
  - OpenAI chat completions
  - Anthropic messages
  - Google Gemini generateContent
  - OpenAI-compatible/local endpoints
- Reliability controls:
  - Retry with exponential backoff and jitter
  - Per-provider rate limiter (requests/min)
  - Token cost accounting by provider/model

`optimizer/proposer.py` consumes the router and falls back to deterministic mock proposals on provider/parsing failure to keep loops alive.

## Optimization Acceptance Pipeline

Per cycle, `optimizer/loop.py` runs:

1. Validate candidate config against schema.
2. Evaluate baseline and candidate.
3. Apply hard/soft gates:
   - safety hard gate
   - composite improvement gate
   - regression gate
4. Apply paired statistical significance gate.
5. Persist attempt to `optimizer_memory.db`.

Additional attempt fields now persisted:

- `significance_p_value`
- `significance_delta`
- `significance_n`

Possible statuses now include:

- `accepted`
- `rejected_invalid`
- `rejected_safety`
- `rejected_no_improvement`
- `rejected_regression`
- `rejected_not_significant`
- `rejected_noop`

## Real Eval Pipeline

`evals/runner.py` now supports both fixture-based suites and real datasets.

### Data Inputs

- YAML fixture suites (`evals/cases/*.yaml`)
- JSONL datasets
- CSV datasets

### Dataset Features

- explicit `split` support (`train`, `test`, `all`)
- deterministic fallback split assignment when split is missing
- expected tool assertions (`expected_tool`)

### Metric Outputs

Built-in tracked metrics include:

- quality
- safety
- latency
- cost
- tool-use accuracy

Plus custom evaluator registration at runtime:

- `EvalRunner.register_evaluator(name, fn)`
- custom metrics are aggregated into `CompositeScore.custom_metrics`

### Eval Provenance + History

`evals/history.py` persists:

- run summary
- case-level payloads
- provenance (`dataset_path`, `split`, `category`, `agent_fn`)

API endpoints:

- `GET /api/eval/history`
- `GET /api/eval/history/{run_id}`

## Long-Running Reliability

`optimizer/reliability.py` provides:

- `LoopCheckpointStore`
  - crash-safe checkpoint save/load
  - resume support in CLI and API loop paths
- `DeadLetterQueue`
  - failed cycle/event capture with payload + traceback
- `LoopWatchdog`
  - heartbeat stall detection
- `LoopScheduler`
  - `continuous`, `interval`, and `cron` scheduling
- `ResourceMonitor`
  - memory + approximate CPU sampling
- `GracefulShutdown`
  - SIGINT/SIGTERM safe-stop for CLI loop

### CLI Loop Behavior (`autoagent loop`)

The CLI loop is now production-oriented:

- checkpoint/resume (`--resume/--no-resume`, `--checkpoint-file`)
- schedule selection (`--schedule`, `--interval-minutes`, `--cron`)
- graceful termination that finishes current cycle before exit
- DLQ capture for failed cycles
- structured JSON logging with rotation
- resource warning logging

### API Loop Behavior (`/api/loop/*`)

The API loop now mirrors reliability primitives:

- checkpoint-aware start/resume
- scheduler mode support in request body
- watchdog heartbeat/stall reporting
- dead-letter integration
- resource warning logging
- enriched status payload with stall + heartbeat + DLQ count

## Health Endpoints

- `GET /api/health`: metrics/anomalies/failure buckets for optimization readiness
- `GET /api/health/system`: operational health for loop/watchdog/DLQ/task runtime

## Persistence Model

### `conversations.db`

Conversation-level operational telemetry and outcomes.

### `optimizer_memory.db`

Optimization attempts and acceptance metadata including significance fields.

### `eval_history.db`

Durable eval run history with provenance and case-level detail.

### `.autoagent/loop_checkpoint.json`

Checkpoint state for cycle resume.

### `.autoagent/dead_letters.db`

Dead-letter queue for failed loop/eval events.

### `.autoagent/logs/backend.jsonl`

Structured JSON logs with rotation.

## Failure Strategy

- External provider failures degrade gracefully to mock proposer behavior when configured.
- Loop cycle exceptions are captured to DLQ instead of dropping context.
- Watchdog stalls are surfaced as health degradation and DLQ events.
- Task-level exceptions still surface through API task status payloads.

## Extension Points

- Add provider clients under `optimizer/providers.py`.
- Add custom eval metrics via `EvalRunner.register_evaluator`.
- Add richer significance tests under `evals/statistics.py`.
- Extend loop replay/recovery using DLQ payloads.
