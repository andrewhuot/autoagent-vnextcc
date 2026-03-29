# PM Quick Wins (P0/P1, Small Effort)

This list includes only **P0/P1** issues that are realistically **small effort** and high leverage.

## Sprint 0 (Must-do before external demos)

## 1) Fix ADK deploy request contract

- Priority: P0
- Problem: Web sends `agent_path`, `project_id`, `cloudrun|vertexai`; API expects `path`, `project`, `cloud-run|vertex-ai`.
- Evidence: `web/src/lib/api.ts:1615-1621`, `web/src/pages/AdkDeploy.tsx:9,26`, `api/routes/adk.py:38-43,120-127`
- Action:
  - Standardize to one schema across frontend/backend.
  - Add request model test.
- Success criteria: ADK deploy UI reaches API without 400 from enum/key mismatch.

## 2) Fix ADK status response shape mismatch

- Priority: P0
- Problem: UI expects `{ agent: ... }`, API returns flat fields.
- Evidence: `web/src/lib/api.ts:1587-1591`, `web/src/pages/AdkImport.tsx:107-111`, `api/routes/adk.py:50-56`
- Action:
  - Update API to return nested `agent`, or update UI/types to flat schema.
- Success criteria: ADK import preview renders agent name/model/tools/sub-agent counts correctly.

## 3) Fix ADK diff response/schema mismatch

- Priority: P0
- Problem: UI expects `diff` and file-based fields; API returns only `changes` with different keys.
- Evidence: `api/routes/adk.py:57-59,181-182`, `web/src/pages/AdkDeploy.tsx:154-166`
- Action:
  - Define stable `AdkDiffResponse` with explicit fields used by UI.
- Success criteria: diff preview renders meaningful change rows and optional diff text.

## 4) Fix CX importer client argument mismatch

- Priority: P0
- Problem: `CxImporter` passes `CxAgentRef` object to `fetch_snapshot` that expects a string resource name.
- Evidence: `cx_studio/importer.py:49`, `cx_studio/client.py:397-407`
- Action:
  - Pass `ref.name` into client methods.
- Success criteria: import call reaches CX API instead of failing on type mismatch.

## 5) Fix CX exporter client argument mismatch

- Priority: P0
- Problem: exporter passes typed objects/ref where client expects `(resource_name: str, updates: dict)`.
- Evidence: `cx_studio/exporter.py:69,79`, `cx_studio/client.py:218-227,257-268`
- Action:
  - Convert resource refs and payloads before calling `CxClient` patch methods.
- Success criteria: exporter performs patch requests without signature/runtime errors.

## 6) Correct ADK copy and prerequisites text

- Priority: P1
- Problem: ADK import page references “Anthropic ADK” and `agent.yaml`.
- Evidence: `web/src/pages/AdkImport.tsx:40,88`
- Action:
  - Update copy to “Google ADK” and Python structure expectations (`agent.py`, `__init__.py`).
- Success criteria: first-time ADK users get accurate setup guidance.

---

## Sprint 1 (High trust and discoverability gains)

## 7) Add CX pages to sidebar navigation

- Priority: P1
- Problem: `/cx/import` and `/cx/deploy` exist but are not directly navigable from sidebar.
- Evidence: `web/src/App.tsx:72-73`, `web/src/components/Sidebar.tsx:29-56`
- Action: add CX links in an “Integrations” nav group.
- Success criteria: CX journey reachable in one click from global nav.

## 8) Complete page title map

- Priority: P1
- Problem: many routes render generic “AutoAgent” title.
- Evidence: `web/src/components/Layout.tsx:9-33` vs app routes in `web/src/App.tsx:49-77`
- Action: extend `pageTitles` map to all routes.
- Success criteria: every page displays correct title in header.

## 9) Fix Opportunities summary count logic

- Priority: P1
- Problem: summary chips show in-progress/resolved counts while query only fetches `open`.
- Evidence: `web/src/pages/Opportunities.tsx:6,10-14`
- Action:
  - Either fetch all statuses for summary, or relabel to “open only”.
- Success criteria: summary chips reflect actual fetched data.

## 10) Fix Project Memory note input scoping

- Priority: P1
- Problem: add-note reads from global `querySelector`, risking wrong section capture.
- Evidence: `web/src/pages/ProjectMemory.tsx:143-147`
- Action:
  - Pass note value directly from section component callback.
- Success criteria: each note is reliably added to intended section.

## 11) Add MCP docs to README + docs/

- Priority: P1
- Problem: MCP command exists but no onboarding docs.
- Evidence: `runner.py:2296-2313`; no MCP entries in README/docs
- Action:
  - Add quickstart for stdio integration with Claude Code/Codex.
  - Explicitly state `--port` not yet supported.
- Success criteria: developer can connect MCP tools from docs alone.

## 12) Update stale counts and legacy command tables

- Priority: P1
- Problem: README and guides contain outdated counts and command names.
- Evidence: `README.md:759-777`, `README.md:783,811,949-951`, `docs/app-guide.md:29`
- Action:
  - Refresh numbers and examples from current code surface.
- Success criteria: docs match runtime surfaces and route names.

## 13) Flag simulated endpoints/flows clearly

- Priority: P1
- Problem: simulated outputs can be mistaken for live optimization.
- Evidence: `api/routes/optimize_stream.py:41-131`, `api/routes/quickfix.py:42-57`, `api/routes/experiments.py:61-115,128-135`
- Action:
  - Add `source: "mock"` metadata and UI badges.
- Success criteria: operator can always distinguish mock vs live data.

## 14) Replace placeholder repository link in Settings

- Priority: P1
- Problem: settings page links to placeholder repo URL.
- Evidence: `web/src/pages/Settings.tsx:106`
- Action: point to real repository or remove link block.
- Success criteria: all Settings external links are valid.

---

## Execution Order Recommendation

1. ADK/CX contract fixes (items 1-5)
2. Discoverability + correctness quick wins (items 7-10, 14)
3. Documentation and simulation clarity (items 11-13)
4. Copy cleanup (item 6)

---

## Suggested Owners

- Backend/API: items 1, 3, 4, 5, 13
- Frontend: items 2, 7, 8, 9, 10, 14
- Docs/PM: items 6, 11, 12

