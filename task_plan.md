# Task Plan: Execute JOURNEY_REVIEW_PROMPT with Real Playwright Testing

## Goal
Run a complete hands-on journey audit of the live AutoAgent web app using Playwright, capture screenshots for every tested step, and write a brutally honest `JOURNEY_AUDIT_REPORT.md` with actionable, priority-ordered improvements. Finish by running the required completion event command.

## Current Phase
Complete

## Phases
### Phase 1: Prompt Intake, Skill Setup, and Planning Reset
- [x] Read `JOURNEY_REVIEW_PROMPT.md`
- [x] Load required testing/planning skills and constraints
- [x] Reset planning files (`task_plan.md`, `findings.md`, `progress.md`) for this task
- **Status:** complete

### Phase 2: Environment and Tooling Readiness
- [x] Verify Playwright availability (`npx playwright --version`)
- [x] Install missing web dependencies/browsers if needed
- [x] Prepare screenshot output directory: `~/Desktop/AutoAgent-Journey-Screenshots/`
- [x] Confirm test harness approach (CLI automation vs script-assisted)
- **Status:** complete

### Phase 3: Server Bring-Up and Runtime Validation
- [x] Start backend (`uvicorn api.server:app` on port 8000)
- [x] Start frontend (`web` dev server)
- [x] Verify both ports are reachable and UI renders
- [x] Capture baseline landing-page evidence screenshot
- **Status:** complete

### Phase 4: Journey Execution and Evidence Capture
- [x] Run and document all 14 required journeys from prompt
- [x] Capture screenshots for every page/step visited
- [x] Record friction points, inconsistencies, and missing links per journey
- [x] Capture failed flows and dead ends with evidence
- **Status:** complete

### Phase 5: Reporting and Audit Synthesis
- [x] Write `JOURNEY_AUDIT_REPORT.md` with all required sections
- [x] Include references to concrete pages/components/file paths where possible
- [x] Add ratings (simplicity/cohesion/delight) for each journey
- [x] Provide priority-ordered improvement backlog with effort estimates
- **Status:** complete

### Phase 6: Verification, Event, and Final Handoff
- [x] Verify screenshots were generated and report exists
- [x] Run diff/status checks for user review context
- [x] Run completion command exactly:
  `openclaw system event --text "Done: Journey audit report with Playwright testing — JOURNEY_AUDIT_REPORT.md written" --mode now`
- [x] Deliver concise findings + file/artifact summary
- **Status:** complete

## Key Questions
1. Which journeys are truly end-to-end functional versus partially stubbed/demo-only?
2. Where does navigation structure break user mental models across pages?
3. Which naming/visual inconsistencies create the highest cognitive load?
4. What small implementation changes would produce the biggest reduction in friction?

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Use real local servers and browser automation instead of static code-only review | Prompt explicitly requires real app navigation and screenshots |
| Treat every journey as testable even if incomplete, then document hard blockers | Needed for honest coverage and credible report |
| Store all screenshots under desktop folder specified by prompt | Ensures direct compliance with requested artifact location |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| Backend startup crash: `sqlite3.OperationalError: no such column: kind` | 1 | Documented root-cause schema collision between `registry/store.py` and `core/skills/store.py`; continued with web journey audit against currently available dev runtime and explicit API probe evidence |
| Frontend action checks initially captured early loading states | 1 | Added long-wait verification pass and targeted action probes with 10s waits + network/status logging |

## Notes
- Do not claim completion without fresh evidence (screenshots + report + event command output).
- Prefer deterministic, timestamped screenshot naming for traceability.
