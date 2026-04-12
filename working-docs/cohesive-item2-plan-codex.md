# Cohesive Item 2 Workbench-Eval-Optimize UX Plan - Codex

Date: 2026-04-12
Branch: `feat/cohesive-workbench-eval-optimize-ux-codex`

## Scope Contract

Execute Item 2 only from `2026-04-12-cohesive-product-hardening.md`: finish the Workbench -> Eval -> Optimize experience so the typed bridge feels like a guided product flow. Do not touch Item 3 truthfulness surfaces such as judges, context reports, AutoFix, or broad Optimize truth-language cleanup outside the Workbench handoff preconditions.

## Source Inputs Read

- `/Users/andrew/Desktop/agentlab/docs/plans/2026-04-12-cohesive-product-hardening.md`
- `/Users/andrew/Desktop/agentlab-workbench-harness-claude-code-audit-codex/working-docs/workbench-harness-claude-code-audit-codex.md`

## Current Shape

- Backend bridge contract exists in `builder/workbench_bridge.py`.
- Materialization endpoint exists at `POST /api/workbench/projects/{project_id}/bridge/eval`.
- Workbench presentation includes `improvement_bridge`, but the UI currently renders it as passive activity text.
- Optimize already accepts `evalRunId` from router state or URL and passes it through to `useStartOptimize`.
- Optimize still presents "Ready to optimize" when no Workbench/Eval precondition is present, which is too inert for the Workbench handoff path.

## Item Plan

### 1. Tighten Backend Readiness States

Files:
- Modify `builder/workbench_bridge.py`
- Possibly modify `builder/workbench.py` only if presentation needs to preserve new bridge fields.
- Modify `api/routes/workbench.py`
- Test `tests/test_workbench_eval_optimize_bridge.py`

Steps:
1. Add failing bridge tests for display-oriented readiness:
   - draft only / missing generated config -> blocked with user-safe reason.
   - structurally valid but not materialized -> eval status remains not ready with an action label telling the operator to save/materialize.
   - materialized and validation-passed -> eval ready with start label and request payload.
   - eval run id supplied -> optimize ready with start label and concrete request template.
   - missing eval run -> optimize blocked/waiting with a user-safe prerequisite reason.
2. Run targeted pytest and confirm failures before implementation:
   - `python3 -m pytest tests/test_workbench_eval_optimize_bridge.py -q`
3. Extend the bridge models with UI-safe fields instead of making the frontend infer product copy from raw status:
   - `readiness_state`
   - `label`
   - `description`
   - `primary_action_label`
   - `primary_action_target`
   - existing `status`, `request`, and `blocking_reasons` remain backward-compatible.
4. Keep backend blockers deterministic and non-magical. Do not add Item 3 evidence claims.
5. Re-run targeted pytest.

### 2. Preserve Bridge State In The Frontend Store And API

Files:
- Modify `web/src/lib/workbench-api.ts`
- Modify `web/src/lib/workbench-store.ts`
- Test `web/src/components/workbench/ArtifactViewer.test.tsx`

Steps:
1. Add TypeScript fields for the new bridge display contract.
2. Ensure the store hydrates and merges `presentation.improvement_bridge` from `present.ready`, `run.completed`, and plan snapshots.
3. Add failing ArtifactViewer tests for:
   - eval-ready state shows a real next action instead of passive status text.
   - not-materialized state explains the prerequisite.
   - optimize waiting state explains Eval must run first.
4. Run targeted Vitest and confirm failures:
   - `cd web && npm run test -- src/components/workbench/ArtifactViewer.test.tsx`
5. Render the bridge as a guided panel in the Workbench Activity/Evals area.
6. Re-run targeted Vitest.

### 3. Add One-Click Workbench -> Eval Handoff

Files:
- Modify `web/src/lib/workbench-api.ts`
- Modify `web/src/pages/AgentWorkbench.tsx`
- Test `web/src/pages/AgentWorkbench.test.tsx`

Steps:
1. Add `createWorkbenchEvalBridge(projectId, body)` API helper for the existing materialization endpoint.
2. Add failing AgentWorkbench test that:
   - hydrates a completed eval-ready Workbench project.
   - clicks "Open Eval with this candidate".
   - asserts the endpoint is called.
   - asserts navigation lands on `/evals` with agent/config prefill query state.
3. Run targeted Vitest and confirm failure:
   - `cd web && npm run test -- src/pages/AgentWorkbench.test.tsx`
4. Implement the CTA in Workbench shell as a top-level, visible handoff control. It should materialize the candidate first, then navigate to Eval with:
   - `configPath`
   - `workbenchProjectId`
   - candidate name/context
   - `new=1`
5. Disable or relabel the CTA when bridge state is blocked, and show the blocking reasons.
6. Re-run targeted Vitest.

### 4. Make Optimize Preconditions Humane For Workbench Handoff

Files:
- Modify `web/src/pages/Optimize.tsx`
- Test `web/src/pages/Optimize.test.tsx`

Steps:
1. Add failing Optimize tests for Workbench-origin entry:
   - with `workbenchProjectId`/`configPath` but no `evalRunId`, show "Run Eval first" style prerequisite and link back to the Eval route.
   - start button is disabled while this Workbench handoff is missing a completed eval run.
   - with `evalRunId`, show the Workbench eval context and allow Start Optimization.
2. Run targeted Vitest and confirm failure:
   - `cd web && npm run test -- src/pages/Optimize.test.tsx`
3. Extend `OptimizeJourneyState` and URL parsing to recognize Workbench handoff fields without requiring a saved library agent.
4. Render a precondition panel that explains the exact missing prerequisite and links to `/evals` with the same `configPath` and Workbench context.
5. Do not change generic Optimize behavior for non-Workbench users except where required for compatibility.
6. Re-run targeted Vitest.

