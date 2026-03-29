# AutoAgent UX Audit Report

## Executive Summary (1 page)

AutoAgent VNextCC has substantial product depth and strong technical ambition, but the user experience is currently constrained by **integration breakpoints**, **documentation drift**, and **information architecture overload**.

The biggest finding is that the product presents itself as an integrated, end-to-end optimization platform across CLI, web UI, API, ADK, CX Agent Studio, and MCP workflows, yet these surfaces are not consistently wired together. In practice:

- The ADK and CX journeys have multiple contract mismatches between frontend, API, and integration modules that likely block real-world import/export/deploy flows.
- Documentation is materially out of sync with implementation (counts, endpoint names, command names, and integration status), creating avoidable onboarding confusion.
- Navigation and interaction patterns in the web app are dense and inconsistent (26 top-level sidebar items, partial page title mapping, mixed visual styles), increasing cognitive load for both new and daily users.

This is not a “small polish” gap. It is a **trust gap**: users cannot reliably infer what is production-ready vs prototype vs mock behavior.

### Overall Product UX Assessment

- Product maturity signal: **Medium-Low** (strong capability breadth, weak coherence).
- Discoverability: **Low for beginners**, **Medium for power users**.
- Journey completion confidence:
  - First-time user: Medium
  - Import existing agent (CX/ADK): Low
  - Daily operator loop: Medium
  - Power user advanced workflow: Medium-Low
  - VP demo: Medium
  - Developer MCP integration: Low
  - Team handoff continuity: Medium-Low

### Priority Themes

1. **Stabilize integration contracts first (P0)**: ADK/CX data contract and method signature mismatches.
2. **Restore source-of-truth docs (P1)**: README, CLI/API/app guides must match runtime reality.
3. **Reduce navigation and conceptual load (P1)**: group IA, tighten dashboard semantics, surface onboarding paths.
4. **Label simulation vs production behavior (P1)**: explicit mock/stub indicators in API/UI.
5. **Fix high-leverage paper cuts (P1/P2)**: wrong counts, missing titles, incorrect summary chips, placeholder links.

---

## Product Surface Inventory (what exists today)

### Quantitative Surface Map

- CLI surface (`runner.py`):
  - `85` command decorators (`@*.command`)
  - `17` group decorators (`@*.group`)
  - `102` total command/group entries
  - `181` options (`@click.option`)
  - `40` positional arguments (`@click.argument`)
- Web surface:
  - `29` page components (`web/src/pages/*.tsx`)
  - `38` reusable components (`web/src/components/*.tsx`)
  - `26` top-level sidebar navigation items
- API surface:
  - `29` route modules in `api/routes/`
  - `121` router endpoint decorators in route modules
  - `123` API endpoints when including app-level `/api/tasks` + `/api/tasks/{task_id}`
- Documentation:
  - `18` markdown docs in `docs/`
  - `41` command sections in `docs/cli-reference.md`
  - `76` endpoint rows in `docs/api-reference.md`
- Config/setup surface:
  - `10` user-visible config/memory files spanning `autoagent.yaml`, `AUTOAGENT.md`, `configs/*`, and `agent/config/*`

### Drift Between Product and Docs

- README still claims `19` pages and `75` endpoints (`README.md:783`, `README.md:811`, `README.md:949-951`), while implementation currently exposes `29` pages and `121+` route endpoints.
- `docs/app-guide.md` still describes only `9` pages (`docs/app-guide.md:29`).
- `docs/cli-reference.md` covers `41` commands, while code exposes `101+` entries from groups/commands.
- `docs/api-reference.md` includes multiple legacy path forms (`/{id}`, `/list`, `/api/deploy/deploy`) that do not match active route behavior.

### Concept Load (What a new user must internalize)

A user must currently reconcile:

- Multiple execution surfaces: CLI, web, API, MCP.
- Multiple integration domains: ADK, CX Agent Studio.
- Multiple operational modes: mock/simulated vs real provider-backed.
- Multiple state stores: conversation DB, memory DB, registry DB, traces/opportunities/experiments stores, config manifests.
- Multiple nomenclature layers: runs vs experiments vs change cards vs opportunities vs proposals.

