# P0 Handoff — Settings cascade + hook contract

Paste the block below into a fresh Claude Code session at the repo root (`/Users/andrew/Desktop/agentlab`).

**Prerequisites:**
- None. P0 is the foundation phase. Runs first.
- Parity work from Phases 3-7 (prior parity roadmap, merged on master) is assumed in place: TUI default-on, permission overlay, SQLite TaskStore, `/loop`, daemon, `/doctor` sections, `cli/hooks/` package scaffold (registry.py + types.py), `cli/settings.py` flat dotted-key store, `cli/permissions.py` rule-based gate.

**What this unlocks:** P0.5 (provider parity — reads API keys + model defaults from `Settings`), P1 (streaming dispatch — fires `beforeTool`/`afterTool` from the new hook contract), P3 (classifier — persists "always" decisions to settings), P4 (sessions — reads `Settings.sessions.root`). Everything after P0 depends on the cascade and hook events shipping first.

---

## Session prompt

You are picking up the AgentLab Claude-Code-parity roadmap at **P0 — Settings cascade + hook contract**. The roadmap lives at `docs/plans/2026-04-17-claude-code-parity-roadmap-v2.md`. P0 is the foundation phase; six phases follow.

### Your job

Ship **P0** following subagent-driven TDD:

- Fresh subagent per task with full task text + code in the dispatch prompt.
- Each subagent uses `.venv/bin/python -m pytest` (project requires Python 3.11).
- Every task: failing test → minimal impl → passing test → conventional commit.
- Mark TodoWrite tasks complete immediately; don't batch.
- Verify line numbers and function signatures with `Read` before dispatching — don't trust stale references.

### P0 goal

Single source of truth for permissions, env, model defaults, and lifecycle hooks. Three-layer deep-merge cascade (`/etc/agentlab/settings.json` → `~/.agentlab/settings.json` → `<project>/.agentlab/settings.json`), with environment variables taking precedence for back-compat. Wire the existing `cli/hooks/` scaffold to actually fire on turn and tool lifecycle events.

**Reference shape (read for architectural inspiration, do NOT copy code):**
- Claude Code settings loader: `/Users/andrew/Desktop/claude-code-main/src/utils/permissions/permissionsLoader.ts`
- Claude Code hooks contract: `/Users/andrew/Desktop/claude-code-main/src/services/tools/toolHooks.ts`
- Claude Code hook events: `beforeQuery`, `afterQuery`, `PreToolUse`, `PostToolUse`, `SubagentStop`, `SessionEnd`. Mirror the payload shape so users with both tools can share hook scripts.

### Before dispatching anything

1. **Read the roadmap P0 section** at `docs/plans/2026-04-17-claude-code-parity-roadmap-v2.md` — the "P0" subsection.

2. **Ground-truth the current code** (the summary in the roadmap may drift):
   - `cli/settings.py` — existing `ResolvedSettings` dataclass, `DEFAULTS`, `_deep_merge`, `USER_CONFIG_PATH`, `PROJECT_SETTINGS_FILENAME`, `LOCAL_SETTINGS_FILENAME`. This file **already exists**; P0 extends it into a package, not creates it from zero.
   - `cli/hooks/registry.py` + `cli/hooks/types.py` — existing `HookRegistry`, `HookDefinition`, `HookEvent`, `HookOutcome`, `HookVerdict`, subprocess runner. Already functional for subprocess dispatch; P0 wires it into lifecycle events.
   - `cli/permissions.py` — existing `PermissionManager` consulted by `cli/tools/executor.py::execute_tool_call`.
   - `cli/llm/orchestrator.py` — existing turn loop (`LLMOrchestrator.run_turn`) that already integrates hooks + permissions + sessions at the dispatch level.
   - `cli/tools/executor.py::execute_tool_call` — where `beforeTool`/`afterTool` will fire.
   - `tests/test_system_prompt.py` — snapshot test that **must stay byte-stable**.
   - `cli/workbench_app/app.py` — `AGENTLAB_NO_TUI` env-var gate. Must keep working.

3. **Write a TDD expansion plan** at `docs/plans/2026-04-17-p0-settings-hooks-tdd.md`. Use R1's plan shape as the template — exact file paths, code in each step, exact pytest commands. Commit the plan alone (`docs: expand P0 TDD plan`) before any code.

### P0 scope — tasks

Split into five tasks, dispatch one subagent per task:

**P0.1 — Settings package + schema (pydantic model).**
- Promote `cli/settings.py` to a package: `cli/settings/__init__.py` re-exports the public surface so existing imports (`from cli.settings import ...`) keep working.
- Create `cli/settings/schema.py` — pydantic `Settings` model with sub-models: `Permissions`, `Hooks`, `Providers`, `Sessions`, `Paste`, `Input`, `MCP`. Every field has a default so an empty `settings.json` is valid.
- Create `cli/settings/loader.py` — `load_settings(workspace_root) -> Settings` that reads the three layers and deep-merges.
- Deprecation shim: `ResolvedSettings.get("dotted.key")` keeps returning flat-dict values by calling `getattr` through the pydantic tree. Add a deprecation warning log line.
- Tests: `tests/test_settings_cascade.py` — table-driven merge cases (defaults only, user override, project override, local override, partial overlap, list replacement vs merge).

**P0.2 — Environment-variable bridge.**
- Create `cli/settings/env_bridge.py` — reads legacy env vars (`AGENTLAB_NO_TUI`, `AGENTLAB_EXPOSE_SLASH_TO_MODEL`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `GEMINI_API_KEY`) and projects them onto the `Settings` tree at load time. Precedence: **env > project settings > user settings > defaults**. This is critical for back-compat — every existing env-var user keeps working.
- Tests: `tests/test_settings_env_bridge.py` — every documented env var lifts to the expected field; absent env vars leave settings untouched.

