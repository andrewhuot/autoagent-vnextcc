# P0 Workspace State Validation Plan - Codex

## Mission

Make workspace/server state explicit. AgentLab should no longer let a server started from the wrong directory quietly create or use ambient state that looks like a real workspace. The backend should compute workspace validity at startup, health endpoints should expose that state, and the UI should show a blocking or unmistakable recovery path when the workspace is invalid.

## Audit Source Inputs

- `repo-audit-exec-summary-claude-sonnet.md` identifies "Server CWD as invisible dependency" as a core architecture risk: build, optimize, and deploy fail silently if the server is not started from a workspace directory.
- `repo-product-and-codebase-recommendations-opus.md` marks this as P0 item 2.6: validate CWD at startup, expose `workspace_valid` and path in health, and show a UI banner with recovery instructions. It also names long-term `--workspace /path` support as the way to reduce implicit CWD dependence.

## Current Failure Mode

The FastAPI lifespan in `api/server.py` initializes stores from relative paths such as `conversations.db`, `configs`, `.agentlab/traces.db`, `.agentlab/core_skills.db`, and `.agentlab/builder.db`. Those paths resolve against whatever CWD `uvicorn` inherited. If the user runs `agentlab server` from a non-workspace directory, startup succeeds and state is created or read from that non-workspace location. Later build, config, optimize, deploy, and health surfaces have no shared explanation for why no valid agent workspace is active.

The CLI already has workspace discovery primitives in `cli/workspace.py`, including `discover_workspace()` and `AgentLabWorkspace.resolve_active_config()`, but the server command does not require, prefer, or surface a workspace before invoking `uvicorn.run("api.server:app", ...)`.

## Selected Coherent Slice

I will implement an explicit degraded-mode slice rather than a hard startup refusal. That is the strongest coherent slice for this codebase because existing tests and development flows start the API from temporary directories. Degraded mode makes the invalid state impossible to miss while preserving enough server availability for the UI to display recovery instructions.

The slice:

1. Add a workspace-state resolver that prefers an explicit `AGENTLAB_WORKSPACE` path, then falls back to discovery from process CWD.
2. Treat a workspace as valid only when discovery succeeds and an active config can be resolved.
3. Attach the resolved state to `app.state` at startup before store construction.
4. When valid, scope relative server paths to the workspace root by changing process CWD once at lifespan startup before stores are constructed. This reduces ambient CWD dependence for the existing relative-path-heavy initialization path without rewriting every store in this pass.
5. Expose the workspace state on `/api/health`, `/api/health/ready`, and `/api/health/system`.
6. Add `agentlab server --workspace PATH` so users can start the server from anywhere while explicitly selecting a workspace.
7. Add a shell-level UI banner that blocks or very visibly warns when `workspace.valid === false`, with concrete recovery commands.

## Data Contract

Workspace state payload:

```json
{
  "valid": false,
  "current_path": "/path/server-started-from",
  "workspace_root": null,
  "workspace_label": null,
  "active_config_path": null,
  "active_config_version": null,
  "source": "cwd",
  "message": "No AgentLab workspace found...",
  "recovery_commands": [
    "cd /path/to/your/agentlab-workspace && agentlab server",
    "agentlab server --workspace /path/to/your/agentlab-workspace",
    "agentlab init --dir /path/to/new-workspace"
  ]
}
```

For a discovered workspace with missing configs, `valid` remains false but `workspace_root` and `workspace_label` are populated. The message should tell the user to create or activate a config rather than implying the directory is unknown.

## Test Plan - Red First

### Backend Resolver Tests

File: `tests/test_workspace_state.py`

- `test_workspace_state_is_invalid_without_workspace`: in an isolated temp directory with no `.agentlab`, resolver returns `valid=False`, includes `current_path`, no `workspace_root`, and recovery commands.
- `test_workspace_state_is_invalid_when_workspace_has_no_active_config`: create `.agentlab/workspace.json` but no config files; resolver returns the workspace root with `valid=False`.
- `test_workspace_state_is_valid_for_initialized_workspace`: create a minimal `AgentLabWorkspace`, config, and metadata; resolver returns `valid=True`, active config path/version, and label.
- `test_explicit_workspace_path_is_preferred_over_cwd`: run from a non-workspace directory with `AGENTLAB_WORKSPACE` pointing at a valid workspace; resolver reports `source="env"` and the explicit root.

### API/Startup Tests

File: `tests/test_api_server_startup.py` or `tests/test_health_workspace_state.py`

- Existing startup test should continue to start from a non-workspace temp directory but now assert explicit invalid workspace state instead of silent ambiguity.
- `/api/health/ready` returns `workspace.valid=false` from precomputed state.
- `/api/health/system` includes the same workspace payload and returns `status="degraded"` when workspace state is invalid.
- `/api/health` includes workspace payload because existing frontend shell code already polls this endpoint.

