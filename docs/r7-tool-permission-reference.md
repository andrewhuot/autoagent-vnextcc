# Tool Permission Reference

The conversational Workbench (see [r7-workbench-as-agent.md](r7-workbench-as-agent.md))
exposes seven AgentLab commands as model-callable tools. Three are
read-only and auto-allow; four mutate workspace or production state
and ask before running. Workspace overrides live in
`.agentlab/settings.json` under `permissions.rules`.

## Tool reference

| Tool | Default | Action string | What it does |
|---|---|---|---|
| `ImproveList` | allow | `tool:ImproveList` | List recent optimization attempts. Read-only. |
| `ImproveShow` | allow | `tool:ImproveShow` | Show one attempt's full details. Read-only. |
| `ImproveDiff` | allow | `tool:ImproveDiff` | Show config diff for an attempt. Read-only. |
| `EvalRun` | ask | `tool:EvalRun` | Run an eval suite. Costs LLM tokens; writes a row to the eval-run store. |
| `ImproveRun` | ask | `tool:ImproveRun` | Run an optimization attempt (eval → propose → score). Costs LLM tokens. |
| `ImproveAccept` | ask | `tool:ImproveAccept` | Promote an attempt to the active config. Mutates workspace. |
| `Deploy` | ask | `tool:Deploy:<strategy>` | Deploy to canary or full (or rollback / status). Mutates production. The strategy in the action string lets you allowlist canary while still asking for full. |

The three read-only tools carry `read_only = True` on the
`AgentLabTool` subclass and short-circuit to `allow` inside
`PermissionManager.decision_for_tool` before any policy lookup. The
four mutating tools route through `PermissionManager.decision_for`
with the action string above. `Deploy` builds its action string
dynamically from the `strategy` argument — typically
`tool:Deploy:canary` or `tool:Deploy:immediate`.

## Overriding defaults

`.agentlab/settings.json` accepts `permissions.rules.allow`,
`permissions.rules.ask`, and `permissions.rules.deny` as glob lists.
Patterns use `fnmatch` semantics, so `tool:Deploy:*` matches every
strategy and `tool:*` matches every tool.

### Allowlist canary, deny full

Routine canary rollouts run without prompts; full-traffic deploys
are explicitly off-limits and the orchestrator must pick a different
strategy or surface the denial:

```json
{
  "permissions": {
    "rules": {
      "allow": ["tool:Deploy:canary"],
      "deny": ["tool:Deploy:full"]
    }
  }
}
```

### Auto-allow eval runs

Useful in long sessions where you trust the model to call `EvalRun`
without asking each time:

```json
{
  "permissions": {
    "rules": {
      "allow": ["tool:EvalRun"]
    }
  }
}
```

## Precedence chain

When a tool needs a decision, `PermissionManager.decision_for(action)`
walks the chain in order and returns the first match. Highest tier
wins:

1. `_session_deny` — in-memory hard-block from the permission dialog
   (e.g. you picked "deny" with "always for this conversation").
2. `_session_allow` — in-memory "always-yes" from the same dialog.
3. Explicit workspace `deny` from `permissions.rules.deny`.
4. Explicit workspace `ask` from `permissions.rules.ask`.
5. Explicit workspace `allow` from `permissions.rules.allow`.
6. The AgentLab session-ask preset (forces `ask` for `EvalRun`,
   `ImproveRun`, `ImproveAccept`, `Deploy:*`).
7. Mode defaults from `_MODE_RULES` in `cli/permissions.py` (the
   mode from `permissions.mode` in settings — `default`,
   `acceptEdits`, `plan`, `dontAsk`, `bypass`).

A few short examples of how that chain plays out:

- Workspace allowlists `tool:EvalRun`. Default mode would `ask`, the
  AgentLab preset would also `ask`, but the explicit allow at tier 5
  wins. The model runs `EvalRun` without prompting.
- The user picks "deny always for this conversation" on
  `tool:Deploy:immediate`. The session-deny entry at tier 1 wins
  even if `permissions.rules.allow` includes `tool:Deploy:*`. The
  session deny is dropped when the REPL exits.
- Workspace settings define no rules. Tier 6 fires: `EvalRun`,
  `ImproveRun`, `ImproveAccept`, and `Deploy:*` are all `ask`;
  read-only tools auto-allow at the `decision_for_tool` short-circuit
  before the chain runs.

For the conversational quickstart, permission UI walkthrough, and
strict-live setting, see
[r7-workbench-as-agent.md](r7-workbench-as-agent.md).
