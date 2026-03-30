# Claude Code UX Analysis for AutoAgent CLI

Date: 2026-03-30

This brief compares Claude Code's CLI UX to AutoAgent's current workspace-first CLI and recommends the highest-leverage changes for making AutoAgent feel more coherent, safer, and faster to use.

Method:
- Claude Code research from Anthropic primary sources: overview, CLI reference, interactive mode, memory, settings, permissions, permission modes, MCP, headless mode, checkpointing, and Anthropic product/blog pages.
- AutoAgent analysis from `README.md`, `docs/QUICKSTART_GUIDE.md`, `runner.py`, and the `cli/` modules.

High-level conclusion:
- AutoAgent is already strong on durable workspace artifacts, config versioning, and operational surfaces.
- Claude Code feels better because it is session-first, permission-aware, and discoverable inside the terminal.
- The main product move is not "copy Claude Code's commands." It is "wrap AutoAgent's existing capabilities in a unified interactive shell with memory, permissions, resumability, and a clean scripting story."

## Section 1: Claude Code UX Patterns Worth Adopting

### 1. First-run experience

- What Claude Code does:
  Bare `claude` is the main entry point. The official docs position the first run as: install, `cd` into your project, run `claude`, and log in when prompted. CLI reference also exposes explicit auth commands such as `claude auth login` and `claude auth status`.
- Why it works:
  It reduces early decision load. Users do not have to understand the command tree before they get value.
- AutoAgent today:
  Bare `autoagent` prints help and exits instead of launching a guided flow (`runner.py:958-971`). First-run success currently depends on the user knowing `autoagent init`, then `autoagent status`, then another command (`runner.py:985-1078`, `README.md:15-22`, `docs/QUICKSTART_GUIDE.md:45-79`).
- How AutoAgent should adopt it:
  Make bare `autoagent` the smart launcher.
- Specific implementation recommendation:
  Change the root `cli()` behavior so:
  1. If running in a TTY with no workspace, launch a guided onboarding flow with two choices: `Create demo workspace` or `Create empty workspace`.
  2. If running in a TTY inside a workspace, enter the interactive shell.
  3. If running non-interactively, preserve current help behavior.
  Files: `runner.py`, new `cli/repl.py`, new `cli/onboarding.py`, `cli/workspace.py`, `docs/QUICKSTART_GUIDE.md`, `README.md`.
- Priority:
  P0

### 2. Project context

- What Claude Code does:
  Claude Code uses project-scoped context files and directories: `CLAUDE.md`, `.claude/rules/`, `.claude/settings.json`, `.mcp.json`, plus project auto-memory under `~/.claude/projects/...`.
- Why it works:
  The model always has a consistent place to look for project instructions and local behavior.
- AutoAgent today:
  AutoAgent creates `AUTOAGENT.md` and `.autoagent/workspace.json` during bootstrap (`cli/bootstrap.py:228-243`, `cli/workspace.py:21-200`). This is a good foundation, but context is still mostly one file plus workspace metadata.
- How AutoAgent should adopt it:
  Evolve `AUTOAGENT.md` into a full context hierarchy instead of a single memory file.
- Specific implementation recommendation:
  Support:
  1. `AUTOAGENT.md` as the shared project brief.
  2. `AUTOAGENT.local.md` for personal, unshared overrides.
  3. `.autoagent/rules/*.md` for focused instruction packs.
  4. `.autoagent/settings.json` for CLI behavior.
  5. `.autoagent/memory/` for generated summaries and last-session notes.
  Add a loader that merges these and exposes the active set in `autoagent status`, `autoagent doctor`, and the future shell.
  Files: `cli/bootstrap.py`, `cli/workspace.py`, `core/project_memory.py`, `runner.py`.
- Priority:
  P0

### 3. Interactive REPL mode

- What Claude Code does:
  The default product is an interactive terminal session, not a subcommand zoo. Users can ask for work, inspect context, change modes, and keep going in one place.
