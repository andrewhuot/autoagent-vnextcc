# Backend Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make AutoAgent VNextCC production-grade for multi-provider optimization loops with durable state and reliable evaluation.

**Architecture:** Introduce provider and orchestration abstractions around optimizer/eval paths while preserving existing CLI/API contracts. Persist run state/events to durable storage and isolate long-running loop controls (checkpointing, shutdown, watchdog) from business logic.

**Tech Stack:** Python 3.11+, FastAPI/Starlette, Pydantic, SQLite, pytest.

---

### Task 1: Baseline Audit and Gap Mapping

**Files:**
- Create: `BACKEND_REVIEW.md`
- Modify: `findings.md`, `progress.md`, `task_plan.md`
- Read: all project `.py` files outside `.venv`

**Steps:**
1. Enumerate Python modules and classify purpose.
2. Validate whether each phase requirement is currently satisfied.
3. Record concrete deficiencies and risks in `BACKEND_REVIEW.md`.
4. Track decisions and evidence in planning files.

### Task 2: Multi-Provider LLM Layer

**Files:**
- Create/Modify under `optimizer/` and/or `runner.py` support modules
- Update config schema/loader under `agent/config/`
- Add tests under `tests/`

**Steps:**
1. Write failing tests for provider selection + rotation.
2. Implement provider interface and per-provider clients.
3. Add retry/backoff/rate-limit + cost accounting.
4. Validate with targeted tests, then full suite.

### Task 3: Reliability + Loop Lifecycle Hardening

**Files:**
- Modify `runner.py`, API loop routes/tasks, persistence modules
- Add health/checkpoint/watchdog utilities
- Add tests under `tests/`

**Steps:**
1. Write failing tests for graceful shutdown and checkpoint resume.
2. Implement signal-aware loop and state persistence.
3. Add dead-letter handling, watchdog/stall detection, resource telemetry.
4. Validate with targeted tests.

### Task 4: Real Eval Pipeline

**Files:**
- Modify `evals/`, `observer/`, `optimizer/gates.py`, CLI/API interfaces
- Add dataset/eval provenance models
- Add tests under `tests/`

**Steps:**
1. Write failing tests for dataset loading, custom evals, significance gate.
2. Implement built-in evaluators and train/test split support.
3. Add provenance storage and significance checks.
4. Validate with tests.

### Task 5: Docs + Verification + Completion

**Files:**
- Update `docs/architecture.md` and related docs
- Finalize `BACKEND_REVIEW.md`, `progress.md`, `task_plan.md`

**Steps:**
1. Run required verification commands.
2. Record outcomes with evidence.
3. Mark all phases complete in planning files.
4. Execute completion event command.
