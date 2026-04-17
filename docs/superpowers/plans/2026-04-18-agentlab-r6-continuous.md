# R6 — Continuous Improvement & Observability (TDD expansion plan)

**Status:** draft (2026-04-18)
**Branch:** `claude/r6-continuous` (off `master` at `9ea5098`)
**Depends on:** R1 (strict-live), R2 (lineage store + `improve` group),
R3 (reflection, providers, judge cache cost), R5 (trace_converter,
dataset tooling, redaction). R4 nice-to-have for Workbench surfaces.
**Master plan section:**
`docs/superpowers/plans/2026-04-16-agentlab-roadmap-master.md:1401-1450`

## 0. Goal

After R6, AgentLab runs on a schedule against production traffic. Each
cycle ingests new traces (redacted by default), scores them, detects
regressions and drift, notifies via Slack/email, measures real-world
impact of previously-shipped improvements, supports canary A/B
pairwise scoring, and exposes cost-aware Pareto tradeoffs.

```
agentlab loop run --once                    # one cycle, exits
agentlab loop run --interval 1h             # cron-style scheduling
agentlab loop run --interval 1h --slack-webhook $URL
agentlab improve measure <attempt_id>       # replay set → actual impact
agentlab optimize --show-tradeoffs          # quality/safety/cost frontier
agentlab optimize --explain-strategy        # predicted impact, calibrated
```

Post-R6 the six-release roadmap is complete.

## 1. Architectural decisions

### 1.1 "Loop" is a new CLI command; `optimizer/loop.py` is not rewritten

`optimizer/loop.py` (1300 LOC) is the strategy-mode optimization
engine — it selects operators, applies patches, scores candidates,
runs reflection. R6's `agentlab loop run` is a *scheduler* that wraps
ingestion → scoring → regression detection → notification → optional
invocation of `optimizer/loop.py`. They're different concerns.

`cli/commands/loop.py` is new. The "hidden loop" the master plan
refers to is `optimizer/loop.py` at the CLI surface (no command
currently invokes it from outside workbench). Nothing in
`optimizer/loop.py` is gutted by R6 — it gets a scheduled driver.

### 1.2 Scheduling: external cron first, internal scheduler only for daemon

`agentlab loop run --once` executes one cycle and exits with 0 on
success, non-zero on cycle failure. External cron / systemd timer /
launchd `StartInterval` is the prescribed deployment for the
scheduled form.

`agentlab loop run --interval 1h` is a convenience wrapper that sleeps
and re-invokes `--once` in-process, with exponential backoff on
failure (10s → 1m → 10m cap). It is **not** a daemon — the process
still exits when Ctrl-C'd; no PID file, no signal handling beyond the
default. The daemon story is R6.13 (systemd/launchd samples) which
just invokes the `--interval` form with restart policy.

Rationale: `--once` is trivially debuggable (`strace` it, run it
manually, replay it), restartable (idempotent by design, see §1.5),
and the ops-story is understood by every sysadmin. Internal schedulers
hide state.

### 1.3 Notification adapter interface

```python
@dataclass
class LoopEvent:
    kind: Literal["regression", "drift", "cycle_error", "improvement_shipped"]
    severity: Literal["info", "warn", "error"]
    workspace: str
    surface: str | None           # None for workspace-global events
    signature: str                # dedupe key, e.g. f"{kind}:{surface}:{window}"
    payload: dict[str, Any]       # kind-specific details (scores, candidate ids, links)
    emitted_at: float             # time.time()

class NotificationAdapter(Protocol):
    name: str                     # "slack", "email", "pagerduty", …
    def send(self, event: LoopEvent) -> None: ...
```

`notifications/` already ships `channels.py`, `manager.py`, and
`scheduler.py`. R6.4/R6.5 **extend** those modules rather than
recreating them:

- `notifications/channels.py` — add `SlackAdapter(webhook_url,
  http_client=None)` and `EmailAdapter(smtp_host, smtp_port, from_addr,
  to_addrs, smtp_client=None)` implementing the protocol above. Both
  take an optional injected client so tests never hit the network.
- `notifications/manager.py` — gains a `LoopNotificationRouter`
  (different from the existing notification *manager* which predates
  R6) that owns a list of adapters, applies rate-limit + dedupe
  (§1.4), then dispatches.

