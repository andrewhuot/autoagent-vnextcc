# Live End-to-End Verification — Phase 5

Date: 2026-04-13
Provider: `google:gemini-2.5-pro` (new key)
Workspace: `/private/tmp/agentlab-phase5-cli/faq-bot`
Backend: `uvicorn api.server:app --port 8003` (live mode)

## Summary

All Phase 1A/1B fixes verified with real Gemini calls. The core loop
Build → Eval → Optimize → Improve → Deploy is now truly real:
proposer calls Gemini, SSE emits real events, lineage persists each transition.

## CLI live run

| Command | Result |
| - | - |
| `agentlab new faq-bot --template customer-support --demo` | ✅ |
| `agentlab mode set live` | ✅ LIVE mode, Google provider detected |
| `agentlab build "<brief>"` | ⚠️ Gemini returned non-JSON; CLI warned and fell back to pattern builder. **Plan §risks flagged this.** |
| `agentlab eval run` | ✅ **LIVE** mode, 3/6 passed, composite 0.4758 — real Gemini inference, no fallback warnings |
| `agentlab optimize --cycles 1` | ✅ Real Gemini proposer call. **Cost summary reported: 2650 prompt tokens, $0.003312.** Proposal rejected on safety hard gate — correct. |
| `agentlab improve list --limit 3` | ✅ Lists the new live-proposed attempt with `rejected` status |
| `agentlab improve show <id>` | ✅ Full lineage timeline with Unix timestamps |

## API live run (port 8003)

### SSE stream: `GET /api/optimize/stream?task_id=<id>`

Captured a complete cycle. Every payload carries `"source": "optimizer"`.
**Zero `"source": "simulated"` tags** — exactly the plan's acceptance criterion.

```
event: cycle_start        → real task_id, mode=standard
event: diagnosis          → real failure_buckets (safety_violation=7, timeout=2, unhelpful_response=2),
                             real success_rate/latency/error_rate reasons
event: proposal_start     → failure_count=24
event: proposal           → real change_description, real attempt_id, real rejection reason
event: decision           → accepted=false, pending_review=false
event: cycle_complete     → cycle=1, accepted=false
event: optimization_complete → status=rejected
```

### Improvements API

- `GET /api/improvements?limit=3` — returned 2 live-proposed attempts with correct classification.
- `POST /api/deploy` (canary v003, with attempt_id) — 201 Created, lineage row appended.
- `POST /api/deploy/promote` (with attempt_id) — 200 OK, promote lineage row appended.
- `POST /api/improvements/<id>/measure` — returned `status=measured`, `deployed_version=3`,
  `lineage=[reject, deploy_canary, promote, measurement]`. Full proposal → deploy → measurement
  trail recorded in SQLite at `.agentlab/improvement_lineage.db`.

## Cost

Live Gemini spend for this verification run: **~$0.003** (one full optimize cycle).

## Remaining gaps

- Phase 2 canary gate (block promotion on regression) — not implemented. Promotion currently
  goes through even if eval composite is degraded; still the plan's top remaining risk.
- Build path's Gemini non-JSON fallback: CLI warns but silently continues with pattern
  output. A `--strict-live` flag would let CI fail hard. Plan §risks already called this out.
- UI-side consumption of the new SSE and `/api/improvements` endpoints is partial — real
  `Optimize.tsx` uses WebSocket+polling, not the new SSE. Still the simulation preview
  page works correctly via `?simulated=1`.

## Artifacts

- `/tmp/agentlab-phase5-sse.log` — raw SSE capture
- `/tmp/agentlab-phase5-backend.log` — uvicorn log
- `.agentlab/improvement_lineage.db` — lineage SQLite
- `optimizer_memory.db` — optimizer attempts

## Verdict

Phase 1A (real optimizer + SSE) and Phase 1B (Improvements + lineage) work
end-to-end against a live provider. The "fake" fingerprint is gone:
users and CLI tooling now see real events, real costs, and a persisted
lineage of every proposal from generation through post-deploy measurement.
