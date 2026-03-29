# Researcher-Advised Refactor Plan

## Overview

Transform AutoAgent from a prompt optimizer into **CI/CD for agents**. The core insight: the moat is not "we mutate prompts" — it's "we can faithfully replay, grade, and safely improve real enterprise agent workflows."

## Architecture Summary

### Before (Current)
- Flat 9-dimension scoring (all metrics as peers)
- Trajectory matching as default eval mode
- 4-class side-effect classification
- Scalar handoff fidelity
- LLM judge as utility function
- Simple trace-to-eval conversion
- Prompt-focused mutation surface

### After (Target)
- 4-layer metric hierarchy (gates → outcomes → SLOs → diagnostics)
- End-state evaluation as default
- 5-mode replayability matrix per tool
- Structured handoff artifacts
- Judge subsystem with calibration
- Eval compiler with PII scrub, dedup, negative controls
- CI/CD pipeline: versioned agent graphs → eval → promote → canary → release

## Work Streams

### Stream A — Core Domain Objects (Opus)
**New package: `core/`**

Files to create:
- `core/__init__.py` — Package exports
- `core/types.py` — All new first-class domain objects:
  - `AgentGraphVersion` — Framework-neutral IR (typed nodes: router, specialist, guardrail, skill, memory, tool_contract, handoff_schema, judge; typed edges with edge_type)
  - `SkillVersion` — Versioned instruction + script + asset bundles
  - `ToolContractVersion` — Tool name, schema, side-effect class, replay mode, validator, sandbox policy
  - `PolicyPackVersion` — Safety rules, guardrail thresholds, authorization policies
  - `EnvironmentSnapshot` — Captured external system state for replay
  - `GraderBundle` — Ordered grader stack per eval case
  - `EvalCase` — (task, environment_snapshot, grader_bundle, expected_end_state, diagnostic_trace_features)
  - `CandidateVariant` — Versioned diff against AgentGraphVersion
  - `ArchiveEntry` — Pareto archive entry with named role
- `core/handoff.py` — Structured handoff artifacts:
  - `HandoffArtifact` — goal, constraints, known_facts, unresolved_questions, allowed_tools, expected_deliverable, evidence_refs
  - `HandoffComparator` — Field-level completeness and accuracy scoring (replaces scalar handoff_fidelity)

**Integration points:**
- `ToolContractVersion.replay_mode` replaces `SideEffectClass` as canonical replay classification
- `EvalCase` extends existing `TestCase` with end-state and grader bundle
- `ArchiveEntry.role` feeds into Pareto archive named roles
- `AgentGraphVersion` provides the IR that mutations operate on
- Existing code continues to work — new types are additive, not replacing

### Stream B — Judge Subsystem + Eval Compiler + 4-Layer Scorer (Opus)
**New package: `judges/`**

Files to create:
- `judges/__init__.py` — Package exports
- `judges/deterministic.py` — Executable state-check graders, regex validators, business invariant checks
- `judges/rule_based.py` — Configurable rule validators (format, length, required fields)
- `judges/llm_judge.py` — Frozen primary LLM judge with evidence spans
- `judges/audit_judge.py` — Cross-family audit judge for promotions
- `judges/calibration.py` — Judge calibration suite (agreement, drift, position bias, verbosity bias, disagreement rate)
- `judges/grader_stack.py` — GraderBundle execution: deterministic → rule-based → LLM → human flag

**Judge output schema:** Every judge returns `JudgeVerdict` with:
- `score: float` (0-1)
- `passed: bool`
- `evidence_spans: list[str]` — Specific text spans supporting the verdict
- `failure_reasons: list[str]` — Structured failure categorization
- `confidence: float` (0-1)
- `judge_id: str` — Which judge produced this

**Files to modify:**

`evals/scorer.py` — 4-layer metric hierarchy:
- Layer 1 (Hard Gates): safety_compliance, authorization_privacy, state_integrity, p0_regressions
- Layer 2 (North-Star Outcomes): task_success_rate, groundedness, user_satisfaction_proxy
- Layer 3 (Operating SLOs): latency_p50, latency_p95, latency_p99, token_cost, escalation_rate
- Layer 4 (Diagnostics): tool_correctness, routing_accuracy, handoff_fidelity, recovery_rate, clarification_quality, judge_disagreement_rate

New classes:
- `MetricLayer` enum (HARD_GATE, OUTCOME, SLO, DIAGNOSTIC)
- `LayeredMetric` — metric name, layer, direction, threshold
- `LayeredDimensionScores` — Extends DimensionScores with layer classification
- `LayeredScorer` — Wraps EnhancedScorer, adds layer-aware optimization logic

The optimizer searches Layer 2 within Layer 1 gates, subject to Layer 3 SLOs. Layer 4 is diagnosis only.

`evals/data_engine.py` — Eval compiler enhancements:
- `pii_scrub(text)` — Regex-based PII removal (emails, phones, SSNs, names)
- `near_duplicate_detect(cases)` — Similarity-based dedup
- `reproducibility_test(case, agent_fn)` — Replay and compare
- `business_impact_score(case)` — Severity × frequency estimation
- `root_cause_tag(case)` — Auto-categorize failure type
- `solvability_check(case)` — Is there a known good solution?
- `generate_negative_controls(case)` — Counter-examples
- `EvalSuiteType` enum: contract_regression, capability, adversarial, discovery, judge_calibration

`evals/runner.py` — End-state evaluation:
- Default mode = end-state comparison
- `expected_end_state` as structured data on EvalCase
- `EnvironmentSnapshot` diffing for actual vs expected
- Trajectory matching remains available but optional

### Stream C — Replay Matrix + Environment Snapshots (Sonnet)

