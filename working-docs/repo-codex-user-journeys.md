# AgentLab User Journeys - Codex Notes

## Scope

This document maps the product journeys implemented by the repo. It focuses on what an operator, developer, or automation client can actually do through the UI, CLI, API, and MCP surfaces. It distinguishes implemented paths from docs-only or aspirational framing where the code says something different.

## Primary Operator Journey

The core journey is:

`Create/import agent -> build/refine -> evaluate -> inspect results -> compare -> optimize -> review -> deploy -> observe`

The current web navigation makes this concrete as:

`Setup -> Build -> Workbench -> Eval Runs -> Results Explorer -> Compare -> Studio/Optimize -> Improvements -> Deploy`

The CLI makes the same spine concrete as:

`agentlab new -> agentlab build/connect -> agentlab eval run -> agentlab eval results/compare -> agentlab optimize -> agentlab review -> agentlab deploy`

## Journey 1: Start A Workspace

### User Goal

Create an AgentLab workspace with the local files and stores needed to evaluate and improve an agent.

### UI Path

- Open the web console.
- Use `/setup` for workspace readiness, provider/mode status, data-store presence, MCP setup status, and recommended next commands.
- `/dashboard` acts as the home/status overview in the app shell.

### CLI Path

- `agentlab new NAME`
- Optional: `agentlab new NAME --demo`
- Hidden legacy path: `agentlab init`
- Follow-up readiness checks:
  - `agentlab status`
  - `agentlab doctor`
  - `agentlab mode show`
  - `agentlab provider configure`
  - `agentlab model show`

### API Path

- `GET /api/setup/overview`
- `GET /api/health/ready`
- `GET /api/health`
- `GET /api/health/system`

### State Created Or Read

- Workspace directories: `.agentlab/`, `configs/`, `evals/`.
- Runtime files: `agentlab.yaml`, `AGENTLAB.md`.
- Metadata: `.agentlab/workspace.json`.
- Optional provider settings: `.agentlab/providers.json`.
- Config manifest: `configs/manifest.json`.
- Local SQLite/JSON stores as flows are used.

### Implementation Evidence

- CLI workspace creation and legacy init are in `runner.py`.
- Workspace path logic is in `cli/workspace.py`.
- API workspace readiness is in `api/workspace_state.py`, `api/routes/setup.py`, and `api/routes/health.py`.
- Tests include `tests/test_workspace_cli.py`, `tests/test_api_server_startup.py`, and `tests/test_cli_ux_refactor_v2.py`.

### Current Reality Notes

- The product is local-first. A workspace can be invalid or absent, and health/setup endpoints expose that state instead of failing opaquely.
- API startup may change process CWD into a valid workspace root for service compatibility, then restore it on shutdown.

## Journey 2: Build An Agent From A Prompt

### User Goal

Turn a natural-language agent idea into a concrete AgentLab config, starter eval cases, and saved build artifacts.

### UI Path

- Go to `/build`.
- Use Build tabs:
  - Prompt builder.
  - Transcript import/intelligence.
  - Builder Chat.
  - Saved artifacts.
- The UI can generate an agent, preview it, save it to the Agent Library, and proceed to Eval.

### CLI Path

- `agentlab build "agent idea or task description"`
- `agentlab build show latest`
- Hidden compatibility alias: `agentlab build-show latest`

### API Path

- Builder chat:
  - `POST /api/builder/chat`
  - `GET /api/builder/chat/sessions`
  - `GET /api/builder/session/{id}`
  - export/save/preview endpoints under `/api/builder`.
- Intelligence/build artifact routes under `/api/intelligence`.
- Agent save/list routes under `/api/agents`.

### State Created Or Read

- Generated config YAML under `configs/`.
- Generated eval cases under `evals/cases/`.
- `.agentlab/build_artifact_latest.json`.
- `shared.build_artifact_store.BuildArtifactStore` entries.
- Builder chat sessions in `.agentlab/builder_chat_sessions.db`.
- Config versions via `deployer.version_manager` when the config is registered.

### Implementation Evidence

- UI: `web/src/pages/Build.tsx`.
- CLI: `runner.py` build group.
- Builder chat: `builder/chat_service.py`, `api/routes/builder.py`.
- Config persistence: `builder/workspace_config.py`.
- Tests include `tests/test_cli_ux_refactor_v2.py`, `tests/test_builder_api.py`, and frontend route/page tests.

### Current Reality Notes

