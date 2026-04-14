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
- [x] **T10** — Add `/optimize [--cycles N] [--mode …]` slash command bound to the
      `optimize` CLI. Stream progress per cycle. *Landed
      `cli/workbench_app/optimize_slash.py` mirroring the T09 `/eval` design:
      frozen `OptimizeSummary` adds a `cycles_completed` counter on top of
      the shared phase/artifact/warning/error counters, populated by
      counting `phase_completed` events with `phase == "optimize-cycle"`
      (the label `runner.optimize` already emits at ~line 4426 for each
      finished cycle). The injectable `StreamRunner` default shells out to
      `python -m runner optimize --output-format stream-json` and line-
      buffers stdout/stderr through `format_workbench_event` — no new
      renderers are needed because optimize's stream-json vocabulary
      (`phase_started`, `phase_completed`, `artifact_written`,
      `next_action`, `warning`, `error`) already landed via T09.
      `_parse_args` is a verbatim pass-through because `--cycles`,
      `--mode`, `--continuous`, `--config`, `--full-auto`, `--eval-run-id`
      are already native flags. The handler echoes a cyan start banner,
      streams events, and ends with an `on_done(...)` summary: green
      `"/optimize complete — N events, M cycles"` on clean runs (singular
      `"1 cycle"` aware), red `"/optimize failed"` if any `error` event
      arrived or the subprocess exited non-zero, with the final
      `next_action` surfaced as `"Suggested next: …"` and the last three
      artifact paths as additional meta lines. `OptimizeCommandError`
      (non-zero exit) and `FileNotFoundError` (missing binary) both render
      a red failure line and return `display="skip"` so dispatch doesn't
      double-print; unparseable subprocess output is rescued as a
      synthetic `warning` event. `build_builtin_registry()` now registers
      `/optimize` alongside `/eval` under the `include_streaming=True`
      toggle so tests that want just the ten ported built-ins can still
      opt out. Updated `tests/test_workbench_slash.py`: expected set gains
      `"optimize"`, the extras-registry test switched its fixture name
      from `optimize` to `custom` (since the built-in now claims the
      slot), and the streaming-disabled guard asserts `"optimize" not in
      registry.names()` too. Coverage:
      `tests/test_workbench_optimize_slash.py` (26 tests) — arg parsing
      pass-through for `--cycles`/`--mode`/`--continuous`/empty/mixed,
      `_render_event` for `phase_started` / cycle `phase_completed` /
      missing-name / unknown-event, `_summarise` counting cycles vs non-
      cycle phases, artifact-without-path fallback, empty-stream, ignore
      non-cycle `phase_completed` for `cycles_completed`;
      `_format_summary` green clean / singular "1 cycle" / red errors /
      warnings + artifacts; handler integration through `dispatch()` —
      streams events + summary, forwards `--cycles`/`--mode` verbatim,
      reports `OptimizeCommandError` as skip-display, reports
      `FileNotFoundError` with no raw_result, surfaces mixed warnings/
      errors, default runner wiring, meta-message artifact truncation to
      last 3, registry wiring, summary-dataclass frozen guard. Full
      workbench surface green (307 tests).*
- [x] **T11** — Add `/build [target]` slash command bound to
      `workbench build`/`workbench save` so users can iterate candidates inline.
      *Landed `cli/workbench_app/build_slash.py` mirroring the T09/T10
      streaming pattern, plus a companion `/save` local-command in
      `cli/workbench_app/slash.py`. Two nuances distinguish `/build` from
      its siblings: (a) it requires a positional `<brief>` argument —
      missing input is rejected with a red transcript line and
      `display="skip"` so no subprocess is spawned; (b) workbench
      stream-json events use the nested `{event, data}` envelope (see
      `builder/workbench_agent.py`) rather than the flat progress-event
      shape, so `_event_payload(event)` unwraps `event["data"]` (with a
      graceful fall-back to the flat envelope for malformed events)
      before handing the payload to `format_workbench_event`. Frozen
      `BuildSummary` tracks events, `task.completed` count,
      `iteration.started` count, artifact paths from `artifact.updated`
      (both nested `artifact.path` and flat `path`), warnings
      (`progress.stall` + explicit `warning`), errors (explicit `error`
      + `run.failed`), `run_status`
      (`completed`/`failed`/`cancelled`), `run_version` captured from
      `run.completed.version`, and `failure_reason` from
      `run.failed.failure_reason` / `run.cancelled.cancel_reason`.
      `_format_summary` renders `"/build complete (v004)"` green on
      clean runs, `"/build failed"` red when any error was recorded or
      `run_status == "failed"`, and `"/build cancelled"` red for
      ctrl-c paths; singular vs plural `task`/`iteration` labels are
      honoured. Meta messages surface `Reason: <failure_reason>`,
      `Next: /save to materialize project <id>` on successful
      completion, and the last three artifact paths.
      `BuildCommandError` (non-zero exit) and `FileNotFoundError`
      (missing binary) both render red failure lines and return
      `display="skip"` so dispatch doesn't double-print; unparseable
      subprocess output is rescued as a synthetic nested-envelope
      `warning` event. `/save` is a thin local delegator that forwards
      args verbatim to `agentlab workbench save` via the existing
      `_run_click` invoker — sufficient today because `workbench save`
      is a one-shot command without stream-json support.
      `build_builtin_registry()` now wires `/save` under
      `_BUILTIN_SPECS` (ported tier) and `/build` under
      `include_streaming=True`, giving 14 default commands (15 with
      extras). Updated the registry-contains test to expect
      `{save, build}` in the name set, bumped the extras-length
      assertion to 15, and added the `include_streaming=False` guard
      that `"build" not in registry.names()` while `"save"` remains.
      Coverage: `tests/test_workbench_build_slash.py` (25 tests) —
      `_parse_args` pass-through, `_event_payload` nested/flat/
      non-dict branches, `_render_event` nested-data rendering and
      none-returns, `_summarise` counters across tasks/iterations/
      artifacts/nested-artifact objects/`run.completed`/`run.failed`/
      `run.cancelled`/explicit errors+warnings/newest-project-id-wins,
      `_format_summary` green-with-version / singular task+iteration
      labels / red on errors / red on `run.failed` without explicit
      error count / cancelled label / artifact+warning listing,
      handler integration via `dispatch()` — requires-brief guard
      (no subprocess call), streams + summary + meta-with-project-id,
      forwards flags verbatim after the brief, `BuildCommandError` →
      skip with raw result, `FileNotFoundError` → skip with
      `raw_result is None`, `run.failed.failure_reason` surfaced as
      `Reason:` meta line without a `Next: /save` suggestion, artifact
      meta capped to last three, default-runner wiring check,
      `build_builtin_registry` wiring, frozen-dataclass guard. Plus
      two `/save` delegation tests in `tests/test_workbench_slash.py`
      (zero-args runs `"workbench save"`, flags forwarded). Full
      workbench surface green (269 tests across build_slash/
      optimize_slash/eval_slash/slash/transcript/status_bar/screens/
      tool_call_block/commands/app_stub).*