Concept load is high and currently under-scaffolded.

---

## User Journey Analysis (journey-by-journey)

## 1) First-time user: Install -> first command -> quickstart -> explore results

### Typical path

1. Read README and run install commands.
2. Run `autoagent` / `autoagent --help` and inspect commands.
3. Run `autoagent init`, `eval run`, `optimize`, or `quickstart`.
4. Open web console and interpret dashboard.

### Friction points

- CLI is immediately broad (20+ top-level commands in help output) without progressive onboarding.
- `eval` group runs evaluation when invoked without subcommand (`runner.py:450-464`), which is surprising behavior for group commands.
- Default mock mode (`autoagent.yaml:2`) can produce successful-looking outputs that users may misread as production truth.
- README and docs contain stale command group references and inaccurate counts (`README.md:759-777`, `README.md:783-832`).
- Dashboard is information-dense for day-zero users (hard gates, cost controls, event timeline, control hatches all on first screen).

### Net result

Users can get to “something works” quickly, but confidence in what is real vs simulated is fragile.

---

## 2) Import existing agent: CX/ADK agent -> import -> first optimization

### Typical path

1. Discover integration pages/commands.
2. Provide source agent path/IDs and credentials.
3. Import into AutoAgent config.
4. Run optimization and export/deploy back.

### Friction points

- Discoverability: CX routes exist in app (`web/src/App.tsx:72-73`) but are not in sidebar nav (`web/src/components/Sidebar.tsx:29-56`).
- ADK page copy is misleading:
  - “Anthropic's Agent Developer Kit” (`web/src/pages/AdkImport.tsx:40`)
  - Expects `agent.yaml` (`web/src/pages/AdkImport.tsx:88`) while parser validates Python ADK structure (`adk/parser.py:35`, `adk/deployer.py:166-174`).
- ADK frontend/backend contracts are inconsistent:
  - `useAdkStatus` expects `{agent: ...}` (`web/src/lib/api.ts:1587-1591`) but API returns flat status object (`api/routes/adk.py:50-56`, `142-158`).
  - ADK deploy payload mismatch (`agent_path`, `project_id`, `cloudrun|vertexai`) vs API schema (`path`, `project`, `cloud-run|vertex-ai`) (`web/src/lib/api.ts:1615-1621`, `web/src/pages/AdkDeploy.tsx:9,26`, `api/routes/adk.py:38-43,120-127`).
  - ADK diff endpoint returns only `changes` (`api/routes/adk.py:57-59,181-182`), while UI expects `diff` and file-oriented fields (`web/src/lib/api.ts:1627`, `web/src/pages/AdkDeploy.tsx:154-166`).
- ADK route implementation mismatch:
  - Uses `AdkParser` class import (`api/routes/adk.py:68,93,146,170`) even though package exports `parse_agent_directory` function (`adk/__init__.py:32,45`).
  - Uses `AdkExporter(parser, mapper)` (`api/routes/adk.py:97,180`) while exporter constructor has no such params (`adk/exporter.py:23-25`).
  - Reads `tree.root` (`api/routes/adk.py:153-157`) although parsed tree model is `tree.agent` (`adk/types.py:48-55`).
- CX import/export/deploy backend signatures are inconsistent:
  - `CxImporter` passes `CxAgentRef` to `fetch_snapshot` expecting string name (`cx_studio/importer.py:49`, `cx_studio/client.py:397-407`).
  - `CxExporter` calls `update_agent(ref, updated_snapshot.agent)` and `update_playbook(ref, playbook)` (`cx_studio/exporter.py:69,79`) while client expects `(resource_name: str, updates: dict)` (`cx_studio/client.py:218-227,257-268`).
  - `CxDeployer` passes `ref` into client methods expecting names/config payloads (`cx_studio/deployer.py:35,78`, `cx_studio/client.py:355,371-390`).

### Net result

Import/export/deploy journey appears present in UI but is likely unreliable for real usage. This is the highest-risk product gap.

---

## 3) Daily operator: check status -> review failures -> apply fix -> deploy