- The Build page is the primary route for old Builder/Agent Studio/Assistant concepts. Legacy `/builder`, `/agent-studio`, `/assistant`, and `/intelligence` routes redirect to `/build` tabs.
- Build can produce real versioned configs, not only preview artifacts.

## Journey 3: Iteratively Build In Workbench

### User Goal

Use a structured build harness to iteratively create, inspect, validate, and refine an agent before running formal eval.

### UI Path

- Go to `/workbench`.
- Hydrate or create the default Workbench project.
- Start a streaming build from a prompt.
- Inspect generated artifacts, plan state, validation evidence, and compatibility output.
- Iterate on the build.
- Cancel an active run if needed.
- Bridge the generated candidate to Eval.

### API Path

- Project and plan:
  - `POST /api/workbench/projects`
  - `GET /api/workbench/projects/default`
  - `GET /api/workbench/projects/{project_id}`
  - `POST /api/workbench/plan`
  - `GET /api/workbench/projects/{project_id}/plan`
- Mutations and validation:
  - `POST /api/workbench/apply`
  - `POST /api/workbench/test`
  - `POST /api/workbench/rollback`
- Streaming:
  - `POST /api/workbench/build/stream`
  - `POST /api/workbench/build/iterate`
- Control:
  - `POST /api/workbench/runs/{run_id}/cancel`
  - `POST /api/workbench/projects/{project_id}/runs/{run_id}/cancel`
- Handoff:
  - `POST /api/workbench/projects/{project_id}/bridge/eval`

### State Created Or Read

- `.agentlab/workbench_projects.json`: canonical Workbench project state.
- Generated exports/artifacts under the Workbench project snapshot.
- Materialized AgentLab config when bridging to Eval.
- Generated eval cases and build artifacts through `persist_generated_config`.

### Implementation Evidence

- UI: `web/src/pages/AgentWorkbench.tsx`.
- Store/service: `builder/workbench.py`.
- API: `api/routes/workbench.py`.
- Bridge: `builder/workbench_bridge.py`.
- Tests: `tests/test_workbench_eval_optimize_bridge.py` and web journey tests.

### Current Reality Notes

- Workbench is JSON-backed rather than SQLite-backed.
- The Workbench-to-Eval bridge intentionally does not start Eval or Optimize. It materializes a config and returns typed request payloads.
- Optimize is blocked until there is completed eval evidence. This is enforced in the UI and covered by tests.

## Journey 4: Import An Existing Agent

### User Goal

Bring an existing external agent into AgentLab so it can be evaluated, improved, and redeployed or exported.

### UI Path

- Go to `/connect` for general import.
- Use integration-specific routes for ADK and CX:
  - `/adk/import`
  - `/cx/import`
  - `/cx/studio`

### CLI Path

- `agentlab connect openai-agents --path PATH`
- `agentlab connect anthropic --path PATH`
- `agentlab connect http --url URL`
- `agentlab connect transcript --file FILE`
- Advanced ADK:
  - `agentlab adk import`
  - `agentlab adk export`
  - `agentlab adk diff`
  - `agentlab adk deploy`
- Advanced CX:
  - `agentlab cx auth`
  - `agentlab cx import`
  - `agentlab cx export`
  - `agentlab cx diff`
  - `agentlab cx sync`
  - `agentlab cx deploy`

### API Path

- `GET /api/connect`
- `POST /api/connect/import`
- `/api/adk/*`
- `/api/cx/*`

### State Created Or Read

- Connected workspace files.
- Adapter spec/config files:
  - `.agentlab/adapter_spec.json`
  - `.agentlab/adapter_config.json`
- Imported config version under `configs/`.
- Starter eval cases.
- Optional imported traces.
- CX snapshots/manifests under `.agentlab/cx/`.
- ADK source snapshots and portability reports.

### Implementation Evidence

- Adapter model: `adapters/base.py`.
- Workspace materialization: `adapters/workspace_builder.py`.
- Importers: `adapters/openai_agents.py`, `adapters/anthropic_claude.py`, `adapters/http_webhook.py`, `adapters/transcript.py`.
- ADK: `adk/importer.py`, `adk/exporter.py`, `adk/deployer.py`, `api/routes/adk.py`.
- CX: `cx_studio/importer.py`, `cx_studio/exporter.py`, `cx_studio/deployer.py`, `api/routes/cx_studio.py`.
- Tests include `tests/test_connect_cli.py`, `tests/test_adk_api.py`, `tests/test_cx_studio_api.py`, and `tests/test_cx_roundtrip.py`.

### Current Reality Notes