### 1.4 Rate-limit + dedupe state (SQLite)

New table in the workspace SQLite store (co-located with the lineage
store, path `.agentlab/notifications.db`):

```sql
CREATE TABLE IF NOT EXISTS notification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    signature TEXT NOT NULL,
    adapter TEXT NOT NULL,        -- "slack", "email", …
    sent_at REAL NOT NULL,        -- unix seconds
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notification_log_kind_sig_sent
    ON notification_log(kind, signature, sent_at);
```

Before sending, `LoopNotificationRouter` queries:
`SELECT 1 FROM notification_log WHERE kind=? AND signature=?
AND adapter=? AND sent_at > ? LIMIT 1` where the cutoff is
`time.time() - rate_limit_window_s`. Default window: 3600s
(1h) per `(kind, signature, adapter)`. Configurable per-kind
via `continuous.notifications.rate_limit` in the workspace config.

`signature` is built by the emitting code and must be stable:
- regression: `f"regression:{surface}:{window_start_hour}"`
- drift:     `f"drift:{metric}:{window_start_day}"`
- cycle_error: `f"cycle_error:{hash(traceback_first_line)}"`

Tests inject a clock callable (`time_fn: Callable[[], float]`) so
time-based dedupe is deterministic.

### 1.5 Cycle state is recoverable

Every `--once` cycle records:

```sql
CREATE TABLE IF NOT EXISTS loop_cycles (
    cycle_id TEXT PRIMARY KEY,         -- uuid4
    started_at REAL NOT NULL,
    finished_at REAL,                  -- NULL = in-flight/abandoned
    status TEXT NOT NULL,              -- "running" | "ok" | "error" | "abandoned"
    traces_ingested INTEGER DEFAULT 0,
    regressions_queued INTEGER DEFAULT 0,
    eval_run_id TEXT,                  -- R2 lineage FK, nullable
    error_message TEXT
);
```

At cycle start:
1. Mark any `status='running'` rows with `started_at < now - 2h` as
   `status='abandoned'` and emit a `cycle_error` LoopEvent with
   signature `f"cycle_abandoned:{cycle_id}"`.
2. Insert a new row with `status='running'`.

At cycle end: update to `ok` or `error` with `finished_at`.

This makes a dead-mid-cycle process recoverable without a double-
processed trace: the abandoned cycle's partial work is identifiable
via the foreign key into the lineage store.

### 1.6 Trace ingestion: redaction on by default, `--raw` is opt-in × 2

R6.2 reuses R5's redaction path (`evals/dataset/redact.py`). The
scheduled loop runs in **non-interactive** mode. Defaults:

- `continuous.ingest.enabled`: `true` (ingest traces each cycle)
- `continuous.ingest.source`: path glob or a pluggable
  `TraceSource` (next §)
- `continuous.ingest.redact`: `true` (forced — no flag to disable)
- `continuous.ingest.raw`: `false`

Setting `continuous.ingest.raw: true` requires **both**:

1. The config entry explicitly set to `true` (no env var override).
2. A CLI flag `--raw` on the `loop run` invocation.

If either is missing, the loop aborts redaction-off mode with exit 20
(matches R5's abort code for unconsented PII). No silent path.

### 1.7 Regression detection

Each cycle:

1. Convert new traces to eval cases via `TraceToEvalConverter` (R5).
2. Score them with the current deployed config using the existing
   `EvalRunner`.
3. Compute the per-surface composite score for this window.
4. Compare against a rolling baseline stored in SQLite:
   `baseline_score = exp_moving_avg(last_N=50_windows, alpha=0.2)`.
5. A **regression** fires when:
   `current_score < baseline_score - regression_threshold` and
   `n_cases_in_window >= min_cases` (default 20).
6. Default `regression_threshold`: 0.05 (absolute on composite
   weighted score in [0,1]).
7. On regression, emit a `regression` `LoopEvent` and queue an
   `OptimizationOpportunity` via the existing
   `observer.opportunities` module.

Thresholds and window size are per-surface in
`continuous.regression.thresholds`. Default surface is workspace-
global.

### 1.8 Calibration (R6.7)

A new SQLite table:

```sql
CREATE TABLE IF NOT EXISTS predicted_vs_actual (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id TEXT NOT NULL,         -- R2 lineage FK
    surface TEXT NOT NULL,
    strategy TEXT NOT NULL,
    predicted_improvement REAL NOT NULL,
    actual_improvement REAL NOT NULL,
    recorded_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pva_surface_strategy
    ON predicted_vs_actual(surface, strategy);
```

- `predicted_improvement` comes from the proposer's
  `expected_score_delta` field at attempt time.
- `actual_improvement` is filled in by `improve measure <id>` (R6.6)
  after running the production-replay eval set.
- The **calibration factor** for `(surface, strategy)` is
  `mean(actual - predicted)` over the last N=20 rows for that pair.
  With fewer rows, factor = 0.0 (no adjustment). Never raise an
  exception on sparse data — new workspaces must work.
- `optimize --explain-strategy` reads the factor and displays:
  "Predicted +0.08; calibration-adjusted +0.06 (last 20 attempts
  ran 0.02 below prediction on this surface)."

