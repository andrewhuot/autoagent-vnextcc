# AgentLab Repo Audit — Directory & Module Inventory
**Audit date:** 2026-04-12  
**Auditor:** Claude Sonnet 4.6  
**Branch:** audit/full-repo-understanding-claude-sonnet

---

## Repository Identity

| Field | Value |
|-------|-------|
| Product | AgentLab — agent optimization platform |
| Version | 3.0.0 (CHANGELOG) / 1.0.0 (pyproject.toml — stale) |
| Language split | Python (backend, CLI, eval, optimizer) + TypeScript/React (web console) |
| Entry point | `runner.py` → Click CLI; `api/server.py` → FastAPI ASGI |
| Test suite | 240 Python test files + 53 frontend unit test files + 11 Playwright E2E specs |
| Key docs | README.md, BUILDER_CONTRACT.md, OPTIMIZATION_COMPONENTS_AUDIT.md, findings.md |

---

## Top-Level Directory Map

| Directory | Role | Key files |
|-----------|------|-----------|
| `a2a/` | Agent-to-Agent protocol (Google A2A spec) | agent_card.py, handler.py, server.py, discovery.py |
| `adk/` | Google Agent Development Kit integration | importer.py, exporter.py, mapper.py, parser.py, deployer.py |
| `adapters/` | External agent import adapters | workspace_builder.py, openai_agents_adapter.py, http_adapter.py |
| `agent/` | Agent config schema and runtime models | config/schema.py, config/runtime.py |
| `agent_skills/` | Agent skill generation/analysis | store.py, generator.py, gaps.py |
| `api/` | FastAPI application | server.py, main.py, routes/ (59 route modules), tasks.py |
| `assistant/` | Chat-based assistant agent | agent.py, events.py, intent_extractor.py, builder.py |
| `builder/` | Workbench builder agent + harness | harness.py, workbench_agent.py, workbench.py, events.py, store.py |
| `cicd/` | CI/CD gate | gate.py, github_action.yml |
| `cli/` | CLI command implementations | ~28 modules per command group |
| `collaboration/` | Multi-user review workflows | review.py |
| `configs/` | Default/starter agent configs | v001_base.yaml |
| `context/` | Context window workbench | analyzer.py, simulator.py, compaction.py |
| `control/` | Human-in-the-loop control | policy.py, human_control_store.py |
| `core/` | Core shared types and primitives | types.py, skills/store.py, skills/types.py, project_memory.py |
| `cx_studio/` | Google Dialogflow CX integration | auth.py, client.py, importer.py, exporter.py, deployer.py |
| `data/` | Data models, dataset management | episode_types.py, outcome_types.py, dataset_store.py, event_log.py |
| `deploy/` | Cloud deployment scripts | deploy.sh (GCP), cloudbuild.yaml, fly.toml, railway.toml, cloud-run-service.yaml |
| `deployer/` | Deployer class + canary logic | canary.py, versioning.py, release_manager.py, lineage.py |
| `docs/` | Product documentation | 27 files covering guides, features, architecture |
| `evals/` | Eval runner, scorer, data engine | runner.py, scorer.py, data_engine.py, anti_goodhart.py, statistics.py, replay.py |
| `examples/` | Usage examples | — |
| `graders/` | Eval grader implementations | llm_judge.py, deterministic.py, similarity.py, stack.py, calibration.py |
| `judges/` | Judge versioning and calibration | versioning.py, calibration.py, drift_monitor.py |
| `logger/` | Structured logging | event_logger.py, middleware.py |
| `mcp_server/` | MCP server (22 tools, 5 prompts) | server.py, tools.py, prompts.py, resources.py |
| `multi_agent/` | Multi-agent orchestration | teams.py, graph.py, blame.py |
| `notifications/` | Notification manager | manager.py, store.py |
| `observer/` | Observability: traces, opportunities, blame | traces.py, opportunities.py, blame_map.py, trace_grading.py, knowledge_store.py |
| `optimizer/` | Optimization loop, search, mutations | loop.py, proposer.py, search.py, mutations.py, experiments.py, memory.py, pareto.py, gates.py, autofix.py, cost_tracker.py, reliability.py, surface_inventory.py |
| `policy_opt/` | Policy optimization (DPO/RLHF stubs) | orchestrator.py, backends.py, artifact_registry.py, safety_guard.py |
| `portability/` | Model portability reporting | report.py |
| `registry/` | Modular registry (skills/policies/tools/handoffs) | store.py, skill_store.py |
| `rewards/` | Reward modeling | registry.py, scalarizer.py, types.py |
| `runner.py` | Main CLI entrypoint (~445KB) | All Click commands |
| `shared/` | Cross-layer shared contracts | build_artifact_store.py, contracts/ |
| `simulator/` | Adversarial simulator | simulator.py |
| `stores/` | Store configuration | skill_store_config.py |
| `tests/` | Test suite (240+ files) | conftest.py, helpers.py, api/, evals/, fixtures/ |
| `web/` | React frontend | src/pages/ (79 pages), src/components/ (80+), src/lib/ (34 modules) |

