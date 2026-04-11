# Findings & Decisions

## Agent Builder Workbench Campaign Findings

### Initial State

- Branch is `feat/agent-builder-workbench-codex`.
- HEAD is `f5c14c74d14d5a7a145ffe3865f85c0e8894ed41`, matching `origin/master` and the requested base commit.
- Local `master` is older (`f15f0b36a2fb86f103a88aa296b5d7a8cb8adff7`), so this campaign will avoid using it as a base or merge target.
- Initial worktree was clean.
- No project-local `AGENTS.md` file was found in this checkout; follow the user-supplied global instructions and existing repo style.
- Memory quick pass found no relevant hits for Workbench/AgentLab in `/Users/andrew/.codex/memories/MEMORY.md`.

### Product Requirements

- The Workbench must be a new feature in addition to current AgentLab, not a destructive replacement.
- It should reuse current Build, Agent Improver, Eval Runs, Results Explorer, Compare, Optimize, Improvements, Trace, and Deploy surfaces where feasible.
- Canonical model comes first: natural-language changes patch structured state, then generated source/config/export previews derive from that state.
- Conversation and change planning live on the left; the current system truth lives on the right.
- Show a plan before applying, and run validation/testing after applying.
- Label components and exports as portable, ADK-only, CX-only, or invalid for the selected target.
- MVP right-pane surfaces: Preview, Agent Card, Source Code, Tools, Callbacks, Guardrails, Evals, Trace, Test Live, Deploy, Activity/Diff.

### Repo Reconnaissance Findings

- `/build` is the existing unified Build workspace. Its builder-chat tab is the closest current primitive: it calls `/api/builder/chat`, `/api/builder/preview`, exports config, saves via `/api/agents`, and hands off to Eval Runs.
- `BuilderChatService` stores in-memory sessions and converts natural language into generated config. It is useful but not canonical-model-first: follow-up turns mutate `generated_config` directly through `TranscriptIntelligenceService.chat_refine`.
- `builder/workspace_config.py` already maps generated Build contracts into real AgentLab runtime configs, preview runs, saved versions, and generated eval cases. This should be reused for Workbench preview/test/save.
- `/api/agents` already saves builder sessions or config dictionaries into the shared agent library/versioning path and returns agent records suitable for Eval Runs.
- `/evals`, `/traces`, and `/deploy` already have page/API surfaces and React Query hooks. Workbench can link/handoff to those routes and show compact embedded summaries rather than duplicating all logic.
- ADK import/export routes and CX import/export/deploy/preflight routes already exist. For MVP export previews, a canonical compiler can produce representative ADK/CX artifacts without requiring a live ADK snapshot or CX credentials.
- `cx_studio/compat.py` already contains ADK/CX compatibility semantics. Workbench can use its status categories to label canonical components as portable, ADK-only, CX-only, or invalid for target.
- Navigation metadata lives in `web/src/lib/navigation.ts`, route wiring in `web/src/App.tsx`, and sidebar icons in `web/src/components/Sidebar.tsx`.
- Frontend tests use Vitest + Testing Library with inline `fetch` stubs. Backend route tests commonly create a small FastAPI app and include the target router directly.

### Architecture Direction

- Add a new `/workbench` route and navigation entry under Build, keeping `/build` intact.
- Add a backend Workbench service/store under `builder/` that owns canonical agent project state, versions, activity, exports, compatibility labels, and validation/test results.
- Add API endpoints under `/api/workbench` for create/get, plan, apply, test, export preview, history, and rollback.
- Keep generated ADK/CX source/config as compiler output from the canonical model. Do not use generated files as the source of truth.
- On apply, create a new immutable version, compile outputs, and run deterministic validation/test immediately.

### Implementation Findings

- Added `builder/workbench.py` as the canonical model service/store/compiler. It owns structured project state, plan inference, apply operations, export previews, compatibility diagnostics, validation, activity, versions, and rollback.
- Added `/api/workbench` routes for project create/default/get, plan, apply, test, and rollback.
- Workbench state persists to `.agentlab/workbench_projects.json` by default; tests inject an isolated `WorkbenchStore`.
- Export previews are compiler output from canonical state:
  - ADK: `agent.py`, `tools.py`, and `agentlab.yaml`.
  - CX: `agent.json` and `playbook.yaml`.
