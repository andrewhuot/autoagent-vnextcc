# AgentLab PRD P0 Implementation Plan - Codex

Date: 2026-04-12
Branch: `feat/prd-p0-gap-codex`

## Goal

Implement the narrow P0 slice identified in `working-docs/prd-gap-analysis-codex.md`:

1. Make the durable Workbench conversation log one-user-message-per-turn.
2. Preserve prior artifacts during frontend follow-up iteration.
3. Add explicit review gate and handoff contracts to completed Workbench runs and surface them in the UI.
4. Make the Workbench JSON store fail closed on corrupt durable state and use atomic replacement writes.

## Non-Goals

- Do not implement the full PRD Agent Card/IR compiler.
- Do not materialize full workspace folders or write project files to disk.
- Do not implement full optimizer/candidate registry, deployment, live loops, or ADK/CX fidelity preview.
- Do not refactor the Workbench architecture or replace the JSON store.

## Test-First Plan

### Backend Regression Tests

Add focused coverage in Workbench tests:

- Completed stream exposes exactly one durable user conversation message per turn.
- `run.completed` presentation includes `review_gate` with validation, compatibility, and human-review checks.
- `run.completed` presentation includes a resumable `handoff` summary with project/run/version/event context.
- The review gate blocks promotion when validation fails or target compatibility has invalid diagnostics.
- Corrupt existing Workbench JSON raises a clear error and does not reset the store.

### Frontend Regression Tests

Add focused coverage in Workbench UI/store tests:

- `startIteration()` preserves existing artifacts while recording `previousVersionArtifacts`.
- `run.completed` stores review gate and handoff data from the presentation payload.
- Activity tab renders the review gate status, blocking reasons, and handoff resume prompt.

## Implementation Steps

### Step 1: Backend Review Gate Contract

Files:
- `builder/workbench.py`
- `tests/test_workbench_streaming.py` or a new focused Workbench PRD contract test file

Changes:
- Add `build_review_gate(project, run, validation)` helper.
- Add `build_run_handoff(project, run, presentation)` helper.
- Extend `build_presentation_manifest()` to include:
  - `review_gate`
  - `handoff`
- Persist `run["review_gate"]` and `run["handoff"]` when completing a run.
- Ensure terminal run payload includes those fields through existing `presentation` and `run` structures.

Contract shape:

```json
{
  "review_gate": {
    "status": "review_required",
    "promotion_status": "draft",
    "requires_human_review": true,
    "checks": [
      {"name": "harness_validation", "status": "passed", "required": true, "detail": "..."},
      {"name": "target_compatibility", "status": "passed", "required": true, "detail": "..."},
      {"name": "human_review", "status": "required", "required": true, "detail": "..."}
    ],
    "blocking_reasons": []
  },
  "handoff": {
    "project_id": "wb-...",
    "run_id": "run-...",
    "turn_id": "run-...",
    "version": 2,
    "review_gate_status": "review_required",
    "active_artifact_id": "art-...",
    "last_event_sequence": 12,
    "next_operator_action": "Review candidate and run evals before promotion.",
    "resume_prompt": "Resume Workbench project ..."
  }
}
```

### Step 2: Backend Conversation Deduplication

Files:
- `builder/workbench.py`
- Workbench backend tests

Changes:
- Remove the duplicate durable conversation append path for user messages.
- Preserve `project["messages"]` and `run["messages"]` entries because those are separate stream/message records.
- Keep `project["conversation"]` as the planner-facing durable transcript.

### Step 3: Frontend Type/Store/UI Contract

Files:
- `web/src/lib/workbench-api.ts`
- `web/src/lib/workbench-store.ts`
- `web/src/components/workbench/ArtifactViewer.tsx`
- frontend tests

Changes:
- Add `WorkbenchReviewGate`, `WorkbenchReviewGateCheck`, and `WorkbenchHandoff` types.
- Extend `WorkbenchPresentation` and `WorkbenchRun` types.
- Preserve artifacts in `startIteration()`.
- Store presentation `review_gate` and `handoff` on `run.completed`.
- Render review gate and handoff summary in `ActivityWorkspace`.

### Step 4: Store Durability Contract

Files:
- `builder/workbench.py`
- `tests/test_workbench_p0_hardening.py`

Changes:
- Keep missing store files as first-run empty state.
- Raise a clear runtime error for existing corrupt JSON or malformed payloads.
- Write through a temporary sibling file and `os.replace()`.
- Verify corrupt state is not erased.

### Step 5: Verification

Run targeted tests first:

```bash
/opt/homebrew/bin/uv run --extra dev python -m pytest tests/test_workbench_streaming.py tests/test_workbench_multi_turn.py tests/test_workbench_hardening.py tests/test_workbench_p0_hardening.py -q
cd web && npm test -- workbench-store.test.ts ArtifactViewer.test.tsx HarnessMetricsBar.test.tsx
```

Then run broader meaningful checks:

```bash
/opt/homebrew/bin/uv run --extra dev python -m py_compile builder/workbench.py api/routes/workbench.py
cd web && npm run build
git diff --check
```

Run a broader backend or frontend suite if the targeted checks reveal integration risk.

## Acceptance Criteria

- `working-docs/prd-gap-analysis-codex.md` exists and distinguishes implemented, partial, non-P0 missing, and P0 missing.
- `working-docs/prd-p0-implementation-plan-codex.md` exists before code implementation.
- Backend terminal Workbench run payloads expose review gate and handoff contracts.
- Backend durable conversation has exactly one user entry per turn.
- Workbench JSON persistence does not silently reset corrupt existing state.
- Frontend follow-up iterations preserve previous artifacts in visible state.
- Activity tab makes review gate and handoff status legible.
- Targeted backend and frontend verification passes, or failures are clearly documented as unrelated.
- Branch is committed and pushed to origin.
