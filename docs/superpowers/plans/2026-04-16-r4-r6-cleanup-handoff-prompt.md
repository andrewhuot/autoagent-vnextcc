# R4/R6 Cleanup Handoff Prompt — Close All Roadmap Gaps

Paste the block below into a fresh Claude Code session at the repo root
(`/Users/andrew/Desktop/agentlab`).

**Status:** R1, R2, R3, R5, R7 shipped and complete. R4 shipped Slice A
only (in-process refactor); R6 shipped Slice B only (calibration +
canary). This session closes the remaining gaps in R4 and R6 — the
architectural skeleton is already in place, so these are
surgical additions, not new subsystems. Scoped as **one session, ~2
days of work, ~12–15 commits**.

---

## Session prompt

You are closing out the AgentLab six-release roadmap by finishing the
R4 and R6 gaps that weren't shipped in their parent branches. R1, R2,
R3, R5, R7 are all complete on master. The MVP cut (R1+R2+R3) is
production-ready. This session is pure polish — no new architecture.

### What already shipped (context, don't re-do)

- **R1** (`1ac4409`): strict-live, exit codes, rejection records, deploy verdict gate, provider-key validation.
- **R2** (`6a0f242`): lineage store, `agentlab improve` group, modular `cli/commands/*.py`.
- **R3** (`47ff7f8`): coverage-aware proposer, reflection, composite weights, LLM judge.
- **R4 Slice A** (`a782d33`): `WorkbenchSession` + in-process `/eval`, `/build`, `/optimize`, `/improve`, `/deploy`.
- **R5** (`9ea5098`): dataset tooling, trace ingestion, failure-driven generation.
- **R6 Slice B** (`719edf0`): `improve measure --replay-set`, calibration factor in `--explain-strategy`, canary scoring (`CanaryRouter`, `CanaryScoringAggregator`, `LocalCanaryRouter`).
- **R7** (`5867e5f`): conversational Workbench, tool registry, permissions, persistence, streaming.

### Your job

Ship the 12 remaining gaps (6 in R4 Slices B/C, 6 in R6 Slices A/C) in
one session. Follow subagent-driven TDD:

- Fresh subagent per task; full task text + code in each dispatch prompt
- Each subagent uses `uv run pytest` (project requires Python 3.10+)
- Every task: failing test → minimal impl → passing test → conventional commit
- Mark TodoWrite tasks complete immediately; don't batch
- Verify assumptions (file line numbers, function signatures) before
  dispatching — master plan scaffolds are a starting point, not gospel

### Scope — 12 tasks, two parallel slices

**Slice R4-polish (6 tasks) — Workbench Slices B/C:**