- Compatibility diagnostics label canonical objects as `portable`, `adk-only`, `cx-only`, or `invalid`. A local shell tool is ADK-only generally and invalid for the CX target.
- Added `web/src/pages/AgentWorkbench.tsx` with the PRD two-pane shape: left conversation/plans/progress/history, right truth tabs for all MVP surfaces.
- Added `web/src/lib/workbench-api.ts` as a typed frontend client.
- Added `/workbench` route, Build navigation entry, simple sidebar inclusion, route metadata, and sidebar icon.

### Focused Verification

- `.venv/bin/python -m pytest tests/test_workbench_api.py -q`: 4 passed.
- `npm run test -- src/pages/AgentWorkbench.test.tsx src/lib/navigation.test.ts`: 12 passed.

### PRD Coverage

- Covered: new additive `/workbench` surface with the PRD two-pane model.
- Covered: canonical structured project model in backend state before generated outputs.
- Covered: natural-language requests generate structured change-plan cards before apply.
- Covered: applying a plan mutates the canonical model, creates a version, recompiles exports, and runs validation immediately.
- Covered: right-pane surfaces for Preview, Agent Card, Source Code, Tools, Callbacks, Guardrails, Evals, Trace, Test Live, Deploy, and Activity / Diff.
- Covered: portable / ADK-only / CX-only / invalid compatibility labels, including CX-invalid local shell tools.
- Covered: ADK export preview and CX export preview compiled from canonical state.
- Covered: version history and rollback affordance in the Workbench shell.
- Covered: reuse/handoff to existing Eval Runs, Trace, and Deploy surfaces through Workbench tabs and route links.

### Deferred Scope

- Direct save of a Workbench canonical project into the existing AgentLab agent library is not wired yet; the Deploy tab currently hands off to the existing eval/deploy routes.
- Eval execution remains deterministic Workbench validation plus route handoff, not a full generated eval run launched from the Workbench tab.
- Trace is based on Workbench validation events; it does not yet persist into the broader trace database.
- ADK/CX exports are preview artifacts, not downloadable packages or live CX deployments.
- The natural-language interpreter is deterministic MVP inference, not an LLM-backed semantic planner.

### Verification Results

- `.venv/bin/python -m pytest tests/test_workbench_api.py -q`: 4 passed.
- `npm run test -- src/pages/AgentWorkbench.test.tsx src/lib/navigation.test.ts`: 12 passed.
- `.venv/bin/python -m pytest tests/test_workbench_api.py tests/test_builder_chat_api.py tests/test_agents_api.py tests/test_api_server_startup.py -q`: 18 passed.
- `npm run test -- src/pages/AgentWorkbench.test.tsx src/lib/navigation.test.ts src/pages/Build.test.tsx src/components/Layout.test.ts`: 47 passed.
- `.venv/bin/python -m py_compile builder/workbench.py api/routes/workbench.py`: passed.
- `npm run build`: passed with the existing Vite large-chunk warning.
- `npx eslint src/pages/AgentWorkbench.tsx src/pages/AgentWorkbench.test.tsx src/lib/workbench-api.ts src/lib/navigation.ts src/lib/navigation.test.ts src/components/Sidebar.tsx src/App.tsx`: passed.
- `npm run test`: 45 files passed, 271 tests passed, with the existing jsdom navigation warning.
- `.venv/bin/python -m pytest -q`: 3556 passed, 4 failed, 19 warnings. The failures are unrelated to touched files: two mutation-count tests and one mutation registry test expect 13 operators while the current registry has 14, and one shell-script safety test did not observe port 5173 opening in time.
- `npm run lint`: failed on pre-existing repo-wide lint debt in untouched files. Touched-file ESLint passed separately.
- Browser sanity on `/workbench`: passed create-plan, plan-before-apply, apply-to-v2, automatic-test, right-tab, and ADK/CX export preview checks.