- [x] **T12** — Add `/deploy [--strategy canary|immediate]` slash command bound to
      `deploy`. Require explicit confirm ("y/N") before execution. *Landed
      `cli/workbench_app/deploy_slash.py` mirroring the T10 `/optimize`
      streaming pattern, with two new seams: a `Prompter` callable
      (defaults to `click.confirm`) and a handler-level confirmation gate
      that runs **before** the subprocess spawns. Rule: prompt `"Deploy
      with strategy=<s>? (y/N)"` unless the user passed `-y`/`--yes` or
      `--dry-run` (dry-run is read-only; `-y` is an explicit opt-out).
      `_infer_strategy(args)` mirrors `runner.deploy`'s positional-vs-flag
      resolution — positional `canary`/`immediate` wins over `--strategy`,
      and the legacy `release` workflow maps to `immediate` — so the
      confirmation banner reflects what's actually about to happen. On
      confirmation the handler appends `-y` to the stream args so
      `runner.deploy`'s own `PermissionManager.require` doesn't re-prompt;
      cancelled prompts echo yellow `"/deploy cancelled — no changes
      made."` and return `display="skip"` without launching the runner.
      `KeyboardInterrupt`/`EOFError` from the prompter are swallowed as
      cancels so ctrl-c at the y/N gate doesn't crash the loop.
      Subprocess command line: `python -m runner deploy <args>
      --output-format stream-json` via `subprocess.Popen(bufsize=1,
      text=True, stderr→stdout)`, unparseable stdout is rescued as a
      synthetic `warning` event. Frozen `DeploySummary` tracks
      events/phases/artifacts/warnings/errors/next_action + the
      resolved `strategy`, and `_format_summary` renders green
      `"/deploy complete — N events, strategy=<s>, M phase"` (singular
      vs plural phase label honoured) or red `"/deploy failed"` when
      any `error` event arrived. Meta messages surface the final
      `next_action` as `"Suggested next: …"` and the last three
      artifact paths. `DeployCommandError` (non-zero exit) and
      `FileNotFoundError` (missing binary) both render red failure
      lines and return `display="skip"` so dispatch doesn't
      double-print. `build_builtin_registry()` now wires `/deploy`
      under `include_streaming=True` (15 built-ins + 1 extras slot =
      16). Updated `tests/test_workbench_slash.py` registry
      assertions accordingly. Coverage:
      `tests/test_workbench_deploy_slash.py` (31 tests) —
      `_parse_args` pass-through; `_infer_strategy` default + flag w/
      space + `--strategy=X` + positional `canary`/`immediate`/`release`
      + positional-overrides-default; `_is_preconfirmed` for `-y`/
      `--yes`/absent; `_is_dry_run`; `_render_event` happy path +
      orphan; `_summarise` counters + strategy threading + empty
      stream + artifact-without-path fallback; `_format_summary`
      green clean / singular phase / red on errors / warnings +
      artifacts listing; handler integration via `dispatch()` — prompt
      + `-y` append on confirm, cancel-on-`False` path (no subprocess
      call, skip display), `KeyboardInterrupt` → cancel, `-y` on args
      skips prompt + no double append, `--dry-run` skips prompt + no
      `-y` appended, `DeployCommandError` → skip with raw result,
      `FileNotFoundError` → skip with `raw_result is None`, errors
      surfaced in summary, artifact meta capped at last three,
      default-seams wiring, registry wiring, frozen-dataclass guard.
      Full workbench surface green (406 tests across deploy_slash/
      build_slash/optimize_slash/eval_slash/slash/transcript/
      status_bar/screens/tool_call_block/commands/app_stub/cli_workbench).*
