# Claude-Code Parity Deeper Integration

Date: 2026-04-14

Branch: `feat/claude-code-parity-deeper-integration-codex-ralph`

Prior branches reviewed:

- Claude Opus parity branch: `feat/claude-code-source-parity-claude-opus` at `9c8fca2dee40895a84ad9f27107c9317665478b7`
- Codex Ralph parity branch: `feat/claude-code-source-parity-codex-ralph` at `fbdb84b5ef11dc6c8e4ba2d0836d3e05e71450c6`

## Executive Summary

The two finished parity campaigns were complementary rather than redundant.
Claude Opus focused on terminal feel and operator confidence: permission-mode
symbols, bare `?` help, `/cost`, prompt history search, and effort
thinking/stall signals. Codex Ralph focused on the command system as a product
contract: richer command metadata, grouped/detail help, smarter completion,
unknown-command suggestions, session visibility, user-turn persistence, and
truthful footer activity.

This deeper integration adopts Codex Ralph's command metadata and discovery
spine as the base because it is the more durable AgentLab-native foundation.
It then layers in the strongest non-overlapping Claude Opus trust affordances:
permission-mode symbols/color roles, a transparent `/cost` command, effort
verb/stall state, and prompt-toolkit history search. It deliberately avoids
surface-only parity for `!`, `@`, `&`, `/tasks`, queues, transcript mode, or
custom statusline hooks because those need real execution semantics and safety
contracts before they should be shown to users.

## What Was Reviewed

### Claude Opus Report

Reviewed artifact:

- `feat/claude-code-source-parity-claude-opus:working-docs/reviews/2026-04-14-claude-code-source-parity-analysis.md`

The report audited a public Claude Code source mirror across the REPL, prompt
input subsystem, slash commands, spinners/status, permission modes, session
lifecycle, history search, help/onboarding, theme system, keyboard shortcuts,
cost tracking, markdown/diff rendering, and compact/context management.

The report concluded AgentLab already had a strong Claude-Code-like skeleton:
slash registry, autocomplete, permission modes, session persistence/resume,
banner, footer, effort indicator, collapsible output, double Ctrl-C exit,
onboarding, streaming commands, full-screen screens, transcript persistence,
cancellation, status bar, and a single-palette theme system.

Claude's high-priority gap list was:

- Permission mode symbols/icons instead of bare mode text.
- Empty-input `?` help trigger.
- Random goodbye messages.
- Thinking/stall status in the spinner.
- Ctrl-R history search.
- `/cost` command.

Claude's medium and low-priority deferred list included transcript mode/search,
prompt stash, multiple themes, token warnings, narrow/short terminal
adaptations, markdown rendering, message rewind, custom Ink fork, Rust diff
rendering, background sessions, voice/image paste, shimmer-only animation, and
speculative ghost text.

### Claude Opus Diff

Reviewed relevant diff from commit `9c8fca2dee40895a84ad9f27107c9317665478b7`.
The branch changed:

- `cli/permissions.py`
- `cli/workbench_app/app.py`
- `cli/workbench_app/effort.py`
- `cli/workbench_app/pt_prompt.py`
- `cli/workbench_app/slash.py`
- `cli/workbench_app/theme.py`
- `tests/test_claude_code_parity.py`
- `tests/test_workbench_app_stub.py`
- `tests/test_workbench_slash.py`

The implemented slice was terminal UX polish: mode display metadata, mode
formatting helpers, bare `?`, randomized goodbye messages, `/cost`, effort
stall state, and prompt-toolkit history support.

### Codex Ralph Report

Reviewed artifact:

- `feat/claude-code-source-parity-codex-ralph:working-docs/reviews/2026-04-14-codex-claude-code-source-parity-analysis.md`

The report's central thesis was that Claude Code's command metadata is not an
implementation detail. It is the user experience contract powering dispatch,
help, completion, safety routing, availability, source grouping, argument
hints, and onboarding. The report found AgentLab already had a typed command
taxonomy and prompt-toolkit completion, so the right adoption path was
incremental hardening rather than transplanting a new terminal UI.

Codex's remaining gap list was broader than what it implemented:

- No full input modes for `!` shell, `@` file/resource mentions, `&` background
  execution, or side-channel questions.
- No argument-level completion for `/resume <session_id>` or `/model <key>`.
- Footer/status activity was not backed by a central task/shell tracker.
- No Workbench `/tasks` surface.
- No visible command queue while the system is busy.
- No custom statusline hooks.
- Session history lacked Claude-style parent/child UUID chains, transcript
  filtering policy, export workflow, and cross-project/title search.