## Agent Improver Live UX Campaign Findings

### Requirements
- Pressure-test Agent Improver as an actual managed-agent workflow, not a polished one-shot demo.
- Verify user understanding, iterative guidance, state continuity, provider honesty, save/export/eval handoff, and recovery paths.
- Prefer live provider mode when feasible; document exact blocker if live execution is unavailable or rate-limited.
- Implement pragmatic, high-leverage improvements with regression tests and browser verification.

### Initial Environment Findings
- Branch is `feat/agent-improver-live-ux-ralph-codex`.
- Base HEAD is `f15f0b3 fix(eval): correct misleading status label, add back-nav, resolve step numbering conflict`.
- Initial worktree was clean.
- No project-local `AGENTS.md` file exists in this checkout.
- Previous root `findings.md` content is from a portability/readiness task; preserving it below for history while adding this campaign section.

### Research Findings
- Agent Improver primary implementation is `web/src/pages/AgentImprover.tsx` with local persistence helpers in `web/src/lib/agent-improver.ts`.
- Main tests live in `web/src/pages/AgentImprover.test.tsx` and `web/src/lib/agent-improver.test.ts`.
- Route wiring is in `web/src/App.tsx`, navigation metadata in `web/src/lib/navigation.ts`, and sidebar icon mapping in `web/src/components/Sidebar.tsx`.
- The feature appears frontend-heavy and likely uses the builder chat/session layer rather than a dedicated `agent-improver` backend route.
- Nearby relevant web APIs include `web/src/lib/builder-chat-api.ts`, `web/src/lib/builder-api.ts`, and provider fallback helpers.
- The builder backend exposes chat/session/export/save/preview endpoints under `/api/builder/*`, backed by `BuilderChatService`.
- Agent Improver saves through the shared agent library POST `/api/agents` path with `source: built`, `build_source: builder_chat`, and `session_id`.
- Eval handoff currently navigates to `/evals?agent=<id>&new=1` with navigation state `{ agent, open: 'run' }`; the eval page selects the agent and opens the run form.
- Eval generation already exists via `EvalGenerator` and the generated eval suite APIs, but Agent Improver does not carry draft eval intent into that generator.
- Runtime state: `agentlab.yaml` has `optimizer.use_mock: true`; `OPENAI_API_KEY` is present in the shell, but this workspace is explicitly pinned to mock mode.
- CLI live/provider inspection via `runner.py mode show` and `runner.py doctor` failed under the default `python3` because it is too old for PEP 604 type unions in this codebase, and `.venv/bin/python` does not exist in this checkout.

### Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Use planning files for the campaign | The task spans repo discovery, UX audit, browser testing, implementation, verification, commit/push, and notification. |
| Start with evidence before fixes | The prompt asks whether the feature actually works in real life; changes should be grounded in observed journey failures. |

### Issues Encountered
| Issue | Resolution |
|-------|------------|
| No prior session catchup data was emitted | Continued with a clean worktree and fresh discovery. |
| CLI provider inspection failed with `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'` under default `python3` | Record as environment blocker; use explicit newer Python if available for later backend checks. |
| New regression tests failed as expected | Proceed to implementation: real retry should resend, eval plan CTA should call builder chat, and eval handoff should open the generator with Agent Improver context. |
| Live builder request reached the provider path but returned `HTTP Error 429: Too Many Requests` | Preserve honest rate-limit/fallback UX, add real retry behavior, and verify local eval-plan generation still works on the same session. |
| Full Playwright surfaced stale route/health-check strictness in existing tests | Updated mock-honesty and intelligence browser checks to ignore expected Vite `net::ERR_ABORTED` module aborts and assert current `/assistant` redirect behavior. |
| Repo-wide ESLint fails on existing broad lint debt | Cleaned touched-file lint findings and recorded repo-wide lint as a remaining non-blocking issue. |

