# Optimization Breadth Components — Codex Findings

**Author:** Codex
**Date:** 2026-04-12
**Branch:** `feat/optimization-breadth-components-codex`
**Status:** Implementation complete; verification in progress

## Source Read Findings

### Product and Architecture Docs

- AgentLab's core product loop is `BUILD -> WORKBENCH -> EVAL -> COMPARE ->
  OPTIMIZE -> REVIEW -> DEPLOY`.
- Workbench materializes candidates for Eval but does not run Eval or Optimize.
  Optimize should use completed eval evidence rather than structural readiness.
- Improvements/review artifacts are distinct from optimization experiments and
  deployable versions.
- The backend architecture documents the optimizer as a proposer/gates/significance
  service operating beside Eval Runner and Observer.
- Persistent state includes conversations, optimizer memory, eval history,
  configs, loop checkpoints, dead letters, logs, releases, and experiments.

### Canonical IR Baseline

The canonical IR work now on master defines a typed `CanonicalAgent` graph with:

- instructions
- tool contracts and tool parameters
- routing rules
- policies
- guardrails
- handoffs
- recursive sub-agents
- MCP servers
- environment config
- example traces
- metadata
- fidelity notes

Conversion helpers already cover imported specs, config dicts, `AgentConfig`,
and ADK trees. Adapter work improved preservation of tool parameters, guardrails,
handoffs, instructions, MCP servers, ADK sub-agent hierarchy, and routing.

### Initial Gap Hypothesis

The optimizer and review surfaces appear to still use:

- flat config dictionaries
- mutation names plus params
- generic failure buckets
- string diff previews
- coarse proposal surfaces

The likely highest-leverage path is not to replace those flows. It is to add a
typed layer that:

- produces stable component references from canonical IR
- attaches component attribution to failure analysis
- attaches typed patch bundles to proposals
- validates typed patch targets before review/apply
- serializes back to legacy-friendly proposal and diff-preview shapes

## Code Investigation Notes

### Repository State

- Current branch: `feat/optimization-breadth-components-codex`
- Upstream comparison shown by git: branch is based against `origin/master`
- No repo-local `AGENTS.md` file was found in the checkout; the user-supplied
  AGENTS instructions control this run.

### Investigation Lanes

Read-only subagent lanes were launched for:

- optimizer loop/proposer/mutation/autofix
- eval, trace, failure diagnosis, blame map
- review/apply, pending reviews, change cards
- canonical IR, adapters, nominal component surfaces

Their findings will be folded into this file before implementation decisions.

### Optimizer Proposal Flow

- `optimizer/proposer.py` returns a `Proposal` dataclass with
  `change_description`, `config_section`, `new_config`, and `reasoning`.
- The mock proposer already handles routing, prompt quality, timeout, tool
  failure, and safety buckets, but each branch edits flat config dicts.
- LLM proposals accept either a full `new_config` or a simple dot-path
  `new_config_patch`, not typed component patches.
- `optimizer/loop.py` validates the candidate via `AgentConfig`, evaluates
  baseline and candidate, applies gates/significance, and logs an
  `OptimizationAttempt`.
- `OptimizationAttempt` currently persists only change description, config diff,
  section, scores, significance, health context, and skills applied.

### AutoFix and Review Flow

- `AutoFixProposal` stores mutation name, surface, params, expected lift, risk,
  affected eval slices, cost estimate, diff preview, status, timestamps, and
  eval result.
- `AutoFixStore` persists proposals in SQLite with a fixed set of columns. A
  backwards-compatible typed patch slice should avoid mandatory schema churn or
  add a migration carefully.
- `/api/autofix` serializes proposals for frontend review cards and can attach
  extra fields with low risk if consumers ignore unknown keys.
- `PendingReview` is the durable optimizer human-review record for passing
  proposals. It is JSON-file-backed through `PendingReviewStore`.
- `ProposedChangeCard` and `DiffHunk` remain human-readable diff artifacts, with
  audit fields already available for richer metadata.

### Eval and Failure Evidence Flow

- `EvalRunner.evaluate_case()` produces `EvalResult` records with `details`,
  `failure_reasons`, `input_payload`, `expected_payload`, and `actual_output`.
- Eval already detects routing mismatch, behavior mismatch, missing keywords,
  tool mismatch, and safety check failure.
- `EvalHistoryStore` persists case payloads from `_case_payloads()`, so adding a
  serializable component attribution list to `EvalResult` can flow into history.
- Structured results in `evals/results_model.py` mirror failure reasons but do
  not currently include component attribution.
- API optimize scoped eval context converts failed examples into failure
  samples, but samples currently retain only user message, agent response,
  error text, safety flags, tool calls, specialist, and latency.

### Trace and Blame Flow

- `TraceCollector` records tool calls/responses, model calls/responses, errors,
  safety flags, state deltas, and agent transfers.
- `TraceGrader` has graders for routing, tool selection, tool arguments,
  retrieval quality, handoff quality, memory use, and final outcome.
- `BlameMap` clusters failed span grades by grader name, agent path, and failure
  reason.
- These trace pathways provide useful future evidence for component-aware
  attribution, but the lowest-risk first code slice is eval-result attribution
  because `EvalRunner` already has config, expected values, and actual output.

### Surface Inventory

- `optimizer/surface_inventory.py` already names nominal surfaces that match
  this mission: callbacks, guardrails/policies, tool contracts, handoff
  artifacts, workflow topology, sub-agents, and thresholds.
- Inventory notes are stale relative to canonical IR master for several fields:
  `AgentConfig` now represents `tools_config`, `guardrails`, `handoffs`,
  `policies`, `mcp_servers`, and `generation`.
- The inventory can be updated later, but the current implementation should use
  actual canonical IR fields as the source of truth.

## Candidate Implementation Hooks

- `shared/canonical_ir.py` and `shared/canonical_ir_convert.py` for component
  graph helpers and patch application.
- `optimizer/proposer.py`, `optimizer/loop.py`, `optimizer/autofix.py`, and
  `optimizer/autofix_proposers.py` for proposal generation and storage.
- `evals/runner.py`, `evals/scorer.py`, `evals/history.py`,
  `evals/results_model.py`, and trace modules for evidence extraction.
- `optimizer/diff_engine.py`, `optimizer/change_card.py`,
  `optimizer/pending_reviews.py`, `api/routes/autofix.py`,
  `api/routes/changes.py`, and `api/routes/reviews.py` for review surfacing.

## Implemented Findings and Changes

### Canonical Component Patch Layer

- Added a standalone `shared/canonical_patch.py` module rather than modifying
  `CanonicalAgent` itself. This keeps the canonical IR stable while giving
  optimizer/review flows a typed patch vocabulary.
- Component references are JSON-pointer based and cover:
  - `instruction`
  - `tool_contract`
  - `routing_rule`
  - `guardrail`
  - `policy`
  - `callback` for policy records with callback metadata
  - `handoff`
  - `sub_agent`
  - `mcp_server`
  - `environment`
- Patch bundles validate component existence and target field paths before
  application.
- Patch application converts config dicts to `CanonicalAgent`, applies typed
  operations, converts back through `to_config_dict()`, and merges only
  canonical surfaces into the original config. This preserves unrelated legacy
  config keys such as `thresholds`.

### Component-Aware Credit Assignment

- Added eval-level attribution in `evals/component_attribution.py`.
- Routing mismatches now point to the expected `routing_rule` or sub-agent when
  present.
- Tool mismatches now point to the expected `tool_contract`.
- Safety failures now point first to guardrails, then safety/compliance
  policies, callback policies, and finally instructions as a low-evidence
  fallback.
- Handoff context failures can point to a configured handoff.
- Behavior/keyword failures only point to instructions when no higher-evidence
  attribution exists.
- These attributions flow through:
  - `EvalResult`
  - eval cache/history case payloads
  - `ExampleResult`
  - structured results SQLite storage
  - result API response models
  - optimize-scoped failure samples

### Typed Patch Bundle Integration

- `Proposal` now accepts optional `patch_bundle` metadata.
- Mock routing repair proposals build typed append operations against canonical
  routing-rule components when scoped eval failures mine new keywords.
- `OptimizationAttempt` now persists optional serialized patch bundles.
- `PendingReview` and `UnifiedReviewItem` expose optional patch bundles while
  preserving current `config_diff` and `diff_summary` strings.
- `AutoFixProposal` now accepts optional patch bundles, and `AutoFixStore`
  performs a backward-compatible SQLite migration for the new column.
- `AutoFixEngine.apply()` now treats patch bundles as the apply authority when
  present, validates the patched config with `AgentConfig`, and only marks the
  proposal applied after successful validation.
- `ProposedChangeCard` now preserves optional patch bundles in its JSON record
  so external coding-agent proposals can carry typed metadata alongside human
  diff hunks.

## Risks to Track

- Existing mutation operators remain legacy-compatible; AutoFix now validates
  their outputs before marking proposals applied.
- Component attribution intentionally uses confidence values and falls back to
  prompts only when stronger component evidence is unavailable.
- Patch serialization is additive and optional for API/UI consumers.
- SQLite schema changes were limited to additive nullable/defaulted columns for
  AutoFix and structured eval results.
- Existing canonical conversion remains additive and old configs still load.
- Remaining risk: full trace-span credit assignment is not yet implemented;
  this slice is eval-result based.
- Remaining risk: patch bundle UI rendering is not implemented; backend/API
  payloads expose metadata for a future UI pass.

## Verification Notes

- Focused regression run:
  `pytest tests/test_canonical_patch.py tests/test_eval_component_attribution.py tests/test_autofix.py::TestAutoFixProposal::test_to_dict tests/test_autofix.py::TestAutoFixProposal::test_from_dict tests/test_autofix.py::TestAutoFixStore::test_save_and_get_preserves_patch_bundle tests/test_autofix.py::TestAutoFixEngine::test_apply_proposal_uses_patch_bundle_without_registry_operator tests/test_autofix.py::TestAutoFixEngine::test_apply_invalid_patch_bundle_does_not_mark_proposal_applied tests/test_proposer.py`
  - Result: 11 passed, 1 warning.
- Non-FastAPI broader run before local venv setup:
  `pytest tests/test_autofix.py tests/test_proposer.py tests/test_eval_runner_model.py tests/evals/test_results_model.py tests/evals/test_results_store.py tests/test_change_card.py`
  - Result: 79 passed.
- FastAPI/API broader run after creating `.venv` and installing `.[dev]`:
  `.venv/bin/pytest tests/test_autofix.py tests/test_proposer.py tests/test_eval_runner_model.py tests/evals/test_results_model.py tests/evals/test_results_store.py tests/test_optimize_api.py tests/test_unified_reviews.py tests/test_change_card.py`
  - First result: 1 failure in optimize failure-sample construction for old
    result objects without `component_attributions`.
  - Final result after fix: 112 passed.
- Full verification:
  `.venv/bin/pytest`
  - First result: 3914 passed, 12 warnings.
- Focused rerun after AutoFix registry hardening:
  `.venv/bin/pytest tests/test_autofix.py tests/test_proposer.py tests/test_canonical_patch.py tests/test_eval_component_attribution.py tests/test_optimize_api.py tests/test_unified_reviews.py`
  - Result: 83 passed, 1 warning.
- Final full verification:
  `.venv/bin/pytest`
  - Result: 3914 passed, 20 warnings.
- Frontend verification:
  `npm ci`
  - Result: installed from `web/package-lock.json`; npm reported 2 audit
    vulnerabilities in the dependency tree.
  `npm run build`
  - Result: TypeScript and Vite build passed; Vite reported a large chunk
    warning.