- [ ] **C1 (R4.7)**: Eval case-grid progress widget.
  - File: `cli/workbench_app/eval_progress_grid.py` (create).
  - Renders the 12 (or N) eval cases as a grid, each cell colored by
    verdict (green/red/yellow/grey=pending). Textual widget with
    `pilot.snap` snapshot test at 3/12 complete.
  - Wire into `eval_slash.py` progress callback (the `on_event`
    bridge already exists per the module's docstring).

- [ ] **C2 (R4.8)**: Failure preview cards.
  - File: `cli/workbench_app/failure_card.py` (create).
  - For each failed case in an eval run, render a card with:
    case input, expected, actual, diff, and a one-line
    suggested-fix hint from the existing failure analyzer
    (`optimizer/failure_analyzer.py`).
  - Snapshot test for rendered card content.

- [ ] **C3 (R4.9)**: Cost ticker in Workbench status bar.
  - Modify: `cli/workbench_app/status_bar.py`.
  - Pulls from `WorkbenchSession.cost_ticker` (already tracked per
    R7 C3 for conversation turns; extend to include slash-command
    LLM costs from R4 in-process calls).
  - Test: after 3 known-cost events, status bar reflects sum.
  - DO NOT duplicate logic from R7's `cost_calculator.py` — reuse it.

- [ ] **C4 (R4.10)**: `/diff <attempt_id>` multi-pane viewer.
  - File: `cli/workbench_app/attempt_diff_slash.py` (create).
  - Two panes (baseline config YAML / candidate config YAML) plus a
    third pane showing eval-delta if the attempt has a measurement.
  - Reuses R2's lineage store (`view_attempt`) to fetch the pair.
  - Register in `commands.py`. Don't collide with existing
    `config_diff_slash.py` (that's a different feature — system-prompt
    diff, keep it).
  - Snapshot test + integration test dispatching
    `/diff <known_attempt_id>` in a seeded workspace.

- [ ] **C5 (R4.11)**: `/lineage <id>` ancestry visualizer.
  - File: `cli/workbench_app/lineage_view_slash.py` (create).
  - Renders the `eval_run → attempt → deployment → measurement`
    chain for the given id (accepts any node id; resolves forward
    and backward via the R2 lineage store). Tree layout via Textual
    `Tree`.
  - Snapshot test.

- [ ] **C6 (R4.12)**: Inline edit of proposal before accepting.
  - Modify: `cli/workbench_app/improve_slash.py`.
  - `/improve accept <id> --edit` opens the candidate config in a
    Textual `TextArea` pre-populated with the YAML; on submit, writes
    to a scratch file and calls the existing `run_improve_accept_in_process`
    entry point with the scratch path as the override.
  - Test: `pilot` edits the text, submits, verifies the accept call
    received the edited YAML.

**Slice R6-polish (6 tasks) — R6 Slices A/C:**

- [ ] **C7 (R6.1 polish)**: Un-hide `agentlab loop` group.
  - Modify: `runner.py:3829` and `runner.py:3841`.
  - Remove `hidden=True` from both `@cli.group("loop", ..., hidden=True)`
    and `@loop_group.command("run", hidden=True)`.
  - Verify `agentlab --help` now lists `loop` in the output.
  - Snapshot test update for `--help` output.
  - Add a golden test that `agentlab loop --help` shows the schedule
    modes (continuous/interval/cron).

- [ ] **C8 (R6.2 + R6.3)**: Continuous improvement orchestrator.
  - File: `optimizer/continuous.py` (create).
  - `ContinuousOrchestrator.run_once(workspace, trace_source)`:
    1. Ingest new traces since last watermark via the R5
       trace-converter (already wired through
       `cli/commands/ingest.py`).
    2. Score ingested traces against the workspace's scoring
       config (reuse `evals/runner.py`).
    3. If the median score drops by ≥ threshold vs. the last N
       runs, queue an improvement attempt via the R2 `improve run`
       in-process entry point.
    4. Record a `continuous_cycle` lineage event for traceability.
  - Wire into `loop_group.command("run")` when
    `--schedule continuous` AND a new
    `--trace-source <path>` flag is set. Don't break the existing
    plain optimizer loop; gate the continuous behavior on the flag.
  - Test: seeded workspace + fake trace source + stubbed regression
    → one improvement attempt gets queued, one lineage event written.
  - DO NOT auto-deploy; the orchestrator queues, the user approves.

- [ ] **C9 (R6.4 + R6.5)**: Wire existing notification channels into
  the continuous loop.
  - Modify: `optimizer/continuous.py` (from C8) and
    `notifications/manager.py`.
  - `ContinuousOrchestrator` accepts a `NotificationManager` and
    emits events:
    - `regression_detected` when score drops past threshold
    - `improvement_queued` when an attempt is enqueued
    - `continuous_cycle_failed` on orchestrator errors
  - Dedupe within a 1-hour window per
    `(event_type, workspace, signature)`. Use SQLite
    `notification_log` (create if missing) — do not re-send the same
    alert twice.
  - Test: time-mocked clock, two identical regressions within an
    hour → one Slack send; third after 61 min → send.
  - If `notifications/channels.py::SlackChannel` / `EmailChannel`
    exist from pre-R6 work, reuse them verbatim. Only wire them up.

- [ ] **C10 (R6.9 + R6.10)**: Production-score drift detector.
  - File: `evals/drift.py` (create).
  - `detect_distribution_drift(baseline_scores, current_scores,
    threshold=0.2) -> DriftReport`:
    - Buckets both into 10-bin histograms over `[0, 1]`
    - Computes KL divergence
    - Returns `DriftReport(diverged: bool, kl: float,
      recommendation: str)`
    - Recommendation when diverged: `"Your eval set covers X% of
      current production distribution. Ingest traces from the last
      N days: agentlab eval ingest --from-traces <path> --since 7d"`
  - Hook into `ContinuousOrchestrator` from C8 — emit
    `drift_detected` notification via C9 plumbing.
  - This is DIFFERENT from `judges/drift_monitor.py` (that's judge
    agreement drift, a distinct feature — leave it alone). Add a
    cross-reference comment in both modules.
  - Test: synthetic distribution shift (uniform → skewed right) →
    drift fires. No shift → no drift. KL computation verified
    against a scipy reference for one fixture.

- [ ] **C11 (R6.11 + R6.12)**: Cost-aware Pareto + `--show-tradeoffs`.
  - Modify: `optimizer/pareto.py` — verify `cost` is a first-class
    objective direction (currently referenced, may need
    promotion). If workspaces don't have a cost weight configured,
    default weight = 0 (behavior unchanged).
  - Modify: `cli/commands/optimize.py` — add `--show-tradeoffs`
    flag. When set, after `--explain-strategy`, print the top K
    non-dominated candidates from the Pareto archive as a table:
    `candidate | quality | safety | cost | dominates | dominated_by`.
  - Test: fixture Pareto archive with 5 candidates, 2 dominant;
    `--show-tradeoffs` output matches golden.
  - Golden-file update for `optimize --help` (new flag visible).

- [ ] **C12 (R6.13 + R6.14 + R4.14)**: Daemon samples + documentation.
  - Create: `contrib/systemd/agentlab-loop.service` — systemd unit
    calling `agentlab loop run --schedule continuous` with restart
    on failure + backoff. Install under user scope.
  - Create: `contrib/launchd/com.agentlab.loop.plist` — launchd
    equivalent.
  - Create/update: docs for R4 widgets, R6 continuous mode, drift
    alerts, cost-aware tradeoffs, and the daemon samples. A single
    `docs/continuous-mode.md` covers all R6 pieces; extend
    `docs/workbench-quickstart.md` for R4 widgets.
  - Test: files exist, pass a basic syntax lint (systemd
    `systemd-analyze verify` if available; launchd plist validates
    as XML).
  - NEVER install the daemon samples automatically — they're
    reference, not runtime.

### Critical invariants

- **No architectural changes.** Every task is an addition on top of
  existing modules or a small modification to a known seam. If you
  find yourself refactoring an R1/R2/R3 module to add one of these
  features, STOP and ask the user — that's a scope violation.
- **Strict-live still applies.** R1's policy covers anything that
  invokes an LLM, including C8's continuous-loop attempts, C9's
  notification bodies if they go through an LLM, C10's recommendation
  text. Missing provider key + strict-live → exit 14, no silent
  fallback.
- **No silent auto-deploy.** C8 queues improvements; it does not
  accept or deploy them. User still approves explicitly.
- **Notification spam guard is mandatory.** C9's dedupe within a
  1-hour window must work before C10 is wired up, or drift alerts
  will spam.
- **Reuse, don't reinvent.**
  - Trace ingestion: `cli/commands/ingest.py` from R5.
  - Score calculation: `evals/runner.py`.
  - LLM calls: R3's judge provider abstraction (wherever R3 put it
    — verify location).
  - Cost tracking: R7's `cli/workbench_app/cost_calculator.py`.
  - In-process command entry points: `cli/commands/_in_process.py`.
  - Notification channels: `notifications/channels.py`.
  - Lineage queries: R2's `optimizer/improvement_lineage.py`.

