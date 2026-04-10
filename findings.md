# Codex Ralph Build Live UX Campaign Findings

## Source Reconnaissance

- `/build` is the canonical Build entry. Legacy `/builder`, `/builder/demo`, `/agent-studio`, `/assistant`, and `/intelligence` redirect into `/build` tab variants through `web/src/lib/navigation.ts` and `web/src/App.tsx`.
- `web/src/pages/Build.tsx` contains four tabs: prompt, transcript, builder-chat, and saved-artifacts. The builder-chat path is the closest to the requested managed-agent workflow.
- Builder chat state is held in `BuilderChatWorkspace`: messages, latest `BuilderSessionPayload`, preview result, save result, saved agent, and a config modal flag.
- Builder chat flow calls `/api/builder/chat`, `/api/builder/preview`, `/api/builder/export`, and saves through the shared `/api/agents` hook with `source: built` and `build_source: builder_chat`.
- Prompt/transcript flow calls intelligence generation/refinement APIs, then shared preview/save/eval handoff.
- Eval handoff is already wired: Build navigates to `/evals?agent=<id>&new=1` or `/evals?agent=<id>&generator=1` with selected agent in router state; `EvalRuns` uses that state to preselect the agent and show a first-run panel.
- Existing coverage includes `web/src/pages/Build.test.tsx`, `web/src/pages/Builder.test.tsx`, `web/tests/builder-flow.spec.ts`, and backend `tests/test_builder_chat_api.py`.
- Prior docs explicitly flagged a trust gap around mock/live behavior and a previous builder rebuild plan that intentionally created a single conversational builder with mock-friendly APIs.

## Runtime Journey Findings

- Setup had not been run in this clone. `./setup.sh` created `.venv`, `web/node_modules`, `.env`, and demo data successfully.
- Runtime started with `./start.sh`; final browser verification used `http://localhost:5180` with backend `http://localhost:8000` because the default frontend port was already occupied during the campaign.
- `/api/health` reports `mock_mode: true`, `real_provider_configured: false`, and mock reason `Mock mode explicitly enabled by optimizer.use_mock.` The repo-local `agentlab.yaml` has `optimizer.use_mock: true`, and `.env` has blank provider keys. Live mode was therefore blocked by local runtime config/provider setup.
- Browser journey on `/build?tab=builder-chat` succeeded through initial draft, preview, save, and eval handoff.
- The preview/test step exposed a trust problem: after building/refining an airline booking-change agent, the mock preview answered with generic order-support copy (`I can help with your order`) for a delayed-flight change request. The UI correctly labels mock mode, but the preview is too generic to help a user decide whether the agent improved.
- Save-and-eval handoff worked: `Save & Run Eval` saved the draft and navigated to `/evals?agent=agent-v003&new=1`, where Eval Runs showed the saved draft selected and the first-run form ready.

## Product/UX Failure Modes

- The original UI had pieces of an iteration loop, but the loop was not visually treated as the primary object. Users could chat, test, view config, save, and eval, yet there was no persistent sense of iteration count, last change, quality signal, or next best action after a preview/refinement.
- Config visibility is binary: hidden behind a modal or full raw YAML/JSON. That protects the main panel from intimidation, but it also removes lightweight “what changed?” inspection from the core loop.
- Preview results show the agent response and runtime metadata, but they do not turn that evidence into a decision: keep refining, save, generate evals, or validate live.
- The fallback preview path is honest about being simulated, but not helpful enough. A simulated response should still reflect the built domain and selected tool/routing signals so iteration has momentum.

## Implementation Decisions

- Make the iteration loop visible above the Builder Chat workspace instead of relying on scattered controls. The loop now calls out the current iteration, last user change, latest preview signal, and next action across Draft, Inspect, Test, and Save/Eval.
- Add a lightweight draft inspection panel next to the conversation/preview. It summarizes the system prompt, tools, routes, policies, and eval checks so users can inspect what changed without opening raw YAML first.
- Keep raw config access available through the existing modal/download path for deeper review, but make the default Build posture more like an agent workbench than a static form.
- Improve mock-preview usefulness without pretending it is live: airline Build drafts now return airline-specific preview copy, expose configured tool names, and pick the most relevant configured tool for booking changes, cancellations, and flight status.
- Preserve the existing save/export/eval architecture. The high-leverage UX fix did not require new persistence contracts; it made the existing handoff clearer and easier to trust.

## Verification Evidence

- Frontend regression: `npm test -- src/pages/Build.test.tsx -t "shows the current iteration loop"` passed.
- Frontend tool-call regression: `npm test -- src/pages/Build.test.tsx -t "shows configured tool names"` passed.
- Frontend related suite: `npm test -- src/pages/Build.test.tsx src/pages/Builder.test.tsx src/lib/builder-chat-api.test.ts` passed with 24 tests.
- Backend targeted regression: `.venv/bin/python -m pytest tests/test_builder_chat_api.py -k preview_uses_built_domain_in_mock_mode -q` passed.
- Backend related suite: `.venv/bin/python -m pytest tests/test_builder_chat_api.py tests/test_builder_api.py tests/test_build_artifact_store.py -q` passed with 49 tests.
- Syntax check: `.venv/bin/python -m py_compile evals/fixtures/mock_data.py` passed.
- Playwright maintained flow: `PLAYWRIGHT_BASE_URL=http://localhost:5180 npx playwright test tests/builder-flow.spec.ts` passed with 2 tests.
- Manual browser verification on `http://localhost:5180/build?tab=builder-chat` covered create, inspect, test, mock fallback, configured `Tool: change_booking`, save, and `/evals?agent=agent-v003&new=1` handoff to `Start First Evaluation`.
- Full web build remains blocked outside this Build scope: `npm run build` fails on unused `NormalizedFallback` imports in `src/lib/provider-fallback.test.ts` and `src/pages/AgentImprover.tsx`.
