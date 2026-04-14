# AgentLab Ink Terminal Renderer Analysis

Date: 2026-04-14

Branch: `feat/ink-terminal-renderer-codex-yolo`

Reference repo inspected: `https://github.com/codeaashu/claude-code`

Local reference checkout: `/tmp/codeaashu-claude-code-reference`

## Executive Summary

AgentLab's CLI is Python-first today: Click commands, prompt_toolkit input, a Python workbench loop, and pure rendering helpers. The reference repository is a React/terminal app with a custom Ink fork, React components, terminal DOM nodes, Yoga-style layout, and a large component tree for messages, prompt input, status lines, dialogs, panes, and progress states.

The safest production landing is not a wholesale Node/React renderer migration. That would introduce packaging risk, cross-runtime complexity, and licensing/copying concerns. Instead, this pass establishes a Python-native terminal renderer adapter in `cli/terminal_renderer.py`, then routes the most visible Workbench surfaces through it:

- startup session pane
- stable footer divider/status line
- structured `/help` pane
- structured Workbench candidate summary panes
- fractional progress bars for task progress events that carry `ratio`, `progress`, or `current`/`total`

This gives AgentLab an Ink-inspired composition boundary now, while preserving current CLI and workbench workflows.

## What I Inspected In The Reference Repo

### Repository And Runtime Shape

- `package.json`
  - React 19, a custom Ink fork, terminal dependencies such as `wrap-ansi`, `strip-ansi`, `chalk`, `figures`, markdown/highlighting dependencies, and Bun-based build scripts.
  - Important caution: the package is private/unlicensed/leaked according to its metadata, so this pass treats it strictly as a pattern reference. I did not copy large code chunks.

- `prompts/06-ink-react-terminal-ui.md`
  - Gives a useful map of the custom Ink pipeline and the intended verification flow for the terminal renderer.
  - Key referenced files: `src/ink.ts`, `src/ink/root.ts`, `src/ink/reconciler.ts`, `src/ink/dom.ts`, `src/ink/renderer.ts`, `src/ink/components/*`.

### Ink Pipeline Files

- `src/ink.ts`
  - Public wrapper around the internal Ink runtime.
  - Wraps render/createRoot calls in a `ThemeProvider`.
  - Re-exports themed `Box`, `Text`, hooks, links, raw ANSI, spacer, and terminal primitives from one import boundary.

- `src/ink/root.ts`
  - Defines `render`, `createRoot`, `Instance`, and `Root` concepts.
  - Keeps instance management separate from rendering, similar to `react-dom` root semantics.
  - Preserves an async boundary before first render and registers roots by stdout stream.

- `src/ink/renderer.ts`
  - Converts the virtual terminal DOM into frames.
  - Tracks screen buffers, viewport dimensions, dirty state, cursor behavior, alternate screen constraints, and incremental rendering.
  - The lesson for AgentLab is not to recreate this now; it is to keep terminal rendering centralized and side-effect-controlled before attempting dynamic frame diffing.

- `src/ink/dom.ts`
  - Defines terminal DOM node shapes such as text, box, link, progress, raw ANSI, dirty flags, child nodes, layout nodes, and scroll metadata.
  - The useful pattern is a typed intermediate representation between app events and terminal output.

### Product Components And UX Patterns

- `src/components/design-system/ProgressBar.tsx`
  - Fixed-width fractional block progress bar using Unicode block segments.
  - Clamps progress and keeps the rendered width stable.

- `src/components/design-system/Divider.tsx`
  - Terminal-width-aware divider with optional centered title.
  - Handles padding and title width rather than using ad hoc separators.

- `src/components/design-system/Pane.tsx`
  - Slash-command region primitive: a divider plus padded content.
  - Avoids every command inventing its own format.

- `src/components/PromptInput/PromptInput.tsx`
  - Full REPL input surface with history, modes, autocomplete, paste handling, overlays, and shortcut handling.
  - Too application-specific to port directly, but validates that input chrome should be treated as a first-class component.

- `src/components/PromptInput/PromptInputFooter.tsx`
  - Responsive footer that changes layout under narrow terminals, hides lower-priority content when short, and keeps notifications/status/hints together.

- `src/components/StatusLine.tsx`
  - Status line generation is debounced, abortable, and tied to structured context rather than scattered string concatenation.
  - Expensive data is kept in refs/cached state to avoid rerender churn.

- `src/components/AgentProgressLine.tsx`
  - Tree-shaped progress/provenance rows with task status, tool counts, token counts, resolved/background states, and stable glyph positions.

- `src/components/ToolUseLoader.tsx`
  - Small status glyph with stable min width and resolved/error/unresolved states.

