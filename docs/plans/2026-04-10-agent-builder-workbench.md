# Agent Builder Workbench Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a two-pane Agent Builder Workbench where users describe and iteratively change an agent on the left, while inspecting the canonical spec, generated source/config, evals, traces, live tests, and deployment state on the right.

**Architecture:** Add Workbench as a new Build-family route backed by the existing Builder Workspace project/session/task/proposal/artifact/event substrate, then introduce a canonical `AgentProjectSpec` model and compiler layer that can project to AgentLab runtime config, Google ADK artifacts, and CX Agent Studio export surfaces.

**Tech Stack:** FastAPI, Python dataclasses/Pydantic, SQLite-backed builder stores, existing ADK/CX/import/export/eval/trace/deploy services, React, TypeScript, TanStack Query, existing builder UI components.

## Executive Recommendation

Ship Workbench as a new route/surface first, then graduate it into the default Build experience after it proves stable.

Recommended route:

- Add `/workbench` or `/build/workbench` as a new full-width IDE surface under the Build navigation group.
- Keep `/build` as the current lightweight Build surface with prompt, transcript, builder chat, saved artifacts, preview, save, and eval handoff.
- Share all durable backend objects with the existing Builder Workspace rather than creating a separate product island.
- Treat the existing `BuilderChatService` and `BuilderConfigDraft` as compatibility layers, not as the long-term canonical model.

Rationale:

- The PRD asks for an IDE-like surface with a 35-40 percent conversation pane, a 60-65 percent inspector pane, many right-side tabs, target modes, source previews, test sessions, deploy state, rollback, and activity diffs. That is larger than the current `/build` tab model.
- Current `/build` is already the canonical entry for the Build -> Eval -> Optimize -> Improvements -> Deploy journey. Replacing it immediately risks regressions in a recently improved path.
- The repo already contains a stronger Builder Workspace substrate with `BuilderProject`, `BuilderSession`, `BuilderTask`, `BuilderProposal`, `ArtifactRef`, `ApprovalRequest`, `EvalBundle`, `TraceBookmark`, `ReleaseCandidate`, SSE events, permissions, specialist routing, and task execution. Workbench should activate that substrate.
- The current Build chat payload is intentionally narrow. The Workbench needs a richer canonical model that includes agents, sub-agents, tools, callbacks, variables, guardrails, eval suites, environments, deployment targets, generated outputs, validations, sessions, and events.

## Current Architecture Inventory

| Product area | Existing code | Reuse for Workbench | Gap to close |
| --- | --- | --- | --- |
| Current Build route | `web/src/pages/Build.tsx`, `web/src/lib/builder-chat-api.ts`, `builder/chat_service.py`, `builder/chat_types.py`, `/api/builder/chat`, `/api/builder/preview`, `/api/builder/export`, `/api/builder/save` | Keep as compatibility/on-ramp, reuse preview/save/eval handoff patterns, reuse tests for regression coverage | Current config is too narrow and chat mutates state immediately instead of producing a visible plan before apply |
| Builder Workspace backend | `builder/types.py`, `builder/store.py`, `builder/projects.py`, `builder/execution.py`, `builder/events.py`, `builder/orchestrator.py`, `builder/permissions.py`, `builder/metrics.py`, `builder/artifacts.py`, `/api/builder/projects`, `/sessions`, `/tasks`, `/proposals`, `/artifacts`, `/approvals`, `/events`, `/events/stream`, `/metrics`, `/specialists` | Use as the durable project/session/task/proposal/artifact/event spine | Add first-class canonical agent spec storage, mutation plans, validation runs, compiler outputs, and Workbench-specific API wrappers |
| Builder UI components | `web/src/components/builder/TopBar.tsx`, `ConversationPane.tsx`, `Composer.tsx`, `TaskDrawer.tsx`, `Inspector.tsx`, cards and widgets | Use for shell, left pane, plan/progress cards, approvals, task drawer, specialist/progress affordances | Current inspector tabs are not the PRD tabs and some content is mock/static |
| Agent Library and build artifacts | `api/routes/agents.py`, `shared/build_artifact_store.py`, `shared/contracts/build_artifact.py`, `builder/workspace_config.py` | Use for saving a compiled candidate to the existing journey and selecting active agents | Add canonical-spec source metadata, spec version lineage, and runtime-config compilation from Workbench specs |
| ADK import/export/runtime | `adk/types.py`, `adk/mapper.py`, `adk/exporter.py`, `adk/scaffold.py`, `adk/runtime.py`, `adk/session.py`, `api/routes/adk.py` | Reuse ADK agent tree/tool/callback/session types, scaffold/export/deploy routes, export matrices | Add canonical-spec-to-ADK compiler and source bundle preview without relying on arbitrary user source edits |
| CX Studio/import/export/deploy | `cx_studio/types.py`, `adapters/cx_agent_mapper.py`, `cx_studio/exporter.py`, `cx_studio/deployer.py`, `api/routes/cx_studio.py` | Reuse editable CX workspace, CX tool/deploy enums, import/export/preflight/deploy/promote/rollback paths | Add canonical-spec-to-CX compiler and compatibility annotations for CX-only/portable/blocked features |
| Portability/readiness | `portability/types.py`, ADK/CX portability helpers | Use `PortabilityReport`, `PortabilitySurface`, `ExportCapabilityMatrix`, and projection quality statuses for compatibility badges | Add Workbench-level target compatibility labels across tools, callbacks, guardrails, evals, and deployment targets |
| Evals | `api/routes/eval.py`, `api/routes/generated_evals.py`, `evals/auto_generator.py`, `EvalRuns.tsx`, `EvalGenerator.tsx`, `ResultsExplorer.tsx`, `Compare.tsx` | Reuse scenario/golden generation and run APIs, active agent handoff, result browsing, compare | Workbench needs inline eval status, spec-linked generated suites, and "always test after change" orchestration |
| Traces | `api/routes/traces.py`, `observer/traces.py`, `web/src/pages/Traces.tsx`, `TraceTimeline.tsx`, `TraceBookmark` | Reuse trace store, timeline, bookmarks, eval promotion patterns | Expand frontend trace event typing and attach test-live/build events to Workbench tasks and spec versions |
| Optimize/Improvements | `Optimize.tsx`, `Improvements.tsx`, `api/routes/optimize.py`, improvements/opportunities APIs | Reuse downstream journey once a Workbench candidate is saved to Agent Library | Add clear handoff from Workbench eval results to Optimize and Improvements rather than embedding optimizer logic in MVP |
| Deploy | `Deploy.tsx`, `AdkDeploy.tsx`, `CxDeploy.tsx`, `api/routes/deploy.py`, `api/routes/adk.py`, `api/routes/cx_studio.py`, `deployer/*` | Reuse version/canary/rollback plus ADK/CX target flows | Workbench Deploy tab should embed/compose target panels and release-candidate state, not duplicate deploy services |

