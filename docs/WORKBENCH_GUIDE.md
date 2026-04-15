# Workbench Guide — end-to-end

> Interactive, Claude-Code-style harness for building, evaluating, optimizing,
> and deploying agents. This is the default mode of `agentlab` — plain
> `agentlab` in a workspace drops you straight into it.

**What's new (Apr 2026 parity release)**: the workbench is now a live tool-calling
REPL with Claude-Code-equivalent UX — per-tool permission dialogs, disk-loaded
skills, lifecycle hooks, plan mode as a first-class workflow, streaming
markdown, per-model context visualisation, transcript rewind, background
subagent panel, themes, output styles, vim keybindings, and model adapters
for Anthropic and OpenAI. See [Section 14](#14-live-llm-mode-what-changed-in-the-parity-release)
for how to turn it on.

Quick links: [Setup](#0-first-time-setup-one-time-2-min) · [Launch](#1-launch-the-workbench) ·
[Build](#2-describe-what-you-want-to-build) · [Eval](#4-eval-the-current-candidate) ·
[Plan mode](#5-plan-mode-for-risky-runs) · [Optimize](#6-optimize-from-evidence) ·
[Checkpoint / rewind](#7-checkpoint--rewind-to-explore-safely) ·
[Deploy](#8-deploy-with-gates) · [Skills](#9-skills-to-close-gaps) ·
[Daily loop](#10-daily-iteration-loop) · [Power moves](#11-power-moves) ·
[Troubleshooting](#12-troubleshooting) · [Tools](#13-tool-catalogue) ·
[Live LLM](#14-live-llm-mode-what-changed-in-the-parity-release) ·
[Skills deep-dive](#15-skills-prompt--tool-bundles-on-disk) ·
[Hooks](#16-hooks-automate-around-every-tool-call) ·
[Context & sessions](#17-context-transcript-rewind-and-sessions) ·
[Personalization](#18-personalization-themes-output-styles-keybindings) ·
[MCP](#19-mcp-server-integration) ·
[Non-interactive](#20-non-interactive-mode-agentlab-print) ·
[Environment reference](#21-environment-variable-reference)

---

## 0. First-time setup (one-time, ~2 min)

On your first `agentlab` launch in an uninitialized workspace, a wizard walks
you through picking a provider + model for the coordinator and workers and
writes them to `agentlab.yaml`. If you prefer to skip the wizard and set it
up by hand, add:

```yaml
harness:
  models:
    coordinator:
      provider: anthropic
      model: claude-opus-4-6
      api_key_env: ANTHROPIC_API_KEY
    worker:
      provider: anthropic
      model: claude-sonnet-4-6
      api_key_env: ANTHROPIC_API_KEY
```

Export the API key and opt into live workers:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export AGENTLAB_WORKER_MODE=llm      # flip on real workers
```

Verify: `agentlab doctor` — the **Coordinator** section should show resolved
models and `Credentials: ✓`.

Omit `AGENTLAB_WORKER_MODE=llm` and the harness runs **deterministic workers**
— useful for offline dev, CI, and learning the UX without burning tokens.

### Opting in to the live LLM REPL (new)

The parity release adds a second turn path that replaces the coordinator with
a real Claude / GPT / o-series chat loop. **This is opt-in** — existing
workflows stay on the classic coordinator until you set:

```bash
export AGENTLAB_LLM_ORCHESTRATOR=1
export ANTHROPIC_API_KEY=sk-ant-...           # or OPENAI_API_KEY
export AGENTLAB_MODEL=claude-sonnet-4-5       # optional; defaults to this
agentlab
```

That enables streaming text, live tool calls, per-tool permission dialogs,
hooks, skill invocation, and every other Phase 1–7 subsystem. `/build`,
`/eval`, `/optimize`, `/deploy` still route through the coordinator because
those are agentlab-specific workflow commands; natural-language turns are
the ones that change.

Roll back any time with `export AGENTLAB_CLASSIC_COORDINATOR=1` — force
disables the orchestrator even when the opt-in var is set.

---

## 1. Launch the Workbench

```bash
cd your-agent-workspace
agentlab
```

You get a Claude-Code-style REPL: branded banner, `cwd`, current permission
mode, `? for shortcuts`, a bordered input box, and a footer chevron showing
`⏵ default permissions on · idle`.

**Permission modes** (Shift+Tab cycles): `default → acceptEdits → plan → bypass → default`.

| Mode | Behavior |
|---|---|
| `default` | Asks before edits / privileged actions |
| `acceptEdits` | Auto-approves file edits |
| `plan` | Every coordinator turn gates through the approval screen first; in live mode, mutating tools stay blocked until a plan is approved |
| `bypass` | Runs without prompts (use sparingly) |

---

## 2. Describe what you want to build

```text
› I want a customer support agent with a PII guardrail, order lookup tool, and a refund policy
```

The free-text router classifies intent (`build`), seats a coordinator plan,
and streams each worker's state transitions live:

```text
  Coordinator plan coord-abc123 created for 7 workers.
  [0s] requirements analyst • gathering_context
  [1s] requirements analyst • acting
  [2s] requirements analyst • completed — Parsed acceptance criteria + 3 risks
  [3s] adk architect • acting
  [5s] adk architect • completed — Proposed 4-specialist graph
  ...
  [18s] eval author • completed — Smoke suite (5 cases)
  Next: /eval to test the candidate
  Wrote candidate config v014 (v014.yaml).
```

Every successful `/build` snapshots the active config first (pre-execution
auto-checkpoint), then writes the new config as a `candidate` version. No
silent overwrites.

---

## 3. Run `/build` again to refine

The coordinator session **remembers the last 5 turns** across the session, so
follow-ups accumulate. Workers see `prior_turns` in their prompt and avoid
re-proposing work the last turn already did:

```text
› /build add a handoff to human for refund amounts over $500
```

Check `/context` at any point to see what history the coordinator is carrying
forward.

---

## 4. `/eval` the current candidate

```text
› /eval
  [0s] eval author • completed — Prepared smoke + regression tiers
  [1s] eval runner • acting
  [6s] eval runner • completed — 37/42 cases passed (88%)
  [7s] trace analyst • completed — 2 failure clusters identified
  [9s] loss analyst • completed — PII leaked on paraphrased jailbreak; slow on bulk order lookups
  Next: /optimize to improve from loss patterns
```

Loss-analyst output is stored on the coordinator run and passed automatically
to the next `/optimize` turn via multi-turn memory.

---

## 5. Plan mode for risky runs

Press Shift+Tab until the footer reads `⏵ plan permissions on`. Now:

```text
› /build make the PII guardrail also block medical info
  Coordinator plan coord-ghi789 ready — 3 workers queued.
  • guardrail author: revise pii_block to include medical categories
  • build engineer: apply config diff
  • eval author: regression sweep
  Approve with y to execute, n to abort, or edit to refine.
  plan›
```

Type `y` to execute, `n` to abort (nothing written), or
`edit tighten to only PHI not general medical` to re-plan with that
annotation. Up to 5 edit rounds per turn.

### Plan mode as a workflow (new)

The live LLM path elevates plan mode from a permission flag into a **discrete
state machine** with four states: `idle → drafting → approved → archived`.
The draft gets persisted to `.agentlab/plans/<id>.md` so a workbench restart
picks up where you left off.

```text
› /plan migrate the retries library
  Plan started: migrate the retries library  [DRAFTING]
  Drafting — only FileRead / Glob / Grep / ConfigRead / ExitPlanMode are allowed
  until /plan-approve.
```

The LLM can now use the `ExitPlanMode` tool to propose the finalised plan —
you'll see the permission dialog showing the plan text before any mutating
tool runs. Approve with `y` in the dialog or `/plan-approve` on the slash
line.

**Plan commands:** `/plan [goal]`, `/plan-approve`, `/plan-discard`,
`/plan-done`, `/plan-list` (recent plans across sessions).

---

## 6. `/optimize` from evidence

```text
› /optimize --cycles 1
  [0s] trace analyst • completed — Reused /eval loss evidence
  [3s] instruction_optimizer • completed — Prompt diff + jailbreak resistance
  [4s] guardrail_optimizer • completed — Expand pii_block regex + 4 new adversarial cases
  [5s] callback_optimizer • completed — Pre-tool validator for order-lookup
  [9s] eval author • completed — Verification sweep 41/42 (98%)
  Wrote candidate config v016.
```

Three axis optimizers run in sequence (instruction, guardrail, callback). Each
produces a change card listed in `/review`. The verification eval acts as the
gate: if it regresses, the new candidate is flagged but not promoted.

---

## 7. `/checkpoint` / `/rewind` to explore safely

Two independent rewind surfaces:

**Config-level** (unchanged) — snapshots the active agent config version:

```text
› /checkpoint about to try aggressive policy rewrite
  Snapshot saved v017 (v017.yaml) — about to try aggressive policy rewrite

› /rewind v015          # restore a prior config version as active
```

**Transcript-level** (new) — snapshots the conversation so you can undo turns:

```text
› /transcript-checkpoint before risky request
  Transcript checkpoint saved: a1b2c3 (at message 12)

› /transcript-rewind a1b2c3
  Rewound to checkpoint a1b2c3 (message 12).
  Dropped 4 message(s) from the transcript.
```

`/transcript-checkpoints [--all]` lists them — the `--all` flag includes
auto-snapshots captured after each assistant turn.

Candidates can still be inspected and promoted directly:

```text
› /diff v016                 # unified YAML delta between active and v016
› /accept v016               # promote v016 → active, retire prior active
› /reject v016               # mark v016 rolled_back without touching active
```

---

## 8. `/deploy` with gates

```text
› /deploy --strategy canary
  [2s] release_manager • completed — Packaged release candidate
  [4s] gate_runner • completed — CICDGate passed (safety ≥ baseline, cost within budget)
  [7s] platform_publisher • completed — Pushed to cloud-run staging
  [8s] deployment_engineer • completed — Canary plan + rollback steps attached
  Next: /deploy --approve after reviewing canary evidence
```

A dry canary runs against the staging platform. Approve to promote, or roll
back with the release_manager's prepared plan.

---

## 9. `/skills` to close gaps

**Build-time skills** (existing): reusable mutations the harness applies during
any verb. They live in `agent_skills/` and the coordinator surfaces them as
`skill_candidates` inside worker context.

```text
› /skills gap
  • skill_author: prioritized 3 missing capabilities:
    1. order_lookup_cache (tool) — HIGH impact, repeats identical queries
    2. policy_change_log (runtime) — MEDIUM, required for compliance
    3. regex_safety_harness (build) — LOW, helps guardrail optimizer

› /skills generate order_lookup_cache
  Wrote agent_skills/order_lookup_cache/manifest.yaml + skill.py

› /skills list
  (shows all local skills by layer)
```

**User skills** (new): Claude-Code-style prompt+tool bundles authored as
markdown files in `.agentlab/skills/` (project-local) or `~/.agentlab/skills/`
(user-global). See [Section 15](#15-skills-prompt--tool-bundles-on-disk) for
the full authoring guide. Use `/skill-list` to see what's loaded,
`/skill <slug> [args]` to run one.

---

## 10. Daily iteration loop

```text
Morning:
  agentlab
  /sessions              # list recent
  /resume                # pick the one from yesterday
  /tasks                 # show last coordinator run + workers
  /context               # see the 5-turn memory window
  /usage                 # token budget for the current window

Mid-day:
  /eval                  # check overnight regression
  /optimize              # tighten based on loss
  /checkpoint "EOD checkpoint"

End of day:
  /background            # any subagent tasks still running?
  /deploy --strategy canary
  /exit                  # session + transcript persisted
```

---

## 11. Power moves

| Keystroke / prefix | What it does |
|---|---|
| `Shift+Tab` | Cycle permission mode |
| `?` on empty line | Show shortcuts |
| `Ctrl+R` | History search |
| `Ctrl+C` twice | Exit (first: cancel active tool) |
| `Ctrl+T` | Toggle collapsed vs raw-event transcript |
| `!ls -la` | Run a shell command (gated by permission mode) |
| `@src/prompt.md` | File-reference completion |
| `&long-task` | Kick off as background coordinator task (footer counter) |
| `/ppr` | Fuzzy-complete to `/plan-approve` (subsequence match) |

**Full slash command index** (run `/help` for live copy):

### Core REPL
| Command | Purpose |
|---|---|
| `/help [command]` | Show commands or one-command detail |
| `/shortcuts` (`/?`) | Keyboard cheatsheet |
| `/status` | Workspace status |
| `/config` | Active config info |
| `/doctor` | Workspace + Coordinator diagnostics |
| `/memory` | Show AGENTLAB.md contents |
| `/init [--dry-run] [--fresh]` | Scan workspace and refresh AGENTLAB.md |
| `/exit` \| `/quit` | Exit |

### Sessions & transcript
| Command | Purpose |
|---|---|
| `/sessions` | Recent Workbench sessions |
| `/resume [session_id]` | Resume the most recent session |
| `/new [title]` | Fresh session + clear transcript |
| `/clear` | Wipe transcript but keep session |
| `/compact` | Summarize session to memory |
| `/cost` | Session cost summary |
| `/usage` | Context-window token-usage grid |
| `/transcript-checkpoint [label]` | Snapshot the transcript |
| `/transcript-rewind <id>` | Restore transcript to a snapshot |
| `/transcript-checkpoints [--all]` | List transcript checkpoints |

### Workflow (coordinator)
| Command | Purpose |
|---|---|
| `/build` | Build or refine the active agent via coordinator workers |
| `/eval` | Run evals + loss analysis |
| `/optimize` | Axis-scoped optimizer (instruction / guardrail / callback) |
| `/deploy` | Gate + canary + rollback plan |
| `/skills gap \| generate <slug> \| list` | Build-skill surfacing + authoring |

### Config versioning
| Command | Purpose |
|---|---|
| `/diff [version]` | Unified YAML delta between active and a candidate |
| `/accept <version>` | Promote a candidate to active |
| `/reject <version>` | Roll back a candidate without touching active |
| `/checkpoint [reason]` | Snapshot the current active config |
| `/rewind <version>` | Promote a prior version back to active |
| `/checkpoints` | List recorded snapshots (newest first) |
| `/review` | Pending review cards from worker output |
| `/save` | Materialize active candidate |

### Plan mode (new)
| Command | Purpose |
|---|---|
| `/plan [goal]` | Start drafting a plan (restricts tools to read-only) |
| `/plan-approve` | Move from drafting → approved (unlocks normal permissions) |
| `/plan-discard` | Discard the current plan |
| `/plan-done` | Archive an approved plan once its work is complete |
| `/plan-list` | Recent plans |

### User skills (new)
| Command | Purpose |
|---|---|
| `/skill <slug> [args]` | Invoke a markdown skill by slug |
| `/skill-list` | Show loaded skills from `.agentlab/skills/` |
| `/skill-reload` | Rescan skill directories |

### Background tasks (new)
| Command | Purpose |
|---|---|
| `/background [--active-only]` | Live subagent / long-running task panel |
| `/background-clear [--all]` | Drop completed tasks (or every task with `--all`) |

### Personalization (new)
| Command | Purpose |
|---|---|
| `/theme [name]` | Switch colour theme (default, claudelight, claudedark, ocean, nord) |
| `/output-style [concise\|verbose\|json]` | Adjust transcript verbosity / machine mode |
| `/model` | Select model for the next turn |

### Integrations
| Command | Purpose |
|---|---|
| `/mcp` | MCP integration status |
| `/tasks` | Latest coordinator plan, worker states, queued work |
| `/context` | Prior-turn synthesis the coordinator is carrying forward |

---

## 12. Troubleshooting

| Symptom | Fix |
|---|---|
| **Workers return stub output** | You're in deterministic mode. `export AGENTLAB_WORKER_MODE=llm` + confirm `harness.models.*` in agentlab.yaml via `/doctor`. |
| **`WorkerModeConfigurationError: /doctor`** | Missing model config or API key. Run `agentlab doctor` — the Coordinator section points at the exact fix. |
| **Plan gate hangs** | Only triggers when permission_mode is `plan`. Shift+Tab back to `default` to skip. |
| **Nothing happens on free text** | The workbench runtime isn't bound. Check you're not in `agentlab shell --ui classic` (legacy REPL). |
| **Onboarding wizard runs every launch** | `harness.models` keys didn't get written. Inspect `agentlab.yaml`; if in CI, set `AGENTLAB_SKIP_ONBOARDING=1`. |
| **Candidate config pile-up** | `/checkpoints` to audit; `/diff`, `/accept`, `/reject` to curate. `/rewind <v>` to restore a prior version. |
| **Long run feels silent** | Events render with `[Ns]` elapsed stamps — a 30s gap means the current worker is actually still running (check the spinner verb). Press Ctrl+C once to cancel the tool call, twice to exit. |
| **Live LLM mode seems off** | `env \| grep AGENTLAB_LLM_ORCHESTRATOR` must show `=1`; `AGENTLAB_CLASSIC_COORDINATOR` must be unset; API key for the selected provider must be present. |
| **Permission dialog never appears** | `settings.json` permission rules may already allow the tool; or you're in `dontAsk`/`bypass` mode. `/permissions show` prints the effective decisions. |
| **Skill doesn't appear in `/skill-list`** | Frontmatter parse failed. `/skill-list` shows load warnings at the bottom — fix the YAML and `/skill-reload`. |
| **Vim mode didn't activate** | `~/.agentlab/keybindings.json` must exist with `"mode": "vim"`. Default mode is Emacs-style. |
| **`/usage` shows 200k limit for a 1M model** | Pass the model via `ctx.meta['active_model']` or let the orchestrator populate it automatically; `cli/llm/capabilities.py` has the full map. |

---

## 13. Tool catalogue

The live LLM loop gives the model a catalogue of tools. Every tool call
flows through the permission manager (see [Section 14](#14-live-llm-mode-what-changed-in-the-parity-release))
before running.

### Workspace tools (bundled)

| Tool | Read-only? | Purpose |
|---|---|---|
| `FileRead` | ✓ | Return a file with numbered lines |
| `FileWrite` | | Create or overwrite a file |
| `FileEdit` | | Exact-string replacement (unique match required) |
| `Glob` | ✓ | Find files by pattern, newest first |
| `Grep` | ✓ | Regex search with line numbers |
| `Bash` | | Shell command (workspace cwd, 120 s timeout) |
| `ConfigRead` | ✓ | Parse YAML/JSON config with schema validation hints |
| `ConfigEdit` | | Dotted-key change with `AgentConfig` validation before write |
| `WebFetch` | | Fetch a URL (redacts secrets, strips HTML) |
| `WebSearch` | ✓ | Pluggable search backend (env-configurable) |
| `TodoWrite` | | Persist a todo list to `.agentlab/todos.json` |
| `AgentSpawn` | | Register a subagent task in the background panel |
| `SkillTool` | | Run a user skill with its declared tool allowlist |
| `ExitPlanMode` | | Transition a drafting plan to approved (user confirms) |

### MCP tools (dynamic)

Any MCP server listed in `.mcp.json` shows up as `mcp__<server>__<tool>` in
the catalogue. Permission actions use `tool:mcp:<server>:<tool>` so rules can
target a specific server or tool. See [Section 19](#19-mcp-server-integration)
for setup.

### Permission rule grammar

`.agentlab/settings.json` accepts:

```json
{
  "permissions": {
    "mode": "default",
    "rules": {
      "allow": ["tool:FileRead:*", "tool:Grep", "tool:Glob"],
      "ask":   ["tool:Bash:*"],
      "deny":  ["tool:Bash:rm -rf *", "tool:mcp:notion:delete_page"]
    }
  }
}
```

`allow`/`ask`/`deny` patterns are evaluated in that order. Session-level
overrides from the permission dialog ("Approve always (this session)") take
precedence over `settings.json` rules.

---

## 14. Live LLM mode — what changed in the parity release

The parity release makes the REPL **actually call a model** and route tool
use through an orchestrator. Here's the flow.

### Activating it

```bash
export AGENTLAB_LLM_ORCHESTRATOR=1                # turn it on
export ANTHROPIC_API_KEY=sk-ant-...               # or OPENAI_API_KEY
export AGENTLAB_MODEL=claude-sonnet-4-5           # model selector (optional)
agentlab
```

That's it. Type a prompt; the model streams text live, requests tools,
results flow back, the loop iterates until the model ends its turn. Slash
workflow commands still use the coordinator.

### Per-tool permission dialog

First time the model calls `FileEdit` you'll see:

```text
  Permission requested: FileEdit
    Edit configs/v014.yaml

  [a] Approve once
  [s] Approve always (this session)
  [p] Approve always (save to settings.json)
  [d] Deny
```

- `a` — runs it this time only.
- `s` — adds a session-scope allow rule that expires when you exit.
- `p` — writes an allow rule to `.agentlab/settings.json`.
- `d` — denies; the model sees the denial as a tool_result and adapts.

Read-only tools (`FileRead`, `Glob`, `Grep`, `ConfigRead`) auto-allow — no
dialog, no session noise.

### Streaming markdown

The renderer folds code fences (` ``` `), diff blocks, and inline `+foo` /
`-bar` markers into coloured lines as they arrive. Nothing new in the CLI
to enable — it's the default renderer now.

### Context window visualisation

```text
› /usage
  Context window usage

  ████████████████████░░░░░░░░░░░░░░░░░░░░
  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░

  ■ user 18,400 (47.1%)   ■ assistant 12,900 (33.0%)   ■ tools 5,900 (15.1%)
  Context window: 39,100 / 200,000 tokens (19.5%)
```

Token budgets are now model-aware — Claude 4.x shows 200k, GPT-5 shows 1M,
and so on. The curated list lives in `cli/llm/capabilities.py`.

### Background subagents

When the model calls `AgentSpawn(description, prompt)`:

```text
› /background
  Background tasks (newest first):
    bg-1  [running]  Review PR #412 for safety regressions  owner=agent:reviewer  (42s ago)  · dispatched to spawner
```

The spawner callable that actually runs the subagent plugs in via
`ToolContext.extra['agent_spawner']`; out of the box the task registers but
stays `queued` until an adapter lands.

### What's unchanged

Coordinator workflow commands (`/build`, `/eval`, `/optimize`, `/deploy`,
`/skills gap|generate|list`) still go through the coordinator runtime. That's
deliberate — those are agentlab-specific agent-building flows, not chat.

---

## 15. Skills — prompt + tool bundles on disk

Skills live as markdown files with YAML frontmatter. Two locations:

- `~/.agentlab/skills/` — global, available in every workspace
- `<workspace>/.agentlab/skills/` — project-local (wins slug collisions)

### Authoring a skill

```markdown
---
name: commit-helper
description: Write a concise conventional commit for the staged changes
allowed-tools: [Bash, FileRead, Grep]
---

Write a commit message for the currently staged changes.

Rules:
- Use conventional-commit prefix (feat/fix/refactor/docs/test/chore).
- Keep the subject line ≤ 72 chars.
- Include a body only when the change isn't obvious.

Arguments (if any): $ARGUMENTS
```

Frontmatter keys:
- `name` — human title (defaults to filename stem)
- `description` — one-line summary shown in `/skill-list`
- `allowed-tools` — array of exact tool names; anything outside the list is
  denied while the skill runs (composed with plan mode and mode rules)
- Any other keys flow into `skill.extra` without rejection — useful for
  `owner`, `priority`, custom metadata

`$ARGUMENTS` is substituted into the body at invocation; skills that don't
use it still receive arguments appended as `User arguments: ...`.

### Invoking a skill

Three ways:

1. **`/skill <slug> [args]`** — explicit slash dispatch. Shows the expanded
   prompt plus the allowed-tools list.
2. **`/commit`** (when `commit-helper` is loaded and `commit` is the slug) —
   the fuzzy completer surfaces loaded skills as virtual `/slug` completions.
3. **`SkillTool(slug, arguments)`** — the LLM calls it from within a turn.
   The skill runs as a nested orchestrator turn with the allowlist active
   (max 3 levels of recursion).

### Skill-tool allowlist enforcement

During a skill, the permission manager gets a scoped overlay. `FileEdit` is
denied even in `acceptEdits` mode if the skill's frontmatter doesn't list
it. The moment the skill exits, the overlay lifts and normal permissions
return.

### Listing and reloading

```text
› /skill-list
  Loaded skills
      /commit-helper        [workspace]  Write a concise conventional commit
      /deploy-canary        [user]       Run the canary deploy playbook

› /skill-reload               # pick up new / edited files without restart
  Reloaded skills — 2 available.
```

---

## 16. Hooks — automate around every tool call

Hooks declare automation that fires on lifecycle events. Two styles:

### Command hooks (shell)

Runs a shell command with the event payload on stdin. Exit code gates the
action (`PreToolUse` and `OnPermissionRequest` only).

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "./ci/prechecks.sh",
            "timeout_seconds": 10
          }
        ]
      }
    ]
  }
}
```

Exit 0 → tool proceeds. Exit non-zero → blocked with stderr as the
explanation to the model.

### Prompt-fragment hooks (new)

Inject a text fragment into the model's context instead of running a shell
command.

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "prompt",
            "prompt": "Prefer bullet points when summarising tool output.",
            "id": "style-bullets"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "FileRead",
        "hooks": [
          {
            "type": "prompt",
            "prompt": "Summarise the file's purpose in one sentence.",
            "id": "read-summary"
          }
        ]
      }
    ]
  }
}
```

- `PreToolUse` fragments layer onto the system prompt under
  **`## Hook Guidance`** before each model call.
- `PostToolUse` fragments attach to the tool-result message so the next
  model call sees them — scoped by the `matcher` pattern.
- Fragments dedupe by `id` (or content hash) so a single rule doesn't
  repeat across a turn.

### Events

| Event | When it fires | Gating? |
|---|---|---|
| `PreToolUse` | Before a tool runs | ✓ (command) |
| `PostToolUse` | After a tool returns | — |
| `OnPermissionRequest` | Before the permission dialog shows | ✓ (command: 0-exit auto-approves) |
| `Stop` | At session end | — |

### Matchers

Tool names with fnmatch syntax — `matcher: "File*"` matches `FileRead`,
`FileEdit`, `FileWrite`. Empty string matches every tool.

---

## 17. Context, transcript rewind, and sessions

### `/usage` — the context grid

See [Section 14](#context-window-visualisation) — a 4×40 coloured grid plus
a per-role legend, with a red-zone warning at 80% of the window.

### `/context` — coordinator turn history

Shows the 5-turn prior-turn synthesis the coordinator carries forward. This
is separate from the live transcript; it summarises completed workflow turns
(`/build`, `/eval`, `/optimize`, …).

### `/compact`

Summarises the current session to `.agentlab/memory/latest_session.md` so
the next prompt gets a condensed view.

### `/transcript-*` — message-level rewind

Distinct from config `/checkpoint` / `/rewind`:

- **`/transcript-checkpoint [label]`** — snapshot the transcript length.
- **`/transcript-rewind <id>`** — trim the transcript back to that length
  and save the session.
- **`/transcript-checkpoints [--all]`** — list. Default hides auto-saved
  entries (captured after every assistant turn); `--all` shows them.

Auto-snapshots live in `.agentlab/sessions/<session-id>.checkpoints.json`
and survive restarts.

### `/sessions`, `/resume`, `/new`, `/clear`

All unchanged — sessions are still per-workspace JSON in
`.agentlab/sessions/*.json`.

---

## 18. Personalization — themes, output styles, keybindings

### `/theme <name>`

Five bundled palettes: `default`, `claudelight`, `claudedark`, `ocean`,
`nord`. Persisted to `~/.agentlab/config.json` so it sticks across
sessions.

```text
› /theme
  Available themes
    * /theme default      ● ● ● ●
      /theme claudelight  ● ● ● ●
      /theme claudedark   ● ● ● ●
      /theme ocean        ● ● ● ●
      /theme nord         ● ● ● ●

› /theme ocean
  Theme set to 'ocean'. Saved to ~/.agentlab/config.json.
```

### `/output-style <concise | verbose | json>`

Controls transcript verbosity.

- `concise` — tight prose, collapsed tool output, no chrome
- `verbose` — full diagnostics, expanded output, session breadcrumbs (default)
- `json` — one JSON object per turn; scripts can consume without parsing

Persists under `output.style` in workspace `.agentlab/settings.json`.

### Keybindings

Create `~/.agentlab/keybindings.json` to override the defaults:

```json
{
  "mode": "vim",
  "bindings": [
    { "keys": ["ctrl+k", "ctrl+c"], "command": "clear-transcript" },
    { "keys": "ctrl+s", "command": "submit", "when": "prompt" }
  ]
}
```

- `mode`: `"default"` (Emacs-style, default) or `"vim"` (prompt_toolkit's
  vi editing mode, with room to layer overrides in `cli/keybindings/vim.py`).
- `bindings`: a list of `{keys, command, when}` records.
  - `keys` accepts a single string (`"ctrl+s"`) or an array for chords.
  - `command` is a logical action name — registered in
    `cli/keybindings/actions.py`. Typos surface at load time.
  - `when` scopes the binding (currently `"prompt"` or unset).

Built-in actions: `submit`, `cancel`, `interrupt`, `exit`,
`clear-transcript`, `history-previous`, `history-next`, `history-search`,
`completion-next`, `mode-cycle`.

Default vim mode leans on prompt_toolkit's built-in vi emulation (h/j/k/l,
w/b, 0/$, i/a/A/o, dd/yy/p, visual mode, etc.) so you get the full
editor-grade motion set without extra config.

---

## 19. MCP server integration

Existing `.mcp.json` in the workspace root still drives which MCP servers
the workbench knows about. New in the parity release: **their tools
appear in the LLM's tool catalogue** as `mcp__<server>__<tool>`.

### Wiring a client factory

The live REPL needs a factory that returns an `McpClient` for each server
spec. The contract is tiny:

```python
class McpClient(Protocol):
    def list_tools(self) -> list[dict]: ...
    def call_tool(self, name: str, arguments: Mapping) -> dict: ...
```

The factory is passed to `build_workbench_runtime(mcp_client_factory=...)`.
Production setups wrap the official `mcp` SDK client; tests pass a fake.

### What the model sees

Each MCP tool becomes its own `Tool` subclass with the server-reported
`inputSchema` intact. Permission actions are
`tool:mcp:<server>:<tool>`, so rules in `settings.json` can target a single
tool or a whole server:

```json
{
  "permissions": {
    "rules": {
      "allow": ["tool:mcp:github:search_*"],
      "ask":   ["tool:mcp:notion:create_*"],
      "deny":  ["tool:mcp:*:delete_*"]
    }
  }
}
```

### Resilience

A broken server produces a warning via
`runtime.skill_warnings`-style surface but never keeps healthy servers
from registering. Malformed tool descriptors are skipped with a warning
rather than crashing the bridge.

---

## 20. Non-interactive mode (`agentlab print`)

For scripts, CI, and one-shot prompts.

```bash
agentlab print "Summarise README.md" --style concise
# (model streams text to stdout)

agentlab print "List the top 5 risks" --style json
# {
#   "stop_reason": "end_turn",
#   "text": "...",
#   "tool_calls": 2,
#   "usage": {"input_tokens": 4200, "output_tokens": 180}
# }

export AGENTLAB_MODEL=gpt-4o
export OPENAI_API_KEY=sk-...
agentlab print "..."          # routes to OpenAI instead
```

Flags:
- `--style <concise | verbose | json>` — output shape. JSON suppresses
  streaming and emits a single record at end of turn.
- `--system-prompt "..."` — prepend a system prompt for this one call.

Safety: print mode uses a deny-by-default permission dialog — any tool
that would normally prompt gets denied automatically, since there's no
user to ask. Pre-configure the needed allows in `.agentlab/settings.json`
first.

Without an API key, print mode falls back to the `EchoModel` stub so the
command is always exercisable on a fresh clone.

---

## 21. Environment variable reference

| Variable | Effect |
|---|---|
| `AGENTLAB_LLM_ORCHESTRATOR=1` | Enable the live LLM REPL (default: off, classic coordinator) |
| `AGENTLAB_CLASSIC_COORDINATOR=1` | Force-disable the orchestrator even when the opt-in var is set |
| `AGENTLAB_MODEL=<name>` | Model id for the orchestrator / print mode (default `claude-sonnet-4-5`) |
| `ANTHROPIC_API_KEY=sk-ant-...` | Required for Claude models |
| `OPENAI_API_KEY=sk-...` | Required for GPT / o-series models |
| `AGENTLAB_WORKER_MODE=llm` | Switch coordinator workers from deterministic to live LLM |
| `AGENTLAB_SKIP_ONBOARDING=1` | Skip the first-run wizard (CI, scripted setup) |
| `AGENTLAB_SEARCH_BACKEND=<stub\|brave\|tavily>` | Pick a backend for `WebSearch` (stub for tests) |

---

## Architecture pointers

### Classic workbench (coordinator path)
| Concept | Where it lives |
|---|---|
| Coordinator session (owns plan + run state) | `cli/workbench_app/coordinator_session.py` |
| Per-verb worker rosters | `builder/coordinator_turn.py::roles_for_intent` |
| LLM worker adapter | `builder/llm_worker.py` |
| Worker prompt composition | `builder/worker_prompts.py` |
| Plan-mode gate | `cli/workbench_app/plan_gate.py` |
| Checkpoint / rewind | `cli/workbench_app/checkpoint.py` |
| Config version store | `deployer/versioning.py::ConfigVersionManager` |
| Event stream types | `builder/events.py::BuilderEventType` |
| Live event renderer | `cli/workbench_app/coordinator_render.py` |

### Live LLM path (new)
| Concept | Where it lives |
|---|---|
| Slash command registry | `cli/workbench_app/slash.py::build_builtin_registry` |
| Tool registry + base class | `cli/tools/{base,registry}.py` |
| Bundled workspace tools | `cli/tools/{file_read,file_edit,file_write,glob_tool,grep_tool,bash_tool,config_read,config_edit}.py` |
| Web + todo tools | `cli/tools/{web_fetch,web_search,todo_write}.py` |
| AgentSpawn, SkillTool, ExitPlanMode | `cli/tools/{agent_spawn,skill_tool,exit_plan_mode}.py` |
| MCP tool bridge | `cli/tools/mcp_bridge.py` |
| Tool executor (permissions + hooks + dialog) | `cli/tools/executor.py` |
| Permission manager + dialog | `cli/permissions.py`, `cli/workbench_app/permission_dialog.py` |
| Plan-mode workflow | `cli/workbench_app/plan_mode.py`, `plan_slash.py` |
| Context viz + token budgets | `cli/workbench_app/context_viz.py`, `cli/llm/capabilities.py` |
| Transcript rewind | `cli/workbench_app/transcript_checkpoint.py`, `transcript_rewind_slash.py` |
| Streaming markdown | `cli/workbench_app/markdown_stream.py` |
| Disk skills | `cli/user_skills/` |
| Lifecycle hooks | `cli/hooks/` |
| Themes, output style, background panel, init scan | `cli/workbench_app/{theme,output_style,background_panel,init_scan}*.py` |
| Keybindings runtime | `cli/keybindings/` |
| Model client protocol + orchestrator | `cli/llm/{types,orchestrator,streaming,retries,caching}.py` |
| Provider adapters + factory | `cli/llm/providers/` |
| Workbench runtime bundle | `cli/workbench_app/orchestrator_runtime.py` |
| Live REPL wiring | `cli/workbench_app/app.py::run_workbench_app(orchestrator=...)` |
| Non-interactive mode | `cli/print_mode.py` |

Everything runs against the same local workspace state (`.agentlab/`,
`configs/`, `agent_skills/`, `.mcp.json`), so CLI, API, and web console stay
in sync.
