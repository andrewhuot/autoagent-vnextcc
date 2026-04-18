# AgentLab Master Document

Generated: 2026-04-18

Source policy: this document is derived from source code, configuration files, package manifests, and tests only. Existing repository markdown files were intentionally excluded from review because they were identified as outdated. Any references below point to code/config/test artifacts, runtime behavior, or generated storage paths observed in code.

## Executive Summary

AgentLab is a product-grade agent optimization platform. It combines a Python CLI, a FastAPI service, and a React web console to support the full lifecycle of building, importing, evaluating, improving, reviewing, deploying, and observing AI agents.

The product model is an operator journey:

1. Build or import an agent.
2. Materialize a runnable AgentLab config.
3. Run evals against that config.
4. Explore results and compare variants.
5. Optimize against completed eval evidence or observed failures.
6. Review proposed improvements.
7. Deploy as canary or active config.
8. Observe production behavior, mine traces, collect outcomes, and feed the loop.

The system is designed to work in both mock/simulated mode and live-provider mode. Most surfaces expose mock reasons, provider readiness, or strict-live controls so operators can distinguish deterministic local behavior from real model-backed execution.

## Product Surface Map

AgentLab has three primary interfaces:

- CLI: exposed by `runner.py` as the `agentlab` command.
- API: a FastAPI app assembled in `api/server.py`.
- Web console: a Vite/React application under `web/src`.

The Python package is declared as `agentlab` version `2.0.0` in `pyproject.toml`. The package includes backend domains such as `agent`, `api`, `builder`, `optimizer`, `evals`, `observer`, `deployer`, `registry`, `data`, `rewards`, `policy_opt`, `adk`, `cx_studio`, `a2a`, and `mcp_server`.

The web app is a React 19 + Vite console using React Router, TanStack Query, Zustand, Recharts, Tailwind, Vitest, and Playwright-oriented dependencies. Its primary route redirects to `/build`, which makes the Build workspace the entry point rather than the older dashboard.

## End-to-End Operator Experience

### Setup

The Setup page and `/api/setup/overview` check whether an AgentLab workspace exists, whether runtime mode is mock/auto/live, whether provider API keys are configured, what data stores exist, and whether MCP clients are configured. Provider keys are saved through `/api/settings/keys`, runtime mode through `/api/settings/mode`, and live provider connectivity through `/api/settings/test-key`.

The effective modes are:

- `mock`: deterministic/local behavior.
- `auto`: live when possible, fallback when not.
- `live`: requires provider credentials and should fail rather than silently simulate.

The web shell surfaces mock mode, provider mode, and readiness signals globally so users understand whether Build, Eval, Optimize, and assistant behavior is real or simulated.

### Build

The Build surface at `/build` is the main starting point. It supports multiple creation modes:

- Prompt-to-agent generation.
- Transcript-informed generation.
- Conversational builder chat.
- Saved build artifacts.
- Coordinator/specialist workspace.

The Build page calls the transcript intelligence and builder chat APIs to generate a richer draft object, preview it, refine it, export it, or save it into the workspace. Saving a build draft calls the same persistence path used by the Agent Library: generated drafts are projected into a real runtime config, written to the versioned config store, and recorded as build artifacts.

Build artifacts are persisted in `.agentlab/build_artifacts.json`, with a latest compatibility payload in `.agentlab/build_artifact_latest.json`. Saved build configs become versioned YAML files under the configured `configs` directory and appear in `/api/agents`.

### Agent Workbench

The Workbench page at `/workbench` is a streaming, multi-turn build environment. It models a Manus-style build surface with a plan tree, running task status, artifacts, validation, reflection, and a candidate-agent chat loop.

Workbench APIs under `/api/workbench` support:

- Creating or hydrating a default project.
- Planning natural-language changes.
- Applying plans.
- Testing and rolling back canonical versions.
- Streaming full builds over Server-Sent Events.
- Streaming follow-up iterations.
- Chatting with the built candidate agent.
- Materializing a Workbench candidate into Eval-ready and Optimize-ready payloads.

Workbench state is managed in the frontend by `web/src/lib/workbench-store.ts`. It keeps project state, streaming events, artifacts, canonical model, exports, active run state, harness metrics, chat transcript, composer history, and auto-iteration settings.

### Agent Improver

The Agent Improver page is a narrower conversational improvement flow built on the builder chat API. It focuses on a practical sequence:

1. Brief.
2. Refine.
3. Inspect.
4. Validate.

It supports browser-local checkpoints, undo/redo, local persistence, live session restoration, YAML/JSON export, preview, save, and direct continuation into Eval. It also warns on unsaved work before navigation.

### Eval

Eval Runs at `/evals` is the required evidence gate before the main Optimize path. The page selects an active agent, can generate or apply eval suites, and starts eval tasks by calling `/api/eval/run`.

Eval supports:

- Config path selection.
- Dataset path selection.
- Generated suite selection.
- Category and split filtering.
- Strict-live evaluation.
- WebSocket completion notifications.
- Structured result persistence.
- Workbench bridge recording so Optimize can consume the completed eval run.

The eval runner computes case-level outcomes and aggregate scores. Results can be explored under `/results`, compared under `/compare`, and consumed by Optimize.

### Results And Compare

The Results Explorer loads structured eval runs from `/api/evals/results`. Users can:

- Inspect run summaries.
- Filter example-level outcomes by pass/fail, metric thresholds, category, or search.
- Sort by severity, quality, category, and other views.
- Annotate examples.
- Export runs as JSON, CSV, or text-oriented formats.
- Diff one run against another.
- Navigate into Optimize with the relevant agent and evidence context.

The Compare page uses `/api/evals/compare` for pairwise config comparisons. It can compare two configs on a dataset using metric delta, LLM judge, or human-preference strategies, then reports winner, left/right/tie counts, pending human items, p-values, and significance.

### Optimize

Optimize at `/optimize` consumes completed Eval evidence. The route enforces this in the API when `require_eval_evidence` is set. The frontend passes eval run context from Eval or Workbench.

Optimization modes are resolved by `optimizer.mode_router` and can tune:

- Standard versus advanced/research behavior.
- Objective string.
- Guardrails.
- Search strategy.
- Candidate budget.
- Evaluation budget.
- Dollar budget.
- Human approval requirement.

