# Three Features Implementation Plan

## Dependency Order
1. **Judge Ops** — extends existing judges/calibration.py, no dependencies on other features
2. **Context Workbench** — reads traces (existing), no feature dependencies
3. **AutoFix** — depends on mutations.py (existing), can reference judge ops for eval quality

All three backends can be built in parallel since they only depend on existing code.

## Feature 1: AutoFix Copilot

### Files to Create
- `optimizer/autofix.py` — AutoFixEngine (proposal lifecycle: suggest → eval → apply)
- `optimizer/autofix_proposers.py` — FailurePatternProposer, RegressionProposer, CostOptimizationProposer
- `optimizer/autofix_vertex.py` — Vertex Prompt Optimizer stub
- `api/routes/autofix.py` — REST endpoints
- `web/src/pages/AutoFix.tsx` — Web UI
- `tests/test_autofix.py` — Backend tests
- `tests/test_autofix_api.py` — API tests

### Files to Modify
- `runner.py` — Add `autofix suggest`, `autofix apply`, `autofix history` CLI commands
- `api/main.py` — Register autofix router
- `data/event_log.py` — Add autofix event types
- `web/src/App.tsx` — Add AutoFix route

### Key Design Decisions
- Proposals are typed dataclasses with `proposal_id`, `mutation`, `expected_lift`, `risk_class`, `status`
- Status lifecycle: `pending` → `evaluating` → `evaluated` → `applied` | `rejected` | `expired`
- Reuse `MutationOperator.apply()` for actual config changes
- SQLite store for proposals (same pattern as ExperimentStore)
- Each proposer is a simple class: `propose(failures, config) -> list[AutoFixProposal]`

### NOT Building
- No autonomous apply mode (always human approval)
- No compound multi-step mutations
- No fine-tuning proposals
- No real Vertex integration (stub only)

### Risk: Low
- Builds on well-tested mutations system
- Isolated module, no changes to existing optimization loop

## Feature 2: Judge Ops

### Files to Create
- `judges/versioning.py` — GraderVersionStore (version configs, diff versions)
- `judges/drift_monitor.py` — DriftMonitor (agreement windows, alerts)
- `judges/human_feedback.py` — HumanFeedbackStore (corrections, disagreement sampling)
- `api/routes/judges.py` — REST endpoints
- `web/src/pages/JudgeOps.tsx` — Web UI
- `tests/test_judge_ops.py` — All judge ops tests

### Files to Modify
- `runner.py` — Add `judges list`, `judges calibrate`, `judges drift` CLI commands
- `api/main.py` — Register judges router
- `data/event_log.py` — Add judge event types
- `web/src/App.tsx` — Add JudgeOps route

### Key Design Decisions
- Version store is SQLite-backed, stores grader config snapshots with version numbers
- Drift monitor extends existing `JudgeCalibrationSuite.compute_drift()` with time-windowed tracking
- Human feedback store records (case_id, judge_verdict, human_score, human_notes)
- Disagreement sampling: sort by |judge_score - human_score| descending

### NOT Building
- No automated judge retraining
- No A/B testing framework for judges
- No real-time monitoring (batch analysis only)

### Risk: Low
- Extends existing calibration.py patterns
- Pure additive — no changes to judge execution path

## Feature 3: Context Engineering Workbench

### Files to Create
- `context/__init__.py` — Package init
- `context/analyzer.py` — ContextAnalyzer (utilization, growth patterns, failure correlation)
- `context/simulator.py` — CompactionSimulator (strategy comparison, memory TTL experiments)
- `context/metrics.py` — Context metrics (utilization ratio, compaction loss, handoff fidelity, staleness)
- `api/routes/context.py` — REST endpoints
- `web/src/pages/ContextWorkbench.tsx` — Web UI
- `tests/test_context.py` — All context workbench tests

### Files to Modify
- `runner.py` — Add `context analyze`, `context simulate`, `context report` CLI commands
- `api/main.py` — Register context router
- `core/types.py` — Add context-specific types (ContextSnapshot, CompactionStrategy)
- `web/src/App.tsx` — Add ContextWorkbench route

### Key Design Decisions
- Analyzer reads from TraceStore — no new data collection needed
- Metrics are computed on-demand from traces, not pre-aggregated
- Simulator takes a trace + strategy → returns simulated context states
- Compaction strategies are simple callables: `(context_tokens, max_tokens) -> compacted_tokens`

### NOT Building
- No real-time context interception
- No automatic policy optimization
- No token-level attention visualization
- No custom compaction strategy editor

### Risk: Low-Medium
- New package (context/) but follows existing patterns
- Adds types to core/types.py — needs careful integration

## Execution Plan

### Phase 1: Backends (parallel via sub-agents)
- Agent 1: AutoFix backend (`optimizer/autofix.py`, `autofix_proposers.py`, `autofix_vertex.py`) + tests
- Agent 2: Judge Ops backend (`judges/versioning.py`, `drift_monitor.py`, `human_feedback.py`) + tests
- Agent 3: Context Workbench backend (`context/`) + tests

### Phase 2: Integration (sequential)
- Update `data/event_log.py` with new event types
- Update `core/types.py` with context types
- Add CLI commands to `runner.py`
- Add API routes
- Register routes in `api/main.py`
- Add web pages
- Update `web/src/App.tsx`

### Phase 3: Validation
- Run full test suite (must stay ≥735)
- Verify CLI commands work
- Verify API endpoints respond
