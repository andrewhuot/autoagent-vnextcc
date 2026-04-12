# Cohesive Item 4 Plan - Restart Continuity

## Scope

Mission: execute Item 4 only from `docs/plans/2026-04-12-cohesive-product-hardening.md`.

Item 4 outcome: after restart and during long-running use, operators can tell whether what they are seeing is live, interrupted, or historical, and they can still find durable builder sessions, eval history, improvement decisions, and event history.

Explicit non-goal: do not work Item 3 truthfulness/no-fake-progress tasks. This session may add continuity labels and recovery explanations, but it must not change drift/context/autofix/optimize truthfulness semantics outside the Item 4 restart/history/event surfaces.

## Current Findings

- `api.tasks.TaskManager` already persists background tasks to SQLite and marks previously `running` or `pending` tasks as `interrupted` on startup.
- `builder.chat_service.BuilderChatService` already persists conversational builder sessions and exposes `/api/builder/chat/sessions` plus `/api/builder/session/{session_id}`.
- `builder.events.EventBroker` and `DurableEventStore` already persist builder events; `/api/events/unified` merges system and builder events.
- `builder.workbench.WorkbenchService` already recovers stale active Workbench runs as `stale_interrupted`, and the frontend store can render a hydration notice from that state.
- Frontend pages currently expose some durable state, but the copy and labels do not consistently separate live runs, interrupted runs, and historical records.

## Implementation Plan

### Phase 1 - Backend Continuity Contract

Red tests first:

- Extend `tests/test_p0_journey_fixes.py` with coverage that interrupted task reloads expose a user-facing restart recovery context, not just `status="interrupted"`.
- Extend `tests/test_p0_journey_fixes.py` with coverage that persisted builder chat session summaries include durable history/resume metadata after service recreation.
- Extend `tests/test_event_unification.py` with endpoint-level coverage that unified event responses identify event source and durable timeline state for event viewers.

Minimal implementation:

- Add continuity metadata to task serialization and `api.models.TaskStatus`.
- When `TaskManager` marks a task interrupted on startup, persist a helpful recovery error/detail if one is not already present.
- Add continuity/resume metadata to `BuilderChatService.serialize_session()` and `list_sessions()`.
- Annotate `/api/events/unified` rows with source label and durable timeline state, keeping existing fields backwards compatible.

### Phase 2 - Frontend Page Clarity

Red tests first:

- Add/update `web/src/pages/Build.test.tsx` so the builder-chat resume panel distinguishes durable historical sessions from a live draft and shows restored-session context.
- Add/update `web/src/pages/EvalRuns.test.tsx` so eval history displays live, interrupted, and historical states with recovery guidance for interrupted rows.
- Add/update `web/src/pages/Improvements.test.tsx` so the History tab frames decisions as durable historical records rather than live work.
- Add/update `web/src/pages/AgentWorkbench.test.tsx` so a recovered `stale_interrupted` Workbench run is labeled as interrupted, not merely failed.
- Add `web/src/pages/EventLog.test.tsx` if needed to lock event-viewing source/durable labels.

Minimal implementation:

- Update builder chat types and Build UI copy/chips for historical sessions, restored sessions, and live current draft.
- Add Eval Runs continuity summary and per-row state labels derived from `status`.
- Add Improvement History durable-history framing.
- Add a Workbench interrupted-recovery banner/chip for hydrated `stale_interrupted` runs.
- Prefer the unified event endpoint in Event Log and show system/builder plus durable historical labels.

### Phase 3 - Browser Restart Story

Red browser test first:

- Create `web/tests/restart-continuity.spec.ts`.
- Mock a restart-recovered world:
  - `/api/builder/chat/sessions` returns a historical resumable session.
  - `/api/builder/session/{id}` returns restored session content.
  - `/api/eval/runs` returns one `running`, one `interrupted`, and one `completed` run.
  - `/api/events/unified` returns system and builder durable timeline events.
- Validate:
  - Build surfaces durable session history and restored historical context.
  - Eval Runs separates live, interrupted, and historical rows.
  - Event Log shows durable event timeline with source labels.

Minimal implementation:

- Add only UI/API glue required for the test story to pass.

### Phase 4 - Verification, Commit, Push

Targeted commands:

- `python3 -m pytest tests/test_p0_journey_fixes.py tests/test_event_unification.py`
- `cd web && npm run test -- src/pages/Build.test.tsx src/pages/EvalRuns.test.tsx src/pages/Improvements.test.tsx src/pages/AgentWorkbench.test.tsx src/pages/EventLog.test.tsx`
- `cd web && npx playwright test tests/restart-continuity.spec.ts`
- `git diff --check`

If the targeted frontend command cannot include `EventLog.test.tsx` because the file is not created, omit only that test path and record why.

Completion commands:

- Commit with a conventional commit on `feat/cohesive-restart-continuity-codex`.
- Push the branch.
- Run `openclaw system event --text "Done: Codex finished cohesive Item 4 restart continuity on feat/cohesive-restart-continuity-codex" --mode now`.

## Risk Controls

- Keep all changes additive/backwards-compatible for API payloads.
- Do not alter Item 3 surfaces: drift monitor, context no-data semantics, AutoFix truth language, or Optimize truthfulness labels.
- Preserve existing route behavior and mocks; browser test will route missing APIs to existing harmless defaults only when needed for layout.
- If a test already passes before implementation, adjust it until it proves the missing continuity behavior specifically.
