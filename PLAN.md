# PLAN: Refactor AgentLab CLI Workbench to Claude Code UX

## Goal
Refactor the AgentLab CLI workbench so it mirrors Claude Code's interactive experience: a
single persistent terminal app with a status line, streaming transcript, slash-command
surface (/eval, /optimize, /build, /deploy, /skills, /help, /status, /model, /clear,
/resume, etc.), live tool-call blocks, and first-class skill authoring. The workbench
becomes the default `agentlab` entry point so users can watch the harness work in real
time instead of scripting disjoint one-shot commands.

## Reference architecture
Mirror source: https://github.com/yasasbanukaofficial/claude-code
Key patterns we're borrowing (TS→Python translation, not code copy):
- Three-tier command taxonomy: `local` / `local-jsx` / `prompt` (src/types/command.ts)
- `onDone(result, display, shouldQuery, metaMessages)` return protocol
- Full-screen takeover pattern (src/screens/{REPL,Doctor,ResumeConversation}.tsx)
- UX primitives: `AgentProgressLine`, `BashModeProgress`, `CompactSummary`,
  `FileEditToolDiff`, `ContextVisualization`, `CtrlOToExpand`, `EffortIndicator`
- `/skills` as a navigable screen (SkillsMenu), not a flat CLI

## Constraints
- Preserve every existing Click subcommand (`runner.py`). Workbench commands must delegate
  to them rather than re-implementing logic.
- Match project conventions already used in `cli/` (Click, click.style, rich if present).
- Every new module ships with tests. Every bugfix adds a regression test.
- Never commit directly to main. Branch: refactor branch off `feat/cli-live-first-and-loading`.
- No `any`/untyped blobs — type events explicitly.
- Changes stream incrementally to the transcript; no silent long-running work.

## Tasks

- [x] **T01** — Audit the current surface: enumerate every slash command in `cli/repl.py`,
      every event type in `cli/workbench_render.py::_EVENT_RENDERERS`, and every Click
      command in `runner.py`. Write findings to
      `working-docs/workbench-refactor/01-current-surface.md`.
- [x] **T02** — Document Claude Code UX reference (banner, status line, input box, tool
      blocks, transcript compaction, slash-command popup, ctrl-c behavior) to
      `working-docs/workbench-refactor/02-claude-code-ux-reference.md`. Pull from the
      linked blog + source repo notes.
- [x] **T02b** — Port Claude Code's three-tier command taxonomy to
      `cli/workbench_app/commands.py`. Define typed `LocalCommand`, `LocalJSXCommand`,
      `PromptCommand` dataclasses (mirror `src/types/command.ts` from the mirror:
      `paths` globs, `context: 'inline' | 'fork'`, `agent`, `hooks`, `effort`,
      `allowedTools`, `source`). All future slash commands register through this.
- [x] **T03** — Decide rendering stack (prompt_toolkit vs textual vs rich-live). Record
      decision + rationale in `working-docs/workbench-refactor/03-render-stack-adr.md`.
      Update `pyproject.toml` with the chosen dep. *Decision: prompt_toolkit (already a
      dep; no `pyproject.toml` change). See ADR for rationale.*
- [x] **T04** — Create `cli/workbench_app/__init__.py` and `cli/workbench_app/app.py`
      with a stub interactive loop: banner, status line, input prompt, echo-only. Wire
      into `agentlab workbench interactive` (new subcommand). *Stub uses injectable
      `input_provider` + `echo` seams so tests drive the loop without a TTY. The full
      prompt_toolkit `Application` lands with T16; for now the loop wraps plain `input()`
      plus the shared `build_status_line` helper that T06 will replace.*
- [x] **T05** — Extract slash-command handler registry from `cli/repl.py` into
      `cli/workbench_app/slash.py` with a typed `SlashCommand` dataclass (name, help,
      handler, autocomplete args). Port `/help /status /config /memory /doctor /review
      /mcp /compact /resume /exit`. *All ten built-ins register as `LocalCommand`
      instances via `build_builtin_registry()`. Handlers receive a `SlashContext`
      (workspace/session/session_store/echo/click_invoker/registry) and delegate to
      existing Click commands through an injectable `ClickInvoker` so no business
      logic is duplicated. Exit is signalled via `ctx.request_exit()`, which keeps
      handler return types aligned with `LocalHandler`. `dispatch()` also enforces
      that only `local`-kind commands run inline — `local-jsx` and `prompt` variants
      are recognised but deferred to T08b/T05b respectively. The full `onDone`
      display-routing protocol lands in T05b. Coverage:
      `tests/test_workbench_slash.py` (34 tests).*
