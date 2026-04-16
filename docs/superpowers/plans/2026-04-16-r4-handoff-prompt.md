# R4 Handoff Prompt — Workbench is the Harness

Paste the block below into a fresh Claude Code session at the repo root
(`/Users/andrew/Desktop/agentlab`).

**Prerequisites (all confirmed shipped on master as of 2026-04-16):**
- **R1** ✅ — strict-live policy through `1ac4409`
- **R2** ✅ — merged at `6a0f242` (lineage store + `agentlab improve`
  group + `cli/commands/*.py` split)
- **R3** ✅ — merged at `47ff7f8` (smart optimizer)

R4 can run in parallel with R5 (Eval Corpus) — they touch disjoint
code. R4 should land before R6 and R7.

---

## Session prompt

You are picking up the AgentLab roadmap at **R4 — Workbench is the
Harness**. R1, R2, and R3 have shipped on master. R4 is a separate,
large release and gets its own session for clean context.

### What already shipped (context, don't re-do)

**R1 (`433e803` → `1ac4409`):** strict-live policy, exit codes,
rejection records, deploy verdict gate, provider-key validation.

**R2 (merged at `6a0f242`):** lineage store with full
`eval_run_id → attempt_id → deployment_id → measurement_id` chain,
`agentlab improve {run,accept,measure,diff,lineage}` command group,
runner.py split into `cli/commands/{build,eval,optimize,deploy,improve}.py`,
workbench `/improve` slash parity.

**R3 (merged at `47ff7f8`):** coverage-aware proposer, reflection
feedback, configurable composite weights with per-run snapshotting,
LLM-backed pairwise judge with heuristic fallback, `agentlab eval
weights` subcommand, bootstrap CI + paired significance.

### Your job

Ship **R4** following subagent-driven TDD:

- Fresh subagent per task, full task text + code in the dispatch prompt
- Each subagent uses `uv run pytest` (project requires Python 3.10+)
- Every task: failing test → minimal impl → passing test → conventional commit
- Mark TodoWrite tasks complete immediately; don't batch
- Verify assumptions (file line numbers, function signatures) before
  dispatching

### R4 goal

Workbench owns session state. Slash commands call command
implementations **directly in-process** (no `stream_subprocess`),
automatically share `eval_run_id` / `attempt_id` across steps, render
rich progress widgets, show lineage and diffs, and gracefully surface
uncaught exceptions instead of crashing.

### Before dispatching anything

1. **Read the R4 scaffold in the master plan** at
   `docs/superpowers/plans/2026-04-16-agentlab-roadmap-master.md:1296-1346`
   (14 tasks, acceptance tests, risks).

2. **Expand R4 into its own TDD plan file** at
   `docs/superpowers/plans/2026-04-XX-agentlab-r4-workbench-harness.md`.
   Use R1's plan section as the template shape — exact file paths, code
   in each step, exact pytest commands. Commit the plan alone
   (`docs: expand R4 TDD plan`) before any code.

3. **Verify the current state of these files before writing dispatch prompts:**
   - `cli/workbench_app/runtime.py` — how does `stream_subprocess` currently work? Where's the call site for each slash command?
   - `cli/workbench_app/{eval,optimize,build,deploy}_slash.py` — current shape of each slash command. They likely spawn subprocesses today; you'll swap that for direct function calls against `cli/commands/*`.
   - `cli/workbench_app/improve_slash.py` — exists after R2; verify shape.
   - Textual version pinned in `pyproject.toml` — snapshot testing uses `pilot.snap`; confirm API.
   - Existing widget patterns under `cli/workbench_app/` — match the codebase's Textual idioms, don't invent new ones.

4. **Split R4 into three dispatchable slices.** Don't try to ship all
   14 tasks in one session.

   - **Slice A — Session state + in-process refactor** (R4.1–R4.6):
     `WorkbenchSession` dataclass, then refactor each slash command from
     subprocess to in-process, one at a time. Snapshot
     `agentlab --help` equivalent — confirm slash command user-facing
     behavior is byte-identical before/after each refactor.
   - **Slice B — Rich widgets** (R4.7–R4.9): eval case grid, failure
     preview cards, cost ticker. Each is a new Textual widget with
     `pilot.snap` tests.
   - **Slice C — Diff/lineage views + error boundaries** (R4.10–R4.13):
     `/diff <attempt_id>`, `/lineage <id>`, inline-edit accept,
     per-command error boundaries.

   R4.14 (docs) comes after Slice C.