- `src/components/Messages.tsx` and `src/components/Message.tsx`
  - Structured, type-dispatched message rendering.
  - Differentiates user, assistant, system, tool, attachment, and collapsed groups.

- `src/components/Markdown.tsx`
  - Streaming-aware markdown rendering with caching and fast paths.
  - Worth deferring until AgentLab has richer streaming assistant output.

## Ink / React Terminal Patterns Worth Adopting

1. Central renderer boundary
   - Reference uses `src/ink.ts` as the single import boundary for terminal primitives.
   - AgentLab should keep Python CLI business logic from owning ANSI details. This pass adds `cli/terminal_renderer.py` for that role.

2. Pane primitive for slash/status surfaces
   - Reference `Pane` and `Divider` make command output feel coherent.
   - AgentLab now uses shared panes for startup session context, `/help`, candidate summaries, readiness, provenance, and next steps.

3. Fixed-width progress bars
   - Reference `ProgressBar` uses fractional Unicode block segments and clamps input.
   - AgentLab now has `render_progress_bar()` and task progress events with `ratio`, `progress`, or `current`/`total` render stable fractional bars.

4. Structured progress/provenance rows
   - Reference `AgentProgressLine` makes work legible by showing status, tool count, tokens, and background/resolved state.
   - AgentLab now starts this direction by making Workbench candidate summaries explicit about overview, readiness, provenance, and next command.

5. Stable footer/status chrome
   - Reference footer keeps mode, notifications, status, and hints stable and responsive.
   - AgentLab now routes the turn footer through the shared renderer so the divider and permission/task counters are consistent.

6. Responsive terminal layout
   - Reference checks terminal columns and rows before deciding what to show.
   - AgentLab's pane renderer wraps body text to terminal width and has a deterministic fallback width for pipes and tests.

7. Typed event-to-render pipeline
   - Reference message rendering starts from typed message/event shapes.
   - AgentLab already has stream-json progress events and task event renderers; this pass strengthens that path rather than bypassing it.

## What AgentLab Already Has

AgentLab already had a meaningful Claude-Code-like CLI foundation before this pass:

- `runner.py`
  - Default `agentlab` entry can launch Workbench in a TTY and fall back in non-interactive contexts.
  - Long-running commands use shared progress events.

- `cli/workbench_app/app.py`
  - Workbench REPL loop.
  - Branded banner, status line, slash dispatch, Ctrl-C behavior, session store wiring, prompt_toolkit integration path.

- `cli/workbench_app/slash.py`
  - Slash-command dispatch, command history recording, `/help`, `/status`, `/config`, `/memory`, `/resume`, `/clear`, `/new`, `/model`, and streaming command registration.

- `cli/workbench_app/commands.py`
  - Three-tier command taxonomy: `LocalCommand`, `LocalJSXCommand`, and `PromptCommand`.
  - This already mirrors part of the reference's command architecture.

- `cli/workbench_app/status_bar.py`
  - Immutable status snapshot and stateful status bar holder.

- `cli/workbench_render.py`
  - Workbench event renderers.
  - Tool-call block renderer for `task.started`, `task.progress`, `task.completed`, and `task.failed`.
  - Candidate summary, save result, bridge status, project list, validation, and plan rendering.

- `cli/progress.py`
  - Shared stream-json/text progress event renderer.
  - TTY spinner for long-running phases.

- Tests around:
  - Workbench app loop
  - slash commands
  - prompt_toolkit prompt behavior
  - tool-call blocks
  - progress renderer
  - candidate lifecycle

## Gap Between Current CLI And Desired Renderer

### Current State

- Workbench rendering is mostly Python string output with ANSI styling.
- Some surfaces are already structured, but formatting logic is scattered across modules.
- Startup, help, status, candidate summary, save result, bridge status, progress, and transcript blocks use different layout conventions.
- There is no true React/Ink runtime in the Python CLI package.
- There is no root Node package for CLI renderer code, and adding one now would change packaging and install assumptions.

### Desired Direction

- A consistent terminal component system:
  - dividers
  - panes
  - progress bars
  - status footers
  - provenance blocks
  - result sections
  - responsive wrapping

- A stronger event-to-render contract:
  - structured events in
  - renderer primitives out
  - business logic does not concatenate terminal UI manually

- Optional future Ink/React integration:
  - possibly a sidecar renderer or Node subpackage once the Python renderer contract is stable
  - no wholesale CLI rewrite until packaging, IPC, testing, and fallback behavior are specified

### Main Gaps Remaining After This Pass

