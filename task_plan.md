# Task Plan: Add additive NL-first builder, transcript intelligence, and diagnosis-to-change workflows

## Goal
Implement an additive feature slice in AutoAgent VNextCC that brings in natural-language agent building, transcript ingestion, conversation analytics, and diagnosis-to-change workflows without destabilizing the current optimization golden path.

## Current Phase
Phase 5

## Phases
### Phase 1: Requirements & Discovery
- [x] Understand user intent
- [x] Identify constraints and requirements
- [x] Document findings in findings.md
- **Status:** completed

### Phase 2: Planning & Structure
- [x] Define technical approach
- [x] Identify additive product surfaces that preserve the current golden path
- [x] Document decisions with rationale
- **Status:** completed

### Phase 3: Implementation
- [x] Add the chosen backend and frontend feature slices
- [x] Write tests for behavior changes
- [x] Keep existing flows intact while expanding capability
- **Status:** completed

### Phase 4: Testing & Verification
- [x] Run targeted tests for changed areas
- [x] Document test results in progress.md
- [x] Fix any issues found
- **Status:** completed

### Phase 5: Delivery
- [x] Review final diff
- [x] Summarize what changed and any remaining gaps
- [ ] Deliver to user
- **Status:** in_progress

## Key Questions
1. Which existing product surfaces can absorb these capabilities without disrupting the current optimizer and evaluation loop?
2. What is the smallest valuable implementation slice that expresses the competitor-inspired UX while staying cohesive with the current app?
3. How should transcript ingestion, analytics, and change application connect to the existing data model and UI flows?

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Treat `/Users/andrew/Desktop/AutoAgent-VNextCC` as the target repo | It is the most recently modified matching product and its README aligns with the requested feature direction |
| Create planning files manually | The `session-catchup.py` helper exited without output, so manual setup is safer than repeating a failing action |
| Add a dedicated `/intelligence` workspace instead of overloading a single existing page | This keeps the current golden path intact while giving the new transcript and prompt-to-agent workflows a cohesive home |
| Implement transcript intelligence as a backend service plus API routes that feed existing review models | This keeps the feature additive and lets transcript-derived recommendations flow through the current `ChangeCardStore` and review UI |
| Repair the unfinished NL editor and diagnose/change-review contract mismatches while adding the new feature slice | The repo already had partial natural-language infrastructure, but it was unreliable until those contracts were aligned |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| `session-catchup.py` exited with code `-1` and no output | 1 | Switched to manual planning file creation and logged the issue for traceability |
| Global `web` lint/build checks fail in unrelated pre-existing files | 1 | Verified touched frontend files separately and recorded the wider repo blockers in `progress.md` instead of refactoring unrelated surfaces |

## Notes
- Preserve the current optimization loop and existing golden path as the primary constraint.
- Favor additive navigation and workflow entry points over replacing existing pages or interaction patterns.
- The implemented slice centers on a new Intelligence Studio, transcript archive ingestion, report-driven agent updates, and prompt-to-agent artifact generation.
- Final delivery should call out that backend tests passed and the touched frontend files verified cleanly, while the full frontend lint/build remains blocked by unrelated existing issues.
