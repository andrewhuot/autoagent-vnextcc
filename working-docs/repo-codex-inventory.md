# AgentLab Repo Inventory - Codex Notes

## Scope And Evidence

This inventory maps the current implementation in this checkout of `/Users/andrew/Desktop/agentlab-repo-notes-codex` on branch `audit/repo-comprehensive-notes-codex`. It is based on the required product docs, direct code reads, route and command inventories, representative tests, and specialist read-only passes over the frontend, CLI, backend, eval/optimizer/deploy, and integration subsystems.

One requested source file, `docs/plans/2026-04-12-cohesive-product-hardening.md`, is not present in this checkout. Several related item plans exist under `working-docs/`, especially `working-docs/cohesive-item1-plan-codex.md`, `working-docs/cohesive-item2-plan-codex.md`, `working-docs/cohesive-item4-plan-codex.md`, `working-docs/cohesive-item5-plan-codex.md`, and `working-docs/merge-cohesive-4-plan-codex.md`.

## High-Level Shape

AgentLab is a local-first agent development and operations workbench. The repo contains a Python backend and CLI, a React web console, local persistence stores, evaluation and optimization engines, deployment/versioning tools, import/export integrations, and tests/docs around the product loop:

`BUILD -> WORKBENCH -> EVAL -> RESULTS/COMPARE -> OPTIMIZE -> REVIEW -> DEPLOY`

The main product idea is that an operator can define or import an agent, evaluate it against cases or datasets, inspect failures, ask AgentLab to propose improvements, review those proposed changes, and deploy a new active or canary config. CLI, FastAPI, MCP, and web surfaces mostly coordinate through shared on-disk workspace state rather than through one another.

## Repository Areas

