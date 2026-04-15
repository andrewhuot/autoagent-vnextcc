# What's new — Claude-Code parity release (2026-04-15)

A compact tour of everything shipped in the two big commits
(`c2a376c`, `0e5f4ed`, `af2247c`). For the full manual see
[`WORKBENCH_GUIDE.md`](./WORKBENCH_GUIDE.md).

---

## TL;DR

Turn it on:

```bash
export AGENTLAB_LLM_ORCHESTRATOR=1
export ANTHROPIC_API_KEY=sk-ant-...         # or OPENAI_API_KEY
export AGENTLAB_MODEL=claude-sonnet-4-5     # optional, this is the default
cd your-agent-workspace
agentlab
```

You now have a live tool-calling REPL with streaming markdown, per-tool
permission dialogs, plan mode, skills, hooks, transcript rewind, MCP
tools, background subagents, themes, output styles, and vim keybindings.
Slash workflow commands (`/build`, `/eval`, `/optimize`, `/deploy`, `/ship`)
still route through the coordinator because they do agentlab-specific work.

Roll back any time with `export AGENTLAB_CLASSIC_COORDINATOR=1`.

---

## What got added

### 1. Real model adapters + streaming
- `cli/llm/providers/`: `AnthropicClient` (streaming, tool use, prompt
  caching, thinking blocks) and `OpenAIClient` (function-calling
  translation).
- `cli/llm/streaming.py`: tagged-union event protocol (text_delta,
  tool_use_{start,delta,end}, thinking_delta, usage, message_stop) plus
  `collect_stream()` that rebuilds a `ModelResponse`.
- `cli/llm/retries.py`: exponential-backoff retry policy with injectable
  sleep and a provider-agnostic `should_retry` callback.
- `cli/llm/caching.py`: Anthropic prompt-cache breakpoint composer for
  stable system-prompt + tool-schema prefixes.
- `cli/llm/providers/factory.py`: one call (`create_model_client`) picks
  the right adapter by model-name prefix; echo fallback for keyless runs.

### 2. Per-tool permission dialog
Every tool call the LLM makes hits the permission layer:

```text
  Permission requested: FileEdit
    Edit configs/v014.yaml

  [a] Approve once
  [s] Approve always (this session)
  [p] Approve always (save to settings.json)
  [d] Deny
```

Read-only tools auto-allow. Session overrides ("s") live in memory; persistent
overrides ("p") append to `.agentlab/settings.json`. Permission rules use
action strings like `tool:FileEdit:configs/*.yaml` with fnmatch semantics.

### 3. Plan mode as a first-class workflow
Elevated from a permission flag into a four-state machine
(`idle → drafting → approved → archived`) with its own slash commands:
`/plan`, `/plan-approve`, `/plan-discard`, `/plan-done`, `/plan-list`. Plans
persist to `.agentlab/plans/<id>.md` and auto-restore on workbench restart.

The LLM can finalise a plan via the new `ExitPlanMode` tool — the user sees
the plan in the permission dialog and confirms before mutating tools unlock.

### 4. Bundled workspace tools
Ready for the LLM to invoke:

- `FileRead`, `FileWrite`, `FileEdit` — exact-string edits, path-safe.
- `Glob`, `Grep` — workspace-scoped, noise-dir filtered.
- `Bash` — 120s timeout, workspace cwd, output truncation.
- `ConfigRead`, `ConfigEdit` — schema-validated YAML/JSON mutations.
- `WebFetch` — urllib-backed, secret-redacting, HTML-stripping.
- `WebSearch` — pluggable backend (stub, Brave, Tavily).
- `TodoWrite` — persists to `.agentlab/todos.json` with id-based merge.
- `AgentSpawn` — registers a subagent task in the background panel.
- `SkillTool` — runs a disk skill as a nested orchestrator turn with the
  skill's tool allowlist enforced.
- `ExitPlanMode` — transitions the drafting plan to approved.

### 5. Disk-loaded skills (Claude-Code-style)
Markdown + YAML-frontmatter files under
`<workspace>/.agentlab/skills/` or `~/.agentlab/skills/` become callable via
`/skill <slug>`, virtual `/slug` completions, or `SkillTool`.

