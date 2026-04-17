## P1 TDD Expansion Plan

Date: 2026-04-17
Branch: `claude/cc-parity-p1`
Scope: P1a streaming tool dispatch, then P1b structured diff

### Why this plan exists

P1 changes the hottest part of the turn loop and the most visible file-edit UX.
That combination is worth slowing down for long enough to make the work legible,
test-first, and safe to land in slices.

The roadmap spec is the source of truth, but the repo reality matters:

- `cli/llm/orchestrator.py` currently streams text live, then calls
  `collect_stream()` and executes the resulting tool blocks after the assistant
  message finishes.
- `cli/tools/executor.py` already centralizes permissions, plan-mode checks,
  skill overlays, and hook firing. P1a should preserve that seam rather than
  re-implement policy logic in the dispatcher.
- `cli/tools/rendering.py` does not exist yet on this branch, so P1b will add
  it as a narrow extension point rather than modifying transcript rendering ad
  hoc.
- `cli/workbench_app/tui/widgets/task_tree.py` does not exist either; the best
  local pattern for "pure helper + thin UI wrapper" is the pair of
  `cli/workbench_render.py::ToolCallBlockRenderer` and the small Textual
  widgets under `cli/workbench_app/tui/widgets/`.
- The bundled tool surface in this branch is smaller than the roadmap's full
  future surface. Current built-ins are:
  `FileRead`, `FileEdit`, `FileWrite`, `Glob`, `Grep`, `Bash`, `ConfigRead`,
  `ConfigEdit`, `AgentSpawn`, `WebFetch`, `WebSearch`, `TodoWrite`,
  `SkillTool`, and `ExitPlanMode`. There is also an MCP bridge tool module,
  but it is not part of `default_registry()`.

### Non-negotiable invariants

1. `tests/test_system_prompt.py` stays byte-for-byte unchanged.
2. Single-tool turns keep today's semantics and hook ordering.
3. Permission prompts never race with parallel execution.
4. Plan mode and skill allowlists still gate tools exactly once, in the same
   place they do today.
5. Ctrl+C cancellation leaves no zombie in-flight work and no partial tool
   results visible to the model.
6. `AGENTLAB_NO_TUI=1` style flows still get a readable unified diff string.

### Slice order

1. Slice A: P1a streaming tool dispatch.
2. Slice B: P1b structured diff widget.

P1a goes first because it blocks P2 and shares the orchestrator dispatch seam
with P2. P1b is independent once P1a is green.

### Subagent workflow

I will keep the controller role in this session and use subagents for bounded
tasks after the plan commit:

- Implementer subagent for each P1a/P1b task or tightly related task pair.
- Spec reviewer subagent after each implementation step.
- Code-quality reviewer subagent after spec compliance is green.

The critical path stays local when I need immediate integration context, but
review passes and clearly bounded sidecar work can be delegated.

### Baseline architectural decisions

#### P1a dispatcher shape

- Add `Tool.is_concurrency_safe: bool = False` as a class attribute.
- Keep `execute_tool_call()` as the only place that decides policy, prompts,
  hooks, and tool execution details.
- Add a new pure-ish coordinator in `cli/llm/streaming_tool_dispatcher.py`
  that owns:
  - tool input assembly keyed by tool-use id,
  - declared order buffering,
  - thread-pool submission for safe tools,
  - sequential queueing for unsafe tools,
  - permission-prompt serialization by draining the pool before any
    prompt-eligible call,
  - cancellation fan-out.
- Keep the orchestrator synchronous overall. The dispatcher may use threads,
  but `run_turn()` still returns only after the assistant/model cycle is done.

#### P1b rendering shape

- Introduce `cli/tools/rendering.py` as a small typed renderable layer for tool
  outputs that need richer TUI rendering than plain markdown.
- Add `cli/workbench_app/tui/widgets/structured_diff.py` with:
  - a pure `build_diff_lines(...)` helper,
  - a `StructuredDiff` Textual wrapper,
  - a bounded LRU cache keyed by content hashes, language, and width.
- Preserve tool-to-model output as readable text while separately enabling a
  richer user-facing display path.

### TDD task expansion

#### P1a.1 - concurrency flags on bundled tools

Red:
- Add `tests/test_tool_concurrency_flags.py`.
- Assert every bundled tool in `default_registry()` has an explicit expected
  `is_concurrency_safe` value.
- Assert the allowlist is exactly the read-only set that exists in this branch:
  `FileRead`, `Glob`, `Grep`, `ConfigRead`, `WebFetch`, `WebSearch`.
