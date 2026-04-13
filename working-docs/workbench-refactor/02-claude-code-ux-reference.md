# T02 — Claude Code UX Reference

Baseline of the Claude Code terminal UX we are targeting for the AgentLab workbench
refactor. Sourced from:

- Official docs: https://code.claude.com/docs/en/how-claude-code-works
- Source mirror: https://github.com/yasasbanukaofficial/claude-code
  (Ink/React-in-terminal; we translate patterns to Python, not code.)
- User-provided screenshots of the Claude Code transcript and tool blocks.

Each section names the UX primitive, summarizes the observed behavior, and points to
the PLAN.md task that lands the equivalent in AgentLab. Where the mirror exposes a
named component we cite it so future porting is unambiguous.

## 1. Startup & banner

- `claude` with no args boots directly into the REPL; no subcommand required. A small
  banner prints (product name + mode hints like "Plan mode: Shift+Tab to cycle").
- Directory-scoped: the session is tied to `cwd`; `--continue` / `--resume` only see
  sessions for the current directory.
- `/init` and `/doctor` are advertised as onboarding helpers.
- **AgentLab mapping:** T04 (stub app + banner), T20 (default entry point),
  T24 (entry-point regression test).

## 2. Status line

Bottom-anchored line that never scrolls. Observed fields in Claude Code:

| Field | Content |
|-------|---------|
| Working directory | Absolute path (truncated left) |
| Git branch | Current branch when inside a repo |
| Permission mode | `default` / `auto-accept` / `plan` / `auto` (toggled by Shift+Tab) |
| Model | e.g. `sonnet` / `opus`; swap via `/model` |
| Context meter | % of context window consumed; `/context` expands it |
| Session marker | Transient hint ("resumed", "forked", "compacted") |

Updates reactively on every event, never blocks the transcript.
- **AgentLab mapping:** T06 (status bar with workspace label, config version, model,
  pending reviews, best score). We replace Claude's git/branch cluster with
  workspace+config version; everything else maps 1:1.

## 3. Input box

- Single-line by default; expands when the user pastes multi-line content or presses
  the newline chord.
- Leading `/` pops a slash-command palette (see §6).
- Typing into a running tool call does not interrupt — Enter submits queued input to
  the next turn. Interrupt is Esc/Ctrl-C, not typing.
