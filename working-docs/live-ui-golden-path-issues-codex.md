# Live UI Golden Path Issues - Codex

Date: 2026-04-13
Branch: feat/live-ui-golden-path-codex
Scenario: Verizon-like phone-company billing-support agent.
Mode: Live mode only.

## Issue Index

| ID | Severity | Surface | Status | Summary |
| --- | --- | --- | --- | --- |
| ENV-001 | P1 | Startup / workspace discovery | Mitigated, not fixed | This worktree had no `.agentlab`, so API workspace discovery could climb to `/Users/andrew` |
| ENV-002 | P2 | Dev startup / ports | Confirmed, not fixed | `./start.sh` cannot use default 8000 while another AgentLab server owns it; Vite dev proxy still points at 8000 |
| LIVE-001 | P1 | Build / generation quality | Fixed | Live Build understood the name but generated financial-services behavior for a phone billing prompt |
| LIVE-002 | P0 | Build -> Workbench handoff | Fixed | Workbench wrapped the correct Build route context around an unrelated IT Helpdesk project |
| LIVE-003 | P1 | Workbench iteration | Fixed | Workbench follow-up could embed phone billing text while retaining IT Helpdesk identity/tools |
| LIVE-004 | P1 | Workbench -> Eval handoff | Fixed | Eval received a synthetic Workbench ID and repeatedly 404ed on `/api/agents/workbench-...` |
| LIVE-005 | P1 | Eval execution progress | Fixed | Eval stayed visually stuck at 10 percent during long live runs because progress was not updated per case |
| LIVE-006 | P2 | Provider selection | Mitigated | With OpenAI and Google keys present, Workbench preferred OpenAI until the server was restarted Gemini-only |
| LIVE-007 | P1 | Eval live integrity | Fixed | Long live eval could silently fall back to mixed/mock execution after provider failures |
| LIVE-008 | P2 | Eval results UI | Fixed | Eval summary could show unrelated historical completed runs instead of the current selected run |
| LIVE-009 | P1 | Optimize / Improve | Product gap remains | Non-forced Optimize treated a 57 composite one-case eval as healthy; forced Optimize produced a rejected safety-hard-gate candidate with no pending review |
| LIVE-010 | P1 | Deploy status | Fixed | Deploy did not see versions created by Build/Workbench after the deployer started |
| LIVE-011 | P1 | Deploy selected version | Fixed | Deploy UI selected v8 but posted a full config, creating duplicate canary versions instead of marking v8 canary |
| LIVE-012 | P2 | Deploy production confidence | Product gap remains | Local canary deploy works, but there is no active baseline, canary traffic, or external production target in this environment |

## Live Run Evidence

### First Browser Pass

- Server: `http://127.0.0.1:8010`, combined built UI from this branch.
- Health before run: `mock_mode: false`, `real_provider_configured: true`, `workspace_valid: true`.
- Google key validation: `valid: true`, model `gemini-2.5-pro`.
- Scenario prompt used in Build: Verizon-like phone-company support agent for confusing bills, plan charges, device payments, taxes, surcharges, one-time fees, roaming, credits, common bill changes, and safe clarification.
- Build API call: `POST /api/intelligence/generate-agent => 200 OK`.
- First Build output: agent name `BuildVerizonLikeAgent`, model `gemini-2.5-pro`, but config body was financial services/account-transfer/fraud/investment-advice oriented.
- Build save produced `configs/v001.yaml` and route link `/workbench?agent=agent-v001&agentName=BuildVerizonLikeAgent&configPath=.../configs/v001.yaml`.
- Workbench arrival banner said `BuildVerizonLikeAgent is being materialized as a fresh Workbench candidate`.
- Actual Workbench project title and artifacts were IT Helpdesk: `IT Helpdesk Workbench`, `IT Helpdesk Agent - role`, `it_helpdesk_lookup.py`, and `IT Helpdesk Agent regression suite`.
- Workbench follow-up asked to replace IT Helpdesk with Verizon billing support; turn completed but still retained IT Helpdesk identity/tools.
- Workbench Eval bridge navigated to Eval with `agentName=IT Helpdesk Agent` and a synthetic Workbench ID.
- Eval page repeatedly requested `/api/agents/workbench-wb-...-v3` and received 404 responses.

### Re-Run After Build / Workbench / Eval Fixes

- Server restarted with `OPENAI_API_KEY` unset so only Google/Gemini was configured.
- Build generated a `PhoneBillingSupportAgent` for the phone-company billing prompt rather than finance/IT.
- Build -> Workbench preserved the original prompt, the `gemini-2.5-pro` model hint, and the phone billing domain.
- Workbench materialized and saved `configs/v008.yaml`.
- Workbench -> Eval derived `agent-v008`; `/api/agents/agent-v008` returned 200.
- Full live-ish eval task `b2475f10-2e3` completed with result run `6864d19e-d4d`, 50/55 passed, composite 0.891, but mode `mixed`. This exposed the silent fallback issue.
- Strict-live one-case eval task `be3663da-0bc` completed with result run `322dc686-85e`, mode `live`, 1/1 passed, composite 0.57, `total_tokens: 2319`, warnings `[]`, details `keywords: missing expected keywords`.

### Optimize / Improve Evidence

- Eval -> Optimize opened `/optimize?agent=agent-v008&evalRunId=be3663da-0bc`.
- Standard Optimize task `0d18c459-7f3` completed immediately with `System healthy; no optimization needed (mode=standard)`.
- Forced Optimize task `1fa5a010-38e` completed with `REJECTED (rejected_constraints): Safety hard gate failed: 1 safety failures (mode=standard)`.
- The forced candidate change was only to append "Be thorough and detailed in your responses." to the prompt; it did not become a pending review item.
- Product gap: the user can reach Optimize/Improve, but the next useful action is unclear when standard Optimize no-ops and force Optimize rejects without a reviewable proposal.

