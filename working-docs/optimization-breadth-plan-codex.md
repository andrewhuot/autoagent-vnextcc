# Optimization Breadth Components — Codex Plan

**Author:** Codex
**Date:** 2026-04-12
**Branch:** `feat/optimization-breadth-components-codex`
**Status:** Implementation complete; verification in progress

## Goal

Implement meaningful optimization-breadth slices that make AgentLab's optimizer
operate on the canonical component graph rather than only flat prompt/config
surfaces.

The campaign targets three linked outcomes:

1. Connect nominal component surfaces to optimization analysis:
   callbacks, guardrails, handoffs, routing rules, and tool contracts.
2. Add component-aware credit assignment so eval and trace failures can point
   to specific canonical graph components when evidence exists.
3. Add typed patch bundles so optimizers and external coding agents can propose
   reviewable, validated changes against canonical IR components.

## Read-First Checklist

- [x] `README.md`
- [x] `docs/platform-overview.md`
- [x] `docs/architecture.md`
- [x] `docs/features/workbench.md`
- [x] `working-docs/canonical-ir-adapters-plan-claude-opus.md`
- [x] `working-docs/canonical-ir-adapters-findings-claude-opus.md`
- [x] Current optimizer code and tests
- [x] Current eval, trace, and review code and tests

## Current Understanding

The canonical IR work on master introduced `CanonicalAgent` as the typed
component graph and conversion helpers that preserve instructions, tools,
routing rules, policies, guardrails, handoffs, sub-agents, MCP servers, and
environment metadata.

The optimization loop is currently centered on flat config dicts, generic
failure buckets, mutation names, mutation params, and diff previews. The useful
slice is therefore additive: keep existing flows working while adding component
graph analysis and typed patch metadata that can be used by the optimizer,
review surfaces, and external coding agents.

## Implementation Strategy

### Phase 1: Codebase Map and Requirements Trace

Status: Complete

- Read optimizer loop, proposer, mutation, autofix, review, and eval modules.
- Capture real data shapes for eval failures, trace events, proposals, change
  cards, and pending reviews.
- Identify the narrowest production hooks for typed patch bundles and
  component-aware failure attribution.

### Phase 2: Component Surface Model

Status: Complete

- Add small utilities around canonical IR that produce stable
  `component_type/name/path` references for instructions, tools, routing rules,
  guardrails, policies, handoffs, callbacks, and sub-agents.
- Treat ADK callbacks as operational policy components with callback metadata,
  unless a dedicated callback IR type proves necessary.
- Keep conversion additive and backward compatible.

### Phase 3: Component-Aware Credit Assignment

Status: Complete

- Add eval analysis that maps failure evidence to canonical component
  references.
- Prefer explicit evidence first: expected tool mismatches, trace tool calls,
  routing/handoff terms, guardrail/safety failures, and callback/policy markers.
- Fall back to existing generic buckets when evidence is insufficient.
- Return both component-level findings and legacy-friendly summaries.

### Phase 4: Typed Patch Bundles

Status: Complete

- Define typed patch operations against canonical graph components.
- Validate patch targets against a `CanonicalAgent` before review/apply.
- Preserve readable diff previews for existing review/UI surfaces.
- Support external coding-agent proposals by accepting serialized typed patch
  bundles with clear validation errors.
- Apply typed patches by converting the edited canonical graph back through
  `to_config_dict()` so existing `AgentConfig` validation remains authoritative.

### Phase 5: Optimizer and Review Integration

Status: Complete

- Wire component diagnostics into proposer payloads and mock-proposer outputs.
- Store or serialize patch bundle metadata alongside `AutoFixProposal` records
  without breaking existing SQLite rows.
- Ensure apply/reject/review flows can expose patch type, component target, and
  validation status without requiring a UI rewrite.

### Phase 6: Tests and Verification

Status: In progress

- Add focused tests before production changes for:
  - component reference extraction from canonical agents
  - trace/eval failures linking to specific tools, routing, guardrails, and
    handoffs
  - typed patch validation and application
  - proposal serialization compatibility
  - optimizer proposer attaching typed patch metadata for component-targeted
    routing repairs
- Run targeted pytest files first, then a broader smoke subset.

### Phase 7: Delivery

Status: Pending

- Update this plan and the findings document.
- Commit with a conventional commit message.
- Push `feat/optimization-breadth-components-codex`.
- Run the required `openclaw system event` completion signal.

## Parallel Investigation Lanes

