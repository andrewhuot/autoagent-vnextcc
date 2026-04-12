# CX Optimizer Proposers — Findings

**Author:** Claude Opus  
**Date:** 2026-04-12  
**Branch:** `feat/cx-optimizer-proposers-claude-opus`

## What Changed

### 1. Canonical IR Extension: Flow/State/Transition Types (`shared/canonical_ir.py`)

Four new Pydantic types added to the IR:

- **TransitionSpec** — target, condition, intent, fulfillment_message, parameters
- **EventHandlerSpec** — event, action, fulfillment_message, target
- **StateSpec** — name, display_name, entry_fulfillment, form_parameters, transitions, event_handlers
- **FlowSpec** — name, display_name, description, states, transitions, event_handlers

New field on **CanonicalAgent**: `flows: list[FlowSpec]` with helpers `flow_names()`, `all_states()`, `all_transitions()`.

All types use `model_config = {"extra": "allow"}` for forward compatibility.

### 2. Flow Serialization (`shared/canonical_ir_convert.py`)

Full round-trip support for flows through config dict:

- `to_config_dict()` serializes flows to a `flows` key
- `from_config_dict()` deserializes flows from the `flows` key
- 8 helper functions for serialization/deserialization of flows, states, transitions, event handlers

### 3. Flow Component Enumeration (`shared/canonical_patch.py`)

`iter_component_references()` now enumerates flow, state, and transition components with stable JSON-pointer paths:

- Flows: `/flows/{index}`
- States: `/flows/{fi}/states/{si}`
- Transitions: `/flows/{fi}/transitions/{ti}` and `/flows/{fi}/states/{si}/transitions/{ti}`

`flows` added to `_CANONICAL_CONFIG_KEYS` so flows survive `patch_bundle_to_config()`.

### 4. Credit-Based Proposer (`optimizer/proposer.py`)

New `_credit_propose()` method wired as the **primary proposal path** when traces/failure_samples are available:

1. Converts config to CanonicalAgent
2. Runs `ComponentCreditAnalyzer` on traces to produce blame entries
3. Runs `propose_component_patches()` to generate a TypedPatchBundle
4. Applies bundle via `patch_bundle_to_config()` to produce new config
5. Returns a Proposal with evidence-backed reasoning and structured patch_bundle

Falls back to `_mock_propose()` only when:
- No traces available
- All traces are successful (no blame entries)
- An exception occurs during analysis

### 5. Flow/State/Transition Mutation Generators (`optimizer/component_mutation.py`)

Three new generators added to the dispatch table:

- **`_ops_for_flow`** — Adds no-match event handlers to flows with dead ends; adds descriptions to undocumented flows
- **`_ops_for_state`** — Adds entry fulfillment to empty states; adds fallback event handlers to dead-end states  
- **`_ops_for_transition`** — Adds conditions to conditionless transitions; adds fulfillment messages for user clarity

### 6. Flow-Aware Credit Analysis (`optimizer/component_credit.py`)

Three new `ComponentType` enum values: `flow`, `state`, `transition`.

New failure type mappings:
- `flow_error` → flow (HIGH), transition (MEDIUM)
- `transition_error` → transition (HIGH)
- `state_error` → state (HIGH)
- `dead_end` → state (MEDIUM), transition (MEDIUM)
- `infinite_loop` now includes transition (MEDIUM)

New keyword classifiers: "flow", "transition", "dead end", "stuck", "state", "page"

### 7. CX Adapter Flow Projection (`adapters/cx_agent_mapper.py`)

New `_map_flows()` method projects CX flows/pages/transitions into IR-compatible structure:

- CX flows → FlowSpec (name, description, transitions, event_handlers)
- CX pages → StateSpec (name, entry_fulfillment, form_parameters, transitions, event_handlers)
- CX transition routes → TransitionSpec (target, condition, intent, fulfillment_message)
- CX event handlers → EventHandlerSpec (event, action, target, fulfillment_message)

Fulfillment text extracted from CX's nested `triggerFulfillment.messages[].text.text[]` structure.

