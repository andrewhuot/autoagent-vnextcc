# Merge Strategy — Assistant + Skills + Platform Features

## Current State

Master (`~/Desktop/AutoAgent-VNextCC/`) has:
- CC Assistant (committed in `04808ad`)
- 7 Platform Features (committed in `04808ad`)
- 12 pre-existing test failures in `tests/test_magic_ux.py`
- Some unstashed work from platform features session (run `git stash pop` first)

CC Skills (`~/Desktop/AutoAgent-VNextCC-Skills/`) has:
- `core/skills/` — 7 files, 3,684 lines (types, store, loader, composer, validator, marketplace)
- `assistant/` — 10 files, 4,029 lines (orchestrator, builder, explorer, etc.)
- `agent/skill_runtime.py` — runtime skill integration
- `optimizer/skill_engine.py` — build-time skill engine
- `cli/skills.py` — CLI skill commands
- Modified files: `optimizer/loop.py`, `optimizer/memory.py`, `registry/skill_store.py`, `agent_skills/store.py`, `api/routes/skills.py`, `api/server.py`, `api/models.py`, `runner.py`, `agent/config/schema.py`
- Frontend: modified `Skills.tsx`, `Sidebar.tsx`, `Layout.tsx`, `App.tsx`, `types.ts`
- 24 test files for skills + assistant
- 2 collection errors in `test_skills_routes.py` need fixing

Codex (`~/Desktop/AutoAgent-VNextCC-Codex8/`) has:
- Same `core/skills/` structure (7 files)
- Same `assistant/` structure (9 files)
- 11 frontend assistant components (vs CC's 14)
- `web/src/lib/api.ts` hooks for skills
- 3 test files for skills

## Merge Steps

### Step 1: Pop stashed work on master
```
git stash pop
```
Commit any remaining platform features work.

### Step 2: Fix pre-existing test failures
Fix the 12 failures in `tests/test_magic_ux.py` — these are NameError and assertion failures unrelated to new features.

### Step 3: Port CC Skills core module
From `~/Desktop/AutoAgent-VNextCC-Skills/`, copy:
- `core/skills/` directory (entire — types.py, store.py, loader.py, composer.py, validator.py, marketplace.py, __init__.py)
- `agent/skill_runtime.py`
- `optimizer/skill_engine.py`
- `cli/` directory (skills CLI)

### Step 4: Port CC Skills modifications
From `~/Desktop/AutoAgent-VNextCC-Skills/`, apply changes to:
- `optimizer/loop.py` — skill-driven optimization integration
- `optimizer/memory.py` — skill effectiveness tracking
- `registry/skill_store.py` — migration to use core/skills/store
- `agent_skills/store.py` — migration to use core/skills/store
- `api/routes/skills.py` — new skill endpoints
- `api/server.py` — register new routes
- `api/models.py` — skill models
- `runner.py` — skill CLI commands
- `agent/config/schema.py` — skill config in agent schema

**IMPORTANT:** Master has evolved since Skills branched (has Assistant + 7 Platform Features). Merge carefully — don't overwrite the platform features or assistant code already on master.

### Step 5: Port CC Skills tests
From `~/Desktop/AutoAgent-VNextCC-Skills/`, copy all `tests/test_skill*.py` and `tests/test_core_skill*.py` and `tests/test_cli_skills.py` and `tests/test_optimizer_skill*.py`.

Don't overwrite existing assistant tests already on master.

### Step 6: Cherry-pick Codex frontend
From `~/Desktop/AutoAgent-VNextCC-Codex8/`, check if these are better than what CC produced:
- `web/src/pages/Skills.tsx` — compare CC vs Codex redesign
- `web/src/lib/api.ts` — skill API hooks
- `web/src/lib/types.ts` — skill types
- Any assistant card components that are more polished

### Step 7: Update frontend integration
- Ensure `web/src/App.tsx` has all routes (assistant + all platform feature pages + skills)
- Ensure `web/src/components/Sidebar.tsx` has all nav entries
- Ensure `web/src/components/Layout.tsx` has all page titles

### Step 8: Fix import errors and test failures
- Fix the 2 collection errors from CC Skills tests
- Fix any import conflicts from the merge
- Run `python3 -m pytest tests/ -x -q` iteratively until clean

### Step 9: Final verification
- Run full test suite: `python3 -m pytest tests/ -q`
- Target: significantly more than 2,009 (current master count)
- All new features must have tests

### Step 10: Commit and done
Single merge commit: "feat: merge Skills core primitive + fix test suite"

When completely finished, run: openclaw system event --text "Done: Merged Skills + fixed tests — all features integrated on master" --mode now
