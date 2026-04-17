# Changelog

## [2.0.0] — 2026-04-17 — Claude-Code Parity

Breaking: launching `agentlab workbench` now starts the Textual TUI by default
when stdout is a TTY. Set `AGENTLAB_NO_TUI=1` for the legacy line-mode REPL.
Also adds a SQLite-backed task subsystem, recurring `/loop`, a wake-up
scheduler, a daemon supervisor, and skill/slash catalogues in the system
prompt. Plan: [docs/superpowers/plans/2026-04-17-claude-code-parity-roadmap.md](docs/superpowers/plans/2026-04-17-claude-code-parity-roadmap.md).
Operator guide: [docs/CC_PARITY.md](docs/CC_PARITY.md).

### Added — Phase 3 (TUI polish)
- 3.1: TUI default-on with `AGENTLAB_NO_TUI` opt-out.
- 3.2: One-keystroke `PermissionOverlay` (y/a/n/p/esc).
- 3.3: Slash-command autocomplete dropdown.
- 3.4: Thread-safe `CommandQueue` for mid-turn input.
- 3.5: Live status bar (model, ctx %, tok/s, cost, branch).
- 3.6: ESC-to-rewind `CheckpointBar`.

### Added — Phase 4 (task subsystem)
- 4.1: SQLite `TaskStore` at `.agentlab/tasks.db`.
- 4.2: `TaskExecutor` worker threads with cancel tokens.
- 4.3: `TaskCreate`/`TaskList`/`TaskGet`/`TaskOutput`/`TaskStop` tools.
- 4.4: `AgentSpawnTool` mirrors writes through to `TaskStore`.
- 4.5: `TaskTree` widget with parent/child status glyphs.
- 4.6: `reconcile_orphaned_tasks(store)` flips zombie rows on startup.

### Added — Phase 5 (model-facing catalogues)
- 5.1: `SkillRegistry.describe_for_model()` + `## Available skills` section.
- 5.2: `slash_catalogue_for_model(reg)` (opt-in via `AGENTLAB_EXPOSE_SLASH_TO_MODEL`).

### Added — Phase 6 (long-running ergonomics)
- 6.1: `/loop <interval> <prompt>` slash with seconds/minutes/hours.
- 6.2: `cli.tasks.scheduler` (`due_tasks`, `reschedule_loop_task`,
  `schedule_one_shot`) and `ScheduleWakeup` tool.
- 6.3: `DaemonSupervisor` + `DaemonState` (PID-file lifecycle, signal-0
  liveness probe).

### Added — Phase 7 (polish & docs)
- 7.1: `cli.doctor_sections` builders for skills / task store /
  instructions / cost.
- 7.2: `docs/CC_PARITY.md` operator guide.
- 7.3: This release.

## [1.0.0] — 2026-04-17 — R4/R6 Cleanup

Closes the 12 gaps left by R4 Slice A and R6 Slice B. With this change, the R1–R6 roadmap is 100% complete (R4.13 per-command error boundary deferred; not blocking).

**Expansion plan:** [docs/superpowers/plans/2026-04-17-agentlab-r4-r6-cleanup.md](docs/superpowers/plans/2026-04-17-agentlab-r4-r6-cleanup.md).

### Added — R4 Workbench Slice B/C (widgets + navigation)

