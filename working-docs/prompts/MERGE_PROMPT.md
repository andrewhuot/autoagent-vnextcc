# AutoAgent VNextCC — Merge CC + Codex v4 Research Ports

## Mission

You have two parallel implementations of the same v4 research port. Merge the best of both into one production-grade result. CC Opus is the backbone; Codex contributions are folded in.

## The Two Builds

**CC Opus (this repo, current branch `feat/p0-architectural-overhaul`):**
- 326 tests passing
- Modular architecture: separate `optimizer/bandit.py` (170 lines), `optimizer/curriculum.py` (189 lines), `optimizer/holdout.py` (247 lines)
- 3 new frontend components: `DimensionBreakdown.tsx`, `ParetoFrontierView.tsx`, `SearchStrategyBadge.tsx`
- `AdaptiveSearchEngine` subclass pattern
- Loop.py is light (174 lines) — strategy routing not fully wired

**Codex (at `/Users/andrew/Desktop/AutoAgent-VNextCC-Codex/`):**
- 208 tests passing
- `evals/anti_goodhart.py` (145 lines) — clean single-class guard combining holdout rotation, drift detection, judge variance
- `optimizer/loop.py` (494 lines) — fully wired strategy routing (simple/adaptive/full)
- `autoagent.yaml` has all config knobs (search_strategy, bandit_policy, holdout thresholds, drift_threshold, max_judge_variance)
- `CHANGELOG.md` — comprehensive v2.0.0 + v2.1.0 entries
- New API endpoint: `GET /api/optimize/pareto`
- Strategy diagnostics in optimize API responses

## What to Merge FROM Codex INTO CC

1. **`evals/anti_goodhart.py`** — Copy it in. CC's holdout.py stays too (more detailed), but anti_goodhart.py provides the clean single-class guard API that the loop should use.

2. **`optimizer/loop.py` strategy routing** — Port Codex's full strategy-aware loop into CC's loop.py. The key additions:
   - `SearchStrategy` enum routing (simple → existing proposer, adaptive → HSO + bandit, full → HSO + curriculum + Pareto)
   - `StrategyDiagnostics` dataclass
   - Anti-Goodhart guard integration in the loop
   - Wire it to use CC's existing `bandit.py`, `curriculum.py`, `holdout.py` modules (not Codex's inline versions)

3. **`autoagent.yaml` config additions** — Add search_strategy, bandit_policy, search budget limits, anti-Goodhart thresholds to the config schema. Update `agent/config/runtime.py` and `agent/config/schema.py` as needed.

4. **`CHANGELOG.md`** — Copy Codex's changelog, update it to reflect the merged state.

5. **`GET /api/optimize/pareto` endpoint** — Port the Pareto front API endpoint and strategy diagnostics into the API.

6. **Codex's `EvalDetail.tsx` and `Optimize.tsx` enhancements** — Check if Codex added anything useful to these pages that CC doesn't have (9-dimension panel, Pareto front panel, strategy diagnostics). Merge any improvements, but prefer CC's dedicated components where they exist.

## What to KEEP from CC (do not overwrite)

- All test files (CC has 326 tests — preserve every one)
- `optimizer/bandit.py`, `optimizer/curriculum.py`, `optimizer/holdout.py` — CC's modular decomposition
- `optimizer/search.py` with `AdaptiveSearchEngine` — CC's version
- `web/src/components/DimensionBreakdown.tsx`, `ParetoFrontierView.tsx`, `SearchStrategyBadge.tsx`
- `evals/scorer.py` — CC's version (already has 9 dimensions + per-agent)
- `evals/statistics.py` — CC's version
- `optimizer/pareto.py` — CC's version

## Execution Plan

1. Read both codebases thoroughly — understand every difference
2. Copy `evals/anti_goodhart.py` from Codex
3. Rewrite `optimizer/loop.py` to incorporate Codex's strategy routing while using CC's modules
4. Update config schema + autoagent.yaml
5. Port Pareto API endpoint
6. Port any frontend improvements from Codex
7. Add CHANGELOG.md
8. Write tests for any new integration code (anti_goodhart tests, loop strategy tests)
9. Run FULL test suite — all 326+ tests must pass
10. Build frontend — must be clean
11. Commit: `feat: merge CC + Codex v4 research ports — [summary]`

## Constraints

- ALL 326 existing CC tests must still pass after merge
- No breaking changes to existing APIs
- Gemini-first, single-process, SQLite, no new deps
- Frontend must build clean (TypeScript strict)
- `autoagent run` with `search_strategy: simple` must work identically to before

## When Done

Run: `openclaw system event --text "Done: CC+Codex merge — [test count] tests, [summary of what was merged]" --mode now`