## PRD Primitive Mapping

| PRD primitive | Existing AgentLab primitive | Implementation direction |
| --- | --- | --- |
| Conversation on the left | `BuilderChatWorkspace`, `ConversationPane`, `Composer`, `BuilderSession` | Use `ConversationPane` and `Composer` for Workbench; keep current Build chat UI separate during rollout |
| Visible change plan before apply | `BuilderProposal`, `PlanCard`, `ArtifactCardFactory.create_plan_card` | Add planner output as proposal plus JSON-patch mutation preview; apply only after approval or Apply mode confirmation |
| Build/apply/test progress cards | `BuilderTask`, `BuilderExecutionEngine`, `BuilderEvent`, task drawer/cards | Emit task progress and validation events through existing SSE broker |
| Version/change history | `ReleaseCandidate`, artifact source versions, build artifact versions | Add spec version snapshots and activity/diff tab; link release candidates to spec versions |
| Target mode ADK/CX/Hybrid | ADK/CX routes, portability reports | Add `target_mode` to canonical spec and show portability badges across right-side tabs |
| Agent card | Current raw config modal, `CodingAgentConfigTab` | Add structured canonical-spec editor with generated API/config subpanel |
| Source code | ADK scaffold/export, CX export bundle | Add generated source tree tab from compiler outputs; limit editing to tool/callback code blocks in MVP |
| Tools | Current draft tools, ADK/CX tool types, builder ToolsTab | Add canonical `ToolSpec` registry with input/output schema, auth, tests, compatibility, last-run status |
| Callbacks | `AdkCallbackSpec`, CX editable callbacks/hooks concept, portability callbacks | Add canonical `CallbackSpec` and target lifecycle mapping |
| Guardrails | Builder guardrail artifacts, portability surfaces | Add canonical `GuardrailSpec` and policy builder; classify support by target |
| Evals | Generated eval suites, eval runs, eval bundles | Add spec-linked scenario/golden suites and inline run/review state |
| Trace | `TraceStore`, `TraceTimeline`, `TraceBookmark`, builder events | Add event timeline for test-live and builder mutation events; preserve links to full Trace page |
| Test Live | Builder preview, eval runtime preview, ADK session primitives | Add inline session runner backed by compiled runtime config first; later add ADK/CX-specific sessions |
| Deploy | Agent Library save, deploy routes, ADK/CX deploy pages | Add deploy tab that creates release candidates and delegates to existing deploy services |

## Functional Requirement Coverage

The PRD references FR-1 through FR-10 but the supplied excerpt summarizes them rather than listing exact text. This plan treats the following as the build contract and maps each one to a vertical slice.

| Requirement | Workbench contract | Primary tickets |
| --- | --- | --- |
| FR-1: Create an agent from a plain-English brief | A user can create `AgentProjectSpec` from a brief or existing Build chat session | WB-BE-1, WB-BE-2, WB-BE-3, WB-FE-1, WB-FE-2 |
| FR-2: Plan before applying changes | Every mutating request produces interpretation, planned mutations, impacted surfaces, validation plan, and proposal card before mutation | WB-BE-4, WB-BE-5, WB-FE-3 |
| FR-3: Keep one canonical source of truth | `AgentProjectSpec` is persisted/versioned and compiles outward to generated outputs | WB-BE-1, WB-BE-2, WB-COMP-1, WB-COMP-4 |
| FR-4: Keep preview/config/source/evals/deploy in sync | Apply runs compile plus validation and refreshes right-pane tabs from generated outputs | WB-BE-5, WB-COMP-4, WB-EVAL-2, WB-FE-4 |
| FR-5: Support structured agent inspection | Agent Card, Tools, Callbacks, Guardrails, Source Code, Activity/Diff tabs render canonical spec surfaces | WB-FE-4, WB-BE-1 |
| FR-6: Support ADK, CX, and Hybrid target modes | Compiler adapters project the canonical model to ADK and CX with compatibility/readiness labels | WB-COMP-2, WB-COMP-3, WB-COMP-4 |
| FR-7: Support eval generation and execution | Scenario/golden suites are linked to specs, accepted through existing generated eval flow, and run through existing eval runner | WB-EVAL-1, WB-EVAL-2 |
| FR-8: Support trace and event inspection | Builder events, preview/test-live traces, eval traces, and trace bookmarks link back to spec activity | WB-TRACE-1, WB-FE-4 |
| FR-9: Support deployment and rollback | Deploy tab creates release candidates, delegates to existing target deploy services, and rolls back spec versions | WB-BE-2, WB-BE-5, WB-FE-4, WB-ROLL-2 |
| FR-10: Preserve downstream journey integration | Workbench-originated agents can enter Agent Library, Eval Runs, Optimize, Improvements, and Deploy with lineage intact | WB-ROLL-2, WB-QA-1 |

## Route and Surface Decision

