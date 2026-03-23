# FAQ and Troubleshooting

This FAQ focuses on the most common operational issues with AutoAgent VNextCC.

## Quick Triage Checklist

When something looks wrong, run these first:

```bash
autoagent status
autoagent config list
autoagent logs --limit 20
curl -sS http://localhost:8000/api/health
curl -sS http://localhost:8000/api/tasks
```

These five checks usually tell you whether the issue is data, config, task execution, or serving.

## Installation and Startup

## `autoagent` command not found

Cause:
- package not installed in current environment
- virtual environment not activated

Fix:

```bash
pip install -e ".[dev]"
which autoagent
autoagent --version
```

## Server starts, but web UI says frontend not found

Cause:
- `web/dist` does not exist

Fix:

```bash
cd web
npm install
npm run build
cd ..
autoagent server
```

## Port 8000 already in use

Fix:
- run on a different port

```bash
autoagent server --port 8010
```

Then use `http://localhost:8010`.

## CLI and Task Behavior

## I started an eval/optimize call via API, but nothing seems to happen

Check task state:

```bash
curl -sS http://localhost:8000/api/tasks
curl -sS http://localhost:8000/api/tasks/<task_id>
```

If task status is `failed`, inspect `error` in the response.

## Why does eval detail return 409 sometimes?

`GET /api/eval/runs/{run_id}` returns `409` while a run is still active.

Wait for completion, or poll:

```bash
curl -sS http://localhost:8000/api/tasks/<run_id>
```

## Can I force optimization when health is fine?

- CLI `autoagent optimize` does not expose a `--force` flag.
- API supports it:

```bash
curl -X POST http://localhost:8000/api/optimize/run \
  -H "Content-Type: application/json" \
  -d '{"window":100,"force":true}'
```

## Evaluations

## How do I run eval on a specific config version?

Use CLI with config file path:

```bash
autoagent eval run --config configs/v003.yaml
```

Or API with `config_path`:

```bash
curl -X POST http://localhost:8000/api/eval/run \
  -H "Content-Type: application/json" \
  -d '{"config_path":"configs/v003.yaml"}'
```

## How do I run one category only?

CLI:

```bash
autoagent eval run --category safety
```

API:

```bash
curl -X POST http://localhost:8000/api/eval/run \
  -H "Content-Type: application/json" \
  -d '{"category":"safety"}'
```

## My scores look unrealistic

Things to check:
- eval cases are too easy/hard for your domain
- latency/cost normalization constants in `evals/scorer.py`
- agent fixture behavior if you are still using mock responses

## Optimization and Gates

## Why was my candidate rejected?

Check optimize history:

```bash
curl -sS http://localhost:8000/api/optimize/history
```

Typical statuses:
- `rejected_safety`
- `rejected_no_improvement`
- `rejected_regression`
- `rejected_invalid`
- `rejected_noop`

## Optimizer keeps proposing bad changes

Actions:
- increase conversation quality/volume for better failure samples
- verify failure buckets are meaningful in real traffic
- inspect recent attempts in `optimizer_memory.db`
- improve proposer prompt/logic in `optimizer/proposer.py`

## Deployment and Canary

## How do I deploy a specific version immediately?

CLI:

```bash
autoagent deploy --config-version 5 --strategy immediate
```

API:

```bash
curl -X POST http://localhost:8000/api/deploy \
  -H "Content-Type: application/json" \
  -d '{"version":5,"strategy":"immediate"}'
```

## How do I rollback a canary?

```bash
curl -X POST http://localhost:8000/api/deploy/rollback
```

If no canary is active, API returns `400`.

## Canary is stuck in pending

Likely causes:
- not enough canary conversations yet
- low traffic volume

By default, canary needs a minimum sample before verdict.

## Conversations and Data

## No data appears on Dashboard or Conversations

The observer/dashboard depend on conversation records.

Generate signal by:
- running evals
- sending real traffic through your agent runtime
- ensuring logger writes to expected DB path

Check DB path alignment:
- `AUTOAGENT_DB`

## Where are configs and versions stored?

- YAML files: `configs/vNNN.yaml`
- manifest: `configs/manifest.json`

Inspect quickly:

```bash
autoagent config list
autoagent config show
```

## How do I reset local state?

```bash
rm -f conversations.db optimizer_memory.db
rm -rf configs
autoagent init
```

For Docker:

```bash
docker compose down -v
docker compose up --build
```

## Web UI and WebSocket

## Command palette does not open

Use `Cmd+K` (macOS) or `Ctrl+K` (Windows/Linux).

If it still fails:
- click the “Command Palette” button in the top header
- confirm keyboard focus is not inside an input field

## Live updates are not appearing

Check WebSocket path and proxy behavior:
- endpoint must be `/ws`
- reverse proxy must allow websocket upgrades

Browser devtools should show a live websocket connection to `/ws`.

## Development and Testing

## What should I run before committing changes?

Backend:

```bash
pytest
```

Frontend:

```bash
cd web
npm run lint
npm run build
```

## Tests fail only in my environment

Common causes:
- stale virtualenv
- stale node modules
- missing optional dependencies

Reset approach:

```bash
# python env
pip install -e ".[dev]"

# frontend deps
cd web
rm -rf node_modules package-lock.json
npm install
npm run lint
npm run build
```