**P0.3 — Hook contract + lifecycle events.**
- Extend `cli/hooks/types.py::HookEvent` with all Claude-Code-parity events: `BEFORE_QUERY`, `AFTER_QUERY`, `PRE_TOOL_USE`, `POST_TOOL_USE`, `SUBAGENT_STOP`, `SESSION_END`. Keep existing event names as aliases for back-compat.
- Modify `cli/hooks/registry.py` — add a `load_from_settings(settings: Settings) -> HookRegistry` constructor that reads `Settings.hooks` (map of event → list of command definitions).
- Per-hook timeout (default 5s, configurable via `Settings.hooks.timeout_seconds`). A misbehaving hook logs stderr and returns a `TIMEOUT` verdict; it must **not** wedge the turn.
- Tests: `tests/test_hooks_lifecycle.py` — fire/don't-fire matrix, timeout, denial aborts tool call, stderr surfacing.

**P0.4 — Orchestrator + executor wiring.**
- Modify `cli/llm/orchestrator.py::LLMOrchestrator.run_turn` to fire `BEFORE_QUERY` before the first model call and `AFTER_QUERY` after the final one. A `BEFORE_QUERY` denial aborts the turn before any model call.
- Modify `cli/tools/executor.py::execute_tool_call` to fire `PRE_TOOL_USE` before dispatch and `POST_TOOL_USE` after the tool returns. A `PRE_TOOL_USE` denial is a first-class tool-result error ("denied by hook: <name>"). `POST_TOOL_USE` can mutate the tool result (same pattern as Claude Code's `toolHooks.ts`).
- Honor a returned "ask" verdict by falling through to the existing permission prompt (so a hook can escalate rather than outright deny).
- Tests: `tests/test_orchestrator_hooks.py` — fake `ModelClient`, fake tool, fake hook registry; assert event order, denial aborts, mutation passes through.

**P0.5 — Migration + `/doctor` integration.**
- Add `/migrate-settings` slash command in `cli/workbench_app/slash.py` that writes the new `settings.json` from the current flat-dict values and archives the old file to `settings.json.bak`.
- Extend `cli/doctor_sections.py` with `settings_section(settings: Settings) -> dict` — reports which layers loaded, which env vars overrode, which hooks are registered. Wire into `agentlab doctor` and the TUI doctor screen.
- Tests: `tests/test_doctor_sections.py` gets new cases for `settings_section`.

### Critical invariants P0 must preserve

- **Snapshot stability.** `tests/test_system_prompt.py` must pass byte-for-byte after every commit. Any new system-prompt fields get `None` defaults.
- **`AGENTLAB_NO_TUI=1` continues to work.** CI and pipe-only sessions must not regress.
- **Existing `Settings.get("dotted.key")` call sites must keep working.** Deprecation warning is fine; hard break is not.
- **Hook timeouts never wedge the turn.** Default 5s; a hung hook returns a TIMEOUT verdict, logs, moves on.
- **Env > settings precedence.** A user with `ANTHROPIC_API_KEY` in their shell but nothing in `settings.json` must still authenticate.
- **Zero-breakage for users with no `settings.json`.** An empty workspace behaves identically to today.

### Workflow

1. Create a new worktree:
   `git worktree add .claude/worktrees/p0-settings-hooks -b claude/cc-parity-p0 master`
2. Follow `superpowers:subagent-driven-development` — one subagent per task, don't implement in the main thread.
3. After each task, run `.venv/bin/python -m pytest tests/` and confirm snapshot test still passes.
4. After P0.5 lands, offer to open a PR before moving to P0.5 (provider parity) — the next handoff.

### If you get stuck

- `cli/settings.py` is imported in many places (grep to find them). Keep the module-level constants (`DEFAULTS`, `USER_CONFIG_DIR`, etc.) re-exported from `cli/settings/__init__.py` so no downstream import breaks.
- Hook payload shape differs from Claude Code subtly — prefer matching their JSON keys (`tool_name`, `tool_input`, `tool_response`, `stop_reason`) so shared hook scripts work. See `claude-code-main/src/services/tools/toolHooks.ts` for the exact shape.
- Pydantic v2 syntax — check `pyproject.toml` pins `pydantic>=2.0`. Use `BaseModel` + `model_config = ConfigDict(extra="forbid")` so typos in user settings.json surface as errors.
- The orchestrator already has a lot going on — read `run_turn` top to bottom before editing. The new hook calls go at specific places: top of `run_turn` (BEFORE_QUERY), bottom of `run_turn` return path (AFTER_QUERY), and inside the tool-dispatch loop (PRE/POST_TOOL_USE).
- If a test fails because of migration behavior (users with old flat `config.json`), consult `USER_CONFIG_PATH` in `cli/settings.py` — there's a legacy path that needs handling.

### Anti-goals (things NOT to build in P0)

- Do not touch provider adapters (`cli/llm/providers/*.py`). That is P0.5.
- Do not add streaming tool dispatch. That is P1.
- Do not add a transcript classifier. That is P3.
- Do not build session JSONL. That is P4.
- Do not rewrite the `agentlab doctor` Click command — only extend `cli/doctor_sections.py` with new pure-data builders.

### First action

After the user confirms they want to start P0, read the P0 section of `docs/plans/2026-04-17-claude-code-parity-roadmap-v2.md`, read the six files named under "Ground-truth the current code", write the TDD expansion plan, commit it, then dispatch P0.1 as the first subagent.

Use superpowers and TDD. Work in subagents. Be specific.
