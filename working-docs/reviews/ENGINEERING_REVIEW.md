# Engineering Review — AutoAgent VNextCC

**Date**: 2026-03-24
**Reviewer**: Claude Opus 4.6
**Baseline**: 1,131 tests passing, 0 circular imports

---

## 1. Architecture Assessment

### Package Dependency Graph

```
runner.py (CLI) ──→ agent.config, deployer, evals, logger, observer, optimizer, registry
api/server.py  ──→ agent.config, deployer, evals, logger, observer, optimizer, context, data, judges, registry

core/types.py     ← No inbound deps from other packages (leaf)
evals/            ← Depends on: evals.fixtures (internal only)
optimizer/        ← Depends on: agent.config, evals, observer, data
observer/         ← Depends on: logger
deployer/         ← Depends on: logger (via ConversationStore)
judges/           ← Depends on: core.types
graders/          ← Self-contained
registry/         ← Self-contained (SQLite-backed)
context/          ← Self-contained
logger/           ← Self-contained (SQLite + rotating JSON logs)
data/             ← Self-contained (event log)
control/          ← Self-contained
```

**Verdict**: No circular imports detected. Clean DAG. The `api/server.py` lifespan is the composition root — it wires everything together at startup, which is the correct pattern. All heavy imports are deferred to lifespan scope.

### Module Cohesion

| Package | Responsibility | Cohesion |
|---------|---------------|----------|
| `core/` | Domain objects (10 types) | High — pure data, no side effects |
| `evals/` | Test case loading, scoring, replay, statistics | High |
| `optimizer/` | Search, mutations, Pareto, bandit, cost tracking, prompt opt | Medium — large surface, but responsibilities are well-factored into submodules |
| `observer/` | Health metrics, anomaly detection, failure clustering, traces | High |
| `judges/` | Grader stack (deterministic → LLM → audit) | High |
| `graders/` | Lower-level grading primitives | High |
| `deployer/` | Canary, versioning, release management | High |
| `registry/` | Skills, policies, tool contracts, handoff schemas | High |
| `api/` | 16 route modules, models, tasks, websocket | High — clean separation per domain |
| `logger/` | SQLite store + structured JSON logging | High |
| `context/` | Context analysis, simulation, metrics | High |
| `data/` | Event log, repositories | High |

**Verdict**: Good cohesion across the board. The `optimizer/` package is the largest (~26 files) but responsibilities are split into focused modules.

### API Surface Area

- **38 REST endpoints** across 16 route modules
- **1 WebSocket** endpoint for real-time updates
- All routes use `/api/` prefix consistently
- Response models defined in `api/models.py`
- Tags used for OpenAPI grouping

**Verdict**: Large but well-organized. Each route module owns one domain. No redundant endpoints found.

### Data Flow — Request Lifecycle

```
1. HTTP Request → FastAPI router → route handler
2. Route handler reads from app.state (composition root)
3. Business logic delegates to domain services:
   - eval run → EvalRunner.run() → CompositeScorer.score()
   - optimize → Optimizer.optimize() → Proposer + Gates + Significance
   - loop → background task → cycles of observe→optimize→deploy
4. State persisted to SQLite (conversations, eval history, optimizer memory, etc.)
5. WebSocket broadcasts progress updates to connected clients
6. Response returned as JSON
```

---

## 2. Deployment Readiness

### What's Good Already

- Dockerfile exists (multi-stage: Node frontend build → Python 3.11-slim)
- docker-compose.yaml exists with health checks and persistent volume
- Health endpoints: `/api/health`, `/api/health/system`, `/api/health/cost`, `/api/health/scorecard`
- Structured JSON logging with rotation (`logger/structured.py`)
- Runtime config via `autoagent.yaml` with Pydantic validation and sensible defaults
- All DB paths configurable via env vars
- HEALTHCHECK in Dockerfile

### What's Missing for Production

