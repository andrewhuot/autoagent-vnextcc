# Findings & Decisions

## Live UI Integration Merge - Codex

### Mission

- Stay on `/Users/andrew/Desktop/agentlab-live-ui-merge-codex` branch `feat/live-ui-golden-path-integration-codex`.
- Use `feat/live-ui-golden-path-codex` as the backbone and selectively port UI polish plus Playwright coverage from `feat/live-ui-golden-path-claude-opus`.
- Do not push and do not merge the entire Claude branch.
- Preserve Codex backend/UI flow correctness, especially Build handoff/saved-version behavior and EvalRuns strict-live/selected-agent behavior.

### Initial Findings

- Required overlap command completed before source edits.
- Diff stat across requested paths:
  - `web/src/components/workbench/ChatInput.tsx`: 3 lines changed.
  - `web/src/pages/Build.test.tsx`: 30 lines changed.
  - `web/src/pages/Build.tsx`: 48 lines changed.
  - `web/src/pages/EvalRuns.tsx`: 37 lines changed.
  - `web/tests/builder-flow.spec.ts`: 8 lines changed.
  - `web/tests/live-golden-path-deep.spec.ts`: 280 lines added.
  - `web/tests/live-golden-path.spec.ts`: 274 lines added.
  - `web/tests/verify-fixes.spec.ts`: 70 lines added.
- Worktree started clean on `feat/live-ui-golden-path-integration-codex`.
- Session catchup script produced no additional output.

### Merge Decisions

| Decision | Rationale |
|----------|-----------|
| Start with wholesale checkout only for user-approved Claude-only files | Keeps scope bounded and avoids accidentally replacing flow-critical Codex files. |
| Manually inspect Codex and Claude versions before patching Build/EvalRuns | Needed to separate UX polish from flow correctness changes. |

### Wholesale Port Findings

- `web/src/components/workbench/ChatInput.tsx` Claude update changes the send button from an icon-only square to a compact labeled button when text is present.
- `web/tests/builder-flow.spec.ts` Claude update broadens ignored aborted request noise and loosens eval URL matching so additional query params do not fail the flow test.
- Three Claude Playwright specs were added wholesale:
  - `web/tests/live-golden-path.spec.ts`
  - `web/tests/live-golden-path-deep.spec.ts`
  - `web/tests/verify-fixes.spec.ts`

### Manual Merge Findings

- `Build.tsx` retained the Codex `navigateToWorkbenchWorkflow` behavior that carries the original prompt and saved model hint into Workbench.
- Build UX polish added:
  - Primary dark Save to Workspace styling for Builder Chat and Studio save buttons.
  - A persistent saved-next-steps banner above the lower preview/save details area.
  - Banner CTA buttons for Continue to Workbench and Continue to Eval.
- `Build.test.tsx` now covers the saved-next-steps banner and still verifies the Workbench handoff preserves the original prompt.
- `EvalRuns.tsx` retained Codex strict-live request behavior (`require_live`) and active-agent completed-run filtering.
- EvalRuns UX polish added only the disabled Start Eval title and helper text when no agent is selected.

### Verification Findings

- `web/node_modules` was absent, so `npm ci` was required before frontend test execution.
- Literal shell command `cd web && vitest run ...` fails in zsh because `vitest` is not on PATH; the installed project binary works via `./node_modules/.bin/vitest`.
- Touched page check passed: `cd web && ./node_modules/.bin/vitest run src/pages/Build.test.tsx src/pages/EvalRuns.test.tsx` reported 2 files passed and 34 tests passed.
- Global `pytest tests/test_workbench_api.py tests/test_workbench_streaming.py -q` used Homebrew Python without FastAPI, so a project `.venv` was created with `uv` and `.[dev]`.
- Backend verification in the project venv passed:
  - `pytest tests/test_p0_journey_fixes.py -q`: 20 passed.
  - `pytest tests/test_workbench_api.py tests/test_workbench_streaming.py -q`: 23 passed.
  - `pytest tests/test_eval_agent.py tests/test_generated_evals_api.py -q`: 10 passed.