This is **separate** from `optimizer/reflection.py:Reflection`.
Reflection captures *qualitative* learnings; calibration captures
*quantitative* miscalibration. No schema collision.

### 1.9 Canary pairwise scoring (R6.8)

Existing `deployer/canary.py:CanaryManager` does **traffic split**
(10% of requests → canary) and verdict is based on per-version
outcome stats. That's apples-to-oranges: canary and baseline may see
different inputs.

R6.8 adds `optimizer/canary_scoring.py`:

```python
class CanaryRouter(Protocol):
    """Deploy-platform-specific adapter; records paired outputs."""
    def record_pair(self, *, input_id: str,
                   baseline_output: str,
                   candidate_output: str,
                   metadata: dict[str, Any]) -> None: ...

class CanaryScoringAggregator:
    """Deploy-agnostic; scores pairs with the pairwise judge."""
    def score_recent(self, *, min_pairs: int, window_s: float
                     ) -> CanaryVerdict: ...
```

`CanaryVerdict` carries `baseline_wins`, `candidate_wins`, `ties`,
`win_rate_candidate`, `preferred` (one of `"baseline" | "candidate" |
"tie"`), and an effect-size CI. Scoring reuses R3's pairwise
`JudgeRunner`.

Ship one adapter: `LocalCanaryRouter` that stores pairs in SQLite.
K8s/CloudRun adapters are deferred to R6-followup (the interface is
stable enough to add them later).

The existing `CanaryManager` is unchanged — it still drives
deployment traffic routing. The new aggregator plugs in as an
additional verdict signal the deployer can consult.

### 1.10 Drift detection (R6.9)

`evals/drift.py:score_distribution_drift(prev_scores, curr_scores,
bucket_count=10, metric="kl") -> DriftReport`.

- Both `prev_scores` and `curr_scores` are `list[float]` in [0,1].
- Bucketed into `bucket_count` equal-width buckets.
- Histogram probabilities with Laplace-smoothing (add 1/N) so KL is
  finite when a bucket is empty.
- Metric is KL divergence `sum(p * log(p/q))` by default; JS
  available via `metric="js"`.
- Alert threshold default 0.2 (KL). Configurable per-workspace.

`DriftReport`:

```python
@dataclass
class DriftReport:
    metric: str                   # "kl" | "js"
    divergence: float
    threshold: float
    alert: bool
    prev_hist: list[float]
    curr_hist: list[float]
    window_start: float
    window_end: float
    coverage_percent: float       # R6.10: % of prod distribution
                                  # covered by current eval set
```

### 1.11 Drift → eval-set refresh recommendation (R6.10)

A drift alert emits a `drift` LoopEvent whose payload embeds the
recommendation:

```
Drift detected on <surface> (KL=0.27, threshold=0.20).
Your eval set currently covers ~62% of the production score
distribution. Suggested action:
  agentlab eval ingest --from-traces .agentlab/traces/last-14d.jsonl
Run that, then re-run the loop.
```

`coverage_percent` is computed by:
1. Score all eval cases → `eval_dist` histogram.
2. Score production traces for the window → `prod_dist` histogram.
3. For each bucket, the *covered* probability is `min(eval_dist[i],
   prod_dist[i])`. Coverage = `sum(covered) * 100`.

### 1.12 Cost-aware Pareto (R6.11)

