# AgentLab Workbench P0 Hardening Plan

Date: 2026-04-12
Branch: `feat/workbench-p0-hardening-codex`

## Goal

Make the Agent Builder Workbench materially closer to production-ready by hardening server-side run lifecycle semantics, cancellation, recovery, budgets, telemetry, and live/mock operator visibility without replacing the existing Workbench architecture.

## Current Read Findings

- Backend stream entry points live in `api/routes/workbench.py` at `/api/workbench/build/stream` and `/api/workbench/build/iterate`.
- Durable Workbench state lives in `builder/workbench.py` via `WorkbenchStore` JSON persistence and `WorkbenchService`.
- Run persistence already exists as `project["runs"]` with `active_run_id`, run `events`, messages, validation, and presentation.
- Existing run phases are informal strings such as `plan`, `build`, `reflect`, `present`, `failed`; `build_status` also uses `running`, `reflecting`, `completed`, and `failed`.
- Frontend types/store already expect richer multi-turn events (`turn.started`, `validation.ready`, `turn.completed`) and active runs, but the currently read backend stream still emits the older lifecycle around `plan.ready` through `run.completed`.
- The UI stop button currently aborts only the browser stream; it does not call a server endpoint or persist a cancelled terminal run state.
- Existing request models expose `max_iterations`, but there is no explicit server-side budget object for wall-clock, token, or cost limits.
- Harness metrics include step count, tokens, cost estimate, elapsed time, and phase-like information; these can be reused as budget and telemetry inputs.
- Live-mode selection happens in `builder/workbench_agent.py::build_default_agent`. It silently falls back to mock on missing provider readiness or internal failures, which keeps demos running but is not operator-honest enough for staging.
- Baseline verification required `uv run --extra dev` because `python` is absent, `/usr/bin/python3` is too old for the repo's type syntax, and `/opt/homebrew/bin/python3.12` does not have pytest installed.
- The pre-change targeted Python slice produced 17 pass / 4 fail. The failures are all in `tests/test_workbench_multi_turn.py`: current streams start at `plan.ready`, do not emit `turn.started` / `validation.ready` / `turn.completed`, and follow-up calls do not produce smaller delta plans under the multi-turn contract.

## Implementation Priorities

1. **Lifecycle Contract**
   - Introduce explicit server-side run statuses: `queued`, `running`, `reflecting`, `presenting`, `completed`, `failed`, `cancelled`.
   - Introduce explicit phases: `queued`, `planning`, `executing`, `reflecting`, `presenting`, `terminal`.
   - Normalize persisted `build_status`, run `status`, and event payload `status` values around this contract.
   - Preserve existing event names where possible to avoid frontend churn, but add richer `run.started`, `turn.started`, `validation.ready`, `turn.completed`, `run.cancelled`, and `telemetry.event` payloads.

2. **Cancellation**
   - Add a server-side cancellation endpoint, likely `POST /api/workbench/runs/{run_id}/cancel`, accepting an optional reason.
   - Persist `cancel_requested_at`, `cancel_reason`, terminal `status=cancelled`, `completed_at`, and a durable event sequence.
   - Make streaming loops check cancellation before and after each yielded agent event, before reflection/presentation, and before autonomous corrections.
   - Mark pending/running plan tasks as paused or cancelled-compatible without deleting produced artifacts.
   - Keep client-side `AbortController` for network cleanup, but call the server endpoint first when a run id is known.

3. **Recovery**
   - Add recovery semantics during project load/snapshot hydration for stale active runs.
   - If a run is persisted as `queued`, `running`, `reflecting`, or `presenting` with an old `updated_at`, mark it failed or cancelled with a clear recovery reason.
   - Surface recovery events and reasons in `active_run`, `runs`, and the UI instead of pretending the run is still active.

4. **Budgets**
   - Extend build requests with an optional budget object while preserving current fields:
     - `max_iterations`
     - `max_seconds`
     - `max_tokens`
     - `max_cost_usd`
   - Enforce budgets server-side from elapsed time and harness metric payloads.
   - On budget breach, terminate the run as failed with `failure_reason=budget_exceeded` and a specific `budget_kind`.
   - Include budget limits and usage in run payloads, snapshot API, SSE events, and UI metrics.

5. **Telemetry / Operator Visibility**
   - Add structured telemetry records to each durable run event:
     - `run_id`, `turn_id`, `iteration_id`, `phase`, `status`, `provider`, `model`, token estimates, cost estimates, duration, failure/cancel/budget reasons.
   - Maintain a compact `telemetry_summary` on each run for UI hydration.
   - Emit phase transition events and persist operator-readable summaries.
   - Prefer additive data in existing JSON store over introducing a new database.

6. **Live / Mock Honesty**
   - Make agent mode explicit in run metadata: `mode=mock|live`, `provider`, `model`, and `mode_reason`.
   - When live setup is unavailable, surface the fallback reason in the initial run events and snapshot.
   - Keep fallback behavior deterministic, but avoid representing mock output as live validation.
   - Add tests around missing credentials/fallback reason and live-router metadata propagation using stubs.

7. **Frontend**
   - Add `cancelWorkbenchRun` API client.
   - Track `activeRun.run_id`, run mode, budget limits/usage, cancel/failure reasons, and telemetry summary in the store.
   - Wire stop button to call the cancel endpoint before aborting the stream.
   - Expand metrics/operator panels to show current phase, mode, provider/model, budget usage, and terminal reasons.
   - Keep the UI honest on reload: stale/recovered/cancelled runs should render as terminal, not running.

