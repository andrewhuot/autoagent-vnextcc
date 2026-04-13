# CX Agent Studio Compatibility — Findings and Implementation Results
**Author:** Claude Sonnet  
**Date:** 2026-04-13  
**Branch:** `feat/cx-agent-studio-compat-claude-sonnet`

---

## Summary

This session identified and fixed seven concrete fidelity gaps in the CX import/export path. All gaps caused silent data loss or incorrect API behavior in real export operations. 30 new tests were written to prove the fixes and prevent regression.

---

## What was fixed

### 1. `update_mask` field names: snake_case → camelCase (Critical API bug)

**Files:** `cx_studio/exporter.py`

The Dialogflow CX REST API v3 requires `update_mask` field paths to use camelCase (e.g., `generativeSettings`, not `generative_settings`). All multi-word field names in the exporter were using snake_case, which causes the CX API to silently ignore the specified updates — the PATCH call succeeds with HTTP 200 but doesn't write the intended fields.

**Fixed fields:**

| Resource | Snake (broken) | camelCase (fixed) |
|---|---|---|
| agent | `generative_settings` | `generativeSettings` |
| playbook | `input_parameter_definitions` | `inputParameterDefinitions` |
| playbook | `output_parameter_definitions` | `outputParameterDefinitions` |
| intent | `training_phrases` | `trainingPhrases` |
| entity_type | `auto_expansion_mode` | `autoExpansionMode` |
| entity_type | `excluded_phrases` | `excludedPhrases` |
| webhook | `generic_web_service` | `genericWebService` |
| flow | `transition_routes` | `transitionRoutes` |
| flow | `event_handlers` | `eventHandlers` |
| flow | `transition_route_groups` | `transitionRouteGroups` |
| page | `entry_fulfillment` | `entryFulfillment` |
| page | `transition_routes` | `transitionRoutes` |
| page | `event_handlers` | `eventHandlers` |
| page | `transition_route_groups` | `transitionRouteGroups` |
| generator | `prompt_text` | `promptText` |
| generator | `llm_model_settings` | `llmModelSettings` |
| transition_route_group | `transition_routes` | `transitionRoutes` |

**Tests:** `tests/test_cx_fidelity.py::TestUpdateMaskCamelCase` — 9 tests covering every updated resource.

---

### 2. Playbook goal not tracked in diff / conflict detection

**Files:** `cx_studio/exporter.py`

`_field_entries` omitted `playbook.goal`. This meant that a goal change in the workspace would not appear in `preview_changes` output or be detected as a conflict in sync. `_SAFE_CHANGES` already listed `playbook.goal` as safe but it was never tracked.

**Fix:** Added `("playbook", playbook.name, "goal")` to `_field_entries`. Added `goal` handling to `_set_field`.

**Tests:** `TestPlaybookFidelity::test_playbook_goal_tracked_in_diff`, `test_playbook_goal_survives_round_trip`

---

### 3. Playbook referenced_tools/playbooks/flows not exported

**Files:** `cx_studio/exporter.py`

`_apply_playbook_changes` did not include `referenced_tools`, `referenced_playbooks`, or `referenced_flows` in the payload or comparison. Adding a tool reference to a playbook was silently discarded on export. These fields are critical for playbook routing and tool invocation in CX Agent Studio.

**Fix:**
- Added `referencedTools`, `referencedPlaybooks`, `referencedFlows` to the export payload
- Added them to the comparison condition (triggers update when changed)
- Added them to `update_mask`
- Added them to `_field_entries` for diff/conflict tracking
- Added them to `_set_field` for sync merge
- Added `referenced_tools`, `referenced_playbooks`, `referenced_flows` to `_SAFE_CHANGES`

**Tests:** `TestPlaybookFidelity::test_playbook_referenced_tools_exported`, `test_playbook_referenced_tools_in_update_mask`, `test_playbook_referenced_flows_tracked_in_diff`, `test_playbook_referenced_tools_round_trip`

---

### 4. Intent description and labels not exported

**Files:** `cx_studio/exporter.py`

`_apply_intent_changes` did not include `description` or `labels` in the export payload, comparison, or update_mask. Intent labels are used for NLU classification and organization in CX. Adding a label locally would be silently dropped on export.

**Fix:**
- Added `description` and `labels` to the export payload
- Added them to the comparison condition
- Added `"description"` and `"labels"` to `update_mask`
- Added them to `_field_entries` for diff/conflict tracking
- Added them to `_set_field` for sync merge
- Added `intent.description` and `intent.labels` to `_SAFE_CHANGES`

**Tests:** `TestIntentFidelity` — 7 tests covering description and labels export, diff tracking, round-trip, and update_mask presence.

---

