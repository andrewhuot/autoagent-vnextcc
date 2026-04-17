# R4/R6 Cleanup — Roadmap Closeout Plan

**Branch**: `claude/r4-r6-cleanup` · **Date**: 2026-04-17 · **Scope**: 12 tasks across two independent slices.

R1, R2, R3, R5, R7 are shipped on master. R4 shipped Slice A only
(in-process refactor, commit `a782d33`). R6 shipped Slice B only
(calibration + canary, commit `719edf0`). This plan closes the remaining
12 gaps — all additions on top of existing seams, no architectural
changes.

## Invariants

- No refactoring of R1/R2/R3 modules. If a feature requires it, stop and ask.
- Strict-live still applies: any LLM-invoking code exits 14 on missing provider key.
- No silent auto-deploy: C8 queues improvements, user still approves.
- Notification dedupe (C9) must work before C10 is wired up.
- Reuse: `cli/workbench_app/cost_calculator.py`, `optimizer/improvement_lineage.py::ImprovementLineageStore.view_attempt`, `cli/commands/ingest.py`, `cli/commands/improve.py` (in-process entry points), `notifications/manager.py` + `channels.py`, `optimizer/failure_analyzer.py::FailureAnalyzer`, `evals/runner.py::EvalRunner`.

## Ground truth (verified 2026-04-17)

- Cost: `WorkbenchSession.cost_ticker_usd` (float) + `session.increment_cost(delta)`. `cost_calculator.compute_turn_cost(usage, model_id)` never raises.
- Status bar: `StatusBar.refresh_from_workspace(workspace, *, session, model_override, provider_info) -> StatusSnapshot`.
- Lineage: `ImprovementLineageStore.view_attempt(attempt_id) -> AttemptLineageView` (denormalized chain).
- In-process: `run_improve_accept_in_process(attempt_id, strategy, memory_db, lineage_db, on_event, text_writer, deploy_invoker)` in `cli/commands/improve.py`.
- Notifications: `NotificationManager` with `register_webhook` / `register_slack`. `VALID_EVENT_TYPES` must be extended with `regression_detected`, `improvement_queued`, `continuous_cycle_failed`, `drift_detected`.
- Pareto: `ObjectiveDirection(MAXIMIZE|MINIMIZE)`. Cost is NOT first-class — C11 promotes it.
- Loop: `runner.py:3829` (`@cli.group("loop", ..., hidden=True)`) and `runner.py:3841` (`@loop_group.command("run", hidden=True)`).
- Commands: `CommandRegistry.register(SlashCommand)` in `cli/workbench_app/commands.py`.

## Task matrix

| # | ID  | Area           | Files (new / modified)                                         | Test                                           |
|---|-----|----------------|----------------------------------------------------------------|------------------------------------------------|
| 1 | C1  | R4 widget      | new: `cli/workbench_app/eval_progress_grid.py`; mod: `eval_slash.py` | `tests/test_eval_progress_grid.py`             |
| 2 | C2  | R4 widget      | new: `cli/workbench_app/failure_card.py`                       | `tests/test_failure_card.py`                   |
| 3 | C3  | R4 widget      | mod: `cli/workbench_app/status_bar.py` (+ session glue)        | `tests/test_workbench_cost_ticker.py`          |
| 4 | C4  | R4 widget      | new: `cli/workbench_app/attempt_diff_slash.py`; mod: `commands.py` | `tests/test_attempt_diff_slash.py`             |
| 5 | C5  | R4 widget      | new: `cli/workbench_app/lineage_view_slash.py`; mod: `commands.py` | `tests/test_lineage_view_slash.py`             |
| 6 | C6  | R4 widget      | mod: `cli/workbench_app/improve_slash.py`                      | `tests/test_improve_edit_flow.py`              |
| 7 | C7  | R6 CLI         | mod: `runner.py` (lines 3829, 3841)                            | `tests/test_loop_help.py`                      |
| 8 | C8  | R6 orchestrator| new: `optimizer/continuous.py`; mod: `runner.py` loop cmd      | `tests/test_continuous_orchestrator.py`        |
| 9 | C9  | R6 notif       | mod: `optimizer/continuous.py`, `notifications/manager.py`     | `tests/test_notification_dedupe.py`            |
|10 | C10 | R6 drift       | new: `evals/drift.py`; mod: `optimizer/continuous.py`          | `tests/test_distribution_drift.py`             |
|11 | C11 | R6 pareto      | mod: `optimizer/pareto.py`, `cli/commands/optimize.py`         | `tests/test_pareto_tradeoffs.py`               |
|12 | C12 | R6 docs/daemon | new: `contrib/systemd/*`, `contrib/launchd/*`, `docs/continuous-mode.md`; mod: `docs/workbench-quickstart.md` | `tests/test_daemon_samples.py` |

## Dependencies

- C1–C7 are fully independent.
- C9 depends on C8 (needs the orchestrator).
- C10 depends on C8 + C9 (emits via C9 plumbing).
- C12 depends on C7, C8, C11 (documents the features).

## Parallel dispatch plan

| Pair | R4-polish | R6-polish | Rationale                                    |
|------|-----------|-----------|----------------------------------------------|
| 1    | C1        | C7        | Smallest warm-up. Independent.               |
| 2    | C2        | C8        | Both medium-size; C8 unlocks C9/C10.         |
| 3    | C3        | C9        | C3 needs C6's session glue idempotent; fine. |
| 4    | C4        | C10       | Both hit peer modules (commands, continuous).|
| 5    | C5        | C11       | C11 modifies pareto.py + optimize.py.        |
| 6    | C6        | C12       | C12 documents everything — last.             |

After pair 2 and 4 → run full suite (`uv run pytest tests/ -x --ignore=tests/api`) as sanity check.

## Commit convention

One commit per task, conventional prefix matching area:

- `feat(workbench): eval case-grid progress widget (R4.7)` — C1
- `feat(workbench): failure preview cards (R4.8)` — C2
- `feat(workbench): cost ticker in status bar (R4.9)` — C3
- `feat(workbench): /diff attempt multi-pane viewer (R4.10)` — C4
- `feat(workbench): /lineage ancestry visualizer (R4.11)` — C5
- `feat(workbench): inline edit of proposals (R4.12)` — C6
- `feat(cli): un-hide agentlab loop group (R6.1)` — C7
- `feat(optimizer): continuous improvement orchestrator (R6.2/R6.3)` — C8
- `feat(notifications): dedupe continuous-loop alerts (R6.4/R6.5)` — C9
- `feat(evals): production-score drift detector (R6.9/R6.10)` — C10
- `feat(optimizer): cost-aware Pareto + --show-tradeoffs (R6.11/R6.12)` — C11
- `docs: continuous-mode, daemon samples, R4 widget docs (R6.13/R6.14/R4.14)` — C12

## Acceptance

After all 12 green:

1. `uv run pytest tests/ -x --ignore=tests/api` — full suite passes (pre-existing tests/api collection errors noted in memory).
2. Update `docs/superpowers/plans/2026-04-16-agentlab-roadmap-master.md` — R4 and R6 marked "✅ Shipped complete".
3. CHANGELOG entry summarizing the 12 gap closures.
4. PR open with task-to-commit mapping and test commands.

## Known caveats

- Pre-existing failures: `tests/api/` has starlette/httpx collection errors; `agent_card` import + `lineage_store` attr from R5 leftovers (per memory `project_agentlab_r5_leftovers.md`). Not this session's problem.
- `tests/api` excluded from full-suite runs.
- Do not add platform-specific canary routers (R6.8 explicitly out of scope — LocalCanaryRouter is final).
