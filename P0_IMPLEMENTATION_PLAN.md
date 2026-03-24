# P0 Implementation Plan — AutoAgent VNextCC Architectural Overhaul

## Current State Summary

- **Python backend**: ~9.5K lines across `runner.py`, `optimizer/`, `evals/`, `observer/`, `deployer/`, `logger/`, `api/`, `agent/`
- **React frontend**: ~4.5K lines, 9 pages, 20 components
- **Tests**: 42 tests across 14 files
- **Core loop**: Observe → Detect → Propose → Validate → Eval → Gate → Deploy → Checkpoint

## Design Principles (preserved)

1. **Gemini-first** — default model stays Gemini 2.5 Pro
2. **Single-process** — no Celery/Redis/Kafka; SQLite for persistence
3. **Headless-first** — CLI + API primary, web console for insight
4. **User journey simplicity** — `autoagent init` → `autoagent run` → see results

---

## Architecture: Before → After

### Before
```
Observer → (needs_optimization: bool) → Proposer → (single config change) → Gates → Deploy
```

### After
```
TraceCollector → OpportunityQueue → SearchEngine → [MutationOperator...] → ExperimentCards
    → ReplayHarness → ConstrainedGates → StatisticalLayer → Deploy
```

### New Architecture Diagram
```
┌──────────────────────────────────────────────────────────────────────┐
│                         Operator Interfaces                          │
│   CLI (autoagent ...)      REST API (/api/*)      Web Console        │
└─────────────────────────────────┬────────────────────────────────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │  FastAPI + TaskManager     │
                    └─────────────┬─────────────┘
                                  │
     ┌────────────┬───────────────┼───────────────┬────────────┐
     │            │               │               │            │
┌────▼─────┐ ┌───▼────┐   ┌──────▼──────┐  ┌─────▼─────┐ ┌───▼────┐
│  Trace   │ │Opport- │   │  Search     │  │  Deploy   │ │ Replay │
│Collector │ │unity   │   │  Engine     │  │  er       │ │Harness │
│(ADK/OTEL)│ │Queue   │   │(Multi-hyp.) │  │(Canary)   │ │        │
└────┬─────┘ └───┬────┘   └──────┬──────┘  └─────┬─────┘ └───┬────┘
     │           │               │                │            │
     │     ┌─────▼──────┐  ┌────▼──────────┐ ┌───▼────┐       │
     │     │ Failure    │  │ Mutation      │ │Constrained│     │
     │     │ Clustering │  │ Operator      │ │Gates +   │     │
     │     │            │  │ Registry      │ │Stats     │     │
     │     └────────────┘  └──────┬────────┘ └──────────┘     │
     │                            │                            │
     │                    ┌───────▼────────┐                   │
     │                    │ Experiment     │                   │
     │                    │ Cards          │                   │
     │                    └───────┬────────┘                   │
     │                            │                            │
     └────────────────────────────┼────────────────────────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │  Eval Data Engine          │
                    │  (trace→eval, 4 set types, │
                    │   7 evaluation modes)       │
                    └─────────────┬─────────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │   Persistence Layer        │
                    │  SQLite: traces, evals,    │
                    │  experiments, opportunities,│
                    │  operator memory, dead ltrs │
                    └───────────────────────────┘
```

---

## Feature → Implementation Mapping

### Feature 1: Typed Mutation Registry
**Complexity:** Medium | **Files:** New `optimizer/mutations.py`
**What changes:**
- Create `MutationOperator` dataclass with: `name`, `surface`, `risk_class`, `preconditions`, `validator`, `rollback_strategy`, `estimated_eval_cost`, `supports_autodeploy`
- Create `MutationRegistry` with register/lookup/list_by_surface
- Register 9 first-party operators: `instruction_rewrite`, `few_shot_edit`, `tool_description_edit`, `model_swap`, `generation_settings`, `callback_patch`, `context_caching`, `memory_policy`, `routing_edit`
- Update `Proposer` to select operators from registry instead of hardcoded mock logic
**Keep:** Proposer interface, mock fallback
**Replace:** Hardcoded mock_propose strategy selection

