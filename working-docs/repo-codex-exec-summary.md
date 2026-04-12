# AgentLab Executive Summary - Codex Notes

## What This Repo Does

AgentLab is a local-first platform for building, evaluating, improving, reviewing, and deploying AI agent configurations. It gives operators multiple surfaces over the same workspace state:

- A React web console for day-to-day operator workflows.
- A Click-based `agentlab` CLI for setup, automation, and local workflows.
- A FastAPI backend for UI/API access, background tasks, websocket updates, and local service orchestration.
- An MCP server so external AI clients can inspect and operate AgentLab workspaces.
- Integration layers for importing/exporting agents from OpenAI Agents SDK projects, Anthropic/Claude projects, HTTP webhooks, transcripts, Google ADK, and Dialogflow CX / Agent Studio.

The central product loop is:

`BUILD -> WORKBENCH -> EVAL -> RESULTS/COMPARE -> OPTIMIZE -> REVIEW -> DEPLOY`

In practice, an operator can create or import an agent, generate or refine config, run evals, inspect structured results and failures, compare candidates, generate improvement proposals, approve or reject proposed changes, deploy a canary or active version, and observe behavior over time.

## Major Product Areas

### Build And Workbench

The Build surface turns prompts, transcripts, and builder-chat conversations into AgentLab configs, eval cases, and build artifacts. The Workbench is a more structured iterative harness: it keeps canonical project state, streams build and iteration runs, validates outputs, and bridges materialized candidates into Eval. Workbench is a real current route and API subsystem, not just a future concept.

Key implementation areas:

- `web/src/pages/Build.tsx`
- `web/src/pages/AgentWorkbench.tsx`
- `builder/chat_service.py`
- `builder/workbench.py`
- `builder/workspace_config.py`
- `api/routes/builder.py`
- `api/routes/workbench.py`
- `runner.py` build commands

### Eval, Results, And Compare

Eval runs configs against YAML cases, generated suites, or JSONL/CSV datasets. Results are stored in two layers: legacy composite scoring/history for optimizer gates and structured result examples for Results Explorer, annotations, exports, diffs, and scoped optimization. Compare provides pairwise comparison and run/result diff workflows.

Key implementation areas:

- `evals/runner.py`
- `evals/scorer.py`
- `evals/results_model.py`
- `evals/results_store.py`
- `evals/history.py`
- `evals/pairwise.py`
- `evals/auto_generator.py`
- `api/routes/eval.py`
- `api/routes/results.py`
- `api/routes/compare.py`
- `api/routes/generated_evals.py`
- `runner.py` eval commands

### Optimize And Review

The optimizer uses observer failures or completed eval evidence to propose config improvements. It applies safety/regression/improvement gates, records attempts in optimization memory, and normally hands candidates to human review rather than directly deploying them. The current web review surface is `Improvements`, which aggregates opportunities, experiments, optimizer pending reviews, change cards, and history.

Key implementation areas:

- `optimizer/loop.py`
- `optimizer/proposer.py`
- `optimizer/gates.py`
- `optimizer/memory.py`
- `optimizer/pending_reviews.py`
- `optimizer/change_card.py`
- `api/routes/optimize.py`
- `api/routes/reviews.py`
- `api/routes/changes.py`
- `web/src/pages/Optimize.tsx`
- `web/src/pages/Improvements.tsx`
- `runner.py` optimize/review commands

### Deploy And Versioning

Deployment is config-version based. `ConfigVersionManager` writes versioned YAML files and `configs/manifest.json`; `CanaryManager` handles canary routing, verdicts, promotion, and rollback. The UI and CLI support canary, immediate deploy, promote, rollback, and deploy status. Richer release objects and staged release governance exist, but the practical current deploy path is the manifest/canary model.

Key implementation areas:

- `deployer/versioning.py`
- `deployer/canary.py`
- `deployer/release_manager.py`
- `deployer/release_objects.py`
- `api/routes/deploy.py`
- `web/src/pages/Deploy.tsx`
- `runner.py` deploy commands

### Observe, Govern, And Operate

AgentLab captures conversations, traces, events, health metrics, failure buckets, optimization opportunities, task status, loop state, and background-task continuity. This evidence powers diagnosis, optimization, and operator trust. Additional governance features manage datasets, outcomes, judges, scorers, rewards, preferences, policy candidates, registries, runbooks, project memory, and generated skills.

Key implementation areas:

- `logger/store.py`
- `observer/classifier.py`
- `observer/metrics.py`
- `observer/traces.py`
- `observer/opportunities.py`
- `data/event_log.py`
- `api/tasks.py`
- `api/websocket.py`
- `api/routes/events.py`
- `api/routes/loop.py`
- `data/dataset_store.py`
- `data/dataset_service.py`
- `registry/store.py`
- `agent_skills/*`
- `core/skills/*`
- `rewards/*`
- `policy_opt/*`

### Integrations And Automation

AgentLab can import existing agents, round-trip certain external platform formats, and expose operations through MCP. The integration layer keeps platform-specific models separate from AgentLab config, then uses explicit import/export/deploy handoffs.

Key implementation areas:

- `adapters/*`
- `adk/*`
- `cx_studio/*`
- `mcp_server/*`
- `api/routes/connect.py`
- `api/routes/adk.py`
- `api/routes/cx_studio.py`
- `runner.py` connect/adk/cx/mcp commands

## Main User Journeys

1. Create a workspace with `agentlab new` or inspect readiness in `/setup`.
2. Build an agent from a prompt/transcript/chat in `/build` or `agentlab build`.
3. Iterate in `/workbench`, then materialize a candidate for Eval.
4. Import an existing agent through Connect, ADK, CX, HTTP, or transcript flows.
5. Run evals in `/evals` or `agentlab eval run`.
6. Inspect structured examples in `/results` or `agentlab eval results`.
7. Compare runs or candidates in `/compare` or `agentlab eval compare`.
8. Optimize from eval/observer evidence in `/optimize` or `agentlab optimize`.
9. Approve or reject proposed changes in `/improvements` or `agentlab review`.
10. Deploy canary/active versions in `/deploy` or `agentlab deploy`.
11. Observe conversations, traces, events, loop state, health, and failures.
12. Manage datasets, judges, scorers, rewards, preferences, skills, registries, and runbooks for deeper governance.

## System Fit

The repo is organized around shared local workspace contracts rather than a single central service API:

- Web UI calls FastAPI.
- FastAPI composes service singletons in `api/server.py`.
- CLI directly constructs many of the same stores and engines.
- MCP directly constructs stores and tools from workspace/environment paths.
- Integrations write AgentLab-native configs, evals, manifests, snapshots, and metadata.

This design makes local development and automation powerful, but it also means path conventions and store schemas are critical. Tests are the best evidence for cross-surface alignment.

## Important Implementation Boundaries

- Build generates artifacts/configs; deploy/versioning owns rollout state.
- Workbench owns iterative canonical build state; Eval owns formal measurement.
- Eval has a legacy scoring layer for gates and a structured result layer for explorer/diff/annotation.
- Optimizer proposes and gates candidates; review/deploy decide what becomes active.
- Improvements aggregates multiple review sources but does not collapse their stores.
- Deploy has both current manifest/canary mechanics and richer release-governance models.
- CLI/API/Web/MCP share workspace files but execute through different process paths.
- ADK/CX/Connect use typed external models and explicit conversion handoffs.
- Platform-control modules for auth/RBAC/tenant/billing/metering exist, but the main FastAPI app does not currently enforce them as request middleware in this checkout.

## Current Implementation Reality

The repo is broad and product-rich, but some areas are transitional:

- `runner.py` is still the main CLI orchestration file and is very large.
- `api/server.py` is a wide composition root with many services attached to `app.state`.
- Some product docs lag current code. Workbench and Studio are simple-mode UI routes now; Connect exists but is pro/integration navigation rather than simple mode.
- Eval, review, and deploy each have older and newer models coexisting.
- The product has local/demo/mock-friendly behavior alongside live provider and external-platform integration paths.
- Several governance/platform modules appear to be library infrastructure rather than enforced SaaS controls in the current FastAPI runtime.

## Files Produced In This Note Campaign

- `working-docs/repo-codex-inventory.md`: directory/module responsibility map.
- `working-docs/repo-codex-user-journeys.md`: user and operator journey map.
- `working-docs/repo-codex-features-ui-cli.md`: feature map grouped by UI, CLI, shared platform, and integrations.
- `working-docs/repo-codex-architecture-map.md`: system architecture, boundaries, state, and event flows.
- `working-docs/repo-codex-exec-summary.md`: concise executive summary.

## Notable Follow-Up Checks

- The requested `docs/plans/2026-04-12-cohesive-product-hardening.md` is absent from this checkout. Related item plans exist under `working-docs/`.
- `mcp_server/tools.py` appears to call `ConfigVersionManager.load_version(...)`, but `deployer/versioning.py` in this checkout does not define `load_version`. This note campaign did not change code, but this is worth a targeted MCP diff test or fix.