---

## Backend: API Layer

**Framework:** FastAPI with async context manager lifespan  
**Entry:** `api/server.py` → instantiates ~40 stores/services at startup  
**CORS:** All origins (dev-friendly, not production-hardened)  
**WebSocket:** Single `/ws` endpoint for real-time progress  
**SPA serving:** `web/dist/` with index.html fallback

### Route Module Count: 59 modules under `api/routes/`

Key route groups:

| Group | Prefix | What it serves |
|-------|--------|----------------|
| Core pipeline | `/api/eval`, `/api/optimize`, `/api/loop` | Run/monitor optimization loop |
| Builder | `/api/builder`, `/api/workbench` | Workbench builds and streaming |
| Agent/Config | `/api/agents`, `/api/config` | Agent library and version management |
| Deploy | `/api/deploy` | Canary + deploy lifecycle |
| Observability | `/api/traces`, `/api/opportunities`, `/api/experiments` | Evidence and experiment tracking |
| Skills | `/api/skills`, `/api/agent-skills`, `/api/registry` | Skill ecosystem |
| Intelligence | `/api/intelligence`, `/api/assistant` | Transcript analysis and chat |
| Integrations | `/api/adk`, `/api/cx-studio`, `/api/connect`, `/api/a2a` | External frameworks |
| Governance | `/api/judges`, `/api/scorers`, `/api/autofix`, `/api/control` | Judge ops, autofix, policy |
| Infra | `/api/health`, `/api/settings`, `/api/notifications`, `/api/events` | Ops and config |

### Unused/stub modules in `api/routes/`
- `auth.py`, `rbac.py` — authentication/authorization stubs not wired into middleware
- `billing.py`, `metering.py`, `sla.py` — SaaS billing/metering stubs (not integrated)
- `multi_tenant.py` — multi-tenancy stubs (not enforced)

---

## Builder / Harness Stack

| File | Role |
|------|------|
| `builder/harness.py` | `HarnessExecutionEngine` — Plan→Execute→Reflect→Present phases |
| `builder/workbench_agent.py` | `MockWorkbenchBuilderAgent` + `LiveWorkbenchBuilderAgent` |
| `builder/workbench.py` | `WorkbenchService` — orchestrates runs, applies operations |
| `builder/events.py` | `EventBroker` + `DurableEventStore` — SSE streaming + SQLite durability |
| `builder/store.py` | `BuilderStore` — SQLite persistence for sessions/artifacts/proposals |
| `builder/contract.py` | Contract loader for `BUILDER_CONTRACT.md` |
| `builder/workbench_plan.py` | `PlanTask` tree + `WorkbenchArtifact` models |
| `builder/specialists.py` | Specialist router for multi-agent coordination |
| `builder/chat_service.py` | `BuilderChatService` — **in-memory** session store (no restart persistence) |

**Key behavioral note:** `BUILDER_CONTRACT.md` is a detailed spec that is parsed by `contract.py` into metadata. The harness is closely faithful to the contract phases and event sequence. No significant divergence found.

---

## Optimizer / Eval Stack

| File | Role |
|------|------|
| `optimizer/loop.py` | `Optimizer` — orchestrates one cycle: observe→propose→eval→gate |
| `optimizer/proposer.py` | `Proposer` — generates config mutations |
| `optimizer/search.py` | `HybridSearchOrchestrator` — multi-candidate bandit search |
| `optimizer/mutations.py` | `MutationRegistry` — 9+ typed operators |
| `optimizer/experiments.py` | `ExperimentStore` — full experiment lifecycle tracking |
| `optimizer/memory.py` | `OptimizationMemory` — persists accepted/rejected attempts |
| `optimizer/pareto.py` | `ConstrainedParetoArchive` — multi-objective dominance filtering |
| `optimizer/gates.py` | `check_constraints()` — safety/regression hard gates |
| `optimizer/autofix.py` | `AutoFixEngine` — failure analysis → constrained proposals |
| `optimizer/reliability.py` | `LoopWatchdog`, `DeadLetterQueue`, `ResourceMonitor` |
| `optimizer/surface_inventory.py` | Documents which surfaces are live vs nominal |
| `evals/runner.py` | `EvalRunner` — runs test cases, scores, caches results |
| `evals/scorer.py` | `ConstrainedScorer` + 11-dimension `DimensionScores` |
| `evals/data_engine.py` | `EvalSetManager` + `TraceToEvalConverter` |
| `evals/anti_goodhart.py` | Dual holdout + judge variance + drift detection |
| `evals/statistics.py` | `paired_significance()`, clustered bootstrap, sequential testing |
| `observer/opportunities.py` | `FailureClusterer` → `OptimizationOpportunity` priority queue |
| `observer/blame_map.py` | `BlameMap` — failure cluster impact + trend analysis |
| `observer/trace_grading.py` | `TraceGrader` + 7 span-level graders |

