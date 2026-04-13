# CLI Workbench Findings - Codex

Date: 2026-04-13
Branch: `feat/cli-workbench-codex`

## Repo State

- Worktree starts clean.
- Branch: `feat/cli-workbench-codex`.
- `HEAD` and `origin/master` both point to `b4d8de24c3b6f759ae09d7baabfb5a85ea1f25d1`.

## Product Findings From Required Docs

### Core Loop

AgentLab's documented core loop is:

```text
BUILD -> WORKBENCH -> EVAL -> COMPARE -> OPTIMIZE -> REVIEW -> DEPLOY
```

Workbench is a Build-family harness for creating and inspecting a candidate before Eval. It is not a separate lifecycle and should not collapse Eval, Optimize, Review, or Deploy into one command.

### Workbench Scope

Workbench creates a reviewable candidate config with plan/task progress, artifact cards, generated source previews, validation, review gate state, session handoff, and Eval/Optimize bridge state.

The Workbench handoff endpoint is intentionally conservative:

- saves the generated config
- returns an Eval request shape
- returns an Optimize request template
- does not start Eval
- does not start Optimize
- does not call AutoFix

### Readiness Vocabulary

The CLI should preserve these states and labels:

- Candidate needed
- Needs validation
- Ready
- Draft only
- Eval blocked
- Save candidate before Eval
- Ready for Eval
- Eval candidate not ready
- Run Eval before Optimize
- Ready for Optimize
- Review required
- Blocked
- Interrupted

Important wording constraint: `Ready for Eval` means the candidate can be evaluated. It does not mean the agent is approved, optimized, or deployable.

### CLI Surface Today

Docs currently list primary commands as:

- `new`
- `build`
- `eval`
- `optimize`
- `deploy`
- `status`
- `doctor`
- `shell`

Workbench is named in the product loop and web console, but is not yet documented as a CLI command in `docs/cli-reference.md`.

### Documentation Implication

If CLI Workbench becomes a first-class command, update:

- `README.md` primary command table or feature examples.
- `docs/cli-reference.md` primary commands section.
- Possibly `docs/platform-overview.md` CLI surface section.
- Possibly `docs/features/workbench.md` with CLI examples.

## Existing Bridge Prior Work

`working-docs/p1-workbench-eval-optimize-bridge-plan-codex.md` says a prior branch added:

- `builder/workbench_bridge.py`
- `WorkbenchService.generated_config_for_bridge()`
- `WorkbenchService.build_improvement_bridge_payload()`
- `POST /api/workbench/projects/{project_id}/bridge/eval`
- frontend bridge interfaces and Activity rendering
- backend and frontend regression coverage

This campaign should reuse that bridge instead of reimplementing save/handoff logic.

## Open Findings To Fill

- [x] CLI framework and command registration.
- [x] Exact `WorkbenchService` constructor and workspace/store defaults.
- [x] Exact build/iterate streaming API callable from CLI.
- [x] Existing command output conventions for text, JSON, quiet, and banner modes.
- [x] Existing config path/version selection conventions.
- [x] Existing tests that should be extended.
- [x] Whether an interactive TTY loop already exists in `agentlab shell` that can be reused or mirrored.

## CLI Architecture Findings

- The CLI entrypoint is `runner.py`.
- The framework is Click, with `AgentLabGroup` for top-level help and `DefaultCommandGroup` for default subcommands such as `agentlab build "..."` and `agentlab eval`.
- Primary commands are controlled by `PRIMARY_COMMANDS` in `runner.py`; secondary and hidden commands are controlled by `SECONDARY_COMMANDS` and `HIDDEN_COMMANDS`.
- `agentlab build` is a Click group with hidden default command `run`.
- `agentlab eval` is a Click group with hidden/default `run`.
- `agentlab optimize` is a top-level command.
- Shared output helpers:
  - `cli.output.resolve_output_format()`
  - `cli.output.emit_json_envelope()`
  - `cli.progress.ProgressRenderer`
  - `cli.json_envelope.render_json_envelope()`