5. **Confirm with the user which slice to start with.** Default to Slice A.

### Critical invariants R4 must preserve

- **Slash commands stay user-visible identical.** After Slice A,
  `/eval`, `/build`, `/optimize`, `/improve`, `/deploy` produce the same
  output the user saw pre-refactor. Subprocess → in-process is an
  implementation change, not a UX change. Snapshot the rendered output
  before refactoring each command.
- **Error boundaries are non-negotiable.** In-process execution means
  an uncaught exception in an eval path now lives in the same Python
  process as the TUI. Every slash handler must be wrapped so a crash
  renders an error card; the TUI stays interactive. R4.13 exists
  because this is a real regression risk — do NOT ship Slice A without
  at least a stub error boundary around each refactored handler.
- **Session state is thread-safe.** Textual worker threads may touch
  `WorkbenchSession` concurrently. Use `threading.Lock` around
  mutating accessors. Test concurrent writes don't corrupt.
- **No silent ID passing.** If a slash command needs an
  `eval_run_id` / `attempt_id` and the session doesn't have one,
  surface a clear error ("run `/eval` first") rather than using a
  stale or default id.
- **Strict-live still applies.** `--strict-live` behavior from R1 must
  work through the in-process path — when the session is strict-live,
  a mock fallback inside the refactored handler still hard-fails with
  exit semantics equivalent to the CLI path (raise
  `MockFallbackError`, don't just log).

### Architectural decisions the master plan defers to you

- **`WorkbenchSession` shape:** at minimum
  `current_config_path`, `last_eval_run_id`, `last_attempt_id`,
  `cost_ticker`. Add fields only when a slash command concretely needs
  one. Persist to `.agentlab/workbench_session.json` on shutdown if
  users expect session resume — confirm with user before adding
  persistence.
- **In-process invocation shape:** the R2 `cli/commands/*.py` modules
  should expose callable entry points (not just Click commands). If
  they don't, part of R4.2 is refactoring the command module to
  separate "the business logic function" from "the Click wrapper."
  The Click wrapper calls the function; the slash handler also calls
  the function. Don't invoke Click programmatically — call the pure
  function.
- **Cost ticker source:** start with model-name-based estimates from a
  price table (e.g. `pricing.py`). Upgrade to real token counts when
  provider responses include usage metadata. Don't block R4.9 on
  perfect cost tracking.
- **Diff view layout (R4.10):** two panes (before / after config
  YAML), plus a third pane for eval delta if the attempt has a
  measurement. Textual `Horizontal` with three children.
- **Lineage view layout (R4.11):** tree or timeline. A DAG visualizer
  is nice-to-have but expensive — pick the simpler layout that makes
  `eval_run → attempt → deployment → measurement` legible.
- **Inline edit (R4.12):** open the proposal diff in a Textual
  `TextArea` widget pre-populated with the candidate config; on submit,
  save to a scratch file and pass that to the in-process accept call.

### Workflow

1. Create a new worktree:
   `git worktree add .claude/worktrees/<r4-name> -b claude/r4-workbench-harness master`
2. Follow `superpowers:subagent-driven-development` — dispatch one
   subagent per task, don't implement in the main thread.
3. After each slice, offer to open a PR before moving to the next.

### If you get stuck

- Stale line numbers in the master plan: verify with `Read` before dispatching.
- Subagent hits Python 3.9 on the host: tell it to use `uv run python` / `uv run pytest`.
- `pilot.snap` snapshot drift: re-record intentional changes; investigate unintended ones.
- Pre-existing failing tests (starlette/httpx collection errors in API
  tests): note them and move on — not R4's problem.
- Textual worker thread quirks: if a widget update races with session
  mutation, prefer `post_message` over direct attribute writes.

### First action

After the user confirms they want to start, read the master plan's R4
section, read the workbench slash files listed above to ground-truth
assumptions, write the expansion plan, commit it, then ask which slice
(A/B/C) to execute first.

Use superpowers and TDD. Work in subagents. Be specific.
