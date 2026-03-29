# Karpathy Alignment Review (AutoAgent VNextCC)

Date: 2026-03-27

## 1) Research Snapshot: Karpathy + Recent Autonomous Self-Improvement Work

### Primary Karpathy Signals (2025-2026)

1. **AutoResearch (March 2026)**
- Karpathy’s `autoresearch` project is explicitly a keep/discard autonomous loop with minimal moving parts.
- Core pattern: fixed-budget experiment, single objective metric, small code diffs, empirical accept/reject.
- Source:
  - https://github.com/karpathy/autoresearch
  - https://raw.githubusercontent.com/karpathy/autoresearch/master/program.md

2. **Agent reliability and timelines (Oct 17, 2025)**
- Karpathy frames this as a *decade of agents*, not a one-year event.
- He stresses current gaps: robustness, continual learning, multimodality, computer use maturity.
- He also highlights why code is a strong substrate for agents: we already have diff/review infrastructure.
- Source:
  - https://www.dwarkesh.com/p/andrej-karpathy

3. **Self-play + multi-agent culture as missing pieces**
- In the same interview, Karpathy points to self-play-style curriculum generation and richer multi-agent collaboration as underdeveloped, high-upside areas.
- Source:
  - https://www.dwarkesh.com/p/andrej-karpathy

### Adjacent 2025-2026 Research (for calibration)

1. **Darwin Gödel Machine (updated Mar 12, 2026)**
- Demonstrates open-ended self-improving coding agents with archive-based exploration + empirical validation.
- Useful alignment point for "self-improvement with guardrails".
- Source:
  - https://arxiv.org/abs/2505.22954

2. **METR long-task horizon trend (Mar 19, 2025)**
- Shows agent task horizon growth and argues for measuring autonomy by task length completion reliability.
- Useful for setting realistic autonomy expectations and gate strictness.
- Source:
  - https://metr.org/blog/2025-03-19-measuring-ai-ability-to-complete-long-tasks/

---

## 2) Audit: AutoAgent vs Karpathy Principles

### Principle 1: Simplicity Over Complexity

**Status: Partial alignment**

- Strength: the core conceptual loop is present (`trace -> diagnose -> search/propose -> eval -> gate -> deploy -> learn`).
- Drift: implementation includes multiple strategy branches and rich enterprise layers. Powerful, but harder to reason about in one pass versus Karpathy’s minimal single-loop framing.
- Net: architecture is capable, but the “5-minute understandability” objective is only partially met for new contributors.

### Principle 2: Self-Improvement Loops

**Status: Strong alignment, with one key gap addressed in this patch**

- Strength: CLI/API loop runners, checkpointing, dead-letter queue, watchdog, and optimization memory already exist.
- Gap before patch: self-improvement mostly updated **scores** and **skill effectiveness**, but not consistently **new reusable skills** from accepted non-skill optimizations.
- Fix in this patch: added draft-skill autolearning from accepted attempts.

### Principle 3: Eval-Driven Development

**Status: Strong alignment**

- Strength: eval runner, composite scoring, statistical significance gate, anti-Goodhart holdouts/variance checks are present.
- Gap before patch: composite was available but not transparent enough in API responses/messages for quick operator reasoning.
- Fix in this patch: added explicit weighted contribution breakdown in eval responses and richer gate delta narratives.

### Principle 4: Small Diffs

**Status: Good alignment**

- Strength: optimizer tracks config diffs and rejects no-op proposals.
- Gap: no hard line-count or semantic complexity budget on proposal magnitude.
- Current state is still directionally aligned with small-diff practice.

### Principle 5: Composite Scoring (One Number, Transparent)

**Status: Aligned after patch**

- Strength: one composite score has existed.
- Gap before patch: contribution accounting was implicit.
- Fix in this patch: explicit `composite_breakdown` with weights, component metrics, and contributions.

### Principle 6: Accept/Reject Gates

**Status: Strong alignment**

- Strength: explicit hard/soft gates and clear status transitions already implemented.
- Improvement in this patch: gate reason strings now include per-dimension delta context.

### Principle 7: Self-Play / Simulation

**Status: Partial alignment, improved in this patch**