- Why it works:
  It preserves flow. Users stay in one mental model instead of constantly remembering command names.
- AutoAgent today:
  AutoAgent is command-per-invocation. It has isolated interactive shells for `edit --interactive` and `diagnose --interactive` (`runner.py:6251-6320`, `runner.py:6514-6556`), but no unified session shell.
- How AutoAgent should adopt it:
  Add a single workspace shell that routes free text and slash commands into existing workflows.
- Specific implementation recommendation:
  Create `autoagent shell` and make it the default bare-command behavior in workspaces. V1 can be thin:
  - Free text like "improve refund handling" routes to `edit`, `build`, or `optimize`.
  - Slash commands route to existing subcommands.
  - The shell shows a left-to-right workflow state: workspace, active config, mode, pending review/autofix items, latest score.
  Files: new `cli/repl.py`, `runner.py`, `cli/status.py`, `cli/workspace.py`.
- Priority:
  P0

### 4. Slash commands

- What Claude Code does:
  Claude Code exposes core functions as slash commands such as `/permissions`, `/memory`, `/mcp`, `/config`, `/resume`, `/rewind`, `/doctor`, `/vim`, and more.
- Why it works:
  Discovery is built into the session. Typing `/` teaches the product.
- AutoAgent today:
  AutoAgent organizes commands well at the Click layer, but discoverability depends on `--help` and documentation. The command tree is large (`runner.py:1-40`, `runner.py:146-182`).
- How AutoAgent should adopt it:
  Keep the Click command tree for scripts. Add a shell-local slash layer for humans.
- Specific implementation recommendation:
  V1 slash commands should map directly to existing surfaces:
  - `/help`
  - `/status`
  - `/config`
  - `/memory`
  - `/doctor`
  - `/mode`
  - `/mcp`
  - `/review`
  - `/autofix`
  - `/exit`
  Then add AutoAgent-native commands:
  - `/compact` to summarize the current shell session into `.autoagent/memory/latest_session.md`
  - `/resume` to restore a prior shell session
  Files: new `cli/repl.py`, `runner.py`.
- Priority:
  P0

### 5. Permission model

- What Claude Code does:
  Permissions are explicit UX. Claude Code has named permission modes, rule-based `allow`/`ask`/`deny` entries, protected-path handling, and a classifier-backed `auto` mode.
- Why it works:
  It gives users a stable safety mental model. Risk is not hidden inside arbitrary confirmation prompts.
- AutoAgent today:
  Risk controls are ad hoc. `deploy` prompts for confirmation unless `--yes` is provided (`runner.py:2463-2467`). `full-auto` requires `--yes` but otherwise just warns and runs (`runner.py:5420-5449`). `mode` only controls `mock` vs `live` execution (`cli/mode.py:17-185`).
- How AutoAgent should adopt it:
  Introduce a shared approval framework for risky operations.
- Specific implementation recommendation:
  Define CLI permission modes:
  - `plan`: read-only analysis and recommendations
  - `default`: ask before config writes, deploys, approvals, or MCP config edits
  - `acceptEdits`: auto-approve local config/eval/memory writes, still ask before deploy/promotion/MCP install
  - `dontAsk`: non-interactive trusted automation
  - `bypass`: unsafe mode for isolated environments
  Back these with `.autoagent/settings.json` rules such as:
  - `allow`: `config.write`, `memory.write`
  - `ask`: `deploy.canary`, `review.apply`, `mcp.install`
  - `deny`: `deploy.immediate`
  Files: new `cli/permissions.py`, `runner.py`, `cli/mode.py`, new `cli/settings.py`.
- Priority:
  P0

### 6. Session continuity

- What Claude Code does:
  Claude Code treats sessions as durable objects. Users can continue the last session, resume by session ID, rewind checkpoints, or clear context without losing resumability.
- Why it works:
  It turns the CLI from a one-shot tool into a long-running workspace.