- [x] **T05b** — Implement Claude Code's `onDone` return protocol in
      `cli/workbench_app/slash.py`:
      `onDone(result: str | None, *, display: 'skip'|'system'|'user'='user',
      should_query: bool=False, meta_messages: list[str] | None=None)`. Every slash
      handler returns via this contract. Add unit tests for each display mode.
      *Landed `OnDoneResult` + `on_done()` helper in
      `cli/workbench_app/commands.py` and wired dispatch to route `display`
      (`skip` → silent, `system` → dim, `user` → plain), echo `meta_messages`
      as dim lines, and surface `should_query` / `raw_result` on
      `DispatchResult`. Handlers still accept the legacy `str | None` sugar
      (normalized to `display='user'` / `display='skip'`); `/help` is ported
      to return `on_done(...)` explicitly as a reference. Errors from
      handler execution or bad return types route through `display='system'`
      so the loop keeps running. Coverage: 13 new tests in
      `tests/test_workbench_slash.py` covering each display mode,
      `should_query`, `meta_messages` ordering, bare-string/None sugar,
      and unsupported-return-type rejection (47 tests total, all green).*
- [x] **T06** — Implement live status line in `cli/workbench_app/status_bar.py` showing
      workspace label, active config version, model, pending reviews, best score. Update
      on every event. *Landed frozen `StatusSnapshot` + stateful `StatusBar` with
      `refresh_from_workspace(workspace, session, model_override)` and `update(**fields)`
      seams. The bar renders workspace label (cyan), `vNNN` config version, model,
      pending-review count (yellow, singular/plural aware, hidden at zero), best score,
      `extras` key:value pairs (for T07/T08 event overlays like cycle/phase), and a dim
      `agentlab <version>` suffix. `render_snapshot(snap, color=False)` strips ANSI for
      tests and downstream logging. `cli/workbench_app/app.py::build_status_line` now
      delegates here so the T04 banner picks up the richer line for free. Coverage:
      `tests/test_workbench_status_bar.py` (21 tests) — snapshot extraction (label,
      version, model override, session title), tolerance for `resolve_active_config`
      raising, pending-review counting against a real sqlite DB, graceful handling of
      a missing and corrupt cards DB, best-score read + empty-file guard, render
      ordering/color/ANSI round-trip, singular vs plural reviews, extras rendering, and
      `StatusBar.update`'s unknown-field rejection. Full workbench surface green
      (120 tests across slash/status/stub/repl/cli_workbench).*
- [x] **T07** — Implement streaming transcript pane in `cli/workbench_app/transcript.py`
      that consumes `render_workbench_event` output and appends lines with role-based
      coloring. *Landed an append-only `Transcript` with a frozen `TranscriptEntry`
      tagged by a `TranscriptRole` literal (`user` / `assistant` / `system` / `tool`
      / `error` / `warning` / `meta`). Added a pure `format_workbench_event` helper
      in `cli/workbench_render.py` so the transcript can capture event lines without
      the implicit `click.echo` on the existing `render_workbench_event`; the latter
      is now a thin wrapper that calls the pure formatter and echoes, preserving
      every existing caller's behaviour. `Transcript.append_event(event_name, data)`
      delegates to `format_workbench_event`, tags the stored entry with the event
      name + payload for later compaction (T17), and returns `None` when the
      renderer suppresses output (heartbeat / message delta / unknown events) so
      callers don't have to special-case each. Role-based coloring is applied at
      format time (not store time) via `format_entry(entry, *, color)` so the same
      history re-renders with color on or off — used by `Transcript.render(color=…)`
      for future `/resume` replay. Tool entries pass through unchanged because the
      workbench event renderers already emit pre-styled strings; other roles get
      the expected click styles (cyan-bold user `> `, dim system/meta, red-bold
      `! ` errors, yellow `⚠ ` warnings). Extras: `replace_tail` for rolling
      `task.progress` updates (T08 prep), `extend`, `clear`, `set_color`,
      `copy_with(echo, color)` for nested screens (T08b), and a private
      `_redact(entry)` helper that drops the raw event payload for session
      compaction. All output goes through an injectable `echo` seam so tests
      drive the loop without a TTY. Coverage: `tests/test_workbench_transcript.py`
      (28 tests) — every role's formatting, ANSI round-trip, event pass-through,
      suppressed-event branches, `replace_tail` / empty-transcript guard,
      `copy_with` isolation, redaction idempotence, and colored `task.completed`
      green styling. Full workbench surface green (179 tests across
      transcript/status/slash/app stub/commands/cli_workbench/streaming).*