| Area | Responsibility | Important Files | Current Implementation Notes |
| --- | --- | --- | --- |
| Root package and CLI entry | Package metadata, command entrypoint, broad CLI orchestration | `pyproject.toml`, `runner.py` | `pyproject.toml` exposes `agentlab = "runner:cli"`. `runner.py` is a large Click command tree and still directly composes many services. |
| Web app | React operator console over the local API | `web/src/App.tsx`, `web/src/lib/navigation.ts`, `web/src/pages/*`, `web/tests/*` | Vite/React SPA. `/` redirects to `/build`. Simple mode currently includes Dashboard, Setup, Build, Workbench, Eval Runs, Results, Compare, Studio, Optimize, Improvements, Deploy, Docs. |
| FastAPI backend | HTTP API, service composition, background tasks, websocket, frontend serving | `api/server.py`, `api/main.py`, `api/routes/*`, `api/tasks.py`, `api/websocket.py` | `api/server.py` is the composition root. It wires route modules explicitly and attaches service singletons to `app.state`. |
| CLI helpers | Workspace discovery, output formats, mode/model/provider settings, MCP setup/runtime | `cli/workspace.py`, `cli/output.py`, `cli/json_envelope.py`, `cli/progress.py`, `cli/mode.py`, `cli/model.py`, `cli/providers.py`, `cli/mcp_setup.py`, `cli/mcp_runtime.py` | CLI uses helpers, but much orchestration remains in `runner.py`. CLI and API share stores directly, not via HTTP. |
| Shared taxonomy/contracts | Shared command/navigation grouping and typed contracts | `shared/taxonomy.py`, `shared/build_artifact_store.py`, `shared/contracts/*` | Taxonomy aligns UI and CLI command areas. Build artifacts are a cross-surface handoff from Build to later stages. |
| Workspace model | Local project paths, active config, runtime metadata | `cli/workspace.py`, `api/workspace_state.py` | Workspace state is centered on `.agentlab/`, `configs/`, `evals/`, `agentlab.yaml`, and `AGENTLAB.md`. API startup may `chdir` into the workspace root. |
| Agent runtime/config | Runtime config loading, templates, specialists, tools | `agent/config/*`, `agent/templates/*`, `agent/specialists/*`, `agent/tools/*` | Provides runtime shape used by eval/optimize/build flows. |
| Builder | Conversational and workspace-style agent builder | `builder/types.py`, `builder/store.py`, `builder/chat_service.py`, `builder/workspace_config.py`, `api/routes/builder.py` | SQLite-backed builder projects, sessions, tasks, proposals, artifacts, approvals, events, and chat sessions. |
| Workbench | Canonical build harness for iterative agent construction | `builder/workbench.py`, `builder/workbench_bridge.py`, `api/routes/workbench.py`, `web/src/pages/AgentWorkbench.tsx` | JSON-backed canonical project store in `.agentlab/workbench_projects.json`. Streams build/iterate events and materializes configs for Eval. |
| Eval | Test cases, datasets, scoring, history, result browsing, generated suites, pairwise compare | `evals/runner.py`, `evals/scorer.py`, `evals/results_model.py`, `evals/results_store.py`, `evals/history.py`, `evals/pairwise.py`, `evals/auto_generator.py`, `api/routes/eval.py`, `api/routes/results.py`, `api/routes/compare.py`, `api/routes/generated_evals.py` | Two important result layers coexist: legacy `CompositeScore` for optimizer gates and structured `EvalResultSet`/`EvalResultsStore` for Results Explorer. |
| Optimization | Failure-driven proposal generation, gates, memory, human review handoff | `optimizer/loop.py`, `optimizer/proposer.py`, `optimizer/gates.py`, `optimizer/memory.py`, `optimizer/pending_reviews.py`, `api/routes/optimize.py`, `api/routes/optimize_stream.py` | Optimizer can work from observer evidence or a completed eval run. Human approval is the normal API/UI path before deploy. |
| Review/change cards | Unified review queue and lower-level change-card workflows | `api/routes/reviews.py`, `api/routes/changes.py`, `optimizer/change_card.py`, `optimizer/pending_reviews.py`, `web/src/pages/Improvements.tsx` | `Improvements` aggregates optimizer pending reviews and change cards. Legacy Review/Changes pages redirect into this surface in the UI. |
| Deploy/versioning | Config version manifest, active/canary state, rollback, releases | `deployer/versioning.py`, `deployer/canary.py`, `deployer/release_manager.py`, `deployer/release_objects.py`, `api/routes/deploy.py`, `web/src/pages/Deploy.tsx` | Current deploy API primarily uses `ConfigVersionManager` and `CanaryManager`; richer release objects/staged release models are present as governance infrastructure. |
| Observer/telemetry | Conversation logs, failure buckets, traces, opportunities, metrics | `logger/store.py`, `observer/classifier.py`, `observer/metrics.py`, `observer/traces.py`, `observer/opportunities.py`, `api/routes/conversations.py`, `api/routes/traces.py`, `api/routes/opportunities.py` | Conversations feed health/failure evidence. Traces and opportunities support diagnose, optimize, and review workflows. |
| Events/tasks/reliability | Background tasks, websocket updates, event log, loop state, checkpoints, DLQ | `api/tasks.py`, `api/websocket.py`, `data/event_log.py`, `api/routes/events.py`, `api/routes/loop.py`, `control/*` | Tasks are persisted to SQLite and running/pending tasks become `interrupted` after restart. Loop runtime state is partly module-global plus task/checkpoint/event stores. |
| Datasets/outcomes/judges/scorers | Eval data management, outcome import, judge calibration, natural-language scorers | `data/dataset_store.py`, `data/dataset_service.py`, `api/routes/datasets.py`, `api/routes/outcomes.py`, `api/routes/judges.py`, `api/routes/scorers.py`, `evals/nl_scorer.py`, `judges/*`, `graders/*` | Supports importing traces/eval cases/CSV, dataset versions/splits, feedback, calibration, custom scorers, and judge operations. |
| Registry/skills/runbooks | Versioned catalogs, generated agent skills, runbooks, project memory | `registry/store.py`, `registry/skills.py`, `api/routes/registry.py`, `core/skills/*`, `agent_skills/*`, `api/routes/skills.py`, `api/routes/agent_skills.py`, `api/routes/runbooks.py`, `api/routes/memory.py` | Generic registry and generated agent-skill workflows are adjacent but distinct. Agent-skill apply routes include path containment checks. |
| MCP server | JSON-RPC MCP server exposing AgentLab tools/resources/prompts | `mcp_server/server.py`, `mcp_server/tools.py`, `mcp_server/resources.py`, `mcp_server/prompts.py`, `mcp_server/transport.py` | MCP tools instantiate stores from environment paths rather than reusing FastAPI `app.state`, so path/config consistency matters. |
| Connect/adapters | Import agents from external projects/endpoints/transcripts into AgentLab workspaces | `adapters/base.py`, `adapters/workspace_builder.py`, `adapters/openai_agents.py`, `adapters/anthropic_claude.py`, `adapters/http_webhook.py`, `adapters/transcript.py`, `api/routes/connect.py` | Connect supports OpenAI Agents SDK, Anthropic/Claude projects, HTTP webhooks, and transcript imports. |
| ADK integration | Google ADK import/export/deploy/diff/status | `adk/types.py`, `adk/importer.py`, `adk/exporter.py`, `adk/deployer.py`, `api/routes/adk.py` | Import maps ADK source to AgentLab config; export patches ADK source; deploy shells out to `gcloud` for Cloud Run/Vertex AI. |
| CX Studio integration | Dialogflow CX / Agent Studio import/export/diff/deploy/widget/status | `cx_studio/types.py`, `cx_studio/importer.py`, `cx_studio/exporter.py`, `cx_studio/deployer.py`, `cx_studio/compat.py`, `api/routes/cx_studio.py` | Keeps CX domain models separate from AgentLab config and uses snapshots/manifests/preflight/diff matrices. Several routes enforce path containment. |
| Sandbox/assistant/knowledge/context/what-if | Supporting product labs for simulation, assistant workflows, mined knowledge, context analysis, replay/projection | `assistant/*`, `context/*`, `simulator/*`, `api/routes/sandbox.py`, `api/routes/assistant.py`, `api/routes/knowledge.py`, `api/routes/context.py`, `api/routes/what_if.py` | These are secondary/pro surfaces that plug into traces, conversations, and generated artifacts. |
| Rewards/policy/preferences | Reward definitions, preference inbox, policy candidates, RL-style policy optimization | `rewards/*`, `policy_opt/*`, `api/routes/rewards.py`, `api/routes/preferences.py`, `api/routes/policy_opt.py`, `web/src/pages/Reward*.tsx`, `web/src/pages/PreferenceInbox.tsx`, `web/src/pages/PolicyCandidates.tsx` | Advanced evaluation/governance area around hard gates, preference data, and reward auditing. |
| Platform-control modules | Auth/RBAC/tenants/billing/metering/audit/secrets/SLA services | `api/auth.py`, `api/rbac.py`, `api/multi_tenant.py`, `api/billing.py`, `api/metering.py`, `api/audit.py`, `api/secrets.py`, `api/sla.py` | Present as service/library modules, but not wired as request-auth or tenant-enforcement middleware in the main FastAPI app in this checkout. |
| Docs and working docs | Product docs, architecture docs, plans, internal notes | `README.md`, `docs/*`, `working-docs/*` | Docs describe the product spine, app guide, CLI, concepts, architecture, and active hardening plans. Some docs lag current route reality. |
| Tests | Unit/integration/e2e coverage for CLI, API, eval, optimizer, web routes, integrations | `tests/*`, `web/tests/*` | Tests are broad and useful as implementation evidence. Web tests include route regressions, operator journey, continuity, and visual QA. |