```markdown
---
name: commit-helper
description: Write a conventional commit for staged changes
allowed-tools: [Bash, FileRead, Grep]
---

Write a commit message. $ARGUMENTS
```

While a skill runs, the permission manager gets a scoped allowlist overlay —
any tool not listed is denied, even in `acceptEdits` mode.

### 6. Lifecycle hooks (two flavours)
Declared in `settings.json::hooks`:

- **Command hooks** — shell commands with event payload on stdin; exit code
  gates.
- **Prompt-fragment hooks** — text injected into the model's context at
  `PreToolUse` / `PostToolUse`. Dedupe by id.

Events: `PreToolUse`, `PostToolUse`, `OnPermissionRequest`, `Stop`.

### 7. Context visualisation (per-model)
`/usage` renders a coloured 4×40 grid of token usage by role (system / user
/ assistant / tools / free), plus a legend and red-zone warning. Context
limits come from `cli/llm/capabilities.py` — Claude 4.x shows 200k, GPT-5
shows 1M, unknown models fall back to 200k.

### 8. Transcript rewind (message-level)
Distinct from config versioning:

- `/transcript-checkpoint [label]` — snapshot the transcript length.
- `/transcript-rewind <id>` — trim back and save.
- `/transcript-checkpoints [--all]` — list (default hides auto-snapshots).

