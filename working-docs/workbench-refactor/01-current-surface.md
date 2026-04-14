# T01 — Current Surface Audit

Audit of the existing AgentLab CLI surface taken from the
`refactor/workbench-claude-code-ux` branch as a baseline for the Claude-Code-style
refactor. Three surfaces are enumerated: **slash commands** (interactive REPL),
**workbench events** (stream renderers), and **Click commands** (top-level CLI).

## 1. Slash commands — `cli/repl.py`

Source: `cli/repl.py:51-62` (`SLASH_COMMANDS` mapping) and the dispatch ladder in
`_handle_slash_command` (`cli/repl.py:65-132`).

| Slash | Help (as shipped) | Handler behaviour |
|-------|-------------------|-------------------|
| `/help` | Show available slash commands | Print `SLASH_COMMANDS` table (`repl.py:78-83`) |
| `/status` | Show workspace status | Delegates to `agentlab status` via `CliRunner` (`repl.py:85-87`) |
| `/config` | Show active config info | Reads `workspace.resolve_active_config()` directly (`repl.py:89-99`) |
| `/memory` | Show AGENTLAB.md contents | Delegates to `agentlab memory show` (`repl.py:101-103`) |
| `/doctor` | Run workspace diagnostics | Delegates to `agentlab doctor` (`repl.py:105-107`) |
| `/review` | Show pending review cards | Delegates to `agentlab review` (`repl.py:109-111`) |
| `/mcp` | Show MCP integration status | Delegates to `agentlab mcp status` (`repl.py:113-115`) |
| `/compact` | Summarize session to `.agentlab/memory/latest_session.md` | `_compact_session` writes markdown summary (`repl.py:117-119`, `152-185`) |
| `/resume` | Resume the most recent session | Prints latest-session metadata only (does not load transcript) (`repl.py:121-129`) |
| `/exit` | Exit the shell | Returns `True` to break the loop (`repl.py:75-76`) |

Free-text router (`_route_free_text`, `repl.py:188-213`) does keyword matching to pick
one of: `build`, `eval run`, `improve`, `review`, `deploy status`, `status`, or a stub
`edit` path. No slash command currently exists for `/build /eval /optimize /deploy
/skills /model /clear /new /theme` — those are all net-new surface for the refactor.

**Gaps relative to target Claude-Code UX:** no autocomplete, no slash popup, no
streaming tool-call blocks, no ctrl-C cancellation semantics, `/resume` does not
actually restore transcript, every delegated command invocation blocks the loop and
buffers output through `CliRunner.invoke` so the user cannot watch progress live.

## 2. Workbench streaming events — `cli/workbench_render.py::_EVENT_RENDERERS`

Source: `cli/workbench_render.py:30-74`. 22 event types are rendered today.

| Event name | Renderer output (shape) | Notes |
|------------|-------------------------|-------|
| `turn.started` | `[turn] Started turn N` (cyan) | one-liner |
| `plan.ready` | `[plan] Plan ready: N tasks` (cyan) | counts via `_count_plan_tasks` |
| `task.started` | `[task] {title} ...started` | per-task lifecycle start |
| `task.progress` | `[task] {title}: {note}` | incremental note |
| `task.completed` | `[task] {title} ...done [source]` (green) | per-task lifecycle end |
| `message.delta` | *(suppressed)* | returns `None` |
| `artifact.updated` | `[artifact] {name} updated` | artifact mutations |
| `iteration.started` | `[iterate] Iteration N started` (yellow) | optimization loop |
| `reflect.started` | `[reflect] Starting validation...` | self-review |
| `reflect.completed` | `[reflect] Reflection complete` | |
| `reflection.completed` | `[reflect] Quality: {quality_score}` | quality gate |
| `validation.ready` | `[validate] Validation: {status}` (green/yellow) | |
| `present.ready` | `[present] {summary}` | presenter stage |
| `build.completed` | `[build] Build pass complete` (green) | |
| `run.completed` | `[done] Run complete: Draft v{version}` (green bold) | terminal success |
| `run.failed` | `[error] Run failed: {reason}` (red) | terminal failure |
| `run.cancelled` | `[cancelled] Run cancelled: {reason}` (yellow) | ctrl-C surface |
| `harness.metrics` | *(suppressed)* | returns `None` |
| `harness.heartbeat` | *(suppressed)* | keep-alive only |
| `progress.stall` | `[warn] Progress stall detected` (yellow) | watchdog |
| `error` | `[error] {message}` (red) | generic |

**Gaps relative to target UX:** there is no nested/tool-call block renderer —
`task.started`/`task.progress`/`task.completed` are printed as flat lines rather than
a collapsible block. No `EffortIndicator` (elapsed time, cost, spinner) and no
ctrl-O expand/collapse for long payloads. `message.delta` suppression means streaming
model output is invisible today.

Other render helpers in the same module (not event-driven, but relevant for future
transcript display): `render_workbench_status` (`workbench_render.py:82-152`),
`render_candidate_summary` (`160-218`), `render_save_result` (`226-240`),
`render_bridge_status` (`248-285`), `render_project_list` (`293-313`),
`render_validation` (`321-331`), `render_plan` (`339-354`).

## 3. Click command catalog — `runner.py`

Top-level `@cli` group at `runner.py:2168`. The interactive workbench needs to
delegate into these via `CliRunner` or async subprocess — never re-implement.