## Current UI Route Inventory

`web/src/App.tsx` defines the current SPA route table. The route map includes:

- Day-one/simple-mode operator routes: `/dashboard`, `/setup`, `/build`, `/workbench`, `/evals`, `/evals/:id`, `/results`, `/results/:runId`, `/compare`, `/studio`, `/optimize`, `/improvements`, `/deploy`, `/docs`.
- Additional product/ops routes: `/agent-improver`, `/demo`, `/live-optimize`, `/configs`, `/conversations`, `/loop`, `/traces`, `/events`, `/judge-ops`, `/context`, `/runbooks`, `/skills`, `/memory`, `/registry`, `/blame`, `/scorer-studio`, `/notifications`, `/settings`.
- Import/integration routes: `/connect`, `/cx/studio`, `/cx/import`, `/cx/deploy`, `/adk/import`, `/adk/deploy`, `/agent-skills`, `/sandbox`, `/knowledge`, `/cli`, `/what-if`.
- Reward/policy routes: `/reward-studio`, `/preference-inbox`, `/policy-candidates`, `/reward-audit`.
- Legacy redirects: `/intelligence`, `/builder`, `/builder/demo`, `/builder/*`, `/agent-studio`, `/assistant`, `/eval`, `/opportunities`, `/experiments`, `/autofix`, `/changes`, `/review`, `/reviews`.

The navigation source of truth is `web/src/lib/navigation.ts`. It confirms that `Workbench` and `Studio` are simple-mode routes. It also confirms that `Connect` exists but is not in the simple-mode path set, even though some docs present Connect as part of first-run flow.

## Current API Route Inventory

`api/server.py` includes routers explicitly. The current HTTP API includes:

- Build and agent creation: `/api/builder`, `/api/workbench`, `/api/agents`, `/api/intelligence`, `/api/studio`.
- Setup and health: `/api/setup`, `/api/settings`, `/api/health`.
- Eval/results/compare: `/api/eval`, `/api/evals/generate`, `/api/evals/generated`, `/api/evals/results`, `/api/evals/compare`.
- Optimize/review/deploy: `/api/optimize`, `/api/changes`, `/api/reviews`, `/api/deploy`, `/api/quickfix`, `/api/autofix`.
- Observe/control: `/api/conversations`, `/api/traces`, `/api/events`, `/api/loop`, `/api/control`, `/api/context`, `/api/diagnose`, `/api/what-if`, `/api/impact`.
- Governance/data: `/api/config`, `/api/datasets`, `/api/outcomes`, `/api/judges`, `/api/scorers`, `/api/runbooks`, `/api/registry`, `/api/skills`, `/api/agent-skills`, `/api/memory`, `/api/preferences`, `/api/rewards`, `/api/rl`, `/api/curriculum`.
- Integrations and labs: `/api/connect`, `/api/cx`, `/api/adk`, `/api/cicd`, `/api/a2a`, `/api/sandbox`, `/api/knowledge`, `/api/assistant`, `/api/notifications`.
- Generic runtime: `/api/tasks`, `/api/tasks/{task_id}`, `/ws`.