---

## Frontend

| Area | Details |
|------|---------|
| Framework | React 19 + TypeScript + Vite |
| Router | React Router DOM 7 |
| State | Zustand (workbench) + TanStack React Query (server state) |
| Styling | Tailwind CSS 4 |
| Charts | Recharts |
| Page count | 79 route-mapped pages |
| Component count | ~80+ top-level components + workbench/ builder/ assistant/ subdirs |
| API module | `lib/api.ts` (105KB) — 223+ useQuery/useMutation hooks |
| Streaming | Three protocols: WebSocket (/ws), EventSource (builder), fetch-stream (workbench) |
| E2E tests | 11 Playwright specs in `/web/tests/` |

---

## Persistence Layer: SQLite Databases

| Database | Default path | Owned by |
|----------|-------------|---------|
| conversations.db | `$AGENTLAB_DB` | ConversationStore |
| optimizer_memory.db | `$AGENTLAB_MEMORY_DB` | OptimizationMemory |
| traces.db | `.agentlab/traces.db` | TraceStore |
| experiments.db | `.agentlab/experiments.db` | ExperimentStore |
| opportunities.db | `.agentlab/opportunities.db` | OpportunityQueue |
| outcomes.db | `.agentlab/outcomes.db` | OutcomeStore |
| event_log.db | `.agentlab/event_log.db` | EventLog |
| builder_events.db | `.agentlab/builder_events.db` | DurableEventStore |
| datasets.db | `.agentlab/datasets.db` | DatasetStore |
| eval_results.db | `.agentlab/eval_results.db` | EvalResultsStore |
| knowledge.db | `.agentlab/knowledge.db` | KnowledgeStore |
| skills.db | `$AGENTLAB_SKILL_DB` | SkillStore |
| registry.db | `$AGENTLAB_REGISTRY_DB` | RegistryStore |
| eval_cache.db | `.agentlab/eval_cache.db` | EvalCacheStore |
| cost_tracker.db | `.agentlab/cost_tracker.db` | CostTracker |

**Total:** 15+ distinct SQLite databases, all initialized on first use.  
**Note:** All SQLite — no PostgreSQL option. Not suitable for multi-instance deployments.

---

## Deployment Infrastructure

| Target | Mechanism |
|--------|-----------|
| Local dev | `make dev` → `./start.sh` (Python backend + Vite frontend) |
| Docker | `docker-compose.yaml` — single service, persistent volume |
| Google Cloud Run | `deploy/deploy.sh`, `deploy/cloudbuild.yaml`, `deploy/cloud-run-service.yaml` |
| Fly.io | `deploy/fly.toml` |
| Railway | `deploy/railway.toml` |
| CI/CD gate | `.github/workflows/agent-quality.yml` → `agentlab eval run --gate` |

---

## Test Suite Summary

| Layer | Files | Estimated tests |
|-------|-------|----------------|
| Backend Python (pytest) | 240 files | ~2,000+ |
| Frontend unit (Vitest) | 53 files | ~200-300 |
| Frontend E2E (Playwright) | 11 files | ~50-100 |

Well-tested: core optimizer, eval/judge/grader, builder/harness, skills, ADK/CX integration  
**Gaps:** `a2a/` (0 tests), `multi_agent/` (0 tests), `logger/` (0 tests), `collaboration/` (sparse), `context/` (sparse)

---

## Key Config Files

| File | Purpose |
|------|---------|
| `agentlab.yaml` | Runtime config — optimizer strategy, models, loop schedule, eval settings, budgets |
| `.env.example` | Required/optional environment variables |
| `pyproject.toml` | Python packaging, deps, pytest config |
| `configs/v001_base.yaml` | Default starter agent config (customer support router) |
| `BUILDER_CONTRACT.md` | Behavioral contract for the builder agent |
| `OPTIMIZATION_COMPONENTS_AUDIT.md` | Candid self-audit of optimizer surface coverage |
| `findings.md` | Large (40KB) internal findings/analysis document |