- Full frontend verification via local binary passed: `cd web && ./node_modules/.bin/vitest run` reported 56 files passed and 394 tests passed.
- Playwright environment caveat: ports 8000 and 5173 were occupied by another `/Users/andrew/Desktop/agentlab` checkout, and 5174 was also occupied. This branch frontend was started on 5175.
- Practical Playwright subset passed: `PLAYWRIGHT_BASE_URL=http://127.0.0.1:5175 ./node_modules/.bin/playwright test tests/builder-flow.spec.ts tests/verify-fixes.spec.ts --workers=1` reported 5 passed.
- The two live golden path specs were not run because their API paths target hardcoded localhost:8000 through Vite proxy/direct page requests, and localhost:8000 was occupied by a different checkout with a real provider configured.

## AgentLab Golden Path E2E Hardening - Codex

### Mission

- Test the full AgentLab UI path end to end with a concrete customer FAQ support agent idea.
- Focus path: Build -> Workbench -> Evals -> Optimize / Improve -> Deploy.
- Ignore pro mode.
- Record gaps in markdown and then fix the highest-impact issues.

### Initial Environment Findings

- Working directory is `/Users/andrew/Desktop/agentlab`.
- Existing unrelated local changes were present before this campaign:
  - `evals/synthetic_dataset.json`
  - `docs/plans/2026-04-12-cohesive-product-hardening.md`
  - `my-agent/`
  - `progress.txt`
- Prior session catchup reported Workbench light-theme work was already pushed as commit `48d2e05`.
- Frontend app lives under `web/` and uses Vite, React 19, Vitest, and Playwright config.
- Primary routes include `/build`, `/workbench`, `/evals`, `/optimize`, `/improvements`, and `/deploy`.

### Browser Golden Path Findings

- Build prompt tested with `FAQ Concierge`, a B2B SaaS FAQ support agent brief covering billing, onboarding, account, security, citations, clarification, and escalation.
- The Build prompt flow enabled `Generate Agent` and produced a draft, but the generated config content was an HR assistant:
  - Summary: employee benefits, policies, payroll, onboarding.
  - Tools: `get_employee_profile`, `submit_time_off_request`, `get_policy_document`.
  - Policies: employee confidentiality, equal treatment, sensitive topic escalation.
- Severity: critical for golden path. The first generated agent does not honor the user's agent idea, even though the UI presents it as a successful draft.
- UX impact: users cannot trust the Build result, and downstream eval/optimize/deploy would operate on the wrong agent.


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

## Cohesive Four Merge Campaign Notes - 2026-04-12

- Required source context read:
  - `2026-04-12-cohesive-product-hardening.md` defines the intended spine: guided operator journey, Workbench -> Eval -> Optimize handoff, restart/history continuity, and final UI language polish.
  - `workbench-harness-claude-code-audit-codex.md` emphasizes truthful Workbench semantics, durable state hydration, explicit handoff contracts, and avoiding overclaiming autonomous/resume behavior.
- Branch refs confirmed:
  - `feat/cohesive-journey-guidance-codex` -> `7414223`
  - `feat/cohesive-workbench-eval-optimize-ux-codex` -> `cdb52d4`
  - `feat/cohesive-restart-continuity-codex` -> `e90bcf2`
  - `feat/cohesive-product-polish-codex` -> `3dd1c12`
  - `origin/master` -> `2e32c26`
- Touched-file overlap:
  - Journey guidance broadly touches core pages, sidebar/layout, navigation, shared types, and adds `OperatorNextStepCard` plus `operator-journey`.
  - Workbench handoff focuses on `builder/workbench_bridge.py`, Workbench API/types/store-facing frontend, ArtifactViewer, AgentWorkbench, and Optimize.
  - Restart continuity touches backend tasks/events/eval, builder chat service, builder/chat API types, Workbench store/layout/feed, Build/EvalRuns/EventLog/Improvements.
- Product polish touches status/empty-state utilities/components and many of the same core pages/tests; likely best merged last so copy/labels normalize the combined result.

---

## Golden Path Live E2E Campaign - 2026-04-13

### Runtime Setup Findings