| Option | Benefit | Cost | Recommendation |
| --- | --- | --- | --- |
| Add `/build?tab=workbench` | Keeps one Build URL and uses existing Build route ownership | The current tab layout and content width fight the IDE layout; high regression risk in current Build journey | Acceptable later, not first |
| Add `/workbench` or `/build/workbench` | Gives the IDE a full-height/full-width layout, allows phased adoption, keeps `/build` stable | Adds another Build-family surface that navigation must explain | Recommended for MVP |
| Replace `/build` immediately | Product clarity: one builder | High risk: current Build/Eval handoff and tests are stable and recently improved | Do not do this for MVP |

Implementation recommendation:

1. Add `AgentWorkbench.tsx` as a new route.
2. Add "Workbench" under the Build navigation group.
3. Preserve legacy redirects to `/build?tab=builder-chat`.
4. Add an affordance inside current Build to "Open in Workbench" once a builder chat session has a generated config.
5. After MVP hardening, consider making Workbench the default `/build` route and moving the old Build flow behind `/build/simple`.

## Canonical Data Model

The canonical model should be a new first-class object, not the existing `BuilderProject` and not the current `BuilderConfigDraft`.

Model roles:

- `BuilderProject`: workspace shell. Owns root path, project instructions, inherited knowledge, skill defaults, permission defaults, preferred models, and deployment target defaults.
- `BuilderSession`: conversation container. Owns messages/tasks/proposals in one interactive run.
- `AgentProjectSpec`: canonical agent truth. Owns the structured agent model that compiles to AgentLab runtime config, ADK, and CX.
- `BuildArtifact`: saved candidate for the existing Agent Library and Build -> Eval journey.
- `ReleaseCandidate`: deployable version linked to spec version, eval bundle, generated outputs, and target.

Recommended Python module:

- Add `builder/agent_model.py` for Pydantic models and validation helpers.
- Add `builder/agent_model_store.py` or extend `BuilderStore` with a `builder_agent_specs` table.
- Add `web/src/lib/workbench-types.ts` as the frontend mirror.

Recommended top-level shape:

```python
class AgentProjectSpec(BaseModel):
    spec_id: str
    project_id: str
    active_session_id: str | None = None
    draft_id: str
    version: int
    status: Literal["draft", "valid", "invalid", "released", "archived"]
    target_mode: Literal["adk", "cx", "hybrid"]
    metadata: AgentMetadata
    root_agent: AgentSpec
    sub_agents: list[AgentSpec] = []
    tools: list[ToolSpec] = []
    callbacks: list[CallbackSpec] = []
    variables: list[VariableSpec] = []
    guardrails: list[GuardrailSpec] = []
    eval_suites: list[EvalSuiteSpec] = []
    environments: list[EnvironmentSpec] = []
    deployment_targets: list[DeploymentTargetSpec] = []
    generated_outputs: GeneratedOutputBundle = GeneratedOutputBundle()
    validation: ValidationSummary = ValidationSummary()
    activity: list[SpecActivityEntry] = []
    lineage: SpecLineage = SpecLineage()
    portability: PortabilityReport | None = None
```

Required child models:

- `AgentMetadata`: `name`, `display_name`, `description`, `owner`, `tags`, `created_at`, `updated_at`.
- `AgentSpec`: `agent_id`, `name`, `description`, `role`, `instruction`, `model`, `generation_config`, `orchestration_type`, `tool_ids`, `callback_ids`, `variable_bindings`, `guardrail_ids`, `sub_agent_ids`, `target_overrides`, `compatibility`.
- `ToolSpec`: `tool_id`, `name`, `description`, `kind`, `target_compatibility`, `input_schema`, `output_schema`, `auth`, `implementation`, `endpoint`, `test_cases`, `last_run`, `source_refs`.
- `CallbackSpec`: `callback_id`, `name`, `lifecycle`, `description`, `code`, `target_compatibility`, `source_refs`.
- `VariableSpec`: `variable_id`, `key`, `source`, `default`, `required`, `scope`.
- `GuardrailSpec`: `guardrail_id`, `name`, `description`, `category`, `rules`, `actions`, `target_compatibility`, `default_enabled`.
- `EvalSuiteSpec`: `suite_id`, `name`, `kind` as `scenario` or `golden`, `cases`, `generated_suite_id`, `last_run_id`, `status`.
- `EnvironmentSpec`: `environment_id`, `name`, `target`, `variables`, `secrets_refs`, `session_config`, `runtime_options`.
- `DeploymentTargetSpec`: `target_id`, `kind`, `environment_id`, `status`, `config`, `last_release_id`.
- `GeneratedOutputBundle`: `agentlab_runtime_config`, `adk_project_tree`, `cx_editable_workspace`, `source_files`, `export_matrix`, `warnings`.
- `ValidationSummary`: `schema`, `compiler`, `preview_smoke`, `evals`, `trace`, `last_validated_at`.
- `SpecActivityEntry`: `activity_id`, `task_id`, `proposal_id`, `mutation_ids`, `summary`, `diff`, `validation_result`, `created_at`.
- `SpecLineage`: `created_from`, `source_config_path`, `build_artifact_id`, `parent_spec_version`, `builder_chat_session_id`.

Compatibility model:

```python
class TargetCompatibility(BaseModel):
    portable: bool
    adk: Literal["ready", "lossy", "blocked"]
    cx: Literal["ready", "lossy", "blocked"]
    notes: list[str] = []
    portability_surface_ids: list[str] = []
```

Mutation model:

- Use JSON Patch style operations (`add`, `replace`, `remove`, `move`, `copy`, `test`) for deterministic application.
- Wrap operations in a `SpecMutationPlan` with interpretation, assumptions, impacted surfaces, validation plan, risk level, and rollback metadata.
- Store the plan as a `BuilderProposal` and optionally as an `ArtifactRef` of type `plan`.
- Store applied mutations in `AgentProjectSpec.activity`.

Important boundary:

- MVP should not reverse-compile arbitrary edited source back into `AgentProjectSpec`.
- Source Code tab can allow limited tool/callback code editing because those code blocks map to explicit fields. Everything else should be generated/read-only.

## Backend and Orchestration Architecture

