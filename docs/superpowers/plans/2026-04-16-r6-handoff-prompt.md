# R6 Handoff Prompt — Continuous Improvement & Observability

Paste the block below into a fresh Claude Code session at the repo root
(`/Users/andrew/Desktop/agentlab`).

**Prerequisite:** R6 depends on **R1 + R2 + R3 + R5**. All four must be
merged to master before R6 begins. R4 is nice-to-have (rich Workbench
widgets visualize R6 data well) but not a hard dependency.

---

## Session prompt

You are picking up the AgentLab roadmap at **R6 — Continuous
Improvement & Observability**. R1, R2, R3, and R5 have already shipped
on master. R6 is the final roadmap release and gets its own session for
clean context.

### What already shipped (context, don't re-do)

**R1:** strict-live policy, exit codes, rejection records, deploy
verdict gate, provider-key validation.

**R2:** lineage store with full
`eval_run_id → attempt_id → deployment_id → measurement_id` chain,
`agentlab improve` command group, modular `cli/commands/*.py`.

**R3:** coverage-aware proposer, reflection feedback, configurable
composite weights (snapshotted per eval run), LLM-backed pairwise
judge with heuristic fallback.

**R5:** dataset tooling, `agentlab eval ingest --from-traces`, pluggable
embedder, failure-driven case generation.

### Your job

Ship **R6** following subagent-driven TDD:

- Fresh subagent per task, full task text + code in the dispatch prompt
- Each subagent uses `uv run pytest` (project requires Python 3.10+)
- Every task: failing test → minimal impl → passing test → conventional commit
- Mark TodoWrite tasks complete immediately; don't batch
- Verify assumptions (file line numbers, function signatures) before
  dispatching

### R6 goal

AgentLab runs continuously against production traffic: scheduled
loop, ingests traces, scores them, detects regressions and drift,
sends notifications, measures real-world impact of shipped
improvements, runs canary scoring, and exposes cost-aware Pareto
tradeoffs.

### Before dispatching anything

1. **Read the R6 scaffold in the master plan** at
   `docs/superpowers/plans/2026-04-16-agentlab-roadmap-master.md:1401-1450`
   (14 tasks, acceptance tests, risks).

2. **Expand R6 into its own TDD plan file** at
   `docs/superpowers/plans/2026-04-XX-agentlab-r6-continuous.md`.
   Use R1's plan section as the template shape. Commit the plan alone
   (`docs: expand R6 TDD plan`) before any code.

3. **Verify the current state of these files before writing dispatch prompts:**
   - Existing `agentlab loop` (the hidden one). The master plan says R6 "replaces the hidden one." Confirm it still exists and capture its current shape before gutting it.
   - `evals/trace_converter.py` — R5 wired it into `eval ingest`; R6.2 adds continuous ingestion as a trigger.
   - `optimizer/pareto.py` — current shape, current objectives. R6.11 adds cost as a first-class objective.
   - `deployer/` — does it expose canary hooks already, or does R6.8 design them from scratch? Check for anything resembling `canary` / `gradual_rollout`.
   - `optimizer/reflection.py` — R3 added `surface_learnings`. R6.7 (calibration) adds `predicted_vs_actual_improvement` data. Confirm schema won't collide.

4. **Split R6 into three dispatchable slices.** Don't try to ship all
   14 tasks in one session.

   - **Slice A — Scheduled loop + ingestion + notifications** (R6.1–R6.5):
     `agentlab loop run --interval 1h` (scheduled, not daemon),
     continuous trace ingestion hook, score-and-queue-regression,
     Slack adapter, email adapter. Self-contained; the foundation for
     everything else.
   - **Slice B — Measurement + calibration + canary** (R6.6–R6.8):
     `improve measure <id>` on production-replay set, calibration
     (actual vs predicted improvement → factor fed back to
     `--explain-strategy`), canary A/B scoring infrastructure.
   - **Slice C — Drift + cost-aware Pareto + daemon wrapper**
     (R6.9–R6.13): KL-divergence drift detection, drift-triggered
     eval-set refresh recommendation, cost-aware Pareto with
     `(quality, safety, cost)`, `optimize --show-tradeoffs`, daemon-
     mode wrapper (systemd / launchd samples).

   R6.14 (docs) comes after Slice C.

5. **Confirm with the user which slice to start with.** Default to Slice A.

### Critical invariants R6 must preserve

- **Start scheduled, not daemon.** R6.1 is an interval-scheduled CLI
  invocation, NOT a long-running process. Daemon wrapper (R6.13) is
  last. Rationale: `cron`-style execution is trivially debuggable and
  restartable; daemon adds an ops burden users aren't ready for until
  the scheduled version is proven.
- **Notification spam guard.** Every notification path needs
  rate-limiting (e.g. max 1 regression alert per surface per hour)
  and dedupe (same regression signature within a window is one
  alert, not N). Test this explicitly with time-mocked clock.
- **Canary A/B safety.** Canary scoring compares candidate vs
  baseline on the SAME inputs. Never let the canary route take
  production traffic the baseline didn't also see — that's a
  statistical foot-gun. Record both paths' outputs and score
  pairwise.
