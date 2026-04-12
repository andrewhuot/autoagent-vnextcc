# AgentLab Features By UI, CLI, Platform, And Integrations - Codex Notes

## Scope

This document groups the repo's major product features by surface area. It is not a route dump; it is a feature map of what the product does in the web UI, CLI, shared platform, and integration layers.

## Product Feature Summary

AgentLab provides a local-first platform for developing and operating AI agents:

- Create a workspace.
- Build or import an agent.
- Run evals from cases, generated suites, or datasets.
- Inspect structured examples and failure evidence.
- Compare runs or configs.
- Generate optimization candidates.
- Review proposed changes.
- Deploy active/canary versions.
- Observe conversations, traces, health, events, and continuous loops.
- Manage datasets, judges, scorers, skills, registry items, and integration round trips.

## Web UI Features

### App Shell And Navigation

Evidence: `web/src/App.tsx`, `web/src/lib/navigation.ts`, `web/src/components/Layout.tsx`, `web/src/components/Sidebar.tsx`.

Features:

- React SPA with explicit routes.
- `/` redirects to `/build`.
- Simple/pro sidebar modes.
- Simple-mode path set:
  - `/dashboard`
  - `/setup`
  - `/build`
  - `/workbench`
  - `/evals`
  - `/results`
  - `/compare`
  - `/studio`
  - `/optimize`
  - `/improvements`
  - `/deploy`
  - `/docs`
- Pro routes for integrations, governance, observability, registry, rewards, policy, and labs.
- Legacy route redirects into current product surfaces.
- Global websocket connection for updates.
- Mock/live mode banner.
- Keyboard shortcuts and operator journey affordances.
- Review count badges in navigation via unified review stats.

Implementation reality:

- `Workbench` and `Studio` are current simple-mode pages.
- `Connect` is a real route but not simple-mode navigation in the current code.

### Setup And Dashboard

Evidence: `web/src/pages/Setup.tsx`, `web/src/pages/Dashboard.tsx`, `api/routes/setup.py`, `api/routes/health.py`.

Features:

- Workspace readiness overview.
- Provider/API key status.
- Mock/live/auto mode visibility.
- Data-store presence.
- MCP client status.
- Recommended CLI commands.
- Health/scorecard/system/cost checks.

### Build

Evidence: `web/src/pages/Build.tsx`, `api/routes/builder.py`, `api/routes/intelligence.py`, `api/routes/agents.py`.

Features:

- Prompt-to-agent generation.
- Transcript intelligence/import flow.
- Conversational Builder Chat.
- Saved build artifacts.
- Preview and save generated configs.
- Save-and-run-eval handoff.
- Agent Library integration.
- XML/root instruction editing through the Build surface.

State/handoff:

- Generated configs.
- Generated eval cases.
- Build artifacts.
- Builder chat sessions.
- Agent Library entries.

### Workbench

Evidence: `web/src/pages/AgentWorkbench.tsx`, `builder/workbench.py`, `api/routes/workbench.py`.

Features:

- Two-pane iterative agent build harness.
- Streaming build runs via server-sent events.
- Streaming iteration runs.
- Canonical model mutation before generated exports.
- Plan snapshots, artifacts, activity, validation, compatibility output.
- Cancel active runs.
- Roll back changes.
- Bridge materialized candidate into Eval.

State/handoff:

- `.agentlab/workbench_projects.json`.
- Materialized configs through `persist_generated_config`.
- Eval request templates and optimize request templates returned by bridge endpoint.

### Eval Runs

Evidence: `web/src/pages/EvalRuns.tsx`, `api/routes/eval.py`, `evals/runner.py`.

Features:

- Select active agent/config.
- Start evals against cases, generated suites, or datasets.
- View task continuity state.
- React to websocket completion events.
- Inspect per-run details.
- Navigate to Results Explorer and Optimize.
- Generated suite and curriculum-related workflows.

### Results Explorer

Evidence: results pages/components, `api/routes/results.py`, `evals/results_store.py`.

Features:

- List structured eval runs.
- Inspect run summary.
- Browse examples.
- Filter failures.
- Inspect score dimensions and grader scores.
- Annotate examples.
- Export JSON/CSV/Markdown.
- Diff result runs.

Implementation reality:

- Results Explorer is backed by structured result storage, not only latest eval JSON files.

### Compare

Evidence: compare page/hooks, `api/routes/compare.py`, `evals/pairwise.py`.

Features:

- Pairwise eval comparison.
- Stored comparison results.
- Compare list/detail views.
- Run-to-run or config-to-config decision support.

### Optimize

Evidence: `web/src/pages/Optimize.tsx`, `api/routes/optimize.py`, `optimizer/loop.py`.

Features:

- Standard/advanced/research modes.
- Run and Live tabs.
- Start optimization from observer evidence or an eval run.
- Workbench-origin guardrails requiring eval evidence.
- Show task status and optimization result.
- View pending optimizer reviews.
- Approve/reject pending proposals.
- Pareto/research surface support.

### Improvements

Evidence: `web/src/pages/Improvements.tsx`, `api/routes/reviews.py`, `api/routes/changes.py`, `api/routes/opportunities.py`, `api/routes/experiments.py`.

Features:

- Opportunity queue.
- Experiment history/archive.
- Unified review queue.
- Review stats.
- Optimization history.
- Approve/reject items.
- Legacy review/change/opportunity routes redirected into this surface.

### Deploy

Evidence: `web/src/pages/Deploy.tsx`, `api/routes/deploy.py`, `deployer/versioning.py`, `deployer/canary.py`.

Features:

- Active version display.
- Canary version display.
- Version history.
- Deploy candidate as canary.
- Immediate deploy/promotion.
- Promote canary.
- Roll back canary.
- Canary verdict/status.

### Observability And Operations

Evidence: pages for conversations, traces, events, loop, context, what-if, impact, diagnose, health APIs.

Features:

- Conversation browsing/statistics.
- Trace search, error views, session traces, blame map.
- Unified event timeline.
- Loop monitor and control.
- Context analysis and simulation.
- What-if replay/project jobs.
- Impact dependency/report analysis.
- Diagnosis and knowledge-mining workflows.

### Governance, Data, Skills, And Rewards

Evidence: routes/pages for judge ops, scorer studio, datasets, registry, skills, memory, reward studio, preference inbox, policy candidates, reward audit.

Features:

- Dataset management and import/export.
- Outcome import/calibration.
- Judge feedback, drift, and calibration.
- Natural-language scorer specs.
- Registry search/import/create/diff.
- Core skills and generated agent skills.
- Project memory and runbooks.
- Reward definitions, hard gates, reward audits, preference review, and policy candidates.

### Integration UI

Evidence: routes for Connect, CX, ADK, Sandbox, Knowledge, CLI launcher.

Features:

- Import from OpenAI Agents SDK, Anthropic/Claude projects, HTTP webhooks, and transcripts.
- Dialogflow CX / Agent Studio import, studio, deploy, widget/status, preview/preflight flows.
- ADK import and deploy.
- Sandbox generation/test/compare.
- Knowledge pattern mining/apply/review.
- CLI launcher/docs pages.

## CLI Features

### CLI Entry And UX

Evidence: `runner.py`, `cli/output.py`, `cli/json_envelope.py`, `cli/progress.py`, `shared/taxonomy.py`.

Features:

- Click-based `agentlab` command.
- Interactive shell or onboarding when run without a command in TTY.
- Non-interactive default routes to `agentlab status`.
- Default help groups primary and secondary commands.
- Hidden advanced commands remain available.
- Text, JSON, and stream-JSON output patterns.
- Standard JSON envelope with `api_version`, `status`, `data`, and `next`.
- Progress events for automation.

### Workspace And Setup Commands

Commands:

- `agentlab new`
- `agentlab init` hidden legacy command.
- `agentlab status`
- `agentlab doctor`
- `agentlab shell`
- `agentlab continue`
- `agentlab session list/resume/delete`
- `agentlab template list/apply`

Features:

- Create starter workspace.
- Seed demo data.
- Detect active config and workspace metadata.
- Diagnose and repair workspace issues.
- Resume sessions.

### Mode, Provider, And Model Commands

Commands:

- `agentlab mode show`
- `agentlab mode set`
- `agentlab provider configure`
- `agentlab provider list`
- `agentlab provider test`
- `agentlab model list`
- `agentlab model show`
- `agentlab model set proposer`
- `agentlab model set evaluator`

Features:

- Mock/live/auto runtime posture.
- Provider registry and API-key environment variables.
- Proposer/evaluator model overrides.
- Workspace settings persistence.

### Build Commands

Commands:

- `agentlab build "prompt"`
- `agentlab build show latest`
- `agentlab build-show` hidden compatibility alias.

Features:

- Natural-language build artifact generation.
- Config and eval case generation.
- Build artifact persistence.
- Config version registration when inside a workspace.

### Connect Commands

Commands:

- `agentlab connect openai-agents`
- `agentlab connect anthropic`
- `agentlab connect http`
- `agentlab connect transcript`

Features:

- External project/endpoint/transcript import.
- Connected workspace materialization.
- Adapter spec/config creation.
- Starter eval creation.

### Eval Commands

Commands:

- `agentlab eval run`
- `agentlab eval show`
- `agentlab eval list`
- `agentlab eval generate`
- `agentlab eval breakdown`
- `agentlab eval results`
- `agentlab eval results annotate`
- `agentlab eval results export`
- `agentlab eval results diff`
- `agentlab eval compare`

Features:

- Workspace active-config eval defaults.
- Suite/category/dataset/split selection.
- Live/real-agent mode checks.
- Instruction override support.
- Latest result handoff file.
- Structured result export/diff/annotation.
- Pairwise comparison.

### Optimize And Loop Commands

Commands:

- `agentlab optimize`
- `agentlab optimize --cycles N`
- `agentlab optimize --continuous`
- `agentlab optimize --mode standard|advanced|research`
- `agentlab optimize --full-auto`
- Hidden compatibility: `agentlab improve`
- Hidden long-running path: `agentlab loop`
- Control aliases: `agentlab pause`, `agentlab resume`, `agentlab reject`, `agentlab pin`, `agentlab unpin`

Features:

- Failure-driven optimization cycles.
- Budget/cost tracking.
- Human-pause gates.
- Continuous loop with checkpoint/resume, watchdog, resource monitor, DLQ, and graceful shutdown.
- Reviewable candidate creation without automatically changing deploy state by default.

### Review Commands

Commands:

- `agentlab review`
- `agentlab review list`
- `agentlab review show`
- `agentlab review apply`
- `agentlab review reject`
- `agentlab review export`
- Compatibility: `agentlab changes`

Features:

- Interactive approval prompt.
- Pending/latest selectors.
- Permission checks before applying changes.
- Change card review and export.

### Deploy Commands

Commands:

- `agentlab deploy canary`
- `agentlab deploy immediate`
- `agentlab deploy release`
- `agentlab deploy rollback`
- `agentlab deploy status`

Features:

- Config manifest active/canary control.
- Candidate version selection.
- Prevent deploying the active version as its own canary.
- Auto-review option.
- CX Studio target packaging/push.

### Integration And Advanced Commands

Command groups:

- `agentlab server`
- `agentlab mcp-server`
- `agentlab mcp ...`
- `agentlab cx ...`
- `agentlab adk ...`
- `agentlab registry ...`
- `agentlab runbook ...`
- `agentlab trace ...`
- `agentlab scorer ...`
- `agentlab dataset ...`
- `agentlab release ...`
- `agentlab quickstart`
- `agentlab demo`

Features:

- Start FastAPI server.
- Start MCP server over stdio/HTTP.
- Configure MCP clients.
- Manage workspace MCP runtime entries.
- Import/export/deploy ADK and CX agents.
- Manage registries/runbooks/scorers/datasets/releases.

## Shared Platform Features

### Workspace State

Evidence: `cli/workspace.py`, `api/workspace_state.py`.

Features:

- Upward workspace discovery via `.agentlab`.
- Active config resolution.
- Workspace metadata.
- Runtime paths for configs, evals, stores, MCP, project memory, and local settings.
- API-visible workspace validity.

### Runtime Modes And Provider Posture

Evidence: `cli/mode.py`, `cli/providers.py`, `cli/model.py`, `api/routes/settings.py`.

Features:

- Mock/live/auto modes.
- Provider key detection.
- Workspace provider registry.
- Model override persistence.
- Live-mode readiness checks.

### Service Composition

Evidence: `api/server.py`.

Features:

- FastAPI lifespan creates a service graph containing conversation store, version manager, observer, trace store, event log, eval runner, results store, pairwise store, generated eval store, optimizer, deployer, task manager, websocket manager, builder services, Workbench store, transcript intelligence, build artifact store, registry, skills, runbooks, memory, datasets, notifications, and more.
- Route handlers use `request.app.state` rather than constructing services repeatedly.

### Background Task Continuity

Evidence: `api/tasks.py`, `/api/tasks` routes, `tests/test_p0_journey_fixes.py`.

Features:

- Persist background task records to SQLite.
- Reload latest tasks on startup.
- Mark pending/running tasks as interrupted.
- Provide user-facing continuity metadata.
- Poll task state from UI.

### Realtime And Events

Evidence: `api/websocket.py`, `data/event_log.py`, `builder/events.py`, `api/routes/events.py`.

Features:

- `/ws` websocket with ping/pong and broadcast support.
- Eval/optimize/loop completion broadcasts.
- Append-only event log.
- Builder durable event history.
- Unified event timeline that merges system and builder lifecycle events.

### Eval Platform

Evidence: `evals/*`, `api/routes/eval.py`, `api/routes/results.py`, `api/routes/compare.py`.

Features:

- YAML eval cases.
- JSONL/CSV dataset-backed evals.
- Generated suites.
- Legacy scoring for gates.
- Structured results for browsing/annotations/diffs.
- Pairwise comparison.
- Caching/fingerprinting and history persistence.