- **Eval case-grid progress widget** (`cli/workbench_app/eval_progress_grid.py`) — live colored grid during `/eval`, one cell per case. Feeds off the R4 Slice A on-event bridge.
- **Failure preview cards** (`cli/workbench_app/failure_card.py`) — after failed cases, renders input/expected/actual/diff plus a one-line fix hint from `optimizer/failure_analyzer.py` (or a deterministic heuristic fallback).
- **Cost ticker in status bar** (`cli/workbench_app/status_bar.py`, `cost_calculator.record_slash_cost`) — `Cost: $X.XX` segment sums conversation turns (R7) and slash-command LLM calls via one sink (`session.increment_cost`).
- **`/attempt-diff <attempt_id>`** (`cli/workbench_app/attempt_diff_slash.py`) — three-pane baseline / candidate YAML / eval-delta viewer. Does NOT collide with the existing `/diff` (system-prompt diff).
- **`/lineage <id>`** (`cli/workbench_app/lineage_view_slash.py`) — ancestry tree (eval_run → attempt → deployment → measurement). Accepts any node id.
- **`/improve accept <id> --edit`** (`cli/workbench_app/improve_slash.py`, `cli/commands/improve.py::run_improve_accept_in_process(candidate_override_path=…)`) — injectable `_prompt_yaml_edit` seam; scratch file at `<workspace>/.agentlab/scratch/accept_<id>.yaml`. Full Textual modal wiring deferred to TUI follow-up.

### Added — R6 Continuous Improvement (Slices A/C)

- **`agentlab loop` visible in help** (`runner.py`) — `hidden=True` removed from both the group and `run` subcommand; `loop` moved from `HIDDEN_COMMANDS` to `SECONDARY_COMMANDS`.
- **Continuous orchestrator** (`optimizer/continuous.py`) — `ContinuousOrchestrator.run_once()` ingests new traces since a watermark, scores via `EvalRunner`, regression-checks against the last N lineage-recorded eval runs, queues an improvement attempt when median drops by ≥ threshold. Records `continuous_cycle` lineage events. **No auto-deploy.**
- **Trace-source CLI flag** — `agentlab loop run --schedule continuous --trace-source <path>` wires the orchestrator. Strict-live respected (exits 12 on mock-fallback, 14 on missing provider key).
- **Notification manager dedupe** (`optimizer/notification_dedupe.py`, `notifications/manager.py`) — 1-hour window per `(event_type, workspace, signature)` via SQLite `notification_log`. `VALID_EVENT_TYPES` extended with `regression_detected`, `improvement_queued`, `continuous_cycle_failed`, `drift_detected`. Backward-compatible: callers without `signature` keep legacy behavior.
- **Production-score drift detector** (`evals/drift.py`) — `detect_distribution_drift(baseline, current)` bucketed KL divergence (default threshold 0.2) with recommendation text. Emits `drift_detected` via the dedupe plumbing. Distinct from judge-agreement drift in `judges/drift_monitor.py` — cross-referenced in both modules.
- **Cost-aware Pareto** (`optimizer/pareto.py`) — `ObjectiveName` enum with `QUALITY`, `SAFETY`, `COST` (direction = MINIMIZE). Default cost weight 0 preserves existing 2D dominance behavior.
- **`agentlab optimize --show-tradeoffs N`** (`cli/commands/optimize.py`) — prints top-N non-dominated candidates with quality / safety / cost columns plus dominates / dominated_by.
- **Daemon samples** (`contrib/systemd/agentlab-loop.service`, `contrib/launchd/com.agentlab.loop.plist`) — reference-only; never auto-installed.
- **Docs** — `docs/continuous-mode.md` (R6 user-facing guide); new R4 widgets section in `docs/workbench-quickstart.md`.

### Deferred

- R4.13 per-command error boundary (surfaces exceptions as error cards without crashing the TUI) — scoped to a follow-up.
- TUI-side Textual `TextArea` modal for `/improve accept --edit`; the injectable seam is in place.
- Wiring real `EvalRunner.case_scores` into `ContinuousOrchestrator.score` path; C8 uses a `score_cases()` seam and drift check is a no-op on today's `EvalRunner` until case-score plumbing lands.
- Cost direction fix in `optimizer/loop.py:211` (currently `ObjectiveDirection.MAXIMIZE`; should be `MINIMIZE` per `ObjectiveName`). Pre-existing inconsistency noted in the C11 report.

---

## [4.0.0-R3] — 2026-04-16 — Optimizer that Learns

