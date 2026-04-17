# Claude-Code Parity Roadmap v2

**Date:** 2026-04-17
**Author:** Planning pass (no code yet)
**Source-of-truth references:**
- AgentLab code: `/Users/andrew/Desktop/agentlab/cli/`
- Claude Code code: `/Users/andrew/Desktop/claude-code-main/src/`
- Prior parity work: `cli/workbench_app/` (already covers TUI default-on, permission overlay, slash autocomplete, status bar, checkpoints, task subsystem, /loop, daemon, doctor, CLAUDE.md loader). Do not redo these.

---

## 1. Current state (code, not docs)

AgentLab already has a credible Claude-Code-shaped REPL:

- **Entry:** `runner.py` Click group → `agentlab workbench` → `cli/workbench_app/app.py` chooses TUI (`tui/app.py`, Textual) vs line REPL (`cli/repl.py`).
- **Model harness:** `cli/llm/orchestrator.py` runs the streaming tool-use loop. Providers in `cli/llm/providers/` — **Anthropic is fully streaming + tool-use + thinking + prompt-cache; OpenAI is non-streaming (`complete()` only, events synthesized post-hoc via `events_from_model_response`); Gemini is a stub that raises `ProviderFactoryError`** (`factory.py:79-87`). Streaming events in `cli/llm/streaming.py` (TextDelta / ThinkingDelta / ToolUseStart/Delta/End / UsageDelta). Prompt cache in `cli/llm/caching.py`. Retries in `cli/llm/retries.py`.
- **Tools (~26):** file_read/write/edit, glob, grep, bash, web_fetch, web_search, todo_write, skill_tool, agent_spawn, schedule_wakeup, exit_plan_mode, config_read/edit, task_create/list/get/output/stop, mcp_bridge. Defined via a `Tool` ABC in `cli/tools/base.py`; executor in `cli/tools/executor.py`; permissions gated in `cli/workbench_app/tool_permissions.py`.
- **TUI:** Textual app with MessageList, StreamingMessage, BackgroundPanel, EffortIndicator, StatusFooter, InputArea. Permission dialog modal. Plan mode (`plan_mode.py`, `plan_gate.py`). Checkpoints (`checkpoint.py`, `transcript_checkpoint.py`, `transcript_rewind_slash.py`).
- **Slash commands:** `cli/workbench_app/slash.py` registry; ~30 slash files (`build_slash`, `eval_slash`, `optimize_slash`, `loop_slash`, `memory_slash`, `resume_slash`, etc.). Autocomplete via `completer.py`.
- **System prompt:** `cli/workbench_app/system_prompt.py` — role + workspace + tool list + skills + slash recommendations + injection guard. AGENTLAB.md layered loader at `cli/project_instructions/loader.py` (enterprise/user/project, with `@inline` includes, 64KB cap).
- **Tasks:** SQLite `TaskStore` at `.agentlab/tasks.db`, `TaskExecutor` worker threads, recovery, scheduler, daemon supervisor (`cli/daemon.py`).
- **Skills:** `cli/user_skills/` — markdown + frontmatter, `allowed_tools` allowlist, registry with workspace > user > bundled precedence.
- **MCP:** `cli/mcp_runtime.py` + `cli/mcp_setup.py` + `cli/tools/mcp_bridge.py` — dynamic Tool subclass per server tool.
- **Hooks:** `cli/hooks/` directory exists (loader.py, runtime.py, actions.py) — present but minimally wired.

**What's missing or weak vs. Claude Code** (verified by reading both trees):

0. **Cross-provider parity.** The `ModelClient` protocol (`cli/llm/types.py:101`) exposes only `complete()` — no streaming method. Only Anthropic honors streaming + thinking + prompt cache. OpenAI is round-tripped as a single response. Gemini is a stub. Every downstream feature that depends on streaming (structured diff progress, per-tool cost attribution, cancellation mid-tool-call, compaction boundaries rendered live) effectively only works on Anthropic today. **This is a pre-req for almost everything else in the roadmap** — parity must be horizontal across Anthropic, OpenAI, and Gemini.

