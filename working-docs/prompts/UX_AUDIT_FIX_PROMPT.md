# UX Audit Fix — Master Prompt

Read `PM_QUICK_WINS.md` and `PM_UX_AUDIT_REPORT.md` in this repo. These contain 40 issues (UX-001 through UX-040) found by a PM audit.

## Your Mission

Fix ALL P0 and P1 issues (UX-001 through UX-029, plus items 1-14 from PM_QUICK_WINS.md). Use planning and sub-agents (Task tool) for parallelism. Group work into independent tracks:

### Track 1: ADK Integration Fixes (P0)
- **UX-001**: Fix ADK route implementation — use `parse_agent_directory` (not `AdkParser` class), `tree.agent` (not `tree.root`), fix exporter constructor
- **UX-002**: Normalize ADK deploy contract — align `agent_path`→`path`, `project_id`→`project`, `cloudrun`→`cloud-run` between frontend and API
- **UX-003**: Fix ADK status response — make API return `{ agent: {...} }` matching frontend expectations, or update frontend
- **UX-004**: Fix ADK diff schema — define stable `AdkDiffResponse` with `changes[]` + optional `diff` field
- **UX-018**: Fix ADK copy — "Google ADK" not "Anthropic ADK", Python structure not `agent.yaml`

### Track 2: CX Integration Fixes (P0)
- **UX-005**: Fix CX importer — pass `ref.name` string to `fetch_snapshot`, not `CxAgentRef` object
- **UX-006**: Fix CX exporter — convert typed objects to `(resource_name: str, updates: dict)` before calling client
- **UX-007**: Fix CX deployer — resolve resource names and configs before deploy/list calls

### Track 3: Frontend UX Fixes (P1)
- **UX-015**: Add CX pages to sidebar nav in an "Integrations" group
- **UX-016**: Complete page title map for ALL routes in Layout.tsx
- **UX-017**: Normalize ADK/CX pages to match app-wide light design (remove dark zinc)
- **UX-023**: Fix Opportunities summary counts — either fetch all statuses or relabel chips
- **UX-024**: Fix Dashboard metric semantics — distinct metrics for "Task Success" vs "Response Quality"
- **UX-026**: Fix Project Memory note input scoping — bind per-section, not global querySelector
- **UX-032**: Replace placeholder repo URL in Settings with real URL or remove block
- **UX-014**: Reorganize sidebar into grouped sections (Operate, Improve, Integrations, Governance)
- **UX-019**: Add global "Mock Mode" banner when running in mock mode
- **UX-022**: Add `source: mock|live` badges on experiment/archive data
- **UX-025**: Add progressive disclosure on Dashboard (simplified default view)

### Track 4: Backend/API Fixes (P1)
- **UX-020**: Label simulated SSE optimization stream as simulated
- **UX-021**: Gate quickfix behind feature flag or add mock labeling
- **UX-029**: Standardize missing-store behavior and error response envelope

### Track 5: Documentation Fixes (P1)
- **UX-008**: Rewrite CX guide from "future plan" to current-state + limitations
- **UX-009**: Regenerate CLI command table in README from actual runner commands
- **UX-010**: Update all stale counts in README (pages: 29, endpoints: 123, commands: 102)
- **UX-011**: Rewrite app guide for current 29-page IA
- **UX-012**: Expand CLI reference to cover all 102 command entries
- **UX-013**: Update API reference to match 123 implemented endpoints
- **UX-027**: Add MCP section to README + docs with stdio setup
- **UX-028**: Clarify stdio-only MCP support in docs and CLI help

## Execution Rules

1. **Use sub-agents** (Task tool) to parallelize independent tracks
2. **Run tests after each track** — `python -m pytest tests/ -x -q` (from project root)
3. **Do NOT break existing tests** — current count is 1,705. Final count must be >= 1,705
4. **Add new tests** for contract fixes (ADK/CX payload validation)
5. **Commit after each track** with conventional commit messages
6. **Final commit** should pass all tests

## Important Context
- Project is Python backend (FastAPI) + React/TypeScript frontend (Vite)
- Tests: `python -m pytest tests/ -q`
- Frontend: `web/src/` (React + TypeScript)
- Backend: `api/routes/`, `cx_studio/`, `adk/`, `agent/`, `optimizer/`, `observer/`, `evals/`, `registry/`
- CLI: `runner.py` (Click-based)
- Docs: `docs/`, `README.md`
- The real GitHub repo URL is: https://github.com/andrewhuot/autoagent-vnextcc

When completely finished, run: openclaw system event --text "Done: UX audit fixes — all P0/P1 issues from PM_UX_AUDIT_REPORT.md fixed across 5 tracks" --mode now