- Workspace mode was initially effective mock because `agentlab.yaml` has `optimizer.use_mock: true`.
- A Google provider key is present in local environment configuration, and setting workspace mode to live makes `/api/health` report `mock_mode: false`, no mock reasons, and `real_provider_configured: true`.
- The `browser-use` CLI is not installed in the workspace shell. Browser testing continues with Playwright tooling, but this is a setup gap for future operators following the requested browser-use workflow.

### Full Golden Path Probe Findings

- Build now creates the requested `FAQ Concierge` draft after the fallback fix, with SaaS FAQ tools (`search_knowledge_base`, `check_account_plan`, `create_escalation_ticket`) and routing for product FAQ, account-plan, and billing/security escalation.
- Live provider generation is reachable, but Gemini returned non-JSON text for Build config generation. The UI falls back to preview mode and should preserve the requested domain.
- Build preview can test the saved draft and then `Save & Run Eval` creates a candidate config and navigates to `/evals?agent=<id>&new=1`.
- Eval starts successfully for the saved candidate and shows a live running task.
- Workbench is not connected to the saved Build candidate. Opening `/workbench` after saving FAQ Concierge lands on demo Workbench content (`Airline Support Workbench`, M&A artifacts), so the advertised Build -> Workbench path is not truthful yet.
- Optimize can be opened with the selected saved agent, but without a completed eval run ID it still asks the operator to run eval first. The UI lets the user arrive while the eval is only running, which is understandable but not frictionless.
- Improvements and Deploy are reachable. Deploy lists the newly saved candidate version, but it does not carry the candidate selection from Build/Eval into the deploy form.

### Fixes Applied

- Added a SaaS FAQ support fallback shape for Build generation when live provider output is invalid JSON or unavailable.
- Added explicit leading-name extraction so prompts like `Build FAQ Concierge, ...` preserve the requested agent name.
- Added a regression test proving invalid live JSON preserves the SaaS FAQ domain instead of drifting into finance.
- Fixed the Build -> Eval handoff so saved Build drafts pass the generated eval cases path into `/evals` and `/api/eval/run`.
- Extended explicit dataset loading to accept Build-generated `.yaml` / `.yml` eval files, not only JSONL/CSV.
- Added UI evidence in Eval Runs showing the generated Build eval path before the first run starts.
- Verified live Eval now runs the 3-case `generated_build.yaml` suite for `FAQ Concierge` instead of launching the broad 55-case default suite.
- Added a Build -> Workbench handoff. Saved Build candidates now expose `Continue to Workbench`, and Workbench can start a fresh candidate materialization from the carried agent/config context instead of reopening the demo project.
- Added a hydration gate in Workbench so an incoming Build handoff does not get overwritten by the final default-project snapshot.

### Remaining Product Gaps

- Optimize still needs the completed eval run ID carried explicitly. Eval Runs has an `Optimize` CTA when the run completes, but opening `/optimize?agent=<id>` directly still asks for eval evidence.
- Deploy lists candidate versions, including the newly saved candidate, but `/deploy?new=1` does not preselect the candidate carried from Build/Eval.
- `browser-use` remains missing from the shell; Playwright is the verified browser path for this session.
- Build live provider output can still fail JSON parsing. The fallback is now domain-preserving, but the live prompt/JSON contract needs hardening so fallback is not the normal path.

### Latest Verification Evidence

- `.venv/bin/python -m pytest tests/test_eval_pipeline.py tests/test_transcript_intelligence_service.py tests/test_builder_chat_api.py -q`: 28 passed.
- `npm test -- src/pages/EvalRuns.test.tsx src/pages/Build.test.tsx src/pages/AgentWorkbench.test.tsx`: 43 passed.
- `npm run build`: passed; Vite still reports the existing large main chunk warning.
- Playwright full golden path probe confirmed the Eval POST body included `dataset_path: /Users/andrew/Desktop/agentlab/evals/cases/generated_build.yaml` and the backend completed a 3-case generated-build run.
- Playwright Workbench handoff probe confirmed `/workbench?agent=...&agentName=FAQ+Concierge&configPath=...` displays `Continuing from Build` and POSTs `/api/workbench/build/stream` with `project_id: null`.

