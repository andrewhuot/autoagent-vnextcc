# AgentLab Port of AutoAgent Landings

Date: 2026-04-14
Branch: `integrate/2026-04-14-port-autoagent-landings`
Starting HEAD: `50694c0` (master)

## Starting State

- AgentLab master at `50694c0`, 4 commits ahead of origin
- Already landed: structured terminal renderer (8a7), Claude Code parity (e790), coordinator-worker planning (dc9)
- One untracked file: `working-docs/reviews/2026-04-14-sequential-merge-integration.md`

## Source Commits Inspected

### Source Landing A — Harness Readiness (b150ff3 via 296fd83)
- Branch: `feat/harness-engineering-cli-codex-yolo`
- Key capability: operator-facing harness status/readiness surface for long-running loop work
- Files: `cli/harness_status.py`, `cli/progress.py`, `cli/status.py`, `runner.py`, tests

### Source Landing B — Context Engineering (dd5a81a via 24a6c95)
- Branch: `feat/context-engineering-pro-codex-yolo`
- Key capability: context profile selection, assembly preview, diagnostics, and context workbench UI upgrade
- Files: `context/engineering.py`, `api/routes/context.py`, `runner.py`, web/src/, tests

## AgentLab Mapping

| Source Feature | Source File | AgentLab Destination | Port Strategy |
|---|---|---|---|
| Harness status collector | `cli/harness_status.py` | `cli/harness_status.py` | Direct port (same product model) |
| Progress checkpoint/recovery events | `cli/progress.py` | `cli/progress.py` | Direct port |
| Status harness fields | `cli/status.py` | `cli/status.py` | Direct port |
| `agentlab harness` command group | `runner.py` | `runner.py` | Direct port |
| Status/doctor harness integration | `runner.py` | `runner.py` | Direct port |
| Loop budget JSON fix | `runner.py` | `runner.py` | Direct port |
| Loop checkpoint/recovery_hint events | `runner.py` | `runner.py` | Direct port |
| Workspace-scoped _control_store | `runner.py` | `runner.py` | Direct port |
| Context engineering module | `context/engineering.py` | `context/engineering.py` | Direct port |
| Context profiles/preview API | `api/routes/context.py` | `api/routes/context.py` | Direct port |
| Context CLI commands | `runner.py` | `runner.py` | Direct port |
| `get_events` → `get_trace` fix | `api/routes/context.py` | `api/routes/context.py` | Direct port |
| Strategy string alias support | `api/routes/context.py` | `api/routes/context.py` | Direct port |
| Command visibility: harness + context | `runner.py` | `runner.py` | Direct port |
| Harness status tests | `tests/test_cli_harness_status.py` | Same | Direct port |
| Context engineering tests | `tests/test_context_engineering.py` | Same | Direct port |
| Progress lifecycle tests | `tests/test_cli_progress.py` | Same | Direct port (additive) |
| Runner context CLI tests | `tests/test_runner.py` | Same | Direct port (additive) |

## What Was Ported

### From b150 (Harness Readiness)
1. **`cli/harness_status.py`** — Full HarnessStatusSnapshot model with health/loop/checkpoint/dead-letter/control/evidence collection and rendering
2. **`cli/progress.py`** — `checkpoint()` and `recovery_hint()` event methods with text rendering
3. **`cli/status.py`** — `harness_label`, `harness_recovery_label`, `harness_evidence_label` fields with verbose output
4. **`runner.py`** — `agentlab harness status` command group; harness data in `agentlab status` (JSON + text); harness readiness in `agentlab doctor` (JSON + text); loop budget JSON/stream-json fix; checkpoint + recovery_hint events in loop; workspace-scoped `_control_store()`
5. **`harness` added to SECONDARY_COMMANDS** so it appears in help
6. **11 focused tests** covering JSON/text output, recovery state, fresh/stale checkpoints, status verbose, doctor JSON, loop stream-json, budget rejection, nested workspace resume

