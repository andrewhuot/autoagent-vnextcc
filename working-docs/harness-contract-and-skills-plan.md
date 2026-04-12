# Harness Contract & Skills Integration — Implementation Plan

**Date**: 2026-04-12
**Branch**: feat/harness-contract-and-skills-claude

## Deliverables

### D1. `BUILDER_CONTRACT.md` (new file, repo root)
The builder/model-harness behavior contract. Defines:
- Builder identity and role within the harness
- Startup sequence (what to read first)
- Loop phases (plan, execute, reflect, present)
- Persistence guarantees (checkpointing, state envelope)
- Completion criteria (what counts as done)
- Verification model (reflection, quality gates)
- Recovery and handoff behavior
- Skill treatment (build-time vs runtime, how each is loaded/surfaced)

### D2. Contract loader (`builder/contract.py`, new file)
- Parses `BUILDER_CONTRACT.md` extracting structured sections
- Exposes `load_builder_contract()` → `BuilderContract` dataclass
- Used by the harness at startup to surface contract metadata in events
- Not enforcement (yet) — visibility and truthfulness first

### D3. Skill context in harness (`builder/harness.py`, modified)
- At startup: load available skills from `SkillStore` (if available)
- Classify loaded skills as build-time or runtime
- Include `skill_context` in plan and execution events
- Tag artifacts with `skill_layer: "build" | "runtime" | "none"`
- Emit `skill_context` summary in `build.completed` event

### D4. Shared contract updates (`shared/contracts/`, modified)
- Add `skill_layer` field to `SkillRecord` (Python + TypeScript)
- Add `skill_context` field to `BuildArtifact` contract (Python + TypeScript)

### D5. API event enrichment (`api/routes/workbench.py`, minimal changes)
- `build.completed` event now includes skill context summary
- No new endpoints needed — context flows through existing SSE stream

### D6. Frontend skill layer indicator (`web/src/`, modified)
- Add `SkillLayerBadge` component showing build/runtime/none on artifacts
- Surface skill context summary in the workbench activity panel
- Add skill layer column to artifact list in the workbench store

### D7. Tests (new + modified)
- `tests/test_builder_contract.py` — contract loading and parsing
- `tests/test_harness.py` — extend existing tests for skill context in events
- `web/src/lib/workbench-store.test.ts` — extend for skill layer state

## File Change Map

| File | Action | Scope |
|------|--------|-------|
| `BUILDER_CONTRACT.md` | Create | Full contract definition |
| `builder/contract.py` | Create | Contract loader (~100 lines) |
| `builder/harness.py` | Modify | Add skill context loading + event enrichment |
| `shared/contracts/skill_record.py` | Modify | Add `skill_layer` field |
| `shared/contracts/skill-record.ts` | Modify | Add `skill_layer` field |
| `shared/contracts/build_artifact.py` | Modify | Add `skill_context` field |
| `shared/contracts/build-artifact.ts` | Modify | Add `skill_context` field |
| `web/src/components/SkillLayerBadge.tsx` | Create | Small badge component |
| `web/src/lib/workbench-store.ts` | Modify | Add skill context to state |
| `web/src/lib/workbench-api.ts` | Modify | Add skill types |
| `tests/test_builder_contract.py` | Create | Contract loader tests |
| `tests/test_harness.py` | Modify | Skill context event tests |
| `web/src/lib/workbench-store.test.ts` | Modify | Skill context state tests |

## Verification Ladder

1. `pytest tests/test_builder_contract.py -v` — contract loads and parses
2. `pytest tests/test_harness.py -v` — harness emits skill context
3. `pytest tests/test_skills_api.py -v` — skills API still works
4. `cd web && npx vitest run` — frontend tests pass
5. `cd web && npx vite build` — frontend builds cleanly

## Risks

| Risk | Mitigation |
|------|------------|
| SkillStore import in harness creates hard dependency | Optional import with graceful fallback |
| Contract file gets stale vs code | Contract defines principles, not line-by-line behavior |
| Skill context adds noise to events | Only added as metadata fields, not changing event shape |
| Frontend changes break existing workbench | Additive only — badge is a new component, state fields are optional |

## Non-goals (explicit)
- Automatic skill application during harness execution
- Skill-driven mutation of the builder loop
- Enforcement engine that blocks builds on contract violations
- Changes to the optimizer or skill engine internals