1. **Streaming tool execution.** AgentLab waits for the model's full assistant message before it dispatches tools. Claude Code's `StreamingToolExecutor` (`src/services/tools/StreamingToolExecutor.ts`) starts execution from `ToolUseStart` and runs concurrency-safe tools in parallel, sequencing the unsafe ones. Big latency win on multi-tool turns.
2. **Structured diff renderer.** `FileEditTool.render_result` returns a unified-diff string. Claude Code has `src/components/StructuredDiff.tsx` — a side-by-side widget with syntax highlighting, gutter caching, and bounded WeakMap caches. AgentLab's TUI deserves the same.
3. **Conversation compaction.** No automatic compaction. Claude Code has `src/services/compact/compact.ts` with `SystemCompactBoundaryMessage` markers and `ToolUseSummaryMessage` digests. AgentLab transcripts grow unbounded.
4. **Auto-memory extraction.** AGENTLAB.md is read on startup, but there is nothing analogous to Claude Code's `src/memdir/memdir.ts` background `extractMemories` task that harvests memories from the turn and writes to MEMORY.md. AgentLab also has no `findRelevantMemories` retrieval before each turn.
5. **Hooks.** `cli/hooks/` exists but has no settings.json schema, no before/after-tool dispatch, no Claude-Code-style `beforeQuery`/`afterTool`/`onSubagentStop` events. Compare to `~/.claude/settings.json` hooks contract.
6. **Paste/image store.** Pastes go inline; no `src/history.ts`-style paste store with `[Pasted text #1 +10 lines]` placeholders, no clipboard image capture, no `src/utils/imageResizer.ts` to keep vision tokens bounded.
7. **Vim mode.** Claude Code ships `src/vim/` (motions, operators, text objects). AgentLab has prompt_toolkit's default emacs bindings only.
8. **Output styles.** Claude Code's output-style system lets the model request rendering styles (`<claude-code output-style="table">`). `cli/workbench_app/output_style.py` is a stub.
9. **Session persistence parity.** AgentLab has `conversation_store.py` and `resume_slash.py`, but no session-scoped UUID tree under `~/.agentlab/projects/<slug>/history/<session-id>.json`, no fork-from-turn (`forkedAgent.ts`), no append-only JSONL streaming.
10. **Permission classifier.** Permissions are rule-based (`tool_permissions.py`). Claude Code has a transcript classifier (`TRANSCRIPT_CLASSIFIER`) that auto-approves obviously-safe tool calls. Big UX win for read-only operations.
11. **Settings file with deep merge.** No `~/.agentlab/settings.json` + `<project>/.agentlab/settings.json` cascade for permissions, hooks, env, model selection. Settings are spread across env vars and ad-hoc dotfiles today.
12. **MCP server lifecycle.** `mcp_runtime.py` covers stdio. No SSE/HTTP transports, no OAuth, no graceful reconnect. Claude Code's `src/services/mcp/types.ts` supports stdio+SSE+HTTP+WebSocket with auth metadata.
13. **/resume picker.** `resume_slash.py` exists but no rich picker UI listing recent sessions with summary + last-message preview.
14. **CLAUDE.md → AGENTLAB.md naming.** Claude Code reads `CLAUDE.md`. AgentLab reads `AGENTLAB.md` only. For users who already have `CLAUDE.md` populated, fall back to it.
15. **/init flow.** AgentLab has `init_slash.py`. Claude Code's `/init` writes a starter CLAUDE.md by introspecting the project. Worth comparing.
16. **Cost + token telemetry.** `cost_calculator.py` + `cost_stream.py` exist. Claude Code's `cost-tracker.ts` is more granular (per-tool, per-cache-tier). Status bar already shows tokens; cost-per-turn breakdown would close the gap.

---

## 2. Roadmap shape

Seven phases. Each phase has a clear theme, ships independently, and is sized so a competent engineer can land it in 1-3 PRs. Sequencing matters: settings + hooks (P0) and full Anthropic/OpenAI/Gemini provider parity (P0.5) unblock everything else; streaming tools + structured diff (P1) are the highest-visibility wins; memory + compaction (P2) buy long-session stability; MCP + permissions (P3) buy production trust; sessions + paste (P4) close the daily-driver gaps; output styles + vim (P5) are polish.

**Cross-cutting rule: every phase must work across Anthropic, OpenAI, and Gemini.** If a feature can only ship on one provider, it is a fallback path, not the primary implementation. See §4 for the capability-matrix contract.

| Phase | Theme | Effort | Risk | Unlocks |
|------:|---|---|---|---|
| P0 | Settings cascade + hook contract | M | Low | All later phases |
| P0.5 | **Cross-provider parity (Anthropic / OpenAI / Gemini)** | **L** | **Med** | **All streaming- and tool-use-sensitive work** |
| P1 | Streaming tool dispatch + structured diff | L | Med | Latency, edit UX |
| P2 | Compaction + memory extraction | L | Med-High | Long sessions |
| P3 | Permission classifier + MCP transports | L | Med | Production trust |
| P4 | Session storage + fork + paste/image store | M | Low | Daily-driver UX |
| P5 | Output styles + vim mode + cost detail | S | Low | Polish |

---

## 3. Phase detail

### P0 — Settings cascade + hook contract (medium, low risk)

