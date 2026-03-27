# Harness Engineering Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Apply modern eval-harness engineering best practices to AutoAgent by adding reliability, reproducibility, cost controls, and observability improvements backed by tests and documentation.

**Architecture:** We will first synthesize a best-practice rubric from primary external sources, then map AutoAgent capabilities and close priority gaps in narrow, test-driven increments. Improvements will focus on deterministic run identity, cache correctness, statistical confidence visibility, and budget-aware execution controls that integrate with existing `evals/`, `judges/`, and `optimizer/` flows.

**Tech Stack:** Python 3.11+, pytest, SQLite-backed repositories, existing AutoAgent eval/judge modules.

---

### Task 1: Research Baseline and Best-Practice Checklist

**Files:**
- Modify: `findings.md`
- Modify: `progress.md`

**Step 1: Collect primary sources**
- Fetch OpenAI Harness Engineering and related eval-harness sources (Anthropic, DeepMind, EleutherAI, METR, Braintrust, LangSmith, W&B).

**Step 2: Distill checklist**
- Build a checklist covering: dataset mgmt, scorer design, statistical rigor, regression controls, orchestration/reproducibility, metric hierarchy, human eval, cost controls, eval debugging, continuous eval.

**Step 3: Persist findings**
- Append source-backed findings to `findings.md`.

### Task 2: AutoAgent Capability Audit and Gap Prioritization

**Files:**
- Modify: `findings.md`
- Modify: `task_plan.md`
- Modify: `progress.md`
- Read: `evals/**`, `graders/**`, `judges/**`, `observer/**`, `optimizer/**`, `runner.py`, relevant tests

**Step 1: Inventory current implementation**
- Identify existing mechanisms for caching, run identity, judging, calibration, drift, and cost accounting.

**Step 2: Map to checklist**
- Produce best-practice vs current-state matrix with concrete evidence.

**Step 3: Prioritize implementation targets**
- Choose 2-4 gaps with highest impact and lowest disruption.

### Task 3: Add Failing Tests for Selected Improvements (RED)

**Files (anticipated):**
- Create/Modify: `tests/test_eval_*.py`
- Create/Modify: `tests/test_optimizer_*.py`

**Step 1: Define behavior-oriented tests**
- Test names describe expected behavior (not implementation details).

**Step 2: Run targeted tests to verify failures**
Run examples:
- `python3 -m pytest tests/test_eval_*.py -q`
- `python3 -m pytest tests/test_optimizer_*.py -q`

**Expected:** tests fail for missing behavior.

### Task 4: Implement Minimal Improvements (GREEN)

**Files (to be finalized after audit):**
- Modify: `evals/*`
- Modify: `judges/*`
- Modify: `optimizer/*`
- Modify: `data/*` (if persistence needed)

**Step 1: Implement deterministic run fingerprinting and safe caching controls**
- Ensure identical eval+config pairs can be reused with transparent provenance.

**Step 2: Implement statistical confidence reporting**
- Add confidence interval output for aggregate pass-rate style metrics.

**Step 3: Implement budget-aware cost guardrails**
- Add optional budget enforcement and surfaced spend estimates.

**Step 4: Re-run targeted tests to green**
- `python3 -m pytest <new/updated test paths> -q`

### Task 5: Refactor and Harden

**Files:**
- Modify: files touched in Task 4
- Modify: tests touched in Task 3

**Step 1: Improve naming and API clarity**
- Keep functions single-purpose and explicit.

**Step 2: Ensure error messages are actionable**
- User-facing failures include next-step guidance.

**Step 3: Run module-level suites**
- `python3 -m pytest tests/test_eval_*.py tests/test_optimizer_*.py tests/test_judges_*.py -q`

### Task 6: Documentation and Final Verification

**Files:**
- Create: `docs/HARNESS_ENGINEERING.md`
- Modify: `findings.md`
- Modify: `progress.md`

**Step 1: Document architecture and best-practice mapping**
- Include gap analysis table and implementation rationale.

**Step 2: Include practical guidance**
- How to write evals, manage datasets, choose graders/judges, and use human review.

**Step 3: Run full suite command**
- `cd tests && python -m pytest -x -q`

**Step 4: Completion actions**
- `openclaw system event --text "Done: Harness engineering best practices applied" --mode now`
- Attempt commit/push if repository state permits and user-requested prompt steps remain valid.