The API streams internal progress through an optimization event bus and also uses task polling and WebSocket broadcasts. The UI shows staged progress: observe, analyze, generate, evaluate, and deploy/review.

When human approval is required, successful candidates become pending reviews rather than being deployed immediately. Pending reviews carry the proposed config, current config, diff, scores, reasoning, selected operator family, governance notes, patch bundle, and baseline eval metadata.

### Improvements And Reviews

The Improvements page unifies several improvement-related concepts:

- Optimizer attempts from `OptimizationMemory`.
- Pending optimizer reviews from `PendingReviewStore`.
- Improvement lineage events from `ImprovementLineageStore`.
- Opportunity queue entries.
- Experiment cards.
- Change card reviews.

The `/api/improvements` API classifies each optimizer attempt into statuses such as proposed, pending review, accepted, rejected, verified, deployed canary, promoted, rolled back, and measured.

The `/api/reviews` API provides a unified review queue across optimizer pending reviews and change cards. It normalizes both into a common item shape with source, status, title, score delta, risk class, diff summary, patch bundle, and optional verification.

Review actions dispatch to the underlying store:

- Optimizer approvals deploy the proposed config, remove the pending review, and mark the attempt accepted.
- Optimizer rejections remove the pending review and mark the attempt rejected by a human.
- Change-card approvals mark cards applied.
- Change-card rejections mark cards rejected with optional reason.

### Deploy

Deploy at `/deploy` publishes config versions. It supports:

- Status inspection.
- Canary deploy.
- Immediate active deploy.
- Promote current canary or selected version.
- Roll back canary.

The underlying deployer uses `ConfigVersionManager` to persist YAML versions and `manifest.json` metadata. Each version includes version number, config hash, filename, timestamp, scores, and status. Status values include active, canary, retired, and rolled back.

Canary behavior is managed by `CanaryManager`. Requests can probabilistically route to the canary config, and canary verdicts are based on conversation outcomes, minimum canary conversation counts, timeout windows, baseline comparison, and optional pairwise aggregation.

### Observe, Govern, And Learn

After deployment, AgentLab has surfaces for:

- Health and scorecards.
- Continuous loops.
- Traces, trace graphs, trace grading, blame maps.
- Event logs and unified event history.
- Human control pause/pin/reject/inject.
- AutoFix suggestions.
- Diagnose chat.
- Knowledge mining.
- Context engineering.
- Skill gaps and generated skills.
- Runbooks.
- Registry items.
- Judge ops.
- Rewards, preferences, policy optimization, and business outcomes.

These surfaces close the loop from production traces and business outcomes back into evals, optimizer context, skills, judge calibration, and future candidate proposals.

## Runtime Topology

### Python CLI

The CLI is declared as `agentlab = runner:cli`. The root command is an `AgentLabGroup` that groups help into primary and advanced commands and hides experimental commands unless requested.

Core user-facing commands include:

- `new`
- `build`
- `workbench`
- `eval`
- `optimize`
- `deploy`
- `ship`
- `status`
- `doctor`
- `shell`

The CLI also includes many advanced domains: sessions, init, templates, connect adapters, provider config, config operations, loop control, harness, logs, human controls, AutoFix, judges, context, review/change cards, experiments, runbooks, memory, server, MCP server, registry, curriculum, traces, scorers, full-auto, quickstart, demo, policy, edit, explain, diagnose, replay, CX, ADK, datasets, outcomes, releases, benchmarking, rewards, RL, preferences, and imports.

The CLI and web console share many stores and request shapes. Several API routes are explicitly written to preserve CLI compatibility files or status semantics.

### FastAPI Service

`api/server.py` constructs the FastAPI application. It:

- Uses lifespan startup to resolve workspace state.
- Changes the process working directory to the workspace root when valid.
- Initializes runtime config and logging.
- Wires all stores, routers, task manager, WebSocket manager, event log, builder services, optimizer services, evaluator services, deployer services, registry, memory, notifications, and integrations.
- Serves API routes under `/api`.
- Exposes `/ws` for task completion and loop/eval/optimize broadcasts.
- Serves built React assets from `web/dist` when present.
- Falls back to an API-running message when frontend assets are absent.

Most API routes depend on `request.app.state` rather than global dependency injection. Startup is therefore the composition root of the backend.

### React Console

`web/src/App.tsx` registers the full route tree. The route taxonomy is centralized in `web/src/lib/navigation.ts` and `shared/contracts/taxonomy.ts`. Navigation groups are:

- Home.
- Build.
- Import.
- Eval.
- Optimize.
- Review.
- Deploy.
- Observe.
- Govern.
- Integrations.
- Help.
- Settings.

The sidebar can be simple or full. Simple mode emphasizes the main journey: Build, Eval, Optimize, Deploy.

`web/src/components/Layout.tsx` wraps the console with:

- Sidebar.
- Command palette.
- Toast viewport.
- Mock-mode banner.
- Provider mode pill.
- Global shortcuts.
- Journey strip on Build/Workbench/Evals/Optimize/Improvements/Deploy.

### Background Work And Streaming

The API uses multiple asynchronous/progressive patterns:

- `api.tasks.TaskManager` for background eval, optimize, loop, and generic task polling.
- WebSocket `/ws` for broadcast messages.
- Server-Sent Events for Workbench build/iterate/chat streams.
- Server-Sent Events for builder event history streams.
- Optimization event bus for live Optimize progress.
- In-memory assistant sessions for current assistant streaming.

The task system keeps progress and result payloads. WebSocket broadcasts are best effort and are bridged into the event log where implemented.

## Configuration Model

### Runtime Config

`agentlab.yaml` is the runtime configuration. It includes:

- Optimizer provider/model routing.
- Search strategy.
- Bandit settings.
- Budget settings.
- Holdout.
- Drift detection.
- Adversarial simulation.
- Skill auto-learning.
- Continuous loop schedule.
- Checkpoint, dead-letter, and structured log paths.
- Eval cache/history/result database paths.
- Significance settings.
- Optimization mode, objective, guardrails, autonomy level, and allowed surfaces.
- Harness coordinator/worker models.