### 5. Operator Flow Validation

Commands:
- `python3 -m pytest tests/test_workbench_eval_optimize_bridge.py tests/test_workbench_multi_turn.py -q`
- `cd web && npm run test -- src/components/workbench/ArtifactViewer.test.tsx src/pages/AgentWorkbench.test.tsx src/pages/Optimize.test.tsx`
- If fast enough and relevant after targeted passes: `cd web && npm run build`
- `git diff --check`

Manual product-flow checklist:
- Workbench completed candidate explains whether it is draft-only, needs materialization, eval-ready, eval-complete, or blocked.
- Workbench has one obvious next action to open Eval with this candidate.
- Eval handoff preserves typed bridge payload and does not call Optimize or AutoFix.
- Optimize entry from Workbench explains missing eval run and points back to Eval.
- Optimize entry with an eval run id carries the context into the optimize request.

### 6. Commit And Push

Steps:
1. Review diff and stage only Item 2 files.
2. Commit with Conventional Commit:
   - `feat(workbench): guide eval optimize handoff`
3. Push:
   - `git push origin feat/cohesive-workbench-eval-optimize-ux-codex`
4. Run completion event:
   - `openclaw system event --text "Done: Codex finished cohesive Item 2 Workbench-Eval-Optimize UX on feat/cohesive-workbench-eval-optimize-ux-codex" --mode now`

## Risks And Guardrails

- Keep `bridge.evaluation.status` and `bridge.optimization.status` backward-compatible.
- Do not make Optimize claim real eval evidence unless an `evalRunId` is present.
- Do not work the Item 3 truthfulness tasks.
- Do not introduce new backend optimizer behavior; this item is product-flow UX and typed handoff clarity.

## Progress Log

- 2026-04-12: Created this Item 2 plan before implementation.
- 2026-04-12: Added backend red tests for bridge display readiness states.
- 2026-04-12: Implemented backend readiness labels/descriptions/action targets for draft-only, materialization-needed, eval-ready, awaiting-eval, and optimize-ready states.
- 2026-04-12: Added Workbench shell CTA that materializes through `/api/workbench/projects/{project_id}/bridge/eval` and opens Eval with Workbench config context.
- 2026-04-12: Added Activity bridge readiness/action copy and Optimize Workbench precondition UX.
- 2026-04-12: Updated Workbench CTA copy to use the bridge action label, including "Save candidate and open Eval" before materialization.
- 2026-04-12: Verified targeted backend/frontend tests, frontend build, targeted Item 2 lint, and diff hygiene.

## Verification Log

- `.venv/bin/python -m pytest tests/test_workbench_eval_optimize_bridge.py tests/test_workbench_multi_turn.py -q` -> 12 passed.
- `cd web && npm run test -- src/pages/AgentWorkbench.test.tsx src/components/workbench/ArtifactViewer.test.tsx src/pages/Optimize.test.tsx` -> 3 files passed, 28 tests passed.
- `cd web && npm run build` -> TypeScript build and Vite production build passed; Vite reported the existing large chunk warning.
- `cd web && npx eslint src/pages/AgentWorkbench.tsx src/pages/AgentWorkbench.test.tsx src/components/workbench/ArtifactViewer.tsx src/components/workbench/ArtifactViewer.test.tsx src/lib/workbench-api.ts` -> passed.
- `cd web && npm run lint` -> failed on pre-existing repo-wide React compiler, Fast Refresh, and typing lint findings outside Item 2, plus existing Optimize lifecycle-effect lint findings. The new unused Workbench test parameter caught by lint was fixed.
- `git diff --check` -> clean.

## Operator Flow Validation Results

- Workbench distinguishes draft-only, needs-materialization, eval-ready, awaiting-eval-run, and ready-for-optimize states using bridge-provided labels/descriptions/action targets.
- A Workbench candidate that passed validation but lacks a saved config presents "Save candidate and open Eval" and calls the existing bridge materialization endpoint before navigating.
- Eval navigation preserves typed bridge payload, saved config path, Workbench project/run context, and a synthetic Workbench agent in router state.
- Optimize entry from Workbench without `evalRunId` disables start and points the operator back to Eval with the same Workbench/config context.
- Optimize entry from Workbench with `evalRunId` creates a Workbench-backed effective agent and starts Optimize with that config path plus the completed Eval run id.

## Errors Encountered

| Error | Attempt | Resolution |
| --- | --- | --- |
| `python3 -m pytest` failed during collection because system Python 3.9 does not support `dataclass(slots=True)`. | First backend red run. | Used repo-local `.venv/bin/python` backed by Python 3.12 for backend tests. |
| `.venv/bin/python` did not exist. | Tried the repo virtualenv path. | Created a local virtualenv with `uv venv --python /opt/homebrew/bin/python3.12 .venv`. |
| `/opt/homebrew/bin/python3.12 -m pytest` had no pytest installed. | Tried Homebrew Python 3.12 directly. | Installed repo dev dependencies with `uv pip install -e '.[dev]'`. |
| `/opt/homebrew/bin/pytest` used Python 3.14 without FastAPI installed. | Tried global pytest. | Used the repo-local `.venv` for backend verification. |
| `cd web && npm run test -- ...Optimize.test.tsx` failed on missing Workbench Optimize precondition copy. | First frontend Item 2 red run. | Added Workbench query parsing and precondition panels in `Optimize.tsx`. |
| `cd web && npm run lint` failed repo-wide. | Post-verification hygiene run. | Fixed the new unused parameter in the Workbench test harness; left unrelated existing lint debt out of Item 2 scope. |
