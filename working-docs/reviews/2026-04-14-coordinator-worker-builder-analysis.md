# Coordinator-Worker Builder Analysis

Date: 2026-04-14
Branch: `feat/coordinator-worker-builder-codex-yolo`
Workspace: `/Users/andrew/Desktop/agentlab-coordinator-worker-builder-codex-yolo`

## Executive Summary

AgentLab already had the beginnings of a multi-agent builder model: a `BuilderOrchestrator`, a specialist roster, delegated task modes, durable builder tasks, Workbench handoffs, skill context, eval bundles, optimizer skill engines, and deployment/release surfaces. The missing product layer was not another full runtime; it was a coordinator-owned way to plan work across specialized workers, expose worker capabilities, include skill/tool boundaries, and persist the provenance of routing decisions.

This pass implements that safe first layer. The new model keeps existing single-agent Build and Workbench flows intact while adding:

- product-aligned worker roles for build, prompt engineering, optimization, evals, and deployment
- a worker capability registry derived from specialist definitions
- deterministic coordinator-owned task graphs
- per-worker tool, permission, skill-layer, expected-artifact, and provenance metadata
- optional materialization of planned worker nodes into child `BuilderTask` records
- enriched specialist invocation payloads with worker capability and routing provenance
- a new API endpoint, `POST /api/builder/coordinator/plan`, for inspecting or materializing coordinator-worker plans

The implementation is intentionally conservative. It does not create a recursive swarm, background worker mailbox, or autonomous deployment path. Instead, it gives AgentLab a durable planning and routing contract that future live workers, Workbench UI, and CLI surfaces can execute against safely.

## Reference Repo Inspection

Reference source:

- `https://github.com/codeaashu/claude-code`
- local clone: `/tmp/codeaashu-claude-code-reference-coordinator`

Important note: the reference repo identifies itself as an archive of leaked Anthropic source and says the original code is not an official licensed release. I treated it as high-level architecture input only and avoided copying implementation details or large source fragments.

Inspected reference paths:

- `README.md`
- `Skill.md`
- `agent.md`
- `docs/architecture.md`
- `docs/bridge.md`
- `docs/commands.md`
- `docs/exploration-guide.md`
- `docs/subsystems.md`
- `docs/tools.md`
- `src/coordinator/coordinatorMode.ts`
- `src/constants/tools.ts`
- `src/tools/AgentTool/AgentTool.tsx`
- `src/tools/AgentTool/runAgent.ts`
- `src/tools/AgentTool/agentToolUtils.ts`
- `src/tools/AgentTool/loadAgentsDir.ts`
- `src/tools/TeamCreateTool/TeamCreateTool.ts`
- `src/tools/TeamCreateTool/prompt.ts`
- `src/tools/TeamDeleteTool/TeamDeleteTool.ts`
- `src/tools/SendMessageTool/SendMessageTool.ts`
- `src/tasks/types.ts`
- `src/Task.ts`
- `src/tasks/LocalAgentTask/LocalAgentTask.tsx`
- `src/tasks/InProcessTeammateTask/types.ts`
- `src/tasks/InProcessTeammateTask/InProcessTeammateTask.tsx`
- `src/tasks/RemoteAgentTask/RemoteAgentTask.tsx`
- `src/services/AgentSummary/agentSummary.ts`
- `src/tools/SkillTool/SkillTool.ts`
- task/team/progress UI components and permission UI components under `src/components/`

## Reference Patterns Worth Adopting

### Coordinator as Synthesizer

The reference architecture treats the coordinator as more than a router. The coordinator owns the plan, decides when to delegate, converts worker findings into concrete next instructions, and synthesizes results for the user. This is a strong fit for AgentLab because AgentLab's product loop already depends on clear transitions between Build, Eval, Optimize, Review, and Deploy.

AgentLab mapping:

- coordinator owns the task graph and next-step synthesis
- workers operate on bounded tasks
- worker outputs should be structured enough for Eval, Optimize, and Deploy to trust later
- coordinator summaries should become first-class handoff state, not free-form chat residue

### Worker Capability Registry

The reference separates coordinator tools from worker tools and uses capability boundaries for spawned workers. That pattern maps cleanly to AgentLab specialists because AgentLab already has `SpecialistDefinition` objects with tools and permission scopes.

