# PROMPT: AgentLab CLI Workbench → Claude Code UX Refactor

## Mission
Turn the AgentLab CLI workbench into a Claude-Code-style interactive terminal app. Users
should be able to `/eval`, `/optimize`, `/build`, `/deploy`, manage skills, and watch the
harness stream progress live — all from one persistent REPL. This becomes the default
`agentlab` entry point.

## Repository
- Work in: `/Users/andrew/Desktop/agentlab`
- Base branch: `feat/cli-live-first-and-loading`
- Create a feature branch: `refactor/workbench-claude-code-ux`
- Never commit to `main`. Use conventional commits (`feat:`, `refactor:`, `test:`, `docs:`).

## Key files to know before touching anything
- `runner.py` — top-level Click CLI; this is where the default entry point change lands.
- `cli/workbench.py` (948 lines) — existing workbench Click group. Do NOT rewrite; the
  new interactive app delegates into these commands.
- `cli/workbench_render.py` (385 lines) — 30+ event renderers. Reuse and extend.
- `cli/repl.py` (271 lines) — current non-interactive shell. Extract slash handlers.
- `cli/skills.py` (925 lines) — skill management surface for `/skills`.
- `cli/sessions.py` — session persistence; every transcript entry goes here.
- `builder/workbench.py` — WorkbenchService + event stream source of truth.

## Reference material
- Claude Code docs: https://code.claude.com/docs/en/how-claude-code-works
- Source reference: https://github.com/yasasbanukaofficial/claude-code
- User-provided screenshots of the Claude Code transcript and tool-call blocks.

## Execution rules
- Follow `PLAN.md` in order. Each task is one Ralph iteration.
- Mark tasks `[x]` when complete. Re-run the relevant test subset after each task.
- If a task fails 3 times, STOP and write the failure details to
  `working-docs/workbench-refactor/BLOCKERS.md`.
- Every new module needs at least one test file. Every bugfix needs a regression test.
- No `any` / untyped dict blobs in new code — use dataclasses or TypedDicts for events.
- Keep slash-command handlers thin — they delegate to existing Click commands via
  `CliRunner` or async subprocess. No duplicated business logic.
- Respect existing conventions: Click for CLI, `click.style` for color, stream-json
  envelope format (`cli/json_envelope.py`).

## Definition of done
- `agentlab` with no args launches the new workbench app.
- `/help` lists every slash command with one-line help.
- `/eval`, `/optimize`, `/build`, `/deploy`, `/skills` all stream live progress.
- Status line updates reactively (workspace, config version, model, score, pending reviews).
- Ctrl-C cancels the active tool call; second press exits cleanly.
- Session persists transcript; `/resume` restores it.
- Full test suite passes (`pytest`, `ruff check`).
- README + AGENTLAB.md updated; old `cli/repl.py` either shimmed or deprecated.