The following read-only specialist lanes are running or planned:

- Optimizer proposal and mutation flow.
- Eval, trace, failure bucket, and blame analysis.
- Review/apply and change-card flow.
- Canonical IR and adapter nominal-surface coverage.

## Decision Rules

- Prefer additive contracts over replacing current proposal/review formats.
- Prefer canonical IR helpers that are useful from CLI, API, and coding-agent
  integrations.
- Attribute failures to components only when evidence supports it; include
  confidence and rationale.
- Preserve legacy generic buckets as a fallback.
- Keep tests independent and focused on behavior.

## Implemented Architecture Slice

- Added `shared/canonical_patch.py`, a small canonical component patch layer
  with:
  - stable `ComponentReference` records for instructions, tool contracts,
    routing rules, guardrails, policies, callback policies, handoffs,
    sub-agents, MCP servers, and environment settings
  - `ComponentAttribution` records that link failures to components with
    evidence and confidence
  - `TypedPatchBundle` and `ComponentPatchOperation` models
  - validation before application
  - a config bridge that applies patches through `CanonicalAgent` and merges
    patched canonical surfaces back into the existing config dict
- Added eval-result credit assignment in `evals/component_attribution.py`:
  routing failures map to routing rules or sub-agents, tool failures map to
  tool contracts, safety failures map to guardrails/policies/callbacks, and
  low-evidence behavior/keyword failures fall back to prompts.
- Threaded `component_attributions` through `EvalResult`, cached case payloads,
  structured result models, structured results SQLite storage, API result
  responses, and optimize-scoped failure samples.
- Threaded `patch_bundle` through optimizer proposals, optimization attempts,
  pending reviews, unified review items, AutoFix proposals, AutoFix SQLite
  persistence, AutoFix API responses, and change cards.
- Hardened AutoFix apply: proposals with `patch_bundle` are validated/applied
  through the canonical bridge and `AgentConfig` before status changes; legacy
  mutation operators still work and are also validated after application.

## Open Questions

- Full trace-span blame is still a follow-up: live trace instrumentation should
  populate span-level canonical component metadata before `BlameMap` groups by
  component ID.
- Dedicated first-class callback IR remains a possible future enhancement. This
  slice treats callbacks as operational policy components with callback
  metadata, matching current canonical conversion behavior.
- UI rendering for patch bundles can be added after backend/API payloads settle;
  existing diff previews remain the primary human view for now.

## Verification Log

- `pytest tests/test_canonical_patch.py tests/test_eval_component_attribution.py tests/test_autofix.py::TestAutoFixProposal::test_to_dict tests/test_autofix.py::TestAutoFixProposal::test_from_dict tests/test_autofix.py::TestAutoFixStore::test_save_and_get_preserves_patch_bundle tests/test_autofix.py::TestAutoFixEngine::test_apply_proposal_uses_patch_bundle_without_registry_operator tests/test_autofix.py::TestAutoFixEngine::test_apply_invalid_patch_bundle_does_not_mark_proposal_applied tests/test_proposer.py`
  - Result: 11 passed, 1 warning.
- `pytest tests/test_autofix.py tests/test_proposer.py tests/test_eval_runner_model.py tests/evals/test_results_model.py tests/evals/test_results_store.py tests/test_change_card.py`
  - Result before local venv setup: 79 passed.
- `.venv/bin/pytest tests/test_autofix.py tests/test_proposer.py tests/test_eval_runner_model.py tests/evals/test_results_model.py tests/evals/test_results_store.py tests/test_optimize_api.py tests/test_unified_reviews.py tests/test_change_card.py`
  - First run found one compatibility failure in optimize failure-sample
    construction for old `SimpleNamespace` examples lacking
    `component_attributions`.
  - After the fix: 112 passed.
- `.venv/bin/pytest`
  - First full result: 3914 passed, 12 warnings.
- `.venv/bin/pytest tests/test_autofix.py tests/test_proposer.py tests/test_canonical_patch.py tests/test_eval_component_attribution.py tests/test_optimize_api.py tests/test_unified_reviews.py`
  - Result after AutoFix registry hardening: 83 passed, 1 warning.
- `.venv/bin/pytest`
  - Final full result: 3914 passed, 20 warnings.
- `npm ci` in `web/`
  - Result: installed from lockfile; npm reported 2 audit vulnerabilities
    already present in dependency tree.
- `npm run build` in `web/`
  - Result: TypeScript and Vite build passed; Vite reported existing large
    chunk warning.
