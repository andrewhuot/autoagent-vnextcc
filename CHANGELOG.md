# Changelog

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