- Permission controls had no dedicated `/permissions` panel.
- Help/completion did not expose availability/enablement reasons.
- Terminal layout did not collapse hints dynamically by dimensions.

### Codex Ralph Diff

Reviewed relevant diff from commit `fbdb84b5ef11dc6c8e4ba2d0836d3e05e71450c6`.
The branch changed:

- `cli/workbench_app/commands.py`
- `cli/workbench_app/slash.py`
- `cli/workbench_app/completer.py`
- `cli/workbench_app/app.py`
- `cli/workbench_app/help_text.py`
- `cli/workbench_app/pt_prompt.py`
- `cli/workbench_app/build_slash.py`
- `cli/workbench_app/eval_slash.py`
- `cli/workbench_app/optimize_slash.py`
- `cli/workbench_app/deploy_slash.py`
- `cli/workbench_app/model_slash.py`
- `cli/workbench_app/skills_slash.py`
- `docs/cli/workbench.md`
- `tests/test_workbench_commands.py`
- `tests/test_workbench_completer.py`
- `tests/test_workbench_slash.py`
- `tests/test_workbench_app_stub.py`
- `tests/test_workbench_pt_prompt.py`

The implemented slice was command discovery and session honesty: metadata
fields, hidden-aware visible commands, source-grouped help, command detail
cards, ranked completion, unknown-command suggestions, `/shortcuts`, bare `?`,
`/sessions`, free-text persistence, truthful footer activity, and a visible
permission cycle that skips `dontAsk` while preserving compatibility.

## What Claude Got Right

Claude correctly identified that a Claude-Code-like workbench is not only a
command dispatcher. It must constantly reassure the operator about state:
current permission mode, whether the agent is thinking or stalled, how long a
run has taken, whether costs exist, and how to discover shortcuts without
already knowing `/help`.

The strongest Claude ideas were:

- Mode labels should be instantly scannable, not plain strings.
- `?` is a better first-help affordance than expecting new users to know
  `/help`.
- `/cost` should exist, but it must be honest when no cost data is available.
- Long-running work should distinguish ordinary thinking from missing progress.
- Prompt history search is a small but important power-user feature in a REPL.

Claude also made good deferral calls. Transcript mode, prompt stash, multiple
themes, markdown rendering, and message rewind are meaningful, but they are not
small parity patches. They require a more complete alternate-screen and
transcript navigation model.

## What Codex Got Right

Codex correctly identified the command registry as the leverage point. AgentLab
already had a typed local/local-jsx/prompt command taxonomy, so command
metadata could improve help, completion, docs, safety labeling, and future
availability logic without changing the core Workbench architecture.

The strongest Codex ideas were:

- Add `argument_hint`, `when_to_use`, `hidden`, `immediate`, and `sensitive`
  to command metadata.
- Keep hidden commands dispatchable but out of broad discovery.
- Make `/help` source-grouped and make `/help <command>` a real detail card.
- Rank completion over aliases and descriptive text, not only prefixes.
- Add unknown-command suggestions.
- Fulfill the startup banner's `? for shortcuts` promise.
- Add `/sessions [count]` using the existing `SessionStore`.
- Persist free-text user turns so resume is truthful.
- Replace fake footer counters with `idle` unless real counters exist.
- Avoid fake queues, fake tasks, or fake shell/file/background modes.

## Overlap Versus Complementarity

The overlap was small and useful:

- Both branches saw `?` help as important.
- Both branches touched permission-mode visibility.
- Both branches touched app-loop footer behavior.
- Both branches changed slash command tests.

The complementarity was larger:

- Claude supplied terminal-state trust features.
- Codex supplied the command metadata/discovery architecture.
- Claude's `/cost` work fit naturally into Codex's richer slash registry.
- Claude's mode symbols fit naturally into Codex's simpler visible permission
  cycle.
- Claude's effort stall state fit the existing pure `EffortIndicator` state
  machine without requiring new UI machinery.

The deeper integration should therefore not be a stacked merge. The coherent
landing is: metadata teaches the command surface, sessions become truthful, and
the prompt/footer/effort chrome makes state legible.

## Deeper Remaining Gaps

After both prior runs and this integration, the main remaining Claude-Code-like
gaps are:

1. Real input modes for `!`, `@`, and `&`, backed by execution, file/resource
   resolution, permissions, and docs.
2. Argument-level completion for known commands such as `/resume <session_id>`,
   `/model <provider/model>`, `/eval --config`, and file/path arguments.