- Esc twice rewinds to the previous checkpoint (file-edit snapshots).
- **AgentLab mapping:** T04 (prompt), T16 (ctrl-c semantics), T19 (slash autocomplete),
  T25 (free-text fallback so we don't regress `_route_free_text`).

## 4. Transcript layout

Claude Code's transcript is a single scrollable stream of role-colored entries:

- **User** turns: plain paragraph, dim prefix `>`.
- **Assistant** turns: reasoning/body text, no prefix, word-wrapped to terminal width.
- **Tool calls**: nested block (see §5) indented under the assistant turn that
  triggered them.
- **Meta lines**: dimmed, single-line, reserved for system events (compaction, resume,
  permission prompts, checkpoint markers).
- Long outputs collapse to a one-line summary with token count; `Ctrl-O` toggles the
  full body (mirror: `CtrlOToExpand`).
- **AgentLab mapping:** T07 (transcript pane reusing `render_workbench_event`),
  T18 (theme palette), T18b (Ctrl-O expand/collapse + effort indicator).

## 5. Tool-call block

This is the primitive that separates Claude Code's transcript from a typical REPL log.
Each tool invocation renders as a nested block with three parts:

```
┌─ Tool: Bash(npm test)             ← header: tool name + one-line arg summary
│  running… 0:04  (spinner)         ← streaming body: progress, partial output
│  3 passed, 1 failed               ← live updates land in-place
└─ ✓ done  0:11  1.2k tok           ← footer: status + elapsed + token cost
```

Key behaviors observed:

- Header shows tool name and a condensed invocation (first 60 chars of args).
- Body streams in real time; long stdout collapses after ~10 lines with a
  "⏎ press Ctrl-O to expand" hint.
- Footer replaces the spinner with a status glyph (✓ / ✗ / ⏸) plus elapsed time,
  cost/token count when available, and cache hit markers.
- For file edits the body renders a unified diff (mirror: `FileEditToolDiff`) with
  +/- gutter and path header.
- For bash tool blocks the mirror exposes `BashModeProgress` — a spinner + rolling
  last-output line + cancel hint.
- Sub-agent invocations show an `AgentProgressLine` summarizing the delegated task
  (name + status dots).
- Interrupt semantics: first Ctrl-C closes the currently streaming block with a
  "cancelled" footer; second Ctrl-C exits.

**AgentLab mapping:** T08 (`render_tool_call_block(event_stream)` wrapping the 22
existing event renderers), T18b (`EffortIndicator` spinner + elapsed time + cost for
any call > 2s), T16 (Ctrl-C / Esc cancellation).

## 6. Slash-command palette

- Typing `/` opens an in-place popup of matching commands with one-line help; arrow
  keys navigate, Enter accepts, Esc dismisses.
- Built-in catalog observed or documented: `/init`, `/agents`, `/doctor`, `/context`,
  `/mcp`, `/compact`, `/model`, `/resume`, `/clear`, `/help`, `/status`, `/memory`,
  `/review`, plugin-contributed entries.
- Commands are grouped by source (built-in vs plugin vs project vs user) — the mirror
  carries a `source` field on every command entry.
- Three-tier taxonomy from the mirror's `src/types/command.ts`:
  - **`local`** — runs inline, returns a string that becomes a system/user meta
    message.
  - **`local-jsx`** — takes over the screen with a full-screen component until the
    user exits (see §9).
  - **`prompt`** — expands to a templated user prompt that the model answers.
- Each command declares metadata: `name`, `description`, `source`, optional `paths`
  globs (for file-scoped commands), `context` (`'inline' | 'fork'`), `agent`, `hooks`,
  `effort`, `allowedTools`.
- Return protocol: every handler ends with
  `onDone(result, display, shouldQuery, metaMessages)`:
  - `display`: `'skip' | 'system' | 'user'` — controls how (or whether) the result
    appears in the transcript.
  - `shouldQuery`: true when the output should be fed back into the model as a new
    user turn.
  - `metaMessages`: dimmed system lines surfaced alongside the result.

**AgentLab mapping:** T02b (typed command dataclasses mirroring the taxonomy),
T05 (extract registry from `cli/repl.py`), T05b (`onDone` protocol + unit tests for
each display mode), T19 (autocomplete popup via the chosen render stack).

## 7. Ctrl-C / Esc / Shift+Tab behavior

| Chord        | Claude Code behavior                                                   |
|--------------|------------------------------------------------------------------------|
| `Ctrl-C ×1`  | Cancels the active tool call; transcript gets a `cancelled` footer     |
| `Ctrl-C ×2`  | Exits the app; kills any lingering subprocess                          |
| `Esc`        | Dismisses popups / exits a `local-jsx` screen                          |
| `Esc ×2`     | Rewinds to the previous file-edit checkpoint                           |
| `Shift+Tab`  | Cycles permission modes (default → auto-accept → plan → auto)          |
| `Ctrl-O`     | Toggles collapse/expand on the currently focused tool-call block       |

- Session-scoped permissions do NOT carry across resume — users re-approve on each
  new session.
- **AgentLab mapping:** T16 (Ctrl-C ladder, no orphan subprocesses), T18b (Ctrl-O),
  T08b (Esc exits full-screen takeovers). Esc-twice checkpoints and Shift+Tab
  permission cycling are **out of scope** for this refactor — we don't own a
  filesystem checkpoint layer and our "permission modes" are the existing workspace
  config. Note these as future work.

## 8. Compaction & context view

- `/context` renders a `ContextVisualization` — a stacked bar showing system prompt,
  CLAUDE.md, auto-memory, tool defs, transcript, live tool output.
- Auto-compaction kicks in near the context limit. Older tool outputs are dropped
  first; then the conversation is summarized. The resulting summary is shown as a
  `CompactSummary` meta block so the user sees what was preserved.
- `/compact focus on X` accepts a focus hint that biases the summary.
- If a single tool payload refuses to fit after summarization, the app stops looping
  and surfaces a thrashing error.
- **AgentLab mapping:** We already have `/compact` (writes
  `.agentlab/memory/latest_session.md`). T07 can render its output as a meta block;
  a full `ContextVisualization` equivalent is **out of scope** for now — park it as a
  stretch for the docs update in T26.

## 9. Full-screen takeovers (`local-jsx` screens)

Observed Claude Code screens that pause the transcript:

- `REPL` — the default screen wrapping input + transcript.
- `Doctor` — renders diagnostics inline in a full-screen panel; Esc returns.
- `ResumeConversation` — lists recent sessions, arrow-key navigable, Enter resumes
  or `f` forks.
- `SkillsMenu` — browse skills, press keys to `list / show / add / edit / remove`;
  opens `$EDITOR` for add/edit; exit returns to REPL.
- `AgentsMenu` (via `/agents`) — same pattern for sub-agent configs.

Contract (from the mirror): each screen implements a `run() -> Result` that blocks
until the user exits, takes ownership of the key bindings while active, and restores
the transcript cleanly on exit. Transcript state must survive the takeover.

- **AgentLab mapping:** T08b (base `Screen` class + `DoctorScreen`, `ResumeScreen`,
  `SkillsScreen` stubs), T13 (flesh out `SkillsScreen` — must not regress the flat
  `cli/skills.py` surface; screen delegates to it).

## 10. Sessions & resume

- Session files are JSONL under `~/.claude/projects/<dir-hash>/`. Each user message,
  assistant response, and tool call is one line.
- `claude --continue` resumes the most recent session for the cwd; `claude --resume`
  opens a picker; `--fork-session` branches off without mutating the original.
- Resumed sessions restore transcript but NOT session-scoped permissions.
- Running the same session in two terminals is allowed but interleaves writes —
  the docs flag this as a footgun.
- **AgentLab mapping:** T15 (`/clear`, `/new`), T17 (real `/resume` that replays
  transcript, not just metadata as `cli/repl.py:121-129` does today). Fork support is
  **out of scope** — note as follow-up.

## 11. Theming & typography conventions

From the screenshots and docs we can see:
- Dimmed grey for meta lines, timestamps, footers.
- Cyan for workspace/cwd and primary identifiers.
- Green for successful completions, checkmarks.
- Yellow for warnings, stalls, cancellations.
- Red for errors and failed tool calls.
- Bold only on terminal status words (`done`, `failed`, `cancelled`).
- Monospace single-column layout — no tables that rely on width estimation.

Matches the palette already implied by `cli/workbench_render.py` (it uses
`click.style(..., fg='cyan'|'green'|'yellow'|'red')`).
- **AgentLab mapping:** T18 (`cli/workbench_app/theme.py` centralizing the palette).

## 12. Summary — which Claude Code primitives map to which AgentLab tasks

| Claude Code primitive / feature            | AgentLab task(s)     |
|--------------------------------------------|----------------------|
| Banner + default-entry REPL                | T04, T20, T24        |
| Status line                                | T06                  |
| Transcript pane                            | T07, T18             |
| Tool-call block (header/body/footer)       | T08, T18b            |
| AgentProgressLine / BashModeProgress       | T08 (reuse), T18b    |
| FileEditToolDiff                           | T08 (diff branch)    |
| Slash-command palette + taxonomy           | T02b, T05, T05b, T19 |
| `onDone(result, display, shouldQuery, …)`  | T05b                 |
| Full-screen takeovers (Doctor/Resume)      | T08b                 |
| SkillsMenu                                 | T13                  |
| Ctrl-C ladder, Ctrl-O collapse             | T16, T18b            |
| CompactSummary meta block                  | T07 (meta render)    |
| Session resume replays transcript          | T17                  |
| Theme palette                              | T18                  |
| `/eval /optimize /build /deploy /model`    | T09–T14              |
| `/clear`, `/new`                           | T15                  |

### Explicitly out of scope for this refactor
- Filesystem checkpoints + Esc×2 rewind (no snapshot layer in AgentLab).
- `Shift+Tab` permission modes (AgentLab uses workspace config, not a per-turn mode).
- `--fork-session` (sessions aren't branched today; note as follow-up).
- `ContextVisualization` (no token accounting surface yet; stretch for T26).

These deferrals are documented here so future work can pick them up without a second
archaeology pass.