`optimizer/pareto.py:ConstrainedParetoArchive` already takes
`objective_directions: dict[str, ObjectiveDirection]`. R6.11 adds:

- A new first-class objective `cost` with `ObjectiveDirection.MINIMIZE`.
- Per-candidate `objectives["cost"]` is the per-case dollar cost:
  `(total_llm_spend + judge_cache_miss_cost) / n_eval_cases`.
- Default cost weight is **0** for legacy workspaces (no behavioral
  change). Enable via `optimizer.objectives.cost.weight` in workspace
  config.
- `agentlab doctor` surfaces the current cost weight + whether cost
  data is flowing (non-null `objectives["cost"]` on recent attempts).

### 1.13 `optimize --show-tradeoffs`

Prints the top-K non-dominated candidates as a table:

```
candidate_id        quality   safety    cost/case    notes
cand_4f2            0.87      0.92      $0.012       recommended (knee)
cand_9a1            0.91      0.90      $0.038       +4% quality, +3× cost
cand_7c3            0.82      0.96      $0.008       -5% quality, 33% cheaper
```

Default K=5. `--show-tradeoffs --k 10` expands. Non-TTY emits JSON via
the existing `cli/output.py:emit_json_envelope`.

### 1.14 Strict-live applies to the continuous loop

If the workspace is strict-live and any cycle-time LLM call would fall
back to mock, the cycle exits with code 13 (same as R1) **and** emits
a `cycle_error` LoopEvent. The scheduled loop keeps running (next
tick tries again). This is the single case where an in-process failure
does not kill `--interval`.

### 1.15 File-handle hygiene

Every SQLite write path uses `with sqlite3.connect(...) as conn:` and
every trace-file read uses `with open(...)`. The 24h soak acceptance
test checks `/proc/<pid>/fd` (Linux) or `lsof -p <pid>` (macOS) before
and after; FD count delta must be 0 ± small constant.

## 2. File map

| File | Status | Why |
|---|---|---|
| `cli/commands/loop.py` | **Create** | `agentlab loop {run,status}` CLI group |
| `optimizer/continuous.py` | **Create** | Cycle orchestrator (ingest→score→detect→notify) |
| `optimizer/cycle_store.py` | **Create** | SQLite: `loop_cycles`, reconcile abandoned |
| `optimizer/calibration.py` | **Create** | `predicted_vs_actual` table + factor lookup |
| `optimizer/canary_scoring.py` | **Create** | `CanaryRouter` protocol + `LocalCanaryRouter` + aggregator |
| `evals/drift.py` | **Create** | `score_distribution_drift`, `DriftReport`, coverage |
| `notifications/channels.py` | **Modify** | Add `SlackAdapter`, `EmailAdapter` |
| `notifications/manager.py` | **Modify** | Add `LoopNotificationRouter` (dedupe/rate-limit) |
| `notifications/rate_limit.py` | **Create** | SQLite-backed dedupe store |
| `optimizer/pareto.py` | **Modify** | `cost` objective support; default weight 0 |
| `cli/commands/optimize.py` | **Modify** | `--show-tradeoffs`, `--explain-strategy` calibration |
| `cli/commands/improve.py` | **Modify** | `improve measure <attempt_id>` subcommand |
| `cli/commands/doctor.py` | **Modify** (if present) | Surface cost weight + continuous config |
| `contrib/systemd/agentlab-loop.service` | **Create** | Sample unit |
| `contrib/systemd/agentlab-loop.timer` | **Create** | Sample timer |
| `contrib/launchd/com.agentlab.loop.plist` | **Create** | Sample plist |
| `docs/continuous/overview.md` | **Create** | R6.14 user-facing guide |

## 3. Slice plan

### Slice A — Scheduled loop + ingestion + notifications (R6.1–R6.5)

**Goal:** a cron-driven `agentlab loop run --once` that ingests traces,
scores them, detects regression, and notifies Slack + email. No
calibration, no canary, no drift yet.