R3 makes the optimizer target its own weak spots, makes the pairwise judge LLM-backed with a cache, and moves composite scoring from hardcoded constants to per-workspace yaml. Slice A (R3.1–R3.6) and Slice B (R3.7–R3.13) are both shipped.

**Expansion plan:** [docs/superpowers/plans/2026-04-XX-agentlab-r3-smart-optimizer.md](docs/superpowers/plans/2026-04-XX-agentlab-r3-smart-optimizer.md) — source of truth for acceptance tests (§7) and risk/mitigation matrix (§8).

### Added — Slice A: Coverage-aware proposer + reflection feedback

- **Coverage-gap signal** (`evals/coverage.py`) — `CoverageAnalyzer.gap_signal()` / `gap_signal_dict()` surface under-tested components ranked by severity.
- **Coverage signal in proposer prompt** (`optimizer/llm_proposer.py`) — `LLMProposer` receives a `coverage_signal` kwarg and injects a "Surface X has only N cases" block into the prompt.
- **Reflection wrapper** (`optimizer/reflection.py`) — `ReflectionEngine.read_surface_effectiveness(surface)` returns `{strategy: effectiveness_score}` from the existing `surface_effectiveness` table (no schema migration — see deferred list).
- **Epsilon-greedy strategy ranking** (`optimizer/proposer.py`) — `Proposer._rank_strategies` weights by reflection effectiveness with ε=0.1 exploration. Deterministic under a seeded `random.Random`.
- **`--explain-strategy`** (`agentlab optimize`) — prints one rationale line per ranked strategy with effectiveness scores and any exploration picks.
- **Auto-grown eval cases** (`optimizer/loop.py`) — `Optimizer._maybe_auto_grow_cases()` fires `CardCaseGenerator` per surface when coverage drops below 30%. Gated on `auto_grow_cases` flag; defaults off in test.

### Added — Slice B: LLM judge + configurable weights + calibrated statistics

- **LLM pairwise judge** (`evals/judges/pairwise_judge.py`) — `PairwiseLLMJudge` now routes to an LLM backend with structured output (`{winner, confidence, rationale}`), a SQLite-backed cache (`.agentlab/llm_judge_cache.db`, 30-day TTL keyed on sha256 of both inputs+outputs), and a strict-live escalation mode. Heuristic path remains the default and the fallback.
- **Composite weights yaml** (`evals/composite_weights.py`) — `CompositeWeights` loads from `eval.composite.weights.{quality,safety,latency,cost}` in `agentlab.yaml`. Defaults match pre-R3 constants, validator rejects `sum != 1.0`.
- **`agentlab eval weights`** (`cli/commands/eval.py`) — new `show / set / validate` subcommands for reading and mutating the weights block.
- **Weights snapshot per score** (`evals/scorer.py`) — `CompositeScore.weights_snapshot` freezes the weights used at scoring time. `CompositeScore.rerender(score, weights=None)` classmethod re-renders a historical score under its snapshot (or an override), immune to yaml mutations.
- **Richer paired significance** (`evals/statistics.py`) — `paired_significance()` gained `confidence_interval` (bootstrap, `n_bootstrap=2000` default, seedable) and `calibrated_effect_size` (delta / stddev_diffs). New kwargs: `bootstrap_ci=True`, `n_bootstrap=2000`, `min_calibrated_effect=0.0`. The `is_significant` gate now requires `p < alpha AND abs(calibrated_effect) >= min_calibrated_effect`.

### Deferred (tracked in plan §11)

Strategy-dimension reflection schema; persistence of auto-grown cases back into the workspace dataset; yaml comment preservation on `eval weights set`; `ConstrainedScorer` objective-weight migration; JSON round-trip of `CompositeWeights` inside `CompositeScore.weights_snapshot`; live LLM judge calibration harness; strategy-level lineage events.

---

## [4.0.0-R1] — 2026-04-16 — Trust the Loop: Strict-Live Enforcement

