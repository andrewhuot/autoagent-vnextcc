# P0 Workbench Evidence Semantics Plan - Codex

Date: 2026-04-12
Branch: `feat/p0-workbench-evidence-semantics-codex`

## Source Findings

- The audit inputs identify `auto_iterate` and terminal evidence semantics as the highest-risk Workbench truthfulness gap.
- This branch still accepts `auto_iterate` on the API but does not use it after entering `WorkbenchService.run_build_stream()`.
- Terminal success is currently based on structural validation alone: canonical model exists, exports compile, and target compatibility passes.
- The frontend already hydrates active runs and validation, but live stream events are not appended into `activeRun.events`, and Activity falls back less reliably than the header.

## Selected Slice

Implement a conservative evidence-backed correction path and operator evidence surface:

1. Add backend red tests for a deterministic CX-incompatible `local_shell` tool.
2. Preserve one-pass honesty when `auto_iterate=False`: one iteration, failed terminal status, invalid tool remains.
3. Enable `auto_iterate=True` to perform one deterministic correction iteration within `max_iterations`: replace known invalid tool types with target-compatible tool records, revalidate, and complete only after validation passes.
4. Add explicit terminal evidence metadata that distinguishes:
   - structural validation status,
   - improvement/change evidence status,
   - auto-correction evidence status,
   - review readiness.
5. Preserve the evidence metadata in run summaries, review gates, handoffs, terminal payloads, and frontend trace/activity surfaces.
6. Pass manual iteration budget controls through the frontend where the API already supports them.

## Non-Goals

- No general-purpose self-repair for arbitrary validation failures.
- No checkpoint resume engine.
- No inline optimizer/improver execution.
- No claim that structural validation proves production quality or eval improvement.

## Test Plan

- Backend targeted:
  - `tests/test_workbench_multi_turn.py`
  - `tests/test_workbench_streaming.py`
  - `tests/test_harness.py` if handoff evidence helpers move.
- Frontend targeted:
  - `web/src/lib/workbench-store.test.ts`
  - `web/src/components/workbench/ArtifactViewer.test.tsx`
  - `web/src/pages/AgentWorkbench.test.tsx`
- Final checks:
  - targeted pytest suite,
  - targeted Vitest suite,
  - `git diff --check`,
  - broader backend/frontend checks as practical before commit.

## Acceptance Criteria

- A structurally valid but evidence-empty build cannot silently read as a normal successful improvement.
- Auto-correction only fires for known deterministic compatibility repairs and is visible as `mode="correction"`.
- Terminal payloads include explicit evidence summary and review gate checks.
- The Workbench Trace tab receives live run events, and Activity can render handoff/review state from durable run or harness state fallbacks.
- Branch is committed, pushed, and the required `openclaw system event` command is run.
