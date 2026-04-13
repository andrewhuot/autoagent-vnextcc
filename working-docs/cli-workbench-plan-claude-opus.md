# CLI Workbench Implementation Plan — Claude Opus

## Command Tree

```
agentlab workbench                              # Default: show status
agentlab workbench status [--project ID] [-j]   # Project snapshot
agentlab workbench create "brief" [OPTIONS]     # Create project from brief
agentlab workbench build "brief" [OPTIONS]      # Stream a build run
agentlab workbench iterate "msg" [OPTIONS]      # Follow-up iteration
agentlab workbench plan "message" [OPTIONS]     # Plan without executing
agentlab workbench apply PLAN_ID [OPTIONS]      # Apply approved plan
agentlab workbench test [OPTIONS]               # Run validation
agentlab workbench rollback VERSION [OPTIONS]   # Revert to prior version
agentlab workbench cancel [RUN_ID] [OPTIONS]    # Cancel active run
agentlab workbench list [-j]                    # List all projects
agentlab workbench bridge [OPTIONS]             # Eval/Optimize handoff readiness
agentlab workbench export [--output PATH]       # Write candidate config to disk
```

## Files to Create

### 1. `cli/workbench_render.py`
Terminal rendering helpers for workbench state and streaming events.
- `render_workbench_status(snapshot, verbose=False)` — text dashboard
- `render_workbench_event(event_name, data)` — single SSE event to text line
- `render_bridge_status(bridge)` — eval/optimize readiness
- `render_project_list(projects)` — table of projects
- `render_validation(validation)` — check results

### 2. `cli/workbench.py`
Click command group with all subcommands. Pattern: define group + commands, export `workbench_group`.
- `_workbench_service()` — lazy factory: WorkbenchStore + WorkbenchService
- `_resolve_project_id(service, project_id)` — default project fallback
- All 12 subcommands listed above
- Streaming commands use `asyncio.run()` to drain async iterators

### 3. `tests/test_workbench_cli.py`
CliRunner tests with isolated_filesystem. Tests for: create, status, plan, apply, test, rollback, list, cancel, bridge, build (mock mode), iterate (mock mode).

## Files to Modify

### 4. `runner.py`
- Add `from cli.workbench import workbench_group` to imports (~line 100)
- Add `cli.add_command(workbench_group)` (~line 1858)
- Add `"workbench"` to `SECONDARY_COMMANDS` set (line 174)

### 5. `docs/cli-reference.md`
- Add workbench command section to Secondary Commands

## Implementation Order

1. `cli/workbench_render.py` — pure functions, no dependencies on Click
2. `cli/workbench.py` — commands calling real backend services
3. `runner.py` — registration (3 lines)
4. `tests/test_workbench_cli.py` — verify commands work
5. `docs/cli-reference.md` — document new commands

## Command-to-Service Mapping

| Command | Service Method | Sync/Async |
|---------|---------------|------------|
| status | get_plan_snapshot / get_default_project | sync |
| create | create_project | sync |
| build | run_build_stream | async |
| iterate | run_iteration_stream | async |
| plan | plan_change | sync |
| apply | apply_plan | sync |
| test | run_test | sync |
| rollback | rollback | sync |
| cancel | cancel_run | sync |
| list | store.list_projects | sync |
| bridge | build_improvement_bridge_payload | sync |
| export | generated_config_for_bridge | sync |

## Streaming Design

```python
async def _drain_stream(stream_coro, on_event, on_complete):
    stream = await stream_coro
    last = None
    async for event in stream:
        on_event(event)
        last = event
    on_complete(last)

asyncio.run(_drain_stream(...))
```

KeyboardInterrupt caught outside asyncio.run(), triggers cancel_run().

## Risk Mitigation

1. Mock mode always available — no API keys needed for testing
2. All sync commands tested with CliRunner + isolated_filesystem
3. Streaming tested with force_mock=True for deterministic events
4. Bridge tested by creating project + applying plan + checking readiness
