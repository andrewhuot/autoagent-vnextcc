# CX Native Expansion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Expand the CX-native editable surface area so both real CX imports and projected ADK imports land in meaningful, optimizable CX Agent Studio structures, while preserving raw source evidence and reporting exactly which mappings are faithful, approximated, or preserved-only.

**Architecture:** Add an additive typed `cx` workspace contract that sits alongside existing generic AgentLab config sections (`prompts`, `routing`, `tools`) instead of replacing them. Populate that contract from two sources: faithful resource-backed CX imports and best-effort ADK projections. Keep raw source snapshots and projection evidence, then compute portability and readiness from both editable CX coverage and projection quality rather than from coarse surface presence alone.

**Tech Stack:** Python, Pydantic, FastAPI, pytest, YAML/JSON workspace configs.

---

## Current Architecture Snapshot

- `adapters/cx_agent_mapper.py` preserves a rich raw CX snapshot in `_cx.snapshot`, but the editable contract is still mostly limited to `prompts`, `routing`, `tools`, and `model`.
- `cx_studio/exporter.py` already supports pushing more CX resources than the mapper exposes:
  - playbook instructions
  - flow descriptions and transition routes
  - intent training phrases
  - entity type definitions
  - webhook settings
- `cx_studio/surface_inventory.py` still classifies many of those areas as `read_only` because the editable workspace contract has not caught up.
- `registry/packs/cx_agent_studio.yaml` already assumes first-class CX-native target surfaces like `cx.playbooks.*`, `cx.flows.*`, `cx.generators.*`, and `cx.entities.*`, but no top-level `cx` config namespace exists yet.
- `cx_studio/compat.py` already expresses the intended ADK-to-CX direction:
  - instructions -> playbooks
  - sub_agents -> child-agent / transfer-style routing
  - callbacks -> generators
- `adk/mapper.py` currently maps ADK into generic AgentLab structures only, which leaves too little CX-native surface area for a CX-first optimization workflow.

## Proposed Typed CX Contract

Add additive typed models in `cx_studio/types.py` for a shared workspace-facing CX bundle:

- `CxProjectionQuality`: `faithful`, `approximated`, `preserved_only`
- `CxProjectionEvidence`: source refs, rationale, preserved raw refs, source platform
- `CxEditablePlaybook`
- `CxEditableFlow`
- `CxEditablePage`
- `CxEditableTransitionRouteGroup`
- `CxEditableIntent`
- `CxEditableIntentParameter`
- `CxEditableEntityType`
- `CxEditableGenerator`
- `CxEditableWebhook`
- `CxEditableProjectionSurface`
- `CxEditableWorkspace`

Top-level config shape:

```yaml
cx:
  source_platform: cx_studio | adk
  target_platform: cx_agent_studio
  projection_summary:
    editable_surface_count: ...
    faithful_count: ...
    approximated_count: ...
    preserved_only_count: ...
  playbooks: {}
  flows: {}
  route_groups: {}
  intents: {}
  entity_types: {}
  generators: {}
  webhooks: {}
  preserved: {}
  projection_surfaces: []
```

Rules:

- Keep `_cx.snapshot` for real CX imports and `_adk_metadata.agent_tree` for ADK imports.
- Keep legacy `prompts`, `routing`, `tools`, and `model` populated for backward compatibility.
- Treat `cx.*` as the source of truth for CX-native editing when present.

## Projection Quality Model

Every projected/imported CX-native surface should be classified as:

- `faithful`: source structure maps directly to an editable CX-native structure and can round-trip without semantic loss under current support.
- `approximated`: structure is editable in CX-native form but required lossy reshaping, flattening, inferred routing, or synthetic IDs.
- `preserved_only`: source evidence is retained and reported, but no truthful editable CX-native structure exists yet.

This quality status should be attached:

- per CX-native surface in the new `cx` contract
- per portability row where relevant
- in aggregate portability/readiness summaries

## Design Choices

- Prefer editable CX-native surfaces over perfect source fidelity, but never hide approximations.
- Reuse existing exporter capabilities first, then widen the mapper to feed them.
- Use stable synthetic IDs for projected ADK resources so optimizers can target them across sessions.
- Keep route groups, handlers, and generators explicit even when only partially editable.
- Preserve source-native evidence for every projected record so reviewers can audit what came from where.

## Task 1: Add Failing Tests for the Expanded CX Contract

**Files:**
- Modify: `tests/test_cx_studio.py`
- Modify: `tests/test_cx_roundtrip.py`
- Modify: `tests/test_portability_reporting.py`
- Modify: `tests/test_adk_importer.py`
- Modify: `tests/test_adk_mapper.py`

**Step 1: Write the failing tests**

- Assert that real CX imports produce a top-level `cx` contract with editable records for:
  - flows/pages
  - transition route groups
  - intents + intent parameters
  - entity types
  - playbook parameters
  - playbook handlers
  - generators
- Assert that the mapper can apply edits from `config["cx"]` back onto a `CxAgentSnapshot` for the writable subset.
- Assert that ADK imports produce projected `cx` structures with per-surface quality markers (`faithful`, `approximated`, `preserved_only`) and preserved source evidence.