AgentLab mapping:

- build worker: source/config/test implementation
- prompt worker: prompt and XML instruction revisions
- eval worker: eval suites and benchmarks
- optimization worker: eval-driven improvement proposals and skill-engine usage
- deployment worker: canary, rollback, environment, and release-readiness planning
- skills/tool workers: skill manifests, tool contracts, guardrails, integration tests

### Typed Task Lifecycle and Provenance

The reference makes background task state inspectable through stable IDs, statuses, summaries, tool activity, and terminal states. AgentLab already has `BuilderTask`, `ArtifactRef`, `EvalBundle`, `ReleaseCandidate`, task parentage, and task metadata, so the safer path is to use those instead of inventing a second task store.

AgentLab mapping:

- coordinator plan nodes include `task_id`, `worker_role`, `depends_on`, `status`, selected tools, expected artifacts, and provenance
- optional materialization creates child `BuilderTask` records with `parent_task_id`
- each child task records the coordinator plan id and source task id

### Skill and Tool Boundaries

The reference allows workers to invoke skills/tools, but keeps destructive operations behind a permission model. AgentLab already has build-time/runtime skill distinctions in `core/skills`, optimizer-owned skill application in `optimizer/skill_engine.py`, and deploy/review gates elsewhere.

AgentLab mapping:

- coordinator plans expose skill candidates per worker
- build-time skills are surfaced to build, prompt, eval, guardrail, and optimization workers
- runtime skills are surfaced to tool/integration workers
- skill author workers can see both layers
- the coordinator does not directly apply skill mutations in this first slice
- deployment workers plan deployment work but do not bypass deploy/review gates

### UI/CLI Activity Surfaces

The reference has rich surfaces for task and team status. AgentLab already exposes builder tasks, events, metrics, Workbench handoffs, and API routes. The incremental version should expose coordinator-worker activity through API and task metadata first, then layer CLI and UI rendering on top.

## Patterns Not Adopted Now

### Full Async Swarm Runtime

The reference has local, remote, in-process, and teammate task types, plus messaging and shutdown protocols. Bringing that into AgentLab now would add too much concurrency and persistence complexity before there is a stable AgentLab-specific task contract.

### Recursive Worker Spawning

Workers spawning workers is powerful but risky. AgentLab should not add recursive delegation until permission boundaries, worktree ownership, task cancellation, and provenance semantics are fully specified.

### Worker Mailboxes and Team Memory

Inter-worker messaging, scratchpads, and team memory are useful later. They are not needed for the first production-ready landing because AgentLab's immediate gap is deterministic task decomposition and worker routing.

### Deployment Bypass

Deployment workers must not directly promote or ship changes outside AgentLab's existing review/deploy surfaces. This pass keeps deployment as a planned capability with permission scope metadata.

## AgentLab Architecture Inspected

### Builder

Inspected:

- `builder/types.py`
- `builder/specialists.py`
- `builder/orchestrator.py`
- `builder/execution.py`
- `builder/store.py`
- `builder/projects.py`
- `builder/workbench.py`
- `builder/harness.py`
- `builder/workbench_bridge.py`
- `builder/workspace_config.py`
- `BUILDER_CONTRACT.md`

Current strengths:

- `BuilderTask` already supports lifecycle state, parentage, delegated mode, active specialist, artifacts, proposals, approvals, sandbox references, and metadata.
- `BuilderOrchestrator` already routes intent to specialists and records handoffs.
- `BuilderExecutionEngine` already supports delegate mode, worktree metadata, lifecycle transitions, progress events, crash recovery, and evidence clamps.
- `BuilderStore` provides durable SQLite persistence for projects, sessions, tasks, artifacts, proposals, approvals, eval bundles, trace bookmarks, sandbox runs, worktrees, and releases.
- `BUILDER_CONTRACT.md` already defines a builder harness contract with plan, execute, reflect, present, persistence, completion criteria, and skill treatment.

Gaps before this pass:

- no product-aligned build/prompt/optimization/deployment worker roles
- no typed worker capability registry
- no coordinator-owned task graph
- no plan-level skill/tool boundary metadata
- no invocation provenance beyond basic handoff records
- no API route to inspect a coordinator-worker plan

### Workbench

Inspected:

- `builder/workbench.py`
- `builder/harness.py`
- `docs/features/workbench.md`
- Workbench tests around API, streaming, harness engineering, eval/optimize bridge, and CLI workbench surfaces

Current strengths:

- Workbench has durable run envelopes, streamed events, active run hydration, validation, review gates, evidence summaries, run handoffs, stale recovery, and Workbench -> Eval -> Optimize bridge state.
- `HarnessExecutionEngine` already has deterministic plan -> execute -> reflect -> present behavior and skill-context event enrichment.

Decision:

- Do not put the first coordinator-worker runtime inside Workbench streaming. Workbench is already a complex user-facing harness. The safer foundation is in Builder Workspace orchestration, where the task model already exists.

### Evals and Optimizer

Inspected:

- `evals/runner.py`
- eval result models/stores
- `optimizer/skill_engine.py`
- optimizer CLI flow in `runner.py`
- related tests for eval, optimize, and skills

Current strengths:

- Eval is already the evidence owner.
- Optimizer already has skill-aware selection and mutation proposal logic.
- Review and Deploy are separate from Optimize.

Decision:

- The coordinator should route to eval and optimization workers and surface skill candidates, but should not apply optimizer mutations directly.

### Skills

Inspected:

- `core/skills/types.py`
- `core/skills/store.py`
- `agent_skills/*`
- `registry/skill_*`
- skill API/CLI tests

Current strengths:

- Build-time and runtime skills are first-class.
- Skills include capabilities, mutation operators, eval criteria, runtime tool definitions, policies, dependencies, tests, and effectiveness metrics.

Decision:

- Worker plans include `skill_layer` and `skill_candidates`, using project-level build-time/runtime skill lists.
- This keeps the design honest: workers can call appropriate skills/tools later, but this first slice does not pretend to execute them.

## Prioritized Design and Feature List

### P0: Safe Coordinator-Worker Contract

Implemented now.

- product-aligned worker roles
- worker capability registry
- coordinator-owned plan graph
- worker tool and permission boundaries
- skill candidate exposure
- provenance and next-step synthesis
- API route for plan creation

### P1: Worker Activity Surface

Partially enabled now through API payloads and task metadata. Follow-up should add CLI rendering and web UI panels.

Recommended surfaces:

- `agentlab build coordinate ...` or `agentlab workbench coordinate ...`
- Workbench Activity tab section for coordinator plan and worker tasks
- Builder UI roster showing capability, skill layer, and selected tools

### P2: Execution Runtime

Not implemented now. Follow-up should execute materialized worker tasks through bounded adapters.

Candidate execution strategy:

- start with local deterministic workers that call existing AgentLab services
- then add live LLM-backed workers behind explicit mode flags
- use worktree ownership for write-heavy workers
- keep Eval and Deploy as separate gates

### P3: Inter-Worker Messaging and Continuation

Not implemented now. Follow-up should add continuation IDs, worker summaries, and coordinator synthesis loops after the task graph is stable.

### P4: Rich Team Memory

Not implemented now. Follow-up should reuse AgentLab project memory and Workbench handoff state before creating a separate team memory store.

## What Was Implemented Now

### Product Worker Roles

Updated `SpecialistRole` with additive enum values:

- `build_engineer`
- `prompt_engineer`
- `optimization_engineer`
- `deployment_engineer`

Existing roles were preserved:

- `orchestrator`
- `requirements_analyst`
- `adk_architect`
- `tool_engineer`
- `skill_author`
- `guardrail_author`
- `eval_author`
- `trace_analyst`
- `release_manager`

### Specialist Registry Updates

Updated `builder/specialists.py` so each new role has:

- display name
- role description
- recommended tools
- permission scope
- context template
- intent keywords

### Worker Capability Registry

Added typed `WorkerCapability` records derived from specialist definitions. Each capability includes:

- role
- display name
- description
- tools
- permission scope
- trigger keywords
- skill layer
- expected artifacts
- whether the worker can call skills

### Coordinator-Owned Task Graph

Added `CoordinatorPlan` and `CoordinatorTask` records. Plans include:

- plan id
- root task id
- session id
- project id
- goal
- task nodes
- worker registry snapshot
- skill context
- synthesis summary
- mode: `coordinator_worker`

Task nodes include:

- stable node id
- worker role
- dependencies
- selected tools
- skill layer
- skill candidates
- permission scope
- expected artifacts
- routing reason
- provenance

### Optional Child Task Materialization

`BuilderOrchestrator.plan_work(..., materialize_tasks=True)` creates child `BuilderTask` records for planned worker nodes. Child tasks keep:

- parent task id
- active specialist
- coordinator plan id
- source/root task id
- worker role
- selected tools
- skill candidates
- expected artifacts
- provenance

This is optional and defaults off so plan inspection remains non-mutating except for recording the parent task's latest coordinator plan.

### Enriched Invocation Payloads

`BuilderOrchestrator.invoke_specialist(...)` still returns the existing fields and now also includes:

- `worker_capability`
- `recommended_tools`
- `provenance`

Existing API clients that expect the old keys should continue working.

### API Endpoint

Added:

```text
POST /api/builder/coordinator/plan
```

Request fields:

- `task_id`
- `goal`
- `requested_roles`
- `materialize_tasks`
- `extra_context`

The endpoint returns the serialized `CoordinatorPlan`.

### Project Skill Defaults on Create

`CreateProjectRequest` now accepts:

- `buildtime_skills`
- `runtime_skills`
- `deployment_targets`

This lets coordinator plans immediately reflect project skill context when projects are created through the builder API.

## Why This Slice

This slice makes AgentLab smarter without destabilizing the core product loop.

It is valuable now because it:

- gives builders a durable multi-worker plan instead of a single opaque route
- aligns workers with the AgentLab loop: Build, Prompt, Eval, Optimize, Deploy
- exposes which skills/tools are appropriate before execution
- makes routing and provenance inspectable
- uses existing `BuilderTask` persistence when materialization is requested
- keeps default single-agent flows working

It is safe because it:

- does not alter Workbench streaming behavior
- does not auto-run evals, optimize, or deploy
- does not add recursive workers
- does not bypass review or deploy gates
- leaves existing role values intact
- defaults to deterministic planning rather than live agent execution

## What Was Not Implemented Now

### No Live Worker Runtime

Live LLM-backed worker execution is a larger feature. It needs cancellation, budget tracking, provider selection, permission checks, worktree ownership, and result persistence.

### No Workbench UI Panel

Workbench can consume this API later. Adding UI now would increase scope and require frontend verification without proving the backend contract first.

### No CLI Command

The API and task metadata now expose the core surface. A CLI command should be added once the exact operator workflow is settled.

### No Skill Mutation Application

The coordinator exposes skill candidates; it does not apply build-time skills. Optimizer-owned skill application remains in `optimizer/skill_engine.py`.

### No Deployment Execution

Deployment worker plans include permission scope and expected artifacts. Actual release/canary/rollback remains owned by existing Deploy/Release flows.

## Residual Risks

- The coordinator plan is deterministic and keyword-based. It is safer than a live worker runtime but less intelligent than future model-backed planning.
- Product roles overlap with older roles. For example, `deployment_engineer` and `release_manager` both touch shipping concerns. The current split is deployment readiness versus release packaging, but UI copy should make that clearer later.
- Child task materialization creates planned tasks but does not execute them. API clients must not interpret materialized child tasks as completed work.
- Repeated calls with `materialize_tasks=true` intentionally create a new plan and new child tasks each time. A later UI/CLI surface should make this visible and may want explicit deduplication controls.
- Skill candidates come from project defaults, not semantic skill search. Future work should integrate `SkillStore.recommend(...)` for richer matching.
- There is no dedicated coordinator-worker UI yet, so users need API/task inspection to see the plan.
- Workbench does not yet include coordinator plans in its run handoff. That should be a follow-up once the backend shape has enough usage evidence.

## Follow-Up Opportunities

1. Add `agentlab build coordinate` or `agentlab workbench coordinate` to create and display coordinator plans from the CLI.
2. Add a Workbench Activity panel for coordinator plan, worker tasks, skill candidates, expected artifacts, and provenance.
3. Add execution adapters for deterministic worker tasks that call existing AgentLab services:
   - eval worker calls eval generation/run setup
   - optimize worker prepares optimizer request templates
   - prompt worker prepares instruction diffs
   - deploy worker prepares release/canary readiness checks