**Goal.** Single source of truth for permissions, env, model defaults, and hooks. Cascade `<repo>/.agentlab/settings.json` over `~/.agentlab/settings.json` over `/etc/agentlab/settings.json`. Wire the existing `cli/hooks/` package to actually fire on lifecycle events.

**Files to create.**
- `cli/settings/__init__.py` — `Settings` pydantic model.
- `cli/settings/loader.py` — three-layer load + deep-merge.
- `cli/settings/schema.py` — JSON schema for editor support.
- `tests/test_settings_loader.py` — precedence + merge cases.
- `tests/test_hooks_lifecycle.py` — fire/don't-fire matrix.

**Files to modify.**
- `cli/hooks/loader.py` — read from `Settings.hooks` instead of ad-hoc dotfiles.
- `cli/hooks/runtime.py` — add events: `beforeQuery`, `afterQuery`, `beforeTool`, `afterTool`, `onSubagentStop`, `onSessionEnd`. Mirror Claude Code's payload shape so users with both tools can share scripts.
- `cli/llm/orchestrator.py` — fire `beforeQuery`/`afterQuery`.
- `cli/tools/executor.py` — fire `beforeTool`/`afterTool`. Honor blocking hook return that denies a tool call.
- `cli/workbench_app/tool_permissions.py` — read permission rules from `Settings.permissions`.

**Risks / edge cases.**
- Existing env-var-based config (`AGENTLAB_NO_TUI`, `AGENTLAB_EXPOSE_SLASH_TO_MODEL`, etc.) must keep working. Resolution order: env > project settings > user settings > defaults.
- Hook scripts run user code → must enforce a per-hook timeout (default 5s) and capture stderr. A misbehaving hook should not wedge the turn.
- Schema migration: emit a deprecation warning if old dotfiles are present; ship a `/migrate-settings` slash command that writes the new file and archives the old.

**Test strategy.**
- Pure unit tests for the merge function (table-driven).
- Hook fire matrix: settings-defined hook fires; missing hook is a no-op; failing hook is logged but doesn't crash the turn.
- Smoke: `agentlab workbench` starts cleanly with empty + populated settings.

---

### P0.5 — Cross-provider parity: Anthropic, OpenAI, Gemini (large, medium risk)

**Goal.** Every user-visible capability must work across Anthropic (Claude Sonnet/Opus/Haiku 4.x), OpenAI (GPT-4o, GPT-5, o1/o3/o4 reasoning models), and Google Gemini (2.5 Pro / 2.5 Flash / 2.0 Flash). Today the model harness is Anthropic-shaped and leaks that shape into the protocol, which means downstream phases (streaming dispatch, compaction UI, cost attribution) de-facto only work on one provider. Fix this before we pile more on top.

**Sub-goals.**

P0.5a — **Lift the `ModelClient` protocol above any one provider.** The protocol in `cli/llm/types.py:101` declares only `complete()` and returns `ModelResponse`. Add an explicit streaming contract + a capability descriptor so adapters can say what they do and don't support, and the orchestrator branches on that rather than on provider strings.