- [x] **T13** — Implement `/skills` as a `local-jsx`-style screen (`SkillsScreen` from
      T08b) modeled on the mirror's `SkillsMenu`. Arrow-key navigable list with
      `list / show / add / edit / remove` actions; `$EDITOR` opens for add/edit; delegates
      to `cli/skills.py` under the hood. NOT a flat CLI — it's a full-screen modal.
      *Landed `cli/workbench_app/skills_slash.py` with three seams so the flow
      is testable without a TTY or real sqlite: a `SkillsBackend` Protocol
      (`list_skills` / `show` / `add` / `edit` / `remove` → `BackendResult`),
      a `CliSkillsBackend` default that delegates to `core.skills.store`
      via the existing `cli.skills._get_store` helper, and a
      `SkillsScreenAdapter(Screen)` that runs the T08b `SkillsScreen` once,
      inspects the returned `ScreenResult.action` (`list` / `show` / `add`
      / `edit` / `remove` / `exit` / `cancel`), dispatches the matching
      backend method, echoes its `lines` verbatim to the transcript, and
      returns a `ScreenResult(action="exit", meta_messages=(summary,))` so
      the outer dispatch layer surfaces the summary as a dim meta line.
      Single-shot semantics mirror Claude Code's `SkillsMenu` exit-on-action
      UX; users re-invoke `/skills` for a follow-up action, which keeps the
      inner screen re-paint logic trivial and leaves no nested loops to
      manage. `$EDITOR`/`$VISUAL` launching is isolated behind an injectable
      `EditorRunner = Callable[[Path], int]` seam (default shells out to
      `subprocess.call([editor, path])` with `EDITOR → VISUAL → vi`
      fallback) and confirmation before `remove` lives behind `Confirmer =
      Callable[[str], bool]` (default `click.confirm(..., default=False)`
      with `click.Abort` / `KeyboardInterrupt` / `EOFError` all coerced to
      `False`). `add` writes a starter YAML template to a temp file, opens
      `$EDITOR`, parses via `core.skills.loader.SkillLoader`, and
      `store.create`s each parsed skill. `edit` dumps the selected skill
      to a temp YAML, opens `$EDITOR`, re-parses via
      `core.skills.types.Skill.from_dict`, and calls `store.update`; parse
      errors render a red meta line without mutating the store. `remove`
      confirms, deletes via `store.delete`, and surfaces the result.
      Every temp file is unlinked in a `finally` clause via
      `_unlink_quiet(path)` so crashes don't leak scratch YAML into `/tmp`.
      To make dispatch handle `local-jsx` properly, extended
      `cli.workbench_app.slash.dispatch` with a new `_dispatch_local_jsx`
      branch: constructs the screen via `command.screen_factory(ctx, *args)`,
      runs `screen.run()`, echoes `ScreenResult.meta_messages` as dim lines
      (mirroring `_render_and_echo`'s `meta_messages` routing), and folds
      the result into `DispatchResult(display="system", meta_messages=...,
      raw_result=value if str else None)`. Factory exceptions render a red
      `"Error running /skills: <exc>"` line and return `error=<str(exc)>`
      so the loop stays alive. `PromptCommand` still returns
      `error="unsupported-kind"` (landing in T14+). `build_skills_command(*,
      backend=None)` returns a `LocalJSXCommand(source="builtin",
      screen_factory=...)`; the factory accepts `(ctx, *args)` and threads
      `ctx.echo` into the adapter so the transcript owns every line. Wired
      into `build_builtin_registry(include_streaming=True)` alongside the
      other T09–T12 streaming commands (16 built-ins + 1 extras slot = 17
      total). Coverage: `tests/test_workbench_skills_slash.py` (23 tests) —
      adapter exit key / list count (plural + singular) / show with cursor
      navigation / show-needs-selection on empty list / add without
      selection / edit / remove / empty-summary omits meta / EOF exits
      cleanly; `build_skills_command` type + kind + source; full dispatch
      integration with patched key provider + echo assertion;
      `CliSkillsBackend` via a `monkeypatch`-installed fake `SkillStore`
      (`_get_store` patched at `cli.skills._get_store`) — list→items
      projection, store-close accounting, `show` missing-skill + yaml
      body, `remove` cancels on `confirmer=False` without calling delete,
      `remove` deletes on confirm, `remove` of missing skill reports
      error, `edit` aborts on editor non-zero exit with no store mutation,
      `edit` saves after successful editor and cleans up the temp file,
      `edit` missing skill, `add` aborts on editor non-zero, `add` creates
      from editor buffer via a stub `SkillLoader`. Plus two updates to
      `tests/test_workbench_slash.py`: the registry contains set gains
      `"skills"`, the extras-registry count bumps to 17, the
      `include_streaming=False` guard adds `"skills" not in
      registry.names()`, and the old
      `test_dispatch_localjsx_command_reports_unsupported_kind` is
      replaced with `test_dispatch_localjsx_command_runs_screen` /
      `test_dispatch_localjsx_command_handles_factory_errors` covering
      the new happy path + factory-error path (factory args thread-through,
      meta_messages dim-echoed, raw_result from str value). Full
      workbench surface green (329 tests across skills_slash/slash/
      transcript/status/screens/app_stub/commands/tool_call_block/
      eval_slash/optimize_slash/build_slash/deploy_slash).*
- [x] **T14** — Add `/model` slash command that lists configured models and switches the
      active one for the session (persist to session state). *Landed
      `cli/workbench_app/model_slash.py` as an inline `LocalCommand`
      (not streaming) with three modes: (a) `/model` lists every entry
      from `cli.model.list_available_models(workspace.root)`, marking
      the session-active one with `●` (green) and annotating credential
      status via `_credential_note` (`key set` / `missing ENV_VAR` /
      `no credentials`); (b) `/model <key>` resolves `<key>` against
      full `provider:model` keys first, falling back to unique bare
      model names (ambiguous short names intentionally fail with
      "Unknown model: …" to avoid silent miss-selection); (c)
      `/model reset|clear|none|default|unset` drops the override. The
      session-local override is stored in
      `session.settings_overrides["model"]` and persisted via
      `session_store.save(session)` so `/resume` carries it forward —
      the status bar already accepts a `model_override` parameter on
      `snapshot_from_workspace` (T06) that downstream refresh code
      reads from `session.settings_overrides.get("model")`. An
      injectable `ModelLister` seam (default shells out to
      `cli.model.list_available_models`) keeps tests hermetic — they
      never need a real `agentlab.yaml` on disk. `build_model_command
      (*, lister=None)` is the factory; it's registered in
      `build_builtin_registry` outside `_BUILTIN_SPECS` so it lands in
      both the streaming-on (default) and streaming-off configurations
      — `/model` is inline, not subprocess-based. Error-path matrix:
      lister raises → red "Could not load models: <exc>"; empty
      model list → plain "No models configured"; unknown key → red
      "Unknown model: <raw>…" + no session mutation; no session bound
      → yellow "No active session — cannot persist model override.";
      no store bound → in-memory mutation succeeds + meta line
      "Not persisted — no session store bound."; `store.save` raises
      → yellow warning naming the exception with a "applies for this
      run only" meta (in-memory mutation kept so subsequent dispatches
      see it); reset with nothing to clear → "No session model
      override to clear.". Defensive coercion in `_set_override`
      replaces a non-dict `settings_overrides` with a fresh dict so
      freshly-constructed Session objects (missing field) behave
      sensibly. Updated `build_builtin_registry` to import
      `build_model_command` lazily (mirrors the streaming factories)
      and register it unconditionally. Coverage:
      `tests/test_workbench_model_slash.py` (33 tests) — helpers:
      `_resolve_root` with/without workspace, with missing `.root`,
      `_session_override` tolerates non-dict + missing session,
      `_match_model` exact-key/case-insensitive/unique-short/
      ambiguous-short/empty-string, `_credential_note` env-set/
      env-missing/no-env, `_format_list` marker placement; surface:
      `build_model_command` returns `LocalCommand(kind="local",
      source="builtin", name="model", description=…)`; listing:
      happy-path rendering, meta "No session override" when none,
      meta "Session override: <key>" when set, `●` marker only on
      active row, empty model list, lister-exception surfaced;
      setting: full-key persists + reload-from-disk survives, short
      name resolves, unknown key leaves session + disk clean, no
      session → warning, no store → in-memory + "Not persisted" meta,
      `store.save` raises → yellow warning with exception text,
      meta mentions `/model reset`; resetting: clears + persists with
      previous value echoed, `clear` alias works, reset-when-none
      is idempotent, reset-without-session is a noop, best-effort
      persistence tolerates `store.save` failure; wiring: default
      registry + `include_streaming=False` registry both contain
      `/model`. Plus three edits to `tests/test_workbench_slash.py`:
      `expected` set for `test_builtin_registry_contains_all_ten_commands`
      adds `"model"`, `test_builtin_registry_without_streaming` gains
      `assert "model" in registry.names()`, extras-count bumps from 17
      to 18. Full workbench surface green (631 tests across
      model_slash/slash/status/screens/transcript/tool_call_block/
      skills_slash/build_slash/optimize_slash/eval_slash/deploy_slash/
      commands/app_stub/cli_workbench and every sibling suite).*
