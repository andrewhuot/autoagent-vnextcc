# Findings & Decisions

## P1 Workbench Eval Optimize Bridge - Codex

### Mission

- Create a typed Workbench -> Eval -> Optimize bridge so the improvement loop is structurally connected and evidence-based.
- Avoid AutoFix shortcuts. Workbench should hand off typed candidate/evidence data into Eval, then Optimize should consume completed eval run context.
- Required deliverable includes `working-docs/p1-workbench-eval-optimize-bridge-plan-codex.md`, tests, validation, commit, push, and an `openclaw system event`.

### Required Document Findings

- Workbench harness audit says Workbench and Optimizer are adjacent rather than connected. It recommends a structured improvement handoff containing validation status, failed checks, target, export names, generated config identity, review gate state, and recommended eval suite.
- Product/codebase audit highlights a trust gap and coherence gap. The relevant P1 principle is "wire before implement": avoid new surfaces without real loop integration.
- User/operator journey audit frames the main flow as `BUILD -> EVAL -> OPTIMIZE -> REVIEW -> DEPLOY` and identifies current gaps where these pages are adjacent rather than continuous.
- The right downstream path is Eval Runs -> Optimize using a real `eval_run_id`-scoped optimizer path. AutoFix should remain separate because it is proposal/apply-oriented and does not provide the eval/canary guarantees users might infer.

### Initial Bridge Direction

- Add a typed Workbench improvement handoff and downstream request builders rather than launching Eval or Optimize inline.
- The handoff should be durable, structured, and explicit about readiness, missing prerequisites, validation evidence, candidate config identity, recommended eval request, and optimizer handoff status.

### Implementation Findings

- Workbench already had a durable handoff refreshed from `_record_run_event()`; nesting `improvement_bridge` there makes it persist on active runs, terminal stream payloads, and `harness_state.latest_handoff`.
- Eval's typed request boundary is `EvalRunRequest(config_path, category, dataset_path, generated_suite_id, split)`.
- Optimize's typed request boundary already supports the desired downstream bridge with `OptimizeRequest(config_path, eval_run_id, ...)`.
- Optimize's `eval_run_id` path depends on an in-memory completed eval task before it enriches from durable result storage, so Workbench should not generate a concrete Optimize request until a real eval run has completed.
- The materialization endpoint saves the Workbench generated config into the real workspace config/version path, then returns an Eval request and an Optimize template with `eval_run_id=None`.
- Frontend `Optimize` already handled eval IDs passed through navigation state from Eval Runs, but ignored the `?evalRunId=` query param used by Eval Detail. The bridge slice fixed that so URL-based handoffs preserve eval context.

## Model Harness Engineering Campaign - Codex

### Mission

- Improve AgentLab's model harness for long-running agent loop quality, context and memory management, durable progress and handoff engineering, orchestration clarity, operator visibility, verification discipline, and anti-fake-progress behavior.
- Preserve current architecture where sound and ship one coherent high-leverage slice.
- Required deliverables: `working-docs/model-harness-engineering-analysis-codex.md`, `working-docs/model-harness-engineering-plan-codex.md`, implementation, tests, commit, push, and completion event.

### Initial Environment Findings

- Working directory is `/Users/andrew/Desktop/agentlab-model-harness-engineering-codex`.
- Branch is `feat/model-harness-engineering-codex`.
- Initial worktree was clean before planning-file creation.
- No project-local `AGENTS.md` file was found by `find . -maxdepth 2 -name AGENTS.md`; user-supplied working agreements are the active instructions.
- Existing `findings.md` already contains prior AgentLab/Workbench harness research and implementation notes; this campaign appends a fresh section.

### External Harness Research Findings

- Claude Code frames the harness loop as gather context, act, verify, and repeat, with the user able to interrupt and steer at any point. Effective harnesses should therefore surface where the loop is and what can be verified.
- Claude Code context guidance reinforces that conversation history is not durable state. Persistent instructions, memory, and repo files should carry long-lived decisions because compaction can lose early detail.
- Anthropic's long-running-agent guidance identifies two failure modes to guard against: trying to do too much at once, and prematurely declaring completion after seeing partial progress. Their mitigations are feature lists, incremental progress, progress files, clean git commits, and a basic startup verification path.
- Anthropic's application harness design emphasizes planner/generator/evaluator separation, concrete sprint contracts, evaluator logs with actionable failures, and skeptical QA rather than self-praise.
- Anthropic's managed-agents design separates brain, hands, and session log. The durable session log lives outside the model context and exposes event slices so a restarted harness can recover without a special surviving process.
- OpenAI's harness-engineering guidance emphasizes agent-legible repo knowledge, active execution plans and decision logs, typed and mechanically enforced boundaries, direct app/log/metric legibility, and feedback loops that turn repeated failures into tools or guardrails.

### Codebase Reconnaissance Findings

