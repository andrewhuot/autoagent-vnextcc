# P1 Handoff — Streaming tool dispatch + structured diff

Paste the block below into a fresh Claude Code session at the repo root (`/Users/andrew/Desktop/agentlab`).

**Prerequisites:**
- **P0 merged** (hook contract — P1's dispatcher fires `PRE_TOOL_USE`/`POST_TOOL_USE` per tool call).
- **P0.5 merged** (capability descriptor — dispatcher consults `capabilities.parallel_tool_calls` to decide concurrency strategy). Shipping P1 before P0.5 means branching dispatcher logic on provider strings, which is tech debt.
- Parallel-safe with **P3** (no file overlap). Parallel-safe with **P4** (only risk: `input_router.py`; land P1's router change first).
- **NOT parallel-safe with P2.** Both touch `cli/llm/orchestrator.py` at the dispatch call site. Ship P1 first, then P2.

**What this unlocks:** Latency wins on multi-tool turns, Claude-Code-quality edit UX, baseline for P2's compaction UI (streaming compaction boundary needs the same event bus).

---

## Session prompt

You are picking up the AgentLab Claude-Code-parity roadmap at **P1 — Streaming tool dispatch + structured diff**. P0 (settings + hooks) and P0.5 (provider parity) shipped. The roadmap lives at `docs/plans/2026-04-17-claude-code-parity-roadmap-v2.md`.

### Your job

Ship **P1** in two slices, following subagent-driven TDD:

- **Slice A — Streaming tool dispatch** (P1a). Foundation; lands first.
- **Slice B — Structured diff widget** (P1b). Independent of Slice A; can be dispatched in parallel to Slice A if you have two engineers. Single-engineer: ship A first, then B.

- `.venv/bin/python -m pytest` (Python 3.11).
- Failing test → minimal impl → passing test → conventional commit.
- Mark TodoWrite tasks complete immediately; don't batch.

### P1 goal

**Slice A:** Today `LLMOrchestrator.run_turn()` in `cli/llm/orchestrator.py` accumulates the assistant message, then dispatches tool calls sequentially. Replace with a streaming dispatcher that starts concurrency-safe tools the moment a `ToolUseEnd` event arrives, sequences the unsafe ones, buffers results in declared order, and feeds them back to the model when the model message completes. Matches Claude Code's `StreamingToolExecutor.ts`.

**Slice B:** `FileEditTool.render_result` returns a unified-diff string. Add a Textual widget that renders side-by-side gutter + content with syntax highlighting and bounded per-hunk cache. Matches Claude Code's `StructuredDiff.tsx`.

**Reference shape (read for architectural inspiration, do NOT copy code):**
- `/Users/andrew/Desktop/claude-code-main/src/services/tools/StreamingToolExecutor.ts` — the streaming dispatcher pattern.
- `/Users/andrew/Desktop/claude-code-main/src/services/tools/toolOrchestration.ts` — concurrency gating.
- `/Users/andrew/Desktop/claude-code-main/src/components/StructuredDiff.tsx` + `StructuredDiff/colorDiff.ts` — diff rendering with caching.

### Before dispatching anything

1. **Read the P1 section** of `docs/plans/2026-04-17-claude-code-parity-roadmap-v2.md`.

2. **Ground-truth these files:**
   - `cli/llm/orchestrator.py::LLMOrchestrator.run_turn` — the post-message tool-dispatch loop (where the new dispatcher plugs in).
   - `cli/llm/streaming.py` — `TextDelta`, `ThinkingDelta`, `ToolUseStart/Delta/End`, `UsageDelta`, `MessageStop`, `collect_stream`.
   - `cli/tools/base.py::Tool` — the ABC, and `ToolContext`. P1 adds a class-level `is_concurrency_safe: bool = False` opt-in.
   - `cli/tools/executor.py::execute_tool_call` — current sync dispatch site. Must become async-compatible (or wrap in thread pool for now).
   - `cli/workbench_app/cancellation.py` — reuse for Ctrl+C mid-turn abort.
   - `cli/workbench_app/tool_permissions.py` + `cli/workbench_app/permission_dialog.py` — modal prompt that must serialize against concurrent dispatch.
   - `cli/llm/provider_capabilities.py` (from P0.5) — `capabilities.parallel_tool_calls`.
   - `cli/tools/file_edit.py::FileEditTool.render_result` — where the new diff widget hooks in.
   - `cli/tools/rendering.py` — existing extension point for `Renderable`-type tool results.
   - `cli/workbench_app/tui/widgets/` — widget pattern (e.g., `task_tree.py` has pure-helper + thin-wrapper pattern).

3. **Write a TDD expansion plan** at `docs/plans/2026-04-17-p1-streaming-diff-tdd.md`. Commit alone before any code.

### P1a — Streaming tool dispatch (tasks)

**P1a.1 — `is_concurrency_safe` opt-in on tools.**
- Add class attribute to `cli.tools.base.Tool`. Default `False`.
- Opt in: file_read, glob, grep, web_fetch, web_search, config_read, task_get, task_list, task_output. (Read-only tools only.)
- **Do NOT opt in:** file_edit, file_write, bash, config_edit, task_create, task_stop, schedule_wakeup, agent_spawn, todo_write, exit_plan_mode, skill_tool, anything MCP. These must sequence.
- Tests: `tests/test_tool_concurrency_flags.py` — every bundled tool declared; every tool's flag matches the allowlist.

**P1a.2 — `StreamingToolDispatcher` pure helper.**
- Create `cli/llm/streaming_tool_dispatcher.py`:
  ```python
  class StreamingToolDispatcher:
      def __init__(self, *, registry, executor, capabilities, max_concurrency=4): ...
      def on_tool_use_start(self, event: ToolUseStart) -> None: ...
      def on_tool_use_delta(self, event: ToolUseDelta) -> None: ...
      def on_tool_use_end(self, event: ToolUseEnd) -> ToolExecutionHandle: ...
      def results_in_order(self) -> list[ToolExecution]: ...
      def cancel_all(self) -> None: ...
  ```
- Uses a `ThreadPoolExecutor` (not asyncio — executor is currently sync). Safe tools submit immediately; unsafe tools queue. Dispatcher serializes any call that requires a permission prompt (drains the pool before showing the modal).
- Respects `capabilities.parallel_tool_calls`: false → sequential; true → up to `max_concurrency`. Per-tool `is_concurrency_safe=False` always sequential regardless.
- Hook lifecycle: `PRE_TOOL_USE` fires inside the worker *before* the tool runs; `POST_TOOL_USE` fires after. Hook denial aborts that call with a tool-result error, does not abort sibling calls.
- Tests: `tests/test_streaming_tool_dispatch.py` — tables of (tools, flags, capabilities) → expected execution order and timing. Permission-prompt serialization. Cancellation drains in-flight. Hook denial isolates.

**P1a.3 — Orchestrator integration.**
- Modify `cli/llm/orchestrator.py` — replace the post-message dispatch block with `StreamingToolDispatcher` driven by the existing streaming-event pipeline. At each `ToolUseEnd` from `collect_stream`, push into the dispatcher. When the assistant message finishes, call `results_in_order()` and feed them into the follow-up model call.
- Preserve **all** existing semantics: plan-mode tool allowlist, skill-bound tool allowlist, permission checks, hook events, max_tool_loops cap, usage aggregation.
- Tests: `tests/test_orchestrator_streaming_dispatch.py` — multi-tool turns run faster than sequential baseline; cancellation mid-tool still leaves session state consistent; plan mode still blocks writes.

**P1a.4 — Ctrl+C cancellation.**
- Wire `cli/workbench_app/cancellation.py` into the dispatcher — `cancel_all()` signals every in-flight tool via the shared `threading.Event` already used by `TaskExecutor`.
- Tests: `tests/test_streaming_dispatch_cancellation.py` — dispatcher receives cancel, all workers exit cleanly within a short budget, partial results are discarded (model does not see them).

### P1b — Structured diff widget (tasks)

**P1b.1 — Pure `build_diff_lines` helper.**
- Create `cli/workbench_app/tui/widgets/structured_diff.py` — pure function first, Textual widget second (same pattern as `task_tree.py`).
- `build_diff_lines(old: str, new: str, *, language: str | None, width: int) -> list[DiffRow]`
- Uses `difflib` for hunks, `pygments` for highlighting (lazy import; no-op when missing).
- Side-by-side layout when width ≥ 80 cols; unified when narrower. Gutter column for line numbers.
- Cache: bounded LRU keyed by `(sha256(old), sha256(new), language, width)`. Max 64 entries. Evict LRU.
- Tests: `tests/test_structured_diff.py` — golden cases for Python / TypeScript / YAML / Markdown / plain text / very-long-line / very-many-hunks / binary-detected. Cache hit / evict. Narrow-width fallback. Pygments-missing fallback.

**P1b.2 — Textual widget wrapping the helper.**
- `class StructuredDiff(Widget)` that calls `build_diff_lines` and renders. Static tests only — no Textual event-loop dependency.
- Refresh-if-mounted gate (same pattern as `task_tree.py`).

**P1b.3 — Tool rendering hook.**
- Extend `cli/tools/rendering.py` with a `StructuredDiffRenderable(old, new, file_path)` variant.
- Modify `cli/tools/file_edit.py::FileEditTool.render_result` to emit the new renderable on success; line-mode REPL falls back to the existing unified diff string (check for `render_result` fallback behavior in the executor).
- Modify `cli/tools/file_write.py::FileWriteTool.render_result` similarly (left side empty for new files; right side truncated if > 1000 lines).
- Tests: `tests/test_file_edit_structured_diff.py` — tool result round-trips to the renderable; line-mode fallback still reads.

### Critical invariants P1 must preserve

- **Snapshot stability.** `tests/test_system_prompt.py` stays byte-for-byte.
- **Tool semantics unchanged.** Opt-in concurrency means a single-tool turn behaves identically to today's sequential path (same hook order, same permission prompts).
- **Permission prompt never races.** Any tool needing a prompt drains the pool first. Test this explicitly.
- **Hook order honored.** `PRE_TOOL_USE` / `POST_TOOL_USE` fire per-tool in declared order even when execution is parallel. The *dispatcher* parallelizes; the *result stream* is ordered.
- **Cancellation is graceful.** Ctrl+C mid-turn leaves `TaskStore` consistent (any in-flight task marked FAILED, not zombie RUNNING).
- **Diff widget degrades.** Narrow width → unified. Pygments missing → plain text. Never crash the renderer.
- **Line-mode REPL still works.** `AGENTLAB_NO_TUI=1` must still show a readable unified diff.

### Workflow

1. Worktree: `git worktree add .claude/worktrees/p1-streaming-diff -b claude/cc-parity-p1 master` (after P0.5 merged).
2. Dispatch P1a first (Slice A — blocks P2).
3. After P1a lands and tests pass, dispatch P1b (independent). Or run P1b in parallel with P1a if you have two engineers.
4. After both slices ship, dogfood: open workbench, edit a large file with multi-tool chain, confirm latency improves and diff looks good.
5. Open a PR before moving on.

### If you get stuck

- Thread pool + permission modal is the trickiest interaction. Keep it simple: any tool that might prompt drains the pool by `executor.shutdown(wait=True)` before invocation, re-creates a fresh pool after. The permission dialog is already a modal Textual screen — take the hit in throughput to preserve modality.
- Diff cache key must include `width` — same hunks at different widths render differently.
- Pygments has many edge cases (Go generics, Rust macros). Wrap the lex call; on exception, emit plain (non-highlighted) rows.
- If `cli/tools/rendering.py`'s existing `Renderable` ABC can't cleanly express the side-by-side shape, extend it rather than replace — other tools depend on it.
- Tests for cancellation can flake on slow CI; use a test clock + explicit synchronization rather than `time.sleep`.

### Anti-goals

- Do not add compaction UI. That is P2.
- Do not add a permission classifier. That is P3.
- Do not add async/await to the tool executor yet — thread pool first. Full async is a future rewrite.
- Do not add a new file-diff tool. Existing `FileEditTool` + `FileWriteTool` are the surface.

### First action

After the user confirms they want to start P1, read the roadmap's P1 section, read the ten ground-truth files, write the TDD expansion plan, commit, dispatch P1a.1.

Use superpowers and TDD. Work in subagents. Be specific.