### Deploy Evidence

- Before the Deploy fixes, `/api/deploy/status` did not see all saved Workbench versions from the running server context.
- After the Deploy status fix, Deploy listed 8 saved versions and v8 appeared in the dropdown.
- Before the frontend deploy-payload fix, selecting v8 and clicking Deploy created duplicate canary versions because the UI POSTed a full `config`.
- After the backend and frontend deploy fixes, browser network showed `POST /api/deploy` with request body `{"version":8,"strategy":"canary"}`.
- Final Deploy status after browser recheck: `canary_version: 8`, `total_versions: 10`, v8 status `canary`, v9/v10 status `retired`.
- v9 and v10 are runtime artifacts from pre-fix browser attempts; the fixed path did not create v11.

## Environment Or External Limits

- Port 8000 is occupied by another AgentLab server from `/Users/andrew/Desktop/agentlab`. This campaign used port 8010 with explicit workspace env.
- Root `python3` is Python 3.9.6. The campaign used `.venv/bin/python` created with Python 3.12.
- `ANTHROPIC_API_KEY` is missing. `GOOGLE_API_KEY` and `GEMINI_API_KEY` are available; `GOOGLE_API_KEY` was validated through the app.
- The live flow validates local canary deployment state, not an external production hosting target.

## Product Bugs Fixed

### LIVE-001 - Build generation is not faithful to the user domain

Severity: P1
Status: Fixed.

Impact:

- The first saved candidate was not fit for the requested job despite a reassuring generated name and success toast.
- Downstream Eval/Optimize/Deploy would have hardened the wrong domain.

Fix summary:

- Added telecom billing domain fallback and phone billing templates in Build, Workbench, harness generation, and transcript intelligence.
- Added tests that ensure phone billing prompts do not fall back to financial services or IT Helpdesk templates.

### LIVE-002 / LIVE-003 - Workbench materialization and iteration drift to IT Helpdesk

Severity: P0/P1
Status: Fixed.

Impact:

- The main requested journey broke at the first cross-surface bridge.
- Users saw a correct handoff wrapper around incorrect generated state.

Fix summary:

- Build now hands Workbench the original prompt and saved model hint.
- Workbench infers phone billing domain from the Build handoff and materializes phone billing artifacts.
- Workbench preserves the Gemini model from the saved Build config.

### LIVE-004 - Workbench Eval handoff generates a non-fetchable agent id

Severity: P1
Status: Fixed.

Impact:

- Eval looked ready while the underlying selected agent fetch was failing.
- Optimize context could inherit a synthetic, non-fetchable ID.

Fix summary:

- Workbench -> Eval now derives a real `agent-vNNN` ID from the materialized config version.
- Regression coverage confirms the bridge URL uses the saved agent version.

### LIVE-005 / LIVE-007 - Eval progress and live integrity

Severity: P1
Status: Fixed.

Impact:

- Long eval runs appeared stuck at 10 percent.
- Live runs could silently become mixed-mode if the provider failed mid-run.

Fix summary:

- Eval runner now accepts a progress callback and the API updates task progress per case.
- Eval API accepts `require_live`; the Eval UI sends it for non-mock active agents.
- `ConfiguredEvalAgent` now refuses per-call fallback when strict live is required.
- Strict-live browser rerun completed `be3663da-0bc` in mode `live`.

### LIVE-008 - Eval summary can show stale historical state

Severity: P2
Status: Fixed.

Impact:

- Operators could see a completed summary from unrelated historical evals while the current run was not complete.

Fix summary:

- EvalRuns now scopes journey summary to current run/selected run state instead of unrelated historical runs.
- Failed eval rows surface the first error line.

### LIVE-010 / LIVE-011 - Deploy does not canary the selected saved candidate

Severity: P1
Status: Fixed.

Impact:

- Deploy could miss fresh versions created by Workbench.
- Selecting a saved candidate could duplicate it as a new canary version.

Fix summary:

- Deploy route refreshes the disk-backed version manager and reconnects the deployer/canary manager before status/action calls.
- Deploy route can mark an existing selected version as canary.
- Frontend `useDeploy` posts `{version, strategy}` for canary rather than fetching and reposting the full config.
- Browser recheck proved v8 became canary without creating v11.

## Product Gaps Remaining

### LIVE-009 - Optimize / Improve does not yet create a clear next action

Severity: P2
Status: Remains.

Evidence:

- Standard Optimize from strict-live eval `be3663da-0bc` returned no-op despite composite 0.57 and missing-keyword details.
- Forced Optimize completed, but rejected its candidate on a safety hard gate and produced no pending review.

Impact:

- The path is reachable, but the operator does not get a clearly reviewable improvement when the eval score is poor.

Suggested follow-up:

- Let Optimize consume selected eval-run evidence directly for small generated suites.
- When a forced proposal is rejected, create a visible rejected proposal with reason, diff, and suggested next action.

### LIVE-012 - Deploy has no production confidence signal in this environment

Severity: P2
Status: Remains.

Evidence:

- Local Deploy can mark v8 as canary.
- Canary status has 0 conversations and no active baseline.

Impact:

- It is not responsible to promote the canary based on this environment alone.

Suggested follow-up:

- Make the Deploy page explicit when a canary has no baseline traffic and should not be promoted yet.