### Implementation Findings
- Rate-limit recovery was only a composer convenience: `Retry last request` repopulated text but did not actually retry the live builder request. The button now replays the last user request against the same builder session.
- Agent Improver lacked an explicit way to turn a promising draft into validation cases. Summary mode now exposes a `Generate eval plan` action when the live session can continue and no draft eval plan exists.
- Draft eval ideas were not meaningful in the handoff. Saved drafts with eval plans now route to `/evals?agent=<id>&generator=1&from=agent-improver` with state that opens the Eval Generator and explains the handoff.
- Eval Runs now distinguishes an Agent Improver handoff from a generic eval setup. The generator panel tells the user to formalize, review, and then run the saved config's eval suite.
- Existing `/assistant` browser coverage was stale because that legacy route now redirects to Build. The mock-honesty spec now verifies the current redirect plus Build preview-mode warnings.

### Visual/Browser Findings
- Added and passed a Playwright browser journey for Agent Improver: open route, create draft, generate eval plan, inspect config, download export, save, and land in Eval Generator with Agent Improver context.
- Full Playwright verification passes: 36 tests passed against local Vite at `http://127.0.0.1:5174`.
- Live/API probe used isolated API state on port 8010 to avoid polluting the checkout. The existing server on port 8000 is mock-pinned, and the isolated live-preferred server hit provider rate limiting.

### Verification Results
- `npm run test -- src/pages/AgentImprover.test.tsx src/pages/EvalRuns.test.tsx src/lib/agent-improver.test.ts src/lib/provider-fallback.test.ts src/components/EvalGenerator.test.tsx src/components/GeneratedEvalReview.test.tsx`: 74 passed.
- `npm run test`: 44 files passed, 264 tests passed. Output includes jsdom's known `Not implemented: navigation to another Document` message.
- `.venv/bin/pytest tests/test_builder_chat_api.py tests/test_agents_api.py tests/test_eval_generate_routes.py tests/test_generated_evals_api.py -q`: 31 passed.
- `npm run build`: passed; Vite still warns that the main chunk is larger than 500 kB.
- `npx eslint <touched files>`: passed.
- `npm run lint`: failed on pre-existing repo-wide lint debt in unrelated files plus broad React compiler rules; touched files were cleaned separately.
- `PLAYWRIGHT_BASE_URL=http://127.0.0.1:5174 npx playwright test`: 36 passed.

---

## Build Live UX Campaign Findings

### Source Reconnaissance

- `/build` is the canonical Build entry. Legacy `/builder`, `/builder/demo`, `/agent-studio`, `/assistant`, and `/intelligence` redirect into `/build` tab variants through `web/src/lib/navigation.ts` and `web/src/App.tsx`.
- `web/src/pages/Build.tsx` contains four tabs: prompt, transcript, builder-chat, and saved-artifacts. The builder-chat path is the closest to the requested managed-agent workflow.
- Builder chat state is held in `BuilderChatWorkspace`: messages, latest `BuilderSessionPayload`, preview result, save result, saved agent, and a config modal flag.
- Builder chat flow calls `/api/builder/chat`, `/api/builder/preview`, `/api/builder/export`, and saves through the shared `/api/agents` hook with `source: built` and `build_source: builder_chat`.
- Prompt/transcript flow calls intelligence generation/refinement APIs, then shared preview/save/eval handoff.
- Eval handoff is already wired: Build navigates to `/evals?agent=<id>&new=1` or `/evals?agent=<id>&generator=1` with selected agent in router state; `EvalRuns` uses that state to preselect the agent and show a first-run panel.
- Existing coverage includes `web/src/pages/Build.test.tsx`, `web/src/pages/Builder.test.tsx`, `web/tests/builder-flow.spec.ts`, and backend `tests/test_builder_chat_api.py`.
- Prior docs explicitly flagged a trust gap around mock/live behavior and a previous builder rebuild plan that intentionally created a single conversational builder with mock-friendly APIs.

### Runtime Journey Findings