3. A central task/shell tracker feeding footer state, status, cancellation,
   and a future `/tasks` surface.
4. A visible command queue while the system is busy, but only once the loop can
   safely accept and replay queued input.
5. Custom statusline hooks with a stable context schema and safe execution
   policy.
6. Transcript mode with search and navigation.
7. Session export/search, transcript filtering/redaction policy, and possibly
   parent/child session chains.
8. Dedicated permission management inside Workbench, such as `/permissions`.
9. Availability/enablement metadata in help and completion.
10. Terminal-density adaptations for narrow or short terminals.
11. Context/token warning surfaces once the model layer exposes current usage.
12. Terminal markdown rendering for model answers.

## Implemented Now

### Command Metadata And Discovery

Implemented in:

- `cli/workbench_app/commands.py`
- `cli/workbench_app/completer.py`
- `cli/workbench_app/slash.py`
- `cli/workbench_app/build_slash.py`
- `cli/workbench_app/eval_slash.py`
- `cli/workbench_app/optimize_slash.py`
- `cli/workbench_app/deploy_slash.py`
- `cli/workbench_app/model_slash.py`
- `cli/workbench_app/skills_slash.py`

What changed:

- Added `argument_hint`, `when_to_use`, `hidden`, `immediate`, and `sensitive`
  metadata to command definitions.
- Added `CommandRegistry.visible()`.
- Made `match_prefix()` and `help_table()` hidden-aware.
- Added source-grouped `/help`.
- Added `/help <command>` detail cards.
- Added ranked completion across command names, aliases, descriptions,
  argument hints, usage text, source, and conservative fuzzy matches.
- Added richer completion metadata with argument hints, aliases, and source.
- Added unknown-command suggestions.
- Added metadata to the workflow command factories.

Why now:

This is the best foundation for future Claude-Code-like behavior. It improves
daily usability now and gives later work a structured place to hang
availability, argument completion, and safety semantics.

### Shortcut And Session Surfaces

Implemented in:

- `cli/workbench_app/help_text.py`
- `cli/workbench_app/app.py`
- `cli/workbench_app/slash.py`
- `docs/cli/workbench.md`

What changed:

- Added shared shortcut help.
- Added `/shortcuts` and `/?`.
- Added bare `?` handling in the app loop.
- Added `/sessions [count]`.
- Persisted non-slash free-text user turns.
- Kept persistence best-effort so read-only or partial embedder contexts do
  not crash the REPL.
- Bound missing session, store, workspace, and registry fields onto partial
  `SlashContext` objects so embedders can pass only the pieces they customize.

Why now:

The startup banner already promised `? for shortcuts`, and sessions were
already durable. These changes make existing promises real rather than adding
new surfaces.

### Truthful Footer Activity And Permission Chrome

Implemented in:

- `cli/permissions.py`
- `cli/workbench_app/theme.py`
- `cli/workbench_app/app.py`
- `cli/workbench_app/pt_prompt.py`

What changed:

- Added permission-mode display metadata.
- Added mode color helpers and `theme.format_mode()`.
- Updated footer and prompt toolbar labels.
- Changed footer activity from hardcoded `0 shells, 0 tasks` to `idle` unless
  real counters are provided through `SlashContext.meta`.
- Added active shell/task counter rendering when supplied.
- Added visible shift-tab cycle:
  `default -> acceptEdits -> plan -> bypass -> default`.
- Preserved `dontAsk` as a loadable settings value that cycles back to
  `default`.
- Added prompt-toolkit history and `enable_history_search=True` for Ctrl-R.

Why now:

This resolves a trust problem. The footer should not pretend to know shell/task
counts it does not have, and the permission mode should be legible at a glance.

### Cost And Effort State

Implemented in:

- `cli/workbench_app/slash.py`
- `cli/workbench_app/effort.py`

What changed:

- Added `/cost`.
- `/cost` renders recorded totals from `ctx.meta["cost"]` if present.
- `/cost` explicitly says no cost data is recorded when the session has none.
- `/cost` tolerates JSON-ish numeric strings for cost/token/duration metrics
  while still surfacing malformed values as command errors instead of crashing
  the loop.
- Added `DEFAULT_STALL_SECONDS`, `EffortSnapshot.verb`,
  `EffortSnapshot.stalled`, `EffortIndicator.set_verb()`,
  `EffortIndicator.record_progress()`, and `EffortIndicator.stalled`.
- `format_effort()` now renders the verb and warning-colors stalled snapshots.

Why now:

These are small trust features that fit existing primitives. They do not
pretend AgentLab has complete provider accounting or a central task tracker
yet.

## Deliberately Not Implemented Now

- Random goodbye messages: low product value and not part of the coherent
  discovery/trust spine.
- Transcript mode/search: requires alternate-screen navigation and search
  semantics.
- Prompt stash: useful, but not as important as session persistence and command
  discovery.
- Multiple themes: requires a broader accessibility and palette strategy.
- Token/context warnings: blocked on reliable model context usage data.
- Markdown rendering: should be added when terminal model-response rendering is
  the target, not as a command-discovery patch.
- Message rewind/selector: needs conversation indexing and mutation semantics.
- `!`, `@`, `&`, and side-channel input modes: should not be shown until they
  have execution, resource lookup, permissions, and tests.
- `/tasks`: should wait for a central task/shell tracker.
- Command queue: should wait for real busy-state queue semantics.
- Custom statusline hooks: needs a stable schema and hook safety policy.
- Argument-level completion: valuable follow-up, but should be command-specific
  rather than a global string hack.

## Validation

TDD red path:

- `.venv/bin/pytest ...` initially failed because no project venv existed.
- `python3 -m pytest ...` failed under system Python 3.9 because AgentLab
  requires Python >=3.11 and imports `tomllib`.
- `/opt/homebrew/bin/python3 -m pytest ...` failed because that interpreter did
  not have `prompt_toolkit`.
- `uv run --extra dev python -m pytest ...` created a project `.venv`, installed
  dev dependencies, and produced expected collection failures for missing new
  implementation symbols before the production code was added.

Final green path:

```bash
uv run --extra dev python -m compileall cli/workbench_app cli/permissions.py
git diff --check
uv run --extra dev python -m pytest tests/test_workbench_commands.py tests/test_workbench_completer.py tests/test_workbench_slash.py tests/test_workbench_app_stub.py tests/test_workbench_pt_prompt.py tests/test_workbench_effort.py tests/test_workbench_theme.py -q
uv run --extra dev python -m pytest tests/test_workbench_*.py tests/test_cli_workbench.py tests/test_cli_permissions.py tests/test_cli_usage.py tests/test_cli_commands.py -q
uv run --extra dev python -m pytest tests/test_cli_*.py tests/test_workbench_*.py tests/test_cost_tracker.py -q
```

Result:

- `compileall`: clean.
- `git diff --check`: clean.
- Touched-file tests: `219 passed in 0.27s`.
- Related Workbench/CLI suite: `736 passed, 2 warnings in 108.62s`.
- Broader relevant CLI/Workbench/cost suite: `920 passed, 2 warnings in
  124.79s`.
- The two warnings are the existing `--classic` entry path
  `DeprecationWarning` from `runner.py:2200`.

Skeptic pass:

- A read-only skeptic agent reviewed the final diff and found no blocking
  issues.
- Two non-blocking observations were addressed before commit:
  `/cost` now accepts numeric strings, and partial slash contexts inherit
  missing loop session bindings.

## Residual Risks

- Command metadata flags such as `sensitive`, `immediate`, and `hidden` are
  descriptive in this slice. They do not yet enforce safety or availability.
- Free-text persistence records the operator's raw input. This is correct for
  resumable sessions, but future export/redaction policy should account for it.
- `/cost` depends on future model/tool runners populating `ctx.meta["cost"]`.
  It is honest today, but mostly empty until those call sites wire data in.
- Effort stall detection only knows about explicit `record_progress()` calls.
  Callers must invoke it when tokens/output arrive to avoid false stall state.
- Footer activity counters are only rendered when supplied. A central tracker
  is still needed before the footer can be authoritative during every workflow.
- Completion ranking is conservative but still heuristic. As command count
  grows, ranking should be reviewed against real usage.

## Follow-Up Opportunities

Priority order:

1. Add command-specific argument completion for `/resume`, `/model`, `/eval`,
   `/build`, and path-bearing commands.
2. Build a central shell/task tracker and feed footer, cancellation, status, and
   a future `/tasks` command from it.
3. Add real `!` shell mode with permission gates and transcript persistence.
4. Add `@` file/resource mentions with path traversal checks and completion.
5. Add command queue semantics while busy.
6. Add `/permissions` panel/detail command using the existing permission
   manager.
7. Add statusline hooks after defining a safe context schema.
8. Add transcript mode/search after the prompt shell supports alternate-screen
   state cleanly.
9. Add context/token warning surfaces when model usage data is reliable.
10. Add terminal markdown rendering for model responses.
