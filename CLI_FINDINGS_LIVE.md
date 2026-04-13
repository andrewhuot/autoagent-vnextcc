# CLI Live Findings — Phase 0 Baseline

Date: 2026-04-13
Workspace: `/private/tmp/agentlab-phase0-cli/faq-bot`
Key: `GOOGLE_API_KEY` provided by user (see blocker below)

## Blocker
Provided Gemini key returns HTTP 403 "Your API key was reported as leaked" for all requests. Confirmed by direct curl and by `agentlab build`. CLI correctly falls back to pattern matcher with a warning — no silent failure in build step.

```
Live LLM call failed — used pattern fallback. Reason: HTTP Error 403: Forbidden
```

Eval/optimize similarly live-fall-back to mock and emit honest `eval_run.live_fallback_to_mock` warnings — good.

## Happy-path commands exercised

| Step | Command | Result |
| - | - | - |
| workspace | `agentlab new faq-bot --template customer-support --demo` | ✅ creates workspace, demo data seeded |
| mode | `agentlab mode set live` | ✅ writes `.agentlab/workspace.json` |
| status | `agentlab status` | ✅ |
| build | `agentlab build "..."` | ⚠️ live 403 → pattern fallback; writes `configs/v003.yaml` + `evals/cases/generated_build.yaml` |
| eval | `agentlab eval run` | ⚠️ mixed mode — falls back to `mock_agent_response` silently (after warning) |
| optimize | `agentlab optimize --cycles 1` | ✅ ran, diagnosed safety_violation, proposal rejected (`rejected_constraints`) — matches plan |
| review | `agentlab review list` | ✅ shows 1 demo card |
| deploy | `agentlab deploy --auto-review --yes` | ✅ auto-reviews, releases, deploys v003 as canary |
| workbench | `create / build / save` | ✅ materializes `configs/v004.yaml`; live Gemini path runs end-to-end when domain inference does not need LLM |

## CLI issues captured

1. `agentlab workbench build "<brief>"` creates a **second** workbench project rather than using the one just created by `workbench create` — project IDs `wb-6ebdd077` then `wb-e26950cc` for the same brief. UX footgun: users think `create` is prep work, but `build` alone suffices.
2. Workbench project name "Phone Billing Support Workbench" is synthesized even when the brief says "FAQ bot for billing and onboarding". Name ≠ brief; the optimizer downstream uses the name in the config card.
3. `eval_run.live_fallback_to_mock` warnings are ok but there is no non-zero exit code or `--strict-live` flag — a scripted pipeline cannot fail on mock drop.
4. `agentlab deploy --auto-review --yes` happily promotes v003 to canary on a workspace whose **eval just failed** ("Status: Degraded"). No verdict gate.
5. Every `agentlab ...` command ends with `Shell cwd was reset to /Users/andrew` — harmless but noisy.
6. No `agentlab improve ...` command exists. CLI exposes `review` and `optimize history` but there is no single surface that walks a proposal from diagnosis → accept → deploy → measurement.

## Truthiness probe (against live server on :8002)

- `/api/optimize/stream` → every `data:` payload contains `"source": "simulated"`. Confirmed SSE is canned fixture, not real optimizer events. Plan §1A correct.
- `/api/improvements` → 404. Endpoint missing. Plan §1B correct.
- `/api/what-if` → 404 on this server build. (UI_FINDINGS referenced it; likely gated by feature flag. Worth auditing.)
- `/api/health` with `GOOGLE_API_KEY` set reports `mock_mode: false`, `real_provider_configured: true`.

## Next
- Implement Phase 1A: kill canned SSE, flip Proposer default, thread eval evidence into Proposer.
- Implement Phase 1B: Improvements API + lineage tables.