### From dd5 (Context Engineering)
1. **`context/engineering.py`** — Full context profile/component/diagnostic/assembly-preview model with profile presets (lean/balanced/deep), offline token estimation, workspace config loading, context diagnostics (budget, instruction hierarchy, compaction, memory, shape)
2. **`context/__init__.py`** — Updated exports
3. **`api/routes/context.py`** — `GET /api/context/profiles` and `POST /api/context/preview` endpoints; `get_events` → `get_trace` fix; strategy string alias support in simulate endpoint
4. **`runner.py`** — `agentlab context profiles` and `agentlab context preview` CLI commands; `context` moved from HIDDEN_COMMANDS to SECONDARY_COMMANDS
5. **4 focused tests** covering build_context_preview, over-budget diagnostics, profiles API, preview API

## What Was Intentionally Not Ported

1. **AutoAgent README changes** — Not applicable to AgentLab's README
2. **AutoAgent docs changes** (cli-reference.md, UI_QUICKSTART_GUIDE.md, api-reference.md, app-guide.md, features/context-workbench.md, platform-overview.md) — These reference AutoAgent-specific docs/surfaces
3. **AutoAgent findings.md** — Analysis notes belong in the source repo
4. **AutoAgent working-docs analysis reports** — Source-specific analysis docs
5. **Web frontend UI changes** (ContextWorkbench.tsx, api.ts types/hooks, types.ts, navigation.ts) — These require deep integration with AgentLab's web UI which differs from AutoAgent's. The API endpoints are in place; web integration can follow in a dedicated UI pass.
6. **provider-fallback.test.ts whitespace fix** — Trivial unrelated cleanup

## Conflicts/Fit Issues

- No conflicts with existing AgentLab commits (8a7, e790, dc9)
- Harness status module cleanly integrates with existing `optimizer/reliability.py` and `optimizer/human_control.py`
- Context engineering module cleanly extends existing `context/` package
- `DefaultCommandGroup` already available in runner.py from prior work

## Test Ladder and Outcomes

### Focused Tests (all new)
- `test_cli_progress.py` — 3 passed (including new harness lifecycle events)
- `test_cli_harness_status.py` — 11 passed
- `test_context_engineering.py` — 4 passed
- `test_runner.py` — 13 passed (including new context profiles/preview tests)

### Related Suite
- `test_cli_commands.py` — 48 passed, 1 failed (pre-existing: `test_doctor_reports_runtime_provider_ready_without_provider_registry` — confirmed failing before our changes)
- `test_context.py` — passed (broader context module tests)

### Quality Gates
- `git diff --check` — clean
- No whitespace issues
- Clean git status showing only intended changes

## Broader Test Suite

Awaiting full `tests/` run results (documented below when complete).

## Files Changed in AgentLab

### New Files
- `cli/harness_status.py` — Harness lifecycle status collector and renderer
- `context/engineering.py` — Context profile, assembly preview, and diagnostics model
- `tests/test_cli_harness_status.py` — 11 harness status tests
- `tests/test_context_engineering.py` — 4 context engineering tests

### Modified Files
- `api/routes/context.py` — Added profiles/preview endpoints, fixed get_events→get_trace, added strategy aliases
- `cli/progress.py` — Added checkpoint() and recovery_hint() event methods
- `cli/status.py` — Added harness_label/recovery_label/evidence_label fields
- `context/__init__.py` — Updated exports for engineering module
- `runner.py` — Added harness command group, context profiles/preview commands, harness integration in status/doctor, loop checkpoint/recovery events, budget JSON fix, workspace-scoped control store
- `tests/test_cli_progress.py` — Added harness lifecycle event test
- `tests/test_runner.py` — Added context profiles/preview tests

## Whether Local AgentLab Master Was Updated

Pending verification of broader test suite results.

## AutoAgent Confirmation

AutoAgent (`/Users/andrew/Desktop/AutoAgent-VNextCC-Codex-P0`) was treated as read-only source material. No modifications were made.

## Residual Risks / Follow-Up

1. **Web UI integration deferred** — The API endpoints for profiles and preview are in place, but ContextWorkbench.tsx, api.ts, and types.ts updates from dd5 were not ported. A dedicated UI pass should add profile selection and assembly preview to the context workbench page.
2. **Pre-existing test failure** — `test_doctor_reports_runtime_provider_ready_without_provider_registry` was already failing; should be investigated separately.
3. **Doc updates deferred** — AgentLab-specific documentation for the harness command and context profiles/preview commands should be added in a follow-up.
