# AgentLab Architecture Map - Codex Notes

## Scope

This map explains how the major systems in the repo fit together: entrypoints, subsystem boundaries, state stores, event flows, and product handoffs. It reflects current implementation in this checkout, not only architecture-document intent.

## Architecture In One Page

AgentLab is a local-first agent workbench with four main surfaces over shared workspace state:

```text
                 Web UI (React/Vite)
                       |
                       | HTTP + SSE + websocket
                       v
              FastAPI app in api/server.py
                       |
          app.state service graph and route modules
                       |
      ------------------------------------------------
      |          |          |          |             |
   Builder    Eval     Optimizer    Deploy      Observe/Govern
      |          |          |          |             |
      ------------------------------------------------
                       |
              Local workspace state
     agentlab.yaml, configs/, evals/, .agentlab/*.db/json

CLI in runner.py -------------------------------^
MCP server -------------------------------------^
External integrations ---- adapters/ADK/CX -----^
```

The web app primarily talks to FastAPI. The CLI and MCP server often instantiate the same stores and engines directly. External integrations convert external agent formats into AgentLab workspace artifacts and config versions.

## Main Entrypoints

### CLI Entrypoint

- Package script: `agentlab = "runner:cli"` in `pyproject.toml`.
- Main implementation: `runner.py`.
- Command framework: Click.
- Helper modules: `cli/workspace.py`, `cli/mode.py`, `cli/model.py`, `cli/providers.py`, `cli/output.py`, `cli/json_envelope.py`, `cli/progress.py`, `cli/mcp_setup.py`, `cli/mcp_runtime.py`.

Boundary:

- The CLI is not simply an API client. It directly constructs `EvalRunner`, `Optimizer`, `Deployer`, `ConversationStore`, `OptimizationMemory`, `BuildArtifactStore`, and integration services.

### API Entrypoint

- ASGI alias: `api/main.py`.
- Composition root: `api/server.py`.
- Route modules: `api/routes/*`.
- Background task runtime: `api/tasks.py`.
- Websocket manager: `api/websocket.py`.

Boundary:

- `api/server.py` owns service construction and route inclusion. Most route handlers access services through `request.app.state`.
- Routes are included explicitly, not discovered dynamically.

### Web Entrypoint

- SPA route table: `web/src/App.tsx`.
- Navigation source: `web/src/lib/navigation.ts`.
- API hooks/types: `web/src/lib/api.ts`, `web/src/lib/types.ts`.
- Shell components: `web/src/components/Layout.tsx`, `web/src/components/Sidebar.tsx`.

Boundary:

- The web app is a client of FastAPI and websocket/SSE streams. It does not run eval/optimizer/deploy logic itself.

### MCP Entrypoint

- Server: `mcp_server/server.py`.
- Tools: `mcp_server/tools.py`.
- Resources: `mcp_server/resources.py`.
- Prompts: `mcp_server/prompts.py`.
- Transport: `mcp_server/transport.py`.

Boundary:

- MCP is operationally parallel to FastAPI. It instantiates stores from environment/workspace paths and does not reuse `api.server` `app.state`.

## Workspace State Model

Workspace state is the main shared contract between surfaces.

```text
Workspace root
|
|-- agentlab.yaml                  Runtime config
|-- AGENTLAB.md                    Workspace guide/context
|-- configs/
|   |-- manifest.json              Version manifest, active/canary pointers
|   |-- v001.yaml                  Versioned config snapshots
|   |-- v002.yaml
|
|-- evals/
|   |-- cases/                     YAML eval cases
|
|-- .agentlab/
|   |-- workspace.json             Workspace metadata, active config path, mode
|   |-- providers.json             Provider settings
|   |-- settings.json              Permissions/model overrides
|   |-- conversations.db           Conversation records
|   |-- optimizer_memory.db        Optimization attempts
|   |-- eval_history.db            Legacy eval history
|   |-- tasks.db                   Background task continuity
|   |-- change_cards.db            Reviewable change cards
|   |-- events.db                  System events
|   |-- workbench_projects.json    Workbench canonical project state
|   |-- builder_workspace.db       Builder objects
|   |-- builder_chat_sessions.db   Builder chat sessions
|   |-- generated_evals.json       Generated eval suites
|   |-- cx/                        CX snapshots/workspaces/manifests
|   |-- adapter_spec.json          Connect import spec
|   |-- adapter_config.json        Connect import config
```

Important owners:

- `cli/workspace.py` owns workspace path discovery and metadata helpers.
- `api/workspace_state.py` exposes workspace validity to the backend.
- `deployer/versioning.py` owns `configs/manifest.json` and versioned config snapshots.
- `builder/workbench.py` owns `.agentlab/workbench_projects.json`.
- `api/tasks.py` owns task persistence and continuity labels.

## FastAPI Service Graph

