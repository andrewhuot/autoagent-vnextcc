# Findings & Decisions

## Requirements

- Review the in-progress diff before editing and preserve the branch intent.
- Finish the structured optimization surface coverage inventory.
- Expose the inventory from `GET /api/optimize/surfaces`.
- Make the inventory reflect real optimizer/component coverage, not placeholder filler.
- Align the audit artifact and findings with the implemented inventory.
- Run targeted verification for the touched area and commit only if those checks pass.

## Research Findings

- The worktree was already in progress when this pass began: `api/routes/optimize.py` and `findings.md` were modified, and `OPTIMIZATION_COMPONENTS_AUDIT.md`, `optimizer/surface_inventory.py`, and `tests/test_optimize_surface_inventory.py` were untracked. `uv.lock` was also untracked but appears unrelated to this audit slice.
- `GET /api/optimize/surfaces` is intentionally a read-only seam. The route in `api/routes/optimize.py` simply returns `build_surface_inventory()`, which keeps the API contract lightweight and deterministic.
- `optimizer/surface_inventory.py` is now the backend source of truth for this audit surface map. Each row carries:
  - `support_level`
  - declared mutation surfaces
  - default and experimental operator names
  - `optimization_paths`
  - `representation_paths`
  - explicit booleans for each live loop / import / export seam
  - notes for the important caveat on that surface
- The current inventory reports 18 surfaces in total:
  - 2 `full`
  - 8 `partial`
  - 7 `nominal`
  - 1 `none`
- Live coverage is computed from real codepaths instead of doc-only claims:
  - adaptive loop reachability comes from `optimizer.search._OPERATOR_TO_FAMILY`
  - opportunity reachability comes from `observer.opportunities._BUCKET_TO_OPERATORS`
  - NL-edit reachability comes from `optimizer.nl_editor.KEYWORD_SURFACE_MAP`
  - simple proposer and AutoFix reachability are normalized through the inventory metadata
- Tool runtime config needed a factual correction. ADK import and connected-runtime import both create tool config entries, but writeback is still incomplete, so that surface is `partial`, not absent.
- The biggest structural mismatch remains the same as the audit doc concludes: the mutation registry is broader than the live loop, and the live loop is broader than the canonical config and writeback contracts.

## Technical Decisions

| Decision | Rationale |
|----------|-----------|
| Keep one curated inventory module as the truth source for support tiers and notes | Support level is an editorial synthesis and should not be inferred from booleans alone |
| Compute operator/reachability evidence dynamically from live code | This keeps the inventory honest when search, opportunity mapping, or editor coverage changes |
| Preserve the route as a thin read-only wrapper over `build_surface_inventory()` | The endpoint should stay easy for UI, docs, and external coding agents to consume |
| Leave unrelated worktree changes out of scope | The request was specifically to button up the audit/inventory slice, not to churn dependencies or adjacent features |

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| The existing `findings.md` content was from a different verification pass and no longer matched this branch | Replaced it with branch-specific findings for the surface inventory work |
| Inventory facts were split across registry code, proposer/autofix heuristics, ADK mapper/exporter code, and connect adapters | Consolidated the branch conclusion in `optimizer/surface_inventory.py`, while still computing live path evidence from current code |
| `uv.lock` appeared in the worktree but is unrelated to this audit scope | Left it untouched and excluded from the commit scope |

## Resources

- `/Users/andrew/Desktop/AutoAgent-OptimizeAudit-Codex/api/routes/optimize.py`
- `/Users/andrew/Desktop/AutoAgent-OptimizeAudit-Codex/optimizer/surface_inventory.py`
- `/Users/andrew/Desktop/AutoAgent-OptimizeAudit-Codex/optimizer/search.py`
- `/Users/andrew/Desktop/AutoAgent-OptimizeAudit-Codex/optimizer/proposer.py`
- `/Users/andrew/Desktop/AutoAgent-OptimizeAudit-Codex/optimizer/autofix_proposers.py`
- `/Users/andrew/Desktop/AutoAgent-OptimizeAudit-Codex/optimizer/mutations.py`
- `/Users/andrew/Desktop/AutoAgent-OptimizeAudit-Codex/optimizer/mutations_topology.py`
- `/Users/andrew/Desktop/AutoAgent-OptimizeAudit-Codex/observer/opportunities.py`
- `/Users/andrew/Desktop/AutoAgent-OptimizeAudit-Codex/agent/config/schema.py`
- `/Users/andrew/Desktop/AutoAgent-OptimizeAudit-Codex/adk/mapper.py`
- `/Users/andrew/Desktop/AutoAgent-OptimizeAudit-Codex/adk/exporter.py`
- `/Users/andrew/Desktop/AutoAgent-OptimizeAudit-Codex/adapters/base.py`
- `/Users/andrew/Desktop/AutoAgent-OptimizeAudit-Codex/adapters/openai_agents.py`
- `/Users/andrew/Desktop/AutoAgent-OptimizeAudit-Codex/adapters/anthropic_claude.py`
- `/Users/andrew/Desktop/AutoAgent-OptimizeAudit-Codex/tests/test_optimize_surface_inventory.py`
- `/Users/andrew/Desktop/AutoAgent-OptimizeAudit-Codex/tests/test_adk_mapper.py`
- `/Users/andrew/Desktop/AutoAgent-OptimizeAudit-Codex/tests/test_adk_exporter.py`

## Verification Summary

- Ran `./.venv/bin/python -m pytest tests/test_optimize_surface_inventory.py`
  - Result: 2 tests passed
- Ran `./.venv/bin/python -m pytest tests/test_optimize_surface_inventory.py tests/test_adk_mapper.py tests/test_adk_exporter.py`
  - Result: 25 tests passed

## Remaining Gaps

- The inventory is now a reliable audit surface, but support tiers and notes are still curated judgments rather than a future component-graph-derived model.
- `GET /api/optimize/surfaces` is available for the backend, but the Studio / Inspector UI is not yet wired to consume it.
- Naming is still inconsistent across some existing codepaths, especially `generation`, `generation_settings`, and ADK `generate_config`.
