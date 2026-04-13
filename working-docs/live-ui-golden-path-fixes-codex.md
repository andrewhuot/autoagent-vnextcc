# Live UI Golden Path Fixes - Codex

Date: 2026-04-13
Branch: feat/live-ui-golden-path-codex
Scenario: Verizon-like phone-company billing-support agent.
Mode: Live mode only.

## Fix Log

| Fix ID | Linked Issue | Status | Files | Tests |
| --- | --- | --- | --- | --- |
| FIX-001 | LIVE-001 | Complete | `optimizer/transcript_intelligence.py`, `builder/harness.py`, `builder/workbench.py`, `builder/workbench_agent.py` | `tests/test_transcript_intelligence_service.py`, `tests/test_workbench_streaming.py`, `tests/test_harness.py`, `tests/test_workbench_api.py` |
| FIX-002 | LIVE-002, LIVE-003 | Complete | `web/src/pages/Build.tsx`, `web/src/pages/AgentWorkbench.tsx`, `builder/workbench.py` | `web/src/pages/Build.test.tsx`, `web/src/pages/AgentWorkbench.test.tsx`, backend Workbench tests |
| FIX-003 | LIVE-004 | Complete | `web/src/pages/AgentWorkbench.tsx` | `web/src/pages/AgentWorkbench.test.tsx` |
| FIX-004 | LIVE-005, LIVE-007 | Complete | `evals/runner.py`, `api/routes/eval.py`, `api/models.py`, `agent/eval_agent.py`, `web/src/pages/EvalRuns.tsx`, `web/src/lib/api.ts`, `web/src/lib/types.ts` | `tests/test_eval_runner_model.py`, `tests/test_eval_agent.py`, `tests/test_api.py`, `tests/test_generated_evals_api.py`, `web/src/pages/EvalRuns.test.tsx`, `web/src/lib/api.test.tsx` |
| FIX-005 | LIVE-008 | Complete | `web/src/pages/EvalRuns.tsx`, `web/src/lib/api.ts`, `web/src/lib/types.ts` | `web/src/pages/EvalRuns.test.tsx` |
| FIX-006 | LIVE-010, LIVE-011 | Complete | `api/routes/deploy.py`, `web/src/lib/api.ts` | `tests/test_p0_journey_fixes.py`, `web/src/lib/api.test.tsx`, `web/src/pages/Deploy.test.tsx` |

## Implementation Details

### FIX-001 - Phone billing domain generation

- Added a telecom billing fallback domain to transcript intelligence so live generation can recover when the model returns an unrelated vertical.
- Added phone billing Build/Workbench templates for capabilities, rules, style, sensitive flows, tools, guardrails, and eval criteria.
- Ensured generated ADK source uses the configured root agent model instead of hardcoded Claude model text.
- Added regression tests that phone billing prompts generate phone billing artifacts and avoid IT Helpdesk fallback content.

### FIX-002 - Build -> Workbench continuity

- Build now passes the original user prompt and saved Build model into the Workbench handoff.
- Workbench resets stale handoff state before a fresh start.
- Workbench only auto-starts from active Build handoff context.
- Workbench infers phone billing from the handoff prompt and preserves the saved Gemini model.
- Regression tests cover prompt/model propagation and fresh-start behavior.

### FIX-003 - Workbench -> Eval real agent version

- Workbench now derives `agent-vNNN` from the saved config version when opening Eval.
- This prevents Eval from selecting synthetic `workbench-...` IDs that the backend cannot fetch.
- Browser recheck confirmed `/api/agents/agent-v008` returned 200.

### FIX-004 - Eval progress and strict live mode

- `evals.runner` accepts a progress callback and reports per-case progress.
- `api/routes/eval.py` wires progress updates into task state.
- `EvalRunRequest` gained `require_live`.
- `ConfiguredEvalAgent` gained a strict per-call config flag that raises instead of falling back when live is required.
- EvalRuns sends `require_live: true` for non-mock active-agent runs.
- Browser recheck confirmed strict-live run `be3663da-0bc` completed with `mode: live`, one case, no warnings.

### FIX-005 - Eval summary scoping

- EvalRuns journey summary now uses current selected run state rather than unrelated historical completed runs.
- Failed rows expose first error text, making provider/config failures more actionable.

### FIX-006 - Deploy selected candidate without duplication

- Deploy route now refreshes the version manager from disk before status, deploy, promote, and rollback calls.
- Deploy route reconnects the deployer and canary manager to the refreshed version manager.
- Deploy route handles canary strategy with `body.version` by marking that saved version canary in place.
- Frontend `useDeploy` posts `{version, strategy}` for canary and immediate deploys.
- Browser recheck confirmed selecting v8 sent `{"version":8,"strategy":"canary"}` and changed v8 to canary without creating v11.

## Regression Strategy