- [x] **T08** — Build the tool-call block renderer: a nested block (header, streaming
      body, footer) for `task.started`/`task.progress`/`task.completed` sequences. Add
      to `cli/workbench_render.py` as `render_tool_call_block(event_stream)` + unit tests.
      *Landed frozen `ToolCallBlockState` + stateful `ToolCallBlockRenderer` keyed by
      `task_id` (with title/name fallback), plus a `render_tool_call_block(stream)`
      generator for the one-shot batch case. Visual layout mirrors Claude Code:
      cyan-bold `⏺ <title>` header, dim `  ⎿ <note>` body lines, green `  ✓ done
      [source]` footer on `task.completed`, red-bold `  ✗ failed: <reason>` footer on
      `task.failed` (reason/failure_reason/message keys all accepted). Interleaved
      task_ids render independently; duplicate `task.started` refreshes the title
      without re-emitting a header; orphan `task.progress` / `task.completed` events
      synthesize headers on the fly so the block is always balanced. Non-task events
      fall through to `format_workbench_event` so a single renderer can drive the
      whole transcript. `close_all(reason=…)` flushes any still-open blocks with a
      failure footer — used by `render_tool_call_block` when the stream ends with
      open blocks and by the T16 ctrl-c path for orphan cleanup. Coverage:
      `tests/test_tool_call_block.py` (27 tests) — happy path, styling (cyan/dim/
      green/red), state tracking on `open_blocks` / `completed_blocks`,
      task.failed reason fallbacks, interleaved task_ids, duplicate-started,
      orphan progress/completed, empty/missing notes, message-field fallback,
      title/name/task_id resolution priority, title-keyed grouping when task_id is
      absent, non-task passthrough, `harness.heartbeat` + `message.delta`
      suppression, `None` data tolerance, `close_all` footer batching, and
      `render_tool_call_block(close_unfinished=False)` opt-out. Full workbench
      surface green (184 tests across tool_call_block/transcript/status/slash/
      app stub/commands/cli_workbench).*