- Setup had not been run in this clone. `./setup.sh` created `.venv`, `web/node_modules`, `.env`, and demo data successfully.
- Runtime started with `./start.sh`; final browser verification used `http://localhost:5180` with backend `http://localhost:8000` because the default frontend port was already occupied during the campaign.
- `/api/health` reports `mock_mode: true`, `real_provider_configured: false`, and mock reason `Mock mode explicitly enabled by optimizer.use_mock.` The repo-local `agentlab.yaml` has `optimizer.use_mock: true`, and `.env` has blank provider keys. Live mode was therefore blocked by local runtime config/provider setup.
- Browser journey on `/build?tab=builder-chat` succeeded through initial draft, preview, save, and eval handoff.
- The preview/test step exposed a trust problem: after building/refining an airline booking-change agent, the mock preview answered with generic order-support copy (`I can help with your order`) for a delayed-flight change request. The UI correctly labels mock mode, but the preview is too generic to help a user decide whether the agent improved.
- Save-and-eval handoff worked: `Save & Run Eval` saved the draft and navigated to `/evals?agent=agent-v003&new=1`, where Eval Runs showed the saved draft selected and the first-run form ready.

### Product/UX Failure Modes

- The original UI had pieces of an iteration loop, but the loop was not visually treated as the primary object. Users could chat, test, view config, save, and eval, yet there was no persistent sense of iteration count, last change, quality signal, or next best action after a preview/refinement.
- Config visibility is binary: hidden behind a modal or full raw YAML/JSON. That protects the main panel from intimidation, but it also removes lightweight "what changed?" inspection from the core loop.
- Preview results show the agent response and runtime metadata, but they do not turn that evidence into a decision: keep refining, save, generate evals, or validate live.
- The fallback preview path is honest about being simulated, but not helpful enough. A simulated response should still reflect the built domain and selected tool/routing signals so iteration has momentum.

### Implementation Decisions

- Make the iteration loop visible above the Builder Chat workspace instead of relying on scattered controls. The loop now calls out the current iteration, last user change, latest preview signal, and next action across Draft, Inspect, Test, and Save/Eval.
- Add a lightweight draft inspection panel next to the conversation/preview. It summarizes the system prompt, tools, routes, policies, and eval checks so users can inspect what changed without opening raw YAML first.
- Keep raw config access available through the existing modal/download path for deeper review, but make the default Build posture more like an agent workbench than a static form.
- Improve mock-preview usefulness without pretending it is live: airline Build drafts now return airline-specific preview copy, expose configured tool names, and pick the most relevant configured tool for booking changes, cancellations, and flight status.
- Preserve the existing save/export/eval architecture. The high-leverage UX fix did not require new persistence contracts; it made the existing handoff clearer and easier to trust.

### Verification Evidence

- Frontend regression: `npm test -- src/pages/Build.test.tsx -t "shows the current iteration loop"` passed.
- Frontend tool-call regression: `npm test -- src/pages/Build.test.tsx -t "shows configured tool names"` passed.
- Frontend related suite: `npm test -- src/pages/Build.test.tsx src/pages/Builder.test.tsx src/lib/builder-chat-api.test.ts` passed with 24 tests.
- Backend targeted regression: `.venv/bin/python -m pytest tests/test_builder_chat_api.py -k preview_uses_built_domain_in_mock_mode -q` passed.
- Backend related suite: `.venv/bin/python -m pytest tests/test_builder_chat_api.py tests/test_builder_api.py tests/test_build_artifact_store.py -q` passed with 49 tests.
- Syntax check: `.venv/bin/python -m py_compile evals/fixtures/mock_data.py` passed.
- Playwright maintained flow: `PLAYWRIGHT_BASE_URL=http://localhost:5180 npx playwright test tests/builder-flow.spec.ts` passed with 2 tests.
- Manual browser verification on `http://localhost:5180/build?tab=builder-chat` covered create, inspect, test, mock fallback, configured `Tool: change_booking`, save, and `/evals?agent=agent-v003&new=1` handoff to `Start First Evaluation`.
- Full web build remains blocked outside this Build scope: `npm run build` fails on unused `NormalizedFallback` imports in `src/lib/provider-fallback.test.ts` and `src/pages/AgentImprover.tsx`.