**Step 2: Run tests to verify they fail**

Run:

```bash
pytest \
  tests/test_cx_studio.py \
  tests/test_cx_roundtrip.py \
  tests/test_portability_reporting.py \
  tests/test_adk_importer.py \
  tests/test_adk_mapper.py \
  -q
```

Expected: failures because the `cx` editable contract and projection-quality reporting do not exist yet.

## Task 2: Implement the Typed CX-Native Workspace Contract

**Files:**
- Modify: `cx_studio/types.py`
- Modify: `adapters/cx_agent_mapper.py`
- Modify: `cx_studio/importer.py`
- Modify: `cx_studio/exporter.py`

**Step 1: Add the typed models**

- Introduce additive Pydantic models for editable CX-native structures and projection evidence.

**Step 2: Map real CX snapshots into the new contract**

- Build `config["cx"]` from imported snapshots.
- Populate legacy `prompts`, `routing`, `tools`, and `model` from the same source data.

**Step 3: Reverse-map `config["cx"]` back into `CxAgentSnapshot`**

- Honor edits for the writable/high-value subset:
  - playbook instructions
  - flow descriptions and transition routes
  - page routes/forms where available
  - intents/training phrases/parameters
  - entity types
  - generator prompts/model settings
  - webhook settings
- Preserve unsupported fields as raw evidence and do not silently drop them from reporting.

**Step 4: Re-run focused CX tests**

Run:

```bash
pytest tests/test_cx_studio.py tests/test_cx_roundtrip.py -q
```

Expected: real-CX mapper/import/export contract tests pass.

## Task 3: Strengthen ADK-to-CX Projection

**Files:**
- Modify: `adk/mapper.py`
- Modify: `adk/importer.py`
- Modify: `adk/portability.py`
- Modify: `adk/parser.py`

**Step 1: Project ADK agents into CX-native structures**

- Build projected playbooks from root/sub-agent instructions.
- Build projected flows/pages/routing groups from delegation structure and derived route intent groupings.
- Build projected intents and intent parameters from routing keywords/patterns and callback/tool usage hints where possible.
- Build projected generators from callback bindings when the mapping is meaningful; otherwise preserve callback evidence explicitly.

**Step 2: Attach projection quality and evidence**

- Mark direct mappings as `faithful`.
- Mark flattened or inferred CX-native structures as `approximated`.
- Mark source-only records with preserved raw evidence as `preserved_only`.

**Step 3: Preserve backward compatibility**

- Keep current generic AgentLab sections intact.
- Keep raw ADK tree metadata preserved for auditability.

**Step 4: Re-run focused ADK tests**

Run:

```bash
pytest tests/test_adk_importer.py tests/test_adk_mapper.py tests/test_portability_reporting.py -q
```

Expected: projected ADK imports now carry CX-native editable structures plus truthful quality reporting.

## Task 4: Extend Portability and Readiness Reporting

**Files:**
- Modify: `portability/types.py`
- Modify: `portability/reporting.py`
- Modify: `cx_studio/portability.py`
- Modify: `cx_studio/surface_inventory.py`
- Modify: `api/models.py`
- Modify: `api/routes/cx_studio.py`

**Step 1: Extend shared reporting**

- Add editable CX coverage counts and projection-quality counts.
- Expose faithful/approximated/preserved-only summaries alongside existing portability statuses.

**Step 2: Reclassify moved-forward CX surfaces**

- Update current surface rows for the newly editable/writable areas.
- Distinguish editable-but-lossy versus preserved-only.

**Step 3: Expose the richer report through API models**

- Keep response fields additive and backward compatible.

**Step 4: Run API-focused tests**

Run:

```bash
pytest tests/test_cx_studio_api.py tests/test_adk_api.py -q
```

Expected: API responses surface the richer CX-native coverage and projection quality metadata.

## Task 5: Broad Verification and Commit Readiness

**Files:**
- Modify: `task_plan.md`
- Modify: `findings.md`
- Modify: `progress.md`

**Step 1: Focused backend verification**

```bash
pytest \
  tests/test_cx_studio.py \
  tests/test_cx_roundtrip.py \
  tests/test_portability_reporting.py \
  tests/test_adk_importer.py \
  tests/test_adk_mapper.py \
  tests/test_adk_api.py \
  tests/test_cx_studio_api.py \
  -q
```

**Step 2: Broader stabilization slice**

```bash
pytest tests/test_adk_exporter.py tests/test_adk_parser.py tests/test_cx_studio_integration.py -q
```

**Step 3: Commit when reviewable**

- Capture exact command results in `progress.md`.
- Re-read the moved-forward vs still-blocked surface list before committing.
- Commit with a conventional-commit message once the branch is in a strong reviewable state.

## Risks to Watch

- Route-group and handler editing may be only partially pushable even after the new contract exists; keep those statuses explicit.
- ADK callback -> generator projection can easily overclaim fidelity; default to `approximated` or `preserved_only` unless the mapping is concrete.
- New `cx` config structures must not break existing generic optimization or config-loading flows.
- Surface inventory and readiness summaries must reflect actual mapper-plus-exporter behavior, not just theoretical target support.