## Greenhouse Guide Live Hardening Pass - 2026-04-13

### Mission

- Test the simple-mode UI journey end to end with a concrete lawn and garden store chat agent.
- Use live mode with `GOOGLE_API_KEY from local .env`.
- Keep Pro mode out of scope.
- Fix the highest-impact friction that prevents a non-expert user from moving through Build, Workbench, Eval, Optimize, Improvements, and Deploy without guessing.

### Initial Findings

- The current branch is `feat/golden-path-faq-bot-ralph`.
- `browser-use` is still unavailable in the shell; Playwright and Chrome MCP are available.
- Literal provider-key-looking strings were present in `PLAN.md` and `PROMPT.md`; they were redacted before live testing.

### Build

- Issue: generating `Greenhouse Guide` from `/build` produced a candidate named correctly but configured as a healthcare assistant.
- Page / action: `/build` -> fill Agent description with a lawn and garden store website chat agent prompt -> Generate Agent -> inspect generated configuration.
- Observed behavior: system prompt referenced healthcare, tools included appointment and patient lookups, and policies included HIPAA/clinical advice guardrails.
- Expected behavior: the candidate should stay in the lawn/garden retail domain with plant care, planting plans, delivery, returns, and escalation handling.
- Severity: critical, because the first golden-path artifact carries the wrong domain into Workbench, Evals, Optimize, and Deploy.
- Suspected root cause: fallback domain detection had healthcare keywords but no lawn/garden retail guard, so negative safety phrasing such as avoiding medical claims could pull the fallback into the wrong domain.
- Fix owner: Codex.
- Verification evidence: added and passed `test_generate_agent_config_fallback_keeps_lawn_garden_prompt_out_of_healthcare_domain`; full `tests/test_transcript_intelligence_service.py` passed.

- Issue: live Build preview failure is framed as mock/missing-key recovery even when health reports live provider readiness.
- Page / action: `/build` -> generate Greenhouse Guide -> `Test Agent` preview.
- Observed behavior: `/api/intelligence/preview-agent` returned `mock_mode: true` with a provider `HTTP Error 403: Forbidden`; the UI copy said live preview was not ready and suggested adding API keys.
- Expected behavior: if live mode is configured but the provider rejects the call, the UI should say the provider request failed and preserve the live-mode diagnostic without implying local key setup is missing.
- Severity: medium, because it does not block saving but undermines operator trust during live testing.
- Suspected root cause: preview fallback copy collapses all provider failures into the same no-key/mock recovery path.
- Fix owner: future UX/API polish unless it blocks final verification.
- Verification evidence: browser network inspection during the Greenhouse Guide Build pass.

### Workbench

- Issue: the Workbench operator journey card dropped candidate context by linking to bare `/evals?new=1`.
- Page / action: `/workbench` opened from saved Greenhouse Guide Build candidate -> wait for materialization -> inspect journey card.
- Observed behavior: the lower Workbench handoff button could save/open Eval with agent and config context, but the main journey card still sent users to an unscoped Eval page.
- Expected behavior: the page-level next step should use the Workbench handoff action so users do not have to infer which Eval agent/config belongs to the candidate.
- Severity: high, because the most prominent CTA can lose the golden-path context.
- Suspected root cause: `getWorkbenchJourneySummary` only knew local build readiness and did not use the typed Workbench bridge state.
- Fix owner: Codex.
- Verification evidence: `web/src/pages/AgentWorkbench.test.tsx` now passes with the handoff context assertions.

- Issue: Workbench -> Eval omitted the generated eval cases path.
- Page / action: `/workbench` -> `Save candidate and open Eval`.
- Observed behavior: navigation carried `agent`, `projectId`, `runId`, and `configPath`, but not `evalCasesPath`; Eval would therefore not send `dataset_path` for this Workbench-generated candidate.
- Expected behavior: `/evals?agent=<id>&new=1&evalCasesPath=<path>` and the navigation state both preserve the generated dataset path.
- Severity: high, because Optimize evidence depends on evaluating the exact generated candidate cases.
- Suspected root cause: the bridge endpoint returned `eval_cases_path` in `save_result`, but the evaluation request did not default `dataset_path` to that file and the frontend did not copy it into the route.
- Fix owner: Codex.
- Verification evidence: backend bridge regression asserts `dataset_path == save_result["eval_cases_path"]`; frontend test asserts `evalCasesPath` is present in the route and state.