- Assert all mutating or interaction-heavy tools remain false:
  `FileEdit`, `FileWrite`, `Bash`, `ConfigEdit`, `AgentSpawn`, `TodoWrite`,
  `SkillTool`, `ExitPlanMode`.
- Assert the MCP bridge tool type defaults false.

Green:
- Add `is_concurrency_safe = False` to `Tool`.
- Opt in the allowlisted built-ins only.

Refactor:
- Keep the allowlist obvious in tests and near each tool class; do not add a
  central flag registry that can drift.

Commit:
- `test(tools): lock concurrency safety flags`

#### P1a.2 - dispatcher helper

Red:
- Add `tests/test_streaming_tool_dispatch.py` covering:
  - all-sequential behavior when provider capability disables parallel calls,
  - mixed safe/unsafe calls where safe calls overlap and unsafe calls serialize,
  - declared-order result buffering even when completion order differs,
  - hook denial isolation for a single tool,
  - prompt serialization: a prompt-eligible tool waits until active safe calls
    finish, then prompts alone,
  - cancellation drains queued and in-flight work.

Test design:
- Use stub tools with controllable barriers instead of `sleep`.
- Use a fake executor callback that records start/end order, thread overlap,
  and hook outcomes.
- Represent result handles explicitly so tests can ask whether a tool was
  submitted, running, cancelled, or completed.

Green:
- Create `cli/llm/streaming_tool_dispatcher.py`.
- Core types:
  - `ToolExecutionHandle`
  - `OrderedToolCall`
  - `StreamingToolDispatcher`
- Dispatcher responsibilities:
  - collect `ToolUseStart`/`ToolUseDelta`/`ToolUseEnd`,
  - submit safe calls immediately when allowed,
  - queue unsafe calls behind active work,
  - treat `capabilities.parallel_tool_calls=False` as global sequential mode,
  - expose `results_in_order()` that waits for completion and returns
    `ToolExecution` in original declaration order,
  - expose `cancel_all()`.

Implementation notes:
- Use `ThreadPoolExecutor`.
- For permission serialization, identify prompt-eligible calls using the same
  `permissions.decision_for_tool(...)` path the executor would use. Before
  running one of those calls, wait for active futures, then execute it
  exclusively, then recreate the pool for later safe calls.
- Keep hook execution inside the worker by continuing to call
  `execute_tool_call()`.

Refactor:
- Extract small helpers for queue draining and exclusive execution.
- Keep public API small; internal state can stay private and simple.

Commit:
- `feat(llm): add streaming tool dispatcher`

#### P1a.3 - orchestrator integration

Red:
- Add `tests/test_orchestrator_streaming_dispatch.py`.
- Cases:
  - streaming model emits multiple `ToolUseEnd` events before `MessageStop`;
    safe tools start before the message completes,
  - overall turn time beats a forced sequential baseline,
  - tool results are still fed back to the model in declared order,
  - plan mode still blocks mutating tools,
  - usage aggregation and post-tool prompt fragments are preserved.

Green:
- Modify `cli/llm/orchestrator.py` so `_run_model_turn()` can feed the live
  event stream both to the renderer and to a dispatcher instance.
- Start dispatch as each `ToolUseEnd` arrives.
- After the message ends, call `results_in_order()`, convert to tool_result
  blocks, append any post-tool fragments, and continue the existing loop.
- Keep the non-streaming fallback path by synthesizing events and sending those
  through the same integration path.

Refactor:
- Avoid bloating `run_turn()` by extracting one helper for
  "run model turn with optional streaming tool dispatch".
- Preserve `_result_to_block()` semantics unless P1b needs a richer content
  path.

Commit:
- `feat(llm): stream tool dispatch during model turns`

#### P1a.4 - cancellation wiring

Red:
- Add `tests/test_streaming_dispatch_cancellation.py`.
- Cases:
  - cancelling the dispatcher causes waiting workers to exit promptly,
  - queued tools never start after cancellation,
  - partial results are discarded from `results_in_order()`,
  - no task remains logically running after cancel completes.

Green:
- Thread a cancellation primitive into dispatcher worker context.
- Reuse `cli/workbench_app/cancellation.py` semantics where possible, but use a
  thread-safe signal that sync tools can poll via `ToolContext.cancel_check`.
- Ensure `cancel_all()` marks the dispatcher terminal before any buffered
  partial results can leak to the orchestrator.