Runtime config supports mock/live provider behavior and migration of older optimization strategy shapes.

### Agent Config

`agent/config/schema.py` defines the runnable agent config shape. It includes:

- Routing rules.
- Prompt blocks.
- Tool enablement/configuration.
- Thresholds.
- Context caching.
- Compaction settings.
- Memory policy.
- Optimizer settings.
- Model settings.
- Quality boost settings.
- Guardrails.
- Handoffs.
- Policies.
- MCP servers.
- Generation settings.
- Adapter metadata.

It also provides canonical conversion, validation, and config diff helpers.

### Canonical IR

`shared/canonical_ir.py` defines a platform-neutral agent representation. It models:

- Instructions with semantic role and format.
- Tool contracts and parameters.
- Routing rules.
- Policies.
- Guardrails.
- Handoffs.
- MCP server references.
- Environment config.
- Sub-agents.
- Example traces.
- Fidelity notes.

Adapters convert imported external agents into this IR so AgentLab can reason across OpenAI Agents, Anthropic SDK projects, Google ADK, Dialogflow CX / CX Agent Studio, HTTP webhooks, transcript exports, and native builds.

## Backend Domain Architecture

### Agent Runtime

The agent runtime has two major forms:

- `ConfiguredEvalAgent`, which runs generated or saved AgentLab configs through eval harnesses.
- ADK-root agent definitions under `agent/root_agent.py` for Google ADK style orchestration.

`ConfiguredEvalAgent` supports:

- Mock fallback responses.
- Live LLM routing through `LLMRouter`.
- Specialist routing by keyword/pattern scoring.
- Implied tool-call generation for catalog, order database, and FAQ tools.
- Prompt assembly from config.
- XML instruction merging and overrides.
- Strict live mode that fails when live execution is required but unavailable.

### Builder

The builder domain is large and central. It covers prompt-to-agent generation, chat-based refinement, coordinator plans, specialist execution, durable events, permissions, releases, and Workbench canonical projects.

Important builder concepts:

- `ExecutionMode`: ask, draft, apply, delegate.
- Task and worker statuses.
- Artifact types: plan, source diff, ADK graph diff, skill, guardrail, eval, trace evidence, benchmark, release.
- Specialist roles: orchestrator, build engineer, requirements analyst, prompt engineer, ADK architect, tool engineer, skill author, guardrail author, eval author, eval runner, loss analyst, optimization engineer, instruction optimizer, guardrail optimizer, callback optimizer, trace analyst, deployment engineer, release manager, gate runner, and platform publisher.

`builder/store.py` is a SQLite store for projects, sessions, tasks, proposals, artifacts, approvals, worktrees, sandbox runs, eval bundles, trace bookmarks, release candidates, coordinator runs, and related payloads.

`builder/orchestrator.py` routes tasks to specialists by verb and keyword. It tracks worker capability contracts, skill layers, expected artifacts, permission scopes, and handoffs.

`builder/execution.py` manages task lifecycle: create, pause, resume, cancel, progress, duplicate, fork, complete, fail, crash recovery, delegate-mode worktrees, sandbox runs, and event publication.

`builder/chat_service.py` provides durable builder chat sessions. A first user prompt creates a generated config through transcript intelligence. Follow-up messages refine it. Sessions can be listed, resumed, previewed, exported, and saved.

`builder/workbench.py` manages canonical Workbench projects, plan snapshots, canonical versions, validation, rollback, exports to portable/ADK/CX targets, active runs, cancellation, heartbeat, and stale run recovery.

`builder/workbench_agent.py` defines the streaming build event contract. Live and mock execution emit compatible events such as plan ready, task started, message delta, task progress, artifact updated, task completed, build completed, and error.

`builder/coordinator_runtime.py` executes persisted coordinator plans, resolves worker mode, runs dependency-ordered workers, verifies artifacts, synthesizes outcomes, and publishes builder events.

### Transcript Intelligence

Transcript intelligence is exposed by `/api/intelligence`. It supports:

- Archive import from base64.
- Report listing and retrieval.
- Question answering against a report.
- Applying an insight to create a change card.
- Prompt-to-agent draft generation.
- Agent config generation with optional transcript report, XML instruction block, requested model/name, and tool hints.
- Chat refinement of a generated config.
- Saving generated agents.
- Previewing generated agents.
- Retrieving generated knowledge assets.
- Deep research over a report.
- Autonomous loops from report insight to sandbox validation and optional shipping.

The generated config is saved by `builder/workspace_config.py`, which maps the richer Build UI contract into the real AgentLab runtime config. It stores Build-specific details under `journey_build` while projecting runnable pieces into prompts, routing, tools, and model fields.

### Evaluation

The eval subsystem is implemented under `evals`. Core pieces:

- `EvalRunner`: loads test cases from YAML/JSONL/CSV, handles train/test splits, detects data-integrity problems, filters by tag/category/split, executes an agent function, scores results, fingerprints inputs for cache, and persists history/results.
- `scorer.py`: computes dimension scores and composite scores.
- `results_store.py`: persists structured eval runs, examples, scores, and annotations in SQLite.
- `auto_generator.py`: generates eval suites across categories.
- `pairwise.py`: runs and stores pairwise comparisons.

Eval categories include happy path, tool usage, routing, policy compliance, safety, edge cases, regression, and performance.

The enhanced scorer covers dimensions:

- Task success.
- Quality.
- Safety.
- Latency p50/p95/p99.
- Token cost.
- Tool correctness.
- Routing.
- Handoff.
- Satisfaction proxy.

Default composite weights emphasize quality, safety, latency, and cost. Constrained scoring adds hard constraints such as zero safety failures and required regression pass behavior.

`/api/eval/run` creates a background eval task, resolves config/dataset/generated suite inputs, handles strict live mode, streams progress, saves structured results, broadcasts completion, and returns provenance including fingerprints and execution mode.

### Optimization

The optimizer converts evidence into candidate config changes. It combines observation, failure classification, skill application, proposer strategies, typed mutations, gates, statistical tests, adversarial checks, memory, and lineage.

`optimizer/loop.py` is the main optimizer. It can:

- Observe health and failures.
- Respect human pause and immutable surfaces.
- Check budget/stall conditions.
- Apply relevant skills first.
- Propose candidate changes through LLM or deterministic logic.
- Use search strategies such as simple, adaptive, full, and pro.
- Evaluate baseline and candidate.
- Run significance checks.
- Run adversarial simulation when enabled.
- Gate against safety and regression.
- Log attempts.
- Update rejection rings and reflection.
- Optionally learn new skills.

`optimizer/mutations.py` defines typed mutation surfaces, including instruction, few-shot, tool description, model, generation settings, callback, context caching, memory policy, routing, workflow, skill, policy, tool contract, and handoff schema. Operators carry risk classes, validators, rollback support, eval cost, and autodeploy support.

`optimizer/proposer.py` ranks and creates proposed changes. The deterministic/mock path targets observed failure buckets such as routing errors, quality gaps, safety violations, timeouts, and tool failures.

`optimizer/gates.py` enforces hard constraints and regression thresholds.

`optimizer/pareto.py` maintains feasible/infeasible candidate archives and direction-aware objectives, including cost minimization.

`optimizer/memory.py` persists attempts in SQLite with metadata such as attempt id, timestamp, change description, diff, section, status, before/after scores, significance, health context, skills applied, patch bundles, predicted effectiveness, strategy surface, and strategy name.

### Opportunities, Experiments, And Improvements

The observer and optimizer can create opportunities and experiment records:

- `/api/opportunities` lists and updates optimization opportunities.
- `/api/experiments` lists experiment cards, stats, Pareto frontier, archive entries, and judge calibration data.
- `/api/improvements` joins optimizer attempts, pending reviews, and lineage events into a single improvement model.

This allows users to move from raw failures to concrete opportunities, track candidate experiments, and understand which proposals were accepted, rejected, deployed, rolled back, or measured.

### Deployment

Deployment is config-version based. `deployer/versioning.py` writes config YAML files and a manifest. `deployer/canary.py` controls canary routing and verdicts. `deployer/publish.py` shares publish logic between HTTP routes and coordinator workers.

Deployment operations can:

- Save a new active version.
- Save a new canary version.
- Mark an existing version as canary.
- Promote a version to active.
- Promote current canary.
- Roll back a canary.
- Diff versions.
- Summarize versions.

Lineage is recorded where available so an improvement can be traced from proposal through deploy, promotion, rollback, verification, and measurement.

### Continuous Loop

`/api/loop` starts and stops continuous optimization cycles. A loop cycle:

1. Observes recent conversation health.
2. Classifies whether optimization is needed.
3. Builds failure samples.
4. Runs optimizer.
5. Evaluates and deploys accepted candidates as canary.
6. Checks existing canary verdicts.
7. Records checkpoint state.
8. Samples resource usage.
9. Emits WebSocket and event-log updates.

Reliability pieces include:

- Checkpoint store.
- Dead-letter queue.
- Loop watchdog.
- Resource monitor.
- Structured logging.
- Resume-from-checkpoint support.

### Observability

The observer domain computes health and trace insight. It includes:

- Conversation metrics.
- Anomaly detection.
- Failure classification.
- OpenTelemetry span types and exporters.
- Auto-instrumentation.
- Trace store.
- Trace grading.
- Trace graph.
- Blame map.
- Trace promotion into eval cases.
- Knowledge mining.

Health metrics include success rate, average latency, error rate, safety violation rate, average cost, and total conversations.

Anomaly detection uses adaptive baselines and a 2-sigma rule for success rate, latency, error rate, safety violation rate, and cost.

Trace APIs support recent events, search, error filtering, session traces, blame maps, trace grades, trace graphs, full trace retrieval, and manual trace promotion into an eval case file.

Event APIs expose:

- System event log.
- Unified event timeline combining system and durable builder events.
- Source metadata and continuity state so the frontend can show durable history after restart.

### Human Control

Human control APIs under `/api/control` support:

- Pause optimization activity.
- Resume optimization activity.
- Pin immutable surfaces.
- Unpin surfaces.
- Reject an experiment, with canary rollback when applicable.
- Inject a manual mutation payload and deploy it as canary after evaluation.

This store is consulted by optimizer behavior so users can stop or constrain automated changes.

### AutoFix And Diagnose

AutoFix is a proposal layer over failures and current config. It can suggest, list, apply, reject, and summarize proposals. Proposal payloads include expected lift, affected eval slices, risk class, cost impact, diff preview, and patch bundle.

Diagnose provides a conversational root-cause workflow. It creates a `DiagnoseSession` over conversation store, observer, optimizer, eval runner, deployer, and a natural-language editor. Users can ask for examples, move between clusters, skip, or apply a pending fix. Applied diagnose changes are logged as optimization attempts and may update project memory intelligence.

### Governance: Registry, Runbooks, Skills, Judges

The registry domain stores versioned items in SQLite:

- Skills.
- Policies.
- Tool contracts.
- Handoff schemas.
- Runbooks.

The registry API supports search, import from file, list, get, diff versions, and create/register operations for each item type.

Runbooks are named, versioned bundles of skills, policies, tool contracts, and surfaces. Applying a runbook returns the registered elements for the operator workflow.

Core skills are a unified build-time and runtime skill system. A skill has kind, domain, triggers, mutations, tools, policies, tests, dependencies, tags, status, and effectiveness metrics. APIs support CRUD, search, recommendations, composition, marketplace browse/install, validation/testing, draft promotion, archiving, application queueing, and effectiveness analytics.

Generated agent skills are a separate pipeline under `/api/agent-skills`. It analyzes skill gaps from opportunities, generates skill source files, stores them, supports approve/reject, and can apply approved generated files to a workspace root with path traversal checks.

Judge Ops includes judge version/feedback stores, human feedback submission, calibration, and drift endpoints. Drift currently requires accumulated verdict data; the route reports zero/no-data when verdicts are absent.

### Project Memory And Context Engineering

Project memory is a structured and layered context system managed by `core/project_memory.py`. It has shared/local/rules/generated layers and exposes structured fields such as agent identity, business constraints, known good patterns, known bad patterns, team preferences, and optimization history.

Important behavior:

