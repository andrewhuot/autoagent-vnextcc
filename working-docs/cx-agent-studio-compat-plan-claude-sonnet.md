# CX Agent Studio Compatibility — Implementation Plan
**Author:** Claude Sonnet  
**Date:** 2026-04-13  
**Branch:** `feat/cx-agent-studio-compat-claude-sonnet`

---

## Scope

Improve import/export fidelity for Google Dialogflow CX / Conversational Agents so that round-trips actually work with higher reliability. Focus on bugs that cause real data loss or silent failures with the live CX REST API.

---

## Pre-implementation findings (summary)

After reading the codebase broadly (mapper, exporter, client, types, tests, docs), seven concrete fidelity gaps were identified. Full analysis is in `cx-agent-studio-compat-findings-claude-sonnet.md`.

### Priority 1 — Critical (silent API failures / data loss)

| # | Location | Issue |
|---|---|---|
| 1 | `exporter.py` | All multi-word `update_mask` fields use snake_case; CX REST API v3 requires camelCase. Updates silently ignored by the API. |
| 2 | `exporter.py:_field_entries` | `page.entry_fulfillment` not tracked → not compared in diff/conflict |
| 3 | `exporter.py:_field_entries` | `playbook.goal` not tracked → goal changes invisible in diff |
| 4 | `exporter.py:_apply_playbook_changes` | `referenced_tools/playbooks/flows` not in payload or update_mask → playbook tool references silently lost on export |
| 5 | `exporter.py:_apply_intent_changes` | `description` and `labels` not exported → intent metadata lost |

### Priority 2 — Correctness

| # | Location | Issue |
|---|---|---|
| 6 | `exporter.py:_field_entries` | `entity_type.auto_expansion_mode` not tracked (exported but not diffed) |
| 7 | `exporter.py:_apply_page_changes` | New pages silently skipped (`if original is None: continue`); should call `create_page` |
| 8 | `exporter.py:_SAFE_CHANGES` | Missing entries for `playbook.goal`, `playbook.referenced_*`, `intent.description`, `intent.labels` |
| 9 | `exporter.py:_set_field` | No handlers for `playbook.goal`, `playbook.referenced_*`, `intent.description`, `intent.labels` → sync merges silently drop these |

---

## Implementation plan

### Step 1: Fix `update_mask` camelCase (exporter.py)

Convert all `update_mask` lists from snake_case to camelCase as required by the CX REST API:

| Resource | Before | After |
|---|---|---|
| agent | `["description", "generative_settings"]` | `["description", "generativeSettings"]` |
| playbook | `["instruction", "goal", "input_parameter_definitions", ...]` | `["instruction", "goal", "inputParameterDefinitions", "outputParameterDefinitions", "handlers"]` |
| flow | `["description", "transition_routes", "event_handlers", "transition_route_groups"]` | `["description", "transitionRoutes", "eventHandlers", "transitionRouteGroups"]` |
| page | `["entry_fulfillment", "form", "transition_routes", ...]` | `["entryFulfillment", "form", "transitionRoutes", "eventHandlers", "transitionRouteGroups"]` |
| intent | `["training_phrases", "parameters"]` | `["trainingPhrases", "parameters"]` |
| entity_type | `["kind", "auto_expansion_mode", "entities", "excluded_phrases"]` | `["kind", "autoExpansionMode", "entities", "excludedPhrases"]` |
| webhook | `["generic_web_service", "timeout", "disabled"]` | `["genericWebService", "timeout", "disabled"]` |
| generator | `["prompt_text", "placeholders", "llm_model_settings"]` | `["promptText", "placeholders", "llmModelSettings"]` |
| transition_route_group | `["transition_routes"]` | `["transitionRoutes"]` |

### Step 2: Fix `_field_entries` to track all exported fields

Add tracking for:
- `("page", page.name, "entry_fulfillment")` → page entry messages
- `("playbook", playbook.name, "goal")` → playbook goal
- `("entity_type", entity_type.name, "auto_expansion_mode")` → expansion mode
- `("intent", intent.name, "description")` → intent description
- `("intent", intent.name, "labels")` → intent labels
- `("playbook", playbook.name, "referenced_tools")` → tool references
- `("playbook", playbook.name, "referenced_playbooks")` → playbook references
- `("playbook", playbook.name, "referenced_flows")` → flow references

### Step 3: Fix `_SAFE_CHANGES` and `_LOSSY_CHANGES`

Add missing safe fields: `playbook.goal`, `playbook.referenced_*`, `intent.description`, `intent.labels`.
Move `page.entry_fulfillment` into `_LOSSY_CHANGES` (it's already pushed but wasn't classified).

### Step 4: Fix `_apply_playbook_changes` payload

Add `referencedTools`, `referencedPlaybooks`, `referencedFlows` to the payload and comparison. Add to `update_mask`.

### Step 5: Fix `_apply_intent_changes` payload

Add `description` and `labels` to payload, comparison, and update_mask.

### Step 6: Fix `_set_field` handlers

Add setters for `playbook.goal`, `playbook.referenced_tools/playbooks/flows`, `intent.description`, `intent.labels`.

### Step 7: Add `create_page` to client and fix `_apply_page_changes`

Add `create_page` method to `CxStudioClient`. Update `_apply_page_changes` to create new pages instead of skipping them.

### Step 8: Write comprehensive tests

New tests in `tests/test_cx_roundtrip.py`:
- update_mask camelCase verification
- playbook referenced_tools round-trip
- intent description/labels round-trip
- page entry_fulfillment tracked in diff
- playbook goal tracked in diff
- new page creation via export

---

## What remains intentionally partial

| Surface | Status | Rationale |
|---|---|---|
| Page topology (add/remove flows) | Read-only | Structural mutations require complex dependency resolution |
| App-level tools | Read-only | CX tool resources are not editable through workspace config |
| Playbook code blocks | Read-only | Execution-time code; not declarative config |
| Playbook examples | Unsupported | Not fetched from the examples sub-resource |
| Speech settings | Read-only | Platform-specific audio config, not agent logic |
| Test cases | Read-only (import only) | Converted to evals on import; no writeback path |
| Environments/Versions | Read-only | Deployment concerns separate from config |
| Service directory webhooks | Partially preserved | `service_directory` field preserved in `raw` but not exposed editably |

---

## Verification ladder

1. `python -m pytest tests/test_cx_roundtrip.py -v` — CX-specific round-trip tests
2. `python -m pytest tests/test_cx_studio_integration.py -v` — integration features
3. `python -m pytest tests/test_cx_studio_api.py tests/test_cx_deploy_hardening.py -v` — API/deploy safety
4. `python -m pytest tests/test_cx_surface_inventory.py -v` — surface matrix alignment
5. `python -m pytest tests/ -x -q` — broader regression check
6. `git diff --check` — no whitespace errors
