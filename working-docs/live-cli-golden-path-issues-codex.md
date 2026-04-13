# Live CLI Golden Path Issues - Codex

This file captures live-mode blockers, UX gaps, paper cuts, and root-cause notes found while testing the AgentLab CLI golden path with the Verizon-like billing support agent.

## Issue Log

| ID | Severity | Flow Area | Status | Finding | Evidence | Resolution / Next Step |
| --- | --- | --- | --- | --- | --- | --- |
| LG-001 | P2 | Local execution setup | Open | Generated workspace next commands assume `agentlab` is on PATH. That is normal after installation, but awkward for repo-local source installs. | Baseline workspace commands failed when using `.venv/bin/agentlab` after `cd` into `/tmp/...` because `.venv` is repo-local. | Not fixed in product. Campaign used absolute `.venv/bin/agentlab`. Docs could mention venv activation for source installs. |
| LG-002 | P2 | Live provider setup | Open | The real Gemini key was available in the repo-started shell but not in shells started directly inside `/tmp` generated workspaces. | `provider test` from a workspace-started shell reported missing `GOOGLE_API_KEY`; the same command worked when launched from the repo shell and then `cd` into the workspace. | Environment-specific. Campaign used repo-started shell commands. Docs could suggest globally exported keys or workspace-local env files. |
| LG-003 | P1 | Build | Fixed | `agentlab build` accepted the Verizon-like billing brief but produced generic ecommerce/order config and generic eval cases. | Baseline `configs/v002.yaml` routed billing prompts through `orders`/`recommendations`; generated evals asked about order numbers and cancellations. | Added billing-context detection and billing-specific config/eval synthesis in `runner.py`. Confirmation Build produced billing/autopay support routing and three billing eval cases. |
| LG-004 | P1 | Workbench build | Fixed | Live Workbench misclassified the billing brief as IT Helpdesk because "It should..." matched an `it ` substring heuristic. | Baseline live Workbench returned `IT Helpdesk Workbench`, `IT Helpdesk Agent`, and `it_helpdesk_lookup` despite `execution_mode: live` with Google/Gemini. | Reworked domain inference in `builder/workbench.py` to check billing/telecom hints first and use word/phrase matching instead of raw `it ` substring matching. |
| LG-005 | P1 | Workbench live visibility | Fixed | Workbench text output did not clearly say whether a candidate came from live provider execution or deterministic/mock paths. | Baseline `workbench show` made readiness visible but did not show live provider/model execution status. | `cli/workbench_render.py` now prints execution status such as `Execution: live via google:gemini-2.5-pro`. |
| LG-006 | P1 | Workbench save / Eval handoff | Fixed | `workbench save` generated eval YAML as a bare list, but `EvalRunner` expects `cases:`. The saved eval file could be ignored, causing starter evals to run. | Baseline saved eval file was a YAML list; live Eval against the saved config ran starter cases instead of the generated Workbench cases. | `builder/workspace_config.py` now writes `{"cases": [...]}` and normalizes generated cases. Tests assert the file is loadable by `EvalRunner`. |
| LG-007 | P1 | Workbench bridge | Fixed | `workbench bridge --eval-run-id ...` forgot the materialized config/eval paths after `workbench save`, so the handoff still looked like it needed a save. | Baseline bridge with eval run ID showed `needs_materialization` despite `configs/v003.yaml` and generated eval cases existing. | Workbench now records `materialized_candidate`; bridge reads it when explicit paths are omitted and recommends Optimize after an eval run ID is present. |
| LG-008 | P2 | Eval guidance | Fixed | `eval run --output-format json` pointed to deprecated `agentlab improve` instead of the active Optimize command. | Baseline Eval JSON `next` field said `agentlab improve`. | `runner.py` now recommends `agentlab optimize --cycles 3` in text and JSON eval output. |
| LG-009 | P1 | Workbench config compilation | Fixed | Saved Workbench billing configs leaked billing terms into ecommerce/order routing and disabled FAQ despite billing/fee/tax/autopay tool text. | Confirmation v003 still routed `bill`/`charges` to `orders` and kept `faq_enabled: false`. | `builder/workspace_config.py` now applies billing-first support routing, removes billing terms from orders, preserves original source prompt, and enables FAQ for billing explanation tool text. Confirmation v004 had billing support routing and FAQ enabled. |
| LG-010 | P2 | Workbench iteration source preview | Open | A post-iteration generated source preview can still omit existing tools/guardrails even when the canonical agent card contains them. | Confirmation `workbench iterate` kept the billing agent/tool/guardrail in JSON, but latest source artifact still rendered `tools=[]` and `# No tools configured yet`. | Product polish remains. The saved runtime config/eval path works, but source-artifact rendering should preserve canonical tool/guardrail details through iteration. |
| LG-011 | P2 | External provider reliability | Open | A strict full-suite live Eval hit Gemini HTTP 503. The CLI correctly refused mock fallback, but the user experience remains dependent on provider availability. | `eval run --config v004 --require-live --output-format json` failed with `HTTP Error 503: Service Unavailable`; generated-dataset retry succeeded live. | External/transient. Could improve retry/backoff guidance, but no mock fallback occurred. |
| LG-012 | P1 | Agent quality / safety | Open | The billing agent still fails one generated safety eval; Optimize improves score but rejects the candidate because the safety hard gate fails. | Strict live generated-dataset Eval: 2/3 passed, safety 0.6667, composite 0.5267. Optimize cycle improved score but was discarded with `Safety hard gate failed: 1 safety failures`. | This is correct gate behavior and honest CLI feedback. More agent-policy iteration is still needed to clear the safety case before broad deployment. |

## Severity Guide

- P0: Blocks the live golden path completely.
- P1: Allows progress only with confusing manual intervention, hidden knowledge, or materially wrong artifacts.
- P2: Paper cut that slows or weakens the experience but does not block the path.

## Live Baseline Evidence

- Workspace: `/tmp/agentlab-live-cli-golden-path-codex-20260413011616/verizon-billing-support-codex`
- Mode: live.
- Provider: Google / `gemini-2.5-pro`.
- Provider check: passed when launched from the repo shell with the real `GOOGLE_API_KEY` in environment.
- Build: completed, but produced generic ecommerce/order artifacts.
- Workbench build: live Gemini run completed, but produced IT Helpdesk identity because of domain inference.
- Workbench iterate/save/bridge: completed, but saved config/eval and bridge handoff were confusing.
- Eval: strict live path ran, but not against the intended generated cases due eval YAML shape.
- Optimize: ran but the flow guidance was harder than necessary.
- Deploy: local canary deploy worked once a config existed.

## Live Confirmation Evidence

- Workspace: `/tmp/agentlab-live-cli-golden-path-codex-confirm-20260413013429/verizon-billing-support-codex-confirm`
- Mode/provider checks: `mode show`, `provider test`, and `doctor` reported live Google/Gemini readiness.
- Build: generated billing-aware config and billing eval cases.
- Workbench build: created `Phone Billing Support Workbench` with live Gemini execution metadata.
- Workbench save: produced `configs/v004.yaml` and `evals/cases/generated_build.yaml` with `cases:`.
- Eval: generated billing dataset ran in strict live mode with run ID `22d262d5-040`.
- Optimize: ran one cycle and rejected unsafe candidate through the hard gate.
- Deploy: created release `rel-0d223280` and canary-deployed v004 at 10% traffic.
