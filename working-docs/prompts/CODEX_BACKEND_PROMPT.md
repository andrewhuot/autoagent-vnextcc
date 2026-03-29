# Codex Task: Backend Architecture Review + Production Hardening

## Mission
Review and harden AutoAgent VNextCC's backend so it can genuinely optimize AI agents in production. This system should run for days continuously, support multiple LLM providers, and produce real measurable improvements.

## Context
AutoAgent VNextCC is a self-optimizing platform for AI agents. It evaluates agent performance, proposes improvements via LLM-as-optimizer, runs accept/reject gates, and deploys winners. The core loop: Eval → Observe → Optimize → Deploy → Repeat.

Key files:
- `runner.py` — main engine (eval, optimize, deploy, observer, conversation logger)
- `api/` — REST API (FastAPI/Starlette)
- `tests/` — pytest suite
- `autoagent.yaml` — config

## Phase 1: Architecture Audit
Review every Python file and answer:
1. Can this actually run a real eval against a real agent? If not, what's missing?
2. Can the optimization loop run continuously for days without memory leaks, state corruption, or crashes?
3. Is error handling robust enough for production (network failures, API rate limits, timeouts)?
4. Are results persisted durably (not just in-memory)?
5. Is the eval scoring system sound? Does it produce meaningful composite scores?

Write findings to `BACKEND_REVIEW.md`.

## Phase 2: Multi-Model Support
Ensure the system can use ANY LLM provider for the optimizer (the LLM that proposes improvements):
- OpenAI (GPT-4o, GPT-5, o3)
- Anthropic (Claude Sonnet, Claude Opus)
- Google (Gemini 2.5 Pro, Gemini 2.5 Flash)
- Local models via OpenAI-compatible API

Design:
- Config-driven model selection in `autoagent.yaml`
- Support model rotation/ensemble: run the same eval through multiple models and compare proposals
- Abstract LLM calls behind a provider interface
- Include rate limiting, retry with backoff, and cost tracking per provider
- Support "mixture of models" — e.g., Gemini for fast screening, Claude for deep analysis, GPT for creative proposals

## Phase 3: Long-Running Reliability
Make the optimization loop production-grade for multi-day runs:
- Graceful shutdown (SIGTERM/SIGINT handlers, finish current eval before exiting)
- Checkpoint/resume: save loop state so it can restart from where it left off
- Configurable scheduling: run evals every N minutes, or on cron, or continuously
- Resource monitoring: log memory/CPU usage, warn if leaking
- Structured logging (JSON) with rotation
- Dead letter queue for failed evals (don't lose data)
- Health check endpoint in API
- Watchdog: detect if the loop stalls and alert/restart

## Phase 4: Real Eval Pipeline
Ensure the eval system can actually measure agent quality:
- Support custom eval functions (Python callables)
- Built-in eval types: response quality (LLM-as-judge), latency, cost, safety, tool-use accuracy
- Eval datasets: load from JSONL/CSV, support train/test splits
- Statistical significance: don't accept improvements that aren't statistically significant
- Eval history with full provenance (which model judged, what prompt, what score)

## Phase 5: Tests + Documentation
- Add integration tests for the full eval→optimize→deploy loop (can use mocks)
- Add tests for multi-model provider switching
- Add tests for checkpoint/resume
- Update all docs in `docs/` to reflect changes
- Update `docs/architecture.md` with the real system design

## Phase 6: Final Verification
1. All tests pass: `python3 -m pytest tests/ -v`
2. Server starts cleanly: `python3 -m uvicorn api.main:app`
3. CLI commands work: `python3 runner.py eval`, `python3 runner.py optimize`, `python3 runner.py loop`
4. Write `BACKEND_REVIEW.md` with full findings and changes made

When completely finished, run: openclaw system event --text "Done: VNextCC backend hardening - multi-model, long-running, production-grade" --mode now