### Typical path

1. Open Dashboard to assess health.
2. Investigate opportunities/failures.
3. Apply quick fix or AutoFix proposal.
4. Deploy candidate and watch canary.

### Friction points

- Dashboard metric semantics are inconsistent:
  - “Task Success” and “Response Quality” both read from `metrics.success_rate` (`web/src/pages/Dashboard.tsx:233-241`), blurring outcome dimensions.
- Dashboard mixes advanced controls into the default landing flow (pause/resume, pin/unpin, reject experiment, cost, timeline), increasing cognitive burden.
- Opportunity summary counts are misleading because data source is pre-filtered to open opportunities (`useOpportunities('open')`) yet UI displays in-progress/resolved counters (`web/src/pages/Opportunities.tsx:6,10-14`).
- Quick fix flow returns mock values (`api/routes/quickfix.py:42-57`) without clear product-level labeling.
- Deploy flow is solid structurally, but docs still refer to legacy deploy paths and canary commands, creating cross-surface confusion.

### Net result

Daily operation is workable for experienced users, but semantic clarity and confidence in “realness” of automated fixes are weak.

---

## 4) Power user: custom eval criteria -> advanced optimization -> skill creation -> deploy

### Typical path

1. Define custom scorers/eval dimensions.
2. Run optimize loops with deeper control.
3. Use registry/skills/runbooks.
4. Review and deploy.

### Friction points

- CLI docs underrepresent advanced surfaces (skill, review, demo, cx, adk, mcp-server, explain, diagnose, replay, etc.).
- Context CLI commands are partially placeholder/no-data outputs (`runner.py:1950-1956`), while web/API expose richer behavior.
- Naming inconsistencies across surfaces:
  - CLI `skill` vs API `/api/skills` vs web “Skills”
  - CLI `runbook` vs API `/api/runbooks`
  - CLI `review` vs web “Changes”
- Advanced features are discoverable but not staged; beginners and power users share the same dense IA.

### Net result

Power users can find depth, but orchestration requires tribal knowledge and cross-referencing code/docs.

---

## 5) VP demo: set up -> run demo -> show results -> answer questions

### Typical path

1. Run `autoagent demo quickstart` or `demo vp`.
2. Open web console to showcase score movement and operational controls.
3. Answer “how this works” and “is this production-ready?” questions.

### Friction points

- Demo UX depends on mixed truth sources (simulated vs live), but explicit provenance labeling is limited.
- Visual inconsistency reduces “product polish” signal:
  - Most app pages use light white/gray system, while ADK/CX pages are dark zinc blocks.
- Documentation figures and endpoint tables are visibly stale, undermining executive trust during diligence.

### Net result

Storytelling potential is high, but consistency and trust cues need tightening for VP/exec confidence.

---

## 6) Developer integration: connect Claude Code/Codex -> use MCP tools -> build agent

### Typical path

1. Search docs for MCP integration.
2. Start MCP server.
3. Connect coding agent client and call tools.

### Friction points

- No MCP documentation in README/docs despite runnable command (`runner.py:2296-2313`).
- `--port` path explicitly not implemented (`runner.py:2308-2310`) but no guide explains stdio-only setup.
- No quickstart snippets for Claude Code/Codex tool wiring, tool list, or sample flows.

### Net result

High-value integration exists in code but is effectively hidden for most developers.

---

## 7) Team handoff: one person sets up -> another takes over -> continuity

### Typical path

1. Person A initializes system and establishes workflows.
2. Person B takes over operational control.
3. Team continues safely with shared context.

### Friction points

- Project memory exists and is valuable, but note entry behavior is brittle:
  - Add-note handler uses global query selector and can capture the wrong field (`web/src/pages/ProjectMemory.tsx:143-147`).
- Settings contains placeholder repo URL (`web/src/pages/Settings.tsx:106`), reducing handoff reliability.
- Multiple env var naming schemes across modules (`AUTOAGENT_DB` vs `AUTOAGENT_DB_PATH` in `agent/server.py:99`) increase setup ambiguity.
- No dedicated “handoff checklist” or operator runbook surfaced in UI onboarding.

