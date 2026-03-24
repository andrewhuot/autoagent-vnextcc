# Findings

## Notes
- Findings will be appended during module audit and implementation.

## Architecture Risks
- Pending

## Design Decisions
- Pending

## Phase 1 Audit Findings (2026-03-23)
- Eval path is mostly fixture-driven (`mock_agent_response`) and does not yet represent real LLM-backed quality measurement.
- Proposer lacks real provider integrations; `_llm_propose` is placeholder fallback.
- No durable loop checkpoint/resume support; restart loses loop progress.
- No explicit SIGTERM/SIGINT graceful-drain behavior for long-running loops.
- API task/loop state is process-local and in-memory (non-durable across restart).
- Existing scoring is coherent but lacks statistical significance gating and provenance persistence.
- Multi-model routing now supports OpenAI/Anthropic/Google/OpenAI-compatible providers with retries/rate limits/cost tracking.
- Loop reliability now includes checkpoint/resume, DLQ persistence, graceful shutdown, watchdog telemetry, and schedule modes.
- Eval pipeline now supports JSONL/CSV datasets, split handling, custom evaluators, provenance history, and significance gating.
