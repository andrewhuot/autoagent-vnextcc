# Workbench Model Harness — Integration Plan

## Strategy

**Codex branch** is the production backbone. **Claude branch** adds harness
abstraction, metrics, reflection, iteration, and diff UX on top.

The merge is **additive**: keep every Codex concept (durable runs, persisted
run envelopes, active_run, reflect/present lifecycle, workspace tabs,
presentation manifest) and layer Claude's harness concepts in alongside them.

## Branch Topology

```
                          48d2e05 (common ancestor — light theme)
                           /          \
              b0b1773 (Codex)      5ea4e56 (Claude)
              durable runs        harness engine
                  |
            current HEAD
```

Claude diverged *before* the Codex durable-run commit (b0b1773). Claude's
versions of overlapping files therefore **lack** the durable-run model
entirely. We cannot take Claude's versions wholesale — we must surgically
add Claude's net-new features into the Codex codebase.

## Risks

| Risk | Mitigation |
|------|------------|
| Claude store removes `activeRun`, `presentation`, `exports`, etc. | Keep Codex store; ADD harness fields additively |
| Claude api.ts removes `WorkbenchRun`, `WorkbenchPresentation`, etc. | Keep Codex types; ADD harness types at top |
| Claude workbench.py removes durable run lifecycle | Keep Codex service; ADD iteration_stream method |
| Claude ArtifactViewer removes workspace tabs | Keep Codex workspace tabs; ADD diff view to Artifacts workspace |
| Claude tests remove durable-run assertions | Keep Codex tests; ADD harness test suite alongside |
| New components reference store fields that don't exist | Ensure store has both Codex + Claude fields |

## File-by-File Approach

### New files (take from Claude as-is)
- `builder/harness.py` — 1882-line execution engine (no conflicts)
- `web/src/components/workbench/HarnessMetricsBar.tsx` — new component
- `web/src/components/workbench/IterationControls.tsx` — new component
- `web/src/components/workbench/ReflectionCard.tsx` — new component
- `web/src/components/workbench/HarnessMetricsBar.test.tsx` — new tests
- `web/src/components/workbench/IterationControls.test.tsx` — new tests
- `web/src/components/workbench/ReflectionCard.test.tsx` — new tests
- `tests/test_harness.py` — 981-line harness test suite
- `working-docs/harness-architecture.md` — architecture doc

### Overlapping files (manual merge)

| File | Strategy |
|------|----------|
| `builder/workbench.py` | KEEP Codex durable-run service. ADD `run_iteration_stream()` and `_iteration_event_stream()` from Claude. Wire `harness_state` into project. |
| `builder/workbench_agent.py` | KEEP Codex agent. ADD `LiveWorkbenchBuilderAgent` that wraps `HarnessExecutionEngine` + `iterate()` method. |
| `api/routes/workbench.py` | KEEP Codex routes. ADD `/build/iterate` endpoint + `WorkbenchIterateRequest` model. |
| `web/src/lib/workbench-api.ts` | KEEP Codex types (Run, Presentation, Message). ADD `HarnessMetrics`, `ReflectionEntry`, `IterationEntry` at top. ADD `iterateWorkbenchBuild()`. ADD new event types to union. |
| `web/src/lib/workbench-store.ts` | KEEP Codex state (activeRun, presentation, exports, etc.). ADD harness fields (harnessMetrics, iterationCount, reflections, etc.). ADD harness event handlers alongside existing ones. ADD `startIteration()`, `selectVersionForDiff()`. |
| `web/src/components/workbench/WorkbenchLayout.tsx` | KEEP Codex layout (including "Candidate ready" CTA). ADD `HarnessMetricsBar` below header. ADD `iterationControls` slot. |
| `web/src/components/workbench/ArtifactViewer.tsx` | KEEP Codex workspace tabs. ADD diff view/tab to the ArtifactsWorkspace sub-component. ADD version badges. |
| `web/src/pages/AgentWorkbench.tsx` | KEEP Codex hydration (with all durable-run fields). ADD `handleIterate()` + `consumeStream()` + `IterationControls`. |
| `web/src/components/workbench/ConversationFeed.tsx` | ADD `ReflectionCard` rendering + `onApplySuggestion` prop. |
| `web/src/components/workbench/ArtifactViewer.test.tsx` | REPLACE with Claude tests (they test the integrated component). |
| `web/src/lib/workbench-store.test.ts` | KEEP Codex durable-run tests. ADD Claude harness test section. |
| `tests/test_workbench_streaming.py` | KEEP Codex tests. Add harness-aware assertions where needed. |
| `tests/test_workbench_agent_live.py` | KEEP Codex structure. UPDATE tests to work with harness engine. |

### Files with minor Claude changes (apply selectively)
- `web/src/components/workbench/ChatInput.tsx` — enable attach button (cosmetic)
- `web/src/components/Layout.tsx` — remove eslint-disable comments + workbench route special-casing

## Verification Ladder

1. Python workbench/harness tests: `python -m pytest tests/test_harness.py tests/test_workbench_streaming.py tests/test_workbench_agent_live.py -x`
2. Frontend workbench tests: `cd web && npx vitest run --reporter=verbose`
3. TypeScript build: `cd web && npm run build`
4. Self-review of all changed files

## Ordering

1. New files first (no conflicts)
2. Backend overlapping files (workbench.py, workbench_agent.py, routes)
3. Frontend types + store (api.ts, store.ts)
4. Frontend components (Layout, ArtifactViewer, ConversationFeed, AgentWorkbench)
5. Tests
6. Verify
