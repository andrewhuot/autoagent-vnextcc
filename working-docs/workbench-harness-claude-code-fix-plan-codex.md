# Workbench Harness Claude-Code Fix Plan - Codex

Date: 2026-04-12

Branch: `feat/workbench-harness-claude-code-audit-codex`

## Goal

Make the Workbench/model harness more truthful and practically useful as a long-running coding-agent system by fixing one major fake-progress gap: autonomous iteration must be tied to validation evidence and must produce real, durable correction semantics.

## Non-Goals

- Do not rewrite the whole harness.
- Do not add a full checkpoint resume engine in this pass.
- Do not run optimizer/improver automatically after every build.
- Do not replace the existing Workbench UI architecture.

## Implementation Plan

### 1. Add Red Tests First

Add backend regression coverage for a deterministic validation failure:

- a mock agent emits a `local_shell` tool while targeting `cx`;
- with `auto_iterate=False`, the run remains one pass and fails compatibility;
- with `auto_iterate=True` and `max_iterations=2`, the service emits a second correction iteration, repairs the tool to a target-compatible type, revalidates, and completes.

The test should assert durable semantics, not just event count:

- two `iteration.started` events when auto-iterate is enabled;
- the second iteration has `mode="correction"`;
- terminal payload has `status="completed"`;
- final validation status is passed;
- the persisted model no longer contains the invalid tool type.

### 2. Add Operation Support For Repair

Extend Workbench model operation application with `update_tool`.

Rules:

- identify existing tools by stable `id`;
- merge only the replacement object for that tool;
- preserve normal dedupe behavior;
- keep the operation explicit so the event log shows a real state transition.

### 3. Wire Validation Into Autonomous Correction

After `validation.ready` and before final presentation:

- inspect failed checks and compatibility diagnostics;
- if `auto_iterate=True`, the current turn has budget remaining, and deterministic correction operations exist, start a new `correction` iteration;
- emit durable `iteration.started`, `plan.ready`, `message.delta`, `task.started`, `artifact.updated`, `task.completed`, and `build.completed` events for the correction;
- re-enter the normal reflect/validate/present/run-completed path;
- stop at `max_iterations` and fail honestly if validation still does not pass.

The correction pass should be conservative. It should only repair known deterministic compatibility failures, not pretend to solve arbitrary failed evals.

### 4. Improve Frontend Operator Trust Where Low-Risk

Make the Workbench store/UI preserve more of the durable backend story:

- append live stream events into `activeRun.events` so trace/activity state is not only terminal-hydrated;
- store `run_summary` and `harness_state` snapshot fields if returned by the API;
- pass iteration budget controls through manual iteration requests;
- render durable handoff/checkpoint details from `activeRun.handoff` even when `presentation` is absent.

### 5. Verification Ladder

Backend targeted:

- `tests/test_workbench_multi_turn.py`
- `tests/test_workbench_streaming.py`
- `tests/test_workbench_harness_eng.py`
- `tests/test_workbench_p0_hardening.py`
- `tests/test_builder_execution.py`

Frontend targeted:

- `web/src/lib/workbench-store.test.ts`
- `web/src/pages/AgentWorkbench.test.tsx`
- relevant Workbench component tests if touched.

Repository checks:

- `git diff --check`
- web build if practical.

## Done Criteria

- Required audit and fix-plan docs exist under `working-docs/`.
- Red test fails before implementation and passes after implementation.
- Autonomous iteration performs a real repair for at least one validation-backed failure class.
- Terminal success after auto-correction is backed by final validation, not just a second stream ending.
- Manual/no-auto behavior remains honest.
- Verification results and remaining risks are reported.
- Branch is committed and pushed.
- Required `openclaw system event` command is run after completion.
