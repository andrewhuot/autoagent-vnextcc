# Findings & Decisions

## Requirements
- Build a shared, typed portability/readiness model for ADK and CXAS imports.
- Report imported, optimizable, read-only, unsupported, and exportable surfaces explicitly.
- Surface callbacks, graph topology, tool-code boundaries, and round-trip/export readiness.
- Preserve backward compatibility where practical.
- Add high-signal backend and API tests using realistic imported agents.

## Research Findings
- `adk/types.py` and `cx_studio/types.py` each define narrow `ImportResult` and `ExportResult` models today; neither carries a structured portability/readiness report.
- `adk/types.py` already models callback references on `AdkAgent`, but only as raw string fields and not as first-class import result metadata.
- `cx_studio/types.py` carries richer raw resource snapshots than ADK, which suggests a shared readiness model should allow per-platform evidence while staying generic.
- `api/models.py` is the central Pydantic contract file and will likely need additive models if route responses are upgraded.
- `adk/exporter.py` still operates on legacy keys like `instructions` and `generation_settings`, while `adk/importer.py` writes config with `prompts`, `generation`, `model`, and `tools`; the new reporting work should align these surfaces instead of hiding the mismatch.
- `cx_studio/exporter.py` has a concrete writable-field inventory in `_field_entries()` and `_apply_*()` methods, which can drive a truthful export capability matrix.
- `optimizer/surface_inventory.py` already defines which optimization surfaces are reachable, so importer-side readiness scoring can align to that vocabulary without inventing a separate surface taxonomy.
- `core/types.py` has a framework-neutral graph IR, but its node taxonomy is broader agent-system IR rather than import topology; a dedicated import topology model is likely cleaner than forcing flow/page/callback resources into unrelated node types.
- The shared portability package can stay framework-neutral and sit below API routes, which keeps ADK/CX layer boundaries intact while letting the API reuse the same report types directly.
- ADK import/export parity improves materially when exporter change detection accepts both the legacy keys (`instructions`, `generation_settings`) and the current importer keys (`prompts`, `generation`, `model`, `tools.*.description`).

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Favor a shared portability/readiness schema with source-specific evidence fields | The user requested a generic model reusable for ADK and CXAS. |
| Keep changes additive on import/export result types where possible | This preserves existing callers while allowing richer readiness reporting. |
| Treat export readiness as a first-class report derived from exporter reality | Customers need to know what can actually round-trip today, not what the platform might support eventually. |
| Use dedicated ADK and CX portability builder modules on top of shared report helpers | This keeps platform-specific topology and surface rules explicit while reusing scoring and matrix logic. |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| No prior session catchup data was emitted | Continued with a clean worktree and fresh discovery. |
| API route tests are environment-gated by `pytest.importorskip("fastapi")` | Ran them anyway as part of the focused suite; they were reported as skipped rather than silently omitted. |

## Resources
- `adk/types.py`
- `cx_studio/types.py`
- `api/models.py`
- `tests/test_adk_importer.py`
- `tests/test_adk_api.py`
- `tests/test_cx_studio.py`
- `tests/test_cx_studio_api.py`

## Visual/Browser Findings
- No browser or image inspection used for this task.