- Strength: simulation sandbox already existed.
- Gap before patch: adversarial simulation was not integrated into candidate acceptance path.
- Fix in this patch: added optional adversarial A/B simulation check as part of final candidate validation.

---

## 3) Drift Identified and Improvements Implemented

### A) Long-running loop resilience

**Gap:** checkpoint loading failed hard if JSON was corrupted.

**Implemented:**
- `LoopCheckpointStore` now maintains a backup checkpoint copy and falls back to backup if primary is corrupt.
- `clear()` now removes primary + backup.
- Added tests for corruption recovery and backup cleanup.

Files:
- `optimizer/reliability.py`
- `tests/test_reliability.py`

### B) Composite score transparency

**Gap:** one-number scoring existed, but attribution was opaque at API/operator surfaces.

**Implemented:**
- Added weighted contribution breakdown on `CompositeScore`.
- Exposed breakdown through eval API responses.
- Improved gate messages to include per-dimension deltas.

Files:
- `evals/scorer.py`
- `api/routes/eval.py`
- `api/models.py`
- `optimizer/gates.py`
- `tests/test_scoring_v2.py`

### C) Adversarial simulation during optimization

**Gap:** simulation existed but was disconnected from promotion decisions.

**Implemented:**
- Added `AdversarialSimulator` with configurable conversation count and max allowed drop.
- Integrated into optimizer candidate finalization as an optional veto (`rejected_adversarial`).
- Added deterministic simulation behavior to avoid flaky gates.
- Added runtime knobs and wiring in CLI/API bootstrap paths.

Files:
- `optimizer/adversarial.py`
- `optimizer/loop.py`
- `simulator/sandbox.py`
- `agent/config/runtime.py`
- `runner.py`
- `api/server.py`
- `autoagent.yaml`
- `tests/test_adversarial_simulator.py`
- `tests/test_optimizer.py`

### D) Skill learning from successful optimizations

**Gap:** accepted attempts improved memory but did not consistently distill into reusable draft build-skills.

**Implemented:**
- Added `SkillAutoLearner` that synthesizes **draft** build-time skills from accepted attempts (thresholded, deduped, review-first).
- Hooked into optimizer success path with event logging and status annotation.

Files:
- `optimizer/skill_autolearner.py`
- `optimizer/loop.py`
- `runner.py`
- `api/server.py`
- `tests/test_skill_autolearner.py`
- `tests/test_optimizer.py`

### E) Clearer experiment narratives

**Gap:** experiment summaries were numeric but terse.

**Implemented:**
- Search experiment cards now include narrative-style “what we learned” summaries with strongest gain/regression dimensions.

File:
- `optimizer/search.py`

---

## 4) Where AutoAgent Exceeds Karpathy’s Baseline Vision

1. **Production reliability envelope**
- Dead-letter queue, watchdog, checkpointing, structured logs, and human control layers exceed the minimal AutoResearch baseline.

2. **Statistical rigor and anti-Goodhart controls**
- Significance checks, holdout handling, judge variance checks, and drift handling go beyond simple keep/discard.

3. **Governance and deployment controls**
- Explicit gating and deploy/canary surfaces are stronger than a pure overnight autonomous loop.

---

## 5) Verification Run

Requested command:
- `cd tests && python -m pytest -x -q`
- Result in this environment: `python` not found.

Equivalent attempted:
- `cd tests && python3 -m pytest -x -q`
- Result in this environment: fails early because `fastapi` is not installed in the local interpreter environment.

Targeted verification of touched areas:
- `python3 -m pytest -q tests/test_reliability.py tests/test_scoring_v2.py tests/test_adversarial_simulator.py tests/test_skill_autolearner.py tests/test_optimizer.py`
- `python3 -m pytest -q tests/test_search.py tests/test_experiments.py tests/test_simulation_sandbox.py`
- Result: passing.

---

## 6) Remaining High-Value Follow-ups

1. Add a strict small-diff budget gate (e.g., max changed surfaces/fields per cycle) for even tighter Karpathy-style mutation discipline.
2. Add explicit holdout/adversarial dashboards in web UI so accept/reject reasons are first-class and auditable.
3. Promote approved draft skills through a human-reviewed “draft -> active” workflow with quality bars.
4. Add a self-play curriculum generator that synthesizes harder eval prompts from recent failure clusters.