- AutoAgent today:
  AutoAgent persists workspace artifacts and optimizer checkpoints, but not human conversation state. `resume` means resume the optimizer loop, not resume a CLI session (`runner.py:3133-3155`, `runner.py:2503-2583`).
- How AutoAgent should adopt it:
  Persist shell sessions separately from optimization state.
- Specific implementation recommendation:
  Store sessions under `.autoagent/sessions/` with:
  - `session_id`
  - title
  - started/updated timestamps
  - transcript
  - command history
  - active goal
  - pending next actions
  Add:
  - `autoagent continue`
  - `autoagent session list`
  - `autoagent session resume <id>`
  - `/resume`
  Files: new `cli/sessions.py`, new `cli/repl.py`, `runner.py`, `cli/workspace.py`.
- Priority:
  P0

### 7. Progress and streaming

- What Claude Code does:
  Claude Code makes "work in progress" visible in-session and in structured output. The product exposes task lists and stream-JSON events for automation.
- Why it works:
  The user can tell whether the system is thinking, acting, blocked, or retrying.
- AutoAgent today:
  AutoAgent has good progress output in pockets. `quickstart` and `demo quickstart` use staged output and `_stream_cycle_output` (`runner.py:5482-5646`, `runner.py:5670-5799`). Continuous optimization logs to `.autoagent/experiment_log.tsv` and prints status lines (`docs/QUICKSTART_GUIDE.md:232-266`). But progress rendering is not a shared product primitive.
- How AutoAgent should adopt it:
  Standardize progress events across long-running commands.
- Specific implementation recommendation:
  Create a shared progress/event layer used by `build`, `eval run`, `optimize`, `loop`, `deploy`, `review apply`, and the future shell. Human output and `--output-format stream-json` should come from the same event stream.
  Event types:
  - `phase_started`
  - `phase_completed`
  - `artifact_written`
  - `warning`
  - `error`
  - `next_action`
  Files: new `cli/progress.py`, `runner.py`, `cli/stream2_helpers.py`, `cli/status.py`.
- Priority:
  P1

### 8. Error recovery

- What Claude Code does:
  Claude Code bakes troubleshooting into the CLI with `/doctor`, checkpoint recovery, permission guidance, and structured failure events.
- Why it works:
  Failures are part of the product, not a documentation tax.
- AutoAgent today:
  AutoAgent has `doctor` (`runner.py:2905-3045`) and some good targeted messages such as missing workspace and missing provider-key guidance (`runner.py:201-206`, `cli/mode.py:120-127`), but many commands still fail as isolated messages.
- How AutoAgent should adopt it:
  Route every common failure into a shared recovery format.
- Specific implementation recommendation:
  Add a common error renderer with:
  - `What failed`
  - `Why likely`
  - `Try next`
  - `Run doctor`
  - `Docs link`
  Also add `autoagent doctor --json` and emit structured recovery fields from machine-readable commands.
  Files: `runner.py`, new `cli/errors.py`, `cli/stream2_helpers.py`.
- Priority:
  P1

### 9. Configuration hierarchy

- What Claude Code does:
  Claude Code documents config scopes clearly and uses multiple files with explicit precedence.
- Why it works:
  Users know whether they are setting a global preference, a repo behavior, or a one-off session override.
- AutoAgent today:
  AutoAgent has:
  - runtime config in `autoagent.yaml`
  - workspace state in `.autoagent/workspace.json`
  - environment variables for providers and paths
  - ad hoc command flags
  There is no unified CLI settings layer (`cli/workspace.py:15-200`, `cli/mode.py:17-185`).
- How AutoAgent should adopt it:
  Separate agent runtime settings from CLI interaction settings.
- Specific implementation recommendation:
  Introduce:
  - `~/.autoagent/config.json` for user defaults
  - `.autoagent/settings.json` for project settings
  - `.autoagent/settings.local.json` for ignored local overrides
  - session overrides stored in session metadata
  Precedence:
  flags > session > local project > project > user > defaults
  Keep `autoagent.yaml` as the agent runtime spec.
  Files: new `cli/settings.py`, `runner.py`, `cli/workspace.py`, docs.
