# AutoAgent VNextCC — Major Refactor Based on AI Researcher Review

## Context

An AI researcher reviewed our evaluation and optimization architecture. Their feedback is in `RESEARCHER_ADVICE.md`. Read it FIRST — every word. This is the most important input you'll receive.

Their headline: **"Build AutoAgent as an eval-native experimentation system around versioned agent graphs, skills, tool contracts, and stateful sandbox replay. The moat is not 'we mutate prompts.' The moat is 'we can faithfully replay, grade, and safely improve real enterprise agent workflows.'"**

## Your Mission

Implement a deep architectural refactor that transforms AutoAgent from a prompt optimizer into CI/CD for agents. This is a foundational rewrite of core abstractions, not a feature addition.

## Phase 1: Planning (Opus-level thinking, write REFACTOR_PLAN.md)

Read the ENTIRE codebase + RESEARCHER_ADVICE.md. Then plan:

### 1.1 New First-Class Domain Objects

Create a new `core/` package with the canonical internal representations:
- `AgentGraphVersion` — framework-neutral IR for agent systems (typed nodes: router, specialist, guardrail, skill, memory, tool_contract, handoff_schema, judge; typed edges)
- `SkillVersion` — versioned bundles of instructions, scripts, assets (OpenAI/Anthropic skills pattern)
- `ToolContractVersion` — tool name, schema, side-effect class, replayability mode, validator, sandbox policy
- `PolicyPackVersion` — safety rules, guardrail thresholds, authorization policies, as deployable code
- `EnvironmentSnapshot` — captured state of external systems for replay
- `GraderBundle` — ordered grader stack per eval case (deterministic → rule-based → LLM judge → human)
- `EvalCase` — (task, environment_snapshot, grader_bundle, expected_end_state, diagnostic_trace_features)
- `CandidateVariant` — a proposed change as a versioned diff against an AgentGraphVersion
- `ArchiveEntry` — Pareto archive entry with role (quality_leader, cost_leader, latency_leader, safety_leader, cluster_specialist)

### 1.2 Four-Layer Metric Hierarchy (replace flat 9-dimension)

Refactor `evals/scorer.py`:
- **Layer 1 — Hard Gates**: safety/policy violations, authorization/privacy breaches, state integrity / business invariant failures, P0 regressions
- **Layer 2 — North-Star Outcomes**: end-state task success, grounded answer quality (factual accuracy, citation accuracy, completeness, source quality), calibrated user satisfaction / human effort saved
- **Layer 3 — Operating SLOs**: latency (p50/p95/p99), token cost, escalation rate
- **Layer 4 — Diagnostics**: tool correctness, routing accuracy, handoff fidelity, recovery rate, clarification quality, judge disagreement rate

Add missing metrics: `state_integrity` (business invariant correctness), `groundedness` (evidence fidelity), `escalation_rate`, `recovery_rate`, `clarification_quality`, `judge_disagreement_rate`.

The optimizer searches over Layer 2 outcomes within Layer 1 gates, subject to Layer 3 SLOs. Layer 4 is for diagnosis only, never optimized directly.

Dashboard composite stays simple for humans.

### 1.3 End-State Evaluation (replace trajectory matching as default)

Refactor `evals/runner.py` and `evals/data_engine.py`:
- Default eval mode = end-state comparison (did the agent leave the system in the correct final state?)
- Trajectory matching = optional, sparse (for debugging, not for scoring)
- `EvalCase` stores `expected_end_state` as structured data, not just text comparison
- Add `EnvironmentSnapshot` diffing — compare actual vs expected end state

### 1.4 Richer Replayability Matrix (replace 4-class side-effects)

Refactor `evals/replay.py` and `evals/side_effects.py`:
- 5 replay modes per tool: `deterministic_stub`, `recorded_stub_with_freshness`, `live_sandbox_clone`, `simulator`, `forbidden`
- Each tool gets: replay_mode, validator, sandbox_policy, freshness_window
- `EnvironmentSnapshot` capture and restore for sandbox replay

### 1.5 Structured Handoff Artifacts

New `core/handoff.py`:
- `HandoffArtifact` with fields: goal, constraints, known_facts, unresolved_questions, allowed_tools, expected_deliverable, evidence_refs
- Replace scalar handoff_fidelity with structured artifact comparison
- Measure handoff quality by field-level completeness and accuracy

### 1.6 Judge Subsystem (replace utility function)

New `judges/` package:
- `judges/deterministic.py` — executable state-check graders, regex validators, business invariant checks
- `judges/rule_based.py` — configurable rule validators (format, length, required fields)
- `judges/llm_judge.py` — frozen primary LLM judge with evidence spans (not just scalar)
- `judges/audit_judge.py` — cross-family audit judge for promotions (different model family than proposer)
- `judges/calibration.py` — judge calibration suite: agreement with humans, drift across versions, position bias, verbosity bias, disagreement rate
- `judges/grader_stack.py` — `GraderBundle` that chains: deterministic → rule-based → LLM → human review flag
- Judge outputs include `evidence_spans`, `failure_reasons`, `confidence`, not just a score