- `docs/plans/2026-04-11-workbench-model-harness-refactor.md` shows the latest Workbench vertical slice already implemented durable `run-*` envelopes, persisted messages/events, reflect/present lifecycle events, validation, presentation manifests, and frontend workspace tabs.
- `builder/workbench.py` now owns the main model harness lifecycle. `run_build_stream()` creates a run, persists events, updates canonical model state, runs reflect/present, and ends in `run.completed`.
- `builder/workbench.py` stores each run's `events`, `messages`, `validation`, `presentation`, `budget`, and `telemetry_summary`, and `get_plan_snapshot()` hydrates the active run plus turns, conversation, and a compact `harness_state`.
- `builder/harness.py` contains a deterministic `HarnessExecutionEngine` with plan/execute/checkpoint/reflect/present events and iteration support. It is agent-legible and testable, but checkpoint persistence errors are intentionally non-fatal and invisible.
- `api/routes/workbench.py` exposes streaming build, iterate, snapshot, validation, rollback, and server-side cancel endpoints.
- `web/src/lib/workbench-store.ts` stores run state, turn state, validation, active run, harness metrics, reflections, and cancellation events. The frontend consumes terminal `run.completed` rather than trusting `build.completed` as completion.
- Existing tests cover run lifecycle, reflect/present event order, persisted plan/artifacts/messages, failed runs, cancellation UI state, harness metrics, iteration, and harness_state checkpoint summaries.
- Remaining high-leverage gap: persisted run data is detailed but not distilled into a stable handoff/progress contract. Operators and resumed harnesses can inspect raw event arrays, but there is no concise "current task / last event / verification state / next action / recovery reason" digest analogous to a long-running agent progress file.
- Related gap: `harness_state` snapshot currently returns only `checkpoint_count` and `last_metrics`; it does not expose recent checkpoints or a recovery digest that would help steer or resume after refresh/stale recovery.
- Subagent backend inspection confirmed the older Builder Workspace uses durable SQLite sessions/tasks/artifacts, but its `EventBroker` remains in-memory and task progress can be set to 100 without artifacts, evals, approval, validation, or terminal status.
- Subagent Workbench inspection confirmed `auto_iterate` is advertised but not a real corrective loop yet, checkpointing is not resumability yet, and final verification remains shallow. Those are valuable follow-ups but larger than the safest coherent slice for this pass.

### Selected Implementation Slice

- Add a Workbench run `handoff`/progress manifest maintained from durable events. It should summarize current phase/status, last event, current task, completed/total task counts, latest artifact, verification state, next action, recent checkpoints, stale recovery details, and telemetry/budget pointers.
- Expose the manifest in `active_run`, terminal run payloads, and `harness_state.latest_handoff` so reloads and handoffs no longer require parsing the raw event array.
- Persist `harness_state.last_metrics` from `harness.metrics` events and expose recent checkpoints, not only a count.
- Add an evidence-safe Builder task progress clamp: non-terminal `progress_task(..., progress >= 100)` should stop at 99 and record a reason, preventing a running task from presenting as complete without using `complete_task()`.
- Keep all changes additive and test-focused.


## Workbench Model Harness Refactor Campaign

### Mission

- Transform Workbench into a true model harness for building agents.
- Target experience: natural-language instruction on the left, builder agent plan/act/reflect/present loop behind the scenes, live artifacts/results/preview on the right.
- Deliver code, tests, architecture note, commit, push, and completion event on `feat/workbench-model-harness-ralph-codex`.

### Initial Environment Findings

- Working directory is `/Users/andrew/Desktop/agentlab-workbench-model-harness-ralph`.
- Branch is `feat/workbench-model-harness-ralph-codex`.
- Initial worktree was clean.
- No relevant memory hits for AgentLab/Workbench/model harness/Ralph in `/Users/andrew/.codex/memories/MEMORY.md`.
- Project-local `AGENTLAB.md` is sparse project memory; user-supplied AGENTS instructions are the effective working agreement for this run.
- Existing `findings.md` already contains prior Workbench planning and implementation notes, including an additive `/workbench` route, `builder/workbench.py`, `/api/workbench`, deterministic natural-language planning, artifact previews, validation, versioning, and previous verification results.

### External Harness Research Findings

- Claude Code guidance emphasizes conversational iteration, interrupt/steer behavior, exploration before implementation, and verification targets the agent can check against.
- Anthropic long-running harness guidance emphasizes persistent progress notes, feature/state files, running a basic test at session start, and self-verification before marking work complete.
- Anthropic app harness guidance points toward explicit planner/generator/evaluator style phases and using the harness to keep an agent on a concrete build contract.
- Anthropic Managed Agents guidance reinforces separating session state, harness lifecycle, and execution/review surfaces so user control and recovery remain legible.
- OpenAI harness engineering emphasizes repo-local structured knowledge, first-class plans and decision logs, typed/validated boundaries, feedback loops, and agent-legible architecture over one giant instruction blob.

### Architecture Direction