- Connect exists in the UI, but the current simple-mode navigation does not include `/connect`; it is an integration/pro route.
- External platform deploy paths require real credentials and tooling, especially ADK deploy with `gcloud`.

## Journey 5: Run Eval And Inspect Results

### User Goal

Measure agent behavior against test cases, generated suites, or datasets, then inspect examples and metrics.

### UI Path

- Go to `/evals`.
- Select an active agent/config and eval source.
- Start an eval run.
- Watch task continuity state and completion broadcasts.
- Open `/evals/:id` for details.
- Open `/results` or `/results/:runId` for Results Explorer.
- Filter examples, inspect failures, annotate examples, export results.

### CLI Path

- `agentlab eval run`
- `agentlab eval run --config PATH`
- `agentlab eval run --dataset FILE --split SPLIT`
- `agentlab eval run --category CATEGORY`
- `agentlab eval results`
- `agentlab eval results annotate`
- `agentlab eval results export`
- `agentlab eval results diff`
- `agentlab eval generate`
- `agentlab eval breakdown`

### API Path

- Start/list/detail:
  - `POST /api/eval/run`
  - `GET /api/eval/runs`
  - `GET /api/eval/runs/{run_id}`
  - `GET /api/eval/runs/{run_id}/cases`
  - `GET /api/eval/history`
- Structured results:
  - `GET /api/evals/results`
  - `GET /api/evals/results/{run_id}`
  - `GET /api/evals/results/{run_id}/summary`
  - `GET /api/evals/results/{run_id}/examples`
  - `POST /api/evals/results/{run_id}/examples/{example_id}/annotations`
  - `GET /api/evals/results/{run_id}/export`
  - `GET /api/evals/results/{run_id}/diff`
- Generated eval suites:
  - `POST /api/evals/generate`
  - `GET /api/evals/generated`
  - suite accept/edit/delete endpoints.

### State Created Or Read

- `.agentlab/tasks.db`: background task state.
- `.agentlab/eval_history.db`: legacy eval history.
- Structured eval results SQLite store.
- `.agentlab/eval_results_latest.json`: latest CLI handoff file.
- Generated suite store.
- Dataset store when dataset-backed evals are used.
- Websocket broadcasts such as `eval_complete`.

### Implementation Evidence

- Runner: `evals/runner.py`.
- Scoring: `evals/scorer.py`.
- Structured results: `evals/results_model.py`, `evals/results_store.py`.
- History: `evals/history.py`.
- Generated suites: `evals/auto_generator.py`.
- UI: `web/src/pages/EvalRuns.tsx`, Results Explorer pages.
- API: `api/routes/eval.py`, `api/routes/results.py`, `api/routes/generated_evals.py`.
- Tests include `tests/test_eval_pipeline.py`, `tests/test_eval_runner_model.py`, `tests/evals/test_results_store.py`, `tests/test_results_cli.py`, and `tests/test_generated_evals_api.py`.

### Current Reality Notes

- Eval has two result systems: legacy composite score/history and structured result examples. Both are current and serve different consumers.
- Eval tasks survive restart in completed state; running/pending tasks are marked interrupted on startup by `TaskManager`.

## Journey 6: Compare Runs Or Candidates

### User Goal

Decide whether one config or eval run is better than another before optimizing or deploying.

### UI Path

- Go to `/compare`.
- Select two eval runs or candidates.
- Review pairwise outcome and summary.

### CLI Path

- `agentlab eval compare --config-a A --config-b B`
- `agentlab eval compare --left-run RUN_A --right-run RUN_B`
- `agentlab eval results diff BASELINE_RUN CANDIDATE_RUN`

### API Path

- `POST /api/evals/compare`
- `GET /api/evals/compare/{comparison_id}`
- `GET /api/evals/compare`
- Results diff endpoint under `/api/evals/results/{run_id}/diff`.

### State Created Or Read

- Pairwise comparison SQLite store.
- Structured result examples for run diffs.
- Eval history or result stores depending on comparison type.

### Implementation Evidence

- Pairwise model/engine: `evals/pairwise.py`.
- API: `api/routes/compare.py`, `api/routes/results.py`.
- CLI compare logic: `runner.py`.
- Tests: `tests/evals/test_pairwise.py`, `tests/test_results_cli.py`.

## Journey 7: Optimize From Evidence

### User Goal

Ask AgentLab to propose an improvement based on failures, eval evidence, or observed conversations.

### UI Path

- Go to `/optimize`.
- Choose standard, advanced, or research mode.
- Optionally arrive from Eval with `evalRunId`.
- Start optimization.
- Monitor task status and result.
- If approval is required, continue to Improvements.