- [x] **T15** — Add `/clear` (wipe transcript, keep session) and `/new` (start fresh
      session) slash commands. *Landed two inline `LocalCommand` handlers in
      `cli/workbench_app/slash.py` plus a new `transcript: Transcript | None`
      field on `SlashContext` (guarded with `TYPE_CHECKING` to avoid a runtime
      import cycle). `/clear` — if the context carries a `Transcript`, calls
      `transcript.clear()`, returns `on_done("  Transcript cleared.",
      display="system", meta_messages=(f"Removed N entr{'y'|'ies'};
      session kept.",))`; with no transcript bound, returns a dim
      "No transcript bound — nothing to clear." line and does nothing. The
      on-disk `Session` pointer and its persisted `.agentlab/sessions/*.json`
      are deliberately untouched, so `/clear` is non-destructive and mirrors
      Claude Code's context-reset semantics. `/new` — requires a
      `SessionStore`; calls `store.create(title=args joined)` and swaps the
      new session onto `ctx.session` (previous file is left on disk, not
      deleted). When `ctx.transcript` is bound, it is cleared too so the
      visible pane matches the fresh session. Meta messages surface the
      previous session id (only when it existed and differs), the new
      session id, and — when a title was supplied — "Title: <title>". The
      auto-generated title from `SessionStore.create(title="")` is omitted
      from the meta list because empty-string titles collapse to a
      timestamp banner that adds no signal. Store failures
      (`RuntimeError`, etc.) are caught and returned as a dim system line so
      the loop stays alive. Both commands registered in `_BUILTIN_SPECS`
      (inline; no streaming dependency), so `build_builtin_registry
      (include_streaming=False)` still exposes them. Updated the
      registry-size assertions: the default built-in registry now carries 19
      commands (11 originally ported + /clear + /new + /model + /eval +
      /optimize + /build + /deploy + /skills); the +extras test lands at 20.
      Coverage: 10 new tests in `tests/test_workbench_slash.py`
      (`test_clear_handler_without_transcript_is_a_noop`,
      `test_clear_handler_wipes_transcript_entries`,
      `test_clear_handler_uses_singular_noun_for_one_entry`,
      `test_clear_handler_keeps_session_intact` — verifies the persisted
      session file is untouched and only the in-memory transcript is wiped,
      `test_new_handler_without_store_reports_and_keeps_session`,
      `test_new_handler_creates_session_and_swaps_on_context`,
      `test_new_handler_accepts_title_from_positional_args`,
      `test_new_handler_clears_transcript_when_bound`,
      `test_new_handler_surfaces_store_failure_as_system_line` — uses a
      stub `_BrokenStore.create` that raises, and
      `test_new_handler_omits_previous_meta_when_no_session_bound`). Full
      workbench surface green (376 tests across slash / transcript /
      status / screens / commands / eval_slash / optimize_slash /
      build_slash / deploy_slash / skills_slash / model_slash /
      tool_call_block / app_stub).*
- [x] **T16** — Implement ctrl-c / esc handling: first press cancels the current
      streaming tool call, second press aborts the app. Ensure no orphan subprocesses.
      *Landed `cli/workbench_app/cancellation.py` with a thread-safe
      `CancellationToken` that tracks a monotonic `cancelled` flag plus a
      registry of live :class:`subprocess.Popen` children. `cancel()` is
      idempotent, sends SIGTERM, and escalates to SIGKILL after a
      configurable grace window (`terminate_grace=0.5s` default) so a
      hung or signal-swallowing child never leaks as an orphan; a race
      window check (processes registered *after* a cancel) immediately
      terminates the late arriver. `ProcessLookupError` and `OSError`
      are swallowed at the termination site to stay resilient under
      races. `register_process` / `unregister_process` / `reset` round
      out the API; `iter_with_cancellation(stream, token)` is a small
      helper for draining iterators that don't know about the token.
      Threaded the token through `SlashContext.cancellation` (new
      optional field, defaults to `None`) and into each of the four
      streaming runners (`/eval`, `/optimize`, `/build`, `/deploy`) via
      a new keyword-only `cancellation` parameter on
      `_default_stream_runner`. Each runner now registers the
      subprocess on start, polls `token.cancelled` between line reads,
      and always unregisters in the `finally` clause so a late cancel
      can't race with a natural exit. The non-zero exit check is
      suppressed when a cancellation is in flight so the handler
      doesn't double-report the subprocess error. An `_invoke_runner`
      helper in each `*_slash.py` probes the runner signature so the
      existing test fixtures (single-arg `runner(args)`) still work
      unchanged — only callers who opt in to a cancellation token pay
      the kwarg. Handler side: each of the four streaming handlers
      now wraps the event loop in `try/except KeyboardInterrupt`,
      flips `token.cancel()` (which kills the subprocess), and falls
      through to a shared cancelled-path that emits a yellow
      `"/{cmd} cancelled — …"` line and returns
      `on_done(display="skip")` so the dispatch layer doesn't
      double-print. The same path also catches the case where a
      `*CommandError` surfaces *because* the cancellation flipped the
      subprocess exit code — the error is then treated as a
      consequence of the cancel rather than a real failure.
      App-loop side: `run_workbench_app()` gained an optional
      `cancellation` parameter (default: a fresh token), tracks a
      consecutive-interrupts streak, and routes ctrl-c based on
      `token.active`: (a) if a tool call is registered the first press
      calls `token.cancel()` and echoes "cancelled active tool call
      — press ctrl-c again to exit" (yellow), leaving the loop intact;
      (b) at idle the first press echoes "press ctrl-c again to exit,
      or /exit" (yellow) and continues; (c) a second consecutive press
      without intervening input exits with `exited_via="interrupt"`.
      Successful input resets both the streak and the token so a
      stray ctrl-c never forces the user out. `StubAppResult` gained
      an `interrupts` field so tests can inspect the exit streak.
      Coverage: 28 tests in `tests/test_workbench_cancellation.py` —
      token defaults (uncancelled + inactive), idempotent `cancel()`,
      `reset()` clearing flag + registry, `register_process` active-
      state tracking, graceful SIGTERM-only path, SIGKILL escalation
      when terminate is ignored (`exits_on_terminate=False` fake +
      `terminate_grace=0.01`), late-arriver termination after cancel,
      best-effort `unregister_process` (double-call tolerated),
      `ProcessLookupError` swallowed at terminate site,
      `iter_with_cancellation` breaking on flag flip, real subprocess
      cleanup (spawns a 10s `time.sleep` Python child, registers,
      cancels, asserts `poll() is not None` within 1s + last-resort
      cleanup); handler integration — parameterised across all four
      streaming commands for both mid-stream token flip and direct
      `KeyboardInterrupt`, legacy handler w/o token still emits
      yellow cancelled line, runner that accepts `cancellation` kwarg
      receives the token, runner with legacy positional-only signature
      is still invoked via the probe helper; app-loop — first
      interrupt at idle warns without exiting, double-interrupt with
      no input exits cleanly, stray interrupt between valid inputs is
      forgiven (resets streak), interrupt with an active tool call
      fires `token.cancel()` (verified via fake `Popen.terminate` call
      count) and does not count toward the exit threshold; context
      wiring — `SlashContext(cancellation=token)` accepted, defaults
      to `None`. Full workbench surface green (450 tests); full test
      suite green (4483 tests).*