- Keep `/workbench` as the focused harness surface and evolve the existing backend rather than starting another parallel model.
- Add a durable harness-run concept with clear phases: plan, act/build, reflect/validate, present.
- Persist phase events, current step, artifacts, validation results, and next actions server-side so refresh and iteration are trustworthy.
- Treat generated source/config/test/preview artifacts as compiled outputs from canonical project state, not the canonical state itself.
- The frontend should render run state from the API: queued/running/completed/failed, step timeline, artifacts, preview, and user controls.

### Open Questions To Resolve During Recon

- How much of the existing `builder/workbench.py` already has run/session state and how much is still request/response-only?
- Whether current tests assert a mocky plan/apply split or can be extended to assert end-to-end harness run behavior.
- Whether frontend currently polls/fetches durable state or derives progress locally after a request.

### Reconnaissance Findings

- Current backend already had `WorkbenchStore`, `WorkbenchService`, `WorkbenchBuilderAgent`, `PlanTask`, `WorkbenchArtifact`, `/api/workbench/build/stream`, and a live/mock agent split.
- The streaming path persisted plan/artifacts and applied operations, but did not have a first-class run envelope, persisted event replay, persisted assistant narration, reflect/present phases, or automatic validation after streaming completion.
- The synchronous plan/apply API already validates apply/rollback and deterministic compatibility; this campaign kept it intact.
- Existing Builder Workspace primitives (`BuilderStore`, `BuilderExecutionEngine`, `EventBroker`, `BuilderOrchestrator`) remain the right future durable substrate, but this vertical slice can safely add run state inside current Workbench JSON persistence.
- Current frontend already had a two-pane Workbench shell, Zustand stream reducers, SSE parser, plan tree, artifact cards, and artifact/source preview.
- Frontend gaps were: right pane only artifact gallery, stream completion did not hydrate final version/model/exports/activity, category filtering could show stale active artifacts, refreshed messages were not supported, shared layout constrained Workbench width, and `Create agent` / paperclip looked active without behavior.

### Implementation Findings

- Added durable Workbench run envelopes with `run_id`, phase, status, started/completed versions, persisted messages, replayable events, validation, presentation, and errors.
- Streaming events are enriched with `project_id`, `run_id`, phase, and status.
- Streaming now completes through `build.completed -> reflect.started -> reflect.completed -> present.ready -> run.completed`.
- Reflection compiles exports, runs `run_workbench_validation`, stores `last_test`, and records activity.
- Presentation publishes artifact IDs, generated output names, validation status, and next actions.
- Stream failures now persist `build_status = failed`, run status/error, and terminal `run.failed`.
- `get_plan_snapshot` now returns messages, active run, runs, last test, activity, exports, and compatibility.
- `api.server` now initializes `app.state.workbench_store` from `AGENTLAB_WORKBENCH_STORE` or the default `.agentlab/workbench_projects.json`.
- Frontend store now tracks active run, presentation, exports, compatibility, validation, activity, workspace tab, and persisted messages.
- `build.completed` no longer marks the UI done; `run.completed` is the terminal success event.
- Right pane now has tabs for Artifacts, Agent Card, Source Code, Evals, Trace, and Activity.
- Artifact category selection now switches the active artifact into the selected category.
- Workbench gets a full-width layout exception in shared `Layout`.
- Misleading inert controls were softened: attachments are disabled, and `Create agent` is disabled until a completed run.

### Verification Results For This Campaign

- Red backend test run initially failed on missing terminal `run.completed`, missing `reflect.started`, stale `idle` status, and unpersisted exception state.
- Red frontend test run initially failed on premature `build.completed` done state, ignored `run.completed`, and artifact category mismatch.
- `.venv/bin/python -m pytest tests/test_workbench_streaming.py -q`: 13 passed.
- `.venv/bin/python -m pytest tests/test_workbench_api.py tests/test_workbench_streaming.py tests/test_workbench_agent_live.py -q`: 25 passed.
- `npm run test -- src/lib/workbench-store.test.ts src/components/workbench/ArtifactViewer.test.tsx`: 13 passed.
- `npm run test -- src/pages/AgentWorkbench.test.tsx src/lib/workbench-store.test.ts src/components/workbench/ArtifactViewer.test.tsx src/lib/navigation.test.ts`: 26 passed.
- `npm run test`: 48 files passed, 291 tests passed; output includes jsdom's known `Not implemented: navigation to another Document` message.
- `npm run build`: passed with Vite's existing large-chunk warning.
- `npx eslint <touched Workbench/Layout files>`: passed.
- `.venv/bin/python -m py_compile builder/workbench.py builder/workbench_agent.py builder/workbench_plan.py api/routes/workbench.py api/server.py`: passed.
- `git diff --check`: passed.
- Browser smoke on `/workbench`: passed prompt submit, `Candidate ready`, Agent Card, Source Code, Evals, Trace, and Activity tab checks. Workbench network calls returned 200 and no console warning/error appeared before local server shutdown.
- `.venv/bin/python -m pytest -q`: 3578 passed, 3 failed, 19 warnings. The failures are unrelated to Workbench: `tests/test_mutations.py::test_create_default_registry_has_13_operators`, `tests/test_mutations.py::test_register_duplicate_overwrites`, and `tests/test_registry.py::TestMutationSurfaceExtensions::test_total_operator_count` expect 13 mutation operators while the current registry returns 14.