`api/server.py` builds the backend service graph during lifespan startup. Major services include:

- Workspace/runtime:
  - `workspace_state`
  - `runtime_config`
- Core state:
  - `conversation_store`
  - `version_manager`
  - `observer`
  - `trace_store`
  - `event_log`
  - `structured_logger`
- Eval and results:
  - `eval_runner`
  - `results_store`
  - `pairwise_store`
  - `generated_eval_store`
  - `auto_eval_generator`
- Optimize/review/deploy:
  - `optimization_memory`
  - `optimizer`
  - `proposer`
  - `pending_review_store`
  - `change_card_store`
  - `deployer`
  - `cost_tracker`
  - `control_store`
- Reliability:
  - `task_manager`
  - `ws_manager`
  - `dead_letter_queue`
  - `checkpoint_store`
  - `loop_watchdog`
  - `resource_monitor`
- Builder/workbench:
  - `builder_store`
  - `builder_project_manager`
  - `builder_orchestrator`
  - `builder_events`
  - `builder_permissions`
  - `builder_execution`
  - `builder_metrics`
  - `builder_artifacts`
  - `builder_chat_service`
  - `workbench_store`
- Intelligence and artifacts:
  - `transcript_report_store`
  - `transcript_intelligence_service`
  - `build_artifact_store`
  - `what_if_engine`
- Registry/skills/governance:
  - `core_skill_store`
  - `skill_engine`
  - `skill_store`
  - `registry_store`
  - `runbook_store`
  - `agent_skill_store`
  - `project_memory`
  - `nl_scorer`
- Other subsystems:
  - `autofix_engine`
  - `grader_version_store`
  - `human_feedback_store`
  - `drift_monitor`
  - `context_analyzer`
  - `opportunity_queue`
  - `experiment_store`
  - `notification_manager`

Current reality:

- This is a monolithic composition root. It is easy to find service wiring in one file, but route/service ownership boundaries are enforced mostly by convention and tests.

## Product Spine Data Flow

### Build To Config

```text
Prompt/transcript/chat
        |
        v
Build / Builder Chat / Workbench services
        |
        v
Generated config + starter evals + build artifact
        |
        v
ConfigVersionManager saves candidate/active version
```

Main modules:

- `web/src/pages/Build.tsx`
- `web/src/pages/AgentWorkbench.tsx`
- `builder/chat_service.py`
- `builder/workbench.py`
- `builder/workspace_config.py`
- `api/routes/builder.py`
- `api/routes/workbench.py`
- `api/routes/agents.py`
- `runner.py` build group

Boundary:

- Build artifacts are product evidence and handoff material.
- Config versioning is owned by `deployer/versioning.py`, not by the builder itself.

### Workbench To Eval

```text
Workbench canonical project
        |
        | bridge/eval
        v
Materialized AgentLab config
        |
        v
Eval request template returned to UI
        |
        v
User/operator starts Eval
```

Main modules:

- `builder/workbench.py`
- `builder/workbench_bridge.py`
- `api/routes/workbench.py`
- `tests/test_workbench_eval_optimize_bridge.py`

Boundary:

- The bridge materializes a config and returns typed request payloads.
- It intentionally does not start Eval, Optimize, or AutoFix.
- Optimize is not considered ready until completed eval evidence exists.

### Eval To Results

```text
Config + cases/dataset/generated suite
        |
        v
EvalRunner
        |
        | legacy aggregate
        v
CompositeScore
        |
        | structured examples
        v
EvalResultSet / EvalResultsStore
```

Main modules:

- `evals/runner.py`
- `evals/scorer.py`
- `evals/results_model.py`
- `evals/results_store.py`
- `evals/history.py`
- `evals/auto_generator.py`
- `api/routes/eval.py`
- `api/routes/results.py`

Boundary:

- `CompositeScore` remains important for optimizer gates.
- Structured results power Results Explorer, annotations, exports, diffs, and scoped optimize context.
- Eval task state and durable result/history state are distinct.

### Results To Compare

```text
Structured result runs or config pair
        |
        v
PairwiseEvalEngine / Results diff
        |
        v
Comparison store + UI/CLI report
```

Main modules:

- `evals/pairwise.py`
- `api/routes/compare.py`
- `api/routes/results.py`
- `runner.py` eval compare/results diff commands

Boundary:

- Pairwise comparison has its own store and domain models.
- Results diff works over structured result examples.

### Evidence To Optimize

```text
Observer failures OR completed eval run
        |
        v
Optimizer.optimize()
        |
        v
Candidate config + attempt record + diagnostics
        |
        v
Pending review OR direct deploy depending on policy/request
```

Main modules:

- `observer/classifier.py`
- `observer/metrics.py`
- `optimizer/loop.py`
- `optimizer/proposer.py`
- `optimizer/gates.py`
- `optimizer/memory.py`
- `api/routes/optimize.py`
- `runner.py` optimize group