- [x] **T08b** — Port Claude Code's screen/dialog pattern to
      `cli/workbench_app/screens/` (full-screen takeovers that pause the transcript).
      Scaffold `DoctorScreen`, `ResumeScreen`, `SkillsScreen` base classes with a
      `run() -> Result` contract. Each screen owns its own key bindings and restores
      the transcript on exit. *Landed a `cli/workbench_app/screens/` package with
      an abstract `Screen` base class (satisfies the pre-declared `Screen` Protocol
      in `commands.py`), frozen `ScreenResult(action, value, meta_messages)`, and a
      `KeyProvider = Callable[[], str]` seam that accepts either a callable or an
      iterable of keystrokes (`iter_keys([...])`) so tests drive the loop without a
      TTY. `Screen.run()` paints header → `render_lines()` → footer via an
      injectable `echo`, reads keys, dispatches to `handle_key(key)`, and
      re-paints until the subclass returns a result; `EOFError` /
      `KeyboardInterrupt` from the provider both translate into
      `ScreenResult(action="cancel")` so callers always get a well-formed value.
      Keys are normalized (named keys lower-cased, single-character keys
      preserved for case-sensitive bindings). The transcript-restoration
      contract is fixed: screens never write to the main `Transcript`; they
      paint locally and return `meta_messages` that the wrapping
      `LocalJSXCommand` dispatch will surface through `onDone(meta_messages=…)`.
      Three scaffold subclasses: (a) `DoctorScreen` — runs the `doctor` Click
      command via an injectable `DoctorRunner` (cached across re-paints),
      renders stdout lines, exits on `q`/`enter`/`escape`/`ctrl+c`, and paints
      a red error line if the runner throws; (b) `ResumeScreen` — consumes
      either a `Sequence[Session]` or a `SessionStore` (pulling
      `list_sessions(limit=…)` lazily), highlights the cursor row with `▶`
      cyan-bold, navigates on `j/k` / `up/down` (clamped), returns
      `action="resume"` on `enter` and `action="fork"` on `f` (both carry the
      `session_id` plus a dim meta line), `q`/`escape` cancel, empty-list
      renders a dim placeholder and cancels with a meta explanation; (c)
      `SkillsScreen` — displays `SkillItem(skill_id, name, kind, description)`
      rows with `[kind]` prefixes, arrow-key navigation, and action keys
      `l`/`s`/`a`/`e`/`r` returning `ScreenResult(action=<verb>, value=skill_id
      | None)` (list/add omit the selection payload; show/edit/remove carry
      it), `q`/`escape` exit, unknown keys ignored. T13/T17 will flesh these
      into real delegations via `LocalJSXCommand`; the scaffold fixes the
      contract today. Coverage: `tests/test_workbench_screens.py` (28 tests) —
      `iter_keys` exhaustion, base-class paint/re-paint counts, header/footer
      ordering, EOF and KeyboardInterrupt → cancel, named-key lower-casing,
      case-sensitive single-char preservation, `Screen` Protocol conformance,
      `Screen()` abstract-instantiation rejection; `DoctorScreen` runner
      caching, `enter`/`escape` exits, empty-output placeholder, exception
      rendering, unknown-key re-paint; `ResumeScreen` empty list, arrow
      navigation, cursor clamping, enter-returns-id, fork action, cancel
      key, selected-marker rendering, `store=` auto-load ordering;
      `SkillsScreen` empty placeholder, navigate-and-show, add without
      selection payload, remove with selection, unknown-keys-ignored,
      cursor clamping, kind/description rendering. Full workbench surface
      green (212 tests across screens/tool_call_block/transcript/status/
      slash/app stub/commands/cli_workbench).*
- [x] **T09** — Add `/eval [--run-id …]` slash command that spawns `agentlab eval run`
      as an async subprocess, pipes stream-json output through the transcript, and
      surfaces summary on completion. *Landed `cli/workbench_app/eval_slash.py` with
      a frozen `EvalSummary`, an injectable `StreamRunner` seam (default shells out
      to `python -m runner eval run --output-format stream-json` via
      `subprocess.Popen(bufsize=1, text=True, stderr→stdout)`), and an `_parse_args`
      layer that aliases `--run-id <v>` → `--config <v>` so the documented `/eval`
      surface matches the real `eval run` flag. The handler echoes a cyan start
      banner, streams events through `format_workbench_event` (extended to cover
      `phase_started` / `phase_completed` / `artifact_written` / `next_action` /
      `warning`, which were previously emitted but unstyled), and ends with an
      `on_done(...)` summary line — red + `/eval failed` when any `error` event
      arrived or the subprocess exited non-zero, green + `/eval complete`
      otherwise. Meta messages surface the final `next_action` as "Suggested
      next: …" and the last three artifact paths so the main summary stays terse.
      Subprocess errors (`EvalCommandError` from non-zero exit, `FileNotFoundError`
      for a missing interpreter) render a red line and return `display="skip"` so
      dispatch doesn't double-print; unparseable subprocess output is rescued as a
      synthetic `warning` event so nothing is silently dropped.
      `build_builtin_registry()` gained an `include_streaming=True` toggle so tests
      that want just the ten ported built-ins can opt out, and `/eval` registers as
      a `LocalCommand(source="builtin")` by default. Coverage:
      `tests/test_workbench_eval_slash.py` (23 tests) — arg parsing pass-through,
      `--run-id` alias, mixed flags, trailing value, empty; `_render_event` happy
      paths and none-returns; `_summarise` counters (phases/artifacts/warnings/
      errors/next_action), empty-stream, artifact-without-path fallback;
      `_format_summary` green clean / red errors / artifact + warning counts;
      handler integration through `dispatch()` — streams events + summary,
      forwards args incl. `--run-id`, reports `EvalCommandError` as skip-display,
      reports `FileNotFoundError` with no raw_result, surfaces mixed warnings/
      errors, default runner wiring, meta-message artifact truncation to last 3,
      registry wiring. Plus a new `test_builtin_registry_without_streaming` and an
      updated extras test in `tests/test_workbench_slash.py` (using `/optimize`
      since `/eval` now occupies the default extras slot). Full workbench surface
      green (197 tests).*