### 9. Streaming markdown renderer
Fence detection (`` ``` ``), inline diff highlighting, CRLF normalisation.
Folds partial text into complete lines as tokens arrive so code blocks
never render half-styled.

### 10. Background task panel
`/background` shows subagent / long-running task state (queued / running /
completed / failed) with elapsed time. `/background-clear` drops
terminated tasks.

### 11. `/init` workspace scanner
Walks `configs/`, `agent/`, `evals/`, `.agentlab/skills/`, `.agentlab/plans/`
and writes/updates `AGENTLAB.md` — preserving any hand-written sections
outside the auto-managed `<!-- detected -->` block. `--dry-run` previews;
`--fresh` overwrites the scaffold.

### 12. Themes + output styles
- `/theme <default|claudelight|claudedark|ocean|nord>` — persisted to
  `~/.agentlab/config.json`.
- `/output-style <concise|verbose|json>` — transcript verbosity /
  machine-readable mode, persisted to workspace settings.

### 13. Keybindings JSON loader + opt-in vim mode
`~/.agentlab/keybindings.json` declares bindings with chord support.
`"mode": "vim"` switches prompt_toolkit into vi editing mode (h/j/k/l,
w/b, dd/yy/p, visual mode). Default stays Emacs-style.

### 14. MCP tool bridge
Any `.mcp.json`-declared server's tools flow into the registry as
`mcp__<server>__<tool>`. Permission actions
(`tool:mcp:<server>:<tool>`) support fine-grained rules. Resilient to a
single broken server.

### 15. Fuzzy slash completer
Subsequence matching (`/ppr` surfaces `/plan-approve`), plus loaded skills
appear as virtual `/slug` completions. Collision-suppressed when a
built-in already owns the slug.

### 16. Non-interactive `agentlab print`
```bash
agentlab print "Summarise README.md"                    # concise streaming
agentlab print "Top 5 risks" --style json               # one JSON record
agentlab print "..." --system-prompt "Reply in bullets" # per-call system
```

### 17. LLM orchestrator + live REPL wiring
`cli/llm/orchestrator.py::LLMOrchestrator` composes tool registry,
permissions, hooks, plan workflow, skill registry, transcript rewind,
background panel, and streaming renderer into one `run_turn()`.

`cli/workbench_app/orchestrator_runtime.py::build_workbench_runtime()` is
the single constructor that wires every subsystem.

`run_workbench_app(orchestrator=...)` routes natural-language turns
through it. `launch_workbench()` auto-builds the runtime when
`AGENTLAB_LLM_ORCHESTRATOR=1` is set.

---

## Migration notes

**Nothing is mandatory.** Default behaviour is unchanged for every existing
workspace — the opt-in env var is the switch.

**If you opt in:**
1. Existing `settings.json::permissions` rules still apply. The new
   `tool:*` actions stack on top; old action strings (`config.write`,
   `deploy.*`, etc.) work as before.
2. Coordinator slash commands keep their existing behaviour. Only
   natural-language turns change.
3. Tests that drove the old coordinator path (e.g. `test_workbench_app_stub`)
   don't set `orchestrator=` so they stay on the classic path — no
   migration needed.

**If you've written custom hooks:** the default `type: command` still works.
To add a prompt-fragment hook, just change `type` to `"prompt"` and supply
`prompt`/`id` instead of `command`.

**If you've been manually editing AGENTLAB.md:** `/init` only rewrites the
sentinel-bracketed `## Detected` block; your custom sections are preserved.

---

## Recipes

### Plan a risky change, then execute with a tool allowlist

```text
› /plan refactor the retries library to use exponential backoff
  Plan started: refactor the retries library to use exponential backoff  [DRAFTING]

› (model uses FileRead/Grep to study the current code, then calls ExitPlanMode)
  Permission requested: ExitPlanMode
    1. Rewrite cli/llm/retries.py to accept backoff_factor from env.
    2. Update all 4 call sites.
    3. Add regression tests under tests/.

  [a] Approve once  [d] Deny

› a
  Plan 'refactor the retries library to use exponential backoff' approved.

› (model now has access to FileEdit + FileWrite under normal permissions)
```

### Author a skill, then let the LLM invoke it

```bash
cat > .agentlab/skills/risk-review.md <<'EOF'
---
name: risk-review
description: Audit a PR for safety and compliance regressions
allowed-tools: [FileRead, Grep, WebFetch]
---

Review the changes staged in git. Flag any regressions in:
- secrets handling
- auth boundaries
- error swallowing
- PII logging

Use FileRead / Grep only. Do not edit files.
Target: $ARGUMENTS
EOF

agentlab
› /skill-reload
› Can you run the risk-review skill on the recent FileEdit changes?
  (model calls SkillTool(slug="risk-review", arguments="recent FileEdit changes")
   under a scoped allowlist of FileRead/Grep/WebFetch only)
```

### Inject a prompt-fragment hook for every tool call

```json
// .agentlab/settings.json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "prompt",
            "prompt": "Cite exact file paths when referencing code.",
            "id": "cite-paths"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "prompt",
            "prompt": "If the shell command failed, explain the exit code in plain English.",
            "id": "bash-explain"
          }
        ]
      }
    ]
  }
}
```

### One-shot CI run

```bash
export AGENTLAB_LLM_ORCHESTRATOR=1
export ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY_FROM_SECRETS
agentlab print "Summarise the eval regressions in outputs/eval_results/*.json" \
  --style json > ci-summary.json
```

---

## Where to look in the code

Architecture pointers live at the end of
[`WORKBENCH_GUIDE.md`](./WORKBENCH_GUIDE.md#architecture-pointers). Key
entry points:

- `cli/workbench_app/orchestrator_runtime.py::build_workbench_runtime` —
  one constructor that wires every subsystem.
- `cli/llm/orchestrator.py::LLMOrchestrator.run_turn` — the per-turn loop.
- `cli/tools/executor.py::execute_tool_call` — the sole seam for
  permission + hooks + skill allowlist + dialog.
- `cli/llm/providers/factory.py::create_model_client` — pick a provider.

---

## Remaining parity gaps

This release targets parity for the agent build loop and Claude-style operator
experience, not every Claude Code command or integration. The remaining gaps
are tracked as lower priority because they do not block the
`build -> eval -> optimize -> review -> ship` workflow:

- Git workflow commands beyond the existing local release/deploy path.
- IDE, mobile, remote handoff, voice, and auth surfaces.
- Plugin management and install/update UX.
- Notebook editing and language-server integrations.
- REPL-only helpers and PowerShell-specific command surfaces.

The supported shipping path is `agentlab deploy --auto-review --yes`, with
`agentlab ship --yes` as a visible shortcut that uses the same implementation
path. In Workbench, `/ship` prepares the same canary-first deploy intent, and
`/permissions [show|set <mode>]` delegates to the root permission controls.

---

## Running the full test suite

```bash
source .venv/bin/activate
python -m pytest tests/ -q
cd web && npm test -- --run && npm run build
```

Expected as of the workflow hardening pass:

- Python: **5,397 passed, 1 skipped**.
- Web tests: **56 files passed, 403 tests passed**.
- Web build: passes; Vite still warns that the main JS chunk is larger than
  500 kB after minification.