Boundary:

- The optimizer produces evidence-backed candidates and memory records.
- It is not intrinsically the deployment owner.
- API/UI review policy decides whether to create a pending review or deploy.

### Optimize To Review

```text
Candidate config / change card
        |
        v
PendingReviewStore or ChangeCardStore
        |
        v
Unified review API
        |
        v
Improvements UI or CLI review
```

Main modules:

- `optimizer/pending_reviews.py`
- `optimizer/change_card.py`
- `api/routes/reviews.py`
- `api/routes/changes.py`
- `web/src/pages/Improvements.tsx`
- `runner.py` review group

Boundary:

- Unified review normalizes different underlying stores.
- Approval dispatches back to the correct source type.
- Optimizer pending-review approval may deploy a proposed config; change-card approval may only mark the card applied depending on source.

### Review To Deploy

```text
Approved candidate
        |
        v
ConfigVersionManager
        |
        | immediate
        v
Active config

        | canary
        v
Canary config -> canary verdict -> promote or rollback
```

Main modules:

- `deployer/versioning.py`
- `deployer/canary.py`
- `deployer/release_manager.py`
- `deployer/release_objects.py`
- `api/routes/deploy.py`
- `web/src/pages/Deploy.tsx`
- `runner.py` deploy group

Boundary:

- `ConfigVersionManager` owns versions and active/canary manifest state.
- `CanaryManager` owns canary routing/verdict logic.
- Richer release objects are available for governance-heavy staged releases but are not the only deploy path.

## Observability And Event Flow

### Conversation/Trace Flow

```text
Agent run or imported trace
        |
        v
ConversationStore / TraceStore
        |
        v
Observer metrics + failure classification
        |
        v
Opportunities, health reports, optimize evidence
```

Main modules:

- `logger/store.py`
- `observer/classifier.py`
- `observer/metrics.py`
- `observer/traces.py`
- `observer/opportunities.py`
- `api/routes/conversations.py`
- `api/routes/traces.py`
- `api/routes/opportunities.py`

Boundary:

- Conversation records are business/eval evidence.
- Trace records are operational execution evidence.
- Opportunities are derived optimization leads.

### Background Task Flow

```text
API starts eval/optimize/loop task
        |
        v
TaskManager thread
        |
        | updates status/progress/result
        v
tasks.db + /api/tasks/{task_id}
        |
        v
web polling + websocket broadcast
```

Main modules:

- `api/tasks.py`
- `api/server.py`
- `api/websocket.py`
- `api/routes/eval.py`
- `api/routes/optimize.py`
- `api/routes/loop.py`

Boundary:

- Task state is not the same as durable domain result state.
- On restart, previously pending/running tasks are marked `interrupted`.

### Event Timeline Flow

```text
Domain event / task broadcast / builder lifecycle event
        |
        v
EventLog and/or Builder DurableEventStore
        |
        v
/api/events and /api/events/unified
        |
        v
Events UI and operator timeline
```

Main modules:

- `data/event_log.py`
- `builder/events.py`
- `api/routes/events.py`
- `tests/test_event_unification.py`

Boundary:

- Not every builder event is copied into system events.
- Lifecycle builder events are bridged into the system event log.
- Unified timeline suppresses duplicates for bridged lifecycle events.

## CLI/API/UI Boundary

### Shared Concepts

The surfaces share these concepts:

- Workspace root.
- Active/canary config versions.
- Eval cases and result runs.
- Optimization attempts.
- Pending reviews/change cards.
- Conversations, traces, events.
- Mode/provider/model settings.

### Different Execution Models

The surfaces execute differently:

- Web UI: API client with HTTP, SSE, websocket, React Query, and local UI state.
- API: service graph in `app.state`, background tasks, route-level orchestration.
- CLI: direct local service composition in `runner.py` and `cli/*`.
- MCP: JSON-RPC server with tools/resources/prompts, direct local store construction.

Implication:

- Agreement comes mostly from shared file/store formats and tests.
- Behavior can diverge when a surface uses a different path, env var, or legacy store path.

## Integration Boundaries

### Connect

```text
External source
        |
        v
AgentAdapter -> ImportedAgentSpec
        |
        v
create_connected_workspace()
        |
        v
AgentLab config + evals + adapter metadata + traces
```

Main modules:

- `adapters/base.py`
- `adapters/workspace_builder.py`
- `adapters/openai_agents.py`
- `adapters/anthropic_claude.py`
- `adapters/http_webhook.py`
- `adapters/transcript.py`
- `api/routes/connect.py`

Boundary:

- External-specific parsing ends at `ImportedAgentSpec`.
- Workspace materialization writes AgentLab-native files.

### ADK