- Priority:
  P0

### 10. Non-interactive and scripting mode

- What Claude Code does:
  Claude Code has a strong headless mode: `-p`/`--print`, `--output-format json|stream-json`, JSON schema output, `--allowedTools`, `--bare`, and session continuation.
- Why it works:
  Interactive and non-interactive use share the same mental model instead of feeling like separate products.
- AutoAgent today:
  AutoAgent already has meaningful `--json` coverage, but it is inconsistent. `cli/stream2_helpers.py:179-185` defines a standard `{status, data, next}` envelope, while older commands like `status --json` and `eval run --json` return raw payloads (`runner.py:2819-2841`, `runner.py:1316-1326`, `docs/QUICKSTART_GUIDE.md:779-782`).
- How AutoAgent should adopt it:
  Normalize the scripting contract before adding more commands.
- Specific implementation recommendation:
  Add shared output flags across long-running commands:
  - `--output-format text|json|stream-json`
  - `--json-schema <path>` where relevant
  - `--continue` after session support lands
  - `--bare` to suppress banners and prose
  Also keep a backward-compatible `--json` alias that maps to `--output-format json`.
  Files: `cli/stream2_helpers.py`, `runner.py`, new `cli/output.py`.
- Priority:
  P0

### 11. MCP integration

- What Claude Code does:
  Claude Code treats MCP as part of the core UX. It has scoped MCP config, native commands, `.mcp.json`, and in-session management via `/mcp`.
- Why it works:
  Tool connectivity is not a separate installer workflow. It is visible, explainable, and inspectable.
- AutoAgent today:
  AutoAgent's `mcp` group only installs AutoAgent into external clients by writing client config files (`cli/mcp_setup.py:55-313`). That is useful, but it is not the same as AutoAgent itself having native MCP-aware runtime configuration.
- How AutoAgent should adopt it:
  Split "AutoAgent as an MCP server" from "AutoAgent using MCP servers."
- Specific implementation recommendation:
  Keep the existing install flow but rename it conceptually to `mcp install-client`.
  Add a second surface:
  - `autoagent mcp list`
  - `autoagent mcp add`
  - `autoagent mcp remove`
  - `autoagent mcp status`
  - `autoagent mcp inspect`
  Read `.mcp.json` from the workspace and merge it with user-level config. Surface MCP state in `status`, `doctor`, and the future shell.
  Files: `cli/mcp_setup.py`, new `cli/mcp_runtime.py`, `cli/workspace.py`, `runner.py`.
- Priority:
  P1

### 12. Memory files

- What Claude Code does:
  Memory is inspectable, layered, and partly automatic.
- Why it works:
  Users trust the system more when they can see what the assistant "remembers."
- AutoAgent today:
  `memory show` and `memory add` operate on `AUTOAGENT.md` (`runner.py:4110-4158`). This is useful, but manual and limited to four note sections.
- How AutoAgent should adopt it:
  Keep `AUTOAGENT.md`, but make memory a browsable system instead of a note bucket.
- Specific implementation recommendation:
  Add:
  - `memory list`
  - `memory edit`
  - `memory summarize-session`
  - `memory where`
  - automatic session summaries written to `.autoagent/memory/`
  Extend `AUTOAGENT.md` to support includes or references to focused files.
  Files: `core/project_memory.py`, `runner.py`, `cli/bootstrap.py`.
- Priority:
  P1

### 13. Tooling integration

- What Claude Code does:
  Claude Code works naturally with terminal workflows, editors, git, and remote/web control.
- Why it works:
  It reduces context switching between "tool" and "workspace."
- AutoAgent today:
  AutoAgent already opens the web console from quickstart/demo (`runner.py:5644-5645`, `runner.py:5798-5799`) and integrates outward via MCP, but it does not offer strong editor/open-surface shortcuts.