### Parallelism within this session

Slice R4-polish (C1–C6) and Slice R6-polish (C7–C12) are fully
independent. Two concurrent subagents at any time, one per slice, is
safe. Do NOT run two subagents on the same slice concurrently — they
share touchpoints (`status_bar.py` in C3, `commands.py` registration
in C4/C5/C6, `optimizer/continuous.py` in C8/C9/C10).

### Workflow

1. Create a new worktree:
   `git worktree add .claude/worktrees/r4-r6-cleanup -b claude/r4-r6-cleanup master`
2. Write a tiny expansion plan at
   `docs/superpowers/plans/2026-04-XX-agentlab-r4-r6-cleanup.md`
   enumerating the 12 tasks with exact file paths and pytest
   invocations. Commit the plan alone (`docs: expand R4/R6 cleanup
   plan`) before any code.
3. Dispatch in pairs (one R4-polish + one R6-polish subagent at a
   time) via `superpowers:subagent-driven-development`.
4. After every 4 tasks, run the full suite and confirm no
   regressions in R1–R7 tests:
   `uv run pytest tests/ -x --ignore=tests/api`
5. Open a PR when all 12 are green.

### Acceptance tests (one per task, consolidated at the end)

- `pytest tests/test_eval_progress_grid.py` — widget snapshot.
- `pytest tests/test_failure_card.py` — card snapshot.
- `pytest tests/test_workbench_cost_ticker.py` — status bar sum.
- `pytest tests/test_attempt_diff_slash.py` — diff viewer integration.
- `pytest tests/test_lineage_view_slash.py` — lineage tree snapshot.
- `pytest tests/test_improve_edit_flow.py` — inline edit → accept.
- `pytest tests/test_loop_help.py` — `loop` group visible in help.
- `pytest tests/test_continuous_orchestrator.py` — fake-trace cycle.
- `pytest tests/test_notification_dedupe.py` — 1-hr dedupe.
- `pytest tests/test_distribution_drift.py` — KL drift + recommendation.
- `pytest tests/test_pareto_tradeoffs.py` — `--show-tradeoffs` golden.
- `pytest tests/test_daemon_samples.py` — sample files valid.