## Current CLI Inventory

The top-level command is `agentlab`, implemented by `runner.py` using Click. The custom root group hides advanced commands from normal help and separates primary vs secondary commands.

Default primary commands:

- `agentlab new`: create a workspace from a starter template, optionally with demo seed data.
- `agentlab build`: generate an agent config/evals from a natural-language prompt and save build artifacts.
- `agentlab eval`: run eval suites/datasets, inspect results, generate cases, compare configs or runs.
- `agentlab optimize`: run improvement cycles, optionally continuous, with standard/advanced/research modes.
- `agentlab deploy`: canary, immediate, release, rollback, status.
- `agentlab status`: workspace home command and non-interactive default.
- `agentlab doctor`: workspace/config/provider/eval/MCP diagnostics and optional repair.
- `agentlab shell`: interactive shell.

Default secondary commands:

- `agentlab config`
- `agentlab connect`
- `agentlab instruction`
- `agentlab memory`
- `agentlab mode`
- `agentlab model`
- `agentlab provider`
- `agentlab review`
- `agentlab template`

Advanced or hidden-but-functional areas include `loop`, `compare`, `mcp`, `cx`, `adk`, `server`, `quickstart`, `demo`, `registry`, `runbook`, `trace`, `scorer`, `dataset`, `release`, `ship`, `init`, `changes`, `pause`, `resume`, `improve`, and legacy aliases such as `build-show`.

## Persistence And Workspace Files

The repo is designed around local workspace state. Important paths include:

- `agentlab.yaml`: runtime configuration.
- `AGENTLAB.md`: local workspace guide/context.
- `configs/manifest.json`: config version manifest with active/canary pointers.
- `configs/v###.yaml`: versioned config snapshots.
- `evals/cases/`: YAML eval cases.
- `.agentlab/workspace.json`: workspace metadata, active config path, preferred mode, settings.
- `.agentlab/providers.json`: provider configuration managed by CLI provider commands.
- `.agentlab/settings.json`: permissions/model overrides and similar settings.
- `.agentlab/conversations.db`: conversation records.
- `.agentlab/optimizer_memory.db`: optimization attempts.
- `.agentlab/eval_history.db`: legacy eval history.
- `.agentlab/eval_results.db` or env-configured results DB: structured Results Explorer data.
- `.agentlab/tasks.db`: persisted background task status and restart continuity.
- `.agentlab/change_cards.db`: reviewable change cards.
- `.agentlab/autofix.db`: AutoFix proposals/history.
- `.agentlab/events.db`: append-only event log.
- `.agentlab/workbench_projects.json`: Workbench canonical project state.
- `.agentlab/builder_workspace.db`: builder workspace objects.
- `.agentlab/builder_chat_sessions.db`: builder chat sessions.
- `.agentlab/build_artifact_latest.json`: latest build artifact pointer/payload.
- `.agentlab/generated_evals.json`: generated eval suites.
- `.agentlab/cx/*`: CX snapshots/workspaces/manifests.
- `.agentlab/adapter_spec.json`, `.agentlab/adapter_config.json`: Connect/import handoff data.
- `.mcp.json`: workspace MCP runtime configuration.

## Implementation Reality Notes

- `runner.py` is a significant monolith. The CLI has helper modules, but many command handlers still instantiate and coordinate stores/services directly.
- `api/server.py` is also a broad composition root. Route handlers are mostly thin, but they depend heavily on `request.app.state` service singletons.
- Several systems have parallel or transitional stores: eval has legacy history plus structured results; review has pending optimizer reviews plus change cards; deploy has current manifest/canary flow plus richer release-governance objects.
- The backend is local-first and broad rather than a narrowly multi-tenant SaaS API. Auth/RBAC/billing/metering modules exist, but main app request enforcement is not wired in the current route stack.
- Some docs list Connect as first-run/simple-mode; code currently treats Connect as a real pro/integration route and keeps Build/Workbench/Eval/Optimize/Improvements/Deploy as the simple operator spine.
- Workbench is more than a placeholder. It has a real page, real API routes, SSE streaming, durable project JSON, cancel/restart metadata, and a typed Eval handoff.