### Top-level single commands
`advanced`, `shell`, `continue`, `init` (hidden), `new`, `build-show` (hidden),
`optimize`, `deploy`, `status`, `logs`, `doctor`, `pause` (hidden), `resume`
(hidden), `reject`, `pin`, `unpin`, `server`, `mcp-server`, `full-auto`,
`quickstart`, `ship` (hidden), `edit`, `explain`, `diagnose`, `replay`.

### Top-level groups (each with subcommands)
- `session` (hidden) — `list`, `resume`, `delete`
- `template` — `list`, `apply`
- `connect` — `openai-agents`, `anthropic`, `http`, `transcript`
- `provider` — `configure`, `list`, `test`
- `build` (default `run`) — `run`, `show`
- `eval` (default `run`) — `run`, `results` (sub: `annotate`, `export`, `diff`),
  `show`, `list`, `generate`, `compare` (sub: `show`, `list`), `breakdown`
- `improve` (hidden, default `run`) — `run`, `list`, `show`, `optimize`
- `compare` — `configs`, `evals`, `candidates`
- `instruction` — `show`, `edit`, `validate`, `generate`, `migrate`
- `config` — `resolve`, `list`, `show`, `set-active`, `diff`, `import`,
  `rollback`, `migrate`, `edit`
- `loop` (hidden, default `run`) — `run`, `pause`, `resume`
- `autofix` — `suggest`, `apply`, `revert`, `history`, `show`
- `judges` — `list`, `calibrate`, `drift`
- `context` — `analyze`, `simulate`, `report`
- `review` — `list`, `show`, `apply`, `reject`, `export`
- `changes` — `list`, `show`, `approve`, `reject`, `export`
- `experiment` — `log`
- `runbook` — `list`, `show`, `apply`, `create`
- `memory` — `show`, `list`, `where`, `edit`, `summarize-session`, `add`
- `run` (hidden) — `agent`, `eval`, `observe`, `optimize`, `loop`, `status`
- `registry` — `list`, `show`, `add`, `diff`, `import`
- `skill` — `export-md`, `import-md`
- `curriculum` — `generate`, `list`, `apply`
- `trace` — `show`, `grade`, `blame`, `graph`, `promote`
- `scorer` — `create`, `list`, `show`, `refine`, `test`
- `demo` — `quickstart`, `seed`, `vp`
- `build-inspect` (hidden) — (placeholder group)
- `policy` — `list`, `show`
- `cx` — `auth`, `compat`, `list`, `import`, `export`, `diff`, `sync`,
  `deploy`, `widget`, `status`
- `adk` — `import`, `export`, `deploy`, `status`, `diff`
- `dataset` — `create`, `list`, `stats`
- `outcomes` — `import`
- `release` — `list`, `create`
- `benchmark` — `run`
- `reward` — `create`, `list`, `test`
- `rl` — `train`, `jobs`, `eval`, `promote`, `rollback`, `dataset`, `canary`
- `pref` — `collect`, `export`
- `import` (hidden) — `config`, `transcript` (sub: `upload`, `report`,
  `generate-agent`)

### Workbench group (via `cli/workbench.py`)
`workbench` group (`cli/workbench.py:383`) with subcommands: `status` (hidden),
`create`, `build`, `iterate`, `show`, `list`, `plan`, `apply`, `test`, `rollback`,
`cancel`, `save`, `bridge`.

### Target slash-command → Click-command map for the refactor
- `/eval` → `eval run` (and `eval show` / `eval list` for flags)
- `/optimize` → `optimize` (top-level) with `--cycles`, `--mode`
- `/build` → `workbench build` / `workbench save` / `workbench iterate`
- `/deploy` → `deploy` (confirm guard before invoking)
- `/skills` → `skill export-md`, `skill import-md`, plus `cli/skills.py` authoring
  surface; promoted to a full-screen `SkillsScreen`
- `/status` → `status` (already wired, upgrade to render via transcript)
- `/doctor` → `doctor`
- `/review` → `review list` / `review show`
- `/config` → `config list` / `config show` / `config set-active`
- `/model` → new session-local toggle over `provider list`; persists to session
  state, does not invoke Click today
- `/resume` → `session resume` (currently only prints metadata; upgrade to replay
  transcript)
- `/memory` → `memory show`

## 4. Key takeaways for the refactor

1. **Ten existing slash commands** → need nine net-new ones (`/eval`, `/optimize`,
   `/build`, `/deploy`, `/skills`, `/model`, `/clear`, `/new`, `/theme`).
2. **22 event renderers** already exist and are reusable — the missing piece is
   the nested block renderer (T08) plus `EffortIndicator` / `CtrlOToExpand`
   (T18b). Do not rewrite the line-renderers; wrap them.
3. **All business logic already lives in Click commands.** Slash handlers must
   stay thin, delegating via `CliRunner` (sync) or async subprocess (streaming).
   This is enforced by the execution rules in `PROMPT.md`.
4. **`/resume` is a stub today.** The T17 session-persistence task has to actually
   rehydrate transcript entries, not just print metadata.
5. **Free-text routing is heuristic and keyword-based** (`_route_free_text`).
   It's out of scope for the initial refactor, but the new app should preserve a
   fallback path for non-slash input so we don't regress.