### 5. Page entry_fulfillment not tracked in diff / conflict detection

**Files:** `cx_studio/exporter.py`

`_field_entries` omitted `page.entry_fulfillment`. Page entry messages were being pushed correctly in `_apply_page_changes` but changes would never show up in `preview_changes` or trigger conflict detection. A user editing page messages locally and a remote edit to the same page would silently merge without detecting the conflict.

**Fix:** Added `("page", page.name, "entry_fulfillment")` to `_field_entries`. Added `entry_fulfillment` handling to `_set_field`.

**Tests:** `TestPageFidelity::test_page_entry_fulfillment_tracked_in_diff`, `test_page_entry_fulfillment_change_is_classified_lossy`

---

### 6. New pages silently skipped in export (create_page missing)

**Files:** `cx_studio/exporter.py`, `adapters/cx_studio_client.py`

`_apply_page_changes` contained `if original is None: continue`. If a new page was added to the workspace via the editable CX contract, it would be applied to the local snapshot but silently skipped during export — never pushed to the CX API.

`CxStudioClient` also had no `create_page` method.

**Fix:**
- Added `create_page` method to `CxStudioClient` (POSTs to `{flow_name}/pages`)
- Updated `_apply_page_changes` to call `create_page` for new pages instead of skipping them

**Tests:** `TestPageFidelity::test_new_page_calls_create_page`, `test_existing_page_update_uses_update_page`

---

### 7. entity_type.auto_expansion_mode not tracked in diff

**Files:** `cx_studio/exporter.py`

`_field_entries` omitted `entity_type.auto_expansion_mode`. The field was correctly in `_SAFE_CHANGES` and was being pushed in `_apply_entity_type_changes`, but changes were invisible in diffs.

**Fix:** Added `("entity_type", entity_type.name, "auto_expansion_mode")` to `_field_entries`. Added `auto_expansion_mode` handling to `_set_field`.

**Tests:** `TestEntityTypeFidelity::test_auto_expansion_mode_tracked_in_diff`, `test_auto_expansion_mode_survives_round_trip`

---

## Test results

| Test file | Tests | Result |
|---|---|---|
| `tests/test_cx_fidelity.py` (new) | 30 | **All passed** |
| `tests/test_cx_roundtrip.py` | 4 | All passed |
| `tests/test_cx_studio_integration.py` | 4 | All passed |
| `tests/test_cx_studio_api.py` | 7 | All passed |
| `tests/test_cx_deploy_hardening.py` | 21 | All passed |
| `tests/test_cx_surface_inventory.py` | 1 | All passed |
| `tests/test_cx_studio.py` | 53 | All passed |
| Broader suite | 3238 | 1 pre-existing failure (shell script, unrelated) |

**Total CX tests: 120 passing. No regressions introduced.**

The one pre-existing failure (`test_stop_script_does_not_kill_unrelated_processes`) was confirmed to exist on the base branch before these changes.

---

## What remains intentionally partial

| Surface | Status | Rationale |
|---|---|---|
| Playbook examples | Unsupported | Examples sub-resource not fetched by client; would need a `list_playbook_examples` method and store |
| Playbook code blocks | Read-only | Execution-time code; storing/editing as config is not safe |
| App-level tools (OpenAPI/MCP/Python) | Read-only | CX tool resources cannot be mutated through workspace config; preserved in `preserved.app_tools` |
| Speech settings | Read-only | Audio pipeline config; not agent logic |
| Environments and versions | Read-only | Deployment lifecycle concerns separate from config |
| Test cases | Import-only | Converted to evals on import; no writeback path needed |
| Flow/page structural topology (add/remove) | Partial | `create_page` added; `create_flow` existed already. Removing flows/pages is intentionally blocked (destructive) |
| Webhook service_directory | Preserved in `raw` | Service Directory webhooks are stored in `raw` but the editable contract only surfaces `genericWebService` |
| Temp session parameters | Not tracked | `temp:` prefix params (vs `user:`, `app:`) are dropped as they're runtime-scoped |

---

## Files changed

| File | Change |
|---|---|
| `cx_studio/exporter.py` | Fixed 17 update_mask field names; added 11 missing `_field_entries` tracked fields; extended `_SAFE_CHANGES`; added referenced_tools/playbooks/flows to playbook payload; added intent description/labels; fixed `_set_field` for 8 new field handlers; fixed `_apply_page_changes` to create new pages |
| `adapters/cx_studio_client.py` | Added `create_page` method |
| `tests/test_cx_fidelity.py` | 30 new tests (all new file) |
| `working-docs/cx-agent-studio-compat-plan-claude-sonnet.md` | Plan document |
| `working-docs/cx-agent-studio-compat-findings-claude-sonnet.md` | This document |