### If you get stuck

- R7's cost ticker already covers conversation turns; C3 extends it
  to cover slash-command LLM calls. If the cost calculator only
  exposes a per-turn API, factor a `record_cost(amount_usd)` method
  and have both R7 and C3 call it.
- If `optimizer/continuous.py` grows past ~400 lines in C8+C9+C10,
  split: `orchestrator.py` for the loop, `events.py` for the event
  types, `dedupe.py` for the notification-log table.
- If `cost` isn't actually in `pareto.py`'s `ObjectiveDirection`
  today — just a comment — C11 becomes "add cost as a first-class
  objective dimension"; test with a fixture that has three
  objectives and verify cost participates in domination checks.
- If `evals/drift.py` conflicts with any pre-existing statistical
  test, move it to `evals/score_drift.py` to disambiguate from
  `judges/drift_monitor.py` more clearly.
- Pre-existing failing tests (starlette/httpx collection errors in
  `tests/api/`): note them and move on — not this session's problem.
  Use `--ignore=tests/api` in the full-suite runs.

### Anti-goals (things NOT to build in this session)

- New roadmap features beyond R1–R7 scaffolds.
- Production-traffic A/B routing (R6.8's Kubernetes / Cloud Run
  adapter hinted at in the original plan — keep to
  `LocalCanaryRouter`, don't add platform-specific ones).
- Refactoring any R1/R2/R3 module.
- Rewriting R7's cost calculator.
- Replacing or deprecating `judges/drift_monitor.py`.
- Any new dependency not already in `pyproject.toml`.

### Final deliverable

After all 12 tasks pass:

1. Run the full R1–R7 smoke suite:
   `uv run pytest tests/ -x --ignore=tests/api`
2. Update `docs/superpowers/plans/2026-04-16-agentlab-roadmap-master.md`:
   mark R4 and R6 as "✅ Shipped complete" (currently Slice A and
   Slice B only).
3. Append a CHANGELOG entry summarizing the 12 gap closures.
4. Open the PR with the full list of test commands and the
   task-to-commit mapping in the description.
5. After merge, the roadmap is 100% complete.

### First action

After the user confirms they want to start, read the 12 task specs
above once more, read the ground-truth files listed in "Reuse, don't
reinvent" to confirm current signatures, write the short expansion
plan, commit it, then dispatch C1 + C7 in parallel (one per slice).

Use superpowers and TDD. Work in subagents. Be specific.
