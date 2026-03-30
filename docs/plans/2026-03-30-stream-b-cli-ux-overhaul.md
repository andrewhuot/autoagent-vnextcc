# Stream B CLI UX Overhaul Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement Stream B of the AutoAgent CLI UX overhaul: permissions, memory v2, progress/events, MCP runtime management, usage/budget surfaces, model controls, and the six quick wins in a way that fits the existing V2 command structure.

**Architecture:** Add new focused CLI/core modules for settings-backed behavior and keep `runner.py` as the integration layer. Reuse existing runtime config, workspace discovery, JSON envelope helpers, and cost/memory stores, while introducing `.autoagent/settings.json`, `.mcp.json`, and layered project memory as first-class workspace state.

**Tech Stack:** Python, Click CLI, Pydantic runtime config, SQLite-backed cost/memory stores, pytest, JSON/YAML workspace artifacts.

---

### Task 1: Add regression tests for settings, permissions, and layered memory

**Files:**
- Create: `tests/test_cli_permissions.py`
- Create: `tests/test_project_memory_v2.py`
- Modify: `tests/test_project_memory.py`

**Step 1: Write failing tests for permissions**

Cover:
- default mode asks for risky actions and config writes
- `acceptEdits` auto-allows local writes but still asks for deploy/MCP
- `dontAsk` auto-allows actionable operations
- settings rules override the mode defaults
- plan mode denies writes

**Step 2: Run the new permissions tests to verify they fail**

Run: `pytest tests/test_cli_permissions.py -q --tb=short`
Expected: FAIL because `cli/permissions.py` and settings-backed rule evaluation do not exist yet

**Step 3: Write failing tests for layered memory**

Cover:
- loader merges `AUTOAGENT.md`, `AUTOAGENT.local.md`, `.autoagent/rules/*.md`, and `.autoagent/memory/*.md`
- memory commands expose `list`, `where`, `edit`, and `summarize-session`
- status/doctor-facing snapshot contains active file metadata

**Step 4: Run the project memory tests to verify they fail**

Run: `pytest tests/test_project_memory.py tests/test_project_memory_v2.py -q --tb=short`
Expected: FAIL because the layered loader and new command surfaces are not implemented

### Task 2: Add regression tests for progress, MCP runtime, usage, model, and JSON/error UX

**Files:**
- Create: `tests/test_cli_progress.py`
- Create: `tests/test_mcp_runtime.py`
- Create: `tests/test_cli_usage.py`
- Create: `tests/test_cli_model.py`
- Modify: `tests/test_json_flags.py`
- Modify: `tests/test_cli_ux_refactor_v2.py`

**Step 1: Write failing tests for progress rendering**

Cover:
- text renderer emits consistent phase and next-action lines
- JSON and stream-json render the same event payload shape
- commands using `--output-format json|stream-json` emit the expected envelope/event records

**Step 2: Write failing tests for MCP runtime**

Cover:
- `mcp list/add/remove/status/inspect`
- `.mcp.json` workspace file read/write behavior
- `mcp init` remains working

**Step 3: Write failing tests for usage and model surfaces**

Cover:
- `usage` reports last eval/optimize, cumulative spend, configured budget, and remaining budget
- `optimize` and `loop` accept `--max-budget-usd`
- `model list/show/set proposer/set evaluator` read and write `.autoagent/settings.json`

**Step 4: Write failing tests for quick wins**

Cover:
- `doctor --json` returns `{status, data, next}`
- `status`, `eval run`, `explain`, `diagnose`, and `replay` all use the standard envelope
- missing workspace/config import/credentials routes mention `autoagent doctor`
- interactive `edit` and `diagnose` help text shows workspace and quit hints

**Step 5: Run targeted UX tests to verify they fail**

Run: `pytest tests/test_cli_progress.py tests/test_mcp_runtime.py tests/test_cli_usage.py tests/test_cli_model.py tests/test_json_flags.py tests/test_cli_ux_refactor_v2.py -q --tb=short`
Expected: FAIL on the newly asserted behaviors

### Task 3: Implement settings, permissions, output/error helpers, and memory v2

**Files:**
- Create: `cli/permissions.py`
- Create: `cli/errors.py`
- Create: `cli/output.py`
- Modify: `cli/workspace.py`
- Modify: `core/project_memory.py`
- Modify: `runner.py`

**Step 1: Implement workspace settings helpers and permission evaluation**

Add:
- settings loader/writer around `.autoagent/settings.json`
- mode defaults for `plan`, `default`, `acceptEdits`, `dontAsk`, `bypass`
- action classifiers for `config.write`, `memory.write`, `deploy.canary`, `deploy.immediate`, `review.apply`, `mcp.install`, `mcp.write`