Add six internal services around existing primitives.

### 1. Interpreter

Suggested module: `builder/workbench_interpreter.py`

Responsibilities:

- Turn a user request plus current spec context into a structured interpretation.
- Identify whether the user is asking, planning, applying, testing, exporting, or deploying.
- Produce confidence, assumptions, target surfaces, and missing context.

Reuse:

- Current `BuilderChatService` prompt/refinement machinery can be used as a bridge.
- Existing specialist roles can inform routing: requirements analyst, ADK architect, tool engineer, guardrail author, eval author, trace analyst, release manager.

### 2. Planner

Suggested module: `builder/workbench_planner.py`

Responsibilities:

- Convert interpretation into a `SpecMutationPlan`.
- Populate `BuilderProposal` with human-readable plan details.
- Emit planned JSON Patch operations against `AgentProjectSpec`.
- Estimate risk and required approvals.

Reuse:

- `BuilderProposal`, `RiskLevel`, `ApprovalRequest`, `ArtifactCardFactory.create_plan_card`, `PlanCard`.

### 3. Canonical Model Store

Suggested module: `builder/agent_model_store.py`

Responsibilities:

- Persist spec snapshots and active draft pointers.
- Query current spec by project/session/spec ID.
- Record activity entries, validation summaries, and generated output metadata.
- Support rollback to a prior spec version.

Storage recommendation:

- Add `builder_agent_specs` SQLite table with indexed `spec_id`, `project_id`, `draft_id`, `version`, `status`, `updated_at`, and JSON `payload`.
- Keep generated large source bundles as artifacts or files referenced from the spec, not giant inline blobs if they grow.
- Add `ArtifactType.AGENT_SPEC` or `ArtifactType.CANONICAL_SPEC` only if the UI needs card rendering; the source of truth should still be the spec store.

### 4. Compiler Layer

Suggested package: `builder/compiler/`

Responsibilities:

- Validate and normalize `AgentProjectSpec`.
- Compile to AgentLab runtime config for preview, save, eval, optimize, and deploy.
- Compile to ADK source tree and export matrix.
- Compile to CX editable workspace/export bundle and export matrix.
- Produce compatibility warnings and structured generated outputs.

Reuse:

- `builder/workspace_config.py` for existing runtime config mapping patterns.
- `adk/scaffold.py`, `adk/types.py`, `adk/mapper.py`, `adk/exporter.py`.
- `cx_studio/types.py`, `adapters/cx_agent_mapper.py`, `cx_studio/exporter.py`.
- `portability/types.py`.

### 5. Validator / Test Runner

Suggested module: `builder/workbench_validator.py`

Responsibilities:

- Run schema validation after every planned/apply action.
- Run compile validation for all selected target modes.
- Run preview smoke tests against the AgentLab runtime config.
- Run generated or attached eval suites when available.
- Attach trace IDs, eval bundle IDs, and validation result summaries to the spec activity and builder task.

Reuse:

- `/api/builder/preview`, `preview_generated_config`.
- `/api/evals/generate`, `/api/eval/run`, generated eval store.
- `EvalBundle`, `TraceBookmark`, `TraceStore`.

### 6. Deployment Adapter Layer

Suggested package: `builder/deployment_adapters/`

Responsibilities:

- Convert spec version plus compiler outputs into target-specific deploy requests.
- Create/update `ReleaseCandidate`.
- Delegate deploy execution to existing AgentLab, ADK, and CX deploy routes/services.
- Record rollback metadata and deploy activity.

Reuse:

- `deployer/release_manager.py`, `deployer/versioning.py`, `api/routes/deploy.py`.
- `api/routes/adk.py`, `adk/deployer.py`, `adk/vertex_engine.py`.
- `api/routes/cx_studio.py`, `cx_studio/deployer.py`.

## API Design

Keep existing `/api/builder/*` routes and add Workbench routes under the same namespace.

Recommended endpoints:

- `POST /api/builder/workbench/projects/{project_id}/specs`: create a spec from a plain-English brief or current builder session.
- `GET /api/builder/workbench/specs/{spec_id}`: fetch current spec, generated outputs, validation summary, and activity.
- `POST /api/builder/workbench/specs/{spec_id}/interpret`: return interpretation only.
- `POST /api/builder/workbench/specs/{spec_id}/plan`: create `BuilderTask` + `BuilderProposal` + mutation plan; do not mutate.
- `POST /api/builder/workbench/specs/{spec_id}/apply`: apply an approved proposal or direct apply-mode request, then validate/compile.
- `POST /api/builder/workbench/specs/{spec_id}/validate`: run schema/compiler/smoke/eval checks.
- `POST /api/builder/workbench/specs/{spec_id}/compile`: compile to `agentlab`, `adk`, `cx`, or `all`.
- `POST /api/builder/workbench/specs/{spec_id}/preview`: run inline test-live preview against compiled runtime config.
- `POST /api/builder/workbench/specs/{spec_id}/evals/generate`: generate scenario/golden eval suites linked to the spec.
- `POST /api/builder/workbench/specs/{spec_id}/evals/run`: run linked eval suite.
- `POST /api/builder/workbench/specs/{spec_id}/save-agent`: save compiled AgentLab runtime config to Agent Library.
- `POST /api/builder/workbench/specs/{spec_id}/release-candidates`: create a release candidate.
- `POST /api/builder/workbench/specs/{spec_id}/rollback`: restore a prior spec version.

API response pattern:

- Return `spec`, `task`, `proposal`, `artifacts`, `validation`, `generated_outputs`, and `events_cursor` where relevant.
- Emit events through the existing `/api/builder/events/stream`.
- Keep route payloads typed with Pydantic request/response models; avoid free-form dictionaries at the boundary except for target-specific preserved raw resources.

## Frontend Architecture

Add a new page and small Workbench-specific component layer while reusing builder cards/widgets.

Suggested files:

- `web/src/pages/AgentWorkbench.tsx`
- `web/src/lib/workbench-api.ts`
- `web/src/lib/workbench-types.ts`
- `web/src/components/workbench/WorkbenchShell.tsx`
- `web/src/components/workbench/WorkbenchTopBar.tsx`
- `web/src/components/workbench/WorkbenchLeftPane.tsx`
- `web/src/components/workbench/WorkbenchRightPane.tsx`
- `web/src/components/workbench/tabs/PreviewTab.tsx`
- `web/src/components/workbench/tabs/AgentCardTab.tsx`
- `web/src/components/workbench/tabs/SourceCodeTab.tsx`
- `web/src/components/workbench/tabs/ToolsTab.tsx`
- `web/src/components/workbench/tabs/CallbacksTab.tsx`
- `web/src/components/workbench/tabs/GuardrailsTab.tsx`
- `web/src/components/workbench/tabs/EvalsTab.tsx`
- `web/src/components/workbench/tabs/TraceTab.tsx`
- `web/src/components/workbench/tabs/TestLiveTab.tsx`
- `web/src/components/workbench/tabs/DeployTab.tsx`
- `web/src/components/workbench/tabs/ActivityDiffTab.tsx`

Reuse:

- `TopBar` concepts for project selector, env selector, mode selector, approvals, and pause/resume.
- `ConversationPane`, `Composer`, `TaskDrawer`, `PlanCard`, `SourceDiffCard`, `ADKGraphDiffCard`, `EvalCard`, `GuardrailCard`, `TraceEvidenceCard`, `ReleaseCard`.
- `EvalGenerator`, generated eval review components, `TraceTimeline`, deploy panels where feasible.
- Existing `AgentSelector`/active-agent store for downstream handoff once a Workbench draft is saved.

Right pane tabs for MVP:

1. `Preview`: compiled runtime preview with desktop/mobile toggle, refresh, fullscreen, and open-in-new-window where supported.
2. `Agent Card`: structured canonical spec viewer/editor with generated API/config subpanel.
3. `Source Code`: generated source tree for AgentLab runtime config, ADK files, and CX export bundle; read-only except tool/callback code blocks.
4. `Tools`: canonical tool registry with target compatibility and last test run.
5. `Callbacks`: lifecycle editor and compatibility status.
6. `Guardrails`: policy builder and target compatibility.
7. `Evals`: linked scenario/golden suites, generation, review, and run status.
8. `Trace`: builder events plus runtime trace timeline for preview/test-live/eval runs.
9. `Test Live`: inline chat runner against compiled runtime config.
10. `Deploy`: release candidate and target-specific deploy status/actions.
11. `Activity / Diff`: mutation history, spec diffs, generated output diffs, rollback.

Layout notes:

- The current global `Layout` uses a constrained main container. Workbench needs a full-width/full-height exception or a shell-level prop so the primary experience does not feel embedded.
- Keep left pane around 35-40 percent and right pane around 60-65 percent on desktop.
- Collapse to stacked tabs on smaller viewports, but keep conversation and current right-tab state accessible.
- Do not duplicate whole Build page UI inside Workbench. Reuse logic and component primitives, not nested pages.

## Highest-Risk Architecture Choices

1. Canonical model scope creep
   - Risk: the first model tries to perfectly represent ADK, CX, and AgentLab runtime internals and becomes impossible to implement.
   - Mitigation: model only MVP surfaces first; preserve unknown target-specific raw fields in `target_overrides` and `source_refs`.

2. Two builder models diverge
   - Risk: `BuilderConfigDraft` and `AgentProjectSpec` both become "truth."
   - Mitigation: mark `BuilderConfigDraft` as legacy/simple-build. Add adapters from `BuilderConfigDraft` to `AgentProjectSpec` and from `AgentProjectSpec` to runtime config.

3. Plan-before-apply gets bypassed
   - Risk: chat mutations continue to mutate generated config directly, undermining the PRD's inspection model.
   - Mitigation: Workbench API must split `interpret`, `plan`, and `apply`. Apply-mode can combine UX steps, but backend should still create a proposal and mutation plan.

4. ADK/CX parity claims become misleading
   - Risk: UI marks features as portable when projection is lossy or blocked.
   - Mitigation: every tool/callback/guardrail/deploy surface carries target compatibility from compiler/export matrices.

5. Source editing implies reverse compilation
   - Risk: users edit arbitrary generated source and expect Agent Card to update.
   - Mitigation: MVP source tab is generated/read-only except explicit tool/callback code fields mapped into the canonical spec.

6. Event model fragmentation
   - Risk: builder events, trace events, eval events, and deploy events appear unrelated.
   - Mitigation: Workbench activity entries should link `task_id`, `proposal_id`, `spec_id`, `spec_version`, `eval_run_id`, `trace_id`, and `release_id`.

7. Deploy tab duplicates existing deploy flows
   - Risk: Workbench creates a parallel deploy system.
   - Mitigation: Workbench creates release candidates and calls existing deploy/adk/cx services; target-specific pages remain source of deeper operational details.

## Phase Order

### Phase 0: Contract and Persistence Foundation

Outcome:

- A canonical spec model exists, can be created from a brief or existing Build chat draft, can be saved/loaded/versioned, and can validate without UI changes.

Verification:

- Unit tests for `AgentProjectSpec` validation, store CRUD, version snapshots, rollback, and `BuilderConfigDraft` adapter.
- `pytest tests/test_builder_store.py tests/test_builder_chat_api.py <new workbench model tests> -q`.

### Phase 1: Read-Only Workbench Shell

Outcome:

- `/workbench` loads a project/spec, shows the two-pane shell, renders conversation/proposal placeholders on the left, and renders read-only right tabs from the current spec and generated outputs.

Verification:

- Frontend unit tests for route rendering, tab selection, target mode badges, and mobile/desktop pane behavior.
- Existing `Build.test.tsx` and `Builder.test.tsx` still pass.

### Phase 2: Plan-Before-Apply Loop

Outcome:

- User messages in Workbench produce interpretation, mutation plan, impacted surfaces, validation plan, and proposal card before mutation.
- Apply updates canonical spec, recompiles AgentLab runtime config, runs schema/compiler/preview smoke validation, and records activity.

Verification:

- Backend tests prove `plan` does not mutate and `apply` does.
- Frontend tests prove plan cards appear before changed Agent Card values.
- API tests cover Ask, Plan, and Apply modes.

### Phase 3: Compiler and Export Adapters

Outcome:

- Canonical spec compiles to AgentLab runtime config, ADK source bundle, and CX editable/export bundle with compatibility matrices.
- Source Code tab shows generated files and blocked/lossy warnings.

Verification:

- Golden tests for spec-to-runtime, spec-to-ADK, and spec-to-CX outputs.
- Existing ADK/CX import/export tests continue to pass.
- Diff/readiness UI tests cover ready/lossy/blocked rows.

### Phase 4: Tools, Callbacks, Guardrails, and Evals

Outcome:

- Right tabs allow structured edits for tool/callback/guardrail/eval surfaces.
- Scenario and golden eval suites can be generated, reviewed, accepted, linked to the spec, and run inline.

Verification:

- Tests for tool schema validation, callback lifecycle mapping, guardrail compatibility, eval generation linkage, and eval run status updates.
- Existing generated eval API tests remain green.

### Phase 5: Trace, Test Live, Deploy, Activity, and Rollback

Outcome:

- Test Live creates traceable sessions.
- Trace tab renders builder/runtime/eval evidence.
- Deploy tab creates release candidates and delegates to existing deploy services.
- Activity/Diff tab supports spec diffs and rollback.

Verification:

- API tests for preview/test-live trace linkage, release candidate creation, deploy delegation, and rollback.
- Frontend tests for trace tab, deploy tab, activity diff, and rollback confirmation.

### Phase 6: Rollout and Build Integration

Outcome:

- Workbench appears in Build navigation.
- Current Build can open a generated draft in Workbench.
- Agent Library, Eval Runs, Optimize, Improvements, and Deploy handoffs accept Workbench-originated agents.
- Feature can be toggled and monitored.

Verification:

- End-to-end browser smoke: brief -> plan -> apply -> preview -> generate evals -> run eval -> save agent -> deploy stub.
- Regression browser smoke for current `/build?tab=builder-chat`.

## Ticket Backlog

### Backend / Orchestration

#### WB-BE-1: Add canonical agent model types

Files:

- Add `builder/agent_model.py`
- Add tests in `tests/test_workbench_agent_model.py`

Tasks:

- Define `AgentProjectSpec` and child models listed above.
- Include docstrings explaining why each public model exists.
- Implement validation for unique IDs, root/sub-agent references, tool/callback/guardrail references, target mode, eval kinds, and deployment environment references.
- Add compatibility helper methods for `portable`, `adk`, and `cx` status.

Verification:

- `pytest tests/test_workbench_agent_model.py -q`

#### WB-BE-2: Persist canonical specs

Files:

- Add `builder/agent_model_store.py` or extend `builder/store.py`
- Add tests in `tests/test_workbench_agent_model_store.py`

Tasks:

- Add `builder_agent_specs` table with JSON payload storage.
- Implement create, get, list by project, save new version, get active draft, and rollback.
- Preserve existing builder tables and migrations.
- Decide whether to add `ArtifactType.AGENT_SPEC`; only add it if card rendering needs it.

Verification:

- `pytest tests/test_workbench_agent_model_store.py tests/test_builder_store.py -q`

#### WB-BE-3: Add builder-chat-to-spec adapter

Files:

- Add `builder/workbench_adapters.py`
- Update `builder/workspace_config.py` only if shared helper extraction is needed
- Add tests in `tests/test_workbench_adapters.py`

Tasks:

- Convert current `BuilderConfigDraft` into `AgentProjectSpec`.
- Convert `AgentProjectSpec` into the runtime config shape used by `persist_generated_config` and eval runs.
- Preserve Build chat metadata in spec lineage.

Verification:

- `pytest tests/test_workbench_adapters.py tests/test_builder_chat_api.py tests/test_agents_api.py -q`

#### WB-BE-4: Implement interpreter/planner contracts

Files:

- Add `builder/workbench_interpreter.py`
- Add `builder/workbench_planner.py`
- Add `builder/workbench_mutations.py`
- Add tests in `tests/test_workbench_planner.py`

Tasks:

- Define request/response objects for interpretation and mutation plans.
- Implement deterministic JSON Patch application and rollback metadata.
- Create `BuilderTask`, `BuilderProposal`, and plan `ArtifactRef` for each plan request.
- Support Ask, Plan, and Apply modes without mutating during Ask or Plan.

Verification:

- `pytest tests/test_workbench_planner.py tests/test_builder_execution.py tests/test_builder_orchestrator.py -q`

#### WB-BE-5: Add Workbench API routes

Files:

- Update `api/routes/builder.py` or add `api/routes/workbench.py` mounted under `/api/builder/workbench`
- Update `api/server.py` state wiring
- Add tests in `tests/test_workbench_api.py`

Tasks:

- Add create/get/plan/apply/validate/compile/preview/save-agent/rollback endpoints.
- Use existing `BuilderStore`, `EventBroker`, `PermissionManager`, `ArtifactCardFactory`, `BuildArtifactStore`, and generated eval store from app state.
- Return typed response payloads that frontend can render without extra stitching.

Verification:

- `pytest tests/test_workbench_api.py tests/test_builder_chat_api.py tests/test_agents_api.py -q`

### Compiler / Export Adapters

#### WB-COMP-1: Compile spec to AgentLab runtime config

Files:

- Add `builder/compiler/runtime_config.py`
- Add tests in `tests/test_workbench_runtime_compiler.py`

Tasks:

- Produce config accepted by `preview_generated_config`, `persist_generated_config`, `/api/eval/run`, and Agent Library save.
- Preserve tools, routing, policies/guardrails, eval criteria, and model settings.
- Include `journey_build`/lineage metadata compatible with existing saved artifacts.

