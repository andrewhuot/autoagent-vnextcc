# Live CLI Golden Path Fixes - Codex

This file records implemented changes, tests, and verification evidence for the live CLI golden-path hardening campaign.

## Fix Log

| Fix ID | Related Issues | Files Changed | What Changed |
| --- | --- | --- | --- |
| FX-001 | LG-003 | `runner.py`, `tests/test_cli_commands.py` | Added billing-context detection to top-level Build. Billing prompts now generate billing-aware root prompts, support routing, FAQ-style tools, billing eval cases, and safety probes instead of ecommerce/order defaults. |
| FX-002 | LG-004 | `builder/workbench.py`, `tests/test_cli_workbench.py` | Replaced raw substring domain inference with word/phrase helpers. Billing/telecom signals are checked before IT Helpdesk signals, preventing "It should..." from becoming IT Helpdesk. |
| FX-003 | LG-005 | `cli/workbench_render.py`, `tests/test_cli_workbench.py` | Workbench text rendering now surfaces execution mode/provider/model, for example `Execution: live via google:gemini-2.5-pro`. |
| FX-004 | LG-006 | `builder/workspace_config.py`, `builder/workbench.py`, `tests/test_cli_workbench.py` | Workbench save now serializes generated evals as `cases:`, normalizes cases, and includes canonical eval suites from the Workbench model. Tests assert the file loads through `EvalRunner`. |
| FX-005 | LG-007 | `builder/workbench.py`, `builder/workbench_bridge.py`, `cli/workbench.py`, `api/routes/workbench.py`, `tests/test_cli_workbench.py` | Workbench save records `materialized_candidate` metadata with config/eval paths. Bridge reads that persisted handoff and recommends Eval or Optimize based on whether an eval run ID exists. |
| FX-006 | LG-008 | `runner.py`, `tests/test_cli_commands.py` | Eval text/JSON next-step guidance now points to `agentlab optimize --cycles 3` instead of deprecated `agentlab improve`. |
| FX-007 | LG-009 | `builder/workspace_config.py`, `tests/test_cli_workbench.py` | Saved Workbench billing configs now preserve the original operator brief, route billing/charges/autopay terms to support, keep order routing clean, and enable FAQ for billing explanation tool text. |
| FX-008 | LG-003, LG-004, LG-006 | `optimizer/transcript_intelligence.py`, `builder/harness.py` | Added phone-billing domain knowledge to artifact generation and harness rendering: billing intents, tools, rules, sensitive flows, guardrails, journeys, and eval cases. Generated source now uses the canonical model instead of a hardcoded Claude model. |

## Live Commands Run

Baseline workspace:

```bash
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab new verizon-billing-support-codex --template customer-support --no-demo --mode live
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab provider configure --provider google --model gemini-2.5-pro --api-key-env GOOGLE_API_KEY
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab provider test
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab doctor
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab build "Build a Verizon-like phone-company support agent..."
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab workbench build "...billing support brief..." --json
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab workbench iterate "...billing correction..." --json
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab workbench save --json
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab eval run --config configs/v003.yaml --require-live --output-format json
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab optimize --cycles 1 --output-format json
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab deploy --auto-review --yes
```

Confirmation workspace:

```bash
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab new verizon-billing-support-codex-confirm --template customer-support --no-demo --mode live
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab provider configure --provider google --model gemini-2.5-pro --api-key-env GOOGLE_API_KEY
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab mode show
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab provider test
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab doctor
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab build "Build a Verizon-like phone-company support agent..."
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab workbench build "...billing support brief..." --json
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab workbench show
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab workbench bridge --json
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab workbench iterate "...first-bill activation fees..." --json
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab workbench save --json
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab workbench bridge --eval-run-id eval-confirm-123 --json
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab eval run --config configs/v004.yaml --dataset evals/cases/generated_build.yaml --split all --require-live --output-format json
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab eval show latest
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab workbench bridge --eval-run-id 22d262d5-040 --json
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab optimize --cycles 1 --output-format json
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab deploy --auto-review --yes
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab deploy status
/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab status
```

## Automated Verification Already Run

```bash
.venv/bin/python -m pytest tests/test_cli_workbench.py::TestWorkbenchDomainInference::test_phone_billing_prompt_does_not_match_it_pronoun tests/test_cli_workbench.py::TestWorkbenchShowLifecycle::test_workbench_show_text_renders_readiness_and_next_step tests/test_cli_workbench.py::TestWorkbenchSaveLifecycle::test_workbench_save_materializes_candidate_for_eval -q
```

Result: 3 passed.

```bash
.venv/bin/python -m pytest tests/test_cli_commands.py::TestEvalCommands::test_eval_run_json_points_to_optimize_next -q
```

Result: 1 passed.

```bash
.venv/bin/python -m pytest tests/test_workbench_eval_optimize_bridge.py tests/test_cli_workbench.py tests/test_cli_commands.py::TestEvalCommands -q
```

Result: 43 passed.

```bash
.venv/bin/python -m pytest tests/test_cli_commands.py::TestJourneyCommands::test_build_billing_prompt_generates_billing_config_and_evals tests/test_cli_workbench.py::TestWorkbenchDomainInference::test_phone_billing_prompt_does_not_match_it_pronoun -q
```

Result: 2 passed.

```bash
.venv/bin/python -m pytest tests/test_workbench_eval_optimize_bridge.py tests/test_cli_workbench.py tests/test_cli_commands.py::TestJourneyCommands tests/test_cli_commands.py::TestEvalCommands tests/test_eval_pipeline.py -q
```

Result: 59 passed before the final billing-save regression was added; final rerun passed 60 tests.

## Final Verification Before Commit

```bash
.venv/bin/python -m py_compile runner.py cli/workbench.py cli/workbench_render.py builder/workbench.py builder/workbench_bridge.py builder/workspace_config.py builder/harness.py api/routes/workbench.py optimizer/transcript_intelligence.py
.venv/bin/python -m pytest tests/test_workbench_eval_optimize_bridge.py tests/test_cli_workbench.py tests/test_cli_commands.py::TestJourneyCommands tests/test_cli_commands.py::TestEvalCommands tests/test_eval_pipeline.py -q
.venv/bin/python -m pytest tests/test_golden_path_fresh_install.py tests/test_cli_workbench.py tests/test_workbench_agent_live.py tests/test_workbench_eval_optimize_bridge.py tests/test_e2e_value_chain_cli.py tests/test_cli_commands.py::TestEvalCommands tests/test_cli_integrations.py::TestModeCLI tests/test_provider_runtime.py -q
```

Results:

- Compile check exited 0.
- Focused regression suite: 60 passed in 31.82s.
- Broader CLI/Workbench/provider slice: 65 passed in 34.27s.

## Confirmation Results

- Build generated billing-specific artifacts.
- Workbench build/iterate used live Gemini execution and kept billing identity.
- Workbench save generated a loadable `cases:` eval file.
- Bridge carried saved config/eval paths into Eval and Optimize guidance.
- Strict live Eval against the generated billing dataset completed with run ID `22d262d5-040`, 2/3 passing, safety 0.6667, composite 0.5267.
- Optimize improved score but rejected the candidate because the safety hard gate still failed one case.
- Deploy created release `rel-0d223280` and canary-deployed v004 at 10% traffic.