### CLI Tests

File: `tests/test_cli_commands.py`

- `agentlab server --workspace <valid-workspace>` sets `AGENTLAB_WORKSPACE`, prints the selected workspace, and calls `uvicorn.run`.
- `agentlab server --workspace <missing-path>` exits with a helpful Click error before calling uvicorn.

### Frontend Tests

File: `web/src/components/MockModeBanner.test.tsx` or a new `WorkspaceStateBanner.test.tsx`

- When `/api/health` returns `workspace.valid=false`, the shell shows "Workspace needs attention" with the invalid/current path and both `cd ... && agentlab server` and `agentlab server --workspace ...` guidance.
- Invalid workspace warnings are not dismissible.
- Valid workspace state does not render the workspace banner.
- Preview/mock banner behavior still works for valid workspace health payloads.

## Implementation Steps

1. Create the resolver/model layer:
   - Add `api/workspace_state.py`.
   - Add `WorkspaceStateResponse` to `api/models.py`.
2. Add startup wiring:
   - Resolve workspace state at the top of `api.server.lifespan()`.
   - Attach `app.state.workspace_state`.
   - If valid, `os.chdir(workspace_root)` before loading runtime and stores.
3. Add health fields:
   - Include workspace state in `HealthResponse` and `SystemHealthResponse`.
   - Include workspace state in readiness response without database queries.
4. Add CLI explicit workspace:
   - Add `--workspace` option to `runner.py server`.
   - Validate path and set `AGENTLAB_WORKSPACE` before `uvicorn.run`.
5. Add frontend contract:
   - Extend `HealthReport` type with workspace state.
   - Add a dedicated shell banner component or extend the existing health banner.
   - Keep workspace invalid state higher priority than mock/preview state.
6. Run targeted tests and fix.
7. Run a user-facing recovery-flow check with mocked health and, if feasible, a local backend health probe.

## Validation Commands

Backend targeted:

```bash
.venv/bin/python -m pytest tests/test_workspace_state.py tests/test_api_server_startup.py tests/test_cli_commands.py -q
```

Frontend targeted:

```bash
cd web && npm run test -- src/components/MockModeBanner.test.tsx src/components/Layout.test.ts
```

Build/type smoke if targeted tests pass:

```bash
cd web && npm run build
```

Manual/API recovery probe:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
from api.workspace_state import resolve_workspace_state
print(resolve_workspace_state(start=Path('/tmp')).to_dict())
PY
```

## Remaining Risks

- `os.chdir()` in API lifespan is global. It is a pragmatic compatibility bridge for this relative-path-heavy server, but the longer-term fix should convert server state paths to explicit absolute paths derived from the selected workspace.
- Degraded startup keeps the server alive outside a workspace. This is intentionally recoverable, but write-heavy routes may still need route-level guards in a later pass.
- Adding workspace fields to health models must remain backward-compatible for frontend and tests by using defaults.

## Implemented Slice

- Added `api.workspace_state.resolve_workspace_state()` with explicit `AGENTLAB_WORKSPACE` support and CWD fallback.
- API startup now resolves workspace state before store construction, exposes it through `app.state.workspace_state`, scopes valid workspaces by changing CWD during lifespan, restores the previous CWD on shutdown, and skips demo seeding when workspace state is invalid.
- Health endpoints now expose `workspace_valid` plus detailed `workspace` recovery state on `/api/health`, `/api/health/ready`, and `/api/health/system`.
- `agentlab server --workspace PATH` now selects an explicit workspace before starting uvicorn and rejects missing/non-workspace paths before server startup.
- The global shell banner now treats invalid workspace health as higher priority than mock/preview mode, renders on every route, is not dismissible, and provides retry/setup/recovery-command guidance.

## Verification Evidence

- Red backend run failed first with `ModuleNotFoundError: No module named 'api.workspace_state'`.
- Red frontend run failed first because invalid workspace payloads rendered the existing preview/frontend-only banner instead of workspace recovery UI.
- `.venv/bin/python -m pytest tests/test_workspace_state.py tests/test_api_server_startup.py tests/test_server_boot.py tests/test_cli_commands.py::TestBrandedBanner -q`: 15 passed.
- `cd web && npm run test -- src/components/MockModeBanner.test.tsx src/lib/api.contract.test.ts src/components/Layout.test.ts`: 32 passed.
- `cd web && npm run build`: passed; Vite reported the existing large-chunk warning.
- `PLAYWRIGHT_BASE_URL=http://127.0.0.1:5175 npx playwright test tests/mock-mode-banner.spec.ts`: 5 passed.
- `cd web && npx eslint src/components/MockModeBanner.tsx src/components/MockModeBanner.test.tsx src/lib/types.ts tests/mock-mode-banner.spec.ts`: passed.
- `.venv/bin/python -m py_compile api/workspace_state.py api/server.py api/routes/health.py`: passed.