## Agent Builder Workbench Planning Campaign

### Requirements
- Produce a concrete, ticketed implementation plan for Agent Builder Workbench / Workbench for Agents.
- Ground the plan in the current AgentLab codebase, especially Build, Agent Improver, Eval Runs, Results Explorer, Compare, Optimize, Improvements, Trace, and Deploy.
- Decide whether Workbench should be a new route/surface in addition to Build or a deeper Build evolution.
- Define the canonical data model, reusable backend services/stores/APIs, reusable frontend surfaces/components, vertical slicing order, risks, and verification expectations.
- Save the durable deliverable under `docs/plans/`.
- Commit and push `feat/agent-builder-workbench-plan-codex`, then send the requested `openclaw system event`.

### Initial Environment Findings
- Branch is `feat/agent-builder-workbench-plan-codex`.
- Worktree was clean before this campaign.
- The current workspace already contains historical `findings.md` notes from prior Build and Agent Improver UX campaigns.

### Research Findings
- Repository has dedicated backend packages for `builder`, `adk`, `cx_studio`, `evals`, `observer`, `deployer`, `stores`, and API routes under `api/routes`.
- Web surfaces already include `Build`, `AgentImprover`, `EvalRuns`, `ResultsExplorer`, `Compare`, `Optimize`, `Improvements`, `Traces`, `Deploy`, `AdkDeploy`, `CxDeploy`, `CXStudio`, and a lower-level builder component system.
- Prior commit history confirms the branch starts from `f5c14c7 feat(journey): connect eval→optimize→improve→deploy journey with navigation and CTAs`.
- Existing docs/plans already contain related plans for agent builder rebuild, seamless journey, ADK/CXAS portability, CX deploy hardening, and CX native expansion.
- `working-docs/briefs/BUILDER_WORKSPACE_PRD.md` already defined a broader Builder Workspace with projects, sessions, tasks, proposals, artifacts, approvals, worktrees, eval bundles, trace bookmarks, release candidates, specialist roster, and event streaming.
- The current backend has matching builder primitives in `builder/types.py`, SQLite persistence in `builder/store.py`, project inheritance helpers in `builder/projects.py`, task lifecycle/delegate simulation in `builder/execution.py`, event broker/SSE helpers in `builder/events.py`, and specialist routing in `builder/orchestrator.py`.
- The current API already exposes `/api/builder/*` conversational builder endpoints plus projects/sessions/tasks/proposals/artifacts/approvals/permissions/events/metrics/specialists in `api/routes/builder.py`.
- `api/server.py` wires builder store/project manager/orchestrator/events/permissions/execution/metrics/artifacts into `app.state`, but conversational `BuilderChatService` remains in-memory/lazy-created rather than persisted in `BuilderStore`.
- `web/src/pages/Build.tsx` is the canonical `/build` surface and already includes prompt, transcript, builder-chat, and saved-artifacts tabs with config preview, runtime preview, save to Agent Library, and eval handoff.
- `web/src/lib/builder-chat-api.ts` defines the current narrow `BuilderConfig` shape: name, model, system prompt, tools, routing rules, policies, eval criteria, and metadata. This is not yet the PRD's richer canonical agent-project model.
- `web/src/lib/builder-types.ts` mirrors the broader Builder Workspace project/session/task/proposal/artifact/event model, separate from the narrow builder-chat config payload.
- `web/src/App.tsx` redirects legacy builder/assistant/agent-studio routes to `/build?tab=builder-chat`; navigation simple mode centers the Setup → Build → Eval → Improve → Deploy flow.

### Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Use the existing root `findings.md` as campaign working memory | It already contains related Build/Agent Improver discoveries that are relevant to the Workbench plan. |
| Recommend Workbench as a new Build-family route first, not an immediate `/build` replacement | The PRD's two-pane IDE scope is much larger than the current stable Build flow; a separate route can reuse the Builder Workspace substrate without destabilizing current Build -> Eval handoffs. |
| Treat `AgentProjectSpec` as a new canonical model layered under `BuilderProject` | `BuilderProject` is a workspace shell, while the PRD needs a structured agent truth that compiles to AgentLab runtime config, ADK, and CX. |
| Reuse Builder Workspace primitives for plan/apply/task/event history | `BuilderSession`, `BuilderTask`, `BuilderProposal`, `ArtifactRef`, `EvalBundle`, `TraceBookmark`, and `ReleaseCandidate` already match much of the PRD's harness architecture. |

### Issues Encountered
| Issue | Resolution |
|-------|------------|

### Verification Results
- Plan written to `docs/plans/2026-04-10-agent-builder-workbench.md`.
- `git diff --check`: passed.
- `rg` heading check confirmed the plan includes executive recommendation, current architecture inventory, functional requirement coverage, route decision, canonical data model, backend/frontend architecture, risks, phase order, ticket backlog, and verification matrix.

## Agent Builder Workbench Campaign Findings

