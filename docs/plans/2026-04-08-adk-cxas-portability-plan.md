# ADK and CXAS Portability Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a shared, typed portability/readiness report for ADK and CXAS imports and exports so customers can see exactly what was imported, what is optimizable, what is read-only or unsupported, what callbacks and topology were discovered, and what can safely round-trip back to production.

**Architecture:** Introduce a framework-neutral portability model that both ADK and CXAS can populate from their importer/exporter paths without leaking API-layer concerns downward. Keep existing result fields for backward compatibility, but extend import/export results with machine-readable coverage, callback, topology, readiness, and export capability data. Use importer-side evidence from parsed trees/snapshots plus exporter-side capability knowledge to compute explicit round-trip readiness instead of inferring from coarse `surfaces_mapped` lists.

**Tech Stack:** Python, Pydantic models, FastAPI routes, pytest.

---

## Current Architecture Snapshot

- `adk/parser.py` parses ADK source trees into `AdkAgentTree`, but callback extraction is limited and topology is implicit in nested sub-agents.
- `adk/mapper.py` maps ADK trees into AgentLab config dicts containing prompts/tools/routing/model/generation plus `_adk_metadata`.
- `adk/importer.py` writes YAML and snapshots, then returns a shallow `ImportResult`.
- `adk/exporter.py` computes limited diffs/write-back support for instruction/model/config/tool docstrings, but does not publish a capability matrix and still uses config keys inconsistent with current importer output.
- `cx_studio/importer.py` fetches a `CxAgentSnapshot`, materializes a workspace, and returns a shallow `ImportResult`.
- `adapters/cx_agent_mapper.py` carries most CX-to-AgentLab mapping logic, including flows/intents/webhooks/playbooks metadata.
- `cx_studio/exporter.py` already knows which CX resources are actually writable, which makes it a good source for export-capability reporting.
- `api/routes/adk.py` and `api/routes/cx_studio.py` define inline response models and expose only summary fields.
- Existing tests cover parser/import/export happy paths but do not prove portability/readiness reporting for realistic imports.

## Proposed Shared Model

Create a new framework-neutral portability module with:

- `PortabilitySurfaceStatus`: enum values for `optimizable`, `read_only`, `unsupported`.
- `ImportCoverageStatus`: enum values for `imported`, `partial`, `referenced`, `missing`.
- `ExportReadinessStatus`: enum values for `ready`, `lossy`, `blocked`.
- `PortabilitySurface`: one row per surface with source-specific evidence, rationale, and machine-readable flags.
- `ImportedCallback`: first-class callback records with lifecycle stage, source binding, optimization visibility, and export readiness.
- `ImportGraphNode` / `ImportGraphEdge` / `ImportTopology`: normalized graph representation and summary for imported agents.
- `OptimizationEligibilityScore`: numeric readiness score plus rationale and blockers.
- `ExportCapabilityMatrix`: per-surface round-trip status, aggregate readiness, and explicit blockers.
- `PortabilityReport`: top-level shared report embedded into both ADK and CXAS import/export results.

## Key Design Choices

- Keep existing `surfaces_mapped`, `tools_imported`, and `test_cases_imported` fields so current callers continue to work.
- Model callbacks and topology as explicit import surfaces instead of burying them in metadata.
- Use source-native evidence for each platform:
  - ADK: parsed tree, tool bodies/signatures, callback bindings, sub-agent hierarchy, agent type.
  - CXAS: snapshot playbooks/flows/pages/intents/webhooks/tools/entity types/test cases.
- Derive optimizer visibility from a stable mapping aligned with `optimizer/surface_inventory.py`, but do not couple importer code directly to UI-only route shapes.
- Report export limitations from exporter reality, not intention. ADK export should mark routing/topology/tool-code/callback changes as blocked or lossy when not actually writable today.

## Task 1: Shared Portability Models

**Files:**
- Create: `portability/__init__.py`
- Create: `portability/types.py`
- Modify: `adk/types.py`
- Modify: `cx_studio/types.py`
- Modify: `api/models.py`
- Test: `tests/test_adk_importer.py`
- Test: `tests/test_cx_studio.py`

**Step 1: Write the failing tests**

- Extend ADK and CX result-model tests to assert that import/export results can carry a shared portability report with coverage rows, readiness score, callback inventory, topology summary, and export matrix.

**Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_adk_importer.py tests/test_cx_studio.py -q
```

Expected: failures because the shared portability fields/types do not exist yet.

**Step 3: Write minimal implementation**

- Add shared Pydantic portability models.
- Extend ADK/CX type models and API models additively to reference the new report structures.

**Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_adk_importer.py tests/test_cx_studio.py -q
```

Expected: passing type/serialization coverage.

## Task 2: ADK Discovery and Reporting

**Files:**
- Modify: `adk/parser.py`
- Modify: `adk/mapper.py`
- Modify: `adk/importer.py`
- Modify: `adk/exporter.py`
- Modify: `adk/drift_detector.py`
- Test: `tests/test_adk_parser.py`
- Test: `tests/test_adk_importer.py`
- Test: `tests/test_adk_exporter.py`