- [ ] **T10** — Add `/optimize [--cycles N] [--mode …]` slash command bound to the
      `optimize` CLI. Stream progress per cycle.
- [ ] **T11** — Add `/build [target]` slash command bound to
      `workbench build`/`workbench save` so users can iterate candidates inline.
- [ ] **T12** — Add `/deploy [--strategy canary|immediate]` slash command bound to
      `deploy`. Require explicit confirm ("y/N") before execution.
- [ ] **T13** — Implement `/skills` as a `local-jsx`-style screen (`SkillsScreen` from
      T08b) modeled on the mirror's `SkillsMenu`. Arrow-key navigable list with
      `list / show / add / edit / remove` actions; `$EDITOR` opens for add/edit; delegates
      to `cli/skills.py` under the hood. NOT a flat CLI — it's a full-screen modal.
- [ ] **T14** — Add `/model` slash command that lists configured models and switches the
      active one for the session (persist to session state).
- [ ] **T15** — Add `/clear` (wipe transcript, keep session) and `/new` (start fresh
      session) slash commands.
- [ ] **T16** — Implement ctrl-c / esc handling: first press cancels the current
      streaming tool call, second press aborts the app. Ensure no orphan subprocesses.
- [ ] **T17** — Wire session persistence: every transcript entry and slash command
      appends to the existing `SessionStore`. On startup, offer `/resume` hint if latest
      session is recent.
- [ ] **T18** — Add theming: dim meta lines, cyan for workspace, green for completed,
      yellow for warnings, red for errors. Read palette from
      `cli/workbench_app/theme.py`.
- [ ] **T18b** — Add an effort indicator + ctrl-O expand/collapse for long outputs
      (port the mirror's `EffortIndicator` and `CtrlOToExpand`). Long tool-call output
      collapses to a summary line with token count; ctrl-O toggles full view. Effort
      indicator shows a spinner + elapsed time + cost for any running tool call > 2s.
- [ ] **T19** — Add slash-command autocomplete popup (show matching commands as user
      types `/`). Use the chosen rendering stack's completer.
- [ ] **T20** — Make workbench the default: `agentlab` with no args launches
      `workbench_app`. Add `--classic` flag to opt out. Update `runner.py` entry logic.
- [ ] **T21** — Unit tests: `tests/cli/test_workbench_slash.py` covering dispatch,
      unknown-command handling, and autocomplete matching.
- [ ] **T22** — Unit tests: `tests/cli/test_tool_call_block.py` for the new block
      renderer across started/progress/completed/error sequences.
- [ ] **T23** — Integration test: `tests/cli/test_workbench_app_eval.py` drives
      `/eval` end-to-end using a mocked subprocess that emits stream-json events and
      asserts transcript output.
- [ ] **T24** — Integration test: `tests/cli/test_workbench_default_entry.py` verifies
      `agentlab` boots workbench_app, `--classic` falls back to REPL, `/exit` returns 0.
- [ ] **T25** — Migration: update `cli/repl.py` to thin-shim over `workbench_app` or
      mark deprecated with a pointer. Keep backward compatibility for one release.
- [ ] **T26** — Update docs: `README.md`, `AGENTLAB.md`, and
      `docs/cli/workbench.md` with new default mode, slash-command catalog, and
      screenshots/asciicasts.
- [ ] **T27** — Run `pytest` full suite + `ruff check` + `mypy` (if configured). Fix
      any regressions introduced by the refactor. Do not commit until all green.
