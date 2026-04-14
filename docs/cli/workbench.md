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
  `/build`, `/deploy`, `/skills`, and session utilities) available
  inline with live stream-json progress.
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
| `/compact` | Summarize the current session into `.agentlab/memory/latest_session.md`. |
| `/sessions [count]` | List recent persisted sessions with `/resume <session_id>` hints. |
| `/shortcuts` | Show keyboard shortcuts and input affordances. Bare `?` opens the same view. |
| `/clear` | Wipe the visible transcript while keeping the active session (on-disk session is preserved). |
| `/new [title]` | Start a fresh session and clear the transcript. Optional positional `title` becomes the session label. |
| `/resume [session_id]` | Restore the latest session's transcript (or the explicit `session_id`). Alias: `/r`. |
| `/exit` | Exit the Workbench. Aliases: `/quit`, `/q`. |

### Workflow (streaming)

These commands shell out to the root CLI with `--output-format
stream-json` and pipe events into the transcript in real time.

| Command | Wraps | Notes |
|---------|-------|-------|
| `/eval [--config VERSION\|--run-id ID] [...]` | `agentlab eval run` | `--run-id` is sugar for `--config` so the documented `/eval` surface matches Claude-style references. |
| `/optimize [--cycles N] [--mode MODE] [--continuous] [...]` | `agentlab optimize` | Counts `phase_completed` events labeled `optimize-cycle` and reports `M cycles` in the final summary. |
| `/build <brief> [...]` | `agentlab workbench build` | Requires a brief. Summary surfaces the new candidate project id and suggests `/save`. |
| `/save [...]` | `agentlab workbench save` | Materializes the active candidate into the workspace config path. |
| `/deploy [canary\|immediate] [...]` | `agentlab deploy` | Prompts `Deploy with strategy=<s>? (y/N)` unless `--dry-run` or `-y`/`--yes` is passed. Cancelling at the prompt never spawns the subprocess. |

### Skills

| Command | What it does |
|---------|--------------|
| `/skills` | Opens a full-screen navigable list of configured skills. Arrow keys or `j/k` navigate. Action keys: `l` list, `s` show (detail), `a` add (opens `$EDITOR` with a starter YAML), `e` edit selected, `r` remove selected (with confirm). `q`/`esc` exits back to the transcript. |

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
via `agentlab --classic`. It emits a `DeprecationWarning` on entry and
points at this doc. Queued input while the harness is busy still lives
only in the classic shell; Workbench now owns prompt permission cycling,
slash discovery, shortcut help, and session visibility.

---

## See also

- [CLI Reference](../cli-reference.md) — full root-CLI command reference.
- [Claude-Style Auto Mode](../guides/claude-style-auto-mode.md) — the
  non-interactive `--ui auto` harness that backs `agentlab optimize`,
  `agentlab full-auto`, and related long-running flows.
- [Workbench feature guide](../features/workbench.md) — product overview
  of the Workbench candidate loop (the same loop surfaced here via
  `/build` and `/save`).
