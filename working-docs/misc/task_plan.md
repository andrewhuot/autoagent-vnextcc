# Task Plan: Builder Rebuild Completion

## Goal
Finish the in-progress single-screen conversational builder rebuild by verifying the existing frontend/backend work, fixing broken behavior, validating the `/build` flow in a real browser, adding end-to-end coverage, cleaning up obsolete builder routes/pages if fully replaced, then committing and sending the requested completion event.

## Current Phase
Phase 1

## Phases
### Phase 1: Context Sync & Code Review
- [x] Recover prior-session context
- [x] Sync planning files to this task
- [ ] Read all builder-related code that was already created
- [ ] Identify old builder pages/routes that may now be dead
- **Status:** in_progress

### Phase 2: Baseline Verification
- [ ] Run `cd web && npx tsc --noEmit`
- [ ] Run `cd web && npx vitest run src/pages/Builder.test.tsx`
- [ ] Run `python -m pytest tests/test_builder_chat_api.py`
- [ ] Record failures and likely root causes
- **Status:** pending

### Phase 3: Runtime Debugging & Fixes
- [ ] Launch frontend and backend locally
- [ ] Exercise `/build` from the sidebar with Playwright
- [ ] Fix chat, config preview, export/download, redirects, and responsive issues
- [ ] Remove dead old builder pages if the new flow fully replaces them
- **Status:** pending

### Phase 4: Automated Coverage
- [ ] Add a Playwright E2E test for the full builder flow
- [ ] Re-run targeted frontend/backend/browser verification
- **Status:** pending

### Phase 5: Delivery
- [ ] Review diff
- [ ] Commit with `feat(builder): complete single-screen conversational builder rebuild`
- [ ] Run requested `openclaw system event ...` command
- **Status:** pending

## Key Questions
1. Does the current code compile and pass the targeted frontend/backend tests?
2. Is the `/build` experience wired correctly end-to-end to the new chat API?
3. Which older builder pages/routes are still reachable and should redirect or be removed?
4. What is missing from automated coverage after the manual Playwright pass?

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Keep the already-started builder implementation and finish it in place | The user explicitly asked to continue the existing rebuild rather than replace it |
| Use real compile/test/browser validation before making claims | The requested finish criteria are behavioral, not just code-complete |
| Preserve unrelated worktree state | Repo-level instructions prohibit reverting unrelated changes |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| Planning files were from an unrelated docs task | 1 | Replaced them with builder-task tracking before proceeding |

## Notes
- Use Playwright iteratively: launch, test, fix, repeat.
- Keep UI aligned with existing app tokens and patterns rather than inventing a new design system.
- Do not remove legacy builder pages until redirects and feature replacement are confirmed.
