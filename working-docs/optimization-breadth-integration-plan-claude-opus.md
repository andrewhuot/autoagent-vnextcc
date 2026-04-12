# Optimization Breadth Integration Plan

**Branch:** `feat/optimization-breadth-integration-claude-opus`
**Date:** 2026-04-12
**Author:** Claude Opus (integration agent)

## Context

Two parallel branches expanded AgentLab's optimization from flat config-dict mutations
to typed, component-aware patches:

| Branch | Commit | Focus |
|--------|--------|-------|
| `feat/optimization-breadth-components-codex` | 7fb0d9f | Production backbone: `shared/canonical_patch.py`, eval attribution, autofix/memory/API/frontend integration |
| `feat/optimization-breadth-components-claude-opus` | cbc989f | Intelligence layer: typed mutations, multi-tier credit assignment, 7 per-component generators |

Both fork from `0ed588d` (canonical IR commit). No file overlaps, but they define
**parallel patch and attribution abstractions** that would conflict architecturally
if merged wholesale.

## Strategy: Codex Backbone + Claude Intelligence

### 1. Land Codex as-is (fast-forward merge)

The Codex branch is the production backbone because it wires component patches into
every layer that matters at runtime:

- `shared/canonical_patch.py` — authoritative patch types (`TypedPatchBundle`, `ComponentReference`, `ComponentPatchOperation`)
- `evals/component_attribution.py` — eval-result-based attribution feeding into structured results
- `evals/runner.py`, `evals/results_model.py` — attribution in eval pipeline
- `optimizer/autofix.py` — `patch_bundle_to_config()` as apply authority
- `optimizer/memory.py`, `change_card.py` — persistence
- `api/routes/optimize.py`, `autofix.py`, `reviews.py` — API exposure
- `web/src/lib/types.ts` — frontend type hints

**Action:** `git merge origin/feat/optimization-breadth-components-codex`

### 2. Port Claude's component mutation module (adapted to Codex types)

Claude's `optimizer/component_mutation.py` (487 lines) is the prime candidate. It provides
7 specialized mutation generators that bridge failure analysis to concrete patches:

| Component | Failure Type | Patch Strategy |
|-----------|-------------|----------------|
| routing_rule | routing_error | Expand keywords, add fallback rules |
| tool_contract | tool_failure | Increase timeouts, add descriptions |
| guardrail | safety_violation | Upgrade enforcement to BLOCK, add safety gates |
| instruction | hallucination | Add anti-hallucination constraints |
| handoff | infinite_loop | Upgrade to FULL context transfer |
| policy | safety_violation | Add/upgrade safety policies |
| environment | timeout | Reduce max_tokens, lower temperature |

**Adaptation required:**
- Replace `optimizer.component_patch.ComponentPatch` → `shared.canonical_patch.ComponentPatchOperation`
- Replace `optimizer.component_patch.PatchBundle` → `shared.canonical_patch.TypedPatchBundle`
- Replace `optimizer.component_patch.ComponentRef` → `shared.canonical_patch.ComponentReference`
- Use `iter_component_references()` / `find_component_reference()` to resolve component paths
- Map Claude's `modify` → Codex's `replace`/`update` operations
- Map Claude's `add` → Codex's `add` operations

**What stays from Claude:**
- All 7 mutation generators (rewritten to produce Codex types)
- `propose_component_patches()` top-level function
- `analyze_and_propose()` convenience function
- `apply_and_convert()` bridge function (uses `patch_bundle_to_config`)
- Risk classification logic
- Past-surface deduplication

### 3. Port Claude's credit analyzer (adapted, no duplicate ComponentType)

Claude's `optimizer/component_credit.py` (345 lines) provides trace-based multi-tier
attribution that complements the Codex eval-result-based attribution:

**What to port:**
- `AttributionConfidence` enum (HIGH/MEDIUM/LOW/HEURISTIC) — valuable semantic layer
- `ComponentBlameEntry` dataclass — component-level aggregate blame
- `ComponentCreditAnalyzer` class — multi-tier attribution strategy
- `_FAILURE_TYPE_TO_COMPONENT` mapping — failure type → component type heuristics
- `_SEVERITY_MULTIPLIERS` — severity-weighted impact scoring
- Trace keyword classification
- Explicit annotation support (blamed_component, failed_tool, failed_guardrail)

**Adaptation required:**
- Use plain string component types matching Codex vocabulary ("tool_contract" not "tool")
- Remove dependency on `optimizer.component_patch.ComponentType` enum
- Define a local `ComponentType` enum aligned with Codex's component_type strings

### 4. Deliberately leave behind

| Claude file | Reason |
|------------|--------|
| `optimizer/component_patch.py` | Duplicate of `shared/canonical_patch.py`. Different type system (dataclass vs Pydantic, index-based vs path-based). Keeping both would create split-brain patch semantics. |
| `tests/test_component_optimization.py` (as-is) | Tests the Claude-only types. Port test logic into new tests using Codex types. |

### 5. Test strategy

1. **New tests** in `tests/test_component_mutation.py`:
   - Each mutation generator produces valid `ComponentPatchOperation` objects
   - Generated `TypedPatchBundle` passes `validate_patch_bundle()` against test agents
   - End-to-end: traces → credit analysis → mutation proposals → apply → config
   - Integration with `patch_bundle_to_config()` roundtrip
   - Risk classification, past-surface skipping, max-patches limit

2. **Existing Codex tests** must still pass:
   - `tests/test_canonical_patch.py`
   - `tests/test_eval_component_attribution.py`
   - `tests/test_autofix.py`

3. **Broader regression:** optimizer, eval, and review test suites

## File Map

| Action | File | Source |
|--------|------|--------|
| merge | `shared/canonical_patch.py` | Codex (authoritative) |
| merge | `evals/component_attribution.py` | Codex (authoritative) |
| merge | 16 modified files | Codex integrations |
| merge | `tests/test_canonical_patch.py` | Codex |
| merge | `tests/test_eval_component_attribution.py` | Codex |
| port+adapt | `optimizer/component_credit.py` | Claude → Codex types |
| port+adapt | `optimizer/component_mutation.py` | Claude → Codex types |
| new | `tests/test_component_mutation.py` | Integration tests |
| skip | `optimizer/component_patch.py` | Deliberately excluded (duplicate) |
| skip | `tests/test_component_optimization.py` | Deliberately excluded (tests duplicate types) |

## Risks

1. **Type mapping fidelity**: Claude's modify-with-old_value conflict detection doesn't exist in Codex's operations. Mitigation: validate_patch_bundle() provides equivalent safety.
2. **Component type vocabulary**: Claude uses "tool", Codex uses "tool_contract". Mitigation: explicit mapping table in credit module.
3. **Index-based vs path-based addressing**: Claude finds components by list index; Codex uses JSON-pointer paths. Mitigation: use `find_component_reference()` to resolve names to paths.
