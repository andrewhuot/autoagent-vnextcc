# Workbench Model Harness Refactor

## Context

This implementation evolves the existing AgentLab Workbench from an artifact-streaming demo into a durable model harness slice for building agents. The product target is "Claude Code, but for building agents": users describe work in natural language, a builder agent plans and executes behind the scenes, and the right-side workspace shows the live artifacts, source, validation, trace, and activity needed to iterate with confidence.

The design is grounded in five external harness references:

- Claude Code's loop: conversational iteration, explore-before-implement, tool observations, and explicit verification targets.
- Anthropic long-running harnesses: persistent progress notes, feature/run state, and self-verification before marking work complete.
- Anthropic app harness design: planner/generator/evaluator phases and build contracts that can be tested.
- Anthropic Managed Agents: separation of session state, harness lifecycle, and execution/review surfaces.
- OpenAI harness engineering: repo-local structured knowledge, first-class plans, validated boundaries, durable feedback loops, and agent-legible architecture.

## Request Lifecycle

1. The Workbench page hydrates the latest project from `/api/workbench/projects/default`, then hydrates the latest plan/run snapshot from `/api/workbench/projects/{project_id}/plan`.
2. The user submits a natural-language build request in the left pane.
3. The frontend begins a streaming request to `/api/workbench/build/stream`, passing `project_id`, `brief`, `target`, and `environment`.
4. The backend creates a durable `run-*` envelope on the canonical project. It records:
   - `brief`
   - `target`
   - `environment`
   - status and phase
   - starting/completed versions
   - persisted message history
   - replayable event log
   - validation summary
   - presentation manifest
5. The builder agent emits plan/task/artifact events. The service persists each event, updates task state, stores artifacts, and mutates the canonical model only through structured operations.
6. After build execution, the service runs a reflect phase, compiles export previews, validates the candidate, and records the test activity.
7. The service emits a present phase with artifact IDs, generated output names, validation status, and next actions.
8. The terminal `run.completed` payload carries the updated project, version, model, exports, compatibility diagnostics, activity, messages, validation, and active run so the UI stays honest without waiting for a reload.

## Builder-Agent Loop

The implemented loop is:

| Phase | Event Contract | Responsibility |
| --- | --- | --- |
| Plan | `plan.ready` | Produce a nested task tree from the brief. |
| Act / Build | `message.delta`, `task.started`, `task.progress`, `artifact.updated`, `task.completed`, `build.completed` | Execute leaf tasks, generate artifacts, and apply structured canonical operations. |
| Reflect | `reflect.started`, `reflect.completed` | Recompile outputs, run deterministic validation, and persist a validation trace. |
| Present | `present.ready`, `run.completed` | Publish the final manifest and updated canonical project snapshot to the UI. |
| Failure | `error`, `run.failed` | Persist failed status, error message, and terminal run state. |

The agent implementation remains compatible with mock and live modes. Mock mode provides deterministic behavior for local development and regression tests. Live mode can use `LLMRouter` for planner/executor payloads, then falls back to deterministic execution when provider output cannot be parsed.

## State And Persistence

Workbench still uses the existing JSON-backed `WorkbenchStore` for this vertical slice, but it now stores real run envelopes rather than only the latest plan/artifacts. This keeps the patch scoped while creating a clear seam for the planned migration onto the Builder Workspace SQLite substrate.

Project-level persisted state now includes:

- canonical `model`
- compiled `exports`
- `compatibility`
- latest `last_test`
- `activity`
- `messages`
- `runs`
- `active_run_id`
- `plan`
- `artifacts`
- `build_status`

The API server also initializes `app.state.workbench_store` during lifespan, so production routes no longer rely only on lazy default construction.

## Artifact And Preview Surface

The right pane now has six harness workspace tabs:

- `Artifacts`: live generated artifacts with category filtering and preview/source toggle.
- `Agent Card`: canonical root agent, instructions, counts, and compatibility diagnostics.
- `Source Code`: ADK and CX compiled export previews.
- `Evals`: canonical eval suites plus latest reflection checks.
- `Trace`: persisted run events and validation trace events.
- `Activity`: presentation next actions and canonical diff/activity records.

This keeps the right side connected to backend state instead of acting as a static artifact gallery.

## User Controls

The left pane still supports natural-language iteration and client-side cancellation of the active SSE stream. Inert controls were made less misleading:

- The paperclip affordance is disabled until attachments exist.
- The `Create agent` control is disabled until a harness run reaches a completed state and then reads as a candidate-ready affordance.
- Workbench uses a full-width layout exception so the harness feels like a workspace rather than a small embedded preview.

## Tradeoffs

- JSON persistence remains for this slice. It is enough for local durability and tests, but the next hardening step should migrate run/session/task/artifact storage onto `BuilderStore` and `EventBroker`.
- The streaming path now auto-applies structured operations as tasks complete. The synchronous plan/apply API still exists for explicit approval flows, but the main UI path remains a live builder run. A future iteration should add an approval/proposal mode inside the same run model.
- Reflection is deterministic validation, not a live generated eval execution. This preserves reliability in mock/local mode while creating the event contract needed for richer eval and trace integration later.
- Backend cancellation is still client-abort-only. A durable `POST /api/workbench/runs/{run_id}/cancel` endpoint should be added with task cancellation semantics.

## Follow-Up Work

1. Move Workbench run/session/task/artifact persistence onto the existing Builder Workspace SQLite primitives.
2. Add explicit approval cards backed by `planWorkbenchChange` and `applyWorkbenchPlan` inside the left pane.
3. Add a backend cancel endpoint and persist cancelled task status.
4. Save completed candidates into the Agent Library / BuildArtifactStore with Workbench lineage.
5. Launch generated eval suites from the Evals tab and attach real eval run IDs.
6. Attach Workbench reflection/test-live events to the broader Trace store.
7. Add Build-to-Workbench handoff from `/build`.