- How AutoAgent should adopt it:
  Add explicit "take me to the artifact" actions.
- Specific implementation recommendation:
  Add:
  - `autoagent open config`
  - `autoagent open memory`
  - `autoagent open evals`
  - `autoagent open latest-review`
  - `autoagent open console`
  Respect `$EDITOR` and fall back to printing the path.
  Files: new `cli/openers.py`, `runner.py`, `cli/workspace.py`.
- Priority:
  P2

### 14. Cost and token awareness

- What Claude Code does:
  Claude Code exposes usage and classifier costs in docs and structured output, making cost part of the operational model.
- Why it works:
  Users can reason about speed, budget, and safety tradeoffs without external bookkeeping.
- AutoAgent today:
  AutoAgent already computes token and cost metrics in eval output and optimize cost summaries (`runner.py:252-274`, `runner.py:1929-1939`). It also stores a budget tracker path in runtime config bootstrap (`cli/bootstrap.py:198-207`). But cost is not a first-class home-screen concept.
- How AutoAgent should adopt it:
  Promote usage from a trailing metric to a visible control surface.
- Specific implementation recommendation:
  Add `autoagent usage` and surface in `status`:
  - last eval tokens/cost
  - last optimize run cost
  - workspace cumulative spend
  - configured budget
  - budget remaining
  Also allow `optimize` and `loop` to take `--max-budget-usd`.
  Files: `runner.py`, `cli/status.py`, `cli/bootstrap.py`, new `cli/usage.py`.
- Priority:
  P1

### 15. Multi-model support

- What Claude Code does:
  Claude Code lets users pick or switch models directly in the product. Model selection is an ergonomic action, not only a config edit.
- Why it works:
  It shortens the loop between "I need a different speed/cost/capability profile" and action.
- AutoAgent today:
  AutoAgent supports multi-model runtime config in `autoagent.yaml` and documents multiple providers in the README, but there is no ergonomic model command in the CLI (`README.md:587-624`, `cli/mode.py:56-74`).
- How AutoAgent should adopt it:
  Add a model command surface instead of forcing config edits.
- Specific implementation recommendation:
  Add:
  - `autoagent model list`
  - `autoagent model show`
  - `autoagent model set proposer <model>`
  - `autoagent model set evaluator <model>`
  - `/model` in the future shell
  Prefer writing per-workspace overrides into `.autoagent/settings.json`, not mutating `autoagent.yaml` silently.
  Files: new `cli/model.py`, `cli/mode.py`, `runner.py`, `cli/workspace.py`.
- Priority:
  P1

## Section 2: AutoAgent-Specific Gaps

These are needs Claude Code does not directly solve, but Claude Code's approach is still instructive.

### A. AutoAgent needs a campaign shell, not just a chat shell

Claude Code optimizes around "one conversation doing work." AutoAgent needs a session that is aware of:
- active config
- latest eval
- pending review card
- pending autofix
- canary status
- next best action

Claude's task-list and status-oriented shell design is the right reference. AutoAgent should copy the session feel, not the coding-agent task semantics.

### B. AutoAgent needs approvals tied to deployment semantics

Claude Code permissions mostly guard file edits, commands, and web actions. AutoAgent's risky actions are different:
- promoting configs
- deploying canaries
- auto-applying fixes
- enabling full-auto loops
- rewriting client MCP config

Claude's permission modes should inspire the UX, but AutoAgent's policy objects should be domain-specific.

### C. AutoAgent needs artifact-aware memory and compaction

Claude Code can summarize conversation state. AutoAgent also needs to preserve artifact state:
- why config v017 exists
- why review card `card-123` is pending
- which failure bucket the current session is targeting
- which eval suite was last trusted

Its session summaries should reference real files and IDs, not just natural-language notes.

### D. AutoAgent needs team-shared project state plus local operator overrides