Verification:

- `pytest tests/test_workbench_runtime_compiler.py tests/test_agents_api.py tests/test_eval_generate_routes.py -q`

#### WB-COMP-2: Compile spec to ADK bundle

Files:

- Add `builder/compiler/adk_adapter.py`
- Add tests in `tests/test_workbench_adk_compiler.py`

Tasks:

- Map root/sub-agents to `AdkAgentTree`.
- Map tools to ADK `FUNCTION_TOOL`, `MCP_TOOLSET`, `OPENAPI_TOOL`, or blocked/lossy rows.
- Map callbacks to ADK callback bindings where possible.
- Use `adk/scaffold.py` or compatible rendering to generate inspectable files.
- Return `ExportCapabilityMatrix`.

Verification:

- `pytest tests/test_workbench_adk_compiler.py tests/test_adk_import_export.py tests/test_adk_scaffold.py -q` or the repo's closest existing ADK test names.

#### WB-COMP-3: Compile spec to CX editable workspace/export bundle

Files:

- Add `builder/compiler/cx_adapter.py`
- Add tests in `tests/test_workbench_cx_compiler.py`

Tasks:

- Map root/sub-agents to CX playbooks/flows where supported.
- Map CX-compatible tool kinds using `CxToolType`.
- Preserve blocked/lossy constructs with clear export rows.
- Produce a `CxEditableWorkspace` and export preview compatible with existing CX routes.

Verification:

- `pytest tests/test_workbench_cx_compiler.py tests/test_cx_studio_exporter.py tests/test_cx_agent_mapper.py -q` or the repo's closest existing CX test names.

#### WB-COMP-4: Add unified compiler facade

Files:

- Add `builder/compiler/__init__.py`
- Add `builder/compiler/service.py`
- Add tests in `tests/test_workbench_compiler_service.py`

Tasks:

- Compile selected target mode: AgentLab only, ADK, CX, or all.
- Merge compiler warnings into `ValidationSummary`.
- Attach `PortabilityReport` and `ExportCapabilityMatrix` to generated outputs.

Verification:

- `pytest tests/test_workbench_compiler_service.py -q`

### Eval / Trace / Testing

#### WB-EVAL-1: Link generated eval suites to specs

Files:

- Update `api/routes/generated_evals.py` only if request metadata needs extension
- Add Workbench route wrapper in `/api/builder/workbench`
- Add tests in `tests/test_workbench_evals.py`

Tasks:

- Generate scenario and golden suites from current spec.
- Store generated suite IDs on `EvalSuiteSpec`.
- Allow review/accept using existing generated eval APIs.
- Run accepted suites through existing `/api/eval/run`.

Verification:

- `pytest tests/test_workbench_evals.py tests/test_generated_evals_api.py tests/test_eval_generate_routes.py -q`

#### WB-EVAL-2: Add always-test-after-change validator

Files:

- Add `builder/workbench_validator.py`
- Add tests in `tests/test_workbench_validator.py`

Tasks:

- Run schema validation after every apply.
- Run compiler validation for selected target mode.
- Run preview smoke test when runtime config compiles.
- Run evals when linked suites exist or when apply request asks for evals.
- Store validation summary on spec version and emit builder events.

Verification:

- `pytest tests/test_workbench_validator.py tests/test_builder_chat_api.py tests/test_generated_evals_api.py -q`

#### WB-TRACE-1: Attach traces/events to Workbench activity

Files:

- Update Workbench validator/API
- Update `web/src/lib/workbench-types.ts`
- Possibly expand trace frontend types near `Traces.tsx`/`TraceTimeline.tsx`
- Add tests in `tests/test_workbench_trace_linkage.py`

Tasks:

- Record trace IDs from preview/test-live/eval runs in spec activity.
- Support `TraceBookmark` creation from Workbench.
- Expand frontend event typing for state changes, tool requests/results, errors, and control signals if currently missing.

Verification:

- `pytest tests/test_workbench_trace_linkage.py tests/test_traces_api.py -q` or the repo's closest trace route tests.

#### WB-QA-1: Add MVP browser journey

Files:

- Add `web/tests/workbench-flow.spec.ts`

Tasks:

- Cover brief -> plan -> apply -> preview -> inspect Agent Card -> generate eval -> save -> deploy stub.
- Mock backend responses enough for deterministic frontend checks.
- Include regression check that `/build?tab=builder-chat` still renders.

Verification:

- `PLAYWRIGHT_BASE_URL=http://127.0.0.1:<port> npx playwright test web/tests/workbench-flow.spec.ts`

### Frontend

#### WB-FE-1: Add Workbench route and navigation

Files:

- Update `web/src/App.tsx`
- Update `web/src/lib/navigation.ts`
- Add `web/src/pages/AgentWorkbench.tsx`
- Add `web/src/pages/AgentWorkbench.test.tsx`

Tasks:

- Register Workbench route.
- Add Build navigation item.
- Add route metadata.
- Ensure current legacy redirects remain unchanged.
- Add a full-width/full-height layout mode if necessary.

Verification:

- `npm run test -- src/pages/AgentWorkbench.test.tsx src/pages/Build.test.tsx src/pages/Builder.test.tsx`

#### WB-FE-2: Add Workbench API/types client

Files:

- Add `web/src/lib/workbench-types.ts`
- Add `web/src/lib/workbench-api.ts`
- Add tests in `web/src/lib/workbench-api.test.ts`

Tasks:

- Mirror backend `AgentProjectSpec`, plan/apply responses, generated outputs, validation, and target compatibility.
- Add client functions for create/get/plan/apply/validate/compile/preview/evals/save/deploy/rollback.
- Preserve existing builder chat client.

Verification:

- `npm run test -- src/lib/workbench-api.test.ts`

#### WB-FE-3: Build two-pane Workbench shell

Files:

- Add `web/src/components/workbench/WorkbenchShell.tsx`
- Add `WorkbenchTopBar`, `WorkbenchLeftPane`, `WorkbenchRightPane`
- Add component tests

