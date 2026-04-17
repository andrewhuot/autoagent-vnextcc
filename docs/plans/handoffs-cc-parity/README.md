# Claude-Code Parity Handoffs — Parallelism Map

Six phases, one prompt each. Paste the matching file's prompt into a fresh Claude Code session at the repo root (`/Users/andrew/Desktop/agentlab`).

Source plan: `docs/plans/2026-04-17-claude-code-parity-roadmap-v2.md`.

## Sequencing

```
P0 ─┬─> P0.5 ─┬─> P1 ─┬─> (everything else)
    │        │      │
    │        │      └─> P2 (compaction + memory)
    │        │
    │        └─> P3 (classifier + MCP transports)     ← can start after P0.5
    │
    └─> P4 (sessions + paste/image)                   ← can start after P0
    └─> P5.c per-tool cost                            ← can start after P0.5
    └─> P5.a output styles, P5.b vim                  ← can start after P0
```

## What must be sequential

| From | To | Why |
|---|---|---|
| P0 | P0.5 | P0.5 reads Gemini/OpenAI/Anthropic keys + provider defaults from the new `Settings` cascade. If P0.5 ships first, it'll re-hardcode env vars and we'll do it twice. |
| P0 | P1 | P1 wires new hook events (`beforeTool`/`afterTool`) the orchestrator fires at dispatch time. Needs the hook contract from P0. |
| P0.5 | P1 | P1's streaming tool dispatcher consults `capabilities.parallel_tool_calls`. Without the capability descriptor, dispatcher logic branches on provider strings — tech debt. |
| P0.5 | P2 | P2's compaction reads `capabilities.max_context_tokens` and uses the active-family cheap model for the digest (Haiku / gpt-4o-mini / Gemini Flash). |
| P0 | P3 | P3 writes permission rules back to `<project>/.agentlab/settings.json` via the cascade's write path. |
| P0.5 | P3a | The classifier needs `capabilities` to know which tools are auto-approvable per provider. |
| P0 | P4 | P4 session paths read from `Settings.sessions.root` with the settings cascade as source of truth. |
| P0.5 | P5c | Per-tool cost needs the cross-provider pricing table landed in P0.5e. |

## What can run in parallel

Once P0 + P0.5 are both on master:

- **P1 (streaming dispatch + structured diff)** and **P3 (classifier + MCP)** can go in parallel — no file overlap except the settings schema (both *read* but don't *modify* it).
- **P4 (sessions + paste/image)** can go in parallel with P1 *and* P3 — touches `cli/sessions/`, `cli/paste/`, and `cli/workbench_app/resume_slash.py` / `input_router.py`. The only overlap risk is `input_router.py` if P1 adds streaming-side input plumbing; resolve by landing P1's router change first.
- **P5 sub-phases are independent of each other and of P1-P4** once prereqs are met:
  - P5a output styles: after P0 (reads a settings key).
  - P5b vim mode: after P0 (reads a settings key).
  - P5c per-tool cost: after P0.5 (needs pricing table).
- **P2 (compaction + memory)** should NOT run in parallel with P1 — both touch `cli/llm/orchestrator.py` at the same call site (post-turn hook for compaction, pre-dispatch for streaming). Land P1 first, then P2.

## Suggested wall-clock schedule

| Week | Track A | Track B |
|---|---|---|
| 1 | P0 | — |
| 2 | P0.5 | — |
| 3 | P0.5 | — |
| 4 | P1 | P3 |
| 5 | P1 | P3 + P4 |
| 6 | P2 | P4 |
| 7 | P2 | P5a + P5b + P5c |

One engineer: ~8-12 weeks serial. Two engineers parallelized: ~4-5 weeks after P0/P0.5 land (3 weeks serial lead-in).

## Handoff files

- [P0 — Settings cascade + hook contract](P0-settings-hooks.md)
- [P0.5 — Cross-provider parity](P0.5-provider-parity.md)
- [P1 — Streaming tool dispatch + structured diff](P1-streaming-diff.md)
- [P2 — Compaction + memory extraction](P2-compaction-memory.md)
- [P3 — Classifier + MCP transports](P3-classifier-mcp.md)
- [P4 — Sessions + paste/image store](P4-sessions-paste.md)
- [P5 — Output styles + vim + cost detail](P5-polish.md)

## One-line invariants that span all handoffs

Every subagent dispatched by every handoff must preserve:

1. **Snapshot stability.** `tests/test_system_prompt.py` must continue to pass byte-for-byte. New kwargs default to `None`/off.
2. **`AGENTLAB_NO_TUI=1` escape hatch.** CI cannot break.
3. **Python 3.11** via `.venv/bin/python` (or `uv run python`). Don't add a different Python path.
4. **TDD.** Failing test → minimal impl → passing test → conventional commit. Never batch.
5. **Never commit to master.** Use the feature branch the handoff names.
6. **Pure helpers first, Textual wrappers second.** Tests must not require a running event loop.
7. **Capability matrix.** Any feature that touches the model harness must pass the three-provider fake-SDK test case (Anthropic, OpenAI, Gemini).