- **Production data privacy is opt-in.** Trace ingestion in Slice A
  must default to redaction-on (reuse R5's redaction path). A
  `--raw` flag requires explicit user consent plus a written config
  entry (`continuous.ingest.raw: true`). No silent raw ingestion.
- **Daemon state is recoverable.** If the scheduled loop dies
  mid-cycle, the next invocation reconciles: check the lineage
  store for orphan `eval_run_id`s without downstream records, finish
  them or mark abandoned. Don't double-process.
- **Drift alerts must be actionable.** A drift alert without a
  recommendation is noise. R6.10 explicitly says "drift alert →
  trigger eval-set refresh recommendation" — the alert payload
  includes "your eval set now covers X% of production distribution;
  suggest ingesting traces from the last N days to refresh."
- **Cost weight defaults to 0 for legacy workspaces.** R6.11 adds
  cost to the Pareto; workspaces upgraded from R3 may not have a
  cost weight configured. Default to 0 so behavior is unchanged
  until the user opts in. Surface the setting in `doctor`.
- **Strict-live still applies.** If the continuous loop invokes a
  proposer/eval/judge that would fall back to mock, and strict-live
  is set in the workspace config, the loop iteration errors and
  surfaces via notification instead of silently degrading.

### Architectural decisions the master plan defers to you

- **Scheduler:** pure Python `schedule` library OR an external cron
  that invokes `agentlab loop run --once`. Prefer external cron for
  the scheduled version; the daemon wrapper (R6.13) can adopt an
  internal scheduler. `--once` is a flag on `loop run` that exits
  after one cycle.
- **Notification adapter interface:** `send(event: LoopEvent) -> None`
  where `LoopEvent` has `kind`, `severity`, `workspace`,
  `surface`, `payload`. Slack and email implement the same interface.
  New adapters (PagerDuty, Discord) drop in without touching the
  orchestrator.
- **Rate-limit state:** SQLite table `notification_log` with `(kind,
  signature, sent_at)`. Before sending, query for same `(kind,
  signature)` within the rate-limit window; skip if present.
- **Calibration factor shape (R6.7):** per (surface, strategy) pair,
  track `mean(actual - predicted)` over the last N measurements. The
  calibration factor adjusts the predicted improvement used by
  `--explain-strategy`. Start with N=20.
- **Canary scoring plumbing (R6.8):** a pluggable `CanaryRouter`
  interface with `record_pair(baseline_output, candidate_output,
  input) -> None`. Deploy adapters (k8s, Cloud Run, local) implement
  it. The scoring aggregator is deploy-agnostic.
- **Drift distribution compare (R6.9):** KL divergence on the score
  distribution. Both distributions are histograms over bucketed
  scores (say 10 buckets in [0,1]). Alert threshold default 0.2;
  configurable per workspace.
- **Cost objective (R6.11):** per-case dollar cost (from R3's
  judge-cache cost plus proposer/eval tokens). Pareto surface now
  lives in `(quality, safety, cost)` space. `--show-tradeoffs` prints
  the frontier as a table with the top K non-dominated candidates.
- **Daemon wrapper (R6.13):** a thin shim — systemd unit + launchd
  plist — that calls `agentlab loop run` in a loop with backoff on
  failure. Samples committed under `contrib/systemd/` and
  `contrib/launchd/`; not installed automatically.

### Workflow

1. Create a new worktree:
   `git worktree add .claude/worktrees/<r6-name> -b claude/r6-continuous master`
2. Follow `superpowers:subagent-driven-development` — dispatch one
   subagent per task, don't implement in the main thread.
3. After each slice, offer to open a PR before moving to the next.
4. After Slice A lands, consider running the scheduled loop against
   a sandbox workspace for 24h as a soak test before Slice B.

### If you get stuck

- Stale line numbers in the master plan: verify with `Read` before dispatching.
- Subagent hits Python 3.9 on the host: tell it to use `uv run python` / `uv run pytest`.
- Notification tests flaky due to real network calls: every adapter
  must accept an injected HTTP/SMTP client so tests use a fake.
- Daemon-mode 24h soak test reveals file-handle leaks: audit every
  `open()`/sqlite3 connection in the loop orchestrator; use context
  managers.
- Pre-existing failing tests (starlette/httpx collection errors in API
  tests): note them and move on — not R6's problem.
- Calibration data is sparse (new workspace): default calibration
  factor to 1.0 (no adjustment) until N measurements exist.

### Post-R6 — the roadmap is done

After R6 Slice C + docs, the six-release roadmap is complete. Offer to:

1. Bump the package version (semver major — R1 through R6 is a
   major release).
2. Write the consolidated CHANGELOG entry summarizing all six releases.
3. Open a "roadmap complete" PR against master.
4. Propose the next roadmap's scope based on what was deferred from
   R1–R6.

### First action

After the user confirms they want to start, read the master plan's R6
section, read the files listed above (existing loop, pareto, deployer,
reflection) to ground-truth assumptions, write the expansion plan,
commit it, then ask which slice (A/B/C) to execute first.

Use superpowers and TDD. Work in subagents. Be specific.