### Optimization Platform

Evidence: `optimizer/*`, `api/routes/optimize.py`.

Features:

- Failure-family classification and proposal mapping.
- Simple/pro/hybrid optimization strategies.
- Gate evaluation for safety/regression/improvement.
- Statistical/significance fields.
- Anti-Goodhart and Pareto/research support.
- Optimization memory.
- Pending human review.

### Deployment Platform

Evidence: `deployer/*`.

Features:

- Versioned config YAML files.
- Config manifest with active/canary pointers.
- Canary traffic splitting and verdicts.
- Promotion and rollback.
- Release objects with lineage, approvals, risk, rollback instructions, and business outcomes.
- Staged release manager for governance-heavy flows.

### Data And Governance Platform

Evidence: `data/*`, `judges/*`, `graders/*`, `rewards/*`, `policy_opt/*`.

Features:

- Dataset rows and immutable versions.
- Import from traces/eval cases/CSV.
- Split generation and metrics.
- Outcome capture.
- Judge calibration/drift.
- NL scorers.
- Reward definitions, audits, hard gates.
- Preference inbox and policy candidates.

### Registry And Skills Platform

Evidence: `registry/*`, `core/skills/*`, `agent_skills/*`.

Features:

- Generic versioned registry for skills, policies, tool contracts, handoff schemas, and runbooks.
- Core skill storage/execution layer.
- Generated skill gap analysis.
- Skill generation from templates.
- Approval/rejection/apply workflows.
- Project memory and runbook support.

## Integration Features

### Connect Adapters

Evidence: `adapters/*`, `api/routes/connect.py`, CLI connect group.

Supported sources:

- OpenAI Agents SDK projects.
- Anthropic/Claude projects.
- Generic HTTP webhooks.
- Transcript JSONL exports.

Features:

- Normalize imported agent specs.
- Infer prompts/tools/guardrails/handoffs/MCP refs/session patterns/traces.
- Materialize workspaces.
- Write config versions, manifests, starter evals, traces, and adapter metadata.

### ADK

Evidence: `adk/*`, `api/routes/adk.py`, CLI `agentlab adk`.

Features:

- Parse ADK source directories.
- Map ADK agent tree to AgentLab config.
- Write imported config and portability report.
- Export AgentLab config back into ADK source patches.
- Diff ADK source/config changes.
- Deploy to Cloud Run or Vertex AI through `gcloud`.
- Status reporting.

### Dialogflow CX / Agent Studio

Evidence: `cx_studio/*`, `api/routes/cx_studio.py`, CLI `agentlab cx`.

Features:

- Auth and list agents.
- Import CX snapshots into AgentLab workspaces.
- Map AgentLab config back to CX snapshots.
- Diff/export/sync with safe/lossy/blocked classifications.
- Preflight validation.
- Deploy to CX environments.
- Canary/promote/rollback.
- Widget generation and status.
- Compatibility matrix across ADK and CX capabilities.

### MCP

Evidence: `mcp_server/*`, `cli/mcp_setup.py`, `cli/mcp_runtime.py`.

Features:

- JSON-RPC 2.0 MCP server.
- Stdio and HTTP transports.
- Tools for status, diagnose, failures, suggest fix, edit, eval, compare, skill gaps, skill recommendation, replay, diff, scaffold, generate evals, sandbox runs, trace inspection, ADK source sync, and PR opening.
- Read-only resources for configs/traces/evals/skills/datasets.
- Prompt templates for common AgentLab tasks.
- MCP client config setup for Claude Code, Codex, Cursor, and Windsurf.

### Notifications, Collaboration, CICD, A2A, Sandbox

Evidence: `notifications/*`, `collaboration/*`, `cicd/*`, `a2a/*`, `api/routes/notifications.py`, `api/routes/collaboration.py`, `api/routes/cicd.py`, `api/routes/a2a.py`, `api/routes/sandbox.py`.

Features:

- Webhook/Slack/email notifications.
- Review request and submit flows.
- CI/CD support routes.
- Agent-to-agent related APIs.
- Synthetic sandbox conversations, tests, comparisons, and result retrieval.

## Implementation Boundaries To Remember

- UI, CLI, API, and MCP are separate surfaces over shared local state.
- CLI and MCP instantiate many core services directly; they are not thin HTTP clients.
- API route handlers depend heavily on `app.state`.
- Eval has both legacy and structured result models.
- Review aggregates multiple underlying proposal stores.
- Deploy has practical manifest/canary state plus richer release-governance models.
- Platform auth/RBAC/billing/metering modules exist, but the main FastAPI app does not currently enforce them as middleware.
- Connect/CX/ADK keep external platform models separate and convert at explicit import/export handoff points.