- Files to create:
  - `cli/llm/capabilities.py` — `ProviderCapabilities` dataclass: `streaming: bool`, `native_tool_use: bool`, `thinking: bool`, `prompt_cache: bool`, `vision: bool`, `parallel_tool_calls: bool`, `json_mode: bool`, `max_context_tokens: int`, `max_output_tokens: int`. Note: a `cli/llm/capabilities.py` file already exists — inspect before creating; rename if it collides.
  - `cli/llm/tool_schema_translator.py` — converts the canonical tool schema (Anthropic-shaped, since that's our source of truth today) into OpenAI function-call shape and Gemini function-declaration shape. Pure function, table-driven tests per tool.
  - `cli/llm/providers/gemini_client.py` — real adapter using the `google-genai` SDK. Streaming via `generate_content(..., stream=True)`. Tool use via `types.Tool(function_declarations=...)`. System instruction via `system_instruction=`. Thinking via `thinking_config=` on 2.5 models. No prompt cache in the SDK yet — declare `prompt_cache=False` and skip gracefully.
  - `tests/test_tool_schema_translator.py` — every bundled tool round-trips into each provider's schema shape and back.
  - `tests/test_gemini_client.py` — fake SDK injected via constructor (same pattern as `anthropic_client.py` tests). Covers streaming, tool use, multi-turn, safety-block handling, quota-error retries.
  - `tests/test_provider_capabilities.py` — capability matrix is declared and matches what the adapter actually does.

- Files to modify:
  - `cli/llm/types.py` — extend `ModelClient` protocol with `stream(system_prompt, messages, tools) -> Iterator[StreamEvent]` (the existing `streaming.events_from_model_response` becomes the fallback). Add `capabilities: ProviderCapabilities` attribute on the protocol.
  - `cli/llm/providers/openai_client.py` — **make it actually stream.** Use `chat.completions.create(..., stream=True)` and translate deltas (`choices[0].delta.content`, `choices[0].delta.tool_calls`) into our `StreamEvent` types in real time, not post-hoc. Support the reasoning models' `reasoning_content` delta as `ThinkingDelta`. Map OpenAI function calls to `ToolUseStart/Delta/End` using the `tool_call_id` as the id.
  - `cli/llm/providers/anthropic_client.py` — keep current behavior but declare its capabilities explicitly via the new descriptor.
  - `cli/llm/providers/factory.py` — remove the Gemini stub; add `("gemini-", "gemini")` real resolution; read `GOOGLE_API_KEY` **or** `GEMINI_API_KEY` (users have either); add model aliases table for common names (`gemini-2.5-pro`, `gemini-2.5-flash`, `gemini-2.0-flash`).
  - `cli/llm/orchestrator.py` — call `stream()` by default; use `complete()` only when `capabilities.streaming is False`. Branch on `capabilities.parallel_tool_calls` for dispatch strategy.
  - `cli/llm/caching.py` — already Anthropic-specific; guard its application behind `capabilities.prompt_cache`. No-op on OpenAI and Gemini.
  - `cli/provider_keys.py` — add Gemini key entry + reachability probe.
  - `cli/mcp_setup.py` and onboarding — Gemini option in the model picker.

P0.5b — **Unify tool-use semantics.** Each provider names things differently. Normalize at the adapter boundary so the orchestrator never sees a raw SDK type.

- Anthropic: `input_schema` / `tool_use` blocks / `tool_result` → canonical (already matches).
- OpenAI: `parameters` (JSON Schema) / `tool_calls[].function` / `tool` role message → canonical. Handle OpenAI's argument-streaming quirk (`arguments` arrives as a JSON **string** delta, so we must accumulate then `json.loads` at `ToolUseEnd`; never try to parse partial JSON).
- Gemini: `function_declarations[].parameters` (OpenAPI subset) / `function_call` part / `function_response` part → canonical. Handle Gemini's **"automatic function calling"** opt-out (we want manual so the orchestrator keeps control).

P0.5c — **Thinking / reasoning-token normalization.** Anthropic exposes `thinking` blocks; OpenAI `o1/o3/o4` expose `reasoning_content` (sometimes hidden, sometimes summarized); Gemini 2.5 exposes `thought_summary`. Emit a single `ThinkingDelta` regardless. Surface a capability flag so the UI can show or hide the thinking panel.

P0.5d — **System prompt shape.** Anthropic takes a top-level `system`; OpenAI takes a leading `{"role":"system"}` message; Gemini takes `system_instruction` on the model. Adapter handles this; orchestrator passes one string.

P0.5e — **Cost + token accounting across providers.** Each provider reports usage differently (input/output tokens, cache read/write, reasoning tokens, thought tokens). Normalize into the existing `UsageDelta` with explicit fields for each, and update `cli/workbench_app/cost_calculator.py` to consult a price table keyed by `(provider, model)` rather than hard-coded Claude rates. Ship a small `cli/llm/pricing.py` data file that can be overridden via settings (P0) so users with enterprise contracts can set their own rates.

P0.5f — **Provider-aware cache boundary strategy.** Anthropic's breakpoint-based cache, OpenAI's automatic input-prefix cache, and Gemini's context-cache-by-handle are three different mechanisms. Wrap them behind a single `cache_hint(blocks)` interface that the adapter interprets — or no-ops on — so the orchestrator doesn't care.

**Risks.**

- **Feature drift:** Anthropic ships tool-use features before the others (or vice versa). We must pick a canonical shape (keep Anthropic's today — least churn) and translate. When a provider adds something we don't have, add it to the capability matrix, not the protocol.
- **Gemini safety filters** can hard-stop a generation mid-stream (`finish_reason=SAFETY`). Treat this as a first-class `stop_reason` so the UI surfaces "blocked by safety filter" rather than silently ending the turn.
- **OpenAI JSON-mode vs tool-use** interact oddly. Prefer tool-use everywhere; expose JSON mode only via a capability flag for the one or two callers (evals) that need strict-schema output.
- **Vision token accounting** differs (Anthropic counts image tokens differently from OpenAI which differs from Gemini). Ship a conservative estimate; never claim exactness.
- **Parallel tool calls** — OpenAI supports them by default; Gemini's function-calling mode is one-at-a-time (unless you explicitly ask for parallel); Anthropic supports them on newer models only. P1's streaming dispatcher must consult `capabilities.parallel_tool_calls`.

**Test strategy.**

- **Per-adapter matrix.** For each of {Anthropic, OpenAI, Gemini}, run the same scripted turn (3 tools, one of them failing, one with a big output) against a fake SDK and assert we get the same `StreamEvent` sequence.
- **Golden capability table.** A test that imports every provider and asserts its `ProviderCapabilities` matches the expected matrix — catches someone silently lying about features.
- **Live smoke (opt-in).** `tests/smoke_live.sh` already exists for Anthropic-style live runs. Extend to `--provider openai` and `--provider gemini` gated on env keys, wired into an optional CI job.

**Backward compatibility.** The `complete()` method stays on the protocol as a fallback. Existing callers that pass `create_model_client(model="claude-...")` continue to work. The Gemini stub's `ProviderFactoryError` message changes to a real adapter.

---

### P1 — Streaming tool dispatch + structured diff (large, medium risk)

**Goal.** Two of the most visible deltas vs. Claude Code, bundled because they share the streaming-event refactor.

**P1a — Streaming tool dispatch.**

Today `LLMOrchestrator.run_turn()` accumulates the assistant message then dispatches tools. Claude Code's `StreamingToolExecutor` consumes `ToolUseEnd` events as they arrive, dispatches concurrency-safe tools immediately to a pool, and sequences the unsafe ones. Tool results are buffered and yielded to the model in declared order.

- Files to create:
  - `cli/llm/streaming_tool_dispatcher.py` — pool + ordering buffer.
  - `tests/test_streaming_tool_dispatch.py` — concurrency + ordering + cancellation.
- Files to modify:
  - `cli/tools/base.py` — add `Tool.is_concurrency_safe: bool` (default False; opt-in). Read-only tools (file_read, glob, grep, web_fetch, web_search, config_read, task_get/list/output) opt in.
  - `cli/llm/orchestrator.py` — replace post-message dispatch with the new dispatcher.
  - `cli/tools/executor.py` — make `execute_tool_call` async-friendly (already returns `ToolResult` synchronously; wrap in a thread pool for now, switch to true async later).
- Risks:
  - Permission prompts are modal — concurrent tool dispatch must serialize on the prompt. Easiest: any tool needing prompt → drains the pool first.
  - Hooks (P0) must fire in declared order even when execution is parallel.
  - Cancellation: `Ctrl+C` mid-turn must abort all in-flight tools. Reuse `cli/workbench_app/cancellation.py`.
  - **Cross-provider:** dispatcher consults `capabilities.parallel_tool_calls` from P0.5. Anthropic and OpenAI allow parallel by default on newer models; Gemini serializes function calls — dispatcher falls back to sequential for Gemini turns, still honors `is_concurrency_safe` as a per-tool hint for ordering within the sequential path.

**P1b — Structured diff widget.**

`cli/workbench_app/tui/widgets/` already has the widget pattern. Add `structured_diff.py` modeled on `claude-code-main/src/components/StructuredDiff.tsx`: side-by-side gutter + content, syntax highlighting via `pygments` (already in many Python TUIs), bounded LRU cache keyed by `(file_path, old_sha, new_sha, terminal_width)`.

- Files to create:
  - `cli/workbench_app/tui/widgets/structured_diff.py` — pure helper `build_diff_lines(old, new, language) -> list[DiffRow]` + Textual widget wrapping it.
  - `tests/test_structured_diff.py` — pure-helper tests for hunking, highlighting, cache keys.
- Files to modify:
  - `cli/tools/file_edit.py::FileEditTool.render_result` — return a `Renderable` recognized by the TUI (use `cli/tools/rendering.py` extension point) that maps to the new widget. Line-mode REPL falls back to existing unified diff.
  - `cli/tools/file_write.py` — same treatment for new-file creation (left side empty, right side full).
- Risks:
  - Wide diffs on narrow terminals — degrade gracefully to unified diff below 80 cols.
  - Pygments lex failure on unknown extensions — fall back to no highlighting, never crash the renderer.
- Test strategy: golden file tests for 5-10 representative diffs (Python, TS, YAML, Markdown, plain text, binary-detected, very-long-line, very-many-hunks).

---

### P2 — Compaction + memory extraction (large, medium-high risk)

**Goal.** Long sessions that don't blow context, plus a CLAUDE.md-style auto-memory loop.

**P2a — Conversation compaction.**

Match Claude Code: insert a `SystemCompactBoundaryMessage` and a `ToolUseSummaryMessage` when transcript size exceeds a threshold. Old turns archived to disk; the model sees only the digest.

- Files to create:
  - `cli/llm/compaction.py` — `should_compact(transcript, budget) -> bool`, `compact(transcript) -> CompactedTranscript`. Uses a forked agent call with the cheapest available model (Haiku) to summarize tool phases.
  - `cli/llm/digests.py` — `digest_tool_phase(turns) -> str`, structured per Claude Code's pattern.
  - `tests/test_compaction.py` — threshold logic, digest content, idempotency, no-op when below threshold.
- Files to modify:
  - `cli/llm/orchestrator.py` — call `should_compact` after each turn.
  - `cli/workbench_app/transcript.py` — append the boundary message and re-render.
  - `cli/workbench_app/conversation_store.py` — persist the pre-compaction transcript for `/uncompact`.
- Risks:
  - **High-risk:** compaction can drop information the user needs. Must be reversible (`/uncompact` restores the full transcript) and the user must see the boundary clearly in the UI.
  - Cost: each compaction is an extra model call. Default threshold conservative (~80% of effective context).
  - Tool-result-heavy phases (e.g., big grep dumps) need different compression than chat phases. Two strategies: extractive (drop blob, keep first/last 20 lines + count) vs. abstractive (model summary).
  - **Cross-provider:** threshold is per-model (Anthropic 200K, GPT-4o 128K, GPT-5 400K, Gemini 2.5 Pro 2M, Gemini 2.5 Flash 1M). Read `capabilities.max_context_tokens` from P0.5 rather than hard-coding. Use the cheapest fast model *within the active provider family* for the digest (Haiku / GPT-4o-mini / Gemini Flash), not a hard-coded Claude Haiku — keeps keys and quotas self-contained.
- Test strategy:
  - Unit tests for thresholding and idempotency.
  - Snapshot tests for digest format on canned tool sequences.
  - Manual smoke: drive a transcript past the threshold, confirm digest reads sensibly and `/uncompact` restores.

**P2b — Memory extraction + retrieval.**

Match Claude Code's `extractMemories` background task and `findRelevantMemories` retrieval.

- Files to create:
  - `cli/memory/__init__.py` — package.
  - `cli/memory/extractor.py` — `extract_memories(turn) -> list[Memory]` using a forked Haiku call with the AGENTLAB.md memory-type schema.
  - `cli/memory/retrieval.py` — `find_relevant(query, memories, k=5)` — start with simple BM25 + recency bonus; semantic later.
  - `cli/memory/store.py` — markdown file CRUD with frontmatter (type, name, description). Mirror the `~/.claude/projects/.../memory/` layout you already use globally.
  - `tests/test_memory_extractor.py`, `tests/test_memory_retrieval.py`.
- Files to modify:
  - `cli/llm/orchestrator.py` — after each completed turn, dispatch extraction as a background `TaskCreate`. Don't block.
  - `cli/workbench_app/system_prompt.py` — accept `relevant_memories=` kwarg, render under `## Relevant memories` (default `None`, preserve snapshot).
  - `cli/project_instructions/loader.py` — load `MEMORY.md` from same paths as AGENTLAB.md.
- Risks:
  - Auto-extraction can save garbage. Mitigate with a strict frontmatter schema and a per-session cap (e.g., max 5 new memories per session).
  - Storing user messages in plain markdown has privacy implications — never send memories to a third-party model without surfacing this in the system prompt and `/doctor`.
  - Retrieval relevance is hard to evaluate offline. Ship with a `/memory-debug` slash that shows what was injected and why, so users can correct false positives.
  - **Cross-provider:** the extractor prompt must be provider-neutral (no `<thinking>`-style hints that only one model family uses). The forked call goes through the same `create_model_client` factory as the main turn, so it respects the user's active provider. Gemini's stricter JSON-output defaults make the schema extraction *easier* there; give it a structured-output mode when `capabilities.json_mode` is true, fall back to lenient parsing on the others.

---

### P3 — Permission classifier + MCP transports (large, medium risk)

**Goal.** Less prompting on safe ops; MCP that works with hosted servers, not just stdio.

**P3a — Transcript classifier for auto-approval.**

Replicate `TRANSCRIPT_CLASSIFIER`: a small heuristic-then-classifier pipeline that auto-approves clearly-safe tool calls (read-only file/grep, well-known web hosts, bash commands matching an allowlist regex).

- Files to create:
  - `cli/permissions/classifier.py` — heuristics first (rule table per tool), classifier hook for future ML upgrade.
  - `cli/permissions/denial_tracking.py` — count denials per (tool, session); fall back to prompting after N (default 3).
  - `tests/test_permission_classifier.py`, `tests/test_denial_tracking.py`.
- Files to modify:
  - `cli/workbench_app/tool_permissions.py` — consult classifier before showing the prompt; respect "always" decisions persisted in settings.
  - `cli/workbench_app/permission_dialog.py` — add a "save as rule" button that writes back to `<project>/.agentlab/settings.json`.
- Risks: false positives are dangerous. Default to **prompt**, not auto-approve, on any ambiguity. Bash classifier in particular must be conservative — the allowlist is short (`ls`, `pwd`, `git status`, `git diff`, etc.) and pipelines/redirects always prompt.

**P3b — MCP SSE + HTTP transports + reconnect.**

Today `cli/mcp_runtime.py` runs stdio servers. Add SSE and HTTP transports + graceful reconnect with backoff. OAuth deferred to P5 (low frequency for AgentLab's audience).

- Files to create:
  - `cli/mcp/transports/sse.py`, `cli/mcp/transports/http.py`.
  - `cli/mcp/reconnect.py` — exponential backoff supervisor.
  - `tests/test_mcp_transports.py` — fixtures for each transport using a mock server.
- Files to modify:
  - `cli/mcp_runtime.py` — dispatch on `transport: stdio|sse|http`.
  - `cli/mcp_setup.py` — wizard supports the new transports.
- Risks: long-lived connections leak FDs if shutdown isn't clean. Add a daemon-style supervisor with health checks. Tool schemas can change at reconnect — invalidate cached schemas and re-register on the executor.

---

### P4 — Session storage + fork + paste/image store (medium, low risk)

**Goal.** Match Claude Code's session model so `/resume` is delightful and pastes/images don't bloat the input.

- Files to create:
  - `cli/sessions/store.py` — append-only JSONL at `~/.agentlab/projects/<slug>/history/<session-id>.jsonl`. UUID per session, slug from workspace path.
  - `cli/sessions/fork.py` — fork a session at turn N into a new UUID; copy transcript prefix.
  - `cli/sessions/picker.py` — pure data builder for the resume picker (id, started_at, summary, last user message preview).
  - `cli/workbench_app/tui/widgets/resume_picker.py` — Textual widget over the pure builder.
  - `cli/paste/store.py` — content-addressed paste store at `.agentlab/pastes/`. Returns `[Pasted text #N +M lines]` placeholders for the input; full content threaded through to the model.
  - `cli/paste/image.py` — clipboard image capture (pyperclip + PIL) + resize to <=4K longest edge.
  - Tests for each.
- Files to modify:
  - `cli/workbench_app/conversation_store.py` — wrap the new store; keep the SQLite path for backward-compat reads.
  - `cli/workbench_app/resume_slash.py` — open the picker.
  - `cli/workbench_app/input_router.py` — detect large pastes (>2KB or contains image) and replace inline.
- Risks:
  - JSONL append must be crash-safe (write+fsync+rename for the index file; per-line append is naturally atomic).
  - Image dependencies (PIL) — make optional; degrade gracefully when absent.
  - Backward compat with existing `conversation_store.py` rows. Run a one-time migration script wrapped in `/migrate-sessions`.

---

### P5 — Output styles + vim + cost detail (small, low risk)

Three independent polish items.

- **Output styles.** Flesh out `cli/workbench_app/output_style.py` so the model can request `<agentlab output-style="table|json|markdown|terse">`. Renderer applies the style to its responses; default unchanged. Keep the directive format provider-neutral (plain XML-ish tag, not a Claude-specific `<claude-code>` tag) since all three model families handle it via system-prompt hint.
- **Vim mode.** Wire prompt_toolkit's vi mode into `cli/workbench_app/pt_prompt.py` behind a `Settings.input.vim = true` flag. Add a `cli/workbench_app/vim_help_slash.py` cheat sheet. (Don't reimplement Claude Code's hand-rolled vim — prompt_toolkit's is good.)
- **Per-tool cost.** Extend `cli/workbench_app/cost_calculator.py` to track per-tool tokens. Surface in `/doctor` and the status bar drawer. Pricing table lives in `cli/llm/pricing.py` (added in P0.5) and carries Anthropic / OpenAI / Gemini rates; status bar reads from the active `(provider, model)` pair rather than hard-coded Claude rates.

Risks across P5: all low. Keep behind opt-in flags so default UX is unchanged.

---

## 4. Cross-cutting concerns

**Provider parity contract.** Every feature shipped after P0.5 is scored against this capability matrix. A feature is "parity-ready" only when it has a primary path for all three providers or an explicit fallback declared in the matrix.

| Capability | Anthropic | OpenAI | Gemini | AgentLab handling |
|---|:-:|:-:|:-:|---|
| Streaming text | ✓ | ✓ (post P0.5) | ✓ | Primary path; no fallback needed |
| Native tool use | ✓ | ✓ | ✓ | Primary path; no fallback needed |
| Parallel tool calls | ✓ (Sonnet 4+) | ✓ | partial | P1 dispatcher reads `capabilities.parallel_tool_calls`; falls back to sequential on Gemini |
| Thinking / reasoning tokens | ✓ | ✓ (o1/o3/o4) | ✓ (2.5) | Normalized to `ThinkingDelta`; UI shows a unified "thinking" panel |
| Prompt cache | ✓ (breakpoint) | ✓ (auto prefix) | ✓ (handle) | Adapter-owned; no-op where unsupported |
| Vision | ✓ | ✓ | ✓ | Shared image path (P4 image store) |
| Structured / JSON output | via tool use | ✓ | ✓ | Only used by evals; capability-flagged |
| Context window | 200K | 128K-400K | 1M-2M | Compaction threshold per-model (P2) |
| Safety blocks | rarely | rarely | often | Gemini `finish_reason=SAFETY` surfaces as a distinct stop_reason in the UI |

**Naming.** Rename internal `AGENTLAB.md` references to also accept `CLAUDE.md` — read whichever is present, prefer `AGENTLAB.md`. This is a one-line change in the loader and a doc note. Friction with existing Claude Code users drops to zero.

**Backward compatibility.** Every phase ships behind defaults that preserve current behavior. Snapshot tests (`tests/test_system_prompt.py`, etc.) must stay byte-stable. The `ModelClient.complete()` method stays on the protocol after P0.5 even though `stream()` becomes the primary path — callers that passed `EchoModel` or a test fake keep working.

**Test discipline.** Each phase ships pure helpers that can be tested without spinning up Textual or the model. Same pattern the prior parity work already follows. Target ≥80% coverage on new modules. **Every feature touching the model harness gets a three-provider test case** using fake SDKs (already the pattern for Anthropic; extend to OpenAI + Gemini in P0.5).

**Telemetry / cost.** Every new model call (compaction, memory extraction, classifier fallback) goes through `cost_calculator` and appears in `/doctor`. Users must be able to see what the agent is spending in the background. Rates come from `cli/llm/pricing.py` keyed by `(provider, model)`, editable via settings.

**Performance budget.** Streaming tool dispatch should not regress single-tool turns. Compaction must run in <2s on a representative transcript. Hook execution must time out at 5s. Adapter overhead (translation + capability dispatch) must stay under 5ms per call.

---

## 5. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Compaction loses information silently | High | `/uncompact`, visible boundary, conservative threshold |
| Auto-memory writes garbage | Med-High | Strict schema, per-session cap, `/memory-debug` review |
| Classifier auto-approves something dangerous | High | Default to prompt; tiny allowlist; never auto-approve writes |
| Streaming dispatch surfaces races in tools | Med | Opt-in `is_concurrency_safe`; default false |
| Settings cascade breaks existing env-var users | Low | Env > settings precedence; deprecation warnings |
| MCP SSE/HTTP transports leak FDs | Med | Supervisor with health checks; reconnect tests |
| Session storage migration drops history | Med | Read-only fallback to old SQLite; no destructive migration |
| Pygments slow on very large diffs | Low | Cap highlight to first N hunks; fall back to plain |
| Provider capability drift (one ships a feature early) | Med | Canonical Anthropic shape + translator; capability matrix governs orchestrator branches |
| Gemini safety filter ends turn silently | Med | Surface `finish_reason=SAFETY` as explicit stop_reason in UI |
| OpenAI tool-call JSON arrives as partial string | Med | Accumulate `arguments` delta; parse at `ToolUseEnd` only, never partial |
| Gemini SDK API drift (pre-1.0) | Med | Pin `google-genai` minor version; isolation tests against the pin |

---

## 6. Scope estimate

**Overall: large.** ~8-12 weeks of focused engineering for one experienced contributor, or 4-5 weeks parallelized across two with clear phase boundaries. The P0.5 insertion adds roughly 2 weeks over v1 of this plan but prevents rework across every downstream phase.

Per-phase: P0 small-medium, **P0.5 large**, P1 large, P2 large, P3 large, P4 medium, P5 small.

**Sequencing rationale.** P0 must land first because P0.5's settings-driven provider keys, P1's hook integration, P2's compaction events, P3's classifier persistence, and P4's settings-driven session paths all depend on it. **P0.5 must land second** — once streaming tool dispatch (P1) and compaction (P2) assume a single-provider shape, retrofitting cross-provider parity becomes painful. P1-P5 can interleave once P0 and P0.5 are both in.

---

## 7. Recommended next step

1. **Land P0 first** — settings cascade + hook contract. Cheapest, lowest-risk, unblocks P0.5.
2. **Land P0.5 second** — full Anthropic / OpenAI / Gemini parity with a capability matrix. Streaming OpenAI adapter + real Gemini adapter + tool-schema translator + provider-aware cost table. Do this before anything piles more Anthropic-shaped assumptions on top.
3. After P0.5 ships, decide P1 vs. P2 based on user demand: P1 if streaming latency or multi-tool turns are the loudest complaint; P2 if long sessions are.