## Test Plan

- Add or update Python tests in `tests/test_workbench_streaming.py`, `tests/test_workbench_multi_turn.py`, and/or a new focused Workbench hardening test file.
- Red tests first for:
  - cancel endpoint marks active run cancelled and stream honors cancellation checks
  - snapshot recovery marks stale in-flight runs terminal with a recovery reason
  - iteration/time/token/cost budget breaches produce durable terminal events and summaries
  - run events include structured telemetry and explicit mock/live metadata
- Add frontend tests in `web/src/lib/workbench-api.test.ts` or `web/src/lib/workbench-store.test.ts` and `web/src/pages/AgentWorkbench.test.tsx` for:
  - cancel API call path
  - `run.cancelled` handling
  - budget/mode/telemetry state hydration and rendering

## Verification Targets

- Python targeted:
  - `/opt/homebrew/bin/uv run --extra dev python -m pytest tests/test_workbench_streaming.py tests/test_workbench_multi_turn.py tests/test_workbench_agent_live.py tests/test_harness.py -q`
  - Narrower new tests while developing.
- Frontend targeted:
  - `cd web && npm test -- --run src/lib/workbench-store.test.ts src/pages/AgentWorkbench.test.tsx src/components/workbench/HarnessMetricsBar.test.tsx`
- Web build:
  - `cd web && npm run build`
- Environment setup may require installing Python and frontend dependencies because this checkout initially had neither FastAPI nor Vitest available.

## Risks / Non-Goals

- True provider validation cannot be proven without real credentials; this pass will harden codepaths and operator affordances, then report credential-dependent validation as not run.
- JSON-store cancellation is cooperative, not process-killing. It can reliably stop the Workbench loop at event boundaries but cannot preempt a blocking provider call already in progress unless the provider layer supports timeout/cancellation.
- Avoid broad rewrites of the Workbench harness. This pass should layer explicit lifecycle semantics onto the existing `WorkbenchService`, `WorkbenchStore`, harness events, and frontend store.

## Shipped In This Pass

- Added explicit run statuses/phases and normalized terminal semantics so active runs end as `completed`, `failed`, or `cancelled` with `phase=terminal` where appropriate.
- Added server-side cancellation at both `POST /api/workbench/runs/{run_id}/cancel` and `POST /api/workbench/projects/{project_id}/runs/{run_id}/cancel`, with durable `run.cancel_requested` and `run.cancelled` events.
- Added stale-run recovery during project/snapshot hydration. Active runs older than `AGENTLAB_WORKBENCH_STALE_RUN_SECONDS` are marked failed with `failure_reason=stale_interrupted` and a durable `run.recovered` event.
- Added server-authoritative run budgets for iterations, elapsed seconds, estimated tokens, and estimated cost. Budget breaches fail the run with `failure_reason=budget_exceeded`, `budget.exceeded`, and usage/limit details.
- Added structured telemetry envelopes on durable run events, including run/turn/iteration IDs, phase/status, provider/model, execution mode, duration, token/cost estimates, and failure/cancel/budget reasons.
- Added explicit live/mock readiness metadata via `build_default_agent_with_readiness()` and persisted execution metadata on runs and stream events.
- Preserved prior-turn artifacts during follow-up iterations so multi-turn history stays auditable.
- Wired frontend cancellation helper and Stop button path to the server cancel endpoint before local abort.
- Extended frontend state/API types for budget, telemetry, provider/model, execution mode, cancel/failure reasons, and `cancelled`/`reflecting`/`presenting` build states.
- Added operator-visible mode and token budget usage to the metrics bar, extended the trace view with telemetry details, and included `/workbench` in the mock/live banner routes.

## Verification Results

- Syntax:
  - `/opt/homebrew/bin/uv run --extra dev python -m py_compile builder/workbench.py api/routes/workbench.py` passed.
- Targeted Workbench backend:
  - `/opt/homebrew/bin/uv run --extra dev python -m pytest tests/test_workbench_api.py tests/test_workbench_streaming.py tests/test_workbench_multi_turn.py tests/test_workbench_hardening.py tests/test_workbench_p0_hardening.py -q` passed: 28 tests.
- Harness/live backend:
  - `/opt/homebrew/bin/uv run --extra dev python -m pytest tests/test_harness.py tests/test_workbench_agent_live.py -q` passed: 65 tests.
- Frontend targeted:
  - `cd web && npm test -- workbench-api.test.ts workbench-store.test.ts HarnessMetricsBar.test.tsx` passed: 34 tests.
- Frontend full:
  - `cd web && npm test` passed: 52 files, 332 tests. JSDOM printed `Not implemented: navigation to another Document`.
- Web build:
  - `cd web && npm run build` passed. Vite emitted the existing large chunk warning.
- Full backend:
  - `/opt/homebrew/bin/uv run --extra dev python -m pytest -q` ran 3649 tests: 3646 passed, 3 failed.
  - The failures are outside Workbench in mutation-registry count assertions that expect 13 first-party operators while the current checkout returns 14:
    - `tests/test_mutations.py::test_create_default_registry_has_13_operators`
    - `tests/test_mutations.py::test_register_duplicate_overwrites`
    - `tests/test_registry.py::TestMutationSurfaceExtensions::test_total_operator_count`
