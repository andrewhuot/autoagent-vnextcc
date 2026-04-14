# T03 — Render Stack ADR

Status: **Accepted** (2026-04-13)
Scope: choose the terminal rendering stack that powers `cli/workbench_app/`
(the Claude-Code-style interactive workbench that will become the default
`agentlab` entry point).

## Context

The new workbench app needs, at minimum:

1. **Async input** that can be edited while background events stream to the
   transcript above it (Claude Code's input-box-over-streaming-transcript
   pattern — see `02-claude-code-ux-reference.md` §3, §4).
2. **Streaming output interleaved with a live input buffer** — the status bar
   and transcript update without corrupting what the user is typing.
3. **A bottom-anchored status line** (T06) that never scrolls.
4. **Tool-call blocks** with headers, streaming bodies, and footers that can
   collapse/expand (T08, T18b).
5. **Slash-command autocomplete popup** (T19).
6. **Full-screen modal takeovers** for `/skills`, `/resume`, and `/doctor`
   (T08b, T13) that pause the transcript and own their own key bindings.
7. **Ctrl-C / Esc key binding protocol**: first press cancels the active
   tool call, second press exits (T16) — requires a proper key-binding layer
   and awareness of async task state.
8. **Theming via `click.style`-compatible ANSI** so existing renderers in
   `cli/workbench_render.py` (30+ event renderers) keep working without a
   port.

Out of scope for this decision: chart/image rendering, mouse support,
web-view fallback. Everything else is terminal-only.

## Options considered

### Option A — `prompt_toolkit` (chosen)

- **Already a first-class dependency** (`pyproject.toml` line 16:
  `prompt_toolkit>=3.0`) and already used by `cli/repl.py`
  (`PromptSession`, `KeyBindings`, `patch_stdout` at `cli/repl.py:352-379`).
  Migrating to it costs zero new deps and lets us reuse live patterns the
  team is already comfortable with.
- `patch_stdout()` solves the single hardest problem — streaming events to
  stdout while a prompt line remains editable — without us reimplementing
  it. This is the exact interaction Claude Code uses.
- `KeyBindings` gives us the Ctrl-C / Esc / Ctrl-O protocol (T16, T18b)
  with explicit handlers, including access to the in-flight async task so
  "first press cancels, second press exits" is implementable cleanly.
- `WordCompleter` / `FuzzyCompleter` power the slash-command popup (T19)
  out of the box.
- `Application` + `Layout` support full-screen takeovers (T08b, T13) via
  nested `Float` / `HSplit` primitives; we can drop into a modal and pop
  back to the transcript.
- Renders plain ANSI text, so every existing `click.style(...)` string in
  `cli/workbench_render.py` keeps working — no renderer rewrite.
- Active, permissively licensed, Python-native, 3.11 compatible.

### Option B — `textual`

- Modern TUI framework; best-in-class widget model, reactive state, CSS.
- **Not currently a dep.** Adding it is a significant new surface area
  (event loop ownership, widget tree, CSS theming) that we do not need
  given our existing ANSI-based renderers.
- Textual strongly prefers to own the full screen and the event loop. Our
  Click subcommands shell out (subprocesses streaming stream-json),
  mix sync and async, and rely on `click.echo`/`click.style` ANSI strings
  — bridging those into Textual widgets is a rewrite, not a migration.
- Every renderer in `cli/workbench_render.py` would need to be rewritten
  as widget output rather than plain printable strings, blowing the
  scope of this refactor.
- Keep in reserve: if we ever need a side-panel inspector or embedded
  charts, Textual is the escape hatch. Not today.

### Option C — `rich.live.Live` + `input()` / readline

- Lightweight; excellent renderers (tables, syntax, diffs).
- **`rich.Live` does not compose with a persistent editable input line.**
  The canonical pattern is either live output *or* prompts, not both. To
  get Claude Code's behavior we would have to hand-roll what
  `prompt_toolkit.patch_stdout` already provides.
- No native key-binding layer — Ctrl-C handling, autocomplete popups, and
  modal screens would all be bespoke.
- Could be added *alongside* prompt_toolkit later for niceties like diff
  rendering (see "Future work" below), but it is not a sufficient primary
  stack.

### Option D — Raw `curses` / `blessed`

- Rejected. Too low-level; we'd be rebuilding what prompt_toolkit gives us.

## Decision

**Primary stack: `prompt_toolkit>=3.0`.**

- `workbench_app/app.py` owns the top-level `prompt_toolkit.Application`
  (or `PromptSession` for early stubs — T04 uses `PromptSession` because
  the stub is echo-only; we upgrade to `Application` when T08b screens
  land).
- `patch_stdout()` wraps every streaming write so the transcript appends
  cleanly above the live input line.
- `KeyBindings` owns Ctrl-C / Esc / Ctrl-O / slash-trigger behavior.
- `Completer` subclass drives the slash-command autocomplete popup.
- Status bar is a bottom toolbar (`bottom_toolbar=` callable) for
  `PromptSession`, or a dedicated `Window` in the full `Application`.
- Event renderers in `cli/workbench_render.py` keep emitting
  ANSI-colored strings via `click.style`; prompt_toolkit prints them
  verbatim. No renderer port required.

## Secondary / complementary

- `click.style` stays the coloring primitive (already pervasive in
  `cli/`). No migration to `rich.console` unless we hit a renderer we
  cannot express in ANSI.
- `asyncio` subprocesses (not `subprocess.Popen`) for `/eval`,
  `/optimize`, `/build`, `/deploy` so cancellation is cooperative and
  the event loop stays responsive (T16 depends on this).

## Consequences

- No new runtime dependencies needed — `prompt_toolkit` is already
  installed.
- Existing `cli/repl.py` patterns (PromptSession, patch_stdout,
  KeyBindings) transfer directly; much of T04's stub can reuse that
  wiring.
- Tests: prompt_toolkit supports scripted input via `create_pipe_input`
  and `DummyOutput`, which we will use in T23/T24 integration tests
  instead of pty hacks.
- Full-screen screens (T08b) require moving from `PromptSession` to
  `Application` once we introduce them. That's a planned step, not a
  surprise — call it out in T08b.

## Future work (out of scope for this ADR)

- If we add side-by-side panes (transcript + inspector) we can either
  stay in prompt_toolkit (`HSplit`) or reach for Textual. Revisit then.
- `rich` could be added later as a pure renderer (diffs, tables) whose
  output we capture as ANSI and hand to prompt_toolkit. No decision
  needed now.

## pyproject.toml impact

None. `prompt_toolkit>=3.0` is already declared. No version bump
required. This ADR explicitly records that we are *not* adding
`textual` or `rich` at this time.
