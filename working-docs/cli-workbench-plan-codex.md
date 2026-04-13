# CLI Workbench Plan - Codex

Date: 2026-04-13
Branch: `feat/cli-workbench-codex`
Base at launch: `origin/master` / `b4d8de24c3b6f759ae09d7baabfb5a85ea1f25d1`

## Mission

Implement a CLI Workbench flow that supports the core AgentLab Workbench loop for loading or selecting an agent/config, inspecting and iterating candidate agent card/config state, materializing saved candidate changes, understanding readiness, and handing off honestly toward Eval and Optimize.

The CLI surface should feel like a serious terminal-native agent-building workbench, but it must preserve AgentLab Workbench semantics instead of wrapping the web UI or inventing a parallel lifecycle.

## Product Contract

- Workbench creates and prepares a candidate.
- Eval measures the materialized candidate.
- Optimize waits for completed eval evidence.
- Review and Deploy remain separate human-controlled surfaces.
- CLI output must not imply that structural validation is production proof.
- CLI commands should reuse Workbench service/store/bridge contracts where practical.

## Deliverables

- [x] `working-docs/cli-workbench-plan-codex.md`
- [x] `working-docs/cli-workbench-findings-codex.md`
- [x] Implemented CLI Workbench feature/code
- [x] Updated docs and examples
- [x] Tests for highest-risk CLI Workbench flows
- [ ] Commit and push `feat/cli-workbench-codex`
- [ ] Completion event:
  `openclaw system event --text "Done: Codex finished CLI Workbench implementation on feat/cli-workbench-codex" --mode now`

## Read-First Checklist

- [x] `README.md`
- [x] `docs/features/workbench.md`
- [x] `docs/cli-reference.md`
- [x] `docs/app-guide.md`
- [x] `docs/platform-overview.md`
- [x] `web/src/pages/AgentWorkbench.tsx`
- [x] `web/src/lib/workbench-api.ts`
- [x] `web/src/lib/workbench-store.ts`
- [x] `builder/workbench.py`
- [x] `builder/workbench_bridge.py`
- [x] `api/routes/workbench.py`
- [x] related tests
- [x] CLI entrypoint and command organization

## Current Phase

Phase 7: ship after final diff review.

## Phases

### Phase 1 - Discovery and Contract Mapping

Status: complete

Goals:

- Map current CLI framework and command conventions.
- Map Workbench service, store, bridge, validation, run, materialization, and readiness contracts.
- Map UI workflow semantics into terminal terms.
- Identify the smallest coherent CLI command set.

Exit criteria:

- Findings document captures CLI, backend, bridge, UI, and test observations.
- Plan has a concrete implementation approach and command contract.

### Phase 2 - CLI Workbench Design

Status: complete

Goals:

- Define command group and subcommands.
- Define text and JSON output shapes.
- Define non-interactive and interactive behavior.
- Define readiness and handoff presentation.

Proposed command set:

- `agentlab workbench status`
- `agentlab workbench show`
- `agentlab workbench build "brief..."`
- `agentlab workbench iterate "follow-up..."`
- `agentlab workbench save`
- `agentlab workbench handoff`

Design notes:

- `build` should create a new project unless `--project-id` is provided.
- `iterate` should require or resolve a project and run `WorkbenchService.run_iteration_stream()`.
- `show` should render the hydrated plan snapshot, candidate model summary, artifacts, validation, review gate, and bridge readiness.
- `status` can be an alias-like compact view of `show`, focused on readiness/next step.
- `save` should materialize via `persist_generated_config()` and then rebuild the bridge with saved config/eval paths.
- `handoff` should show the bridge without necessarily saving unless `--save` is provided.
- JSON output should use the standard envelope.
- Text output should explicitly say that Eval is the next measurement step and Optimize waits for an eval run.

Initial implementation boundary:

- Avoid arbitrary run-id bridge selection in v1; use the current/default project and latest active run state, matching existing service behavior.
- Provide `--project-id` for project selection and `--new` for fresh build starts.
- Provide `--mock` for deterministic CLI tests and no-key demos.
- Use `asyncio.run()` around a small async stream consumer in Click command handlers.
- Materialization command must clearly state that it saves a candidate config and sets it active locally.

### Phase 3 - Regression Tests First