### Feature 2: Patch-based Candidates with Experiment Cards
**Complexity:** Medium | **Files:** New `optimizer/experiments.py`
**What changes:**
- Create `ExperimentCard` dataclass with all specified fields
- Create `ExperimentStore` (SQLite-backed)
- Update `Optimizer.optimize()` to produce ExperimentCards instead of raw config dicts
- Each optimization attempt now has a reviewable experiment card
**Keep:** OptimizationMemory (becomes experiment history)
**Refactor:** `OptimizationAttempt` → wraps `ExperimentCard`

### Feature 3: ADK Event/Trace-based Diagnosis
**Complexity:** High | **Files:** New `observer/traces.py`, update `observer/`
**What changes:**
- Create `TraceEvent` dataclass capturing: tool calls, responses, state deltas, errors, latency, tokens, agent path
- Create `TraceCollector` that wraps agent invocations and emits structured events
- Create `TraceStore` (SQLite) for persisting traces with indexes on invocation_id, session_id, agent_path
- Update Observer to analyze traces, not just conversation-level metrics
**Keep:** HealthMetrics, AnomalyDetector (extended with trace data)
**Replace:** Shallow conversation-level analysis as sole signal

### Feature 4: Ranked Opportunity Queue
**Complexity:** Medium | **Files:** New `observer/opportunities.py`
**What changes:**
- Create `OptimizationOpportunity` with: cluster_id, failure_family, affected_agent_path, affected_surface_candidates, severity, prevalence, recency, business_impact, sample_traces, recommended_operator_families
- Create `OpportunityQueue` (SQLite-backed, priority-sorted)
- Create failure clustering: group by trace signatures (tool errors, transfer chains, latency spikes, safety flags)
- Separate queues: drift, new_failures, cost_latency_optimization
**Keep:** FailureClassifier (extended)
**Replace:** `needs_optimization: bool` → ranked queue

### Feature 5: Trace-to-Eval Data Engine
**Complexity:** High | **Files:** New `evals/data_engine.py`, update `evals/runner.py`
**What changes:**
- Create `EvalSet` types: `golden`, `rolling_holdout`, `challenge`, `live_failure_queue`
- Create `EvalSetManager` for managing eval sets with versioning
- Create trace→eval case converter: bad traces become eval cases automatically
- Add evaluation modes: target_response, target_tool_trajectory, rubric_quality, rubric_tool_use, hallucination, safety, user_simulation
- Each mode maps to a scorer function
**Keep:** EvalRunner, CompositeScorer, existing test cases
**Extend:** EvalResult with evaluation mode field

### Feature 6: Replay and Shadow Harness with Side-Effect Classes
**Complexity:** Medium | **Files:** New `evals/replay.py`, new `evals/side_effects.py`
**What changes:**
- Create `SideEffectClass` enum: `pure`, `read_only_external`, `write_external_reversible`, `write_external_irreversible`
- Create `ToolClassification` registry mapping tool names → side-effect classes
- Create `ReplayHarness`: records baseline tool I/O, stubs tools on replay
- Only `pure` and `read_only_external` tools auto-replayed
**Keep:** Mock agent function (extended as replay source)

### Feature 7: Separate Constraints from Objectives in Scoring
**Complexity:** Medium | **Files:** Update `evals/scorer.py`, `optimizer/gates.py`
**What changes:**
- Split scoring: hard constraints (safety, policy, P0 regression) vs optimization objectives (quality, cost, latency)
- Hard constraints = binary pass/fail gates (not weighted into composite)
- Support lexicographic optimization: quality first, then cost/latency within feasible set
- Support constrained mode alongside existing weighted mode for backwards compat
**Keep:** CompositeScorer (add mode parameter)
**Replace:** Safety-as-both-gate-and-weight pattern

### Feature 8: Statistical Layer for Continuous Search
**Complexity:** Medium | **Files:** Update `evals/statistics.py`
**What changes:**
- Add minimum sample-size requirements per metric family
- Add clustered bootstrap by conversation/user
- Add sequential-testing control (for multi-day runs)
- Add multiple-hypothesis correction (Holm-Bonferroni) across candidate batches
- Add judge-variance estimation (repeated judging on subset)
- Store: effect_size, confidence_interval, power_estimate in run record
- Require improvement on BOTH fixed holdout AND rolling holdout before promotion
**Keep:** `paired_significance()` (extended)
**Add:** `clustered_bootstrap()`, `sequential_test()`, `multiple_hypothesis_correction()`