### Net result

Continuity is possible but not robustly productized.

---

## Issue Registry (every issue found, categorized and prioritized)

| ID | Priority | Category | Surface | Evidence | Journey Impact | Recommended Fix | Effort |
|---|---|---|---|---|---|---|---|
| UX-001 | P0 | Missing | ADK integration | `api/routes/adk.py:68,97,153`; `adk/__init__.py:32,45`; `adk/exporter.py:23`; `adk/types.py:51` | 2 | Align ADK route implementation with exported parser/type model (`parse_agent_directory`, `tree.agent`, exporter ctor) | Small-Medium |
| UX-002 | P0 | Inconsistency | ADK deploy contract | `web/src/lib/api.ts:1615-1621`; `web/src/pages/AdkDeploy.tsx:9,26`; `api/routes/adk.py:38-43,120-127` | 2 | Normalize request keys and target enum values across UI/API (`path/project`, `cloud-run/vertex-ai`) | Small |
| UX-003 | P0 | Inconsistency | ADK status contract | `web/src/lib/api.ts:1587-1591`; `web/src/pages/AdkImport.tsx:107-111`; `api/routes/adk.py:50-56` | 2 | Return consistent shape (either nested `agent` or flattened) and update UI accordingly | Small |
| UX-004 | P0 | Inconsistency | ADK diff contract | `api/routes/adk.py:57-59,181-182`; `web/src/pages/AdkDeploy.tsx:154-166` | 2 | Define stable diff schema (`changes[]`, optional unified `diff`) and update renderer fields | Small |
| UX-005 | P0 | Missing | CX importer runtime | `cx_studio/importer.py:49`; `cx_studio/client.py:397-407` | 2 | Pass `ref.name` into client fetch/list methods | Small |
| UX-006 | P0 | Inconsistency | CX exporter runtime | `cx_studio/exporter.py:69,79`; `cx_studio/client.py:218-227,257-268` | 2 | Convert typed snapshot changes into proper patch dicts with resource-name strings | Medium |
| UX-007 | P0 | Inconsistency | CX deployer runtime | `cx_studio/deployer.py:35,78`; `cx_studio/client.py:355,371-390` | 2 | Resolve environment resource names and version configs before deploy/list calls | Medium |
| UX-008 | P1 | Confusion | Docs integration status | `docs/cx-agent-studio.md:7-8` vs implemented `/api/cx` and CLI `cx` commands | 2,6 | Rewrite CX guide from “future plan” to current-state + known limitations | Small |
| UX-009 | P1 | Inconsistency | README command matrix | `README.md:759-777` (legacy commands) | 1,4,5 | Regenerate CLI table from runner metadata | Small |
| UX-010 | P1 | Inconsistency | README/API counts | `README.md:783,811,924,937,949-951` | 1,5 | Replace static counts with generated counts in docs build step | Small |
| UX-011 | P1 | Inconsistency | App guide stale IA | `docs/app-guide.md:29` (9 pages) vs 29 pages in app | 1,3 | Rewrite route map and workflows to current IA | Medium |
| UX-012 | P1 | Inconsistency | CLI reference coverage | `docs/cli-reference.md` has 41 sections vs ~101 command entries | 1,4 | Expand CLI reference to all groups/subcommands, incl. ADK/CX/MCP | Medium |
| UX-013 | P1 | Inconsistency | API reference drift | 76 documented vs 123 implemented; many legacy path patterns | 1,3,4 | Autogenerate API reference from OpenAPI schema | Medium |
| UX-014 | P1 | Complexity | Sidebar overload | `web/src/components/Sidebar.tsx:29-56` (26 top-level items) | 1,3,4 | Introduce grouped/collapsible IA and role-based defaults | Medium |
| UX-015 | P1 | Missing | CX discoverability | CX routes exist (`web/src/App.tsx:72-73`) but absent from sidebar | 2 | Add CX Import/Deploy entries and integration category | Small |
| UX-016 | P1 | Inconsistency | Page titles | `web/src/components/Layout.tsx:9-27` omits many routes | 1,3 | Add complete title map for all routes | Small |
| UX-017 | P1 | Inconsistency | Visual design language | Dark zinc ADK/CX pages vs light app-wide pattern (`AdkImport/AdkDeploy/Cx*`) | 2,5 | Refactor integration pages to shared design tokens/components | Medium |
| UX-018 | P1 | Confusion | ADK copy accuracy | `web/src/pages/AdkImport.tsx:40,88` | 2 | Correct copy to “Google ADK” and Python file-structure expectations | Small |
| UX-019 | P1 | Confusion | Mock mode default | `autoagent.yaml:2`; mock warnings only in some flows | 1,5 | Add global “Mock Mode ON” banner in UI and CLI header | Small |
| UX-020 | P1 | Confusion | Simulated SSE optimization | `api/routes/optimize_stream.py:41-131` | 3,5 | Label as simulated or wire to real task stream | Medium |
| UX-021 | P1 | Missing | Quickfix realism | `api/routes/quickfix.py:42-57` returns mock result | 3 | Gate endpoint behind feature flag or implement real flow + labeling | Medium |
| UX-022 | P1 | Inconsistency | Archive/calibration fallback | `api/routes/experiments.py:61-115,128-135` mock fallback | 3,4 | Add explicit `source: mock|live` in payload and UI badges | Small |
| UX-023 | P1 | Inconsistency | Opportunities summary counts | `web/src/pages/Opportunities.tsx:6,10-14` filtered data but multi-status chips | 3 | Fetch all-status summary or relabel chips to avoid false zeros | Small |
| UX-024 | P1 | Confusion | Dashboard metric semantics | `web/src/pages/Dashboard.tsx:233-241` same metric for success+quality | 3 | Source distinct quality metric or relabel card | Small |
| UX-025 | P1 | Complexity | Dashboard first-load density | `web/src/pages/Dashboard.tsx` (many advanced controls by default) | 1,3 | Progressive disclosure: Beginner/Operator mode toggle | Medium |
| UX-026 | P1 | Inconsistency | Project memory note targeting | `web/src/pages/ProjectMemory.tsx:143-147` global selector | 7 | Bind note input state per section and pass explicit value | Small |
| UX-027 | P1 | Missing | MCP onboarding docs | `runner.py:2296-2313`; no README/docs references | 6 | Add “Connect Claude Code/Codex” guide and examples | Small |
| UX-028 | P1 | Missing | MCP transport expectation | `runner.py:2308-2310` says HTTP/SSE not implemented | 6 | Clarify stdio-only support in docs and CLI help text | Small |
| UX-029 | P1 | Inconsistency | Error semantics across API | mix of `[]`, `{}`, mock fallback, `404`, `503` for missing stores | 3,4 | Standardize missing-store behavior and response envelope | Medium |
| UX-030 | P2 | Friction | `eval` group default execution | `runner.py:450-464` | 1 | Show help on bare `eval`; require explicit `eval run` | Small |
| UX-031 | P2 | Confusion | Context CLI placeholder output | `runner.py:1950-1956` | 4 | Indicate “no backend data” with actionable next command and links | Small |
| UX-032 | P2 | Inconsistency | Settings repository link placeholder | `web/src/pages/Settings.tsx:106-113` | 7 | Replace with real repo URL or remove block | Small |
| UX-033 | P2 | Inconsistency | API prefix style | `/api` root routes for diagnose/edit/quickfix vs grouped prefixes | 4 | Move to scoped prefixes (`/api/diagnose`, etc.) | Medium |
| UX-034 | P2 | Friction | Command palette coverage | `web/src/components/CommandPalette.tsx` static actions are narrow | 1,3,4 | Expand action coverage to top 10 user tasks + integrations | Small-Medium |
| UX-035 | P2 | Complexity | Config/setup naming spread | `AUTOAGENT_DB` vs `AUTOAGENT_DB_PATH` patterns across modules | 1,7 | Publish canonical env var matrix and deprecate aliases | Medium |
| UX-036 | P2 | Delight gap | No visible “what changed this week” summary | Distributed across events/changes/experiments | 3,5 | Add weekly digest card on dashboard | Medium |
| UX-037 | P2 | Missing | Integration auth guidance in UI | CX/ADK pages capture IDs but no inline credential setup guidance | 2 | Add credential help panel + link to docs | Small |
| UX-038 | P2 | Friction | Incomplete page-route breadcrumbs | only eval detail has breadcrumbs (`Layout.tsx:65-74`) | 3 | Add breadcrumb metadata per route | Medium |
| UX-039 | P3 | Inconsistency | Route naming singular/plural drift | `runbook` vs `/runbooks`, `skill` vs `/skills` | 4 | Decide canonical naming and alias legacy paths | Medium |
| UX-040 | P3 | Delight gap | No explicit success milestones for first run | First-time UX mostly raw outputs | 1 | Add setup completion checklist + celebratory milestone UI | Small-Medium |