The first slice of the R1–R6 roadmap turns every silent mock fallback into
a loud, actionable signal. The loop now refuses to pretend.

### Added

**Strict-Live Policy** (`cli/strict_live.py`, `cli/exit_codes.py`)
- `--strict-live` flag on `agentlab eval run`, `agentlab build`, and `agentlab optimize` — abort instead of silently falling back to mock execution
- Distinct exit codes for CI: `12` (mock fallback under strict-live), `13` (deploy on degraded eval), `14` (live mode requested but no provider key)
- `MockFallbackError` raised with a formatted breakdown of every mock warning the run accumulated

**Structured Rejection Records** (`optimizer/gates.py`, `optimizer/loop.py`)
- `RejectionReason` enum: `SAFETY_VIOLATION`, `REGRESSION_DETECTED`, `NO_SIGNIFICANT_IMPROVEMENT`, `GATE_FAILED`, `COVERAGE_INSUFFICIENT`
- `RejectionRecord` dataclass with `attempt_id`, `reason`, `detail`, optional baseline/candidate scores, metadata
- `Optimizer.recent_rejections(limit=None)` returns a 200-entry ring buffer (newest first)
- Matching `attempt_id` across `RejectionRecord` and the persisted `OptimizationAttempt` for correlation

**Improvement List Surfacing** (`agentlab improve list`)
- `improve` group is now visible in `--help` (was hidden)
- REASON column in text output, `reason` field in JSON
- `--reason <value>` filter (values: `safety_violation`, `regression_detected`, `no_significant_improvement`, `gate_failed`, `coverage_insufficient`)
- `AGENTLAB_TEST_FORCE_REJECTION` env var for CLI e2e testing

**Deploy Verdict Gate**
- `agentlab deploy` blocks when the latest eval verdict is `Degraded` or `Needs Attention` (exits `13`)
- Override: `--force-deploy-degraded --reason "<justification>"` (minimum 10 chars)
- Dry-run is NOT exempt — a dry-run of an unsafe deploy is still unsafe

**Provider Key Validation** (`cli/provider_keys.py`)
- Conservative validator: rejects keys < 20 chars, keys with whitespace, and clearly mismatched prefixes (e.g. `sk-ant-...` pasted into `OPENAI_API_KEY`)
- Onboarding retries up to 3 times on bad input, then aborts instead of silently saving garbage
- `agentlab init` now prompts for a provider key when interactive and the environment is bare; `InitFlow(interactive=False)` added for scripted use

**Doctor Mock-Reason Clarity** (`cli/mock_reason.py`)
- `agentlab doctor` distinguishes three states: `disabled` (green), `configured` (yellow; YAML opt-in), `missing_provider_key` (red; forced by missing env var)
- JSON output: `mock_reason` and `mock_reason_detail` fields
- Text output: a `Fix:` hint specific to each reason

### Changed

- `optimizer.proposer.Proposer()` default is now `use_mock=False`. The optimizer loop no longer silently constructs a mock proposer when the caller omits one.
- Loud errors replace silent skips across eval/build/optimize when `--strict-live` is in effect.

### Tests

Over 80 new tests across `test_exit_codes.py`, `test_strict_live.py`, `test_eval_strict_live.py`, `test_strict_live_propagation.py`, `test_proposer_default_live.py`, `test_gates_rejection.py`, `test_loop_rejections.py`, `test_improve_list_rejections.py`, `test_deploy_verdict_gate.py`, `test_provider_keys.py`, `test_onboarding_validation.py`, `test_init_flow_provider.py`, `test_template_mock_audit.py`, `test_mock_reason.py`, `test_doctor_mock_reason.py`.

### Migration notes

- Existing `--require-live` flag on `eval run` is preserved for backwards compatibility; `--strict-live` is the new canonical name and implies `--require-live`.
- No config changes required. Users who depend on mock mode in automation should pass `--no-strict-live` (the default) or set `optimizer.use_mock: true` explicitly — which will now show up as "configured" rather than "missing key" in `agentlab doctor`.