- Project memory can be saved and updated through `/api/memory`.
- Notes can be added by section.
- Optimizer-relevant context can be extracted.
- Immutable surfaces can be inferred from preferences.
- Intelligence sections can be generated from reports, eval score, recent changes, and skill gaps.

Context engineering APIs support:

- Profile listing.
- Context preview from workspace.
- Trace-specific context analysis.
- Compaction simulation.
- Aggregate context report, currently with a no-data/default path unless trace analyses have been performed.

### External Integrations

#### Connect Adapters

`/api/connect` imports external runtimes into AgentLab workspaces. Supported adapters:

- OpenAI Agents source directories.
- Anthropic SDK source directories.
- HTTP webhook agents.
- Transcript exports.

Adapters discover prompts, tools, guardrails, handoffs, MCP references, traces, starter evals, and metadata. `create_connected_workspace` materializes a workspace and registers imported configs with the version manager when running in the server.

#### ADK

`/api/adk` supports:

- Importing ADK agent directories.
- Exporting optimized config back to ADK source.
- Deploying ADK agents to Cloud Run or Vertex AI.
- Inspecting ADK structure.
- Previewing export diffs.

ADK import registers imported configs as candidate versions when possible.

#### Dialogflow CX / CX Agent Studio

`/api/cx` supports:

- Google auth validation.
- Agent listing.
- Agent import.
- Export.
- Diff.
- Sync.
- Preflight validation.
- Immediate or canary deploy.
- Canary promote.
- Rollback.
- Widget HTML generation.
- Deployment status.
- Previewing export changes from local config and snapshot.

The CX domain includes typed models for agents, pages, flows, intents, entity types, webhooks, transition route groups, playbooks, tools, generators, environments, deployments, test cases, and snapshots. It also maintains compatibility and portability matrices. Export preflight can block on lossy or unsupported surfaces.

#### A2A

The A2A router exposes:

- `/.well-known/agent-card.json` for discovery.
- JSON-RPC style task send.
- Task status.
- Task cancel.
- Registered agents list.
- External agent discovery proxy.

Agent cards are generated from environment and app state. If no agents are registered, default optimize/evaluate skills are advertised.

#### MCP

MCP support appears across CLI setup/status, runtime config, agent config, adapters, tests, and server package modules. The setup overview reports MCP client readiness. Agent configs can include MCP servers, and canonical IR preserves MCP server references.

### Data, Rewards, Policy Optimization, And Business Outcomes

AgentLab includes a first-class dataset service:

- Create/list/get datasets.
- Add rows.
- Create immutable versions.
- List versions.
- Read rows by version/split.
- Compute stats and quality metrics.
- Import from traces or eval cases.
- Configure splits.
- Export to JSON.
- Save version pins tying dataset, grader, judge, config, skill, model, and experiment versions together.

Business outcomes can be ingested singly, in batch, by webhook, or CSV upload. Outcomes are associated with trace ids and can drive dashboard stats, judge recalibration, and skill calibration.

Rewards are versioned definitions that can be created, listed, tested, audited, and challenged against built-in reward-hacking/sycophancy suites. Hard gates can be listed separately.

Preference collection stores chosen/rejected pairs in SQLite and exports DPO/preference datasets. Policy optimization (`/api/rl`) can build datasets from episodes, create training jobs, list jobs, inspect policy artifacts, run offline eval, run off-policy evaluation, canary a policy, promote a policy, and roll back.

### Sandbox, What-If, And Impact

The sandbox API generates synthetic conversation sets, stress-tests a config against generated conversations, compares two configs on the same set, and stores in-memory test/comparison results.

What-if replay replays historical conversations through a candidate config label, compares outcomes, stores results, lists jobs, and projects sample impact to full traffic with confidence intervals and recommendations.

Multi-agent impact analysis currently builds an agent tree and predicts affected agents for a proposed mutation. Some impact report data is static/sample-shaped, which marks this as a partially implemented surface.

### Assistant

The assistant API streams SSE responses and supports:

- Message streaming.
- Uploads.
- History.
- Clear history.
- Suggestions.
- Card actions.

The current backend uses an in-memory mock orchestrator. It emits thinking events, text chunks, cards, and suggestions. It can simulate build, diagnose/fix, exploration, and general guidance flows. This means the UI contract is implemented, but the production orchestrator is not yet wired in the inspected code.

## API Surface By Domain

The API is broad. Major route groups include:

- `/api/health`: readiness, health report, system health, cost, eval-set health, scorecard.
- `/api/setup`: onboarding overview.
- `/api/settings`: provider keys, runtime mode, provider key tests.
- `/api/agents`: Agent Library list/get/save.
- `/api/config`: list/show/diff/active/activate/import/migrate config versions.
- `/api/intelligence`: transcript intelligence, prompt generation, reports, generated agents.
- `/api/builder`: builder chat, projects, sessions, tasks, proposals, artifacts, approvals, permissions, events, metrics, specialists, coordinator, releases.
- `/api/workbench`: canonical Workbench projects, plans, apply/test/rollback, build streams, iterations, chat, eval bridges.
- `/api/eval`: start eval, list tasks, eval details, history, generated suite lifecycle.
- `/api/evals/results`: structured eval results, examples, annotations, export, diff.
- `/api/evals/compare`: pairwise comparisons.
- `/api/optimize`: start optimization, history, surfaces, pending reviews, Pareto snapshot.
- `/api/improvements`: improvement records, verify, measure.
- `/api/reviews`: unified review queue and review actions.
- `/api/changes`: change cards, hunk status, audit, export.
- `/api/deploy`: deploy/status/promote/rollback.
- `/api/loop`: start/stop/status continuous loop.
- `/api/traces`: recent/search/errors/session/blame/grades/graph/promote.
- `/api/events`: system and unified event history.
- `/api/opportunities`: opportunity queue.
- `/api/experiments`: experiment cards, stats, Pareto, archive, judge calibration.
- `/api/control`: pause/resume/pin/unpin/reject/inject.
- `/api/autofix`: suggest/list/apply/reject/history.
- `/api/diagnose`: diagnosis overview and chat.
- `/api/context`: profiles, preview, trace analysis, simulation, report.
- `/api/registry`: versioned skills/policies/tool contracts/handoff schemas.
- `/api/runbooks`: runbook CRUD/search/apply.
- `/api/memory`: project memory read/update/notes/context.
- `/api/skills`: lifecycle skill CRUD, marketplace, recommendations, composition, validation, effectiveness.
- `/api/agent-skills`: skill gaps, generated skills, approval, application.
- `/api/scorers`: natural-language scorer creation/refinement/testing.
- `/api/judges`: judge listing, feedback, calibration, drift.
- `/api/connect`: runtime adapter imports.
- `/api/adk`: ADK import/export/deploy/status/diff.
- `/api/cx`: CX import/export/sync/deploy/widget/status/preview.
- `/api/a2a` and `/.well-known/agent-card.json`: agent-to-agent protocol.
- `/api/datasets`: datasets, versions, rows, splits, pins.
- `/api/outcomes`: business outcomes and recalibration.
- `/api/rewards`: reward definitions, audits, challenge suites.
- `/api/rl`: policy optimization datasets/jobs/policies/eval/canary/promote/rollback.
- `/api/preferences`: preference pairs, stats, export.
- `/api/sandbox`: synthetic conversations and stress tests.
- `/api/what-if`: replay, results, impact projection, jobs.
- `/api/impact`: multi-agent impact predictions.
- `/api/notifications`: webhook/Slack/email subscriptions and history.
- `/api/knowledge`: knowledge mining, entries, review, apply.
- `/api/assistant`: streaming assistant.

