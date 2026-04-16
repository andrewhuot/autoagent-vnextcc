# R3 Handoff Prompt — Optimizer that Learns

Paste the block below into a fresh Claude Code session at the repo root
(`/Users/andrew/Desktop/agentlab`).

**Prerequisite:** R1 is merged to master. R2 should be merged before R3
(R3 builds on the modular command layout R2 extracts, but does not hard-
require R2's lineage store — it reads from the already-existing
reflection and coverage stores).

---

## Session prompt

You are picking up the AgentLab roadmap at **R3 — Optimizer that Learns**.
R1 ("Trust the Loop") and R2 ("Unified Improve Loop") have already shipped
on master. R3 is a separate, large release and gets its own session for
clean context.

### What already shipped (context, don't re-do)

**R1** (commits `433e803` → `1ac4409`):
- Strict-live policy, exit codes (12/13/14), rejection records, deploy
  verdict gate, provider-key validation, doctor tri-state mock reason.
- `optimizer/gates.py` now has `RejectionReason`, `RejectionRecord`,
  `rejection_from_status()`.
- `Optimizer.recent_rejections(limit=None)` ring buffer exists; every
  rejection's `attempt_id` matches the persisted `OptimizationAttempt`.

**R2** (look at `git log` on master — commit range begins after `1ac4409`):
- Lineage store (`optimizer/lineage.py` or extended
  `optimizer/improvement_lineage.py`) with full
  `eval_run_id → attempt_id → deployment_id → measurement_id` chain.
- Canonical `agentlab improve` command group in `cli/commands/improve.py`
  with `run / accept / measure / diff / lineage` subcommands.
- runner.py split into `cli/commands/*.py` modules
  (build, eval, optimize, deploy, improve).
- Workbench `/improve` slash parity.

### Your job

Ship **R3** following subagent-driven TDD:

- Fresh subagent per task, full task text + code in the dispatch prompt
- Each subagent uses `uv run pytest` (project requires Python 3.10+)
- Every task: failing test → minimal impl → passing test → conventional commit
- Mark TodoWrite tasks complete immediately; don't batch
- Verify assumptions (file line numbers, function signatures) before
  dispatching — master plan scaffolds are a starting point, not gospel

### R3 goal

Optimizer uses coverage data to target proposals, reads back its own
reflection learnings, auto-grows the eval suite when coverage is thin,
and uses an LLM-backed pairwise judge. Composite weights become per-
workspace config.

### Before dispatching anything

1. **Read the R3 scaffold in the master plan** at
   `docs/superpowers/plans/2026-04-16-agentlab-roadmap-master.md:1243-1292`
   (14 tasks, acceptance tests, risks).

2. **Expand R3 into its own TDD plan file** at
   `docs/superpowers/plans/2026-04-XX-agentlab-r3-smart-optimizer.md`.
   Use R1's plan section (in the same master file) as a template — exact
   file paths, code in each step, exact pytest commands. Commit this plan
   alone (`docs: expand R3 TDD plan`) before any code.

3. **Verify the current state of these files before writing dispatch prompts:**
   - `optimizer/llm_proposer.py` — does `_build_proposer_context()` exist? what's the current prompt shape?
   - `optimizer/proposer.py` — does `_rank_strategies()` exist?
   - `optimizer/reflection.py` — what's the current schema? add `read_surface_effectiveness(surface)` consistently.
   - `evals/judges/pairwise_judge.py` — the heuristic path is there; the LLM structured-output path needs adding.
   - `evals/scorer.py` — where are composite weights currently defined? Are they hardcoded constants or already config-driven somewhere?
   - `evals/statistics.py` — `paired_significance()` exists; needs bootstrap CI addition.

4. **Split R3 into two dispatchable slices.** Don't try to ship all 14
   tasks in one session.

   - **Slice A — Coverage-aware proposer + reflection feedback** (R3.1–R3.6):
     proposer reads coverage and reflection, cycle auto-grows coverage.
     Self-contained; unblocks Slice B's LLM judge work.
   - **Slice B — LLM judge + configurable weights + statistics** (R3.7–R3.13):
     pairwise judge goes from heuristic to LLM-with-heuristic-fallback;
     composite weights move to yaml; bootstrap CI added.

   R3.14 (docs) comes after Slice B.

5. **Confirm with the user which slice to start with.** Default to Slice A.

### Critical invariants R3 must preserve

- **Epsilon-greedy exploration.** R3.4 (proposer ranks by reflection
  effectiveness) has a feedback-loop risk. Don't let the proposer always
  pick the top-ranked strategy — reserve ~10% of cycles for random
  exploration. Test this explicitly with a deterministic seed.
- **Historical score reproducibility.** R3.11 says snapshot composite
  weights per eval run. When rerunning a historical eval, use the
  snapshotted weights, not the current yaml values. This is back-compat,
  not polish.
- **LLM judge costs money.** R3.7 requires caching
  `(input_a, input_b, output_a, output_b) → verdict` with 30-day TTL.
  Do NOT dispatch the LLM-judge task without the caching wired in first.
- **Heuristic judge stays as fallback.** When the LLM call fails or is
  unconfigured, fall back to heuristic. Users must be able to run evals
  without a provider key for the judge.
- **Strict-live still applies.** If the user passed `--strict-live`, a
  missing LLM judge provider key must hard-fail, not silently fall back.

### Architectural decisions the master plan defers to you

- **Coverage gap signal shape** (R3.1): master plan says
  `CoverageAnalyzer.gap_signal()` returns
  `[(surface, severity, recommended_cases), ...]`. Verify
  `CoverageAnalyzer` is at `evals/coverage_analyzer.py` and pick field
  names consistent with the existing API.
- **Reflection schema** (R3.3): `surface_learnings` table doesn't
  necessarily exist yet. If it doesn't, design the schema as part of
  R3.3 and write a migration. Keep it simple: `(surface, strategy,
  effectiveness_score, sample_count, updated_at)`.
- **Weights validation** (R3.10): weights must sum to 1.0. Use absolute
  tolerance ≤ 1e-6 for float comparison; round-trip yaml.
- **LLM judge cache location**: default `.agentlab/llm_judge_cache.db`.
- **`--explain-strategy` output format** (R3.5): plain text, one line
  per selected strategy: "selected mutation X because effectiveness=0.7
  on similar surfaces (n=12 samples)". JSON flag optional.

### Workflow

1. Create a new worktree:
   `git worktree add .claude/worktrees/<r3-name> -b claude/r3-smart-optimizer master`
2. Follow `superpowers:subagent-driven-development` — dispatch one
   subagent per task, don't implement in the main thread.
3. After each slice, offer to open a PR before moving to the next.

### If you get stuck

- Stale line numbers in the master plan: verify with `Read` before dispatching.
- Subagent hits Python 3.9 on the host: tell it to use `uv run python` / `uv run pytest`.
- Pre-existing failing tests (starlette/httpx collection errors in API
  tests): note them and move on — not R3's problem.
- Reflection table schema drift: if the existing schema diverges from
  what the master plan assumes, adapt the plan, don't force the schema.

### First action

After the user confirms they want to start, read the master plan's R3
section, read the four proposer/judge/scorer/reflection files listed
above to ground-truth assumptions, write the expansion plan, commit it,
then ask which slice (A/B) to execute first.

Use superpowers and TDD. Work in subagents. Be specific.