Refactor:
- Keep cancellation state separate from provider stream handling so Ctrl+C and
  future transport aborts share the same dispatcher API.

Commit:
- `fix(llm): cancel in-flight streaming tool dispatch cleanly`

### P1b task expansion

#### P1b.1 - pure structured diff helper

Red:
- Add `tests/test_structured_diff.py` with golden-style assertions for:
  - Python, TypeScript, YAML, Markdown, and plain text diffs,
  - narrow width fallback to unified mode,
  - very long lines,
  - many hunks,
  - binary-detected or non-text fallback,
  - cache hit and LRU eviction,
  - missing `pygments`,
  - lexer failure fallback.

Green:
- Create `cli/workbench_app/tui/widgets/structured_diff.py`.
- Add:
  - `DiffRow` dataclass,
  - `build_diff_lines(old, new, *, language, width)`,
  - bounded LRU cache of 64 entries keyed by
    `(sha256(old), sha256(new), language, width)`.
- Use `difflib` for hunking and lazy `pygments` import for highlighting.

Refactor:
- Separate diff production, highlighting, and cache maintenance into helpers.
- Keep width-sensitive layout logic obvious and testable.

Commit:
- `feat(tui): add structured diff builder`

#### P1b.2 - Textual wrapper

Red:
- Add static tests for the widget's render preparation and refresh-if-mounted
  behavior without spinning a Textual app loop.

Green:
- Add `StructuredDiff(Widget)` in the same module, thin over
  `build_diff_lines(...)`.
- Mirror existing widget thread-safety patterns (`call_from_thread` /
  `call_later`) only if needed; prefer a simple static widget first.

Commit:
- `feat(tui): add structured diff widget`

#### P1b.3 - tool rendering hook

Red:
- Add `tests/test_file_edit_structured_diff.py`.
- Cases:
  - `FileEditTool` success returns a renderable carrying old/new/path data,
  - `FileWriteTool` does the same, with empty left side for new files,
  - line-mode fallback still produces unified diff text,
  - large writes truncate the right side for TUI rendering as specified.

Green:
- Add `cli/tools/rendering.py` with a minimal renderable model, including
  `StructuredDiffRenderable`.
- Modify `FileEditTool` and `FileWriteTool` to capture before/after content in
  metadata and/or a renderable display path.
- Update the relevant TUI rendering seam so transcript entries can render the
  structured diff when available and otherwise fall back to text.

Refactor:
- Keep the model-facing tool result content simple text unless the current
  `tool_result` wire path already safely supports structured blocks.

Commit:
- `feat(tools): render file changes as structured diffs`

### Verification plan

After each task:
- Run the new focused test file first and watch it fail before implementation.
- Re-run the focused test file until green.
- Re-run nearby regression suites touched by the change.

Before claiming P1a done:
- `.venv/bin/python -m pytest tests/test_tool_concurrency_flags.py`
- `.venv/bin/python -m pytest tests/test_streaming_tool_dispatch.py`
- `.venv/bin/python -m pytest tests/test_orchestrator_streaming_dispatch.py`
- `.venv/bin/python -m pytest tests/test_streaming_dispatch_cancellation.py`
- `.venv/bin/python -m pytest tests/test_system_prompt.py`

Before claiming P1b done:
- `.venv/bin/python -m pytest tests/test_structured_diff.py`
- `.venv/bin/python -m pytest tests/test_file_edit_structured_diff.py`
- `.venv/bin/python -m pytest tests/test_system_prompt.py`

Before PR:
- `.venv/bin/python -m pytest`
- manual dogfood in the workbench:
  - multi-tool read chain with at least two safe tools,
  - a turn with a prompt-eligible tool after safe reads,
  - large file edit/write to inspect diff rendering,
  - Ctrl+C during a long-running tool.

### Risk checklist

- Do not change system prompt text.
- Do not branch on provider strings; only read
  `capabilities.parallel_tool_calls`.
- Do not allow prompt modals to overlap active worker threads.
- Do not let `ToolExecution` ordering depend on completion order.
- Do not leak partial cancelled results into the next model call.
- Do not make `pygments` a hard dependency at render time.

### Immediate execution order after this doc commits

1. P1a.1 failing tests.
2. Minimal tool flag implementation.
3. P1a.1 verification and commit.
4. P1a.2 dispatcher tests and implementation.
5. P1a.3 orchestrator integration.
6. P1a.4 cancellation hardening.
7. P1b sequence.