---

## [3.0.0] — 2026-03-24 — Modular Registry, Trace Grading + Blame Map, NL Scorer (1,131 tests)

### Added

**Modular Registry** (`registry/`)
- RegistryStore with SQLite-backed versioned CRUD for 4 item types
- SkillRegistry — versioned instruction/example/constraint bundles
- PolicyRegistry — versioned rules with hard/soft enforcement
- ToolContractRegistry — versioned tool schemas with replay mode and side-effect classification
- HandoffSchemaRegistry — versioned handoff schemas with validation rules
- Bulk import from YAML/JSON files
- Search, diffing, and deprecation support
- CLI: `agentlab registry list|show|add|diff|import`
- API: 6 endpoints under `/api/registry/`

**Trace Grading** (`observer/trace_grading.py`)
- 7 span-level graders: routing, tool_selection, tool_argument, retrieval_quality, handoff_quality, memory_use, final_outcome
- TraceGrader orchestrator with automatic grader applicability detection
- SpanGrade with score, evidence, failure_reason, metadata

**Blame Map** (`observer/blame_map.py`)
- BlameCluster with impact scoring (count/total_traces) and trend detection (growing/shrinking/stable)
- Failure clustering by (grader_name, agent_path, failure_reason)
- Time-windowed computation from trace store

**NL Scorer Generation** (`evals/nl_scorer.py`, `api/routes/scorers.py`)
- Create eval scorers from natural language descriptions
- ScorerSpec with named dimensions and scoring criteria
- Iterative refinement with additional NL criteria
- Test scorers against sample eval results
- CLI: `agentlab scorer create|list|show|refine|test`
- API: 5 endpoints under `/api/scorers/`

**Frontend**
- Registry page — browse/search skills, policies, tools, handoff schemas
- Blame Map page — visualize failure clusters with impact and trends
- Scorer Studio page — create and test NL scorers
- CLI: `agentlab trace grade|blame|graph`
- API: 3 new trace endpoints (blame, grades, graph)

### Numbers
| Metric | Before | After |
|--------|--------|-------|
| Test suite | 951 | 1,131 |
| Python backend | ~40,000 lines | ~46,600 lines |
| API endpoints | 60 | 75 |
| Frontend pages | 16 | 19 |
| Route modules | 15 | 18 |

---

## [2.5.0] — 2026-03-24 — Pro-Mode Prompt Optimization (951 tests)

### Added

**Pro-Mode Prompt Optimization** (`optimizer/prompt_opt/`)
- ProSearchStrategy orchestrator with algorithm auto-selection
- MIPROv2 — Bayesian search over (instruction, example_set) space with kNN surrogate
- BootstrapFewShot — DSPy-inspired teacher-student demonstration bootstrapping
- GEPA — Gradient-free evolutionary prompt adaptation with tournament selection, LLM crossover/mutation
- SIMBA — Simulation-based iterative hill-climbing optimization
- ProConfig with budget controls and configurable candidates/rounds
- `pro` search strategy added to optimizer configuration

### Numbers
| Metric | Before | After |
|--------|--------|-------|
| Test suite | 862 | 951 |

---

## [2.2.0] — 2026-03-23 — AutoFix, Judge Ops, Context Workbench (862 tests)

### Added

**AutoFix Copilot** (`api/routes/autofix.py`)
- AI-driven failure analysis → constrained improvement proposals
- Review-before-apply workflow with proposal lifecycle
- CLI: `agentlab autofix suggest|apply|history`
- API: 4 endpoints under `/api/autofix/`

**Judge Ops** (`judges/`, `api/routes/judges.py`)
- GraderVersionStore for judge versioning
- DriftMonitor for agreement rate tracking
- HumanFeedbackStore for calibration corrections
- CLI: `agentlab judges list|calibrate|drift`
- API: 4 endpoints under `/api/judges/`