- Issue: the first Workbench harness guardrail for Greenhouse Guide could be generic PII instead of the domain-specific pesticide/medical safety guardrail.
- Page / action: `/workbench` materialization after Build handoff -> inspect generated guardrail artifact.
- Observed behavior: the correct garden domain and tools were present, but the first guardrail artifact could still be `PII Protection`.
- Expected behavior: lawn/garden store briefs should prioritize `No Unsupported Pesticide or Medical Claims` because that is the key risk named in the user prompt.
- Severity: medium, because a later guardrail could still exist, but the first artifact shapes user trust and review focus.
- Suspected root cause: `_select_next_guardrail` appended domain-specific guardrails after generic PII/internal-code entries.
- Fix owner: Codex.
- Verification evidence: added and passed `test_select_next_guardrail_prioritizes_lawn_garden_safety`.

### Eval

- Issue: Eval -> Optimize CTA did not include the selected config path.
- Page / action: `/evals` from Workbench candidate -> complete run -> inspect Optimize CTA.
- Observed behavior: the journey link included `agent` and `evalRunId`, but not `configPath`.
- Expected behavior: `/optimize?agent=<id>&evalRunId=<run-id>&configPath=<path>` so Optimize cannot accidentally drift to a different saved candidate.
- Severity: high, because Optimize must operate on the candidate that produced the completed eval evidence.
- Suspected root cause: Eval completion state tracked run ID and agent, but the summary link only serialized the agent ID and run ID.
- Fix owner: Codex.
- Verification evidence: `web/src/pages/EvalRuns.test.tsx` now asserts the Optimize handoff includes `configPath`.

- Issue: the current strict-live Greenhouse Guide eval run failed because the live provider returned `HTTP Error 403: Forbidden`.
- Page / action: `/evals?source=workbench&new=1&agent=agent-v015&configPath=...&evalCasesPath=...` -> `Start Eval`.
- Observed behavior: the Eval request correctly posted the generated dataset path, then the backend marked the task failed with strict-live fallback refused.
- Expected behavior: strict live mode should not silently accept mock success; the UI should make the provider failure and next recovery step obvious.
- Severity: high for live validation, because it blocked completing the fresh Greenhouse run through Eval in this session.
- Suspected root cause: provider authorization/quota behavior outside the UI flow, plus limited failed-run recovery guidance in the Eval UI.
- Fix owner: Codex for UI recovery polish; provider owner for credential/quota.
- Verification evidence: Chrome network request body included `{"config_path":"configs/v015.yaml","require_live":true,"dataset_path":"/Users/andrew/Desktop/agentlab/evals/cases/generated_build.yaml","split":"all"}` and the failed run reported provider `HTTP Error 403: Forbidden`.

### Workbench Reopen

- Issue: URL-only Workbench handoffs could still drop the saved Build context after refresh or direct open.
- Page / action: `/workbench?agent=agent-v014&agentName=Greenhouse+Guide&configPath=...` -> wait for automatic materialization.
- Observed behavior: before the fix, Workbench created a generic `Agent` with `agent_lookup` rather than the saved lawn/garden candidate.
- Expected behavior: the saved config path should let Workbench recover the original Build prompt and materialize the same candidate domain.
- Severity: high, because users can naturally refresh or copy the handoff URL and lose the candidate without knowing why.
- Suspected root cause: the frontend passed only a vague continuation brief and the backend did not accept/read `config_path` during stream materialization.
- Fix owner: Codex.
- Verification evidence: browser retry showed `Greenhouse Guide Workbench`, `Lawn and Garden Support Agent`, `garden_catalog_search`, `plant_care_guide_lookup.py`, tomato/pesticide evals, and `No Unsupported Pesticide or Medical Claims`.

### Optimize

