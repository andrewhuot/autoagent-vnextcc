# CLI Workbench (Interactive Mode)

The **AgentLab Workbench** is a Claude-Code-style interactive terminal app:
a single persistent REPL with a live status line, streaming transcript,
slash-command surface, and first-class skill authoring. As of this
release it is the default `agentlab` entry point.

```bash
agentlab            # launches the interactive Workbench (default)
agentlab --classic  # opt out: run the legacy shell REPL
```

If stdin is not a TTY, `agentlab` falls back to the non-interactive
`status` summary so CI jobs and piped invocations still behave
predictably.

---

## What you get

- **Status line** — workspace label, active config version, model,
  pending-review count, best eval score, plus per-run overlays
  (current phase/cycle).
- **Structured terminal panes** — startup session context, `/help`,
  candidate summaries, readiness, provenance, and next steps all share a
  width-aware renderer so output stays readable in narrow terminals and
  copy/paste logs.
- **Transcript pane** — streaming, role-colored lines: user input,
  assistant output, tool calls, errors, warnings, and dim meta.
- **Tool-call blocks** — nested `⏺ title / ⎿ progress / ✓ done` blocks
  for every `task.started`/`task.progress`/`task.completed` sequence.
  Events that carry `ratio`, `progress`, or `current`/`total` render a
  fixed-width fractional progress bar without changing plain progress
  events.
- **Slash commands** — the entire workflow (`/eval`, `/optimize`,
  `/build`, `/deploy`, `/skills`, `/tasks`, and session utilities)
  available inline through the coordinator-worker harness.
- **Autocomplete** — typing `/` pops a list of matching commands with
  descriptions, argument hints, aliases, and command source. Matches
  rank names, aliases, and descriptive text so discovery works even
  when you remember intent instead of the exact token.
- **Session persistence** — free-text user turns and slash commands are
  appended to the workspace `SessionStore`. `/resume` restores the
  latest (or a named) session; startup surfaces a dim hint when a
  recent prior session exists.
- **Prompt shortcuts** — bare `?` or `/shortcuts` opens the shortcut
  reference promised by the startup banner.
- **Permission chrome** — mode labels use Claude-Code-style symbols:
  `Default`, `⏵⏵ Accept edits`, `⏸ Plan Mode`, and `⏵⏵ Bypass`.
- **Ctrl-C semantics** — first press cancels the active streaming tool
  call (subprocess is terminated cleanly, no orphans); second press
  exits the app.
- **Themed output** — cyan workspace, green success, yellow warning,
  red error, dim meta. Overridden for `--no-color` / non-TTY output.

---

## Natural-language turns

Free text is no longer echoed back as a placeholder. Workbench treats a
plain-language request as a coordinator turn:

```text
› I want to build my agent
  Coordinator plan coord-... created for 5 workers.
  • requirements analyst: completed ...
  • build engineer: completed ...
  • eval author: completed ...
```

The coordinator creates a Builder project/session/task when needed,
plans specialist worker roles, executes bounded workers, persists the
plan/run ids, and leaves reviewable artifacts plus next actions in the
transcript. Follow-up turns reuse the active Builder project/session so
`evaluate it`, `optimize from those failures`, and `prepare deploy`
continue the same agent-building thread.

---

## Slash commands

Run `/help` inside the Workbench for the current list. The built-in
registry ships the following commands:

### Core / session

| Command | What it does |
|---------|--------------|
| `/help [command]` | Show source-grouped slash commands, or details for one command. |
| `/status` | Print workspace status (wraps `agentlab status`). |
| `/config` | Show the active config version and summary. |
| `/memory` | Display `AGENTLAB.md` project memory. |
| `/doctor` | Run workspace diagnostics (wraps `agentlab doctor`). |
| `/review` | List pending review cards. |
| `/mcp` | Show MCP integration status. |
| `/model [key\|reset]` | Without args: list configured models, marking the session-active one. With a provider/model key: switch the active model for the session (persisted to session state). `reset`/`clear` drops the override. |
| `/cost` | Show recorded session cost totals when model calls have populated them; otherwise says no cost data is recorded yet. |
| `/tasks` | Show the latest coordinator task, plan id, run id, worker roster, active-task count, queued input count, and next actions. Alias: `/task`. |
| `/compact` | Summarize the current session into `.agentlab/memory/latest_session.md`. |
| `/sessions [count]` | List recent persisted sessions with `/resume <session_id>` hints. |
| `/shortcuts` | Show keyboard shortcuts and input affordances. Bare `?` opens the same view. |
| `/clear` | Wipe the visible transcript while keeping the active session (on-disk session is preserved). |
| `/new [title]` | Start a fresh session and clear the transcript. Optional positional `title` becomes the session label. |
| `/resume [session_id]` | Restore the latest session's transcript (or the explicit `session_id`). Alias: `/r`. |
| `/exit` | Exit the Workbench. Aliases: `/quit`, `/q`. |