### Feature 9: Multi-Hypothesis Search Engine
**Complexity:** High | **Files:** New `optimizer/search.py`, update `optimizer/loop.py`
**What changes:**
- Each cycle: cluster failures → generate diverse mutations → rank by lift/risk/novelty → evaluate top K under budget → learn which operators work for which clusters
- Memory of failed ideas (de-duplication)
- Budget-aware evaluation (don't eval all candidates)
- Explicit keep/discard with branch advancement
**Keep:** Optimizer class (refactored internally)
**Replace:** Single-proposal-per-cycle → multi-candidate search

### Feature 10: Google Prompt Optimizer Integration
**Complexity:** Low (stub) | **Files:** New `optimizer/mutations_google.py`
**What changes:**
- Stub three operator classes: `ZeroShotOptimizer`, `FewShotOptimizer`, `DataDrivenOptimizer`
- Each wraps Vertex prompt optimizer API (TODO: requires credentials)
- Register as operators in MutationRegistry
**Implementation:** Stub with TODO markers per master prompt instructions

### Feature 11: Context & Memory Policies as Optimization Surfaces
**Complexity:** Low-Medium | **Files:** Update `optimizer/mutations.py`, `agent/config/schema.py`
**What changes:**
- Add operators: context_caching_threshold, context_compaction, memory_preload, memory_writeback, session_state_template
- Extend AgentConfig schema with `context_caching`, `memory_policy`, `compaction` sections
- Register operators in MutationRegistry
**Keep:** Existing config schema (extended)

### Feature 12: Workflow/Topology Optimization (experimental)
**Complexity:** Low-Medium | **Files:** New `optimizer/mutations_topology.py`
**What changes:**
- Create topology analysis operators: detect transfer loops, bad routing, unnecessary parallelism
- Mark as experimental in code and UI
- Any topology change = PR-only, never auto-promoted
**Implementation:** Experimental flag, UI warning badge

---

## Execution Order (dependency-aware)

```
Phase 1 — Foundation (no dependencies)
├── Feature 1: Mutation Registry         (Stream A)
├── Feature 6: Side-Effect Classes       (Stream A)
├── Feature 7: Constraints vs Objectives (Stream D)
└── Feature 8: Statistical Layer         (Stream C)

Phase 2 — Core Engine (depends on Phase 1)
├── Feature 3: Trace/Diagnosis Engine    (Stream B, needs mutations)
├── Feature 4: Opportunity Queue         (Stream B, needs traces)
├── Feature 5: Eval Data Engine          (Stream B, needs traces + side-effects)
└── Feature 2: Experiment Cards          (Stream A, needs mutations)

Phase 3 — Search & Integration (depends on Phase 2)
├── Feature 9: Multi-Hypothesis Search   (Stream C, needs queue + mutations + stats)
├── Feature 10: Google Optimizer (stub)  (Stream A, needs mutation registry)
├── Feature 11: Context/Memory Policies  (Stream A, needs mutation registry)
└── Feature 12: Workflow/Topology (exp.) (Stream A, needs mutation registry)

Phase 4 — Frontend & Polish
├── Frontend: Opportunity Queue page
├── Frontend: Experiment Cards view
├── Frontend: Trace Viewer page
├── Frontend: Replay Harness controls
├── Frontend: Updated scoring display (constraints vs objectives)
├── Frontend: Search engine dashboard
└── API routes for all new endpoints

Phase 5 — Verification
├── Run full test suite
├── Build frontend
├── Update ARCHITECTURE_OVERVIEW.md
├── Write CHANGELOG.md
└── Final commit
```

---

## Files: Keep vs Replace vs Refactor vs Create

### KEEP (no changes needed)
- `logger/store.py` — ConversationStore is solid
- `logger/middleware.py` — outcome/safety detection works
- `deployer/versioning.py` — ConfigVersionManager is clean
- `deployer/canary.py` — Canary logic is correct
- `api/tasks.py` — TaskManager is fine
- `api/websocket.py` — ConnectionManager works
- `optimizer/providers.py` — Multi-provider router is good
- `optimizer/reliability.py` — All reliability primitives are solid
- `agent/` — Agent code is separate, don't touch
- `web/src/components/` — Most components reusable as-is
- `web/src/lib/websocket.ts` — WebSocket client works

### REFACTOR
- `optimizer/gates.py` → Add constraint/objective separation (Feature 7)
- `optimizer/loop.py` → Integrate search engine, experiment cards (Features 2, 9)
- `optimizer/proposer.py` → Use mutation registry (Feature 1)
- `optimizer/memory.py` → Extend with experiment card linkage (Feature 2)
- `evals/scorer.py` → Add constrained/lexicographic modes (Feature 7)
- `evals/statistics.py` → Add clustered bootstrap, sequential testing, etc. (Feature 8)
- `evals/runner.py` → Add eval set types, evaluation modes (Feature 5)
- `observer/__init__.py` → Integrate opportunity queue (Feature 4)
- `observer/classifier.py` → Feed into clustering (Feature 4)
- `observer/metrics.py` → Add trace-derived metrics (Feature 3)
- `agent/config/schema.py` → Add context/memory/compaction config sections (Feature 11)
- `autoagent.yaml` → Add new config sections
- `runner.py` → Add new CLI commands
- `web/src/lib/types.ts` → Add new types
- `web/src/lib/api.ts` → Add new API hooks
- `web/src/App.tsx` → Add new routes
- `web/src/components/Sidebar.tsx` — Add new nav items

### CREATE (new files)
- `optimizer/mutations.py` — MutationOperator + Registry (Feature 1)
- `optimizer/experiments.py` — ExperimentCard + Store (Feature 2)
- `optimizer/search.py` — Multi-hypothesis search engine (Feature 9)
- `optimizer/mutations_google.py` — Google optimizer stubs (Feature 10)
- `optimizer/mutations_topology.py` — Topology operators (Feature 12)
- `observer/traces.py` — TraceEvent + TraceCollector + TraceStore (Feature 3)
- `observer/opportunities.py` — OpportunityQueue + clustering (Feature 4)
- `evals/data_engine.py` — Eval set management + trace→eval (Feature 5)
- `evals/replay.py` — ReplayHarness (Feature 6)
- `evals/side_effects.py` — SideEffectClass + ToolClassification (Feature 6)
- `web/src/pages/Opportunities.tsx` — Opportunity queue page
- `web/src/pages/Experiments.tsx` — Experiment cards page
- `web/src/pages/Traces.tsx` — Trace viewer page
- `web/src/components/ExperimentCard.tsx` — Card component
- `web/src/components/OpportunityItem.tsx` — Queue item component
- `web/src/components/TraceTimeline.tsx` — Trace visualization
- `web/src/components/ConstraintBadge.tsx` — Constraint pass/fail badge
- `api/routes/traces.py` — Trace API endpoints
- `api/routes/opportunities.py` — Opportunity queue endpoints
- `api/routes/experiments.py` — Experiment card endpoints
- `tests/test_mutations.py` — Mutation registry tests
- `tests/test_experiments.py` — Experiment card tests
- `tests/test_traces.py` — Trace engine tests
- `tests/test_opportunities.py` — Opportunity queue tests
- `tests/test_search.py` — Search engine tests
- `tests/test_replay.py` — Replay harness tests
- `tests/test_scoring_v2.py` — Constraint/objective scoring tests
- `tests/test_statistics_v2.py` — Extended stats tests

---

## What We Intentionally Simplify or Defer

1. **Feature 10 (Google Prompt Optimizers)** — Stub only, no Vertex credentials
2. **Feature 12 (Workflow/Topology)** — Experimental flag, basic operators only
3. **BigQuery analytics** — Not needed; SQLite is sufficient for single-process
4. **OTEL export** — Traces stored locally in SQLite; OTEL export is a future add
5. **User simulation eval mode** — Stub the interface, don't implement the LLM loop
6. **Hallucination/groundedness eval** — Stub scorer, real implementation needs retrieval context
7. **Judge-variance estimation** — Implement the sampling, but actual repeated judging needs LLM calls

---

## Risk Mitigation

1. **Backwards compatibility**: The existing `autoagent optimize` → `autoagent deploy` flow MUST keep working. New features are additive.
2. **Config migration**: New `autoagent.yaml` sections have defaults. Old configs continue to work.
3. **Test coverage**: Every new module gets tests. Existing 42 tests must keep passing.
4. **Frontend**: New pages are additive. Existing pages keep working but get enhanced data.

---

## Estimated Output

| Category | Estimate |
|----------|----------|
| New Python files | ~18 |
| Refactored Python files | ~12 |
| New frontend files | ~7 |
| Refactored frontend files | ~5 |
| New test files | ~8 |
| New test functions | ~60+ |
| New API endpoints | ~10 |
| New CLI commands | ~4 |