| # | Task | Test first |
|---|---|---|
| A.1 | `optimizer/cycle_store.py:CycleStore` with SQLite init + `start_cycle`/`finish_cycle`/`reconcile_abandoned`. | `test_cycle_store_creates_schema`, `test_cycle_start_finish_ok`, `test_reconcile_marks_stale_running_as_abandoned` |
| A.2 | `optimizer/continuous.py:ContinuousLoop.run_once()` — ingests from a pluggable `TraceSource`, converts via R5 `TraceToEvalConverter`, redacts via R5 `redact.py`, scores via `EvalRunner`, writes cycle row. | `test_run_once_ingests_and_scores_fakes`, `test_run_once_strict_live_without_key_exits_13`, `test_run_once_raw_requires_config_and_flag` |
| A.3 | Regression detection: rolling baseline (EMA N=50, α=0.2) + threshold. | `test_regression_fires_when_below_threshold`, `test_regression_ignored_with_too_few_cases`, `test_baseline_ema_stable` |
| A.4 | `notifications/rate_limit.py:RateLimitStore` (SQLite table `notification_log`; `should_send(kind, sig, adapter, window_s, now)`). | `test_rate_limit_blocks_within_window`, `test_rate_limit_allows_after_window`, `test_rate_limit_distinguishes_adapters` |
| A.5 | `notifications/channels.py:SlackAdapter(webhook_url, http_client=None)` with injectable `http_client.post(url, json=...)`. | `test_slack_adapter_posts_payload`, `test_slack_adapter_4xx_raises_with_body`, `test_slack_adapter_no_real_http` |
| A.6 | `notifications/channels.py:EmailAdapter(...)` with injectable SMTP client. | `test_email_adapter_sends_with_fake_smtp`, `test_email_adapter_multi_recipient`, `test_email_adapter_no_real_smtp` |
| A.7 | `notifications/manager.py:LoopNotificationRouter(adapters, rate_limiter, clock)` — dedupe + fanout. | `test_router_respects_rate_limit`, `test_router_dispatches_to_all_adapters`, `test_router_dedupes_same_signature` |
| A.8 | `cli/commands/loop.py:run` click command — `--once`, `--interval`, `--slack-webhook`, `--email-to`, `--raw`. | `test_cli_loop_run_once_exit_0`, `test_cli_loop_run_interval_invokes_n_times`, `test_cli_loop_run_backoff_on_error`, `test_cli_loop_run_raw_requires_config` |
| A.9 | **Acceptance:** seeded trace file + mocked adapters → one cycle emits a regression event to both Slack and email, rate-limiter then blocks the next duplicate. | `test_acceptance_slice_a_regression_fanout_and_rate_limit` |

Commit style (one per task):
- `feat(loop): cycle_store with abandoned-cycle reconciliation`
- `feat(loop): run_once cycle orchestrator`
- `feat(loop): regression detection on rolling baseline`
- `feat(notify): rate-limit store with SQLite dedupe`
- `feat(notify): Slack adapter with injectable HTTP client`
- `feat(notify): email adapter with injectable SMTP client`
- `feat(notify): LoopNotificationRouter with dedupe and fanout`
- `feat(cli): agentlab loop run with --once/--interval/backoff`
- `test(loop): slice A acceptance — regression fanout and rate limit`

### Slice B — Measurement + calibration + canary scoring (R6.6–R6.8)

**Goal:** close the feedback loop on shipped improvements; add
pairwise canary verdicts; feed calibration into the optimizer's
strategy explanation.

| # | Task | Test first |
|---|---|---|
| B.1 | `optimizer/calibration.py:CalibrationStore` with `predicted_vs_actual` schema + `record(attempt_id, surface, strategy, pred, actual)` + `factor(surface, strategy, N=20)`. Sparse → 0.0, never raises. | `test_calibration_factor_sparse_returns_zero`, `test_calibration_factor_last_n`, `test_calibration_record_persists` |
| B.2 | `cli/commands/improve.py:measure <attempt_id> --replay-set <path>` — runs the eval set, diffs against baseline score at attempt time, writes to `CalibrationStore` + lineage. | `test_improve_measure_computes_actual_delta`, `test_improve_measure_writes_calibration_row`, `test_improve_measure_unknown_attempt_exit_4` |
| B.3 | `cli/commands/optimize.py:--explain-strategy` reads the factor and renders the calibrated prediction. | `test_explain_strategy_shows_calibrated_value`, `test_explain_strategy_sparse_falls_back_to_raw` |
| B.4 | `optimizer/canary_scoring.py:CanaryRouter` protocol + `LocalCanaryRouter(db_path)` implementing `record_pair`. | `test_local_router_persists_pairs`, `test_local_router_schema_roundtrip` |
| B.5 | `optimizer/canary_scoring.py:CanaryScoringAggregator.score_recent` using R3 pairwise judge. | `test_aggregator_computes_win_rate`, `test_aggregator_requires_min_pairs`, `test_aggregator_tie_handling` |
| B.6 | Deployer hook: existing `deployer/canary.py:CanaryManager.check_canary` consults aggregator if configured. Non-breaking — default is `None`. | `test_canary_manager_ignores_aggregator_when_none`, `test_canary_manager_uses_aggregator_verdict_when_set` |
| B.7 | **Acceptance:** after a simulated shipped improvement and 50 replay cases, calibration factor updates and `--explain-strategy` shows the calibrated delta. | `test_acceptance_slice_b_calibration_roundtrip` |