Flow projection is **additive** — the existing CxEditableWorkspace in `config["cx"]` continues to function unchanged.

## What This Improves

| Dimension | Before | After |
|---|---|---|
| **Proposer intelligence** | Pattern-matching on failure bucket strings → fixed config changes | Component-level blame analysis → targeted typed patches with evidence |
| **CX flow visibility** | Flows invisible to optimizer (opaque in `config["cx"]`) | Flows projected into IR; enumerable, patchable, and optimizable |
| **Mutation targeting** | 7 component generators (no flow/state/transition) | 10 generators including flow, state, and transition mutations |
| **Patch addressability** | Instructions, tools, routing, guardrails, etc. | + flows, states, transitions (nested under flows) |
| **Round-trip fidelity** | Flows survived only through snapshot preservation | Flows survive through both IR and config dict serialization |
| **Credit analysis** | 9 failure types mapped to components | 13 failure types including flow-specific patterns |

## What Remains Intentionally Lossy

| Component | Status | Rationale |
|---|---|---|
| CX page form parameters | Preserved in IR but not optimizable | Form schemas are platform-specific |
| CX triggerFulfillment webhook tags | In metadata only | Execution-time behavior, not agent definition |
| ADK flows | Not yet projected | ADK uses different sub-agent routing; future work |
| LLM proposer flow awareness | Not changed | LLM proposer receives config dict which now includes flows |
| CxEditableWorkspace | Unchanged | Continues to function for CX-native round-trip; flows are parallel |

## Test Results

| Suite | Tests | Result |
|---|---|---|
| **New: test_cx_optimizer_proposers.py** | 67 | PASS |
| Canonical IR (existing) | 63 | PASS |
| Canonical Patch (existing) | 3 | PASS |
| Component Mutation (existing) | 56 | PASS (vocabulary test updated) |
| Proposer (existing) | 1 | PASS |
| CX Round-Trip (existing) | 4 | PASS |
| CX Studio (existing) | 50 | PASS |
| ADK (existing) | 40 | PASS |
| Skill Proposer (existing) | 12 | PASS |
| AutoFix (existing) | 43 | PASS |
| Runtime Adapters (existing) | 4 | PASS |
| **Total verified** | **343** | **PASS** |

Pre-existing API test collection failures (starlette.testclient async dep) are unrelated to this change.

## Files Changed

| File | Type | Change Summary |
|---|---|---|
| `shared/canonical_ir.py` | Modified | +4 types (TransitionSpec, EventHandlerSpec, StateSpec, FlowSpec), flows field on CanonicalAgent, 3 helper methods |
| `shared/canonical_ir_convert.py` | Modified | +8 serialization/deserialization helpers, flows in to/from_config_dict |
| `shared/canonical_patch.py` | Modified | Flow/state/transition enumeration in iter_component_references, flows in config keys |
| `optimizer/proposer.py` | Modified | New _credit_propose() method, restructured propose() to use credit path first |
| `optimizer/component_mutation.py` | Modified | +3 mutation generators (_ops_for_flow/state/transition) |
| `optimizer/component_credit.py` | Modified | +3 ComponentType values, +4 failure type mappings, +5 keyword classifiers |
| `adapters/cx_agent_mapper.py` | Modified | +_map_flows() and _extract_fulfillment_text(), flows in to_agentlab() |
| `tests/test_cx_optimizer_proposers.py` | New | 67 tests covering all new functionality |
| `tests/test_component_mutation.py` | Modified | Updated vocabulary test for new component types |
| `working-docs/cx-optimizer-proposers-plan-claude-opus.md` | New | Implementation plan |
| `working-docs/cx-optimizer-proposers-findings-claude-opus.md` | New | This document |

## Risks

1. **Proposer behavior change**: The credit-based proposer produces different proposals than the mock. This is intentional — credit proposals are evidence-backed. Mock still available as fallback.
2. **IR extension forward compatibility**: New types use `extra: allow` and default to empty, so existing configs load unchanged.
3. **CX flow projection**: Additive to existing CxEditableWorkspace round-trip. Both representations coexist.
