# Live UI Golden Path Summary - Codex

Date: 2026-04-13
Branch: feat/live-ui-golden-path-codex
Scenario: Verizon-like phone-company billing-support agent.
Mode: Live mode only.

## What Was Tested Live

- Started this branch's AgentLab server on `http://127.0.0.1:8010` with `AGENTLAB_WORKSPACE=/Users/andrew/Desktop/agentlab-live-ui-golden-path-codex`.
- Confirmed `/api/health` reported `mock_mode: false`, `real_provider_configured: true`, and workspace root equal to this branch.
- Confirmed `/api/setup/overview` reported effective live mode, OpenAI unset, Anthropic unset, and Google configured for `gemini-2.5-pro`.
- Built a Verizon-like phone-company support agent in the Build UI.
- Continued the saved Build candidate into Workbench, refined it, and saved it as `configs/v008.yaml`.
- Opened Eval from Workbench and verified the selected agent was fetchable as `agent-v008`.
- Ran a full eval that completed but exposed mixed-mode fallback.
- Added strict-live handling and reran a one-case generated eval in live mode: task `be3663da-0bc`, result `322dc686-85e`, `mode: live`, 1/1 passed, composite 0.57, 2319 tokens, warnings empty.
- Opened Optimize from Eval for `agent-v008` and eval task `be3663da-0bc`.
- Ran standard Optimize task `0d18c459-7f3`; it completed no-op.
- Ran forced Optimize task `1fa5a010-38e`; it completed rejected by safety hard gate.
- Opened Deploy, selected v8, and verified final browser POST body `{"version":8,"strategy":"canary"}`.
- Verified final `/api/deploy/status` reported `canary_version: 8`, `total_versions: 10`, v8 status `canary`, and pre-fix duplicate v9/v10 retired.

## Key UX / Product Gaps Found

- Build could generate an unrelated finance agent from a phone billing prompt.
- Build -> Workbench could display correct handoff context while materializing an unrelated IT Helpdesk project.
- Workbench iteration did not reliably replace an inherited domain model.
- Workbench -> Eval could route through synthetic Workbench IDs that the backend cannot fetch.
- Eval progress looked stuck on long live runs.
- Eval could silently become mixed-mode after provider failures, making live evidence ambiguous.
- Eval summary could present stale historical completion state.
- Optimize/Improve did not produce a clear user action when a strict-live eval scored poorly.
- Deploy status could miss fresh Workbench-saved versions.
- Deploy UI could duplicate a selected saved version instead of marking it canary.
- Deploy canary state lacks production confidence when there is no baseline, traffic, or external deploy target.

## What Was Fixed

- Added phone billing domain support across generation fallback, Workbench inference, Workbench agent defaults, harness templates, and generated source model handling.
- Preserved original Build prompt and Gemini model through the Build -> Workbench handoff.
- Made Workbench -> Eval use a real saved `agent-vNNN` ID instead of a synthetic Workbench ID.
- Added per-case Eval progress updates.
- Added strict live eval support through `require_live` and per-call fallback refusal.
- Scoped Eval summary to the active/current run.
- Surfaced failed eval row error text.
- Refreshed Deploy's disk-backed version manager before status and actions.
- Made backend deploy mark selected existing versions as canary.
- Made frontend deploy send selected version payloads for canary and immediate deploys.

## What Still Remains Hard Or Blocked

- Port 8000 was occupied by another checkout, so the campaign used port 8010.
- This worktree needed an ignored `.agentlab` marker plus explicit `AGENTLAB_WORKSPACE` to avoid parent workspace discovery.
- Standard Optimize returned no-op for a poor one-case strict-live eval.
- Forced Optimize rejected its candidate on safety hard gate and did not create a pending review proposal.
- Local Deploy can mark v8 canary, but promotion should not be performed here because there is no active baseline and no observed canary traffic.
- External production deployment was not available from this environment.

## Tests / Verification Run

- Backend focused and integration tests for phone billing generation, Workbench handoff, Eval strict-live handling, Eval request models, generated eval API, Deploy status refresh, and Deploy selected-version canary: 151 passed.
- Frontend tests for Build, AgentWorkbench, EvalRuns, Deploy, and API hooks: 63 passed.
- Python compile checks for modified backend route/model/eval files passed.
- `git diff --check` passed.
- `cd web && npm run build` passed, with only the existing Vite large chunk warning.
- Live browser re-verification with Playwright against `http://127.0.0.1:8010` passed for the critical path and final Deploy check.

## Branch And Commit

- Branch: `feat/live-ui-golden-path-codex`
- Commit: `fix(live-ui): harden golden path handoffs`; final pushed hash is reported in the final response.
