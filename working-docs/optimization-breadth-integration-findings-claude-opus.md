# Optimization Breadth Integration Findings

**Branch:** `feat/optimization-breadth-integration-claude-opus`
**Date:** 2026-04-12
**Author:** Claude Opus (integration agent)

## What Was Done

Merged two parallel optimization-breadth branches into one coherent system:

### Codex branch (authoritative backbone) — merged as-is

| Layer | Files | Role |
|-------|-------|------|
| Patch types | `shared/canonical_patch.py` | TypedPatchBundle, ComponentReference, ComponentPatchOperation — single patch authority |
| Eval attribution | `evals/component_attribution.py` | Eval-result-based credit assignment (routing mismatch, tool mismatch, safety, handoff, behavior) |
| Eval pipeline | `evals/runner.py`, `results_model.py`, `results_store.py`, `scorer.py` | Attribution flows through eval results end-to-end |
| Optimizer persistence | `optimizer/autofix.py`, `memory.py`, `change_card.py` | patch_bundle as apply authority, SQLite persistence |
| Proposer | `optimizer/proposer.py`, `loop.py` | Enhanced mock proposer with routing keyword repair |
| API | `api/routes/optimize.py`, `autofix.py`, `reviews.py`, `models.py` | Expose component_attributions and patch_bundle in API |
| Frontend | `web/src/lib/types.ts`, `api.ts` | Optional patch_bundle fields on review/autofix types |
| Tests | 3 test files, 120+ new test lines | Canonical patch, eval attribution, autofix patch bundle tests |

### Claude branch (intelligence layer) — selectively ported

| Module | Source | Adaptation |
|--------|--------|------------|
| `optimizer/component_credit.py` | Claude's trace-based credit analyzer | `ComponentType` enum aligned to Codex vocabulary ("tool_contract" not "tool"), removed dependency on `optimizer.component_patch` |
| `optimizer/component_mutation.py` | Claude's 7 per-component mutation generators | Rewritten to produce `TypedPatchBundle`/`ComponentPatchOperation`/`ComponentReference` (Codex types). Uses `find_component_reference()`/`iter_component_references()` for path resolution. |
| `tests/test_component_mutation.py` | New tests covering ported modules | 55 tests: credit analyzer, mutation generators, bundle validation, application, end-to-end, type compatibility, edge cases |

### What was deliberately left behind

| Claude file | Reason |
|------------|--------|
| `optimizer/component_patch.py` (391 lines) | **Duplicate patch system.** Defines parallel `ComponentRef`, `ComponentPatch`, `PatchBundle`, `PatchValidationError` types using dataclasses with index-based addressing. Keeping this alongside `shared/canonical_patch.py` would create split-brain patch semantics — two incompatible ways to address and mutate components. |
| `tests/test_component_optimization.py` (1024 lines) | Tests the Claude-only type system. Relevant test coverage ported into `tests/test_component_mutation.py` using Codex types. |

## Type Mapping Decisions

| Claude type | Codex equivalent | Mapping notes |
|-------------|-----------------|---------------|
| `ComponentRef(type, index, name)` | `ComponentReference(type, name, path)` | Index-based → path-based addressing via `find_component_reference()` |
| `ComponentPatch(operation, ref, old_value, new_value)` | `ComponentPatchOperation(op, component, field_path, value)` | `modify` → `replace`/`set`; `add` → `add`; old_value conflict detection dropped (validate_patch_bundle provides equivalent safety) |
| `PatchBundle(patches, description, risk_class)` | `TypedPatchBundle(operations, title, metadata)` | risk_class moved to metadata dict |
| `PatchOperation.modify` | `"replace"` / `"set"` | `replace` for value-replacing ops, `set` for setting new fields |
| `PatchOperation.add` | `"add"` | Direct mapping |
| `ComponentType.tool` | `"tool_contract"` | Aligned to Codex's `iter_component_references` vocabulary |

## What the Credit Analyzer Brings

The Claude credit analyzer (`optimizer/component_credit.py`) provides capabilities not present in the Codex eval attribution:

1. **Trace-based analysis** — works from raw execution traces, not just eval results. Catches issues that don't map to specific test cases.
2. **Multi-tier confidence** — explicit `HIGH`/`MEDIUM`/`LOW`/`HEURISTIC` levels vs Codex's float confidence. Consumers know exactly how much to trust each attribution.
3. **Severity-weighted impact** — safety violations get 1.5x multiplier, hallucinations 1.3x, routing 1.1x. Impact scores reflect severity, not just frequency.
4. **Explicit annotation support** — traces with `blamed_component`, `failed_tool`, or `failed_guardrail` fields are trusted at HIGH confidence.
5. **Keyword-based classification** — can classify failures from error text even without structured `failure_type` fields.

The two attribution systems are **complementary, not competing**: eval attribution operates on test case results; trace credit operates on execution trace data.

## What the Mutation Module Brings

The Claude mutation module (`optimizer/component_mutation.py`) provides the missing link between blame analysis and concrete patch proposals:

1. **7 specialized generators** — routing rules, tools, guardrails, instructions, handoffs, policies, environment. Each knows the canonical IR type structure.
2. **Risk classification** — safety violations auto-elevate to HIGH risk, high-confidence + high-impact to MEDIUM.
3. **Past-surface deduplication** — avoids re-proposing patches for recently-patched component types.
4. **End-to-end pipeline** — `analyze_and_propose()` goes from traces → blame → validated patches in one call.
5. **Config bridge compatibility** — `apply_and_convert()` uses Codex's `patch_bundle_to_config()` for backward-compatible config application.

## Architecture After Integration

```
Execution Traces                    Eval Test Cases
       │                                   │
       ▼                                   ▼
ComponentCreditAnalyzer          attribute_eval_failure()
(optimizer/component_credit.py)  (evals/component_attribution.py)
       │                                   │
       ▼                                   ▼
ComponentBlameEntry[]            ComponentAttribution[]
       │                                   │
       ▼                                   │
propose_component_patches()         (flows into eval results,
(optimizer/component_mutation.py)    structured results, API)
       │
       ▼
TypedPatchBundle
(shared/canonical_patch.py)
       │
       ├──▶ validate_patch_bundle() ──▶ review surface
       ├──▶ apply_patch_bundle() ──▶ new CanonicalAgent
       └──▶ patch_bundle_to_config() ──▶ backward-compatible config
                                            │
                                            ▼
                                    AutoFix / optimizer loop / deploy
```

One canonical_patch.py. One component_attribution.py for eval results. One component_credit.py for trace analysis. One component_mutation.py producing TypedPatchBundle. No duplicates.

## Test Results

| Suite | Tests | Result |
|-------|-------|--------|
| Canonical patch (Codex) | 3 | PASS |
| Eval attribution (Codex) | 2 | PASS |
| Component mutation (integrated) | 55 | PASS |
| **Total focused** | **60** | **PASS** |

## Skeptic Review Fixes Applied

1. **P1 Confidence type mismatch**: Added `to_float()` method on `AttributionConfidence` (HIGH→0.9, MEDIUM→0.7, LOW→0.4, HEURISTIC→0.2) so credit entries can normalize to the float scale used by `ComponentAttribution`.
2. **P2 ComponentType drift**: Guarded by `test_component_type_values_match_codex_vocabulary` test. The enum lives in `optimizer/component_credit.py` near the credit analyzer; moving it to `shared/` deferred to avoid scope creep.
3. **P2 Unconnected to production**: Intentional — the credit/mutation pipeline is a new capability for the optimization loop to consume. Integration point: `optimizer/loop.py` or `optimizer/proposer.py` when trace-based mutation replaces/complements the mock proposer.
4. **P3 Missing dispatch for 3 types**: Documented in `_ops_for_entry()` docstring. callback/sub_agent/mcp_server need richer context to mutate safely.

## Risks and Future Work

1. **Mutation generators are heuristic** — the 7 generators apply fixed strategies (e.g., increase timeout +2000ms, add fallback routing). Future: LLM-based mutation generation using blame context.
2. **No trace-to-eval bridge yet** — the credit analyzer and eval attribution operate independently. Future: unified attribution that combines both signals.
3. **Add operations use synthetic paths** — when adding new components (e.g., fallback routing rule), the path is constructed rather than discovered. This works because Codex's apply_patch_bundle handles `add` at the end of lists.
4. **No UI for trace-based blame** — the credit analyzer output isn't surfaced in the web console yet. The data flows through TypedPatchBundle metadata but has no dedicated view.