### Workflow (coordinator-worker)

These commands seed explicit coordinator turns. They create a persisted
plan, execute the relevant specialist workers, render a compact worker
summary, and store the latest task/plan/run ids for `/tasks`.

| Command | Coordinator intent | Notes |
|---------|--------------------|-------|
| `/build [brief]` | Build | Plans requirements, build, prompt, architecture, and eval-author workers. With no brief, it refines the active agent. |
| `/eval [target]` | Eval | Plans eval-author and trace-analysis workers against the active candidate/config. |
| `/optimize [request]` | Optimize | Plans trace, optimization, prompt, and guardrail workers. Outputs review-required change cards instead of silently applying changes. |
| `/deploy [request]` | Deploy | Plans deployment and release-manager workers with canary-first and rollback evidence. Approval gates remain required before irreversible deploys. |
| `/skills [request]` | Skills | Plans skill-author work to recommend or attach build-time skills with review. |
| `/save [...]` | Save | Materializes the active Workbench candidate into the workspace config path. |

### Skills

`/skills [request]` now participates in the same coordinator-worker loop
as build/eval/optimize/deploy. Use it conversationally for build-time
skill recommendations or attachments. The older full-screen browser code
remains available to direct screen callers, but the default Workbench
command favors the coordinator so skill changes are planned, reviewed,
and tied to the active Builder project.

All completed slash-command output lands on the transcript with the
appropriate role coloring, and the final summary surfaces as a dim meta
line (e.g. `Suggested next: …`, artifact paths).

The pane/progress primitives live in `cli/terminal_renderer.py`. They are
the current Python-native bridge toward a fuller Ink/React renderer: CLI
business logic emits structured data first, and terminal formatting stays
centralized so the Workbench can migrate surface by surface without
rewriting the Click command layer.

---

## Startup flow

1. `agentlab` boots into the Workbench.
2. A `SessionStore` is created for the workspace (falls back to an
   in-memory ephemeral session if `.agentlab/` is unwritable or the
   command is run outside a workspace).
3. The banner renders, followed by a dim `Tip: /resume to continue …`
   if a recent prior session exists (< 24h old).
4. The status line paints and the prompt becomes interactive.

The turn footer reports the current permission mode plus truthful
activity state. When no shell or task counters are supplied by the
running command context, it says `idle`; it does not print placeholder
activity.

`shift+tab` cycles visible modes in this order:
`default -> acceptEdits -> plan -> bypass -> default`. Existing settings
that contain `dontAsk` still load, then return to `default` on the next
interactive cycle.

Long-running operation footers can include an action verb such as
`thinking...`, token/cost details when present, and a warning-colored
stalled state when no progress has been recorded for the configured
stall window.

---

## Cancellation and exit

- **Ctrl-C during a streaming tool call** — the subprocess is sent
  SIGTERM (escalated to SIGKILL after a short grace window if
  ignored), the handler echoes a yellow `cancelled` line, and the
  app stays live.
- **Ctrl-C at idle** — the app echoes
  `press ctrl-c again to exit, or /exit` and stays live.
- **Ctrl-C twice in a row, with no input in between** — the app
  exits cleanly (`exited_via="interrupt"`).
- **`/exit` or EOF (Ctrl-D)** — clean exit.

The app guarantees that no subprocess outlives it: every streaming
runner registers its child on `CancellationToken` and unregisters in a
`finally` clause.

---

## Classic REPL

The pre-Workbench `agentlab` shell is still available for one release
  via `agentlab --classic` or `agentlab shell --ui classic`. `agentlab
shell` without `--ui classic` is now a compatibility alias for the
Workbench. Classic emits a `DeprecationWarning` on entry and points at
this doc.

---

## See also

- [CLI Reference](../cli-reference.md) — full root-CLI command reference.
- [Claude-Style Auto Mode](../guides/claude-style-auto-mode.md) — the
  non-interactive `--ui auto` harness that backs `agentlab optimize`,
  `agentlab full-auto`, and related long-running flows.
- [Workbench feature guide](../features/workbench.md) — product overview
  of the Workbench candidate loop (the same loop surfaced here via
  `/build` and `/save`).
