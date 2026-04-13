# CLI Workbench Integration Plan — Claude Opus

Date: 2026-04-12
Branch: `feat/cli-workbench-integration-claude-opus`
Base: `origin/master` @ `b4d8de2`

## Mission

Integrate the two parallel CLI Workbench branches into one coherent feature. Codex branch is the semantic backbone (save/materialization/handoff). Claude branch provides the stronger terminal UX and broader command surface.

## Strategy

1. Codex backbone: save/materialization semantics, PRIMARY_COMMANDS, bridge-driven readiness, enriched JSON envelopes
2. Claude ports: renderer split, _WorkbenchGroup bare routing, 7 additional commands, graceful Ctrl+C, 30+ event renderers
3. Drop: Claude's `export` (bypasses canonical materialization), Codex's `handoff` (redundant with `bridge` + `save`)
4. Result: ONE coherent CLI Workbench with 13 commands, no duplicate paths

## Integrated Command Tree

```
agentlab workbench                              # Default: show status
agentlab workbench status [--project-id ID] [-j]
agentlab workbench create "brief" [OPTIONS]
agentlab workbench build "brief" [OPTIONS]      # Streaming, Ctrl+C safe
agentlab workbench iterate "msg" [OPTIONS]      # Streaming, Ctrl+C safe
agentlab workbench show [--project-id ID] [-j]
agentlab workbench list [-j]
agentlab workbench plan "message" [OPTIONS]
agentlab workbench apply PLAN_ID [OPTIONS]
agentlab workbench test [OPTIONS]
agentlab workbench rollback VERSION [OPTIONS]
agentlab workbench cancel [RUN_ID] [OPTIONS]
agentlab workbench save [OPTIONS]               # Authoritative materialization
agentlab workbench bridge [OPTIONS]             # Read-only readiness
```

## Files to Create

### 1. `cli/workbench_render.py`
Claude's renderer module as base, enhanced with Codex rendering functions:
- `render_workbench_status(snapshot, verbose)` — from Claude (raw snapshot dashboard)
- `render_workbench_event(event_name, data)` — from Claude (30+ event types)
- `render_bridge_status(bridge)` — from Claude (readiness display)
- `render_project_list(projects)` — from Claude (project table)
- `render_validation(validation)` — from Claude (check results)
- `render_plan(plan)` — from Claude (plan summary)
- `render_candidate_summary(data, compact)` — adapted from Codex `_render_summary_text`
- `render_save_result(data)` — adapted from Codex `_render_save_text`

### 2. `cli/workbench.py`
Codex backbone + Claude commands:
- Codex data builders: `_build_summary`, `_agent_card`, `_compact_run`, `_extract_bridge`, `_next_commands`, `_terminal_status`
- Codex materialization: `_materialize_candidate` with `persist_generated_config`
- Codex streaming: `_consume_workbench_stream` + Claude Ctrl+C handling
- Claude `_WorkbenchGroup` for bare invocation routing
- 13 commands mapped to existing WorkbenchService methods

### 3. `tests/test_cli_workbench.py`
Combined test suite:
- Codex's 4 lifecycle tests (build/show/save/iterate) — validate authoritative semantics
- Claude-adapted tests for broader surface (create/list/plan/apply/test/rollback/cancel/bridge)
- Help and bare invocation tests

## Files to Modify

### 4. `runner.py`
- Add `from cli.workbench import workbench_group` to imports
- Add `"workbench"` to `PRIMARY_COMMANDS`
- Add `cli.add_command(workbench_group)`

### 5. Documentation
- `README.md` — add workbench to primary table + CLI Workbench section
- `docs/cli-reference.md` — add workbench primary command reference
- `docs/features/workbench.md` — add CLI workflow section
- `docs/platform-overview.md` — add workbench to primary list

## Implementation Order

1. `cli/workbench_render.py` — pure rendering, no dependencies
2. `cli/workbench.py` — commands calling real backend
3. `runner.py` — registration (3 lines)
4. `tests/test_cli_workbench.py` — verify everything works
5. Documentation updates
6. Test ladder verification
7. Commit and push

## Verification Plan

1. `uv run --extra dev python -m py_compile cli/workbench.py cli/workbench_render.py runner.py`
2. `uv run --extra dev python -m pytest tests/test_cli_workbench.py -q`
3. `uv run --extra dev python -m pytest tests/test_cli_workbench.py tests/test_workbench_eval_optimize_bridge.py tests/test_workbench_streaming.py tests/test_workbench_api.py tests/test_cli_progress.py tests/test_cli_commands.py -q`
4. `git diff --check`

## Decisions

| Decision | Rationale |
|----------|-----------|
| Codex save as authoritative materialization | Uses `persist_generated_config()` — same path as web UI, writes configs, eval cases, build artifacts |
| Drop Claude `export` | Bypasses workspace metadata and eval case generation. Confusing parallel path |
| Drop Codex `handoff` | Redundant: read-only mode = `bridge`, save mode = `save` |
| Port Claude `bridge` as read-only | Clean separation: `bridge` inspects, `save` materializes |
| PRIMARY_COMMANDS registration | Workbench is in the core loop (BUILD → WORKBENCH → EVAL) |
| Renderer module from Claude | 249 lines of clean separation, 30+ event types, testable |
| Bare invocation → status | `_WorkbenchGroup` from Claude. Better UX than showing help |