- JSON envelope shape for helper-backed commands:
  - `api_version`
  - `status`
  - `data`
  - optional `next`
- Some older commands still emit raw JSON. New Workbench commands should use the standard envelope to avoid adding more drift.
- Workspace discovery:
  - `runner._enter_discovered_workspace()` walks to nearest workspace and changes cwd.
  - `runner._require_workspace()` gives a shared helpful error.
  - `cli.workspace.discover_workspace()` is the lower-level helper.
- Active config resolution:
  - `AgentLabWorkspace.resolve_active_config()` resolves metadata, manifest active version, or newest version.
  - `AgentLabWorkspace.set_active_config()` updates `.agentlab/workspace.json`.

## Workbench Backend Findings

- `WorkbenchStore` persists projects in JSON. Default path is `.agentlab/workbench_projects.json`.
- `WorkbenchService` wraps the store and is safe for direct CLI use.
- Key service methods:
  - `create_project(brief, target, environment)`
  - `get_default_project()`
  - `get_project(project_id)`
  - `run_build_stream(project_id, brief, target, environment, agent, auto_iterate, max_iterations, ...)`
  - `run_iteration_stream(project_id, follow_up, target, environment, agent, max_iterations, ...)`
  - `get_plan_snapshot(project_id)`
  - `generated_config_for_bridge(project_id)`
  - `build_improvement_bridge_payload(project_id, config_path, eval_cases_path, eval_run_id, ...)`
- `run_build_stream()` creates a new project when `project_id` is omitted. If a project id has prior artifacts and a new brief is provided, it routes to iteration semantics.
- `run_iteration_stream()` preserves canonical model and emits follow-up delta artifacts.
- The backend stream emits durable event names used by UI:
  - `turn.started`
  - `plan.ready`
  - `task.started`
  - `task.progress`
  - `message.delta`
  - `artifact.updated`
  - `task.completed`
  - `build.completed`
  - `reflect.started`
  - `validation.ready`
  - `reflect.completed`
  - `present.ready`
  - `turn.completed`
  - `run.completed`
  - failure/cancel/recovery events as needed
- `MockWorkbenchBuilderAgent` provides deterministic no-key behavior and is already used by API tests. CLI should expose this via a `--mock` or mode-compatible option for tests and no-key demos.
- Terminal run payloads include:
  - validation
  - review gate
  - presentation
  - handoff
  - evidence summary
  - improvement bridge
- `get_plan_snapshot()` returns the hydrated snapshot shape the UI uses, including active run, runs, turns, harness state, and run summary.

## Workbench Bridge Findings

- `builder/workbench_bridge.py` defines typed Pydantic contracts:
  - `WorkbenchEvalRunRequest`
  - `WorkbenchOptimizeRequest`
  - `WorkbenchBridgeCandidate`
  - `WorkbenchBridgeEvaluationStep`
  - `WorkbenchBridgeOptimizationStep`
  - `WorkbenchImprovementHandoff`
- `build_workbench_improvement_bridge()` is the canonical readiness builder.
- Evaluation states:
  - `blocked` / `draft_only`
  - `needs_saved_config` / `needs_materialization`
  - `ready` / `ready_for_eval`
- Optimize states:
  - `blocked`
  - `needs_eval_candidate`
  - `awaiting_eval_run`
  - `ready_for_optimize`
- `build_workbench_optimize_request()` requires a non-empty completed eval run ID and a materialized config path.
- The bridge intentionally returns an Optimize request template with `eval_run_id` unset until Eval completes.

## Materialization Findings

- API route `POST /api/workbench/projects/{project_id}/bridge/eval` uses:
  - `service.generated_config_for_bridge()`
  - `builder.workspace_config.persist_generated_config()`
  - `service.build_improvement_bridge_payload()`
- `persist_generated_config()` writes the generated Workbench config into the real workspace:
  - saves a candidate config version under `configs/`
  - updates active config metadata
  - writes `evals/cases/generated_build.yaml`
  - writes latest build artifact metadata
- CLI can reuse the same path directly instead of instantiating FastAPI.