---

## Recommendations (grouped by theme)

## Theme A: Stabilize Integration Reliability (P0)

1. Establish canonical contract definitions for ADK/CX request/response payloads and generate both frontend TypeScript and backend validators from a shared schema.
2. Add integration contract tests that exercise UI hook payloads against API route models and route models against integration module method signatures.
3. Add one smoke test per critical flow:
   - ADK status -> import -> deploy
   - CX list -> import -> deploy
4. Add explicit integration readiness badges in UI (experimental/beta/stable) until contracts are proven.

## Theme B: Rebuild Trust Through Accurate Documentation (P1)

1. Auto-generate CLI docs from Click command tree.
2. Auto-generate API docs from OpenAPI + route annotations.
3. Add doc lint checks in CI to prevent stale hardcoded counts.
4. Split “current behavior” and “future roadmap” docs clearly (especially CX and MCP).

## Theme C: Reduce Cognitive Load in Web Console (P1)

1. Reorganize sidebar into grouped sections:
   - Operate (Dashboard, Conversations, Deploy, Loop)
   - Improve (Eval, Optimize, Experiments, Opportunities, AutoFix)
   - Integrations (ADK, CX, MCP)
   - Governance (Changes, Runbooks, Skills, Memory, Settings)
2. Add beginner/operator/power-user display modes.
3. Fix incomplete page title map and strengthen route-level breadcrumbs.
4. Normalize visual design tokens across all pages (remove dark-zinc outliers).

