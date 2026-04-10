# Findings & Decisions

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

# Previous Findings & Decisions

## Requirements
- Build a shared, typed portability/readiness model for ADK and CXAS imports.
- Report imported, optimizable, read-only, unsupported, and exportable surfaces explicitly.
- Surface callbacks, graph topology, tool-code boundaries, and round-trip/export readiness.
- Preserve backward compatibility where practical.
- Add high-signal backend and API tests using realistic imported agents.

## Research Findings
- `adk/types.py` and `cx_studio/types.py` each define narrow `ImportResult` and `ExportResult` models today; neither carries a structured portability/readiness report.
- `adk/types.py` already models callback references on `AdkAgent`, but only as raw string fields and not as first-class import result metadata.
- `cx_studio/types.py` carries richer raw resource snapshots than ADK, which suggests a shared readiness model should allow per-platform evidence while staying generic.
- `api/models.py` is the central Pydantic contract file and will likely need additive models if route responses are upgraded.
- `adk/exporter.py` still operates on legacy keys like `instructions` and `generation_settings`, while `adk/importer.py` writes config with `prompts`, `generation`, `model`, and `tools`; the new reporting work should align these surfaces instead of hiding the mismatch.
- `cx_studio/exporter.py` has a concrete writable-field inventory in `_field_entries()` and `_apply_*()` methods, which can drive a truthful export capability matrix.
- `optimizer/surface_inventory.py` already defines which optimization surfaces are reachable, so importer-side readiness scoring can align to that vocabulary without inventing a separate surface taxonomy.
- `core/types.py` has a framework-neutral graph IR, but its node taxonomy is broader agent-system IR rather than import topology; a dedicated import topology model is likely cleaner than forcing flow/page/callback resources into unrelated node types.
- The shared portability package can stay framework-neutral and sit below API routes, which keeps ADK/CX layer boundaries intact while letting the API reuse the same report types directly.
- ADK import/export parity improves materially when exporter change detection accepts both the legacy keys (`instructions`, `generation_settings`) and the current importer keys (`prompts`, `generation`, `model`, `tools.*.description`).

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Favor a shared portability/readiness schema with source-specific evidence fields | The user requested a generic model reusable for ADK and CXAS. |
| Keep changes additive on import/export result types where possible | This preserves existing callers while allowing richer readiness reporting. |
| Treat export readiness as a first-class report derived from exporter reality | Customers need to know what can actually round-trip today, not what the platform might support eventually. |
| Use dedicated ADK and CX portability builder modules on top of shared report helpers | This keeps platform-specific topology and surface rules explicit while reusing scoring and matrix logic. |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| No prior session catchup data was emitted | Continued with a clean worktree and fresh discovery. |
| API route tests are environment-gated by `pytest.importorskip("fastapi")` | Ran them anyway as part of the focused suite; they were reported as skipped rather than silently omitted. |

## Resources
- `adk/types.py`
- `cx_studio/types.py`
- `api/models.py`
- `tests/test_adk_importer.py`
- `tests/test_adk_api.py`
- `tests/test_cx_studio.py`
- `tests/test_cx_studio_api.py`

## Visual/Browser Findings
- No browser or image inspection used for this task.
