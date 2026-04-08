# CX Hardening Merge Plan — 2026-04-08

## Branches

| Branch | SHA | Summary |
|--------|-----|---------|
| `feat/cx-native-expansion-codex` | c00b9f4 | Expands CX-native editable surfaces: pages, generators, transition route groups, richer playbook/flow/intent/entity payloads, projection metadata, CxEditable* contracts, ADK mapper expansion |
| `feat/cx-deploy-hardening-claude` | 65cee11 | Adds deploy safety UX: preflight validation, diff change-safety classification, canary/promote/rollback lifecycle, deploy status API, CxDeploy.tsx hardened UI |

## Overlap / Conflict Zones

### `cx_studio/types.py` — LOW conflict
- **Codex** adds: `CxTransitionRouteGroup`, `CxProjectionMetadata`, `CxProjectionSummary`, 8× `CxEditable*` models, `transition_route_groups` to `CxAgentSnapshot`, imports `ProjectionQualityStatus`.
- **Claude** adds: `DeployPhase`, `ChangeSafety`, `PreflightResult`, `CanaryState` enums/models near EOF.
- **Resolution**: Both are additive. Keep both. Only merge conflict is the `from portability.types import ...` line (Codex adds `ProjectionQualityStatus`; Claude leaves it unchanged). Take Codex import.

### `cx_studio/exporter.py` — MEDIUM conflict
- **Codex** expands `_apply_snapshot_changes`, `_apply_*` methods, `_field_entries`, `_set_field` with new resource types and richer payloads.
- **Claude** adds `ChangeSafety` import, augments `_compute_changes` with safety/rationale classification, adds `_classify_change_safety` static method.
- **Resolution**: Both touch different methods. Import line will conflict (both modify line 13). Take union. The `_classify_change_safety` safe/lossy tables need updating to reflect codex's expanded surfaces (playbook now round-trips goal/handlers/params; flow round-trips event_handlers/route_groups; intent round-trips parameters; entity_type round-trips auto_expansion_mode; new resources: page, generator, transition_route_group).

### No other file conflicts
All other files are branch-unique.

## Merge Order

1. **Codex first** — larger structural change (1897 insertions), establishes the expanded type/exporter surface.
2. **Claude second** — smaller surgical additions (1594 insertions but many are new files). The safety classifier merges on top and gets updated for the richer surface inventory.

## Post-merge Adjustments

- Update `_classify_change_safety` safe/lossy tables to cover new Codex surfaces:
  - **Safe**: playbook.{goal, input_parameter_definitions, output_parameter_definitions, handlers}, intent.parameters, entity_type.auto_expansion_mode, webhook.*, generator.{prompt_text, placeholders, llm_model_settings}, transition_route_group.transition_routes
  - **Lossy**: flow.{event_handlers, transition_route_groups}, page.{form, transition_routes, event_handlers, transition_route_groups}

## Verification Plan

1. `python -m pytest tests/test_cx_studio.py tests/test_portability_reporting.py tests/test_adk_mapper.py tests/test_cx_deploy_hardening.py -v`
2. `cd web && npm run build`
3. `cd web && npm test -- --run` (if vitest/jest configured)
4. Manual review of ExportReadiness and CxDeploy components for contract alignment.

## Major Risks

- **Safety classifier stale**: If `_classify_change_safety` doesn't reflect the expanded surfaces, changes that ARE safe would show as "blocked" — misleading UX. Must update.
- **DeployResult vs CanaryState**: Deployer now returns richer state; ensure CxDeploy.tsx properly handles both immediate and canary deploy responses.
- **CxEditable* contracts vs ExportReadiness**: The readiness UI may need to render projection quality from CxEditableWorkspace. Verify the contract flows through.
