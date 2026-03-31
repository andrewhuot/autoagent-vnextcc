# Deployment Guide

This guide covers local, Docker, and Google Cloud deployment for AutoAgent VNextCC.

## Deployment Targets

- Local developer machine (fast iteration)
- Docker Compose (single-node packaged runtime)
- Cloud Run (managed production entry point)

## Prerequisites

- Python 3.11+
- Node.js 20+ (for local frontend build/dev)
- Docker 24+ (for containerized deployment)
- `gcloud` CLI (for Cloud Run)

## 1) Local Runtime

For day-to-day local development, `./start.sh` is the easiest path because it starts:

- the backend on port `8000`
- the Vite frontend on port `5173`

```bash
./start.sh
```

Open:

- UI: `http://localhost:5173/dashboard`
- API docs: `http://localhost:8000/docs`

Use `autoagent server` when you want the backend to serve the built web console directly from port `8000`.

## Install

```bash
pip install -e ".[dev]"
```

## Initialize a workspace

```bash
autoagent new my-project
cd my-project
```

## Start API + web console

```bash
autoagent server --host 0.0.0.0 --port 8000
```

Endpoints:
- UI: `http://localhost:8000`
- OpenAPI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- WebSocket: `ws://localhost:8000/ws`

## Optional: Frontend dev mode

```bash
# terminal A
autoagent server

# terminal B
cd web
npm install
npm run dev
```

In dev mode, use the Vite URL for HMR while backend stays on port 8000.

## 2) Docker Compose

Repository includes:
- `Dockerfile` (multi-stage build: frontend then Python app)
- `docker-compose.yaml` (runtime + persistent volume)

## Build and run

```bash
docker compose up --build
```

This starts the full app on port 8000.

## Stop and keep data

```bash
docker compose down
```

## Stop and reset data

```bash
docker compose down -v
docker compose up --build
```

## Container storage layout

`docker-compose.yaml` mounts named volume `autoagent-data` to `/app/data`.

Env vars in compose:

```yaml
environment:
  - AUTOAGENT_DB=/app/data/conversations.db
  - AUTOAGENT_CONFIGS=/app/data/configs
  - AUTOAGENT_MEMORY_DB=/app/data/optimizer_memory.db
  - AUTOAGENT_EVAL_HISTORY_DB=/app/data/eval_history.db
```

Health check:
- `GET /api/health` every 30 seconds
- `GET /api/health/system` every 30 seconds

## 3) Cloud Run (Recommended Managed Production)

Cloud Run is the simplest managed option for this architecture.

## Build image

```bash
export PROJECT_ID="your-project"
export REGION="us-central1"

gcloud builds submit --tag "gcr.io/${PROJECT_ID}/autoagent-vnextcc"
```

## Deploy

```bash
gcloud run deploy autoagent-vnextcc \
  --image "gcr.io/${PROJECT_ID}/autoagent-vnextcc" \
  --platform managed \
  --region "${REGION}" \
  --port 8000 \
  --cpu 2 \
  --memory 1Gi \
  --min-instances 1 \
  --max-instances 10 \
  --allow-unauthenticated \
  --set-env-vars "AUTOAGENT_DB=/app/data/conversations.db" \
  --set-env-vars "AUTOAGENT_CONFIGS=/app/data/configs" \
  --set-env-vars "AUTOAGENT_MEMORY_DB=/app/data/optimizer_memory.db"
```

## Important Cloud Run caveat

Cloud Run local filesystem is ephemeral.

If you need durable data, move persistence out of local disk:
- conversation store -> managed database
- optimizer memory -> managed database
- config YAML/manifest -> durable object store or DB-backed config table

Until this migration is done, treat Cloud Run as stateless compute only.

## 4) Environment Variables

Runtime paths:

| Variable | Default | Purpose |
|---|---|---|
| `AUTOAGENT_DB` | `conversations.db` | Conversation SQLite path |
| `AUTOAGENT_CONFIGS` | `configs` | Versioned config directory |
| `AUTOAGENT_MEMORY_DB` | `optimizer_memory.db` | Optimization memory SQLite path |
| `AUTOAGENT_EVAL_HISTORY_DB` | unset | Optional eval history SQLite path override |

Other useful env:

| Variable | Typical value | Purpose |
|---|---|---|
| `PYTHONUNBUFFERED` | `1` | Flush logs immediately in containers |
| `OPENAI_API_KEY` | secret | OpenAI proposer/judge provider key |
| `ANTHROPIC_API_KEY` | secret | Anthropic proposer/judge provider key |
| `GOOGLE_API_KEY` | secret | Gemini proposer/judge provider key |

`autoagent.yaml` controls provider selection, retries, scheduling mode, checkpoint path, DLQ DB path, and structured log settings.

## 5) Reverse Proxy and Networking Notes

If running behind a proxy/load balancer:
- preserve WebSocket upgrade support for `/ws`
- forward `X-Forwarded-*` headers as appropriate
- ensure idle timeout allows long task polling and websocket sessions

## 6) Production Hardening Checklist

Before customer-facing deployment:

- Add auth at ingress/API gateway layer
- Restrict CORS from `*` to known origins
- Enforce TLS everywhere
- Add request/response logging policy that excludes secrets/PII
- Add backup/retention strategy for conversation + optimization data
- Add alerting for health and safety regressions
- Document rollback runbook for bad canary decisions

## 7) Smoke Test After Deploy

Run from any shell with network access to the service:

```bash
# health
curl -sS "https://<service-url>/api/health"

# system runtime health
curl -sS "https://<service-url>/api/health/system"

# start eval
curl -sS -X POST "https://<service-url>/api/eval/run" \
  -H "Content-Type: application/json" \
  -d '{}'

# list eval tasks
curl -sS "https://<service-url>/api/eval/runs"

# deployment status
curl -sS "https://<service-url>/api/deploy/status"
```

Expected:
- `/api/health` returns 200 JSON payload
- `/api/health/system` returns 200 with loop/watchdog status
- eval start returns `202` with `task_id`
- runs endpoint includes task status progression
- deploy status returns active/canary metadata

## 8) Operational Monitoring

Minimum recommended monitors:
- service availability (`/api/health`)
- loop runtime health (`/api/health/system`)
- task failure rate (`/api/tasks` and logs)
- safety violation rate
- success rate trend
- canary verdict outcomes (promote vs rollback)

Recommended alert thresholds (starting point):
- success rate < 70% for 5 minutes -> critical
- error rate > 20% for 5 minutes -> critical
- safety violations > 0 -> critical
- latency p95 above internal SLO -> warning/critical per policy

## 9) Common Deployment Issues

## Frontend not loading on `/`

Cause:
- `web/dist` missing inside runtime image or local workspace

Fix:

```bash
cd web
npm install
npm run build
```

Then restart the server/container.

## WebSocket updates not arriving

Cause:
- proxy not configured for websocket upgrade

Fix:
- enable websocket upgrade for `/ws`
- confirm browser can connect to `ws://.../ws` or `wss://.../ws`

## Data disappears between restarts

Cause:
- ephemeral filesystem

Fix:
- mount persistent volume (Docker)
- migrate persistence to managed storage (Cloud Run / K8s)
