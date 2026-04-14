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
- **Transcript pane** — streaming, role-colored lines: user input,
  assistant output, tool calls, errors, warnings, and dim meta.
- **Tool-call blocks** — nested `⏺ title / ⎿ progress / ✓ done` blocks
  for every `task.started`/`task.progress`/`task.completed` sequence.
- **Slash commands** — the entire workflow (`/eval`, `/optimize`,
  `/build`, `/deploy`, `/skills`, and session utilities) available
  inline with live stream-json progress.
- **Autocomplete** — typing `/` pops a list of matching commands with
  one-line descriptions.
- **Session persistence** — every transcript entry and slash command is
  appended to the workspace `SessionStore`. `/resume` restores the
  latest (or a named) session; startup surfaces a dim hint when a
  recent prior session exists.
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
| `/help` | Show every registered slash command with its one-line description. |
| `/status` | Print workspace status (wraps `agentlab status`). |
| `/config` | Show the active config version and summary. |
| `/memory` | Display `AGENTLAB.md` project memory. |
| `/doctor` | Run workspace diagnostics (wraps `agentlab doctor`). |
| `/review` | List pending review cards. |
| `/mcp` | Show MCP integration status. |
| `/model [key\|reset]` | Without args: list configured models, marking the session-active one. With a provider/model key: switch the active model for the session (persisted to session state). `reset`/`clear` drops the override. |
| `/compact` | Summarize the current session into `.agentlab/memory/latest_session.md`. |
| `/clear` | Wipe the visible transcript while keeping the active session (on-disk session is preserved). |
| `/new [title]` | Start a fresh session and clear the transcript. Optional positional `title` becomes the session label. |
| `/resume [session_id]` | Restore the latest session's transcript (or the explicit `session_id`). |
| `/exit` | Exit the Workbench. |

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

---

## Startup flow

1. `agentlab` boots into the Workbench.
2. A `SessionStore` is created for the workspace (falls back to an
   in-memory ephemeral session if `.agentlab/` is unwritable or the
   command is run outside a workspace).
3. The banner renders, followed by a dim `Tip: /resume to continue …`
   if a recent prior session exists (< 24h old).
4. The status line paints and the prompt becomes interactive.

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
points at this doc. Two features still live only in the classic shell:

- Queued input while the harness is busy.
- Bottom-toolbar permission cycling (shift-tab).

Both are slated for the Workbench before the classic shell is removed.
Track the migration in the `refactor/workbench-claude-code-ux` branch
and the top-level `PLAN.md`.

---

## See also

- [CLI Reference](../cli-reference.md) — full root-CLI command reference.
- [Claude-Style Auto Mode](../guides/claude-style-auto-mode.md) — the
  non-interactive `--ui auto` harness that backs `agentlab optimize`,
  `agentlab full-auto`, and related long-running flows.
- [Workbench feature guide](../features/workbench.md) — product overview
  of the Workbench candidate loop (the same loop surfaced here via
  `/build` and `/save`).