Commit style:
- `feat(optimizer): calibration store for predicted-vs-actual`
- `feat(improve): measure subcommand on replay set`
- `feat(optimize): --explain-strategy uses calibration factor`
- `feat(canary): CanaryRouter protocol + LocalCanaryRouter`
- `feat(canary): CanaryScoringAggregator with pairwise verdict`
- `feat(deployer): opt-in pairwise aggregator in CanaryManager`
- `test(loop): slice B acceptance — calibration round-trip`

### Slice C — Drift + cost-aware Pareto + daemon wrapper (R6.9–R6.13)

**Goal:** detect distribution shift with an actionable recommendation;
make cost a first-class optimization objective; expose tradeoffs; ship
OS-level daemon samples.

| # | Task | Test first |
|---|---|---|
| C.1 | `evals/drift.py:score_distribution_drift` + `DriftReport`; KL + JS; Laplace smoothing. | `test_drift_kl_identical_dists_zero`, `test_drift_kl_disjoint_dists_high`, `test_drift_js_symmetric`, `test_drift_laplace_prevents_infinity` |
| C.2 | Coverage percent: `eval_dist` vs `prod_dist` via `min(p, q)` bucket sum. | `test_coverage_full_overlap_is_100`, `test_coverage_disjoint_is_0`, `test_coverage_partial` |
| C.3 | Integrate drift into `ContinuousLoop.run_once`: read last-window eval scores + prod scores from cycle store, emit `drift` LoopEvent with embedded recommendation. | `test_loop_emits_drift_event_above_threshold`, `test_loop_drift_payload_has_recommendation` |
| C.4 | `optimizer/pareto.py`: support `cost` objective; default weight 0 when absent; document in docstring. | `test_pareto_cost_objective_minimize`, `test_pareto_cost_default_weight_zero_unchanged_behavior`, `test_pareto_cost_dominates_cheaper_equal_quality` |
| C.5 | `cli/commands/optimize.py:--show-tradeoffs` prints top-K non-dominated with a TTY table and JSON non-TTY. | `test_show_tradeoffs_tty_table`, `test_show_tradeoffs_json_envelope`, `test_show_tradeoffs_k_flag` |
| C.6 | `agentlab doctor` surfaces continuous config: cost weight, ingest enabled, strict-live mode, notification adapters registered. (Skip if no `doctor` command exists.) | `test_doctor_reports_continuous_config` |
| C.7 | `contrib/systemd/agentlab-loop.{service,timer}` + `contrib/launchd/com.agentlab.loop.plist` samples. Include `OnFailure=` restart policy, clear placeholder paths. No installer. | `test_systemd_unit_is_valid_ini` (parse with `configparser`), `test_launchd_plist_is_valid_xml` (`plistlib`) |
| C.8 | **Acceptance:** synthetic distribution shift → drift alert fires; cost-aware Pareto prefers a cheap-and-good-enough candidate over expensive-marginally-better at same quality weight. | `test_acceptance_slice_c_drift_alert_and_cost_pareto` |

Commit style:
- `feat(evals): KL/JS drift detection on score distributions`
- `feat(evals): coverage percent for eval-vs-prod distributions`
- `feat(loop): emit drift LoopEvent with refresh recommendation`
- `feat(optimizer): cost-aware Pareto with default-zero weight`
- `feat(optimize): --show-tradeoffs top-K non-dominated table`
- `feat(doctor): surface continuous/cost config`
- `chore(contrib): systemd + launchd samples for loop daemon`
- `test(loop): slice C acceptance — drift + cost Pareto`

