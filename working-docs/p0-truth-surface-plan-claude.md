# P0 Truth-Surface Alignment Plan

**Date:** 2026-04-12
**Agent:** Claude Opus 4.6
**Branch:** feat/p0-truth-surface-alignment-claude
**Issue:** Close surfaced-feature truth gap — product must not imply workflows that aren't wired end-to-end.

---

## Problem Statement

The audit identified 7 significant gaps where documented/surfaced behavior doesn't match implementation. These fall into two categories:

1. **Last-mile wiring gaps** — data structures exist but aren't connected
2. **Doc/API lies** — features described as complete that are stubs or partial

## Scope: Highest-Leverage Coherent Slice

This session targets the **truth gap** specifically: making what users see match what actually happens. Preference order:
1. Wire the real behavior if feasible and safe
2. Make docs/UI/API/copy honest and explicit
3. Do not leave user-facing false confidence in place

---

## Implementation Plan

### Phase 1: Real Wiring Fixes (high leverage, safe)

#### 1.1 Wire `search_strategy` from config to Optimizer
- **File:** `api/server.py:245-260`
- **Fix:** Pass `runtime.optimizer.search_strategy` to Optimizer constructor
- **Risk:** Low — Optimizer already accepts this param, just not receiving it from config
- **Validation:** Optimizer starts with strategy matching config value

#### 1.2 Wire `drift_threshold` from config to DriftMonitor
- **File:** `api/server.py:391`
- **Fix:** Pass threshold and create a `DriftMonitor(drift_threshold=runtime.optimizer.drift_threshold)` constructor signature
- **Files changed:** `api/server.py`, `judges/drift_monitor.py`
- **Risk:** Low — adding a parameter, existing hardcoded default preserved as fallback

#### 1.3 Wire `score_handoff()` into `analyze_trace()`
- **File:** `context/analyzer.py`
- **Fix:** Call `score_handoff()` on handoff events, add `handoff_scores` to `ContextAnalysis`
- **Risk:** Low — additive, no existing behavior changes

### Phase 2: Honest Documentation (critical for trust)

#### 2.1 Pro-mode prompt optimization docs
- **Current claim:** "Set `search_strategy: pro` to access MIPROv2..."
- **Reality:** `"pro"` maps to `"research"` via legacy mapping (never reaches _optimize_pro). `_optimize_pro()` uses MockProvider.
- **Fix:** Rewrite docs to mark pro-mode as experimental/not-yet-production. Explain what research mode actually does (FULL strategy: hybrid search + curriculum + Pareto). Remove instructions to set `search_strategy: pro` as if it's production-ready.

#### 2.2 AutoFix docs — stages 5-6
- **Current claim:** "eval → canary deploy" as stages 5-6 of the pipeline
- **Reality:** `apply()` is a pure config mutation. No eval, no gates, no canary.
- **Fix:** Rewrite to describe actual 4-stage pipeline. Note that eval and canary are separate manual steps (which do exist in the platform, just not auto-triggered by AutoFix). Remove empty `canary_verdict`/`deploy_message` fields from API response (or mark as `null` with a note they're reserved for future use).

#### 2.3 Drift monitor docs — pause-on-drift
- **Current claim:** "Optionally pauses auto-promotion" and "Emits SSE event"
- **Reality:** Neither implemented. Drift checks run but receive empty verdicts.
- **Fix:** Remove claims about auto-pause and SSE emission. Document what drift monitoring actually does (detection and alerting). Note the drift route now receives real threshold from config (Phase 1 fix).

#### 2.4 Context Engineering Studio docs — aggregate report
- **Current claim:** CLI `context report` outputs computed metrics
- **Reality:** Stub returning all zeros / static string
- **Fix:** Update docs to say aggregate report requires per-trace data to be collected first. Rewrite example workflow to lead with per-trace analysis (which works). Mark aggregate endpoint as "returns available data or empty defaults when no traces have been analyzed."

### Phase 3: API Response Honesty

#### 3.1 AutoFix apply endpoint
- Remove `canary_verdict: ""` and `deploy_message: ""` from response
- Add explicit `"note": "Eval and canary deployment are separate steps — use /api/eval/run and /api/deploy/canary after applying."`

#### 3.2 Context report endpoint
- Add honest response when no data: `"note": "No traces analyzed yet. Run per-trace analysis first via /api/context/analysis/{trace_id}."`

#### 3.3 Drift endpoint
- Wire to use configured threshold instead of hardcoded
- Add `"configured_threshold"` field to response so operators can verify their config took effect

### Phase 4: Tests

- Test that Optimizer receives `search_strategy` from config
- Test that DriftMonitor receives configured threshold
- Test that `analyze_trace()` produces handoff scores for handoff events
- Test that autofix apply response doesn't contain misleading empty fields

---

## Files to Modify

| File | Change |
|------|--------|
| `api/server.py` | Pass search_strategy and drift_threshold from config |
| `judges/drift_monitor.py` | Accept drift_threshold constructor param |
| `api/routes/judges.py` | Wire real threshold to drift endpoint |
| `context/analyzer.py` | Wire score_handoff into analyze_trace, add field to ContextAnalysis |
| `api/routes/autofix.py` | Remove misleading empty fields, add guidance note |
| `api/routes/context.py` | Add honest note to stub response |
| `docs/features/prompt-optimization.md` | Rewrite to be honest about experimental status |
| `docs/features/autofix.md` | Remove stages 5-6 claims, describe actual 4-stage reality |
| `docs/features/judge-ops.md` | Remove pause-on-drift and SSE claims |
| `docs/features/context-workbench.md` | Remove fake CLI output, describe actual state |
| `tests/test_truth_surface_wiring.py` | New test file for all wiring changes |

---

## What This Does NOT Fix (Remaining Risks)

- **BlameMap → optimizer feedback loop** — requires significant architectural bridging (P1)
- **`algorithm_overrides` dict ignored** — research mode sets it but optimizer doesn't read it (low impact since research mode uses FULL strategy anyway)
- **Pro-mode MockProvider** — not rewiring to real LLM (requires provider configuration; marked experimental in docs)
- **Drift endpoint receives `verdicts=[]`** — need a verdicts store to persist judge outcomes (P1)
- **Context aggregate report computation** — requires trace store integration (P1)

---

## Success Criteria

1. Every documented feature either works as described or docs explicitly state its actual status
2. No API response contains fields that silently return empty/zero with no explanation
3. Config file settings that the system reads are passed to the components that use them
4. Tests verify the wiring is connected
5. A user reading docs and trying the feature gets honest feedback about what works