### 1.7 Eval Compiler (replace simple trace-to-eval converter)

Refactor `evals/data_engine.py`:
- PII scrubbing before storage
- Near-duplicate detection and deduplication
- Reproducibility testing (can we replay this and get similar results?)
- Business impact scoring
- Root-cause tagging (auto-categorize failure type)
- Solvability check (is there a known good solution?)
- Negative control generation (if testing "agent searches when needed," also test "agent doesn't search when unnecessary")
- Five eval suite types: contract/regression, capability, adversarial, discovery, judge_calibration

### 1.8 Search Engine Refinements

Refactor `optimizer/search.py`:
- Optimization unit = one failure family × one mutation surface × one bounded eval bundle × one short experiment loop
- Breadth/depth split: cheap model for many small diffs (Gemini Flash), stronger model for shortlist ranking (Gemini Pro)
- Mutation generator ingests structured critiques from judge (evidence spans + failure reasons), not just pass/fail
- Contextual bandit value = expected_lift × business_impact × uncertainty ÷ eval_cost
- Elite Pareto archive with named roles: quality_leader, cost_leader, latency_leader, safety_leader, cluster_specialists
- New candidates can branch from any archive entry, not just incumbent

### 1.9 Narrow Auto-Change Surface

Update `optimizer/mutations.py`:
- Auto-deploy (low risk): instruction blocks, few-shot examples, tool descriptions, routing thresholds, memory policies, guardrail thresholds, lightweight skill edits with validators
- PR/manual-approval (high risk): model swaps, topology changes, code patches, new tools
- De-emphasize topology as optimization surface (move to experimental, infrequent)

### 1.10 Statistical Layer Cleanup

Refactor `evals/statistics.py`:
- Default offline gate: paired comparison, clustered by conversation/user/env, effect size + 95% CI, explicit power targets
- Remove arbitrary n>=30 rule, replace with power-based sample adequacy
- O'Brien-Fleming for online canaries ONLY (not every batch)
- Safety: severity tiers + one-sided upper bounds on unsafe-rate (not just zero-tolerance binary)
- Promotion rule: zero P0 on red-team → upper bound P1 unsafe below threshold → no slice regressions → winner on hidden holdout → canary survives sequential monitoring
- Add negative controls to eval suites

### 1.11 Release Manager

New `deployer/release_manager.py`:
- Promotion pipeline: hard gates → hidden holdout → slice checks → canary → rollback-ready rollout
- Policy packs versioned and evaluated as deployed config
- Governance-as-code: policies are tested, not just enforced

### 1.12 Training Escalation Path

New `optimizer/training_escalation.py`:
- When a failure family is stable and high-volume, recommend SFT/DPO/RFT instead of endless prompt patching
- Track failure family stability (consistent for N cycles) and volume
- Output: recommendation with dataset, suggested method, expected improvement

### 1.13 Three-Plane Architecture Prep

Refactor for future distribution (don't add infra deps, but structure the code):
- `control/` — experiments, archive, datasets, approvals, policies
- `execution/` — replay workers, eval runners (currently single-process, but isolated for future parallelism)
- `data/` — trace storage, artifact storage, metadata (SQLite for now, Postgres-ready interfaces)

### 1.14 Frontend Updates

- Update dashboard to show 4-layer metric hierarchy (gates → outcomes → SLOs → diagnostics)
- Add judge calibration view
- Update experiment cards to show structured critiques and evidence spans
- Add archive view with named Pareto leaders
- Keep default view SIMPLE — detail layers are expandable/collapsible

## Phase 2: Execution

Use sub-agents for parallel work streams:

- **Stream A (Opus)**: Core domain objects (`core/` package) + AgentGraph IR + handoff artifacts
- **Stream B (Opus)**: Judge subsystem (`judges/` package) + eval compiler + 4-layer scorer
- **Stream C (Sonnet)**: Replay matrix + environment snapshots + sandbox abstractions
- **Stream D (Sonnet)**: Search engine refinements + archive roles + training escalation + release manager
- **Stream E (Sonnet)**: Frontend updates + API changes + config schema updates

## Phase 3: Integration & Verification

1. Merge all streams
2. Run full test suite — all 357+ existing tests must pass, plus new ones
3. Build frontend — TypeScript strict, no errors
4. Update ARCHITECTURE_OVERVIEW.md comprehensively
5. Update CHANGELOG.md
6. Commit: `feat: researcher-advised refactor — CI/CD for agents [summary]`

## Constraints

- ALL 357 existing tests must still pass
- No new infrastructure dependencies (no Postgres, no Redis, no blob storage — those are future)
- SQLite stays for now, but use repository/interface patterns that are Postgres-ready
- Gemini stays default, but judge must use a DIFFERENT model family config than proposer
- Single-process stays, but code should be structured into control/execution/data planes
- Frontend stays Apple/Linear aesthetic
- `autoagent run` with `search_strategy: simple` must work identically to before
- Keep the failure-bucket proposer as simple mode — it's the right v0

## When Done

Run: `openclaw system event --text "Done: Researcher-advised refactor — [file count] files, [test count] tests, [summary of architectural changes]" --mode now`