### CLI Path

- `agentlab optimize --cycles 1`
- `agentlab optimize --continuous`
- `agentlab optimize --mode standard`
- `agentlab optimize --mode advanced`
- `agentlab optimize --mode research`
- `agentlab optimize --full-auto` for deployment without manual promotion gates.

### API Path

- `POST /api/optimize/run`
- `GET /api/optimize/history`
- `GET /api/optimize/history/{id}`
- `GET /api/optimize/surfaces`
- `GET /api/optimize/pending`
- `POST /api/optimize/pending/{id}/approve`
- `POST /api/optimize/pending/{id}/reject`
- `GET /api/optimize/pareto`
- Stream route under `/api/optimize/stream`.

### State Created Or Read

- Conversation and observer data when no eval run is supplied.
- Completed eval task/result data when `eval_run_id` is supplied.
- `optimizer_memory.db` attempts.
- Pending review JSON files.
- Optional change cards/experiments depending on improvement type.
- Websocket broadcasts such as `optimize_complete` or `optimize_pending_review`.

### Implementation Evidence

- Core optimizer: `optimizer/loop.py`.
- Proposal logic: `optimizer/proposer.py`.
- Gates: `optimizer/gates.py`.
- Memory: `optimizer/memory.py`.
- API: `api/routes/optimize.py`.
- UI: `web/src/pages/Optimize.tsx`.
- Tests: `tests/test_optimizer.py`, `tests/test_optimize_api.py`, `tests/test_optimize_surface_inventory.py`, `tests/test_workbench_eval_optimize_bridge.py`.

### Current Reality Notes

- Optimizer is evidence-driven but deploy is not automatic by default. The API commonly creates a pending review instead of changing active config.
- Workbench-origin candidates must complete Eval before Optimize is enabled.
- The optimizer has simple/pro/hybrid/research-style internals, but user-facing modes are simplified.

## Journey 8: Review Proposed Improvements

### User Goal

Inspect, approve, reject, or export proposed changes before they affect deployed config.

### UI Path

- Go to `/improvements`.
- Review tabs:
  - Opportunities.
  - Experiments.
  - Review queue.
  - History.
- Approve/reject unified items.

### CLI Path

- `agentlab review`
- `agentlab review list`
- `agentlab review show pending`
- `agentlab review apply pending`
- `agentlab review reject pending`
- `agentlab review export`
- Compatibility alias group: `agentlab changes`.

### API Path

- Unified review:
  - `GET /api/reviews/pending`
  - `GET /api/reviews/all`
  - `GET /api/reviews/stats`
  - `POST /api/reviews/{item_id}/approve`
  - `POST /api/reviews/{item_id}/reject`
- Change cards:
  - `GET /api/changes`
  - `GET /api/changes/{id}`
  - `POST /api/changes/{id}/apply`
  - `POST /api/changes/{id}/reject`
  - hunk/export/audit endpoints.
- Opportunities/experiments:
  - `/api/opportunities/*`
  - `/api/experiments/*`

### State Created Or Read

- Pending optimizer reviews.
- Change card SQLite store.
- Optimization memory statuses.
- Experiment store and opportunity queue.
- Version manager if an approval deploys a proposed config.

### Implementation Evidence

- API: `api/routes/reviews.py`, `api/routes/changes.py`, `api/routes/opportunities.py`, `api/routes/experiments.py`.
- Stores/models: `optimizer/pending_reviews.py`, `optimizer/change_card.py`, `observer/opportunities.py`.
- UI: `web/src/pages/Improvements.tsx`.
- CLI: `runner.py` review group.
- Tests include route alias and value-chain tests.

### Current Reality Notes

- `Improvements` is the current product surface. Legacy `/review`, `/reviews`, `/changes`, `/opportunities`, `/experiments`, and `/autofix` route into the Improvements experience in the web app.
- Unified review aggregates multiple underlying stores but does not erase their separate lifecycles.

## Journey 9: Deploy, Promote, Or Roll Back

### User Goal

Move a candidate config into active or canary status, monitor rollout state, and roll back when needed.

### UI Path

- Go to `/deploy`.
- Inspect active and canary versions.
- Select canary or immediate strategy.
- Promote current canary.
- Roll back current canary.

### CLI Path

- `agentlab deploy canary`
- `agentlab deploy immediate`
- `agentlab deploy release`
- `agentlab deploy rollback`
- `agentlab deploy status`
- Optional CX target:
  - `agentlab deploy --target cx-studio ...`