## Theme D: Make Simulation Explicit (P1)

1. Add a unified runtime mode indicator (Mock/Live) in CLI and web headers.
2. Add `source` metadata on API responses where data may be mocked.
3. Show “simulated output” badges on Live Optimize and Quickfix-driven outcomes when applicable.

## Theme E: Tighten Daily Operator Feedback Loops (P1/P2)

1. Correct opportunity counts semantics and dashboard metric labeling.
2. Add lightweight post-action result summaries (what changed, confidence, next recommended action).
3. Add confirmation + impact preview for destructive controls (reject, rollback).

---

## Quick Wins (P0/P1 issues that are small effort)

1. Align ADK deploy payload names/enums between UI and API.
2. Fix ADK status response contract (nested vs flat shape) and corresponding UI render path.
3. Fix ADK diff schema mismatch (`diff`, `file` field assumptions).
4. Correct ADK copy (“Google ADK”, remove `agent.yaml` expectation).
5. Patch CX importer/exporter/deployer method argument mismatches.
6. Add CX routes to sidebar and update layout page title map for all routes.
7. Fix Opportunities summary counts logic.
8. Fix Project Memory note input scoping bug.
9. Add MCP section to README + docs with stdio setup examples.
10. Update README/docs stale counts and endpoint examples.
11. Mark simulated endpoints/flows clearly in API responses and UI.
12. Replace placeholder repository URL in Settings.

---

## Strategic Recommendations (larger changes)

1. **Contract-First Platform Layer**
   - Introduce shared schema package for CLI/API/web/integration models.
   - Enforce backward-compatible contract versioning.
2. **Persona-Based Product Shell**
   - Distinct onboarding path for first-time users.
   - Dedicated operator shell for daily runbook-style operations.
   - Advanced labs mode for power users and experimentation.