**Files to modify:**

`evals/side_effects.py`:
- Add `ReplayMode` enum: deterministic_stub, recorded_stub_with_freshness, live_sandbox_clone, simulator, forbidden
- Extend `ToolClassification` with: replay_mode, validator, sandbox_policy, freshness_window
- Keep `SideEffectClass` for backward compat, add migration helper
- `ToolContractRegistry` — Maps tools to full contracts (extends ToolClassificationRegistry)

`evals/replay.py`:
- `EnvironmentSnapshot` capture and restore
- `SnapshotDiff` — Compare actual vs expected end state
- Per-tool replay routing based on ReplayMode
- Freshness window checking for recorded stubs
- Sandbox clone support (interface for future implementation)

### Stream D — Search Refinements + Archive + Training Escalation + Release Manager (Sonnet)

**Files to modify:**

`optimizer/search.py`:
- Optimization unit = failure_family × mutation_surface × eval_bundle × experiment_loop
- Structured critique ingestion (evidence_spans + failure_reasons from judges)
- Contextual bandit value = expected_lift × business_impact × uncertainty ÷ eval_cost
- New candidates can branch from any archive entry

`optimizer/pareto.py`:
- `ArchiveRole` enum: quality_leader, cost_leader, latency_leader, safety_leader, cluster_specialist
- `EliteParetoArchive` — Named roles, branching from any entry
- Role assignment based on per-objective dominance

`optimizer/mutations.py`:
- Narrow auto-change surface: clearly separate auto-deploy (low risk) vs PR/manual (high risk)
- De-emphasize topology as optimization surface

`evals/statistics.py`:
- Default: paired comparison, clustered by conversation/user/env, effect size + 95% CI, explicit power targets
- Remove n>=30 rule, replace with power-based sample adequacy
- O'Brien-Fleming for online canaries ONLY
- Safety severity tiers + one-sided upper bounds
- Promotion rule: zero P0 red-team → upper bound P1 → no slice regressions → winner on holdout → canary survives

**Files to create:**

`optimizer/training_escalation.py`:
- `FailureFamilyStability` — Track consistency over N cycles
- `TrainingRecommendation` — Dataset, method (SFT/DPO/RFT), expected improvement
- `TrainingEscalationMonitor` — Recommend fine-tuning when prompt patching plateaus

`deployer/release_manager.py`:
- `PromotionPipeline` — hard gates → hidden holdout → slice checks → canary → rollback-ready
- `PromotionStage` enum: gate_check, holdout_eval, slice_check, canary, released, rolled_back
- `PromotionRecord` — Full audit trail of promotion decisions
- Policy packs versioned and evaluated as deployed config

### Stream E — Frontend + API Updates (Sonnet)

**Files to modify:**

`api/models.py`:
- Add LayeredDimensionScores, JudgeVerdict, ArchiveRole types
- Add judge calibration response models
- Add training escalation recommendation models

`api/routes/eval.py`:
- Expose 4-layer metric breakdown
- Add judge calibration endpoint

`api/routes/experiments.py`:
- Archive view with named Pareto leaders
- Structured critiques and evidence spans

`web/src/lib/types.ts`:
- Add LayeredDimensionScores, JudgeVerdict, ArchiveEntry types
- Update CompositeScore with layer classification

`web/src/components/DimensionBreakdown.tsx`:
- 4-layer collapsible view (Gates → Outcomes → SLOs → Diagnostics)

`web/src/pages/EvalDetail.tsx`:
- Show layered metrics with gate/outcome/SLO/diagnostic grouping

`web/src/pages/Experiments.tsx`:
- Archive view with named leaders
- Evidence spans in experiment cards

`web/src/components/ExperimentCard.tsx`:
- Add evidence_spans and failure_reasons display

New components:
- `web/src/components/JudgeCalibrationView.tsx` — Judge agreement, drift, bias metrics
- `web/src/components/ArchiveView.tsx` — Named Pareto leaders

## Backward Compatibility Strategy

1. **All existing types are preserved** — New types extend, not replace
2. **`search_strategy: simple`** works identically — simple mode uses existing CompositeScorer
3. **SideEffectClass** stays alongside ReplayMode — migration helper maps between them
4. **DimensionScores** stays — LayeredDimensionScores wraps it with layer classification
5. **TestCase** stays — New EvalCase extends it with end-state fields
6. **ToolClassificationRegistry** stays — ToolContractRegistry extends it
7. **ParetoArchive/ConstrainedParetoArchive** stay — EliteParetoArchive extends with roles

## Test Strategy

1. All 357 existing tests pass unchanged
2. New tests per stream:
   - Stream A: ~30 tests (domain objects, handoff comparator, graph IR)
   - Stream B: ~40 tests (each judge type, grader stack, layered scorer, eval compiler)
   - Stream C: ~20 tests (replay modes, snapshots, freshness, sandbox interface)
   - Stream D: ~25 tests (archive roles, training escalation, release pipeline, stats refinements)
   - Stream E: ~10 tests (API model validation)
3. Target: 480+ total tests

## Execution Order

1. Stream A first (core types needed by all other streams)
2. Streams B, C, D in parallel (independent work)
3. Stream E last (depends on B, C, D API surfaces)
4. Integration pass
5. Full test suite + frontend build
6. Commit

## Constraints Respected

- No new infrastructure deps (no Postgres, Redis, blob storage)
- SQLite stays with repository/interface patterns
- Gemini stays default; judge uses different model family config
- Single-process; code structured into control/execution/data planes
- Frontend stays Apple/Linear aesthetic
- `autoagent run` with `search_strategy: simple` works identically
- Failure-bucket proposer stays as simple mode