**Step 2: Implement common error and output helpers**

Add:
- standard JSON/text output helpers for `text|json|stream-json`
- recovery-oriented error rendering with doctor suggestions

**Step 3: Evolve project memory to layered context**

Add:
- merged context snapshot
- active source list
- memory directory helpers
- session summary writer
- compatibility path for legacy `ProjectMemory.load()/save()/add_note()`

**Step 4: Run the targeted tests and make them pass**

Run:
- `pytest tests/test_cli_permissions.py -q --tb=short`
- `pytest tests/test_project_memory.py tests/test_project_memory_v2.py -q --tb=short`

### Task 4: Implement progress, MCP runtime, usage, and model modules

**Files:**
- Create: `cli/progress.py`
- Create: `cli/mcp_runtime.py`
- Create: `cli/usage.py`
- Create: `cli/model.py`
- Modify: `runner.py`
- Modify: `cli/mcp_setup.py` only if needed for group integration without regressing `mcp init`

**Step 1: Implement shared progress events and renderers**

Add event types:
- `phase_started`
- `phase_completed`
- `artifact_written`
- `warning`
- `error`
- `next_action`

**Step 2: Implement MCP runtime management**

Add workspace `.mcp.json` loader/writer and commands:
- `mcp list`
- `mcp add`
- `mcp remove`
- `mcp status`
- `mcp inspect`

**Step 3: Implement usage and budget surfaces**

Add:
- usage snapshot builder using eval result JSON files and `CostTracker`
- `--max-budget-usd` handling for `optimize` and `loop`

**Step 4: Implement model surface**

Add:
- effective proposer/evaluator resolution from runtime config plus workspace settings overrides
- `model list`, `model show`, `model set proposer`, `model set evaluator`

**Step 5: Run targeted tests and make them pass**

Run:
- `pytest tests/test_cli_progress.py tests/test_mcp_runtime.py tests/test_cli_usage.py tests/test_cli_model.py -q --tb=short`

### Task 5: Wire runner commands to new modules and finish quick wins

**Files:**
- Modify: `runner.py`
- Modify: `cli/status.py`

**Step 1: Wire status and doctor**

Add:
- memory/MCP/usage/model data to status
- `doctor --json`
- doctor suggestion routing in common failure cases

**Step 2: Wire JSON envelope standardization**

Update:
- `status`
- `eval run`
- `explain`
- `diagnose`
- `replay`

**Step 3: Wire permissions into risky actions**

Update:
- `deploy`
- `full-auto`
- `review apply`
- any config/MCP writing flows touched by the new commands

**Step 4: Wire progress events into long-running commands**

Update:
- `build`
- `eval run`
- `optimize`
- `loop`
- `deploy`
- `review apply`

**Step 5: Improve interactive prompts**

Update:
- `edit --interactive`
- `diagnose --interactive`

**Step 6: Run UX-focused tests and make them pass**

Run:
- `pytest tests/test_json_flags.py tests/test_cli_ux_refactor_v2.py -q --tb=short`

### Task 6: Final verification, diff review, commit, and notify

**Files:**
- Modify: any changed Python/tests/docs files from prior tasks

**Step 1: Run Python compilation on changed files**

Run: `python -m py_compile runner.py cli/*.py core/project_memory.py tests/test_cli_permissions.py tests/test_project_memory_v2.py tests/test_cli_progress.py tests/test_mcp_runtime.py tests/test_cli_usage.py tests/test_cli_model.py`

**Step 2: Run the requested full test suite**

Run: `pytest tests/ -q --tb=short --ignore=tests/test_skills_routes.py --ignore=tests/test_builder_chat_api.py --ignore=tests/test_quickfix_api.py --ignore=tests/test_skills_api_integration.py --ignore=tests/test_api_route_aliases.py`

**Step 3: Review the diff**

Run:
- `git status --short`
- `git diff --stat`
- `git diff -- runner.py cli core tests`

**Step 4: Commit**

Run:
- `git add runner.py cli core tests docs/plans/2026-03-30-stream-b-cli-ux-overhaul.md`
- `git commit -m "feat(stream-b): permissions, progress, mcp-runtime, usage, model, memory-v2, quick-wins"`

**Step 5: Send completion event**

Run:
- `openclaw system event --text "Done: Stream B complete — permissions, progress/events, MCP runtime, usage/budget, model surface, memory v2, 6 quick wins. Tests: [X passed]" --mode now`