- Use focused unit/component tests for route payloads and UI handoff state.
- Use backend integration tests where behavior depends on route state, version managers, or task persistence.
- Use live browser re-verification for the end-to-end journey rather than relying only on mocked UI tests.
- Keep runtime artifacts out of the commit.

## Verification Commands Run So Far

| Command | Result |
| --- | --- |
| `.venv/bin/python -m pytest tests/test_transcript_intelligence_service.py::test_generate_agent_config_fallback_keeps_phone_billing_prompt_in_telecom_domain tests/test_workbench_streaming.py::test_mock_agent_uses_phone_billing_domain_for_wireless_bill_briefs -q` | 2 passed |
| `.venv/bin/python -m pytest tests/test_transcript_intelligence_service.py tests/test_workbench_streaming.py tests/test_workbench_eval_optimize_bridge.py -q` | 34 passed |
| `cd web && npm test -- --run src/pages/AgentWorkbench.test.tsx --reporter=verbose` | 10 passed |
| `cd web && npm test -- --run src/pages/Build.test.tsx src/pages/AgentWorkbench.test.tsx --reporter=verbose` | 31 passed |
| `.venv/bin/python -m pytest tests/test_eval_runner_model.py tests/test_harness.py::test_phone_billing_templates_do_not_fall_back_to_it_helpdesk_content tests/test_workbench_api.py::test_project_creation_preserves_build_handoff_model_hint -q` | 4 passed |
| `.venv/bin/python -m pytest tests/test_eval_agent.py::test_configured_eval_agent_per_call_require_live_refuses_mock_fallback tests/test_api.py::TestRequestModels::test_eval_run_request_defaults tests/test_api.py::TestRequestModels::test_eval_run_request_with_values tests/test_generated_evals_api.py::test_eval_run_require_live_marks_config_for_strict_provider_execution -q` | 4 passed |
| `cd web && npm test -- --run src/pages/EvalRuns.test.tsx src/lib/api.test.tsx --reporter=verbose` | 24 passed |
| `.venv/bin/python -m py_compile agent/eval_agent.py api/routes/eval.py api/models.py evals/runner.py` | Passed |
| `.venv/bin/python -m pytest tests/test_p0_journey_fixes.py::TestDeployPromoteEndpoint::test_deploy_status_refreshes_versions_created_after_deployer_start -q` | 1 passed |
| `.venv/bin/python -m pytest tests/test_p0_journey_fixes.py::TestDeployPromoteEndpoint::test_deploy_canaries_selected_existing_version_without_duplication tests/test_p0_journey_fixes.py::TestDeployPromoteEndpoint::test_deploy_status_refreshes_versions_created_after_deployer_start -q` | 2 passed |
| `.venv/bin/python -m py_compile api/routes/deploy.py tests/test_p0_journey_fixes.py` | Passed |
| `cd web && npm test -- --run src/lib/api.test.tsx src/pages/Deploy.test.tsx --reporter=verbose` | 20 passed |
| `cd web && npm run build` | Passed; Vite large chunk warning only |
| `git diff --check` | Passed |
| `.venv/bin/python -m pytest tests/test_transcript_intelligence_service.py tests/test_workbench_streaming.py tests/test_harness.py tests/test_workbench_api.py tests/test_workbench_eval_optimize_bridge.py tests/test_eval_runner_model.py tests/test_eval_agent.py tests/test_generated_evals_api.py tests/test_p0_journey_fixes.py tests/test_api.py -q` | 151 passed |
| `cd web && npm test -- --run src/pages/Build.test.tsx src/pages/AgentWorkbench.test.tsx src/pages/EvalRuns.test.tsx src/pages/Deploy.test.tsx src/lib/api.test.tsx --reporter=verbose` | 63 passed |
| `.venv/bin/python -m py_compile agent/eval_agent.py api/models.py api/routes/deploy.py api/routes/eval.py builder/harness.py builder/workbench.py builder/workbench_agent.py evals/runner.py optimizer/transcript_intelligence.py ...` | Passed |
| `git diff --check` | Passed after final docs and patches |

## Browser Re-Verification

- Build generated the phone billing agent in live Gemini mode.
- Workbench preserved prompt/model continuity and saved `configs/v008.yaml`.
- Eval selected `agent-v008` and strict-live eval `be3663da-0bc` completed in mode `live`.
- Optimize opened from the eval run and completed both standard and forced attempts; forced candidate was rejected by safety hard gate.
- Deploy selected v8 and made v8 canary without adding another version after the final frontend fix.

## Deferred Or Not Fixed

- ENV-001 and ENV-002 are environment/workspace startup issues. They were mitigated for this campaign but not patched.
- LIVE-009 remains a product gap: Optimize/Improve should turn poor eval evidence into a clearer reviewable action.
- LIVE-012 remains an environment/product confidence gap: local canary deploy lacks baseline traffic and external production confirmation.
