# R2 Handoff Prompt — Unified Improve Loop

Paste the block below into a fresh Claude Code session at the repo root
(`/Users/andrew/Desktop/agentlab`).

---

## Session prompt

You are picking up the AgentLab roadmap at **R2 — Unified Improve Loop**. R1
("Trust the Loop") shipped on branch `claude/elastic-sutherland` in 14
commits (`433e803` → `1ac4409`). R2 is a separate, large release and gets
its own session for clean context.

### What R1 shipped (context, don't re-do)

R1 turned every silent mock fallback into a loud, actionable signal:

- `cli/exit_codes.py` — `EXIT_MOCK_FALLBACK=12`, `EXIT_DEGRADED_DEPLOY=13`, `EXIT_MISSING_PROVIDER=14`
- `cli/strict_live.py` — `StrictLivePolicy`, `MockFallbackError`
- `--strict-live` flag on `eval run`, `build`, `optimize`
- `Proposer()` now defaults to live (was `use_mock=True`)
- `optimizer/gates.py` — `RejectionReason` enum + `RejectionRecord` dataclass + `rejection_from_status()` helper
- `optimizer/loop.py` — `Optimizer.recent_rejections(limit=None)` ring buffer; `attempt_id` on `RejectionRecord` matches the persisted `OptimizationAttempt.attempt_id`
- `agentlab improve list` — un-hidden, REASON column, `--reason` filter, `AGENTLAB_TEST_FORCE_REJECTION` env hook
- `agentlab deploy` — blocks on Degraded/Needs-Attention verdict; `--force-deploy-degraded --reason "<≥10 chars>"` override
- `cli/provider_keys.py` — validates pasted keys; `InitFlow(interactive=True|False)`; onboarding retries 3×
- `agentlab doctor` — distinguishes `disabled` / `configured` / `missing_provider_key` (via `cli/mock_reason.py`)

80+ new tests. Full commit list: `git log --oneline 5a33a80..1ac4409` on
`claude/elastic-sutherland`.

### Your job

Ship **R2** following the same subagent-driven TDD pattern as R1:

- Fresh subagent per task, full task text + code in the dispatch prompt
- Each subagent uses `uv run pytest` (project requires Python 3.10+)
- Every task: failing test → minimal impl → passing test → conventional commit
- Mark TodoWrite tasks complete immediately; don't batch
- Verify assumptions (file line numbers, function signatures) before writing the dispatch prompt — R1 had several moments where the master plan was stale

### Before dispatching anything

1. **Read the R2 scaffold in the master plan** at
   `docs/superpowers/plans/2026-04-16-agentlab-roadmap-master.md:1187-1239`
   (lines 1187–1239). It lists 19 tasks, risks, and acceptance tests.

2. **Expand R2 into its own TDD plan file** at
   `docs/superpowers/plans/2026-04-17-agentlab-r2-improve-loop.md`.
   The master plan explicitly says R2 must be expanded before execution.
   Use R1's plan section as a template — exact file paths, code snippets in
   each step, exact pytest commands. Commit this plan file by itself
   (`docs: expand R2 TDD plan`) before any code.

3. **Split R2 into three dispatchable slices.** Don't try to ship all 19
   tasks in one session. Suggested slicing:

   - **Slice A — Lineage store** (R2.1–R2.5): new SQLite store, emit from
     eval/optimize/deploy. Additive, self-contained, unblocks the rest.
   - **Slice B — `improve` commands** (R2.6–R2.11): extract `improve` into
     `cli/commands/improve.py` and build `run/accept/measure/diff/lineage`
     subcommands on top of the lineage store.
   - **Slice C — runner.py refactor** (R2.12–R2.16): extract
     build/eval/optimize/deploy groups into `cli/commands/*.py`.
     High-risk surgical moves — one group per dispatch, verify `agentlab
     --help` stays stable via golden-file snapshot between each.

   R2.17 (workbench slash parity), R2.18 (lineage backfill), R2.19 (docs)
   come after Slice C.

4. **Confirm with the user which slice to start with.** Default to Slice A.

### Critical invariants R2 must preserve

- **No regressions in R1's strict-live policy.** Every new command path
  that executes a proposer/eval must honor `--strict-live` if already
  wired; additions should plumb it through.
- **`attempt_id` is the lineage key.** R1 already matches
  `RejectionRecord.attempt_id` to `OptimizationAttempt.attempt_id`. R2's
  lineage table uses the same id — don't introduce a second identifier.
- **runner.py extractions must be byte-identical in behavior.** Use a
  golden-file test on `agentlab --help` output before and after each
  extraction. If output drifts, fix before committing.
- **Don't break the hidden `improve run` compat alias** at
  `runner.py:4927`. The new first-class `improve` command replaces it,
  but scripts depending on the alias must keep working.

### Architectural decisions the master plan defers to you

- **Lineage table location**: master plan says
  `.agentlab/improvement_lineage.db`. R1's `improve list` already references
  `AGENTLAB_IMPROVEMENT_LINEAGE_DB` env var at `runner.py:5047` and uses
  `optimizer/improvement_lineage.py` (`ImprovementLineageStore`). Check
  whether that existing store can be extended vs. whether R2 needs a new
  one. If the existing one fits, extend it — don't duplicate.
- **Migration strategy for orphan eval runs** (R2.18): idempotent
  backfill on first lineage write. Keep it simple — glob for existing
  eval artifacts, hash their attempt_id, insert if absent.

### Workflow

1. Create a new worktree: `git worktree add .claude/worktrees/<new-name> -b claude/r2-improve-loop master` (branch from master, not from the R1 branch — R1 will be merging via PR separately).
2. Or continue on `claude/elastic-sutherland` if the user prefers stacked branches. Ask.
3. Follow `superpowers:subagent-driven-development` — dispatch one subagent per task, don't implement in the main thread.
4. After each slice, offer to open a PR before moving to the next.

### If you get stuck

- Stale line numbers in the master plan: verify with `Read` before dispatching.
- Subagent hits Python 3.9 on the host: tell it to use `uv run python` / `uv run pytest`.
- Pre-existing failing tests (`test_full_loop_observe_optimize_deploy_promote`, starlette/httpx collection errors in API tests): note them and move on — R1 session already flagged these as pre-existing.

### First action

After the user confirms they want to start, read the master plan's R2
section, write the expansion plan to
`docs/superpowers/plans/2026-04-17-agentlab-r2-improve-loop.md`, commit it,
then ask which slice (A/B/C) to execute first.

Use superpowers and TDD. Work in subagents. Be specific.
