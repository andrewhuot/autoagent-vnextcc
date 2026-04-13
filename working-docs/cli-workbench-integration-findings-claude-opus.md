# CLI Workbench Integration Findings — Claude Opus

Date: 2026-04-12
Branch: `feat/cli-workbench-integration-claude-opus`

## Source Branches

| Branch | Commit | Agent | Lines Added |
|--------|--------|-------|-------------|
| `feat/cli-workbench-codex` | 38455c7 | Codex | 1,423 |
| `feat/cli-workbench-claude-opus` | e37ae6c | Claude Opus | 1,471 |

Both branches diverge from master at `b4d8de2`. They are independent implementations with no cross-branch merge history.

## Codex Branch Analysis

### Strengths (Backbone)
- **Authoritative materialization**: `save` command uses `persist_generated_config()` which writes configs, updates workspace metadata, creates eval cases, and stores build artifact metadata. This is the same path the web UI uses.
- **Bridge-driven readiness**: All Eval/Optimize readiness comes from `WorkbenchImprovementHandoff` Pydantic contracts. Readiness states transition cleanly: `needs_materialization` → `ready_for_eval` → `awaiting_eval_run` → `ready_for_optimize`.
- **Rich JSON envelope**: Standard `api_version`/`status`/`data`/`next` shape with enriched agent card, bridge, next commands, and compact run.
- **PRIMARY_COMMANDS registration**: Workbench is part of the core loop — it belongs in the primary group.
- **Proven 4-test suite**: Build, show, save, iterate tests validate the full materialization lifecycle against real isolated workspaces.
- **Honest product semantics**: Text output explicitly says "Workbench structural validation is not an eval result" and "Eval still measures it afterward."

### Command Surface (6 commands)
`build`, `iterate`, `show`, `status`, `save`, `handoff`

### Weaknesses
- **No renderer split**: All rendering is inline in `workbench.py` (669 lines, mixed logic and presentation).
- **Limited event rendering**: Only handles 7 event types (`turn.started`, `plan.ready`, `task.started`, `artifact.updated`, `validation.ready`, `run.completed`, `run.failed`).
- **No graceful Ctrl+C**: `asyncio.run()` without KeyboardInterrupt handling.
- **No project lifecycle commands**: Cannot `create` standalone, `list` projects, `plan` changes, `apply` plans, `test` validation, `rollback` versions, or `cancel` runs.
- **No bare invocation routing**: `agentlab workbench` without a subcommand shows help, not status.

## Claude Branch Analysis

### Strengths (Port candidates)
- **Renderer split** (`cli/workbench_render.py`): 249 lines of pure rendering functions, cleanly decoupled from command logic. Handles 30+ event types with semantic coloring.
- **`_WorkbenchGroup` class**: Routes bare `agentlab workbench` to `status` subcommand — better terminal UX.
- **Broader command surface** (12 commands): `status`, `create`, `build`, `iterate`, `plan`, `apply`, `test`, `rollback`, `cancel`, `list`, `bridge`, `export`.
- **Graceful Ctrl+C**: KeyboardInterrupt caught outside `asyncio.run()`, attempts `cancel_run()`, exits with code 130.
- **Stronger event rendering**: `_EVENT_RENDERERS` dict maps 30+ event types to colored terminal lines, suppresses noise events (`message.delta`, `harness.heartbeat`, `harness.metrics`).
- **Contextual next-step guidance**: `_suggest_next_step()` adapts suggestions based on project state.
- **Comprehensive tests** (357 lines, 25+ test methods): Covers all 12 commands.

### Weaknesses
- **`export` command breaks materialization semantics**: Just writes YAML to disk without updating workspace metadata, eval cases, or build artifacts. Bypasses `persist_generated_config()`.
- **SECONDARY_COMMANDS registration**: Workbench belongs in PRIMARY per product docs.
- **Simpler JSON output for streaming**: `{"events": [...], "final": {...}}` envelope lacks the enriched agent card, bridge readiness, and next commands that Codex provides.
- **No `handoff` with `--save`**: Bridge inspection is read-only. Save + bridge display requires two commands.

## Integration Decisions

### What stays from Codex (Backbone)
1. **`save` command** with `persist_generated_config()` — authoritative materialization path
2. **PRIMARY_COMMANDS** registration
3. **`_build_summary()`** data builder with agent card, bridge, next commands, compact run
4. **`_materialize_candidate()`** orchestration for save
5. **Rich JSON envelope** structure for build/iterate/show/status/save
6. **`build` and `iterate`** streaming with Codex's `_consume_workbench_stream` pattern
7. **`show`** command for detailed candidate inspection
8. **Bridge readiness vocabulary** preserved exactly

### What is ported from Claude
1. **`cli/workbench_render.py`** renderer module — decouples rendering from logic
2. **`_WorkbenchGroup`** class — bare invocation routes to status
3. **`create`** command — standalone project creation (no conflict)
4. **`list`** command — multi-project listing (no conflict)
5. **`plan`** command — dry-run change planning (no conflict)
6. **`apply`** command — apply planned changes (no conflict)
7. **`test`** command — standalone validation (no conflict)
8. **`rollback`** command — version-based rollback (no conflict)
9. **`cancel`** command — run cancellation (no conflict)
10. **`bridge`** command — read-only eval/optimize readiness (replaces Codex `handoff` for read-only case)
11. **Graceful KeyboardInterrupt** handling for build/iterate
12. **30+ event type renderers** with semantic coloring

### What is deliberately left behind from Claude
1. **`export` command** — bypasses canonical materialization. Use `save` instead.
2. **SECONDARY_COMMANDS** registration — Workbench is PRIMARY.
3. **Simpler streaming JSON output** — Codex's enriched envelope is better for automation.

### What is dropped from Codex
1. **`handoff` command** — redundant. Read-only bridge inspection covered by `bridge` (from Claude). Save + display covered by `save` (Codex). Having both `handoff` and `bridge` creates confusion.
2. **Inline rendering** — moved to render module.

## Final Command Surface (13 commands)

| Command | Source | Purpose |
|---------|--------|---------|
| `status` (default) | Both | Compact readiness view |
| `create` | Claude | Create project from brief |
| `build` | Codex+Claude | Stream build with Ctrl+C |
| `iterate` | Codex+Claude | Follow-up turn |
| `show` | Codex | Detailed candidate inspection |
| `list` | Claude | List all projects |
| `plan` | Claude | Dry-run change planning |
| `apply` | Claude | Apply approved plan |
| `test` | Claude | Standalone validation |
| `rollback` | Claude | Version rollback |
| `cancel` | Claude | Cancel active run |
| `save` | Codex | Authoritative materialization |
| `bridge` | Claude | Eval/Optimize readiness |

## Risk Assessment

1. **Service method compatibility**: All 13 commands map to existing `WorkbenchService` methods. Verified: `create_project`, `plan_change`, `apply_plan`, `run_test`, `rollback`, `cancel_run`, `store.list_projects`, `build_improvement_bridge_payload`, `generated_config_for_bridge`, `run_build_stream`, `run_iteration_stream`, `get_plan_snapshot`, `get_default_project` all exist in `builder/workbench.py`.
2. **No duplicate paths**: `save` is the only materialization command. `export` is omitted. `bridge` is read-only.
3. **Test coverage**: Codex's 4 lifecycle tests validate save/handoff semantics. Claude's tests validate the broader surface. Combined suite covers all 13 commands.