3. **Integration Reliability Program**
   - ADK/CX certification matrix with e2e fixture suites.
   - Integration health dashboard and release gates.
4. **Docs as Product**
   - Generated references + curated guides + examples by journey.
   - “Known limitations” section with concrete workaround matrix.

---

## Appendix: Command Reference Audit

### Command Coverage Snapshot

- Runtime command/group entries from `runner.py`: `102`
- Documented command sections in `docs/cli-reference.md`: `41`
- Underdocumented commands: ~`60` entries

### Notable Missing/Underdocumented Command Areas

- `adk`, `cx`, `mcp-server`, `review`, `memory`, `skill`, `demo`, `diagnose`, `explain`, `replay`, and subcommands.

### CLI Discoverability Observations

- Root help is comprehensive but dense.
- Some groups auto-execute when called bare (`eval`, `review`) while others show help, creating inconsistent mental models.
- Legacy hidden `run` group exists (`runner.py:2320`) and can create maintenance overhead.

---

## Appendix: Web Console Page-by-Page Review

### Core operations

- Dashboard: Rich and powerful; overloaded for first-run; metric semantics partially ambiguous.
- Eval Runs / Eval Detail: Strong structure and workflow continuity.
- Optimize / Live Optimize: Useful controls; live stream currently simulation-backed.
- Deploy: Good flow for canary/immediate with rollback visibility.
- Loop Monitor: Useful for continuous operation posture.

### Analysis and quality

- Conversations / Traces / Blame Map: Good depth for diagnosis.
- Opportunities: Prioritization useful; summary counts currently misleading.
- Experiments: Strong review model with archive/frontier overlays.
- AutoFix: Clean proposal/apply workflow; depends on backend realism signaling.
- Judge Ops / Context Workbench / Scorer Studio: Valuable advanced surfaces, but not progressively introduced.

### Governance and knowledge

- Change Review / Runbooks / Skills / Registry: Good governance primitives.
- Project Memory: Valuable for team continuity; note-input behavior bug reduces trust.
- Settings: Helpful reference; includes placeholder repo URL.

### Integrations

- ADK Import/Deploy: UI exists, but contract/copy mismatches degrade reliability.
- CX Import/Deploy: UI exists, but discoverability and backend method mismatches degrade reliability.

### UX system consistency

- Most pages follow light neutral design system.
- Integration pages use older dark-zinc styling, creating visual discontinuity.

---

## Appendix: API Consistency Audit

### Inventory and Coverage

- Implemented API endpoints: `123` (including app-level task endpoints)
- Documented API endpoints in `docs/api-reference.md`: `76`
- Implemented but undocumented: `71`
- Documented but mismatched/legacy: `24`

### Consistency Findings

1. Path parameter naming drift (`{id}` vs `{run_id}` / `{trace_id}` / `{experiment_id}`).
2. List endpoint naming drift (`/list` legacy docs vs collection root routes).
3. Deploy path docs still show `/api/deploy/deploy` while route is `POST /api/deploy`.
4. Mixed missing-store behavior:
   - some endpoints return `[]`
   - some return mock payloads
   - some return `404`/`503`
5. Mixed route scoping:
   - most under scoped prefixes (`/api/<domain>`)
   - diagnose/edit/quickfix mounted directly under `/api`.

### Error Contract Assessment

- Predominant error shape is FastAPI `{"detail": ...}`.
- Internal integration routes often convert broad exceptions to `502` with raw string detail (`api/routes/adk.py`, `api/routes/cx_studio.py`), which is useful for debugging but inconsistent for product UX and localization.

### Recommendation

Adopt a normalized API envelope for both success and failure on user-facing routes, with explicit fields such as:

- `status`: `ok|error`
- `source`: `live|mock`
- `message`: user-safe summary
- `detail_code`: stable machine-readable code
- `debug`: optional only in development mode

---

## Closing Note

AutoAgent already has the ingredients of a high-trust operator platform: strong loop concepts, real governance primitives, and rich observability surfaces. The next leverage point is not adding more features; it is **making existing features dependable, coherent, and legible across CLI, web, API, docs, and integrations**.