**Step 1: Write the failing tests**

- Add realistic ADK import tests covering callback extraction, topology graph shape, per-surface coverage rows, readiness scoring rationale, and export capability reporting.
- Add exporter tests proving the ADK export report explicitly marks writable vs read-only vs blocked surfaces, and that current import-config keys still diff correctly.

**Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_adk_parser.py tests/test_adk_importer.py tests/test_adk_exporter.py -q
```

Expected: failures on missing callback/topology/reporting behavior.

**Step 3: Write minimal implementation**

- Expand ADK parser callback extraction to cover all known callback fields.
- Build ADK portability surfaces from parsed instructions, model, generation settings, tools, tool code boundary, routing/delegation, callbacks, and workflow topology.
- Emit a normalized topology graph and summary from `AdkAgentTree`.
- Compute an optimization eligibility score and export capability matrix from importer/exporter reality.
- Make `AdkExporter` understand current AgentLab config keys (`prompts`, `generation`, `model`, `tools`) while preserving older aliases when practical.

**Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_adk_parser.py tests/test_adk_importer.py tests/test_adk_exporter.py -q
```

Expected: all targeted ADK portability tests pass.

## Task 3: CXAS Discovery and Reporting

**Files:**
- Modify: `adapters/cx_agent_mapper.py`
- Modify: `cx_studio/importer.py`
- Modify: `cx_studio/exporter.py`
- Modify: `cx_studio/types.py`
- Test: `tests/test_cx_studio.py`
- Test: `tests/test_cx_roundtrip.py`

**Step 1: Write the failing tests**

- Add CX tests asserting import results expose a portability report with imported/optimizable/read-only/unsupported surface rows, topology summary over agent/playbooks/flows/pages/intents/webhooks/tools, and export capability reporting based on the actual writable CX resources.

**Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_cx_studio.py tests/test_cx_roundtrip.py -q
```

Expected: failures because the richer portability report is not yet populated.

**Step 3: Write minimal implementation**

- Build CX portability surfaces from playbooks/prompts, model, flows/pages routing, intents, entity types, webhooks, tools, test cases, and environments.
- Model callback visibility explicitly as unsupported or not present for CX imports unless mapped evidence exists.
- Derive a graph/topology summary from the CX snapshot and export capability matrix from `_field_entries` / `_apply_*` support.

**Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_cx_studio.py tests/test_cx_roundtrip.py -q
```

Expected: CX portability reporting passes targeted tests.

## Task 4: API Contract Exposure

**Files:**
- Modify: `api/routes/adk.py`
- Modify: `api/routes/cx_studio.py`
- Modify: `api/models.py`
- Test: `tests/test_adk_api.py`
- Test: `tests/test_cx_studio_api.py`

**Step 1: Write the failing tests**

- Extend API tests to assert portability reports are returned by ADK and CX import/export endpoints, including readiness score, topology summary, callback inventory, and export readiness fields.

**Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_adk_api.py tests/test_cx_studio_api.py -q
```

Expected: response-model or payload failures because routes currently omit the new fields.

**Step 3: Write minimal implementation**

- Replace or augment inline route models with shared API models.
- Return the new portability report additively from import/export endpoints.

**Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_adk_api.py tests/test_cx_studio_api.py -q
```

Expected: API contract tests pass.

## Task 5: Broader Verification and Drift Safety

**Files:**
- Modify: `task_plan.md`
- Modify: `findings.md`
- Modify: `progress.md`
- Test: `tests/test_adk_importer.py`
- Test: `tests/test_adk_parser.py`
- Test: `tests/test_adk_exporter.py`
- Test: `tests/test_adk_api.py`
- Test: `tests/test_cx_studio.py`
- Test: `tests/test_cx_roundtrip.py`
- Test: `tests/test_cx_studio_api.py`

**Step 1: Run the focused suite**

```bash
pytest \
  tests/test_adk_parser.py \
  tests/test_adk_importer.py \
  tests/test_adk_exporter.py \
  tests/test_adk_api.py \
  tests/test_cx_studio.py \
  tests/test_cx_roundtrip.py \
  tests/test_cx_studio_api.py \
  -q
```

**Step 2: If stable, run a slightly broader regression slice**

```bash
pytest tests/test_adk_integration.py tests/test_cx_studio_integration.py -q
```

**Step 3: Update planning files with outcomes and residual risk**

- Capture exact command results.
- Note any intentionally unimplemented export blockers.

## Risks to Watch

- `adk/exporter.py` currently expects legacy config key names, so importer/exporter contract alignment may expose latent bugs.
- `api/routes/adk.py` and `api/routes/cx_studio.py` define inline models today, so additive API-model refactoring may touch more than one response path.
- CXAS tools versus webhooks are not equally writable today; the export matrix needs to distinguish what is imported from what is actually pushable.
- Callback modeling must be explicit without implying unsupported write-back magically exists.