Status: complete

Goals:

- Add tests that fail before implementation.
- Cover real `CliRunner` flows, not just helper functions.
- Cover JSON output where downstream scripts need stable contract.

Highest-risk flows:

- CLI build creates/restores a Workbench project and streams or records a completed run.
- CLI show/status renders canonical readiness without overstating Eval/Optimize.
- CLI save materializes candidate through the existing bridge and returns config/eval paths.
- CLI handoff reports Eval request and Optimize waiting state.
- CLI handles a terminal `run.completed` event with failed status as failed, not as success.

### Phase 4 - Implementation

Status: complete

Goals:

- Add CLI command group in the existing command architecture.
- Reuse `WorkbenchService`, `WorkbenchStore`, and `builder.workbench_bridge`.
- Keep terminal output readable and JSON output stable.
- Implement TTY-aware interaction only if it is clean and covered.

### Phase 5 - Documentation

Status: complete

Goals:

- Update CLI reference.
- Add README mention if Workbench becomes a primary CLI surface.
- Add examples that preserve Workbench boundaries.

### Phase 6 - Verification

Status: complete

Fresh verification required before completion claims:

- Targeted CLI Workbench tests.
- Related Workbench bridge/backend tests.
- Real CLI help/output smoke commands.
- Formatting/syntax checks appropriate for touched files.
- `git diff --check`.

### Phase 7 - Ship

Status: in progress

Steps:

- Review `git diff`.
- Stage only relevant files.
- Commit with Conventional Commit message.
- Push branch.
- Run completion event command.

## Decisions

| Decision | Rationale | Status |
|---|---|---|
| Treat CLI Workbench as a real command group rather than a hidden helper | Workbench is part of the core loop and product docs already name it between Build and Eval. | decided |
| Reuse Workbench bridge for save/handoff | Existing bridge already encodes materialization, Eval readiness, and Optimize prerequisites. | decided |
| Keep Eval/Optimize execution out of Workbench commands | Product docs say Workbench hands off; Eval and Optimize own measurement and improvement. | decided |
| Use standard JSON envelopes for Workbench summaries | Automation should receive the same stable `api_version` / `status` / `data` / `next` shape as newer CLI surfaces. | decided |

## Errors Encountered

| Error | Attempt | Resolution |
|---|---|---|
| System Python was 3.9 and failed test collection on `dataclass(slots=True)` | Initial `python -m pytest tests/test_cli_workbench.py -q` | Switched verification to `uv run --extra dev python -m pytest ...`, matching repo tooling. |
| Temp smoke parser used `python`, but this shell had no `python` alias | Real CLI smoke command flow | Re-ran the same smoke using `.venv/bin/python` for the assertion helper. |
| Full pytest reported three shell-script safety failures | `uv run --extra dev python -m pytest -q` | Root cause was pre-existing listeners on `127.0.0.1:8000` and `127.0.0.1:5173`; the tests' synthetic port occupants exited because those ports were already owned by an external uvicorn/Vite stack. No Workbench files or shell scripts were involved. |

## Verification Log

- `uv run --extra dev python -m py_compile cli/workbench.py runner.py` - passed.
- `uv run --extra dev python -m pytest tests/test_cli_workbench.py -q` - 4 passed.
- `uv run --extra dev python -m pytest tests/test_cli_workbench.py tests/test_workbench_eval_optimize_bridge.py tests/test_workbench_streaming.py tests/test_workbench_api.py tests/test_cli_progress.py tests/test_cli_commands.py::TestCLIStructure::test_top_level_commands -q` - 33 passed.
- Real temp workspace smoke with `.venv/bin/agentlab new`, `workbench build --mock --max-iterations 1 --json`, `workbench show --json`, `workbench handoff --json`, and `workbench save --json` - all returned `ok`; readiness moved from `needs_materialization` to `ready_for_eval`; saved config existed on disk.
- `git diff --check` - passed.
- `uv run --extra dev python -m pytest -q` - 3979 passed, 3 failed in `tests/test_shell_script_safety.py`; failures reproduced and traced to pre-existing listeners on ports 8000 and 5173 (`uvicorn api.server:app` and Vite from `/Users/andrew/Desktop/agentlab/web`), not the CLI Workbench changes.