- [x] **T17** — Wire session persistence: every transcript entry and slash command
      appends to the existing `SessionStore`. On startup, offer `/resume` hint if latest
      session is recent. *Landed three wiring points plus a pure hint helper.
      (1) :class:`Transcript` gained an opt-in :meth:`bind_session(session,
      store)` seam so the loop can attach a :class:`SessionStore` without
      breaking the existing in-memory-only callers (tests that construct a
      bare ``Transcript(echo=…)`` still behave as before). When bound,
      every ``append_*``/``replace_tail`` writes a :class:`SessionEntry`
      to disk via :meth:`SessionStore.append_entry`; failures are swallowed
      (best-effort, a flaky fs must not take down the live transcript).
      :meth:`Transcript.clear` intentionally stays in-memory-only — the
      on-disk transcript survives so ``/resume`` can still reach it and
      ``/clear`` mirrors Claude Code's context-reset semantics.
      :meth:`Transcript.copy_with` now carries the binding onto clones
      so screens (T08b) inherit persistence. (2) :func:`dispatch` now
      appends every matched slash line to ``session.command_history``
      via :func:`_record_command`, guarded to noop when either
      ``ctx.session`` or ``ctx.session_store`` is unbound and wrapped in
      a swallow-all ``try`` for best-effort semantics. Non-slash lines
      (``handled is False``) are never recorded, so command history
      stays tight to the slash surface. (3) :func:`_handle_resume` now
      actually restores — swaps ``ctx.session`` to the loaded session,
      clears the bound transcript, calls the new
      :meth:`Transcript.restore_from_session(session)` helper to
      rehydrate in-memory entries, and rebinds the transcript to the
      resumed session so future appends flow to it. An optional
      positional ``<session_id>`` argument loads that specific session
      instead of the latest; unknown ids render a dim "No session with
      id …" line. ``restore_from_session`` normalizes unknown role tags
      to ``"system"`` via ``_normalize_role`` so legacy / corrupted
      session files resume cleanly. Meta lines surface
      "Session: <title> (<id>)", "Goal: …", and "Entries restored: N".
      (4) Startup hint: new pure helper :func:`resume_hint(store, *,
      current, max_age_seconds, now)` returns a one-line
      "  Tip: /resume to continue \"<title>\" (Nh ago)" when a prior
      session exists on disk, isn't the current one, and was updated
      within :data:`RESUME_HINT_MAX_AGE_SECONDS` (24h). Relative-time
      formatting (`just now` / `Nm ago` / `Nh ago` / `Nd ago`) lives in
      :func:`_format_age` as a pure helper so tests don't need a clock
      mock beyond ``now=``. :func:`run_workbench_app` gained optional
      ``session_store=`` / ``session=`` parameters; when both the
      banner and a hint-eligible session are present the hint is
      echoed dim-styled right under the banner (suppressed when
      ``show_banner=False``). Defensive: helper swallows
      ``store.latest()`` exceptions and handles ``updated_at=0``.
      Coverage: 11 new T17 tests in
      ``tests/test_workbench_slash.py`` — dispatch persists slash
      history (``/help``, ``/status extra arg``), unbound
      store/session no-ops without crash, non-slash free text doesn't
      touch history, bad-store raising during ``append_command``
      swallowed, ``/resume`` swaps session + restores 3 transcript
      entries + rebinds transcript to new session, ``/resume
      <session_id>`` loads explicit session beating the latest rule,
      unknown id reports dim system line, ``Transcript.bind_session``
      persists appends to disk, detach stops persistence, ``clear()``
      keeps disk entries, ``restore_from_session`` normalizes
      "weird-role" → "system"; 8 new hint tests in
      ``tests/test_workbench_app_stub.py`` — ``resume_hint(None)`` is
      ``None``, empty store returns ``None``, recent session surfaces
      title + "2h ago" + "/resume", ages over 24h skipped, current ==
      latest skipped, 150s formats "2m ago", ``run_workbench_app``
      banner includes the hint, ``show_banner=False`` suppresses the
      hint. Three legacy ``/resume`` tests updated to consume the new
      ``display="system"`` dim-wrapped output and the new
      ``meta_messages`` + session-pointer swap contract. Full
      workbench surface green (437 tests across slash / transcript /
      status_bar / screens / app_stub / commands / cli_workbench /
      tool_call_block / eval_slash / optimize_slash / build_slash /
      deploy_slash / skills_slash / model_slash / cancellation /
      sessions); ``repl.py`` / ``shell_commands`` compatibility suite
      still green (27 tests).*
- [x] **T18** — Add theming: dim meta lines, cyan for workspace, green for completed,
      yellow for warnings, red for errors. Read palette from
      `cli/workbench_app/theme.py`. *Landed `cli/workbench_app/theme.py` with a
      frozen :class:`Palette` dataclass pinning the role → Click colour
      mapping (workspace=cyan, user=cyan, success=green, warning=yellow,
      error=red, assistant=None, command_name=cyan) plus named helpers
      (:func:`meta`, :func:`workspace`, :func:`user`, :func:`assistant`,
      :func:`success`, :func:`warning`, :func:`error`,
      :func:`command_name`, :func:`heading`) and a shared
      :func:`stylize` core that collapses ``bold=False`` / ``dim=False``
      to ``None`` so the rendered ANSI stays tight (no spurious
      off-codes). Every helper honours ``color=False`` for ANSI-free
      output, matching the existing ``render_snapshot(color=False)``
      contract in :mod:`cli.workbench_app.status_bar`. Palette is
      immutable so no caller can repaint at runtime — future themes
      swap by rebinding :data:`PALETTE`. Refactored every high-value
      call site in :mod:`cli.workbench_app` to route through the new
      helpers: (a) ``transcript.format_entry`` now dispatches
      user/system/meta/error/warning/assistant entries through the
      matching theme function; (b) ``app._render_banner`` and the
      ctrl-c / idle-tip / goodbye paths in :func:`run_workbench_app`
      swap cyan-bold banner + yellow warnings + dim goodbye onto
      theme helpers; (c) ``status_bar.render_snapshot`` uses
      :func:`theme.workspace` / :func:`theme.warning` /
      :func:`theme.meta` (dropped the defunct ``import click``); (d)
      slash `/help` heading, `meta_messages` echoing, and the system-
      display branch of `_render_and_echo` now call
      :func:`theme.heading` and :func:`theme.meta`; (e) every
      streaming handler (`/eval`, `/optimize`, `/build`, `/deploy`)
      routes the cyan starting banner, red error summary token,
      red failure lines (`KeyboardInterrupt`, `*CommandError`,
      `FileNotFoundError`), green / red bold summary line, and yellow
      cancelled line through the palette; `/build` also routes its
      "requires a brief" guard message through :func:`theme.error`;
      (f) every screen (`base.header_lines`, `skills`, `resume`,
      `doctor`) uses :func:`theme.workspace` / :func:`theme.meta` /
      :func:`theme.error`. Dropped `click` imports from
      `eval_slash.py`, `optimize_slash.py`, `build_slash.py`, and
      `status_bar.py` since they no longer called `click.style`;
      left `click` imports in `deploy_slash.py` (for
      :func:`click.confirm`), `slash.py` (for :func:`click.echo`
      default + :class:`click.testing.CliRunner`), `transcript.py`
      (for :func:`click.unstyle`), `app.py` (for :func:`click.echo`
      default), and the screens (marked with ``# noqa: F401``
      where the module itself no longer calls into click but tests
      or downstream callers may). Coverage:
      `tests/test_workbench_theme.py` (22 tests) — palette is frozen
      (mutation raises), default role colours pin the advertised
      mapping, every helper: applies the right ANSI code (cyan /
      green / yellow / red / dim / bold), round-trips through
      ``click.unstyle``, and returns plain text under ``color=False``;
      :func:`theme.stylize` returns text verbatim when no flags and
      short-circuits on ``color=False`` even with flags set. No
      existing test suite asserted byte-for-byte ANSI output for the
      refactored lines — they compare plain text via
      :func:`click.unstyle` / ``_strip_ansi`` — so no downstream
      tests needed to change. Full workbench surface green (445
      tests across theme / transcript / status_bar / screens /
      slash / eval_slash / optimize_slash / build_slash /
      deploy_slash / skills_slash / model_slash / tool_call_block /
      commands / app_stub / cancellation); broader workbench / cli
      subset (601 tests) all green.*