4. Integrate `SkillStore.recommend(...)` so skill candidates are semantic and evidence-aware.
5. Add worker result records for actual execution outcomes, including usage, artifacts, recommendations, and verification evidence.
6. Add continuation policy: when to continue the same worker versus spawn a fresh worker.
7. Add permission prompts and approval gates around materialized worker execution, especially source writes, external network, benchmark spend, and deployment.
8. Add result synthesis into Workbench handoff so the coordinator can recommend Eval, Optimize, Review, or Deploy based on completed worker evidence.

## Validation Performed So Far

Focused TDD verification:

```bash
.venv/bin/python -m pytest tests/test_builder_orchestrator.py tests/test_builder_api.py -q
```

Result:

```text
65 passed in 1.32s
```

The RED run before implementation showed expected failures for missing roles, missing capability registry, missing coordinator plan method, missing enriched invocation payload, and missing API endpoint. The same focused suite passed after implementation.

Additional verification:

```bash
.venv/bin/python -m pytest tests/test_builder_execution.py tests/test_builder_store.py tests/test_builder_projects.py tests/test_builder_contract.py -q
```

Result:

```text
105 passed in 0.81s
```

```bash
.venv/bin/python -m py_compile builder/types.py builder/specialists.py builder/orchestrator.py api/routes/builder.py builder/__init__.py
```

Result: exit code 0.

```bash
.venv/bin/python -m pytest tests/test_api_server_startup.py tests/test_workbench_api.py tests/test_workbench_streaming.py tests/test_workbench_eval_optimize_bridge.py -q
```

Result:

```text
36 passed in 25.67s
```

```bash
.venv/bin/python -m pytest tests/test_optimizer.py tests/test_optimizer_skill_integration.py tests/test_skill_engine.py tests/test_core_skill_store.py -q
```

Result:

```text
87 passed, 1 warning in 0.58s
```

The warning is the existing pytest collection warning for the dataclass named `TestCase` in `core/skills/types.py`.

```bash
.venv/bin/python -m pytest tests/test_cli_workbench.py tests/test_workbench_build_slash.py tests/test_workbench_skills_slash.py -q
```

Result:

```text
84 passed in 27.05s
```

```bash
.venv/bin/python -m pytest tests/test_builder_*.py -q
```

Result:

```text
232 passed in 5.89s
```

Server aliveness check:

```bash
.venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8765
curl -fsS http://127.0.0.1:8765/api/health
```

Result: uvicorn started successfully, `/api/health` returned HTTP 200 JSON, and uvicorn shut down cleanly.

Final fresh pre-commit verification:

```bash
.venv/bin/python -m pytest tests/test_builder_orchestrator.py tests/test_builder_api.py tests/test_builder_execution.py tests/test_builder_store.py tests/test_builder_projects.py tests/test_builder_contract.py tests/test_api_server_startup.py -q
```

Result:

```text
174 passed in 2.56s
```

```bash
.venv/bin/python -m py_compile builder/types.py builder/specialists.py builder/orchestrator.py api/routes/builder.py builder/__init__.py
```

Result: exit code 0.

```bash
git diff --check
```

Result: exit code 0.

Report length check:

```bash
wc -l working-docs/reviews/2026-04-14-coordinator-worker-builder-analysis.md
```

Result:

```text
565 working-docs/reviews/2026-04-14-coordinator-worker-builder-analysis.md
```

## Skeptic Self-Review

Review questions and outcomes:

- Could this break single-agent Build or Workbench flows? No direct Workbench streaming path was changed. Specialist invocation preserves existing response keys and adds new fields.
- Could enum expansion break persistence? Existing enum values are unchanged. Hydration still maps stored strings through `SpecialistRole`; new values are additive.
- Could API clients see unexpected project create behavior? New project create fields default to empty lists and match existing `BuilderProject` defaults.
- Could materialized child tasks be mistaken for completed work? They are created as default pending `BuilderTask` records with planned metadata only. The report and residual risks call this out.
- Could deployment workers bypass review/deploy gates? No. Deployment is represented as a worker capability and permission scope only.
- Could skill plans overclaim execution? No. Plans expose skill candidates and skill layers, but do not apply mutations or invoke runtime tools.

No blocking issues were found in self-review. The main follow-up is product surfacing: CLI and UI should render the coordinator plan so users are not limited to raw API/task metadata.
