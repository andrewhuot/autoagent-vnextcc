# Live CLI Golden Path Hardening Plan - Codex

## Mission

Harden the live-mode AgentLab CLI golden path for a real example agent:

1. Build
2. Workbench
3. Evals
4. Optimize / Improve
5. Deploy

The campaign used a Verizon-like phone-company billing support agent that explains charges, plans, fees, discounts, taxes, device payment plans, roaming, and common bill confusion. Mock mode was intentionally out of scope for the live path.

## Operating Rules

- Use the real Gemini API key from the environment.
- Do not print secrets or write secrets to disk.
- Ignore pro mode.
- Capture exact UX and product gaps in `working-docs/live-cli-golden-path-issues-codex.md`.
- Capture implemented changes and verification in `working-docs/live-cli-golden-path-fixes-codex.md`.
- Keep `working-docs/live-cli-golden-path-summary-codex.md` ready for final handoff.
- Add or update tests for behavior changes.
- Re-run the critical path after fixes.
- Commit and push `feat/live-cli-golden-path-codex`.
- Run the requested `openclaw system event` completion command after pushing.

## Campaign Status

| Phase | Status | Evidence |
| --- | --- | --- |
| 0. Orientation and planning | Complete | Read repo instructions, created required working notes, confirmed branch `feat/live-cli-golden-path-codex`. |
| 1. Required docs and source read pass | Complete | Read README, CLI reference, Workbench docs, app guide, platform overview, recent Workbench plans, prior CLI E2E notes, and current CLI/Workbench/Eval/Optimize/Deploy implementations. |
| 2. Live baseline run | Complete | Created `/tmp/agentlab-live-cli-golden-path-codex-20260413011616/verizon-billing-support-codex`, configured Google/Gemini, ran provider checks, Build, Workbench build/iterate/save/bridge, Eval, Optimize, and Deploy. |
| 3. Root cause and prioritization | Complete | Isolated Build billing-domain loss, Workbench `it` pronoun misclassification, generated eval shape mismatch, bridge handoff loss, stale Eval next command, and poor live execution visibility. |
| 4. Fix implementation | Complete | Patched Build synthesis, Workbench domain inference, Workbench materialization, bridge handoff, eval-case serialization, route/tool compilation, renderer execution status, and Eval next-command guidance. |
| 5. Live confirmation run | Complete | Created `/tmp/agentlab-live-cli-golden-path-codex-confirm-20260413013429/verizon-billing-support-codex-confirm` and re-ran the critical live path through canary deploy. |
| 6. Final verification and delivery | In progress | Final docs updated; compile check exited 0; focused suite passed 60 tests; broader CLI/Workbench/provider slice passed 65 tests. Commit, push, and completion event remain. |

## Read Checklist

- [x] `README.md`
- [x] `docs/cli-reference.md`
- [x] `docs/features/workbench.md`
- [x] `docs/app-guide.md`
- [x] `docs/platform-overview.md`
- [x] `docs/plans/2026-04-10-agent-builder-workbench.md`
- [x] `docs/plans/2026-04-11-workbench-model-harness-refactor.md`
- [x] `working-docs/cli-e2e-plan-codex.md`
- [x] `working-docs/cli-e2e-findings-codex.md`
- [x] `working-docs/p1-workbench-eval-optimize-bridge-plan-codex.md`
- [x] `runner.py`
- [x] `cli/workbench.py`
- [x] `cli/workbench_render.py`
- [x] `builder/workbench.py`
- [x] `builder/workbench_bridge.py`
- [x] `builder/workspace_config.py`
- [x] `builder/harness.py`
- [x] `optimizer/transcript_intelligence.py`
- [x] Eval, Optimize, Deploy related tests and command surfaces

## Live Scenario

Working agent name: `verizon-billing-support-codex`

Agent intent:

- Explain monthly bill sections in plain language.
- Help customers understand one-time charges, activation fees, surcharges, taxes, device payment plans, promotions, autopay discounts, roaming charges, and plan changes.
- Ask for missing bill context before making claims.
- Avoid collecting or exposing sensitive account identifiers.
- Give next-step guidance for escalation without impersonating Verizon.

## Baseline Findings

- `agentlab build` accepted the billing brief but produced generic ecommerce/order routing and generic eval cases.
- Live `workbench build` called Google/Gemini, but domain inference misclassified the prompt as IT Helpdesk because the phrase "It should..." matched an `it ` substring heuristic.
- Workbench text output did not make live execution/provider status visible enough for a CLI user.
- `workbench save` wrote generated eval YAML as a bare list. `EvalRunner` ignored that shape and silently used starter eval cases instead of the Workbench-generated cases.
- `workbench bridge --eval-run-id ...` after save did not remember the saved config/eval paths, so the handoff still looked like it needed materialization.
- `eval run --output-format json` pointed users to deprecated `agentlab improve` instead of `agentlab optimize --cycles 3`.
- Workbench materialization stored the Workbench project ID as source prompt and leaked billing terms into ecommerce/order routing after save.
- Deploy worked as a local canary step after a config was available.

## Confirmation Findings

- Build now creates a billing-aware config and generated billing evals for the Verizon-like prompt.
- Workbench now creates `Phone Billing Support Workbench` / `Phone Billing Support Agent` in live mode with Gemini execution metadata.
- Workbench text output now shows `Execution: live via google:gemini-2.5-pro`.
- Workbench save now writes a loadable `cases:` eval file and records saved config/eval paths for bridge handoff.
- Workbench bridge now points to Eval after save and to Optimize after an eval run ID is supplied.
- Strict live Eval against the generated billing dataset ran successfully after a transient full-suite Gemini HTTP 503.
- Optimize ran against live eval evidence and correctly rejected a candidate because the safety hard gate still had a failure.
- Deploy promoted the saved billing config to a 10% local canary.

## Final Done Criteria

- [x] A live-mode baseline was run and documented.
- [x] Major blockers in the core CLI journey were fixed.
- [x] The critical path was re-run after fixes.
- [x] Tests were added or updated for behavior changes.
- [x] Remaining external/environment blockers are explicit.
- [x] Final compile/test verification is fresh.
- [ ] Branch is committed and pushed.
- [ ] Completion event command is run.

## Environment Notes

| Item | Finding | Resolution |
| --- | --- | --- |
| Python | System `python3` is 3.9.6, but the project needs Python 3.12 and dependencies. | Created ignored `.venv` with Python 3.12 and installed editable dev dependencies. |
| CLI path | Generated `/tmp` workspaces do not contain repo-local `.venv/bin/agentlab`. | Used absolute `/Users/andrew/Desktop/agentlab-live-cli-golden-path-codex/.venv/bin/agentlab` for campaign commands. |
| Gemini key | The real Google/Gemini key is present when commands start from the repo shell, but not when the shell starts directly in `/tmp`. | Started commands from the repo and `cd` into the live workspace inside each command. |
| Provider reliability | One strict full-suite eval attempt hit Gemini HTTP 503. | Retried the generated billing dataset with `--require-live`; retry completed in live mode without mock fallback. |
