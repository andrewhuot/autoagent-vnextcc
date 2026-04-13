# Live UI Golden Path Hardening Plan - Codex

Date: 2026-04-13
Branch: feat/live-ui-golden-path-codex
Mode: Live mode only. Mock mode was not used for the golden-path browser run.
Provider: Gemini via `GOOGLE_API_KEY` / `gemini-2.5-pro`; server started with `OPENAI_API_KEY` removed from its environment.
Scenario: Verizon-like phone-company support agent for explaining bills, plans, fees, charges, taxes, surcharges, credits, and common billing confusion.

## Mission

Run the AgentLab UI end to end in live mode, using the real Gemini API key available in the environment, and make the primary Build -> Workbench -> Evals -> Optimize / Improve -> Deploy journey materially easier to use.

## Non-Negotiables

- Use real browser automation or browser tooling.
- Do not test the golden path in mock mode.
- Use the concrete phone-company billing-support agent throughout the journey.
- Capture exact gaps and areas for improvement in working notes.
- Fix issues after discovery, then re-run the critical path.
- Add or update tests for behavior changes where useful.
- Commit and push the branch.
- Run the requested openclaw completion event when fully finished.

## Required Notes

- `working-docs/live-ui-golden-path-plan-codex.md`
- `working-docs/live-ui-golden-path-issues-codex.md`
- `working-docs/live-ui-golden-path-fixes-codex.md`
- `working-docs/live-ui-golden-path-summary-codex.md`

## Campaign Phases

| Phase | Status | Goal | Evidence |
| --- | --- | --- | --- |
| 1. Planning and repo orientation | Complete | Establish plan, read required docs, map relevant routes | Read required docs and route/page surfaces; created this plan |
| 2. Route and code reconnaissance | Complete | Identify Build, Workbench, Evals, Optimize/Improve, Deploy route contracts | Inspected Build, Workbench, EvalRuns, Optimize, Improvements, Deploy, API hooks, and backend routes |
| 3. Live environment startup | Complete | Start backend/frontend in live mode with Gemini env present | Server on `http://127.0.0.1:8010`, `mock_mode: false`, workspace rooted in this branch |
| 4. First live golden-path run | Complete | Build and iterate the billing agent through the core UI | Browser run exposed Build domain drift, Workbench IT-helpdesk drift, Eval handoff 404s, and Deploy stale status |
| 5. Root-cause and prioritization | Complete | Separate product bugs from environment/service limits | Issues recorded in the issues note with severity and evidence |
| 6. Regression tests and fixes | Complete | Add focused tests and implement targeted improvements | Backend and frontend tests added for each behavior change |
| 7. Live re-verification | Complete | Re-run critical path after fixes and compare experience | Live Build -> Workbench -> Eval -> Optimize -> Deploy rerun with `agent-v008` and strict-live eval run `be3663da-0bc` |
| 8. Finalization | In progress | Finish docs, commit, push, completion event | Awaiting final full verification, git commit/push, and openclaw event |

## Scenario Agent Brief

Build a Verizon-like support agent that helps customers understand phone bills:

- Explain monthly charges, taxes, surcharges, device payments, plan fees, add-ons, roaming, and one-time charges.
- Ask clarifying questions when a bill line item is ambiguous.
- Use a calm customer-support tone.
- Avoid inventing account-specific facts.
- Explain likely causes of common billing changes, then recommend where to verify exact account details.
- Be able to compare current plan, expected charges, and unexpected charges.

## Success Criteria

- A user can start from the Build surface and draft the scenario agent without needing internal product knowledge.
- The generated agent can be carried into Workbench with visible continuity of goal, instructions, and next steps.
- Workbench makes it obvious how to refine the agent and inspect artifacts.
- Evals can be generated or run for the scenario without confusing empty states or hidden prerequisites.
- Optimize/Improve offers actionable improvements tied to evaluation or agent behavior, or clearly explains why no accepted improvement exists.
- Deploy has a clear path to canary a selected saved candidate without duplicating it.
- Major blockers discovered in the first live pass are fixed or clearly documented as external/product follow-up.

## Root-Cause Discipline

For every bug or unexpected behavior:

1. Reproduce with exact steps.
2. Record visible symptom and console/network evidence.
3. Trace the route/component/API boundary involved.
4. Add a failing regression test where practical before production changes.
5. Implement the smallest focused fix.
6. Re-run the original path and relevant automated checks.

