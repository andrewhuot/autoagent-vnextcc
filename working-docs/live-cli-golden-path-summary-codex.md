# Live CLI Golden Path Summary - Codex

This is the final handoff draft for the live-mode AgentLab CLI golden-path hardening campaign.

## What Was Tested Live

- Created two real live-mode workspaces for the Verizon-like billing support agent.
- Configured Google/Gemini with the real `GOOGLE_API_KEY` from the environment.
- Ran `provider test` and `doctor` in live mode.
- Ran Build from the billing-agent brief.
- Ran CLI Workbench build, show, bridge, iterate, save, and bridge-with-eval-run-id.
- Ran strict live Eval with `--require-live` against the generated billing dataset.
- Ran Optimize against live eval evidence.
- Ran Deploy with `--auto-review --yes`, then checked deploy/status output.

## Key UX/Product Gaps Found

- Build initially lost the billing domain and fell back to ecommerce/order scaffolding.
- Workbench initially misclassified the prompt as IT Helpdesk because of raw `it ` substring matching.
- Workbench text output initially hid live execution/provider/model context.
- Workbench save initially generated eval YAML that Eval could ignore.
- Workbench bridge initially forgot saved config/eval paths after materialization.
- Eval JSON initially pointed to deprecated `agentlab improve`.
- Saved Workbench configs initially leaked billing terms into order routing and disabled FAQ support.
- Source install and directory-scoped environment behavior make the local CLI path harder than a packaged install.
- Gemini can return transient 503s; strict live mode correctly refused mock fallback.

## What Was Fixed

- Build now generates billing-aware prompts, routing, tool flags, and eval cases for phone-company billing briefs.
- Workbench domain inference now detects billing/telecom first and avoids pronoun-based IT Helpdesk false positives.
- Workbench show now surfaces live execution status, provider, and model.
- Workbench save now writes generated evals under `cases:` and preserves the original operator brief.
- Workbench bridge now persists and reuses materialized config/eval paths and points to Optimize once an eval run ID exists.
- Eval output now recommends `agentlab optimize --cycles 3`.
- Workbench runtime config compilation now routes billing language to support, avoids order-route contamination, and enables FAQ for billing explanation tools.
- Billing domain knowledge was added to artifact generation and harness rendering.

## What Still Remains Hard or Blocked

- Local source installs still need venv activation or an absolute CLI path when moving into generated workspaces.
- Directory-scoped env loading can hide `GOOGLE_API_KEY` in `/tmp` shells unless commands inherit the repo-started environment.
- A full-suite strict live Eval hit a transient Gemini HTTP 503 once; the generated billing dataset retry succeeded live.
- The billing agent still fails one safety eval. Optimize correctly rejected a candidate because the safety hard gate failed, so further agent-policy iteration is needed before broader rollout.
- Workbench iteration source preview can still omit existing tools/guardrails even though the canonical agent card and saved runtime config preserve the useful details.

## Tests and Verification Run

- `.venv/bin/python -m pytest tests/test_cli_workbench.py::TestWorkbenchDomainInference::test_phone_billing_prompt_does_not_match_it_pronoun tests/test_cli_workbench.py::TestWorkbenchShowLifecycle::test_workbench_show_text_renders_readiness_and_next_step tests/test_cli_workbench.py::TestWorkbenchSaveLifecycle::test_workbench_save_materializes_candidate_for_eval -q` -> 3 passed.
- `.venv/bin/python -m pytest tests/test_cli_commands.py::TestEvalCommands::test_eval_run_json_points_to_optimize_next -q` -> 1 passed.
- `.venv/bin/python -m pytest tests/test_workbench_eval_optimize_bridge.py tests/test_cli_workbench.py tests/test_cli_commands.py::TestEvalCommands -q` -> 43 passed.
- `.venv/bin/python -m pytest tests/test_cli_commands.py::TestJourneyCommands::test_build_billing_prompt_generates_billing_config_and_evals tests/test_cli_workbench.py::TestWorkbenchDomainInference::test_phone_billing_prompt_does_not_match_it_pronoun -q` -> 2 passed.
- `.venv/bin/python -m pytest tests/test_workbench_eval_optimize_bridge.py tests/test_cli_workbench.py tests/test_cli_commands.py::TestJourneyCommands tests/test_cli_commands.py::TestEvalCommands tests/test_eval_pipeline.py -q` -> 60 passed.
- `.venv/bin/python -m py_compile runner.py cli/workbench.py cli/workbench_render.py builder/workbench.py builder/workbench_bridge.py builder/workspace_config.py builder/harness.py api/routes/workbench.py optimizer/transcript_intelligence.py` -> exited 0.
- `.venv/bin/python -m pytest tests/test_golden_path_fresh_install.py tests/test_cli_workbench.py tests/test_workbench_agent_live.py tests/test_workbench_eval_optimize_bridge.py tests/test_e2e_value_chain_cli.py tests/test_cli_commands.py::TestEvalCommands tests/test_cli_integrations.py::TestModeCLI tests/test_provider_runtime.py -q` -> 65 passed.

## Branch and Commit

- Branch: `feat/live-cli-golden-path-codex`
- Commit: recorded in final response after commit creation.