```text
ADK source tree
        |
        v
AdkImporter / AdkMapper
        |
        v
AgentLab config
        |
        | export/diff/deploy
        v
ADK source patches or Cloud Run/Vertex AI deploy
```

Main modules:

- `adk/types.py`
- `adk/importer.py`
- `adk/exporter.py`
- `adk/deployer.py`
- `api/routes/adk.py`

Boundary:

- ADK types remain platform-specific.
- AgentLab config is the local optimization/eval format.
- Deploy requires external `gcloud` environment.

### CX Studio

```text
Dialogflow CX / Agent Studio snapshot
        |
        v
CxImporter
        |
        v
AgentLab workspace artifacts
        |
        | export/diff/sync/preflight/deploy
        v
CX snapshot/environment/widget/status
```

Main modules:

- `cx_studio/types.py`
- `cx_studio/importer.py`
- `cx_studio/exporter.py`
- `cx_studio/deployer.py`
- `cx_studio/compat.py`
- `api/routes/cx_studio.py`

Boundary:

- CX domain models are separate from AgentLab runtime config.
- Export classifies changes as safe/lossy/blocked and checks conflicts.
- File-touching preview/apply routes include containment checks.

## Data And Governance Boundaries

### Datasets

- `data/dataset_store.py` owns SQLite persistence.
- `data/dataset_service.py` owns service-level create/list/get/import/version/split/export behavior.
- Eval runner can load direct JSONL/CSV data or use dataset-backed cases depending on route/command.

Boundary:

- Datasets are reusable eval inputs and should not be conflated with one-off eval result examples.

### Judges, Scorers, Rewards, Preferences

- `evals/nl_scorer.py` supports natural-language scorer specs.
- `judges/*` and `graders/*` represent grading/judge concepts.
- `rewards/*` and `policy_opt/*` represent reward definitions, preference data, and policy candidate workflows.

Boundary:

- These are governance/evaluation layers around the core agent loop. They feed quality decisions but are not the same as config versioning.

### Registry And Skills

- `registry/store.py` is a generic versioned catalog.
- `core/skills/*` is the core runtime skill subsystem.
- `agent_skills/*` handles generated agent skills from skill gaps.

Boundary:

- Registry items can include skills, policies, tool contracts, handoff schemas, and runbooks.
- Generated agent skills are a workflow layered over the core skills store.

## Security And Safety-Relevant Boundaries

Important implemented safeguards:

- Workspace/path containment checks in higher-risk routes such as CX preview and agent skill apply.
- Live mode readiness checks for provider credentials.
- Gate checks in optimizer before candidate acceptance.
- Review/pending approval as default human-control path.
- Permission checks in some CLI review apply flows.
- Task exceptions captured into failed task state.

Important current limitations:

- Auth/RBAC/multi-tenant/billing/metering/audit/secrets/SLA service modules exist, but the main FastAPI app does not appear to enforce request auth or tenant isolation as middleware in this checkout.
- CLI and MCP direct-store operation means filesystem access and environment correctness remain important trust boundaries.

## Current Implementation Tensions

### Documentation Vs Route Reality

- Some docs describe Connect as a first-run route. Current navigation treats it as a real pro/integration route, not simple mode.
- Some docs omit Workbench. Current code has Workbench as a first-class simple-mode route and API subsystem.
- Review terminology has shifted. UI product surface is `Improvements`, while CLI still uses `review` and compatibility `changes`.

### Transitional Storage Models

- Eval: `EvalHistoryStore` plus `EvalResultsStore`.
- Review: pending optimizer reviews plus change cards.
- Deploy: manifest/canary flow plus richer release objects.
- Builder: SQLite builder workspace plus JSON Workbench harness plus chat session DB.

### Process Boundaries

- API background tasks are thread-based and process-local, with persisted status.
- Loop state is partly module-global, not solely database-owned.
- MCP and CLI bypass API and can diverge if launched with different env/workspace paths.

### Possible Code Tension

- `mcp_server/tools.py` appears to call `ConfigVersionManager.load_version(...)`, but `deployer/versioning.py` in this checkout does not define `load_version`. This should be verified with targeted tests if MCP diff behavior matters.

## Subsystem Boundary Checklist

- Build owns generation and artifacts, not rollout state.
- Workbench owns canonical iterative build state, not formal eval execution.
- Eval owns measurement, result examples, history, and comparisons.
- Optimizer owns candidate generation and gate evaluation, not final human approval policy.
- Review owns approval/rejection workflows over multiple proposal sources.
- Deploy owns active/canary config state and rollback.
- Observer owns runtime evidence and failure classification.
- Data/judges/rewards own evaluation inputs and governance criteria.
- Registry/skills own reusable operational assets.
- Connect/ADK/CX own platform-specific conversion and external deployment handoffs.
- CLI/API/Web/MCP are separate execution surfaces sharing local workspace contracts.