- Issue: the fresh Greenhouse optimization cycle ended as a no-op instead of creating a reviewable proposal.
- Page / action: `/optimize?agent=agent-v015&evalRunId=1a68f28c-10f&configPath=...` -> start optimization with human approval required.
- Observed behavior: `/api/optimize/run` posted the carried `eval_run_id` and config path, then the task completed as `REJECTED (rejected_noop): Proposal did not change config (mode=standard)`.
- Expected behavior: if the UI offers an improvement cycle, users should either receive a concrete proposal in Review or a clear explanation with a one-click recovery path.
- Severity: medium, because the evidence contract is now correct but the review stage can still feel like a dead end.
- Suspected root cause: the current standard optimizer can produce an unchanged proposal for this candidate/eval pair.
- Fix owner: future Optimize/Review polish.
- Verification evidence: Chrome network request body included `eval_run_id: "1a68f28c-10f"`, `config_path: "configs/v015.yaml"`, and `require_human_approval: true`.

### Improvements

- Issue: the Greenhouse pass could not validate a fresh approve/reject proposal because Optimize produced a rejected no-op.
- Page / action: optimize completion -> `/improvements?tab=review`.
- Observed behavior: no new review item was available for the current Greenhouse optimization cycle.
- Expected behavior: approved optimization output should flow into Review with an obvious next step to Deploy.
- Severity: medium, because it is the only unverified stage in the simple-mode golden path after this pass.
- Suspected root cause: upstream no-op optimize result prevented review artifact creation.
- Fix owner: future Optimize/Improvements owner.
- Verification evidence: route remains reachable, but no Greenhouse proposal was generated in this live cycle.

### Deploy

- Issue: Deploy did not preselect a carried candidate version from the route.
- Page / action: `/deploy?new=1&version=v015&from=optimize`.
- Observed behavior: before the fix, the deploy form opened with `Select version`, forcing the user to infer the intended candidate from the version list.
- Expected behavior: Deploy should preselect the carried candidate/canary version and show the canary state before promotion.
- Severity: high, because deploying the wrong candidate is a costly golden-path error.
- Suspected root cause: the Deploy page ignored `version` query params while opening the `new=1` form.
- Fix owner: Codex.
- Verification evidence: browser retry showed v15 selected; Chrome network inspection confirmed `/api/deploy` posted `{"version":15,"strategy":"canary"}` and `/api/deploy/promote` posted `{"version":15}` after the UI showed canary state.

### Remaining UX Gaps

- Fixed in this pass: Workbench streamed text could concatenate words in the conversation feed, for example `Lawnand`, `I'llstart`, and `Definerole`. Frontend streaming and backend persistence now insert a space when word-boundary chunks omit leading whitespace, while preserving punctuation and contractions.
- Repeated saves create multiple `Greenhouse Guide` entries in Eval agent selection. The correct candidate can be selected by carried route state, but the library list is visually noisy.
- Build preview provider errors still use mock/missing-key framing even when `/api/health` reports live provider readiness.
- A focused Playwright regression now pins the Greenhouse Guide Workbench -> Eval -> Optimize -> Deploy handoff contracts in `web/tests/greenhouse-guide-contracts.spec.ts`, but the CLI browser runner still cannot launch Chromium in this environment.

### Verification Blockers

- `cd web && PLAYWRIGHT_BASE_URL=http://127.0.0.1:5173 npx playwright test tests/operator-main-journey.spec.ts tests/live-golden-path.spec.ts --workers=1` did not reach the app. Chromium headless shell failed at launch with macOS MachPort rendezvous `Permission denied (1100)`. Manual Chrome MCP testing remains the browser evidence for this pass.
- Added `web/tests/greenhouse-guide-contracts.spec.ts` for mocked regression coverage of the carried `evalCasesPath`, `dataset_path`, `eval_run_id`, and deploy `version` contracts. `npx playwright test tests/greenhouse-guide-contracts.spec.ts --list` passed, but browser execution is subject to the same local Chromium launch blocker.
- `cd web && PLAYWRIGHT_BASE_URL=http://127.0.0.1:5173 npx playwright test tests/greenhouse-guide-contracts.spec.ts --workers=1` hit the same Chromium launch failure before assertions could run.
