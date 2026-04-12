# Optimization Breadth: Component-Graph Optimization Plan

**Author:** Claude Opus  
**Date:** 2026-04-12  
**Branch:** `feat/optimization-breadth-components-claude-opus`  
**Builds on:** Canonical IR work (`shared/canonical_ir.py`, `shared/canonical_ir_convert.py`)

## Problem

The optimizer currently works on flat `dict` configs and proposes changes via untyped `Proposal(change_description, config_section, new_config, reasoning)`. While `MutationSurface` declares 14 surfaces (including callback, guardrail, handoff, routing, tool_contract, policy), the actual optimization loop:

1. **Cannot target canonical IR components** — mutations apply to flat dict keys, not typed `CanonicalAgent` fields
2. **Credit assignment is agent-level only** — `MultiAgentBlameMap` attributes failures to agents by name, never to specific component types (was it the guardrail? the routing rule? the tool contract?)
3. **Proposals are untyped** — no structured patch format against the component graph; external coding agents receive raw dicts with no schema for what they're changing

## Solution: Three Interlocking Modules

### 1. Typed Patch Bundles (`optimizer/component_patch.py`)

A typed patch model that targets specific components in the `CanonicalAgent` graph.

**Key types:**
- `ComponentType` enum — maps 1:1 to canonical IR component classes (instruction, tool, routing_rule, guardrail, policy, handoff, sub_agent, mcp_server, environment)
- `PatchOperation` enum — add, modify, remove
- `ComponentRef` — path to a specific component: `(component_type, index_or_name, field?)`
- `ComponentPatch` — one typed change: operation + ref + old_value + new_value
- `PatchBundle` — collection of patches with validation, apply, preview, and rollback
- `PatchValidationResult` — schema-level validation before apply

**Design decisions:**
- Patches target `CanonicalAgent` directly (not flat dict), giving type safety
- Each patch carries old_value for rollback and conflict detection
- `PatchBundle.apply(agent)` returns a new `CanonicalAgent` (immutable semantics)
- `PatchBundle.to_dict()`/`from_dict()` for serialization to external coding agents
- Bridges to existing `DiffHunk` in `change_card.py` for review UI

### 2. Component-Aware Credit Assignment (`optimizer/component_credit.py`)

Extend blame beyond agents to specific component types.

**Key types:**
- `ComponentBlameEntry` — like `AgentBlameEntry` but with `component_type`, `component_name`, and `confidence` (trustworthy vs heuristic)
- `ComponentCreditAnalyzer` — maps failure types + trace signals to component types

**Attribution strategy (priority order):**
1. Explicit trace annotations (`blamed_component`, `failed_tool`, `failed_guardrail`)
2. Failure-type heuristic mapping:
   - `routing_error` → routing_rule component (high confidence)
   - `tool_failure` → tool component (high confidence)
   - `safety_violation` → guardrail component (medium confidence)
   - `hallucination` → instruction component (medium confidence)
   - `timeout` → environment/tool component (low confidence)
   - `invalid_output` → instruction/guardrail (low confidence)
3. Trace structure: tool call names, routing decisions, guardrail triggers in trace events
4. Fallback: instruction component (lowest confidence)

**Confidence levels are explicit** — consumers know what's trustworthy vs heuristic. This is honest about the limits of static attribution.

### 3. Component-Aware Mutations (`optimizer/component_mutation.py`)

Bridge canonical IR components to the optimization loop.

**Key functions:**
- `propose_component_patches(agent, failure_analysis, past_patches)` → `PatchBundle`
  - Maps component blame entries to concrete patch proposals
  - For routing: add keywords, adjust priorities, add fallback rules
  - For guardrails: adjust enforcement level, add new guardrails for safety violations
  - For tools: adjust timeout, modify description, add parameters
  - For handoffs: adjust context transfer mode, add conditions
  - For policies: adjust enforcement level
  - For instructions: append constraints, rewrite sections
- `apply_patch_bundle(agent, bundle)` → `CanonicalAgent`
  - Type-safe application with validation
- `patch_bundle_to_config_diff(bundle)` → dict compatible with existing `config_diff()` format
  - Bridges back to flat config world for existing eval/scoring pipeline

**Integration with existing optimizer:**
- The component mutation module produces `PatchBundle` objects
- These can be converted to flat config dicts via `to_config_dict()` for the existing eval pipeline
- The `ProposedChangeCard` gets richer `DiffHunk` entries from typed patches
- Existing `MutationOperator` apply functions continue to work (backwards compatible)

## File Plan

| File | Type | Purpose |
|------|------|---------|
| `optimizer/component_patch.py` | New | Typed patch bundle model |
| `optimizer/component_credit.py` | New | Component-level credit assignment |
| `optimizer/component_mutation.py` | New | Component-aware mutation proposals |
| `tests/test_component_optimization.py` | New | Tests for all three modules |

## What This Does NOT Change

- Existing mutation operators on flat dicts continue to work unchanged
- `Proposer` class still functions as before for non-IR-aware paths
- `MultiAgentBlameMap` is not modified (component credit is additive)
- Eval pipeline continues to score against flat configs
- No API route changes

## Integration Points

1. `PatchBundle` → `to_config_dict()` via `canonical_ir_convert.to_config_dict()` bridges typed patches to the existing eval pipeline
2. `ComponentBlameEntry` feeds into `propose_component_patches()` to target the right components
3. `PatchBundle.to_diff_hunks()` produces `DiffHunk` objects for `ProposedChangeCard`
4. `PatchBundle.to_dict()`/`from_dict()` enables external coding agents to propose typed changes

## Risks

1. **Attribution confidence** — component-level blame is often heuristic. Mitigated by explicit confidence field.
2. **Patch conflicts** — concurrent patches to the same component could conflict. Mitigated by old_value checks.
3. **IR drift** — if `CanonicalAgent` schema evolves, patches need updating. Mitigated by Pydantic's `extra="allow"`.

## Success Criteria

1. Can create a typed patch targeting any canonical IR component type
2. Can apply patches to produce a valid `CanonicalAgent`
3. Can attribute failures to specific component types with confidence levels
4. Can generate component-aware mutation proposals from blame analysis
5. Can round-trip patches through serialization for external agent consumption
6. All existing tests continue to pass