| Gap | Severity | Fix |
|-----|----------|-----|
| No `.env.example` documenting required/optional env vars | Medium | Create it |
| No `.dockerignore` — builds include .venv, .git, *.db, node_modules | High | Create it |
| Dockerfile missing several packages added since initial build (core/, control/, data/, judges/, graders/, registry/, context/) | **Critical** | Fix COPY directives |
| No deploy/ directory — no Cloud Run, fly.io, or Railway configs | Medium | Create them |
| No Makefile for common tasks | Medium | Create it |
| CORS allows all origins (`*`) — fine for dev, needs tightening for prod | Low | Document; make configurable |
| No readiness probe distinct from liveness (health endpoint does DB work) | Low | Add lightweight `/api/ready` |
| README test count says 862 (stale — actual is 1,131) | Low | Update |
| No `gunicorn` for production multi-worker serving | Low | Add to Dockerfile CMD option |

### Database: SQLite → Postgres Migration Path

Current state: 7 SQLite databases (conversations, eval_history, optimizer_memory, cost_tracker, traces, opportunities, experiments, registry). All use simple key-value or append-only patterns.

**Migration path**: Not needed for single-instance deployment (Cloud Run scales to 1). SQLite is correct for this use case — the platform is single-tenant research tooling, not a multi-user SaaS. If Postgres is needed later, all stores use a thin abstraction layer that could be swapped.

### Config Management

- Runtime config: `autoagent.yaml` → Pydantic-validated `RuntimeConfig`
- Env vars: `AUTOAGENT_DB`, `AUTOAGENT_CONFIGS`, `AUTOAGENT_MEMORY_DB`, `AUTOAGENT_REGISTRY_DB`, `AUTOAGENT_TRACE_DB`, `AUTOAGENT_EVAL_HISTORY_DB`
- API keys: `GOOGLE_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` (referenced by name in config, read at runtime)

### Error Handling

- Optimizer: full try/catch with dead letter queue for unrecoverable failures
- Loop: checkpoint/resume, graceful shutdown, watchdog timeout
- API: FastAPI exception handlers, HTTPException for 4xx/5xx
- Event logging: append-only audit trail

**Verdict**: Solid error handling patterns. The dead letter queue + checkpoint/resume is production-grade.

---

## 3. Google Cloud Deployment Plan

### Recommended: Cloud Run (serverless, scales to zero)

**Why Cloud Run**:
- Single container, no orchestration needed
- Scales to zero when idle (cost-efficient for research tooling)
- Built-in HTTPS, load balancing, revision management
- SQLite works fine with Cloud Run (single instance, persistent volume via Cloud Storage FUSE or just ephemeral for stateless eval runs)

### Architecture on GCP

```
Cloud Build → Artifact Registry → Cloud Run
                                      ↓
                              Cloud Run Volume Mount
                              (for SQLite persistence)
                                      ↓
                              Secret Manager
                              (API keys)
```

### For Non-GCP Users

- **Plain Docker**: `docker compose up` (already works)
- **fly.io**: Single-command deploy with persistent volume
- **Railway**: Zero-config from Dockerfile

---

## 4. Developer Experience

### Current State
- `pip install -e ".[dev]"` works
- `python runner.py server` starts API
- `python -m pytest tests/` runs 1,131 tests in ~3s
- `autoagent` CLI available after install

### What's Needed
- `make dev` to start everything in one command
- `make test` / `make lint` shortcuts
- `make docker-build` / `make docker-run`
- `make deploy` for one-command GCP deployment
- `.env.example` so new developers know what to set

---

## 5. Issues Fixed in This PR

1. **Dockerfile**: Fixed missing COPY directives for core/, control/, data/, judges/, graders/, registry/, context/
2. **`.dockerignore`**: Created to exclude .venv, .git, *.db, node_modules, __pycache__
3. **`.env.example`**: Created with all required/optional env vars documented
4. **`deploy/`**: Created with Cloud Run service YAML, cloudbuild.yaml, deploy.sh, fly.toml, railway.toml
5. **`Makefile`**: Created with setup, dev, test, lint, build, deploy, docker-run targets
6. **README.md**: Updated test count and added deployment section with working instructions
7. **Readiness endpoint**: Added lightweight `/api/ready` endpoint
