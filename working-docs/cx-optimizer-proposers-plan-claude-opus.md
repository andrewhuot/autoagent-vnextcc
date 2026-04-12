# CX Optimizer Proposers — Implementation Plan

**Author:** Claude Opus  
**Date:** 2026-04-12  
**Branch:** `feat/cx-optimizer-proposers-claude-opus`

## Problem Statement

The optimizer proposer is shallow and CX-unaware:

1. **Proposer uses failure-bucket pattern matching** — The mock proposer (`optimizer/proposer.py`) matches `dominant_failure_bucket` to fixed config changes (append text to prompts, add routing keywords, increase timeouts). It doesn't reason about components or use blame analysis.

2. **Component mutation pipeline is disconnected** — `component_credit.py` (trace-based blame) and `component_mutation.py` (7 per-component mutation generators producing TypedPatchBundle) exist but are NOT wired into the proposer. They were ported from the Claude branch but never integrated.

3. **Canonical IR has no flow/state/transition types** — CX agents are built around flows, pages, transition routes, and event handlers. The IR has no representation for these. They survive round-trip only through the opaque `config["cx"]` CxEditableWorkspace, invisible to the optimizer.

4. **Optimizer can't propose CX-native changes** — Because flows/pages/transitions aren't in the IR, the mutation system can't generate patches for them. A CX routing problem gets a generic "add keywords" fix instead of a targeted transition route modification.

## Strategy

Pragmatic three-layer approach: wire what exists, extend what's needed, add what's missing.

### Layer 1: Wire credit/mutation into proposer (highest impact)

The blame analysis and mutation generators already exist and produce TypedPatchBundle. Connecting them to the proposer makes every proposal component-aware with evidence-backed targeting.

**Changes:**
- `optimizer/proposer.py`: Add `_credit_propose()` method that uses `ComponentCreditAnalyzer` + `propose_component_patches()` as the primary proposal path when traces/failure_samples are available
- Fall back to `_mock_propose()` only when no traces exist
- Convert blame-backed TypedPatchBundle into Proposal objects with proper patch_bundle

### Layer 2: Targeted IR extension for state machine graphs

Add minimal types that capture the flow/state/transition graph pattern shared by CX and ADK.

**New types in `shared/canonical_ir.py`:**
- `TransitionSpec` — condition, target, intent, fulfillment_message
- `EventHandlerSpec` — event name, handler action, fulfillment_message  
- `StateSpec` — name, entry_fulfillment, transitions, event_handlers, form parameters
- `FlowSpec` — name, description, states, transitions, event_handlers

**New field on `CanonicalAgent`:**
- `flows: list[FlowSpec]`

### Layer 3: CX flow projection and flow-aware mutations

- Enhance `CxAgentMapper` to project CX flows/pages/transitions into IR `FlowSpec`/`StateSpec`/`TransitionSpec`
- Enhance `canonical_ir_convert.py` to round-trip flows through config dict (stored in a `flows` key)
- Enhance `canonical_patch.py` `iter_component_references()` to enumerate flow components  
- Add flow/state/transition mutation generators in `component_mutation.py`
- Add `flow` and `transition` to `ComponentType` enum in `component_credit.py`

## File-by-File Change Plan

| File | Change | Risk |
|------|--------|------|
| `shared/canonical_ir.py` | Add TransitionSpec, EventHandlerSpec, StateSpec, FlowSpec; add flows field to CanonicalAgent | Low — additive, all defaults empty |
| `shared/canonical_ir_convert.py` | Add flows handling in `from_config_dict()` and `to_config_dict()` | Medium — must preserve existing conversion paths |
| `shared/canonical_patch.py` | Add flow/state/transition enumeration in `iter_component_references()` | Medium — must not break existing patch validation |
| `optimizer/proposer.py` | Add `_credit_propose()` as primary path; restructure `propose()` | High — core optimizer flow |
| `optimizer/component_mutation.py` | Add `_ops_for_flow()`, `_ops_for_state()`, `_ops_for_transition()` | Low — additive generators |
| `optimizer/component_credit.py` | Add `flow`, `state`, `transition` to ComponentType | Low — additive enum values |
| `adapters/cx_agent_mapper.py` | Project CX flows/pages/transitions into IR FlowSpec | Medium — must preserve CX round-trip |
| `tests/test_cx_optimizer_proposers.py` | New comprehensive test suite | N/A |

## What This Does NOT Change

- CX import/export/sync flows — these continue to use CxEditableWorkspace through `config["cx"]`
- ADK adapter — could benefit from flow types but is out of scope for this branch
- LLM proposer — remains as-is; credit-based proposer replaces the mock path
- Review/deploy flows — TypedPatchBundle is already the review currency
- Existing tests — all must continue passing

## Verification Plan

1. Focused: new test suite for proposer, IR extensions, flow round-trip
2. Related: existing `test_canonical_ir.py`, `test_canonical_patch.py`, `test_component_mutation.py`, `test_proposer.py`, `test_cx_roundtrip.py`, `test_cx_studio.py`
3. Broad: full `pytest` suite to catch regressions

## Risks

1. **Proposer behavior change** — Switching from mock to credit-based proposals changes what the optimizer generates. Mitigated by keeping mock as fallback and testing both paths.
2. **IR extension scope creep** — Flow types could sprawl. Mitigated by keeping them minimal (4 types) and forward-compatible (`extra: allow`).
3. **CX round-trip regression** — Flow projection could interfere with existing CxEditableWorkspace round-trip. Mitigated by keeping CX workspace in `config["cx"]` as-is and adding flows as a parallel representation.