## Frontend Route Map

The React app exposes the following major pages:

- `/build`: primary Build workspace.
- `/workbench`: streaming Agent Workbench.
- `/agent-improver`: focused improvement chat.
- `/dashboard`: scorecard and operational summary.
- `/evals`: eval runs and generated suites.
- `/results`: structured result explorer.
- `/compare`: pairwise comparisons.
- `/optimize`: optimization run/live tabs.
- `/improvements`: opportunities, experiments, review, history.
- `/deploy`: version/canary deploy.
- `/loop`: continuous optimization monitor.
- `/setup`: provider/workspace setup.
- `/traces`: trace viewer.
- `/events`: event log.
- `/judge-ops`: judge calibration/drift.
- `/context`: context engineering.
- `/runbooks`: runbooks.
- `/skills`: lifecycle skills.
- `/agent-skills`: generated agent skills.
- `/memory`: project memory.
- `/registry`: registry CRUD.
- `/blame`: blame map.
- `/scorer-studio`: natural-language scorers.
- `/connect`: runtime import adapters.
- `/cx/studio`, `/cx/import`, `/cx/deploy`: CX surfaces.
- `/adk/import`, `/adk/deploy`: ADK import/deploy.
- `/notifications`: subscriptions/history.
- `/sandbox`: synthetic testing.
- `/knowledge`: knowledge mining.
- `/cli`: CLI launcher/help.
- `/docs`: in-app docs/help page.
- `/what-if`: replay impact.
- `/reward-studio`: reward definitions.
- `/preference-inbox`: preference collection.
- `/policy-candidates`: RL policy candidates.
- `/reward-audit`: reward audit/challenge.
- `/settings`: runtime settings.

Several older routes redirect to current Build tabs, including legacy intelligence/builder/agent-studio/assistant paths.

## Persistence And State Stores

AgentLab uses SQLite, JSON, YAML, and in-memory stores. Important persistent paths and stores include:

- Versioned configs: `configs/vNNN.yaml` plus `configs/manifest.json`.
- Conversations: `conversations.db`.
- Optimizer memory: `optimizer_memory.db`.
- Eval history and cache: configured in runtime config.
- Structured eval results: `.agentlab/eval_results.db`.
- Trace store: `.agentlab/traces.db`.
- Event log: `.agentlab/events.db` or configured event store.
- Builder SQLite store: configured by `BuilderStore`.
- Builder durable events: configured durable builder event store.
- Builder chat sessions: `.agentlab/builder_chat_sessions.db`.
- Shared build artifacts: `.agentlab/build_artifacts.json`.
- Latest build artifact compatibility payload: `.agentlab/build_artifact_latest.json`.
- Transcript intelligence reports: `.agentlab/intelligence_reports.json`.
- Generated eval suites: JSON-backed generated suite store.
- Pairwise comparisons: JSON-backed comparison store.
- Improvement lineage: SQLite-backed lineage/improvement stores.
- Registry items: SQLite `registry.db` style store.
- Lifecycle skills: SQLite `executable_skills` and `skill_outcomes`.
- Generated agent skills: agent skill store.
- Change cards: change card store.
- Loop checkpoints and dead letters: configured under `.agentlab`.
- Cost tracking: cost tracker store.
- Notifications: notification manager storage/history.
- Dataset service: dataset SQLite/JSON backing stores.
- Business outcomes: outcome store.
- Preference pairs: `preferences.db` fallback path.
- Policy artifacts: policy optimization registry.

Some routes use in-memory fallback storage when the full app state is not configured, mostly for tests or local unconfigured use. Examples include assistant sessions, sandbox generated conversation sets, and route-local fallbacks for what-if or policy optimization.

## Implementation Patterns

### Composition Through App State

The FastAPI lifespan is the main dependency wiring point. Route modules are mostly thin wrappers that:

1. Pull a store/service from `request.app.state`.
2. Validate request payloads.
3. Invoke domain services.
4. Normalize responses into Pydantic or JSON payloads.
5. Emit event log or WebSocket notifications when needed.

This keeps route modules simple but makes startup wiring important.

### Durable History With UI Continuity

Several stores are written specifically to preserve continuity after restart:

- Builder chat sessions.
- Builder durable events.
- Workbench projects and runs.
- Eval result stores.
- Event logs.
- Optimization memory.
- Improvement lineage.
- Config manifests.
- Build artifact snapshots.

The web UI reflects this with historical/live continuity labels, resumable sessions, and read-only recovery states.

### Mock/Live Transparency

AgentLab has explicit mock/live truth surfaces:

- Runtime mode preference and effective mode.
- Provider readiness and API key tests.
- Eval execution mode metadata.
- Mock-mode reasons in health.
- Strict-live flags for Eval and Workbench.
- Mock reason fields in builder and preview flows.
- Setup guidance when providers are absent or rate-limited.