### Initial State

- Branch is `feat/agent-builder-workbench-codex`.
- HEAD is `f5c14c74d14d5a7a145ffe3865f85c0e8894ed41`, matching `origin/master` and the requested base commit.
- Local `master` is older (`f15f0b36a2fb86f103a88aa296b5d7a8cb8adff7`), so this campaign will avoid using it as a base or merge target.
- Initial worktree was clean.
- No project-local `AGENTS.md` file was found in this checkout; follow the user-supplied global instructions and existing repo style.
- Memory quick pass found no relevant hits for Workbench/AgentLab in `/Users/andrew/.codex/memories/MEMORY.md`.

### Product Requirements

- The Workbench must be a new feature in addition to current AgentLab, not a destructive replacement.
- It should reuse current Build, Agent Improver, Eval Runs, Results Explorer, Compare, Optimize, Improvements, Trace, and Deploy surfaces where feasible.
- Canonical model comes first: natural-language changes patch structured state, then generated source/config/export previews derive from that state.
- Conversation and change planning live on the left; the current system truth lives on the right.
- Show a plan before applying, and run validation/testing after applying.
- Label components and exports as portable, ADK-only, CX-only, or invalid for the selected target.
- MVP right-pane surfaces: Preview, Agent Card, Source Code, Tools, Callbacks, Guardrails, Evals, Trace, Test Live, Deploy, Activity/Diff.

### Repo Reconnaissance Findings

- `/build` is the existing unified Build workspace. Its builder-chat tab is the closest current primitive: it calls `/api/builder/chat`, `/api/builder/preview`, exports config, saves via `/api/agents`, and hands off to Eval Runs.
- `BuilderChatService` stores in-memory sessions and converts natural language into generated config. It is useful but not canonical-model-first: follow-up turns mutate `generated_config` directly through `TranscriptIntelligenceService.chat_refine`.
- `builder/workspace_config.py` already maps generated Build contracts into real AgentLab runtime configs, preview runs, saved versions, and generated eval cases. This should be reused for Workbench preview/test/save.
- `/api/agents` already saves builder sessions or config dictionaries into the shared agent library/versioning path and returns agent records suitable for Eval Runs.
- `/evals`, `/traces`, and `/deploy` already have page/API surfaces and React Query hooks. Workbench can link/handoff to those routes and show compact embedded summaries rather than duplicating all logic.
- ADK import/export routes and CX import/export/deploy/preflight routes already exist. For MVP export previews, a canonical compiler can produce representative ADK/CX artifacts without requiring a live ADK snapshot or CX credentials.
- `cx_studio/compat.py` already contains ADK/CX compatibility semantics. Workbench can use its status categories to label canonical components as portable, ADK-only, CX-only, or invalid for target.
- Navigation metadata lives in `web/src/lib/navigation.ts`, route wiring in `web/src/App.tsx`, and sidebar icons in `web/src/components/Sidebar.tsx`.
- Frontend tests use Vitest + Testing Library with inline `fetch` stubs. Backend route tests commonly create a small FastAPI app and include the target router directly.

### Architecture Direction

- Add a new `/workbench` route and navigation entry under Build, keeping `/build` intact.
- Add a backend Workbench service/store under `builder/` that owns canonical agent project state, versions, activity, exports, compatibility labels, and validation/test results.
- Add API endpoints under `/api/workbench` for create/get, plan, apply, test, export preview, history, and rollback.
- Keep generated ADK/CX source/config as compiler output from the canonical model. Do not use generated files as the source of truth.
- On apply, create a new immutable version, compile outputs, and run deterministic validation/test immediately.

### Implementation Findings

- Added `builder/workbench.py` as the canonical model service/store/compiler. It owns structured project state, plan inference, apply operations, export previews, compatibility diagnostics, validation, activity, versions, and rollback.
- Added `/api/workbench` routes for project create/default/get, plan, apply, test, and rollback.
- Workbench state persists to `.agentlab/workbench_projects.json` by default; tests inject an isolated `WorkbenchStore`.
- Export previews are compiler output from canonical state:
  - ADK: `agent.py`, `tools.py`, and `agentlab.yaml`.
  - CX: `agent.json` and `playbook.yaml`.
- Compatibility diagnostics label canonical objects as `portable`, `adk-only`, `cx-only`, or `invalid`. A local shell tool is ADK-only generally and invalid for the CX target.
- Added `web/src/pages/AgentWorkbench.tsx` with the PRD two-pane shape: left conversation/plans/progress/history, right truth tabs for all MVP surfaces.
- Added `web/src/lib/workbench-api.ts` as a typed frontend client.
- Added `/workbench` route, Build navigation entry, simple sidebar inclusion, route metadata, and sidebar icon.

### Focused Verification

- `.venv/bin/python -m pytest tests/test_workbench_api.py -q`: 4 passed.
- `npm run test -- src/pages/AgentWorkbench.test.tsx src/lib/navigation.test.ts`: 12 passed.

### PRD Coverage