Claude Code's config hierarchy is useful because many users work in shared repos with local preferences. AutoAgent needs the same split:
- shared workspace defaults committed to the repo
- local operator overrides ignored by git
- session-level temporary changes

This is especially important for mock/live mode, model choice, shell defaults, and permission rules.

### E. AutoAgent needs long-run automation ergonomics

Claude Code's checkpointing, resumability, and stream-JSON patterns are directly relevant to:
- overnight optimize runs
- CI-driven evals
- human-supervised loops
- incident triage sessions

AutoAgent should converge on the same "interactive + resumable + machine-readable" contract.

### F. AutoAgent needs native connector/runtime discovery, not only MCP installation

Today `autoagent mcp init claude-code` is about configuring other clients (`cli/mcp_setup.py:58-97`, `cli/mcp_setup.py:274-313`). AutoAgent itself still lacks a project-scoped connector runtime. Claude Code's `.mcp.json` pattern is the right model for making tool access declarative in the workspace.

## Section 3: Concrete Implementation Roadmap

| Feature | One-line description | Effort | Files to modify | Priority |
|---|---|---:|---|---|
| Smart launcher + workspace shell | Make bare `autoagent` launch onboarding or a session shell instead of printing help | L | `runner.py`, new `cli/repl.py`, new `cli/onboarding.py`, `cli/workspace.py`, `cli/status.py`, docs | P0 |
| Permission modes | Add shared approval modes and per-action rules for writes, deploys, MCP installs, and full-auto operations | M | new `cli/permissions.py`, new `cli/settings.py`, `runner.py`, `cli/mode.py` | P0 |
| Session persistence | Persist CLI sessions under `.autoagent/sessions/` and add continue/resume commands | M | new `cli/sessions.py`, new `cli/repl.py`, `runner.py`, `cli/workspace.py` | P0 |
| CLI settings hierarchy | Separate interaction settings from `autoagent.yaml` with user/project/local/session precedence | M | new `cli/settings.py`, `runner.py`, `cli/workspace.py`, docs | P0 |
| Output contract unification | Standardize `--json` and add `--output-format stream-json` for long-running commands | M | `cli/stream2_helpers.py`, new `cli/output.py`, `runner.py` | P0 |
| Slash command layer | Expose shell-first commands like `/status`, `/config`, `/memory`, `/doctor`, `/review`, `/mcp` | M | new `cli/repl.py`, `runner.py` | P1 |
| Context + memory v2 | Turn `AUTOAGENT.md` into a layered context system with local overrides and generated session memory | M | `core/project_memory.py`, `cli/bootstrap.py`, `runner.py`, `cli/workspace.py` | P1 |
| Shared progress/event renderer | Emit progress events and render them consistently across `build`, `eval`, `optimize`, `loop`, and deploy flows | M | new `cli/progress.py`, `runner.py`, `cli/status.py`, `cli/stream2_helpers.py` | P1 |
| MCP runtime support | Add native MCP discovery/config consumption for AutoAgent itself, not just client installation helpers | L | `cli/mcp_setup.py`, new `cli/mcp_runtime.py`, `cli/workspace.py`, `runner.py` | P1 |
| Usage and budget surfaces | Add `usage` command and show spend/budget in `status` and `doctor` | S | new `cli/usage.py`, `runner.py`, `cli/status.py`, `cli/bootstrap.py` | P1 |
| Model command surface | Add `model list/show/set` for proposer/evaluator model selection | S | new `cli/model.py`, `cli/mode.py`, `runner.py`, `cli/workspace.py` | P1 |
| Openers/editor integration | Add `autoagent open ...` commands for memory, config, evals, review cards, and console | S | new `cli/openers.py`, `runner.py`, `cli/workspace.py` | P2 |
| Recovery/error framework | Standardize human and JSON failure responses with actionable next steps | S | new `cli/errors.py`, `runner.py`, `cli/stream2_helpers.py` | P2 |

