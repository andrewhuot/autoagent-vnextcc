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
- [ ] **T05b** — Implement Claude Code's `onDone` return protocol in
      `cli/workbench_app/slash.py`:
      `onDone(result: str | None, *, display: 'skip'|'system'|'user'='user',
      should_query: bool=False, meta_messages: list[str] | None=None)`. Every slash
      handler returns via this contract. Add unit tests for each display mode.
- [ ] **T06** — Implement live status line in `cli/workbench_app/status_bar.py` showing
      workspace label, active config version, model, pending reviews, best score. Update
      on every event.
- [ ] **T07** — Implement streaming transcript pane in `cli/workbench_app/transcript.py`
      that consumes `render_workbench_event` output and appends lines with role-based
      coloring.
- [ ] **T08** — Build the tool-call block renderer: a nested block (header, streaming
      body, footer) for `task.started`/`task.progress`/`task.completed` sequences. Add
      to `cli/workbench_render.py` as `render_tool_call_block(event_stream)` + unit tests.
- [ ] **T08b** — Port Claude Code's screen/dialog pattern to
      `cli/workbench_app/screens/` (full-screen takeovers that pause the transcript).
      Scaffold `DoctorScreen`, `ResumeScreen`, `SkillsScreen` base classes with a
      `run() -> Result` contract. Each screen owns its own key bindings and restores
      the transcript on exit.
- [ ] **T09** — Add `/eval [--run-id …]` slash command that spawns `agentlab eval run`
      as an async subprocess, pipes stream-json output through the transcript, and
      surfaces summary on completion.
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