This is a core architectural theme: simulation is allowed, but the UI and API try to tell the operator when it is happening.

### Evidence-Gated Optimize

The main Optimize API can enforce a completed eval run before optimization. When `require_eval_evidence` is true, the API validates that the provided eval task exists, is of type `eval`, is completed, and has a result payload.

The optimization context can then be scoped to that eval run rather than generic conversation observations. It builds failure samples from structured eval results first, then falls back to task payload cases.

### Typed Candidate Changes

Candidate changes are increasingly structured:

- Mutation surfaces are typed.
- Patch bundles can be stored in pending reviews and attempts.
- Risk classes and operator metadata are tracked.
- Diffs are shown in review surfaces.
- Lineage events track deploy/verify/measure outcomes.
- Pareto archives retain objective vectors and constraint violations.

This is more than prompt string editing; the system is moving toward auditable, typed, reversible optimization operations.

### Safety And Path Controls

Notable safeguards in code:

- Generated agent skill application resolves paths within a workspace root and blocks traversal.
- CX preview resolves config/snapshot paths within a configured workspace root.
- Config/deploy routes validate missing files and bad versions.
- Deploy approval keeps pending review if deploy fails.
- Live mode cannot be enabled without provider credentials.
- Strict-live eval/workbench settings can fail rather than fallback.
- Human controls can pause, pin surfaces, reject experiments, and roll back canaries.
- Registry and skill APIs validate item types and required fields.

## Testing And Verification Coverage

The repository has substantial automated coverage:

- 551 Python test files matching test naming patterns under `tests` when excluding caches.
- 628 non-markdown files under `tests` when excluding caches, including fixtures and golden files.
- 79 frontend test/spec files across `web/src` and the repository excluding ignored dependency/worktree paths.

Test themes include:

- API startup and route aliases.
- Agent library APIs.
- Build, builder chat, builder store, builder execution, builder permissions, coordinator runtime, workbench streaming/cancellation/cost/harness.
- Eval runner, eval API, generated evals, eval strict live, structured results, pairwise comparison, scorers.
- Optimizer, proposer, search, gates, Pareto, bandit, anti-goodhart, adversarial simulation, significance, memory, calibration.
- Deploy, canary, release manager, release API, deploy workers.
- Lineage, improvements, unified reviews, change cards.
- CLI help, CLI streaming JSON for build/eval/optimize/deploy, workbench commands, shell, sessions.
- Provider runtime, model routing, provider keys, strict-live propagation.
- Context engineering, project memory, memory retrieval, system prompt memories.
- Registry, skills, skill composer, validator, migration, promotion, runtime.
- ADK parser/import/export/deploy and CX Studio integration/roundtrip/surface inventory.
- MCP runtime, transports, server, config, bridge.
- Dataset, outcomes, rewards, preferences, policy optimization, OPE.
- Observability, traces, trace grading, event unification, notifications, knowledge mining.
- Frontend pages such as Build, Workbench, EvalRuns, ResultsExplorer, Compare, Optimize, Improvements, Deploy, Setup, Dashboard, EventLog, CX/ADK import/deploy, AgentImprover, UnifiedReviewQueue.

Behavior-changing work should continue to include tests in the relevant layer. This document itself does not change behavior.

## Known Partial Or Mocked Surfaces Observed In Code

Several surfaces are intentionally stubbed, mocked, or partial in the inspected code:

- Assistant backend uses `MockOrchestrator` and in-memory sessions.
- Context aggregate report returns default no-data guidance unless per-trace analyses are available.
- Knowledge entry apply currently marks an entry applied rather than applying a real mutation.
- Skill extraction from conversation and optimization returns 501.
- Multi-agent impact report returns static/sample-shaped summary for report retrieval.
- Some Studio endpoints provide rich mock fallback data when stores are absent.
- Sandbox generated conversation sets and results are in-memory.
- Preference store has a route-level SQLite fallback.
- Policy optimization route has an in-memory fallback registry when not configured.

These are important product truths: the UI/API contracts exist for several forward-looking surfaces, but not all are fully production-backed.

## Primary Workflows In Implementation Detail

### Workflow: Prompt To Deployed Agent

1. User opens `/build`.
2. User enters a prompt, optional XML instruction block, requested model/name, and tool hints.
3. Build calls `/api/intelligence/generate-agent` or `/api/builder/chat`.
4. Transcript intelligence or builder chat produces a generated config object.
5. User previews or refines the draft.
6. User saves through `/api/intelligence/save-agent`, `/api/builder/save`, or `/api/agents`.
7. `persist_generated_config` maps it into runnable runtime config.
8. `ConfigVersionManager` writes a candidate version.
9. Agent appears in `/api/agents`.
10. User navigates to Eval with config path and agent context.
11. Eval run persists structured results and broadcasts completion.
12. Optimize consumes the completed eval run id.
13. Candidate proposal becomes pending review or deploys.
14. Reviewer approves.
15. Deploy saves canary/active config version.
16. Observe/health/traces feed future cycles.

### Workflow: Workbench To Optimize

1. User opens `/workbench`.
2. Workbench hydrates default project and plan snapshot.
3. User starts a streaming build through `/api/workbench/build/stream`.
4. Workbench receives SSE events for plan, tasks, messages, artifacts, validation, reflection, and completion.
5. User iterates or chats with the candidate.
6. User creates an eval bridge through `/api/workbench/projects/{project_id}/bridge/eval`.
7. Bridge persists the candidate config and returns eval request plus optimize request template.
8. User runs eval.
9. Workbench records eval run id through `/api/workbench/projects/{project_id}/bridge/eval-run`.
10. User moves to Optimize with project/config/eval context.

### Workflow: Scoped Optimization

1. User starts Optimize with `eval_run_id`.
2. API validates the eval task is complete.
3. API builds health report from eval payload and structured result store.
4. API extracts failed examples as failure samples.
5. Optimizer selects search strategy and budget from mode router.
6. Optimizer proposes candidate config.
7. Eval runner scores baseline and candidate.
8. Gates/significance/adversarial checks determine acceptance.
9. Optimization memory records attempt.
10. If approval is required, pending review is saved.
11. WebSocket/event log broadcast completion.
12. Review approval deploys, rejection records human rejection.