Recommended sequencing:
1. Build the shell, settings, permissions, and sessions together. Those four pieces are mutually reinforcing.
2. Immediately after that, normalize output contracts so the new shell and old subcommands can share the same event model.
3. Then layer in slash commands, memory v2, and MCP runtime support.

## Section 4: Quick Wins (implement immediately)

These can each be done in under a day and will noticeably improve CLI feel.

| Quick win | Why it matters | Effort | Files | Priority |
|---|---|---:|---|---|
| Make bare `autoagent` smart | In a workspace, show `status` or launch the shell; outside a workspace, offer `init`/`quickstart` guidance instead of dumping help | S | `runner.py`, docs | P0 |
| Add `doctor --json` | Makes troubleshooting automatable and aligns with the existing `doctor` surface | S | `runner.py` | P0 |
| Standardize JSON for legacy commands | Wrap `status`, `eval run`, `explain`, `diagnose`, and `replay` in the same `{status,data,next}` envelope or add `--json-v2` | S | `runner.py`, `cli/stream2_helpers.py` | P0 |
| Add `memory edit` and `config edit` | Removes friction from editing the two most important workspace files | S | `runner.py`, `core/project_memory.py` | P0 |
| Show usage in `status` | Add last eval tokens/cost and last optimize cost summary to the home screen | S | `runner.py`, `cli/status.py` | P1 |
| Route common failures to `doctor` | Missing workspace, missing provider credentials, and config import failures should suggest `autoagent doctor` explicitly | S | `runner.py`, `cli/mode.py` | P1 |
| Improve interactive submode prompts | `edit --interactive` and `diagnose --interactive` should show lightweight in-session help, current workspace, and `quit/help/status` hints | S | `runner.py` | P1 |
| Add `model show` | Quick visibility into the effective proposer/evaluator models without reading YAML | S | new `cli/model.py`, `runner.py` | P1 |
| Add `mcp init --open-config` | After writing config, optionally open the edited file and show the exact inserted block | S | `cli/mcp_setup.py` | P2 |
| Add `status --verbose` | Show active files, workspace metadata path, experiment log path, and last-updated timestamps | S | `runner.py`, `cli/status.py`, `cli/workspace.py` | P2 |

## Source Notes

Claude Code sources used:
- Anthropic docs landing page: <https://docs.anthropic.com/en/docs/claude-code>
- Claude Code overview: <https://code.claude.com/docs>
- Interactive mode: <https://code.claude.com/docs/en/interactive-mode>
- Built-in commands: <https://code.claude.com/docs/en/commands>
- CLI reference: <https://code.claude.com/docs/en/cli-reference>
- Memory: <https://code.claude.com/docs/en/memory>
- Settings: <https://code.claude.com/docs/en/settings>
- Permissions: <https://code.claude.com/docs/en/permissions>
- Permission modes: <https://code.claude.com/docs/en/permission-modes>
- MCP: <https://code.claude.com/docs/en/mcp>
- Headless mode: <https://code.claude.com/docs/en/headless>
- Checkpointing: <https://code.claude.com/docs/en/checkpointing>
- Product page: <https://claude.com/product/claude-code>
- Anthropic webinar page: <https://www.anthropic.com/webinars/claude-code-in-an-hour-a-developers-intro>

AutoAgent code paths referenced most heavily:
- Root CLI behavior: `runner.py:146-182`, `runner.py:958-971`
- Init/build/status/doctor: `runner.py:985-1216`, `runner.py:2760-3045`
- Config/deploy/loop/full-auto: `runner.py:1991-2720`, `runner.py:5420-5449`
- Interactive submodes: `runner.py:6251-6556`
- Memory commands: `runner.py:4110-4158`
- Workspace bootstrap/state: `cli/bootstrap.py:198-243`, `cli/workspace.py:21-200`
- Status rendering: `cli/status.py:31-56`
- Mode and MCP setup: `cli/mode.py:17-185`, `cli/mcp_setup.py:55-313`
- JSON helper contract: `cli/stream2_helpers.py:24-185`