## UI/Store Semantics Findings

- Workbench UI hydrates `getDefaultWorkbenchProject()` then `getWorkbenchPlanSnapshot(project_id)`.
- Fresh builds call `/api/workbench/build/stream`.
- Follow-up turns call `/api/workbench/build/iterate`.
- Eval handoff calls `createWorkbenchEvalBridge(project_id)` and navigates to `/evals` with the materialized config path.
- The right-pane Activity tab displays evidence, review gate, session handoff, and Eval/Optimize bridge.
- The top operator card uses lighter page evidence; the bridge is stricter and should be the CLI source for save/handoff readiness.

## Test Findings

- `tests/test_workbench_streaming.py` covers full backend stream event sequence and durable snapshots.
- `tests/test_workbench_eval_optimize_bridge.py` covers materialization and readiness states.
- CLI tests use `click.testing.CliRunner` in:
  - `tests/test_cli_commands.py`
  - `tests/test_cli_progress.py`
  - `tests/test_cli_ux_refactor_v2.py`
- Existing CLI tests often use `runner.isolated_filesystem()` and call `runner.invoke(cli, [...])`.
- Highest-value CLI Workbench tests should use a real isolated workspace, invoke commands, and inspect on-disk `.agentlab`/`configs`/`evals` outputs.

## Implemented CLI Surface

The implemented command group is `agentlab workbench`.

Subcommands:

- `build "brief"` starts or continues the Workbench build stream and returns candidate readiness.
- `iterate "follow-up"` applies a follow-up turn to the latest or selected project.
- `show` renders the candidate card, artifacts, validation, bridge readiness, and next command.
- `status` renders the same readiness in a compact terminal form.
- `save` materializes the generated Workbench candidate into normal workspace files and rebuilds the bridge with saved paths.
- `handoff` prints the bridge without saving by default, or materializes first with `--save`.

Important flags:

- `--project-id` selects an existing Workbench project.
- `--new` forces a new build project.
- `--target` and `--environment` preserve Workbench target metadata.
- `--mock` enables deterministic no-key builder behavior for tests and demos.
- `--output-format text|json|stream-json` supports terminal display, final JSON envelopes, or raw stream events.
- `--json` is a shortcut for final JSON envelope output.

## Verification Findings

- Focused CLI Workbench tests cover build, show, save, and iterate through `CliRunner` against isolated real workspaces.
- Related Workbench backend/API/bridge tests still pass with the CLI command group registered as a primary command.
- Real temp workspace smoke confirmed the installed console script can run `new`, `workbench build`, `workbench show`, `workbench handoff`, and `workbench save` in sequence.
- `workbench handoff --json` before save reports `needs_materialization`; `workbench save --json` reports `ready_for_eval` and returns a saved config path that exists on disk.
- Full pytest was attempted. The only failures were three shell-script safety tests whose synthetic port occupants could not bind because external processes already occupied `127.0.0.1:8000` and `127.0.0.1:5173`. The Workbench implementation did not touch `start.sh`, `stop.sh`, or those tests.

## Subagent Investigations

Launched read-only investigations:

- CLI command conventions and tests.
- Workbench backend service/bridge contracts. Completed: confirmed direct service/bridge reuse, async stream usage, canonical state transitions, and materialization side effects.
- Workbench UI/store semantics and docs implications.

Additional backend risks from specialist pass:

- `run_build_stream()` and `run_iteration_stream()` are async factories. CLI must `await` the factory, then `async for` the returned stream.
- A terminal event named `run.completed` can still include `data.status == "failed"`. CLI must inspect payload status and `failure_reason`, not just event name.
- Materialization sets the active workspace config and writes eval cases/build artifact files. The CLI must state this honestly.
- Bridge building uses the active/latest run. Run-specific selection would require a new service contract; initial CLI should avoid pretending arbitrary run selection is supported unless implemented deliberately.
- `run.phase` may remain `presenting` on successful completion. CLI should use run status/readiness instead of phase alone.
- Streaming plan task ids and non-stream `/plan` approval ids are separate systems.