## Command Log

| Time | Command / Action | Result |
| --- | --- | --- |
| 2026-04-13 | `python3 /Users/andrew/.agents/skills/planning-with-files/scripts/session-catchup.py "$(pwd)"` | No unsynced catchup output |
| 2026-04-13 | `git status --short --branch` | Branch `feat/live-ui-golden-path-codex...origin/master`; initial tracked files clean |
| 2026-04-13 | Read `README.md`, `docs/features/workbench.md`, `docs/app-guide.md`, `docs/platform-overview.md`, `docs/UI_QUICKSTART_GUIDE.md` | Confirmed intended Build -> Workbench -> Eval -> Compare -> Optimize -> Improvements -> Deploy contract |
| 2026-04-13 | Inspected `web/src/App.tsx` and `web/src/lib/navigation.ts` | Confirmed simple-mode route map and legacy redirects |
| 2026-04-13 | Checked provider env | `GOOGLE_API_KEY` and `GEMINI_API_KEY` are set; `agentlab.yaml` had historical mock preference but workspace mode was set live |
| 2026-04-13 | Created ignored local runtime dirs/deps | Created `.agentlab`, `.venv`, and `web/node_modules` as ignored runtime artifacts |
| 2026-04-13 | `.venv/bin/python runner.py mode set live && .venv/bin/python runner.py mode show` | Workspace preference set to live |
| 2026-04-13 | `cd web && npm run build` | Frontend production build succeeded; large chunk warning only |
| 2026-04-13 | `AGENTLAB_WORKSPACE=... .venv/bin/python runner.py server --host 127.0.0.1 --port 8010 --workspace ...` | Combined app running for this worktree on `http://127.0.0.1:8010` |
| 2026-04-13 | `curl http://127.0.0.1:8010/api/health` | `mock_mode: false`, `real_provider_configured: true`, `workspace_valid: true`, workspace root is this branch |
| 2026-04-13 | `POST /api/settings/test-key {"provider":"google"}` | Gemini key valid for `gemini-2.5-pro` |
| 2026-04-13 | First browser pass through Build -> Workbench -> Eval | Found wrong financial/IT-helpdesk agent drift and Workbench Eval synthetic ID 404s |
| 2026-04-13 | Restarted server with `env -u OPENAI_API_KEY ... --port 8010` | Forced live Gemini-only server provider selection |
| 2026-04-13 | Re-run Build -> Workbench after fixes | Built `PhoneBillingSupportAgent`, preserved Gemini model and phone billing prompt through Workbench |
| 2026-04-13 | Re-run Workbench -> Eval | Saved candidate as `configs/v008.yaml`; Eval used `agent-v008` and fetched `/api/agents/agent-v008` successfully |
| 2026-04-13 | Live full-suite eval task `b2475f10-2e3` | Completed 50/55, composite 0.891, but mode `mixed`, exposing silent fallback risk |
| 2026-04-13 | Strict-live one-case eval task `be3663da-0bc` | Completed mode `live`, 1/1, run `322dc686-85e`, composite 0.57, no warnings |
| 2026-04-13 | Optimize from Eval task `0d18c459-7f3` | Completed no-op: `System healthy; no optimization needed (mode=standard)` |
| 2026-04-13 | Forced Optimize task `1fa5a010-38e` | Completed rejected candidate: safety hard gate failed, no pending review |
| 2026-04-13 | Browser Deploy before final frontend fix | Selecting v8 created duplicate canary v9/v10 because UI posted full config |
| 2026-04-13 | Browser Deploy after backend/frontend fix | Selecting v8 posted `{"version":8,"strategy":"canary"}` and made v8 canary without creating v11 |

## Environment Notes

- System `python3` is 3.9.6 and cannot run the repo code that requires newer Python features. The campaign used `.venv` with `/opt/homebrew/bin/python3.12`.
- Port 8000 was occupied by another AgentLab checkout. This campaign used the combined built UI served by this branch's backend on port 8010 to avoid the Vite dev proxy pointing at the wrong backend.
- This worktree initially lacked `.agentlab`, so workspace discovery could climb to `/Users/andrew`. An ignored `.agentlab` marker and explicit `AGENTLAB_WORKSPACE` kept all live evidence rooted in this branch.
- OpenAI and Google credentials existed in the shell. To honor the Gemini-only campaign requirement, the server was run with `OPENAI_API_KEY` unset.