**Context Engineering Workbench** (`context/`)
- ContextAnalyzer with growth pattern detection (linear/exponential/sawtooth/stable)
- CompactionSimulator with 3 strategies (aggressive/balanced/conservative)
- ContextMetrics (utilization, compaction loss, handoff fidelity, memory staleness)
- CLI: `agentlab context analyze|simulate|report`
- API: 3 endpoints under `/api/context/`

**Frontend**
- AutoFix page
- Judge Ops page
- Context Workbench page

### Numbers
| Metric | Before | After |
|--------|--------|-------|
| Test suite | 735 | 862 |
| Frontend pages | 13 | 16 |
| API endpoints | 38 | ~52 |

---

## [2.1.0] — 2026-03-24 — v4 Research Port (CC + Codex Merge)

### Added

**9-Dimension Evaluation Detail Engine** (`evals/scorer.py`, `evals/runner.py`)
- Added v4 global dimensions:
  task success, response quality, safety compliance, latency p50/p95/p99,
  token cost average, tool correctness, routing accuracy, handoff fidelity,
  user satisfaction proxy
- Added per-agent dimension rollups:
  specialist, orchestrator, and shared-agent metric blocks
- Preserved legacy simple composite view for default UX

**Constrained Pareto Archive** (`optimizer/pareto.py`)
- Explicit feasible vs infeasible candidate pools
- Pareto dominance filtering over feasible candidates
- Knee-point recommendation for default deployment suggestion

**Hybrid Search Orchestrator Primitives** (`optimizer/search.py`)
- Search strategies: `simple`, `adaptive`, `full`
- Operator families: MCTS exploration, local tuning, diversity injection
- Bandit selector with `ucb` and `thompson` policies
- Curriculum stage manager for full-mode opportunity progression
- Full-mode Pareto-front metadata in search results

**Anti-Goodhart Guardrails** (`evals/anti_goodhart.py`, `optimizer/loop.py`)
- Dual holdout checks (fixed + rolling holdout)
- Holdout rotation cadence tracking
- Drift-aware baseline re-anchoring
- Judge variance estimation and rejection thresholds

**API + UI Detail Views**
- Eval API now returns `global_dimensions` + `per_agent_dimensions`
- Optimize API now returns strategy diagnostics (family selection, governance notes)
- New endpoint: `GET /api/optimize/pareto`
- UI detail surfaces:
  `EvalDetail` advanced 9-dimension/per-agent panel,
  `Optimize` Pareto front + strategy diagnostics panel

### Changed

**Strategy-Aware Optimizer Loop** (`optimizer/loop.py`)
- Default remains `simple` proposer path (failure-bucket mapping preserved)
- `adaptive` and `full` now route through hybrid search orchestration
- Added runtime-configurable search and guardrail settings via `agentlab.yaml`

**Runtime Config Schema** (`agent/config/runtime.py`, `agentlab.yaml`)
- Added optimizer strategy fields:
  `search_strategy`, `bandit_policy`,
  search budget limits, anti-Goodhart thresholds

## [2.0.0] — 2026-03-23 — P0 Architectural Overhaul

### Added

**Typed Mutation Registry** (`optimizer/mutations.py`)
- `MutationOperator` with surface, risk_class, preconditions, validator, rollback_strategy
- `MutationRegistry` with filtering by surface, risk, autodeploy capability
- 9 first-party operators: instruction_rewrite, few_shot_edit, tool_description_edit, model_swap, generation_settings, callback_patch, context_caching, memory_policy, routing_edit

**Experiment Cards** (`optimizer/experiments.py`)
- `ExperimentCard` with hypothesis, touched_surfaces, diff_summary, significance stats
- `ExperimentStore` (SQLite) for full experiment lifecycle tracking
- Status lifecycle: pending → running → accepted/rejected/expired

**Trace Engine** (`observer/traces.py`)
- `TraceEvent` and `TraceSpan` for structured event collection
- `TraceCollector` for recording tool calls, model calls, errors, agent transfers
- `TraceStore` (SQLite) with indexes on trace_id, session_id, agent_path