### API Path

- `POST /api/deploy`
- `GET /api/deploy/status`
- `POST /api/deploy/promote`
- `POST /api/deploy/rollback`

### State Created Or Read

- `configs/manifest.json`.
- `configs/v###.yaml`.
- Active/canary config versions.
- Canary conversation outcomes and verdicts.
- Optional release objects and stage records.

### Implementation Evidence

- Versioning: `deployer/versioning.py`.
- Canary/deployer: `deployer/canary.py`.
- Release governance: `deployer/release_manager.py`, `deployer/release_objects.py`.
- UI: `web/src/pages/Deploy.tsx`.
- API: `api/routes/deploy.py`.
- CLI: `runner.py` deploy group.
- Tests: `tests/test_deployer.py`, `tests/test_e2e_value_chain_cli.py`.

### Current Reality Notes

- The practical current deploy path is config-manifest-based active/canary state.
- Richer release objects and staged release governance are present but separate from the simplest deploy API flow.

## Journey 10: Observe, Diagnose, And Operate

### User Goal

Understand production or test behavior, diagnose failures, inspect traces, and monitor local system health.

### UI Path

- `/dashboard` for workspace overview.
- `/conversations` for conversation records.
- `/traces` for trace search/error sessions/blame.
- `/events` for system and builder timeline.
- `/loop` for continuous-loop monitoring.
- `/context`, `/what-if`, `/impact`, `/diagnose`, and `/knowledge` for deeper analysis routes.

### CLI Path

- `agentlab status`
- `agentlab doctor`
- `agentlab trace ...`
- `agentlab loop ...`
- Hidden control aliases: `agentlab pause`, `agentlab resume`, `agentlab reject`, `agentlab pin`, `agentlab unpin`.

### API Path

- `/api/conversations/*`
- `/api/traces/*`
- `/api/events`
- `/api/events/unified`
- `/api/loop/*`
- `/api/control/*`
- `/api/diagnose`
- `/api/context/*`
- `/api/what-if/*`
- `/api/impact/*`
- `/api/knowledge/*`
- `/api/health/*`

### State Created Or Read

- Conversations DB.
- Trace store.
- Event log.
- Builder durable event history.
- Loop checkpoint store.
- Dead-letter queue.
- Resource monitor/watchdog state.
- Optimization opportunities and context reports.

### Implementation Evidence

- Conversation store: `logger/store.py`.
- Observer: `observer/classifier.py`, `observer/metrics.py`, `observer/traces.py`, `observer/opportunities.py`.
- Event log: `data/event_log.py`, `api/routes/events.py`, `builder/events.py`.
- Loop: `api/routes/loop.py`.
- Health: `api/routes/health.py`.
- Tests: `tests/test_observer.py`, `tests/test_event_unification.py`, `tests/test_p0_journey_fixes.py`.

### Current Reality Notes

- Continuous loop state is a mix of module-level process state, persisted task status, checkpoints, event log, and DLQ records.
- The unified event timeline merges system events and builder lifecycle events, with duplicate suppression for bridged builder events.

## Journey 11: Manage Datasets, Judges, Scorers, Outcomes, And Rewards

### User Goal

Build better evaluation data and governance criteria from traces, outcomes, human feedback, custom scorers, preferences, and reward definitions.

### UI Path

- `/judge-ops`
- `/scorer-studio`
- `/reward-studio`
- `/preference-inbox`
- `/policy-candidates`
- `/reward-audit`

### CLI Path

- Advanced commands around `dataset`, `scorer`, `reward`, `rl`, and related hidden/governance groups.

### API Path

- `/api/datasets/*`
- `/api/outcomes/*`
- `/api/judges/*`
- `/api/scorers/*`
- `/api/rewards/*`
- `/api/preferences/*`
- `/api/rl/*`
- `/api/curriculum/*`

### State Created Or Read

- Dataset SQLite store with rows and immutable versions.
- Outcome imports and calibration state.
- Judge feedback/drift/calibration data.
- NL scorer specs.
- Reward definitions and audits.
- Preference records and policy candidates.

### Implementation Evidence

- Dataset service: `data/dataset_store.py`, `data/dataset_service.py`.
- Scoring: `evals/nl_scorer.py`, `judges/*`, `graders/*`.
- Rewards/policy: `rewards/*`, `policy_opt/*`.
- API route files under `api/routes/datasets.py`, `api/routes/outcomes.py`, `api/routes/judges.py`, `api/routes/scorers.py`, `api/routes/rewards.py`, `api/routes/preferences.py`, and `api/routes/policy_opt.py`.
- Tests include `tests/test_data_engine.py`, `tests/test_dataset_builder.py`, reward/policy/preference tests, and web route tests.

