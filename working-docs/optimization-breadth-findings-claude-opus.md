# Optimization Breadth: Component-Graph Optimization — Findings

**Author:** Claude Opus  
**Date:** 2026-04-12  
**Branch:** `feat/optimization-breadth-components-claude-opus`

## What Optimization Scope Widened

Before this work, the optimizer could only mutate flat config dicts via untyped `Proposal` objects. The mutation operators existed for 14 surfaces but worked on string/dict keys without type safety or connection to the canonical IR.

After this work, the optimizer can:

1. **Target any canonical IR component** — instructions, tools, routing rules, guardrails, policies, handoffs, environment, and sub-agent components are all addressable via typed `ComponentRef` paths
2. **Propose typed changes** — each patch carries operation (add/modify/remove), old_value for conflict detection, and new_value with schema-aware structure
3. **Traverse sub-agent hierarchies** — patches can target components inside nested sub-agents via `sub_agent_path`
4. **Bridge to the flat config world** — `apply_and_convert()` produces both a new `CanonicalAgent` and a flat config dict for the existing eval pipeline

### New optimizable surfaces (with concrete mutation logic):

| Surface | Failure trigger | Patch strategy |
|---------|----------------|----------------|
| Routing rules | routing_error | Expand keywords, add fallback rules |
| Tool contracts | tool_failure | Increase timeout, add descriptions |
| Guardrails | safety_violation | Upgrade enforcement to BLOCK, add safety gate |
| Instructions | hallucination, quality | Add anti-hallucination constraints, enhance verification |
| Handoffs | infinite_loop, context loss | Upgrade to FULL context transfer, add conditions |
| Policies | safety_violation | Add REQUIRED safety policy, upgrade enforcement |
| Environment | timeout | Reduce max_tokens, lower temperature |

## What Component Attribution Now Works

The `ComponentCreditAnalyzer` maps failures to specific component types in the canonical IR, replacing the agent-level-only blame map with component-level attribution.

### Attribution strategy (priority order):

1. **Explicit trace annotations** (HIGH confidence) — `blamed_component`, `failed_tool`, `failed_guardrail` fields in traces are trusted directly
2. **Failure-type heuristic mapping** (MEDIUM-HIGH confidence) — `routing_error → routing_rule`, `tool_failure → tool`, `safety_violation → guardrail+policy`, etc.
3. **Trace structure refinement** — tool call names, expected specialists, triggered guardrails narrow attribution to specific component instances
4. **Fallback** (HEURISTIC confidence) — unknown failures attributed to instruction component

### What's trustworthy vs heuristic (explicit in the data):

| Attribution path | Confidence | Example |
|-----------------|------------|---------|
| Explicit `failed_tool` field | HIGH | trace has `{"failed_tool": "catalog"}` |
| `failure_type=routing_error` | HIGH | deterministic mapping to routing_rule |
| `failure_type=safety_violation` | MEDIUM | could be guardrail or policy |
| `failure_type=hallucination` | MEDIUM | instruction is probable but not certain |
| `failure_type=timeout` | LOW | could be environment or tool |
| Unknown/fallback | HEURISTIC | no reliable signal |

Every `ComponentBlameEntry` carries its `confidence` field so consumers can filter or weight appropriately. This is honest about the limits of static attribution.

## What Patch Bundle Model Was Introduced

The `PatchBundle` is a typed, validated, serializable collection of `ComponentPatch` objects:

### Key properties:

- **Immutable-apply semantics** — `bundle.apply(agent)` returns a new `CanonicalAgent`, never mutates the input
- **Conflict detection** — each patch carries `old_value`; mismatches raise `ValueError` at apply time
- **Structural validation** — `bundle.validate()` checks schema invariants before apply (add needs new_value, can't remove environment, etc.)
- **Serialization** — `to_dict()`/`from_dict()` for JSON round-trips to external coding agents
- **Review integration** — `to_diff_hunks()` produces `DiffHunk`-compatible dicts for `ProposedChangeCard`
- **Content hashing** — deterministic hash for deduplication
- **Touched surfaces** — `bundle.touched_surfaces` lists affected component types for repetition avoidance

### External agent interface:

An external coding agent can:
1. Receive a `PatchBundle.to_dict()` as a typed proposal
2. Validate it (`validate()`)
3. Preview it (`preview()`)
4. Apply it to a `CanonicalAgent`
5. Or propose their own patches using the same schema

This replaces the previous untyped `Proposal(change_description, config_section, new_config, reasoning)` with a structured format that's easier to validate and review.

## Test Coverage

69 new tests covering:

| Area | Tests | Coverage |
|------|-------|----------|
| ComponentRef paths | 5 | Index, name, environment, sub-agent, round-trip |
| ComponentPatch serialization | 1 | Full round-trip |
| PatchBundle validation | 5 | Valid, add/modify/remove errors, environment |
| PatchBundle apply | 12 | Modify by name/index, add/remove, environment, conflict, errors |
| PatchBundle serialization | 5 | Round-trip, hash, diff hunks, surfaces, preview |
| ComponentCreditAnalyzer | 16 | All failure types, explicit annotations, refinement, severity, edge cases |
| Component mutation proposals | 13 | All 7 component types, past surface skip, limits, edge cases |
| End-to-end pipeline | 4 | Analyze+propose for routing/tool/safety/success |
| Apply+convert bridge | 2 | Config dict output, guardrail round-trip |
| Integration | 5 | Full pipeline, safety fix, serialization, mixed failures, sub-agents |

All 69 tests pass. All 3,357 pre-existing tests pass (0 regressions).

## Files Changed

| File | Type | Lines | Purpose |
|------|------|-------|---------|
| `optimizer/component_patch.py` | New | ~280 | Typed patch bundle model |
| `optimizer/component_credit.py` | New | ~220 | Component-level credit assignment |
| `optimizer/component_mutation.py` | New | ~310 | Component-aware mutation proposals |
| `tests/test_component_optimization.py` | New | ~530 | Comprehensive tests |
| `working-docs/optimization-breadth-plan-claude-opus.md` | New | ~90 | Architecture plan |
| `working-docs/optimization-breadth-findings-claude-opus.md` | New | ~120 | This document |

## What Still Remains Approximate or Future Work

### Approximate:

1. **Heuristic attribution for some failure types** — timeout → environment/tool, invalid_output → instruction/guardrail are educated guesses. The confidence field makes this explicit.
2. **Mock mutation strategies** — the concrete patch generators (e.g., "add keywords from target name") are deterministic heuristics. LLM-based mutation generation would produce better patches.
3. **No cross-component interaction modeling** — a routing rule change may require a matching handoff change. Currently patches are independent.

### Future work:

1. **LLM-based component mutations** — use the LLM proposer to generate typed patches instead of heuristic ones
2. **Optimizer loop integration** — wire `analyze_and_propose()` into `Optimizer.optimize()` as an alternative to the flat-config proposer path
3. **Change card enrichment** — use `PatchBundle.to_diff_hunks()` to produce richer `ProposedChangeCard` entries with per-component diffs
4. **Pareto archive on component graph** — track which component-level mutations are on the Pareto frontier
5. **Adapter round-trip verification** — ensure patch bundles survive CX/ADK export and re-import
6. **Trace instrumentation** — add `blamed_component`, `failed_tool`, `failed_guardrail` fields to real trace collection for HIGH confidence attribution
7. **Callback mutation bodies** — currently callbacks are represented as policies; actual callback code mutation would require code generation