### Workflow: Continuous Loop

1. User starts loop through `/api/loop/start`.
2. Loop scheduler resolves delay/interval/cron mode.
3. Checkpoint can resume a partial loop.
4. Each cycle observes recent conversations.
5. If unhealthy, optimizer proposes and evaluates a candidate.
6. Accepted candidates deploy as canary.
7. Canary manager checks verdict and promotes/rolls back when ready.
8. Loop writes checkpoint and cycle history.
9. Resource monitor warns on memory/CPU thresholds.
10. Dead-letter queue captures cycle exceptions.
11. WebSocket and event log record cycle events.

### Workflow: Trace To Eval

1. Trace events and spans are stored in trace store.
2. User opens trace details, grades, graph, or blame map.
3. User promotes a trace through `/api/traces/{trace_id}/promote`.
4. `TracePromoter` builds a candidate eval case.
5. CLI helper writes the eval case into the requested eval cases directory.
6. Future eval runs include the promoted case as regression evidence.

### Workflow: Import External Agent

1. User chooses Connect, ADK, or CX import path.
2. Adapter scans source/runtime/snapshot.
3. Adapter produces imported spec or typed snapshot.
4. AgentLab materializes config, snapshots, evals, portability reports, and adapter metadata.
5. Imported config is registered as candidate version.
6. Agent appears in Agent Library and can move through Eval/Optimize/Deploy.

## Architectural Strengths

- The product has a clear build-eval-optimize-review-deploy loop.
- Config versions make deployment auditable and reversible.
- Eval evidence is first-class and increasingly required before optimization.
- The builder/workbench stack has durable history and streaming UX.
- Mock/live boundaries are surfaced rather than hidden.
- The optimizer has multiple safety layers: gates, significance, adversarial checks, human control, pending reviews, canary deploy, rollback.
- Portability is a real architecture concern through canonical IR, adapters, ADK, CX, and A2A.
- Governance is broad: registries, runbooks, skills, judges, rewards, preferences, policies, outcomes.
- Tests cover an unusually wide set of backend, CLI, and frontend behavior.

## Architectural Risks And Maintenance Notes

- `api/server.py` is a large composition root. Service wiring is centralized but dense.
- Many route modules pull directly from `request.app.state`; missing state is handled inconsistently across domains.
- Some stores use configured workspace paths while others have route-local fallbacks. This helps tests but can surprise operators if a surface silently uses isolated storage.
- Several advanced surfaces have complete UI/API contracts but mock or partial backend behavior.
- There are duplicate conceptual surfaces: optimizer pending reviews, unified reviews, change cards, improvements, opportunities, and experiments. The `/api/improvements` and `/api/reviews` aggregation layers are the current consolidation points.
- Project memory and generated memory are code-managed text artifacts. Their contents were not inspected here.
- The web app includes backup files and legacy redirects, which may need cleanup once route consolidation is final.

## Source File Landmarks

Core entrypoints:

- `runner.py`
- `api/server.py`
- `api/main.py`
- `web/src/App.tsx`
- `web/src/components/Layout.tsx`
- `pyproject.toml`
- `web/package.json`
- `agentlab.yaml`
- `Makefile`

Agent and config:

- `agent/config/schema.py`
- `agent/config/runtime.py`
- `agent/eval_agent.py`
- `agent/root_agent.py`
- `shared/canonical_ir.py`
- `shared/canonical_ir_convert.py`

Build and Workbench:

- `builder/types.py`
- `builder/store.py`
- `builder/orchestrator.py`
- `builder/execution.py`
- `builder/chat_service.py`
- `builder/workbench.py`
- `builder/workbench_agent.py`
- `builder/coordinator_runtime.py`
- `builder/workspace_config.py`
- `shared/build_artifact_store.py`

Eval:

- `evals/runner.py`
- `evals/scorer.py`
- `evals/results_store.py`
- `evals/auto_generator.py`
- `evals/pairwise.py`

Optimize:

- `optimizer/loop.py`
- `optimizer/proposer.py`
- `optimizer/mutations.py`
- `optimizer/search.py`
- `optimizer/gates.py`
- `optimizer/pareto.py`
- `optimizer/memory.py`

Deploy:

- `deployer/versioning.py`
- `deployer/canary.py`
- `deployer/publish.py`
- `deployer/lineage.py`

Observe:

- `observer/__init__.py`
- `observer/metrics.py`
- `observer/anomaly.py`
- `observer/classifier.py`
- `observer/traces.py`
- `observer/trace_grading.py`
- `observer/trace_graph.py`
- `observer/blame_map.py`
- `observer/trace_promoter.py`

Governance and learning:

- `core/skills/types.py`
- `core/skills/store.py`
- `registry/store.py`
- `core/project_memory.py`
- `rewards`
- `policy_opt`
- `data`

External integrations:

- `adk`
- `cx_studio`
- `adapters`
- `a2a`
- `mcp_server`

Primary web pages:

- `web/src/pages/Build.tsx`
- `web/src/pages/AgentWorkbench.tsx`
- `web/src/pages/AgentImprover.tsx`
- `web/src/pages/EvalRuns.tsx`
- `web/src/pages/ResultsExplorer.tsx`
- `web/src/pages/Compare.tsx`
- `web/src/pages/Optimize.tsx`
- `web/src/pages/Improvements.tsx`
- `web/src/pages/Deploy.tsx`
- `web/src/pages/Setup.tsx`
- `web/src/pages/Dashboard.tsx`

## Bottom Line

AgentLab is implemented as an agent quality lifecycle platform, not just an eval runner or prompt editor. The strongest implemented path is:

Build or import an agent, save it as a versioned config, run eval evidence, inspect structured results, optimize against failures, review candidate changes, deploy canary or active versions, and observe production traces/outcomes for the next cycle.

The codebase also contains broader platform ambitions around skills, runbooks, rewards, policy optimization, CX/ADK portability, A2A discovery, context engineering, knowledge mining, and assistant-guided operations. Some of these are fully backed by stores and services; others are intentionally mocked or partially implemented. The current architecture already exposes the product journey end to end, with durability, review gates, versioned deployment, and a strong emphasis on making mock versus live behavior visible to operators.