Tasks:

- Use project selector, target mode, draft/version badge, environment selector, eval health, deploy, undo/rollback.
- Use `ConversationPane`, `Composer`, and `TaskDrawer` where compatible.
- Support Plan, Apply, and Ask composer modes.

Verification:

- `npm run test -- src/components/workbench`

#### WB-FE-4: Implement right-pane tabs

Files:

- Add tab components under `web/src/components/workbench/tabs/`
- Add tests per tab or grouped suite

Tasks:

- Implement Preview, Agent Card, Source Code, Tools, Callbacks, Guardrails, Evals, Trace, Test Live, Deploy, Activity/Diff tabs.
- Start read-only in Phase 1; enable structured edits in later phase tickets.
- Show target compatibility consistently.

Verification:

- `npm run test -- src/components/workbench/tabs`

#### WB-FE-5: Add Build-to-Workbench handoff

Files:

- Update `web/src/pages/Build.tsx`
- Update tests in `web/src/pages/Build.test.tsx`

Tasks:

- Add "Open in Workbench" CTA when a builder chat session has generated config.
- Call create-spec-from-session route.
- Navigate to Workbench with returned spec ID.
- Keep Save, Preview, Export, and Eval handoffs unchanged.

Verification:

- `npm run test -- src/pages/Build.test.tsx src/pages/AgentWorkbench.test.tsx`

### Rollout / Integration

#### WB-ROLL-1: Feature flag Workbench entry

Files:

- Existing config/settings location used by the frontend
- Navigation and route code

Tasks:

- Add an `agent_builder_workbench` feature flag or capability gate.
- Default enabled in local/dev if product wants visibility; default disabled in production-like deployments until backend routes are wired.
- Keep route discoverable through direct URL for QA if enabled.

Verification:

- Frontend tests for enabled/disabled nav behavior.

#### WB-ROLL-2: Add downstream journey handoffs

Files:

- Workbench save/eval/deploy frontend and backend route wrappers
- Existing Eval/Optimize/Deploy pages as needed

Tasks:

- Save Workbench spec to Agent Library with `source: built`, `build_source: workbench`, and spec lineage.
- Open Eval Runs with selected saved agent and generated suite context.
- Link eval results to Optimize and Improvements through existing active-agent state.
- Create release candidates for Deploy.

Verification:

- Existing Eval Runs, Optimize, Improvements, Deploy tests plus new Workbench handoff tests.

#### WB-ROLL-3: Add docs and operator notes

Files:

- Add user/developer docs where this repo keeps feature docs.
- Update this plan if implementation discovers a changed architecture.

Tasks:

- Document canonical model boundaries.
- Document why source editing is limited in MVP.
- Document target compatibility labels.
- Document rollback and release-candidate flow.

Verification:

- `git diff --check`

## MVP Definition of Done

MVP is complete when a user can:

1. Open Workbench and create a new agent spec from a plain-English brief.
2. See a visible change plan before applying a mutation.
3. Apply the mutation and see the Agent Card update from the canonical model.
4. See generated AgentLab runtime config and at least one generated target bundle: ADK in Phase 3, CX by the end of MVP if Hybrid is enabled.
5. Run schema/compiler/preview smoke validation after change.
6. Generate or attach scenario/golden evals and run at least one eval suite.
7. Inspect trace/test evidence for a preview or test-live run.
8. Save the compiled runtime config to the existing Agent Library.
9. Reach existing Eval, Optimize, Improvements, and Deploy paths with Workbench lineage intact.
10. Roll back to a prior spec version from Activity/Diff.

## Verification Matrix

| Phase | Backend verification | Frontend verification | Browser verification |
| --- | --- | --- | --- |
| Phase 0 | New model/store/adapter tests plus existing builder store/chat tests | None required | None required |
| Phase 1 | Workbench get/create API tests | Route/shell/tab rendering tests | Smoke open `/workbench` |
| Phase 2 | Plan/apply/mutation/validation API tests | Plan cards and Agent Card update tests | Brief -> plan -> apply -> preview |
| Phase 3 | Runtime/ADK/CX compiler golden tests | Source tab/export matrix tests | Inspect generated files and warnings |
| Phase 4 | Evals/guardrails/tool/callback tests | Structured edit and eval tab tests | Generate/review/run eval |
| Phase 5 | Trace/deploy/rollback tests | Trace, Deploy, Activity/Diff tests | Test Live -> trace -> release candidate -> rollback |
| Phase 6 | Existing journey tests | Build, Eval Runs, Optimize, Improvements, Deploy regression tests | Full MVP journey plus existing Build chat journey |

Minimum final verification before enabling broadly:

- Backend: targeted pytest suites for builder, workbench, agents, evals, traces, ADK, CX, deploy wrappers.
- Frontend: targeted Vitest suites for Workbench plus existing Build/Eval/Deploy journey pages.
- Build: `npm run build` unless pre-existing unrelated TypeScript/build debt is documented.
- Browser: Playwright MVP happy path and current `/build?tab=builder-chat` regression.
- Static: `git diff --check`.

## Open Questions

1. Should the route be `/workbench` or `/build/workbench`? Product language says "Workbench for Agents"; navigation clarity may favor `/workbench`, while Build-family ownership may favor `/build/workbench`.
2. Should Hybrid mode require both ADK and CX compilers to be ready before an apply succeeds, or should it allow lossy/blocking warnings with AgentLab runtime config still valid?
3. Which target should be mandatory for MVP export: ADK first, CX first, or AgentLab runtime plus one target?
4. Should tool/callback code blocks execute in the existing sandbox route or only as smoke tests through preview/eval initially?
5. How much of the current `BuilderChatService` should be migrated versus wrapped? A compatibility adapter is safer for MVP; a deeper rewrite can happen after Workbench proves the canonical model.
6. What production deployment targets are in scope for the first Deploy tab: local preview only, ADK local/package, CX export/API, or full AgentLab deploy/canary?
