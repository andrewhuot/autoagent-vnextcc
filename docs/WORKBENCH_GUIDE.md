# Workbench Guide — end-to-end

> Interactive, Claude-Code-style harness for building, evaluating, optimizing,
> and deploying agents. This is the default mode of `agentlab` — plain
> `agentlab` in a workspace drops you straight into it.

Quick links: [Setup](#0-first-time-setup-one-time-2-min) · [Launch](#1-launch-the-workbench) ·
[Build](#2-describe-what-you-want-to-build) · [Eval](#4-eval-the-current-candidate) ·
[Plan mode](#5-plan-mode-for-risky-runs) · [Optimize](#6-optimize-from-evidence) ·
[Checkpoint / rewind](#7-checkpoint--rewind-to-explore-safely) ·
[Deploy](#8-deploy-with-gates) · [Skills](#9-skills-to-close-gaps) ·
[Daily loop](#10-daily-iteration-loop) · [Power moves](#11-power-moves) ·
[Troubleshooting](#12-troubleshooting)

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
| `plan` | Every coordinator turn gates through the approval screen first |
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

Before a risky operation:

```text
› /checkpoint about to try aggressive policy rewrite
  Snapshot saved v017 (v017.yaml) — about to try aggressive policy rewrite
```

If the next few builds make things worse:

```text
› /checkpoints
  Checkpoints (newest first):
    v017 v017.yaml · about to try aggressive policy rewrite
    v015 v015.yaml · pre_execution:run-abc123
    v013 v013.yaml · manual

› /rewind v015
  Rewound to version v015 (v015.yaml)
  (Forward versions (if any) were marked rolled_back.)
```

Candidates can also be inspected and promoted directly:

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

Build-time skills are reusable mutations the harness can apply during any
verb. They live in `agent_skills/` and the coordinator surfaces them as
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

The next `/build` picks new skills up automatically via `skill_candidates`
injection.

---

## 10. Daily iteration loop

```text
Morning:
  agentlab
  /sessions              # list recent
  /resume                # pick the one from yesterday
  /tasks                 # show last coordinator run + workers
  /context               # see the 5-turn memory window

Mid-day:
  /eval                  # check overnight regression
  /optimize              # tighten based on loss
  /checkpoint "EOD checkpoint"

End of day:
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
| `&long-task` | Kick off as background task (footer counter) |

Full slash command index (run `/help` for live copy):

| Command | Purpose |
|---|---|
| `/build` | Build or refine the active agent via coordinator workers |
| `/eval` | Run evals + loss analysis |
| `/optimize` | Axis-scoped optimizer (instruction / guardrail / callback) |
| `/deploy` | Gate + canary + rollback plan |
| `/skills gap \| generate <slug> \| list` | Skill surfacing + authoring |
| `/tasks` | Latest coordinator plan, worker states, queued work |
| `/context` | Prior-turn synthesis the coordinator is carrying forward |
| `/diff [version]` | Unified YAML delta between active and a candidate |
| `/accept <version>` | Promote a candidate to active |
| `/reject <version>` | Roll back a candidate without touching active |
| `/checkpoint [reason]` | Snapshot the current active config |
| `/rewind <version>` | Promote a prior version back to active |
| `/checkpoints` | List recorded snapshots (newest first) |
| `/review` | Pending review cards from worker output |
| `/cost` | Session cost summary |
| `/doctor` | Workspace + Coordinator diagnostics |
| `/memory` | Show AGENTLAB.md contents |
| `/status` | Workspace status |
| `/config` | Active config info |
| `/mcp` | MCP integration status |
| `/sessions` | Recent Workbench sessions |
| `/resume [session_id]` | Resume the most recent session |
| `/new [title]` | Fresh session + clear transcript |
| `/clear` | Wipe transcript but keep session |
| `/compact` | Summarize session to memory |
| `/save` | Materialize active candidate |
| `/model` | Select model for the next turn |
| `/help [command]` | Show commands or one-command detail |
| `/shortcuts` | Keyboard cheatsheet |
| `/exit` \| `/quit` | Exit |

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

---

## Architecture pointers

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
| Slash command registry | `cli/workbench_app/slash.py::build_builtin_registry` |

Everything runs against the same local workspace state (`.agentlab/`,
`configs/`, `agent_skills/`), so CLI, API, and web console stay in sync.