- No real React reconciler or Ink runtime in AgentLab yet.
- No full-screen virtual scroll/alternate screen implementation for Workbench transcripts.
- No markdown/structured assistant content renderer yet.
- Some existing surfaces still render ad hoc strings: save result, bridge status, validation, project lists, and several slash command outputs.
- Footer task/shell counts are still static placeholders in the basic REPL loop; the renderer can display live counts once the loop owns those counters.

## Prioritized Renderer Plan

### P0: Stabilize Python Terminal Primitives

Status: started in this pass.

- Centralize terminal width detection, dividers, panes, footers, and progress bars in `cli/terminal_renderer.py`.
- Keep all primitives deterministic in non-TTY and test environments.
- Preserve existing CLI text semantics and commands.
- Add tests for wrapping, stable widths, progress clamping, and footer copy.

### P1: Route More Workbench Surfaces Through The Renderer

Status: partially implemented.

- Done now:
  - startup session pane
  - footer renderer
  - `/help` pane
  - candidate overview/readiness/provenance/next-step panes
  - task progress bars for structured progress payloads

- Next candidates:
  - `render_save_result`
  - `render_bridge_status`
  - `render_validation`
  - `render_project_list`
  - `/model`, `/status`, `/doctor`, `/mcp` workbench displays

### P2: Add Structured Result Blocks

Status: follow-up.

- Normalize common result shapes:
  - `StatusBlock`
  - `ProgressBlock`
  - `ProvenanceBlock`
  - `ArtifactBlock`
  - `NextActionBlock`
  - `WarningBlock`
  - `ErrorBlock`

- Let command handlers return structured blocks internally, then render them at the edge.

### P3: Make Footer Counts Live

Status: follow-up.

- Wire active subprocess/tool/task counters into `run_workbench_app`.
- Preserve the current Ctrl-C behavior.
- Show live task/shell counts in the footer.

### P4: Evaluate A True Ink Sidecar

Status: deliberately deferred.

- Only after the Python renderer contract is stable.
- Needs a design for:
  - packaging
  - Python-to-Node IPC
  - no-Node fallback
  - test harness
  - ANSI/TTY behavior under CI
  - stream-json compatibility

## What I Chose To Implement Now And Why

### `cli/terminal_renderer.py`

Implemented:

- `terminal_width()`
- `render_divider()`
- `render_pane()`
- `render_progress_bar()`
- `render_status_footer()`

Why:

- This is the safest analogue to the reference's `src/ink.ts` boundary.
- It keeps terminal formatting out of business logic.
- It gives a future Ink renderer a clear set of shapes to replace or wrap.
- It works in the current Python CLI without new runtime dependencies.

### Startup Session Pane

Implemented in `cli/workbench_app/app.py`.

Why:

- The reference makes startup context feel like a composed terminal surface.
- AgentLab already had the data: cwd, status, permission mode, shortcuts.
- A pane makes this more readable without changing launch behavior.

### Stable Footer Renderer

Implemented in `cli/workbench_app/app.py`.

Why:

- Footer/status chrome is a core Claude-Code-like affordance.
- The shared renderer keeps divider width and count grammar consistent.
- Existing tests still validate the permission and task/shell copy.

### Structured `/help` Pane

Implemented in `cli/workbench_app/slash.py`.

Why:

- `/help` is a high-frequency surface and benefits immediately from a pane layout.
- It proves slash screens can move to shared primitives without changing command registration.

### Structured Candidate Summary

Implemented in `cli/workbench_render.py`.

Why:

- Candidate summary is the key non-interactive Workbench surface.
- The old output mixed overview, readiness, caveat, and next step in a flat list.
- New panes make the handoff semantics clearer:
  - Workbench Candidate
  - Readiness
  - Provenance
  - Next Step

### Fractional Task Progress Bars

Implemented in `cli/workbench_render.py`.

Why:

- Progress bars were one of the strongest low-risk reference patterns.
- The change is backwards-compatible: task progress without numeric progress data still renders exactly as before.
- When events include `ratio`, `progress`, or `current`/`total`, users now get a stable visual bar and percentage.

## What I Chose Not To Implement Now And Why

### Full React/Ink Runtime Migration

Deferred.

Why:

- AgentLab's CLI is Python-first.
- There is no root Node CLI package today.
- A full migration would change install, packaging, execution, error handling, and test behavior.
- The reference includes private/unlicensed/leaked metadata, so copying the custom Ink fork or components would be inappropriate.

### Alternate Screen / Virtual Scroll

Deferred.

Why:

- Useful, but high-risk.
- It changes terminal lifecycle behavior and can easily break CI, pipes, and Ctrl-C semantics.
- AgentLab needs stronger structured blocks and live counters first.

### PromptInput Rewrite

Deferred.

Why:

- The reference prompt input is deeply coupled to its app state, bridge mode, model picker, notifications, and permission system.
- AgentLab already uses prompt_toolkit and has working slash completion/keyboard behavior.
- The safer path is to preserve prompt_toolkit and improve surfaces around it.

### Markdown / Syntax Highlighted Streaming Renderer

Deferred.

Why:

- Valuable once AgentLab streams rich assistant prose/code blocks through Workbench.
- This pass focused on Workbench command/progress/candidate UX, which had clearer immediate value and lower risk.

### Live Footer Counters

Deferred.

Why:

- The renderer can display counts now.
- The REPL loop still needs a trustworthy source of active shell/task counts.
- Faking live counts would harm trust; static placeholders remain until the event loop owns real counters.

## Validation Added

New tests:

- `tests/test_workbench_terminal_renderer.py`
  - progress bar clamping
  - fractional bar segments
  - divider title centering
  - pane wrapping
  - footer count/plural rendering

- `tests/test_workbench_render_surface.py`
  - candidate summary uses structured panes
  - readiness/provenance/next-step text remains visible

Updated tests:

- `tests/test_workbench_app_stub.py`
  - startup banner includes the `Session` pane
  - footer retains a divider and permission/task affordances

- `tests/test_workbench_slash.py`
  - `/help` uses structured pane output and stays width-bounded

- `tests/test_tool_call_block.py`
  - task progress with `current`/`total` renders a fractional progress bar and percentage

## Validation Executed

- `.venv/bin/python -m py_compile cli/terminal_renderer.py cli/workbench_app/app.py cli/workbench_app/slash.py cli/workbench_render.py`
  - passed
- `.venv/bin/python -m pytest tests/test_workbench_terminal_renderer.py tests/test_workbench_render_surface.py tests/test_tool_call_block.py tests/test_tool_call_block_unit.py tests/test_workbench_app_stub.py tests/test_workbench_slash.py tests/test_cli_workbench.py -q`
  - `171 passed in 27.74s`
- `.venv/bin/python -m pytest tests/test_workbench_eval_slash.py tests/test_workbench_optimize_slash.py tests/test_workbench_deploy_slash.py tests/test_workbench_build_slash.py tests/test_workbench_status_bar.py tests/test_workbench_default_entry.py tests/test_workbench_completer.py tests/test_workbench_transcript.py -q`
  - `205 passed, 2 warnings in 0.40s`
  - Warnings are the existing classic REPL deprecation warnings in `runner.py`.
- `.venv/bin/python -m pytest tests/test_cli_progress.py tests/test_cli_commands.py tests/test_workbench_streaming.py tests/test_workbench_hardening.py tests/test_workbench_p0_hardening.py tests/test_workbench_screens.py tests/test_workbench_model_slash.py tests/test_workbench_skills_slash.py tests/test_workbench_pt_prompt.py tests/test_workbench_output_collapse.py tests/test_workbench_effort.py tests/test_workbench_cancellation.py -q`
  - `252 passed in 42.14s`
- `printf '/help\n/exit\n' | .venv/bin/python runner.py workbench interactive`
  - passed; Workbench rendered the startup session pane, structured `/help` pane, status footer, and clean goodbye path.
- `git diff --check`
  - passed

## Residual Risks

- Width handling is simple and ANSI-aware only through `click.unstyle`; it is not a full grapheme-width implementation.
- Unicode block bars assume a UTF-capable terminal. Existing AgentLab output already uses Unicode glyphs; an ASCII fallback could still be added later.
- Candidate summary output changed layout. Existing tests cover key strings, but downstream scripts that parse human text instead of JSON may need to prefer `--json`.
- `render_pane()` wraps plain text well, but command outputs with embedded ANSI sequences inside body lines should be handled carefully.
- A true Ink renderer remains a larger architectural project.

## Follow-Up Opportunities

1. Move `render_save_result()`, `render_bridge_status()`, and `render_validation()` to shared panes.
2. Add an ASCII/NO_COLOR compatibility path for progress bars if field operators need non-Unicode logs.
3. Introduce typed render blocks so slash handlers return structured data rather than preformatted strings.
4. Wire real active task/shell counts into `render_status_footer()`.
5. Add a terminal snapshot/golden test for `agentlab workbench show` in text mode.
6. Design a true Ink sidecar proof of concept only after the Python renderer contract stabilizes.
7. Consider a markdown/code block renderer for assistant transcript output once Workbench streams richer prose into the terminal.

## Bottom Line

This pass deliberately lands the renderer spine before the renderer transplant. AgentLab now has a tested, centralized, Ink-inspired terminal composition layer and uses it in the highest-leverage CLI/workbench surfaces, while preserving the current Python CLI architecture and existing workflows.