## Journey 12: Generate And Apply Agent Skills

### User Goal

Identify skill gaps from agent behavior, generate reusable agent skills, review them, and apply approved files safely.

### UI Path

- `/skills`
- `/agent-skills`
- `/registry`
- `/runbooks`
- `/memory`

### CLI Path

- Advanced or hidden registry/skill/runbook commands.
- MCP tools also expose skill-gap and skill-recommendation workflows.

### API Path

- `/api/skills/*`
- `/api/agent-skills/*`
- `/api/registry/*`
- `/api/runbooks/*`
- `/api/memory/*`

### State Created Or Read

- Core skill store.
- Agent skill store.
- Registry store.
- Generated skill files.
- Gap metadata.
- Project memory records.

### Implementation Evidence

- Registry: `registry/store.py`, `registry/skills.py`.
- Core skills: `core/skills/*`.
- Generated skills: `agent_skills/store.py`, `agent_skills/generator.py`.
- API: `api/routes/skills.py`, `api/routes/agent_skills.py`, `api/routes/registry.py`.
- Tests: `tests/test_agent_skill_store.py`, `tests/test_agent_skills_api.py`, and `tests/test_skills*.py`.

### Current Reality Notes

- Registry and generated agent skills are related but not the same subsystem.
- Generated skill apply flows include path containment safeguards.

## Journey 13: Automate Through MCP

### User Goal

Let external AI clients query AgentLab state, run evals, inspect failures, propose fixes, scaffold agents, or open PRs through MCP.

### CLI Path

- `agentlab mcp-server`
- `agentlab mcp init`
- `agentlab mcp list`
- `agentlab mcp add`
- `agentlab mcp remove`
- `agentlab mcp inspect`

### MCP Surface

- JSON-RPC server over stdio or HTTP.
- Tools include status, explain, diagnose, failure samples, suggest fix, edit, eval, eval compare, skill gaps, skill recommendations, replay, diff, scaffold agent, generate evals, run sandbox, inspect trace, sync ADK source, and open PR.
- Resources include configs, traces, evals, skills, and datasets.
- Prompts cover diagnosis, failure-pattern fixes, eval generation, diff explanation, and instruction optimization.

### State Created Or Read

- Same local workspace stores as the CLI/API, but instantiated from MCP process environment paths.
- MCP client config files for Claude Code, Codex, Cursor, and Windsurf.

### Implementation Evidence

- Server: `mcp_server/server.py`.
- Transport: `mcp_server/transport.py`.
- Tools/resources/prompts: `mcp_server/tools.py`, `mcp_server/resources.py`, `mcp_server/prompts.py`.
- CLI setup/runtime: `cli/mcp_setup.py`, `cli/mcp_runtime.py`.
- Tests: `tests/test_mcp_server.py`, `tests/test_mcp_runtime.py`, `tests/test_mcp_init.py`.

### Current Reality Notes

- MCP is operationally parallel to the FastAPI app. It does not reuse `api.server` `app.state`, so environment/path alignment is important.
- One code tension found during reading: `mcp_server/tools.py` calls `ConfigVersionManager.load_version(...)`, but `deployer/versioning.py` in this checkout does not appear to define `load_version`.

## Cross-Journey Continuity

Several journeys rely on the same continuity mechanics:

- Background API tasks are persisted and pollable through `/api/tasks/{task_id}`.
- Running/pending tasks are marked `interrupted` on startup.
- Websocket broadcasts update the UI for eval, optimize, loop, and related background work.
- CLI JSON output uses a standard envelope from `cli/json_envelope.py`.
- Progress output can be emitted as text, JSON, or stream JSON depending on command support.

## Key Journey Tensions

- Docs sometimes present `Connect` as part of day-one navigation, but current simple-mode navigation omits it.
- Docs and code both recognize Eval, Results, and Compare as separate stages; older docs sometimes collapse these mentally into a single eval area.
- Review is now primarily `Improvements` in the web UI, while CLI still exposes `agentlab review` and compatibility `changes` flows.
- Workbench is now a first-class UI route and API subsystem. Older docs that omit it are behind the code.
- Advanced governance, tenant, billing, policy, reward, and integration surfaces exist, but the product's most coherent current spine is still the local operator loop from Build through Deploy.