- Covered: new additive `/workbench` surface with the PRD two-pane model.
- Covered: canonical structured project model in backend state before generated outputs.
- Covered: natural-language requests generate structured change-plan cards before apply.
- Covered: applying a plan mutates the canonical model, creates a version, recompiles exports, and runs validation immediately.
- Covered: right-pane surfaces for Preview, Agent Card, Source Code, Tools, Callbacks, Guardrails, Evals, Trace, Test Live, Deploy, and Activity / Diff.
- Covered: portable / ADK-only / CX-only / invalid compatibility labels, including CX-invalid local shell tools.
- Covered: ADK export preview and CX export preview compiled from canonical state.
- Covered: version history and rollback affordance in the Workbench shell.
- Covered: reuse/handoff to existing Eval Runs, Trace, and Deploy surfaces through Workbench tabs and route links.

### Deferred Scope

- Direct save of a Workbench canonical project into the existing AgentLab agent library is not wired yet; the Deploy tab currently hands off to the existing eval/deploy routes.
- Eval execution remains deterministic Workbench validation plus route handoff, not a full generated eval run launched from the Workbench tab.
- Trace is based on Workbench validation events; it does not yet persist into the broader trace database.
- ADK/CX exports are preview artifacts, not downloadable packages or live CX deployments.
- The natural-language interpreter is deterministic MVP inference, not an LLM-backed semantic planner.

### Verification Results

- `.venv/bin/python -m pytest tests/test_workbench_api.py -q`: 4 passed.
- `npm run test -- src/pages/AgentWorkbench.test.tsx src/lib/navigation.test.ts`: 12 passed.
- `.venv/bin/python -m pytest tests/test_workbench_api.py tests/test_builder_chat_api.py tests/test_agents_api.py tests/test_api_server_startup.py -q`: 18 passed.
- `npm run test -- src/pages/AgentWorkbench.test.tsx src/lib/navigation.test.ts src/pages/Build.test.tsx src/components/Layout.test.ts`: 47 passed.
- `.venv/bin/python -m py_compile builder/workbench.py api/routes/workbench.py`: passed.
- `npm run build`: passed with the existing Vite large-chunk warning.
- `npx eslint src/pages/AgentWorkbench.tsx src/pages/AgentWorkbench.test.tsx src/lib/workbench-api.ts src/lib/navigation.ts src/lib/navigation.test.ts src/components/Sidebar.tsx src/App.tsx`: passed.
- `npm run test`: 45 files passed, 271 tests passed, with the existing jsdom navigation warning.
- `.venv/bin/python -m pytest -q`: 3556 passed, 4 failed, 19 warnings. The failures are unrelated to touched files: two mutation-count tests and one mutation registry test expect 13 operators while the current registry has 14, and one shell-script safety test did not observe port 5173 opening in time.
- `npm run lint`: failed on pre-existing repo-wide lint debt in untouched files. Touched-file ESLint passed separately.
- Browser sanity on `/workbench`: passed create-plan, plan-before-apply, apply-to-v2, automatic-test, right-tab, and ADK/CX export preview checks.

## Agent Improver Live UX Campaign Findings

### Requirements
- Pressure-test Agent Improver as an actual managed-agent workflow, not a polished one-shot demo.
- Verify user understanding, iterative guidance, state continuity, provider honesty, save/export/eval handoff, and recovery paths.
- Prefer live provider mode when feasible; document exact blocker if live execution is unavailable or rate-limited.
- Implement pragmatic, high-leverage improvements with regression tests and browser verification.

### Initial Environment Findings
- Branch is `feat/agent-improver-live-ux-ralph-codex`.
- Base HEAD is `f15f0b3 fix(eval): correct misleading status label, add back-nav, resolve step numbering conflict`.
- Initial worktree was clean.
- No project-local `AGENTS.md` file exists in this checkout.
- Previous root `findings.md` content is from a portability/readiness task; preserving it below for history while adding this campaign section.

### Research Findings
- Agent Improver primary implementation is `web/src/pages/AgentImprover.tsx` with local persistence helpers in `web/src/lib/agent-improver.ts`.
- Main tests live in `web/src/pages/AgentImprover.test.tsx` and `web/src/lib/agent-improver.test.ts`.
- Route wiring is in `web/src/App.tsx`, navigation metadata in `web/src/lib/navigation.ts`, and sidebar icon mapping in `web/src/components/Sidebar.tsx`.
- The feature appears frontend-heavy and likely uses the builder chat/session layer rather than a dedicated `agent-improver` backend route.
- Nearby relevant web APIs include `web/src/lib/builder-chat-api.ts`, `web/src/lib/builder-api.ts`, and provider fallback helpers.
- The builder backend exposes chat/session/export/save/preview endpoints under `/api/builder/*`, backed by `BuilderChatService`.
- Agent Improver saves through the shared agent library POST `/api/agents` path with `source: built`, `build_source: builder_chat`, and `session_id`.
- Eval handoff currently navigates to `/evals?agent=<id>&new=1` with navigation state `{ agent, open: 'run' }`; the eval page selects the agent and opens the run form.
- Eval generation already exists via `EvalGenerator` and the generated eval suite APIs, but Agent Improver does not carry draft eval intent into that generator.
- Runtime state: `agentlab.yaml` has `optimizer.use_mock: true`; `OPENAI_API_KEY` is present in the shell, but this workspace is explicitly pinned to mock mode.
- CLI live/provider inspection via `runner.py mode show` and `runner.py doctor` failed under the default `python3` because it is too old for PEP 604 type unions in this codebase, and `.venv/bin/python` does not exist in this checkout.

### Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Use planning files for the campaign | The task spans repo discovery, UX audit, browser testing, implementation, verification, commit/push, and notification. |
| Start with evidence before fixes | The prompt asks whether the feature actually works in real life; changes should be grounded in observed journey failures. |

### Issues Encountered
| Issue | Resolution |
|-------|------------|
| No prior session catchup data was emitted | Continued with a clean worktree and fresh discovery. |
| CLI provider inspection failed with `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'` under default `python3` | Record as environment blocker; use explicit newer Python if available for later backend checks. |
| New regression tests failed as expected | Proceed to implementation: real retry should resend, eval plan CTA should call builder chat, and eval handoff should open the generator with Agent Improver context. |
| Live builder request reached the provider path but returned `HTTP Error 429: Too Many Requests` | Preserve honest rate-limit/fallback UX, add real retry behavior, and verify local eval-plan generation still works on the same session. |
| Full Playwright surfaced stale route/health-check strictness in existing tests | Updated mock-honesty and intelligence browser checks to ignore expected Vite `net::ERR_ABORTED` module aborts and assert current `/assistant` redirect behavior. |
| Repo-wide ESLint fails on existing broad lint debt | Cleaned touched-file lint findings and recorded repo-wide lint as a remaining non-blocking issue. |

### Implementation Findings
- Rate-limit recovery was only a composer convenience: `Retry last request` repopulated text but did not actually retry the live builder request. The button now replays the last user request against the same builder session.
- Agent Improver lacked an explicit way to turn a promising draft into validation cases. Summary mode now exposes a `Generate eval plan` action when the live session can continue and no draft eval plan exists.
- Draft eval ideas were not meaningful in the handoff. Saved drafts with eval plans now route to `/evals?agent=<id>&generator=1&from=agent-improver` with state that opens the Eval Generator and explains the handoff.
- Eval Runs now distinguishes an Agent Improver handoff from a generic eval setup. The generator panel tells the user to formalize, review, and then run the saved config's eval suite.
- Existing `/assistant` browser coverage was stale because that legacy route now redirects to Build. The mock-honesty spec now verifies the current redirect plus Build preview-mode warnings.

### Visual/Browser Findings
- Added and passed a Playwright browser journey for Agent Improver: open route, create draft, generate eval plan, inspect config, download export, save, and land in Eval Generator with Agent Improver context.
- Full Playwright verification passes: 36 tests passed against local Vite at `http://127.0.0.1:5174`.
- Live/API probe used isolated API state on port 8010 to avoid polluting the checkout. The existing server on port 8000 is mock-pinned, and the isolated live-preferred server hit provider rate limiting.

### Verification Results
- `npm run test -- src/pages/AgentImprover.test.tsx src/pages/EvalRuns.test.tsx src/lib/agent-improver.test.ts src/lib/provider-fallback.test.ts src/components/EvalGenerator.test.tsx src/components/GeneratedEvalReview.test.tsx`: 74 passed.
- `npm run test`: 44 files passed, 264 tests passed. Output includes jsdom's known `Not implemented: navigation to another Document` message.
- `.venv/bin/pytest tests/test_builder_chat_api.py tests/test_agents_api.py tests/test_eval_generate_routes.py tests/test_generated_evals_api.py -q`: 31 passed.
- `npm run build`: passed; Vite still warns that the main chunk is larger than 500 kB.
- `npx eslint <touched files>`: passed.
- `npm run lint`: failed on pre-existing repo-wide lint debt in unrelated files plus broad React compiler rules; touched files were cleaned separately.
- `PLAYWRIGHT_BASE_URL=http://127.0.0.1:5174 npx playwright test`: 36 passed.

---

## Build Live UX Campaign Findings

### Source Reconnaissance

