# CLI Workbench Findings — Claude Opus

## Architecture Summary

The Workbench is AgentLab's inspectable agent-candidate building harness, bridging Build and Eval. It has three layers:

1. **Backend service** (`builder/workbench.py`): `WorkbenchStore` (JSON file persistence) + `WorkbenchService` (orchestration, streaming, validation, bridge)
2. **Bridge contracts** (`builder/workbench_bridge.py`): Typed Pydantic models for Workbench → Eval → Optimize handoff
3. **API routes** (`api/routes/workbench.py`): FastAPI SSE streaming endpoints that delegate to the service layer

The CLI (`runner.py`) currently has **zero workbench commands**. All other features (build, eval, optimize, deploy) use direct backend imports — no HTTP calls.

## Key Backend Contracts (Reusable As-Is)

### WorkbenchStore
- `create_project(brief, target, environment)` → project dict
- `get_default_project()` → newest project or starter
- `get_project(project_id)` → project or None
- `list_projects()` → list
- `save_project(project)` → atomic JSON write

### WorkbenchService
- **Sync**: `create_project`, `get_default_project`, `get_project`, `plan_change`, `apply_plan`, `run_test`, `rollback`, `get_plan_snapshot`, `cancel_run`, `generated_config_for_bridge`, `build_improvement_bridge_payload`
- **Async**: `run_build_stream(...)`, `run_iteration_stream(...)` — both return `AsyncIterator[dict]`

### Agent Factory
- `build_default_agent_with_readiness(force_mock=False)` → `(agent, execution_metadata)`
- Returns mock agent when no API keys configured, live agent otherwise

### Bridge Models
- `WorkbenchImprovementHandoff` with `candidate`, `evaluation`, `optimization` steps
- Evaluation readiness: blocked → needs_saved_config → ready
- Optimization readiness: blocked → needs_eval_candidate → awaiting_eval_run → ready

## CLI Patterns (Must Match)

| Pattern | Implementation |
|---------|---------------|
| Command groups | `@cli.group("name", cls=DefaultCommandGroup, default_command="run")` |
| External groups | Define in `cli/module.py`, import + `cli.add_command()` in runner.py |
| Output formats | `resolve_output_format(output_format, json_output=json_output)` → text/json/stream-json |
| JSON envelope | `render_json_envelope(status, data, next_command)` |
| Progress | `ProgressRenderer(output_format=fmt)` with `phase_started/phase_completed/next_action` |
| Workspace | `discover_workspace()` → `AgentLabWorkspace` or None |
| Errors | `click.ClickException(msg)` or `click_error(msg)` with doctor hint |
| Lazy imports | Backend services imported inside command function bodies |
| Visibility tiers | `PRIMARY_COMMANDS`, `SECONDARY_COMMANDS`, `HIDDEN_COMMANDS` sets |

## Streaming Challenge

`run_build_stream()` and `run_iteration_stream()` are async generators. The CLI is synchronous Click. Solution: `asyncio.run()` wrapping a drain loop inside each streaming command. No existing async patterns in runner.py, so this is new but minimal.

## State Machine

Build status: `idle → starting → queued → running ⟷ reflecting ⟷ presenting → done | error | cancelled`

Event stream (25+ types): `plan.ready`, `task.started`, `task.progress`, `task.completed`, `message.delta`, `artifact.updated`, `reflect.started`, `validation.ready`, `present.ready`, `run.completed`, `run.failed`, `harness.metrics`, `harness.heartbeat`

## Validation

`run_workbench_validation(project)` checks: canonical_model_present, exports_compile, target_compatibility, sample_message_recorded. Returns `{status: "passed"|"failed", checks: [...]}`.

## Risks

1. **Async in sync CLI**: First async pattern in runner.py. Must handle KeyboardInterrupt for graceful cancellation.
2. **Agent dependency**: Streaming requires `build_default_agent_with_readiness()` which auto-selects mock/live mode.
3. **Config materialization**: `persist_generated_config` requires workspace + deployer infrastructure. CLI export should use the same path.
4. **No existing CLI tests for workbench**: All workbench tests are API-level. Need new CLI-level tests.
