# UX Overhaul Merge: CC Opus backbone + Codex cherry-picks

## Context
Two agents built the same UX Overhaul features independently:
- **CC Opus** (this repo, commit `5e06968`): 1,281 tests, +5,775 lines — the backbone
- **Codex** (`~/Desktop/AutoAgent-VNextCC-Codex5/`, commit `97eb803`): 1,176 tests, +4,429 lines — cherry-pick source

Both started from the same base (commit `0f53eb7` on master).

## Your Job: Cherry-pick 5 things from Codex INTO this repo

### 1. `agent/config/runtime.py` — OptimizationRuntimeConfig + migration
Codex added a Pydantic `OptimizationRuntimeConfig` model with `mode`, `objective`, `guardrails`, `autonomy`, `budget` fields, plus `migrate_legacy_runtime_config()` as a `model_validator(mode="before")` on `RuntimeConfig`. This is better than CC's approach because config migration is baked into the schema layer.

**Action**: Merge Codex's `OptimizationRuntimeConfig`, `OptimizationBudgetConfig`, and `migrate_legacy_runtime_config()` into CC's `agent/config/runtime.py`. Keep CC's existing fields, add the new ones. Make sure `RuntimeConfig` has an `optimization: OptimizationRuntimeConfig` field and the model_validator for auto-migration.

### 2. `registry/playbooks.py` — Builtin playbooks seed data
Codex has 6 `BUILTIN_PLAYBOOKS` entries (fix-retrieval-grounding, reduce-tool-latency, tighten-refusal-policy, improve-routing-accuracy, cut-conversation-cost, onboard-new-agent) with trigger patterns and surface scopes.

**Action**: Add Codex's `BUILTIN_PLAYBOOKS` list to CC's `registry/playbooks.py`. Add a `seed_builtins()` method to `PlaybookStore` that inserts them if they don't already exist.

### 3. `optimizer/proposer.py` — optimization_context injection
Codex modified the proposer to accept `optimization_mode`, `objective`, `guardrails`, and `project_memory_context` kwargs, and injects them as `optimization_context` in the LLM payload.

**Action**: Check if CC's proposer already does this. If not, add similar `optimization_context` injection from Codex's approach. Look at Codex's file at `~/Desktop/AutoAgent-VNextCC-Codex5/optimizer/proposer.py`.

### 4. CLI `--strategy` deprecation warning
Codex's `runner.py` keeps `--strategy` flag but prints a deprecation warning directing users to `--mode`. 

**Action**: If CC's runner doesn't already have this deprecation warning, add it. Check CC's runner.py for the `--strategy` / `--mode` handling and add a `click.echo("⚠️ --strategy is deprecated. Use --mode (standard|advanced|research) instead.", err=True)` warning when `--strategy` is used.

### 5. `web/src/lib/types.ts` — shared UX types
Codex has clean shared type definitions for the new UX features.

**Action**: Compare CC's and Codex's `web/src/lib/types.ts`. If Codex has types CC is missing (especially for modes, playbooks, changes), merge them in. Don't duplicate — just fill gaps.

## After merging

1. Run `python3 -m pytest tests/ -x -q` — must pass (target: ≥1,281)
2. Run `cd web && npx tsc --noEmit` — must pass
3. Commit with message: `feat: UX overhaul merge — CC backbone + Codex config migration, builtin playbooks, proposer context`
4. Push to master

## Important
- Do NOT replace CC's files wholesale. Surgically merge Codex additions into CC's existing code.
- CC's change_card.py (542 lines), sandbox.py (169 lines), project_memory.py (245 lines), and all 3 frontend pages are BETTER — don't touch those.
- If anything conflicts, CC wins.
