# P1 Workbench Eval Optimize Bridge Plan - Codex

Date: 2026-04-12
Branch: `feat/p1-workbench-eval-optimize-bridge-codex`

## Mission

Implement the highest-value coherent slice of a typed Workbench -> Eval -> Optimize bridge. The product should make the improvement loop structurally connected and honest: Workbench creates a candidate and evidence bundle, Eval receives a runnable typed request, and Optimize receives a real eval-run-scoped input. This must not become an inline AutoFix shortcut.

## Required Source Documents Read

- `workbench-harness-claude-code-audit-codex.md`
- `repo-product-and-codebase-recommendations-opus.md`
- `repo-user-journeys-claude-sonnet.md`

## Source Document Takeaways

- Workbench already has durable run envelopes, events, validation, presentation, and handoff-like state, but the product still risks overstating how much of the improvement loop is real.
- The previous audit explicitly recommends a structured Workbench improvement handoff with validation status, failed checks, target, export names, generated config identity, review gate state, and recommended eval suite.
- The desired path is Workbench -> Eval Runs -> Optimize, because the optimizer has a scoped `eval_run_id` path that can convert completed eval failures into optimizer samples. AutoFix is proposal/apply oriented and should not be used as the bridge.
- Operator journeys currently make Build, Eval, Optimize, Review, Deploy look adjacent rather than one coherent loop. The bridge should reduce manual copy/paste and truthfully indicate what is ready to run next.

## Working Hypothesis

The safest high-value slice is a typed Workbench improvement handoff contract that is persisted with Workbench runs and exposed through API/frontend types, plus downstream Eval/Optimize request builders that consume that handoff. This gives operators a real handoff object and gives tests a stable contract to enforce without pretending to run optimization inline.

## Investigation Plan

1. Inspect Workbench backend run models, validation, presentation, snapshot, and API routes.
2. Inspect frontend Workbench store/API types and operator actions around Eval/Optimize.
3. Inspect Eval run API, request contract, results store, and task workflow.
4. Inspect Optimize API, especially any `eval_run_id` path and pending review behavior.
5. Identify the smallest path where a Workbench candidate can become:
   - a typed eval run request or recommendation, and
   - a typed optimize request that references an eval run after Eval completes.

## Implementation Plan

Implemented slice:

1. Added `builder/workbench_bridge.py` with typed Pydantic models:
   - `WorkbenchImprovementHandoff`
   - `WorkbenchBridgeCandidate`
   - `WorkbenchBridgeEvaluationStep`
   - `WorkbenchBridgeOptimizationStep`
   - `WorkbenchEvalRunRequest`
   - `WorkbenchOptimizeRequest`
2. Populated `improvement_bridge` in the durable Workbench run handoff and the terminal presentation payload.
3. Added `WorkbenchService.generated_config_for_bridge()` and `WorkbenchService.build_improvement_bridge_payload()` so routes can build the bridge from persisted run/project state.
4. Added `POST /api/workbench/projects/{project_id}/bridge/eval`, which:
   - saves the Workbench generated config into the real AgentLab workspace config/version path;
   - returns the typed bridge;
   - returns an `eval_request` ready for `/api/eval/run`;
   - returns an `optimize_request_template` for `/api/optimize/run` with `eval_run_id` intentionally unset until Eval completes.
5. Added frontend TypeScript bridge interfaces and rendered the bridge in the Workbench Activity tab.
6. Fixed Optimize to honor `?evalRunId=` query params, making Eval Detail -> Optimize a real eval-scoped route.
7. Added regression coverage for materialized handoff, blocked handoff semantics, bridge rendering, and query-param eval handoff.

## Non-Goals

- Do not run the optimizer inline at Workbench completion.
- Do not call AutoFix.
- Do not implement full checkpoint-based resume.
- Do not solve all review queue or task persistence gaps in this slice.
- Do not make claims that structural validation is equivalent to eval performance.

## Validation Plan

- Run targeted backend tests for Workbench/Eval/Optimize bridge behavior.
- Run targeted frontend tests/type checks if frontend types/components change.
- Run a broader relevant test subset if targeted tests touch shared routes/contracts.
- Validate git diff, commit, push, and run the required completion event command.

Current verification evidence:

- `uv run python -m pytest tests/test_workbench_eval_optimize_bridge.py -q` -> 2 passed.
- `npm test -- --run src/components/workbench/ArtifactViewer.test.tsx src/pages/Optimize.test.tsx` -> 2 files and 18 tests passed.
- `uv run python -m pytest tests/test_workbench_eval_optimize_bridge.py tests/test_workbench_streaming.py tests/test_workbench_p0_hardening.py tests/test_optimize_api.py -q` -> 35 passed.
- `npm run build` -> passed. Vite reported the existing large-chunk warning after minification.
- `git diff --check` -> passed.

## Open Questions To Resolve During Inspection

- Where is the most central Python type boundary for Workbench run payloads?
- Does Eval API accept config paths, config objects, agent IDs, or all of the above?
- What exact Optimize request shape uses `eval_run_id` today?
- Does the frontend already have an operator action surface on Workbench for running eval/optimize, or is this backend-first for this slice?