- [x] **T18b** — Add an effort indicator + ctrl-O expand/collapse for long outputs
      (port the mirror's `EffortIndicator` and `CtrlOToExpand`). Long tool-call output
      collapses to a summary line with token count; ctrl-O toggles full view. Effort
      indicator shows a spinner + elapsed time + cost for any running tool call > 2s.
      *Landed two pure state-machine primitives (the prompt_toolkit
      key-binding layer lives in T19; these modules own the logic the
      binding will drive). (1) `cli/workbench_app/effort.py` ships a
      frozen :class:`EffortSnapshot` (``spinner_frame``, ``elapsed_seconds``,
      optional ``token_count``/``cost_usd``, ``finished``) plus an
      :class:`EffortIndicator` state machine with injectable
      ``clock: Callable[[], float]`` (defaults to :func:`time.monotonic`),
      ``threshold_seconds`` (default ``2.0``) and ``frames`` (default
      10-frame braille spinner ``⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`` — same family Claude Code
      uses). ``start()`` is idempotent; ``tick()`` returns ``None`` while
      under threshold *or* after ``stop()``, so a polling render loop
      naturally transitions from animating → silent. Once visible, each
      tick advances the spinner frame (wraps at ``len(frames)``).
      ``stop()`` is always-visible, idempotent, and uses a ``✓``
      completion glyph; it tolerates being called without a prior
      ``start()`` by treating the run as zero-length (elapsed = 0.0s)
      rather than raising, so mis-ordered callers don't crash rendering.
      ``set_cost(token_count=…, cost_usd=…)`` allows partial updates
      (``None`` fields preserve the prior value); ``clear_cost()`` wipes
      both. Negative values on either field raise
      :class:`ValueError`. Companion helpers: :func:`format_elapsed(secs)`
      returns ``M:SS`` zero-padded ("0:04", "1:05", "61:01",
      clamps negatives to ``0:00``); :func:`format_effort(snap, *, color)`
      renders ``"  ⠋ · 0:03"`` (or ``"  ✓ · 0:11"`` on finished) with
      optional ``· 1.2k tok`` and ``· $0.012`` segments, routed through
      :func:`theme.meta` so the line is dim in colored mode and
      unstyled under ``color=False``. Token formatting is scale-aware
      (``999 tok`` / ``1.0k tok`` / ``3.2M tok``); cost pinned to three
      decimal places to match Claude's ``$0.013`` footer style. (2)
      `cli/workbench_app/output_collapse.py` ships a :class:`CollapsibleOutput`
      dataclass with ``collapse_threshold`` (default ``10``, matching
      Claude Code's default), ``collapsed`` flag, optional
      ``token_count``, and an internal line buffer. Writes:
      ``append(line)`` / ``extend(lines)`` are append-only (matches the
      T08 tool-call block invariant that progress lines are immutable
      once emitted); ``clear()`` empties the buffer without touching
      the ``collapsed`` flag; ``set_token_count(n)`` attaches a count
      that appears in the collapsed summary (``None`` clears, negative
      raises). Reads: ``lines`` is an immutable tuple snapshot (prior
      snapshots are unaffected by subsequent appends); ``line_count``,
      ``is_collapsible`` (strictly greater-than threshold — equal
      stays expanded), ``is_collapsed`` (collapsible *and* flag set).
      Mutators: ``toggle()`` flips ``collapsed`` and returns the new
      value, *no-op on short buffers* (mirrors the Claude UX where
      pressing Ctrl-O on a short block does nothing); ``expand()`` /
      ``collapse()`` force one direction. Render: ``render(*, color)``
      returns a fresh list — full lines when expanded or below
      threshold, or a single summary line when collapsed. Separate
      :func:`format_summary(hidden_count, token_count, *, color)` lets
      the tool-call footer reuse the same wording without touching a
      buffer instance; the summary reads
      ``"  … N lines hidden · <tokens> · press Ctrl-O to expand"``,
      pluralization-aware (``1 line`` / ``2 lines``, ``0`` reads as
      plural per English convention), routed through :func:`theme.meta`
      so it's dim in colored mode. Wiring: exported both modules from
      `cli/workbench_app/__init__.py` (``EffortIndicator``,
      ``EffortSnapshot``, ``format_effort``, ``format_elapsed``,
      ``CollapsibleOutput``, ``format_summary``) so downstream callers
      can import them without reaching into submodules. No existing
      modules change — these are additive primitives that the T19
      prompt_toolkit layer, the T08 tool-call block renderer, and the
      streaming-handler footers will consume when those tasks land.
      Coverage: `tests/test_workbench_effort.py` (27 tests) using a
      ``_FakeClock`` fixture so no real time passes — defaults sanity,
      tick-before-start → None, tick-below-threshold → None,
      tick-emits-snapshot once visible, spinner-frame-advance + wrap,
      ``start()`` idempotent, ``stop()`` returns final always-visible,
      stop-without-start = 0s, tick-after-stop → None,
      ``stop()`` idempotent (first stop timestamp wins), ``set_cost``
      attaches tokens + USD, partial updates preserve other field,
      ``clear_cost()`` drops metadata, negative cost / token rejected,
      constructor rejects negative threshold / empty frames,
      ``EffortSnapshot`` frozen (``elapsed_seconds`` mutation raises);
      ``format_elapsed`` zero-pad / minute-rollover / clamp-negative;
      ``format_effort`` bare snapshot, finished snapshot uses its own
      frame glyph, token inclusion at 1.2k scale, scale-formatting
      sweep (999 tok / 1.0k / 2.5k / 1.0M / 3.2M), cost rendering
      (``$0.013`` rounding), colored-default unstyles to plain via
      ``click.unstyle``, ANSI escape present under color=True.
      `tests/test_workbench_output_collapse.py` (21 tests) — default
      threshold matches 10, append / extend / clear, is_collapsible
      requires > threshold (equal is not), short buffers always render
      full regardless of flag, collapsed long buffer → single summary
      line, expanded long buffer → full lines, toggle flips on long
      buffers, toggle is noop on short, expand/collapse forcing,
      summary includes token count when set, summary omits tok when
      unset, set_token_count rejects negative + accepts None-to-clear,
      ``lines`` snapshot is tuple (immutable), ``render`` returns fresh
      list (not internal reference), colored-default unstyles to
      plain; ``format_summary`` plural/singular (``1 line`` /
      ``2 lines``), zero renders as plural, token scales (999 /
      1.0k / 2.5k / 1.0M), always mentions Ctrl-O, colored is dim.
      Full workbench surface green (287 tests across effort /
      output_collapse / slash / theme / transcript / status_bar /
      app_stub / screens / tool_call_block / commands); full
      test suite green (4571 passed, 1 unrelated pre-existing
      doctor-test failure not touched by this task).*
- [x] **T19** — Add slash-command autocomplete popup (show matching commands as user
      types `/`). Use the chosen rendering stack's completer. *Landed
      `cli/workbench_app/completer.py` with a pure
      :func:`iter_completions(registry, text_before_cursor)` helper plus a
      :class:`SlashCommandCompleter` that adapts it to the prompt_toolkit
      ``Completer`` contract chosen in the T03 ADR. Rules: the completer
      only fires when the buffer starts with ``/`` **and** the caret is
      still inside the first whitespace token — once the user types a
      space we bail out (``/eval `` / ``/eval --run-id 42`` → no rows)
      so arg completion (future work) doesn't accidentally replace
      typed flags. ``iter_completions`` strips the leading ``/`` and
      delegates to :meth:`CommandRegistry.match_prefix`, which already
      handles case-insensitive prefix matching and alias→primary
      deduplication (``/r`` offers the single underlying ``resume``
      row rather than one per alias). Each match is yielded as a
      frozen :class:`SlashCompletion(name, description, source,
      start_position)` with ``start_position = -len(prefix_after_slash)``
      so prompt_toolkit replaces only the typed portion of the command
      token (the leading ``/`` stays in the buffer). A bare ``/`` sets
      ``start_position = 0`` so the user-typed slash is preserved.
      :class:`SlashCommandCompleter` subclasses prompt_toolkit's
      ``Completer`` lazily (import happens inside ``get_completions``)
      so the module can be imported in headless tests without pulling
      the TUI stack at module scope, and wraps each
      :class:`SlashCompletion` in a ``Completion(text=name,
      start_position=…, display="/" + name,
      display_meta=description)`` so the popup shows the slash-prefixed
      label and a one-line description column — mirroring Claude
      Code's command-palette layout. The completer intentionally uses
      ``document.text_before_cursor`` so a cursor parked mid-buffer in
      ``/expand foo`` (cursor at position 3) still offers matches for
      ``ex`` (``exit``/``expand``) instead of bailing on the trailing
      space. :func:`build_completer(registry)` convenience factory
      mirrors the other ``build_*`` helpers in this package and is
      what T20's real prompt_toolkit ``PromptSession`` wiring will
      call. Exported both helpers plus :class:`SlashCompletion` from
      :mod:`cli.workbench_app` so downstream callers don't need to
      reach into the submodule. No changes to ``run_workbench_app`` —
      the T04 stub loop still uses plain ``input()`` because T20 will
      swap the whole input layer to ``PromptSession`` in one coherent
      move; dropping the completer onto the existing stub is a
      wasteful half-step since plain ``input()`` can't render a
      popup. Coverage: ``tests/test_workbench_completer.py`` (24
      tests) — ``iter_completions``: empty buffer, plain text, bare
      ``/`` returns all commands in canonical (alphabetical) order,
      prefix filtering (``/ex`` → ``exit``/``expand``), single match
      (``/he`` → ``help``), no matches (``/zzz``), case-insensitive
      prefix (``/EX``), generator type, alias dedup (``resume`` +
      ``r`` alias yields single row for ``/r``), argument-space
      bailout (``/eval `` and ``/eval --run-id 42`` both empty),
      ``start_position`` covers typed prefix (``-2`` for ``/ex``),
      ``start_position=0`` on bare ``/``, metadata (description +
      source) carried through; ``SlashCommandCompleter``: wraps
      records as prompt_toolkit ``Completion``, ``display`` includes
      the ``/`` prefix, ``display_meta`` shows description,
      ``start_position`` matches pure helper, non-slash buffer → no
      rows, cursor-mid-buffer (text=``/expand foo``, cursor=3) still
      matches on ``ex``, ``registry`` property exposed;
      ``build_completer`` returns ``SlashCommandCompleter`` carrying
      the same registry; integration with the real
      ``build_builtin_registry()`` offers the canonical command set
      (``help``, ``status``, ``eval``, ``optimize``, ``build``,
      ``deploy``, ``skills``, ``exit``) for ``/``, narrows ``/ev`` to
      a single ``eval`` row; ``SlashCompletion`` frozen invariant
      (mutation raises). Full workbench surface green (596 tests
      across completer / slash / transcript / status / screens /
      app_stub / commands / tool_call_block / eval_slash /
      optimize_slash / build_slash / deploy_slash / skills_slash /
      model_slash / cancellation / theme / effort / output_collapse
      / hardening / live / api / streaming / multi_turn / harness_eng
      / eval_optimize_bridge / cli_workbench / p0_hardening).*
- [x] **T20** — Make workbench the default: `agentlab` with no args launches
      `workbench_app`. Add `--classic` flag to opt out. Update `runner.py` entry logic.
      *Landed a `--classic` flag on the root `cli` Click group
      (``agentlab --classic`` → old `cli.repl.run_shell`; default → new
      workbench app). The ``ctx.invoked_subcommand is None`` branch in
      :func:`runner.cli` now routes TTY + workspace-present invocations
      through a new shared helper
      :func:`cli.workbench_app.app.launch_workbench`, which creates a
      persistent :class:`SessionStore` (scoped to ``workspace.root``) and
      :class:`Session` before calling :func:`run_workbench_app` with
      ``session_store`` / ``session`` wired so T17 persistence and
      ``/resume`` land for free. A ``try/except Exception`` round the
      store creation degrades gracefully to an ephemeral in-memory
      session when the workspace's `.agentlab/` directory is unwritable,
      so a flaky fs can never take the app down. No workspace →
      ephemeral in-memory :class:`Session` (``title="ephemeral"``,
      short-uuid id via the new :func:`cli.workbench_app.app.uuid_hex`
      helper) and ``session_store=None``; the workbench loop already
      handles that case (best-effort persistence guards in
      ``Transcript.bind_session`` / ``dispatch`` tolerate the ``None``).
      The classic opt-out preserves every behavior of the existing
      REPL — ``--classic`` is recorded on ``ctx.obj["classic"]`` so
      future subcommands can inspect it, but passing ``--classic``
      together with an explicit subcommand is a no-op (the subcommand
      runs, neither shell fires). Also updated
      ``agentlab workbench interactive`` to delegate to the new helper
      so session wiring lives in one place (previously it called
      :func:`run_workbench_app` with no session — a silent bug that
      T13/T17 would have masked because the slash handlers happily run
      without persistence). Non-TTY ``agentlab`` with no workspace still
      takes the legacy ``status`` fallback. Coverage:
      ``tests/test_workbench_default_entry.py`` (7 tests) — default
      entry launches workbench (spies on both entry points; asserts
      workspace threaded positionally), ``--classic`` launches REPL
      (and does not spawn the workbench), ``ctx.obj["classic"]`` flag
      visible to a probe subcommand, ``--classic _probe2`` runs the
      subcommand without spawning either shell, non-TTY +
      no-workspace path does not spawn either shell,
      :func:`launch_workbench` wires both store and session for a real
      workspace root under ``tmp_path``, :func:`launch_workbench` with
      no workspace falls back to ``session.title == "ephemeral"`` and
      ``session_store=None``. Full workbench-related subset green (722
      tests across workbench / runner / repl / cli_integrations).*
- [x] **T21** — Unit tests: `tests/cli/test_workbench_slash.py` covering dispatch,
      unknown-command handling, and autocomplete matching. *Landed
      `tests/test_workbench_slash_unit.py` (flat-tests convention matches
      the sibling files already in the tree — the `tests/cli/` path in
      the plan was notional) as a consolidated regression checkpoint
      for the three T21 bullets. The module is explicitly scoped to
      the *integration* between the dispatcher, the unknown-command
      path, and the autocomplete completer against the real built-in
      registry — deeper per-handler coverage stays in
      `tests/test_workbench_slash.py` (1200 lines, 96 tests covering
      every ported handler + display modes + session persistence) and
      completer-internals coverage stays in
      `tests/test_workbench_completer.py` (265 lines, 20 tests).
      Coverage split across three bullets: (1) **dispatch** — 7 tests
      exercising `DispatchResult` shape on a slash line, noop on
      free-text, bare-string return → `display="user"`, `None` return
      → `display="skip"`, `OnDoneResult` with `display="system"` +
      `meta_messages` echo ordering, handler `RuntimeError` caught
      into `result.error` with "Error running /boom" echoed so the
      loop stays alive, `/exit` flipping both `DispatchResult.exit`
      and `ctx.exit_requested`; (2) **unknown-command handling** —
      5 tests: `error == "unknown"` + `command is None`, the echoed
      hint carries the offending token *and* a `/help` pointer
      (all three substrings asserted in one joined line), case-
      insensitive lookup echoes the canonical lower-case form
      (`/NoPe` → `/nope`), registry is not mutated by a missed
      lookup, `SlashContext()` without a registry returns
      `error="no command registry bound"` rather than crashing;
      (3) **autocomplete matching** — 9 tests against the real
      `build_builtin_registry()`: bare `/` offers exactly
      `set(registry.names())` (the core cross-module invariant —
      catches drift between the two surfaces immediately),
      `/ev` narrows to `["eval"]` with `start_position == -2`
      so the popup replaces only the typed prefix, case-insensitive
      `/HE` still matches `help`, no-match → empty iterator,
      completion bails after the first whitespace token (
      `/eval ` and `/eval --run-id abc` both empty — the arg-
      completion hook point), non-slash buffers short-circuit,
      every name the completer offers resolves via `registry.get(row.
      name)` (the "no ghost suggestions" contract), completer shares
      the registry by reference so a late `registry.register(...)`
      is immediately visible in the completer's output,
      `SlashCompletion` frozen invariant preserved. All 21 new tests
      green (`.venv/bin/python -m pytest
      tests/test_workbench_slash_unit.py -q` → 21 passed in 0.08s);
      full slash family green too (`tests/test_workbench_slash.py`
      + `test_workbench_completer.py` + `test_workbench_slash_unit.py`
      + `test_workbench_commands.py` → 138 passed in 0.33s).*
- [x] **T22** — Unit tests: `tests/cli/test_tool_call_block.py` for the new block
      renderer across started/progress/completed/error sequences. *Landed
      `tests/test_tool_call_block_unit.py` (flat-tests convention, matching
      the sibling layout T21 adopted — the `tests/cli/` path in the plan was
      notional). This is a focused sequence-oriented companion to the
      T08-era `tests/test_tool_call_block.py` (single-event coverage, 32
      tests). Where the T08 file tests individual `feed()` calls and their
      return lines, this T22 module walks the renderer through full realistic
      lifecycles the transcript will see during `/eval`, `/optimize`,
      `/build`, and `/deploy` runs, asserting the whole emitted line list +
      final `open_blocks` / `completed_blocks` state shape in one diff. 10
      tests: (1) **full-lifecycle sequences** — started → progress → progress
      → completed renders "⏺ / ⎿ / ⎿ / ✓" in order with `[source]` suffix;
      started → progress → failed renders "⏺ / ⎿ / ✗ failed: <reason>";
      completed-state assertion on a three-step happy path
      (``status="completed"``, ``source="judge"``, ``progress_count==1``);
      failed-state assertion captures ``failure_reason`` from the
      ``failure_reason`` key (not just ``reason``) and correct
      ``progress_count``. (2) **back-to-back sequences** — two independent
      task_ids rendered sequentially (one ok, one failed) emit six lines in
      order. (3) **interleaved sequences** — two concurrent task_ids
      finishing in opposite order render emit-order-preserved lines and
      `completed_blocks` in completion order (`[b, a]`). (4) **mixed
      success/failure** — concurrent ok + bad tasks yield
      ``{"ok": "completed", "bad": "failed"}`` with `open_blocks` empty
      at the end. (5) **stream termination** — truncated sequence
      (only started + progress) trailing footer reads
      "  ✗ failed: stream ended" via `render_tool_call_block`'s
      `close_unfinished=True` default; orphan progress-then-completed
      stream synthesises header correctly. (6) **non-task interleaving**
      — `turn.started` / `run.completed` pass through to
      `format_workbench_event`, `harness.heartbeat` and `message.delta`
      are silently suppressed, and the final line count accounts for
      both passthrough and suppression. No changes to
      `cli/workbench_render.py`; the existing renderer already satisfied
      all ten sequences on the first run. Full subset green:
      `tests/test_tool_call_block.py` + the new file +
      `tests/test_workbench_transcript.py` → 65 passed in 0.09s.*
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