**Ranked Opportunity Queue** (`observer/opportunities.py`)
- `OptimizationOpportunity` with severity, prevalence, recency, business_impact scoring
- `OpportunityQueue` (SQLite) replacing `needs_optimization: bool`
- `FailureClusterer` mapping failure buckets to opportunities with recommended operators

**Eval Data Engine** (`evals/data_engine.py`)
- 4 eval set types: golden, rolling_holdout, challenge, live_failure_queue
- 7 evaluation modes: target_response, target_tool_trajectory, rubric_quality, rubric_tool_use, hallucination, safety, user_simulation
- `TraceToEvalConverter` for automatic bad-trace → eval-case conversion
- `EvalSetManager` (SQLite) for eval set versioning

**Replay Harness** (`evals/replay.py`)
- Side-effect classification: pure, read_only_external, write_external_reversible, write_external_irreversible
- `ReplayHarness` records baseline tool I/O and stubs replayable tools
- `ReplayStore` (SQLite) for session persistence

**Multi-Hypothesis Search Engine** (`optimizer/search.py`)
- Budget-aware multi-candidate generation and evaluation
- `OperatorPerformanceTracker` learns which operators work for which failures
- Deduplication against past failed attempts

**Google Prompt Optimizer Stubs** (`optimizer/mutations_google.py`)
- ZeroShotOptimizer, FewShotOptimizer, DataDrivenOptimizer (stubs, requires Vertex credentials)

**Workflow/Topology Optimization** (`optimizer/mutations_topology.py`, experimental)
- detect_transfer_loops, reduce_unnecessary_parallelism, add_deterministic_steps
- All marked experimental, supports_autodeploy=False

**Context & Memory Policies** (`agent/config/schema.py`)
- ContextCachingConfig, CompactionConfig, MemoryPolicyConfig added to AgentConfig
- Backwards-compatible defaults

**Frontend Pages**
- Opportunities page — ranked queue with priority badges and operator recommendations
- Experiments page — reviewable experiment cards with filter tabs
- Traces page — event timeline viewer with expandable traces

**Frontend Components**
- ExperimentCard, OpportunityItem, TraceTimeline, ConstraintBadge

**API Endpoints**
- GET /api/traces/recent, /api/traces/{id}, /api/traces/search, /api/traces/errors, /api/traces/sessions/{id}
- GET /api/opportunities, /api/opportunities/{id}, /api/opportunities/count
- POST /api/opportunities/{id}/status
- GET /api/experiments, /api/experiments/{id}, /api/experiments/stats

### Changed

**Scoring: Constraints vs Objectives** (`evals/scorer.py`)
- `ConstrainedScorer` separates hard constraints (safety, P0 regression) from optimization objectives (quality, latency, cost)
- Three modes: weighted (backwards compat), constrained, lexicographic
- Safety is no longer both a gate AND 25% of weighted composite

**Gates** (`optimizer/gates.py`)
- `check_constraints()` replaces `check_safety()` as first hard gate
- Backwards-compatible: falls back to safety check for scores without constraint data

**Statistical Layer** (`evals/statistics.py`)
- Added clustered bootstrap by conversation/user
- Added sequential testing (O'Brien-Fleming alpha spending)
- Added Holm-Bonferroni multiple-hypothesis correction
- Added minimum sample-size requirements
- Added judge-variance estimation
- All additions are backwards-compatible; original `paired_significance()` unchanged

### Numbers

| Metric | Before | After |
|--------|--------|-------|
| Python backend | ~9,500 lines | ~14,000 lines |
| React frontend | ~4,500 lines | ~6,000 lines |
| Test suite | 76 tests | 157 tests |
| Frontend pages | 9 | 12 |
| React components | 20 | 24 |
| API endpoints | 18 | 28 |
| New Python modules | — | 12 |