### R6.14 — Documentation

`docs/continuous/overview.md` covering:

- `agentlab loop run` flags and exit codes.
- Redaction invariants and the `--raw` double-opt-in.
- Notification adapter registration + rate-limit config.
- Calibration: what `--explain-strategy` now shows.
- Canary pairwise vs traffic-split: when each is meaningful.
- Drift thresholds, coverage percent, and the refresh workflow.
- Cost objective: configuring weight, reading `--show-tradeoffs`.
- Deployment: external cron vs `--interval` vs systemd/launchd
  samples in `contrib/`.

Commit: `docs(continuous): R6 user-facing overview`.

## 4. Invariants (verified by tests)

1. **Scheduled, not daemon.** `--once` exits 0 or non-zero
   deterministically; `--interval` is a sleep-loop wrapper (§1.2,
   test A.8).
2. **No silent raw ingestion.** Raw mode requires both config + flag
   (§1.6, test A.2).
3. **Notification dedupe works across adapters.** Signature-level
   dedupe is independent of channel (§1.4, test A.7).
4. **No real network in adapter tests.** Slack/email tests inject
   fake clients (§1.3, tests A.5/A.6).
5. **Abandoned cycles reconcile.** Stale `running` rows → `abandoned`
   on next start (§1.5, test A.1).
6. **Sparse calibration does not crash.** Factor = 0.0 when N<20
   (§1.8, test B.1).
7. **Canary pairwise uses the same inputs.** Aggregator only scores
   `(baseline, candidate)` tuples recorded together (§1.9, tests
   B.4/B.5).
8. **Cost defaults to 0 weight.** Legacy workspaces unchanged (§1.12,
   test C.4).
9. **Drift alerts are actionable.** Payload must include coverage
   percent + a concrete `agentlab eval ingest` command (§1.11, test
   C.3).
10. **Strict-live kills silent mock fallback inside the loop.** Cycle
    exits 13 and emits `cycle_error` (§1.14, test A.2).
11. **No FD leaks in `--interval`.** Soak test asserts FD delta ≈ 0
    (§1.15, optional follow-up after A.9).

## 5. Risks and mitigations

- **`optimizer/loop.py` is large and load-bearing.** R6 does not
  touch it in Slice A — the scheduler calls its public entry points
  only. If a call-site change is required, isolate it behind a thin
  adapter in `optimizer/continuous.py`.
- **`notifications/manager.py` already has a `NotificationManager`.**
  Confirm naming before adding `LoopNotificationRouter` — likely the
  existing manager can be composed or extended. Verify via `Read`
  before the A.7 dispatch.
- **R5 redaction module path may differ.** Dispatch prompts must
  `Read evals/dataset/redact.py` first and quote the actual import
  path.
- **Pairwise judge cost in B.5.** Aggregator should batch and cache
  via R3's judge cache. Don't re-implement caching.
- **Cost data may be null on pre-R3 attempts.** R6.11 treats `None`
  cost as "not measured" and excludes that axis from dominance
  comparisons (preserving legacy behavior).
- **`agentlab doctor` may not exist yet** as a command. C.6 is
  conditional — if the command is absent, skip the task and note it
  in the commit message for the doc pass.
- **Pre-existing starlette/httpx test-collection failures.** Record
  and move on; not R6's problem (same treatment as R5).
- **systemd/launchd samples on macOS-only dev box.** C.7 validates by
  parsing (not by running). Keep samples minimal and placeholder-
  pathed.

## 6. Out of scope for R6

- K8s/CloudRun canary router adapters (interface ships; concrete
  impls deferred).
- LSH/ANN acceleration for drift coverage on huge score histories
  (bucketed histograms scale fine to 10k cases; large scale deferred).
- Full daemon supervisor (PID file, signal handling, hot-reload).
  `--interval` + systemd sample is the intentional ceiling.
- Multi-workspace aggregation in one loop process. Each workspace
  runs its own `agentlab loop run`.
- R7 work (Workbench as Agent) stays out — R6 only exposes data R7
  can later surface.