- `/build` is the canonical Build entry. Legacy `/builder`, `/builder/demo`, `/agent-studio`, `/assistant`, and `/intelligence` redirect into `/build` tab variants through `web/src/lib/navigation.ts` and `web/src/App.tsx`.
- `web/src/pages/Build.tsx` contains four tabs: prompt, transcript, builder-chat, and saved-artifacts. The builder-chat path is the closest to the requested managed-agent workflow.
- Builder chat state is held in `BuilderChatWorkspace`: messages, latest `BuilderSessionPayload`, preview result, save result, saved agent, and a config modal flag.
- Builder chat flow calls `/api/builder/chat`, `/api/builder/preview`, `/api/builder/export`, and saves through the shared `/api/agents` hook with `source: built` and `build_source: builder_chat`.
- Prompt/transcript flow calls intelligence generation/refinement APIs, then shared preview/save/eval handoff.
- Eval handoff is already wired: Build navigates to `/evals?agent=<id>&new=1` or `/evals?agent=<id>&generator=1` with selected agent in router state; `EvalRuns` uses that state to preselect the agent and show a first-run panel.
- Existing coverage includes `web/src/pages/Build.test.tsx`, `web/src/pages/Builder.test.tsx`, `web/tests/builder-flow.spec.ts`, and backend `tests/test_builder_chat_api.py`.
- Prior docs explicitly flagged a trust gap around mock/live behavior and a previous builder rebuild plan that intentionally created a single conversational builder with mock-friendly APIs.

### Runtime Journey Findings

- Setup had not been run in this clone. `./setup.sh` created `.venv`, `web/node_modules`, `.env`, and demo data successfully.
- Runtime started with `./start.sh`; final browser verification used `http://localhost:5180` with backend `http://localhost:8000` because the default frontend port was already occupied during the campaign.
- `/api/health` reports `mock_mode: true`, `real_provider_configured: false`, and mock reason `Mock mode explicitly enabled by optimizer.use_mock.` The repo-local `agentlab.yaml` has `optimizer.use_mock: true`, and `.env` has blank provider keys. Live mode was therefore blocked by local runtime config/provider setup.
- Browser journey on `/build?tab=builder-chat` succeeded through initial draft, preview, save, and eval handoff.
- The preview/test step exposed a trust problem: after building/refining an airline booking-change agent, the mock preview answered with generic order-support copy (`I can help with your order`) for a delayed-flight change request. The UI correctly labels mock mode, but the preview is too generic to help a user decide whether the agent improved.
- Save-and-eval handoff worked: `Save & Run Eval` saved the draft and navigated to `/evals?agent=agent-v003&new=1`, where Eval Runs showed the saved draft selected and the first-run form ready.

### Product/UX Failure Modes

- The original UI had pieces of an iteration loop, but the loop was not visually treated as the primary object. Users could chat, test, view config, save, and eval, yet there was no persistent sense of iteration count, last change, quality signal, or next best action after a preview/refinement.
- Config visibility is binary: hidden behind a modal or full raw YAML/JSON. That protects the main panel from intimidation, but it also removes lightweight "what changed?" inspection from the core loop.
- Preview results show the agent response and runtime metadata, but they do not turn that evidence into a decision: keep refining, save, generate evals, or validate live.
- The fallback preview path is honest about being simulated, but not helpful enough. A simulated response should still reflect the built domain and selected tool/routing signals so iteration has momentum.

### Implementation Decisions

- Make the iteration loop visible above the Builder Chat workspace instead of relying on scattered controls. The loop now calls out the current iteration, last user change, latest preview signal, and next action across Draft, Inspect, Test, and Save/Eval.
- Add a lightweight draft inspection panel next to the conversation/preview. It summarizes the system prompt, tools, routes, policies, and eval checks so users can inspect what changed without opening raw YAML first.
- Keep raw config access available through the existing modal/download path for deeper review, but make the default Build posture more like an agent workbench than a static form.
- Improve mock-preview usefulness without pretending it is live: airline Build drafts now return airline-specific preview copy, expose configured tool names, and pick the most relevant configured tool for booking changes, cancellations, and flight status.
- Preserve the existing save/export/eval architecture. The high-leverage UX fix did not require new persistence contracts; it made the existing handoff clearer and easier to trust.

### Verification Evidence

- Frontend regression: `npm test -- src/pages/Build.test.tsx -t "shows the current iteration loop"` passed.
- Frontend tool-call regression: `npm test -- src/pages/Build.test.tsx -t "shows configured tool names"` passed.
- Frontend related suite: `npm test -- src/pages/Build.test.tsx src/pages/Builder.test.tsx src/lib/builder-chat-api.test.ts` passed with 24 tests.
- Backend targeted regression: `.venv/bin/python -m pytest tests/test_builder_chat_api.py -k preview_uses_built_domain_in_mock_mode -q` passed.
- Backend related suite: `.venv/bin/python -m pytest tests/test_builder_chat_api.py tests/test_builder_api.py tests/test_build_artifact_store.py -q` passed with 49 tests.
- Syntax check: `.venv/bin/python -m py_compile evals/fixtures/mock_data.py` passed.
- Playwright maintained flow: `PLAYWRIGHT_BASE_URL=http://localhost:5180 npx playwright test tests/builder-flow.spec.ts` passed with 2 tests.
- Manual browser verification on `http://localhost:5180/build?tab=builder-chat` covered create, inspect, test, mock fallback, configured `Tool: change_booking`, save, and `/evals?agent=agent-v003&new=1` handoff to `Start First Evaluation`.
- Full web build remains blocked outside this Build scope: `npm run build` fails on unused `NormalizedFallback` imports in `src/lib/provider-fallback.test.ts` and `src/pages/AgentImprover.tsx`.
