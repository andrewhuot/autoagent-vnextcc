# Conversational Workbench

The Workbench REPL accepts free-form natural language alongside its
slash-command surface. R7 added an LLM tool-use loop on top of the
existing CLI: when you ask a question, the model picks AgentLab
commands as tools (`EvalRun`, `Deploy`, `ImproveRun`, `ImproveList`,
`ImproveShow`, `ImproveDiff`, `ImproveAccept`), runs them in-process,
and streams the answer back. Slash commands typed verbatim
(`/eval`, `/deploy`, `/improve`, …) still work unchanged — chat is
additive.

For the underlying tool surface, default policies, and override
syntax, see [Tool Permission Reference](r7-tool-permission-reference.md).

## What is conversational Workbench?

A conversational Workbench session wraps the same in-process
commands you already invoke from `agentlab eval`, `agentlab improve`,
and `agentlab deploy`, but exposes them through an LLM that can plan
multi-step work. The model decides which tool to call, with what
arguments, and how to interpret the result. You stay in the loop:
mutating tools (everything except the three read-only `Improve*`
inspection tools) prompt for approval before they fire, and the
permission table is auditable in `.agentlab/settings.json`. Read-only
tools auto-allow because prompting on every list-attempts call would
just train you to mash Enter.

## Quickstart

```
$ agentlab            # opens the Workbench REPL
> what's my current eval verdict and what's failing?
```

The first time you ask, the model picks `EvalRun` (or reads the most
recent cached run if one exists) and may follow up with `ImproveList`
to surface known failure clusters. It then summarizes in plain
English. The first `EvalRun` call prompts for permission — pick
"yes, and don't ask again this conversation" if you want the rest of
the session to run without further prompts.

## Three example queries

These are concrete, useful examples worth pasting into a fresh
Workbench:

- **"What's my current eval verdict and what's failing?"**
  Reads the most recent eval run via `EvalRun` (or a cached result),
  then calls `ImproveList` to pull rejected attempts, and summarizes
  the verdict and top failure categories in one paragraph.

- **"Improve safety on case 12 and tell me what changed."**
  Calls `ImproveRun` (prompts for approval), then `ImproveDiff` on
  the resulting attempt id to show the config delta. Read-only
  `ImproveDiff` doesn't prompt; the mutating `ImproveRun` does. Both
  results are streamed back inline.

- **"Deploy the best canary candidate."**
  Calls `ImproveList`, picks the highest-scoring proposed attempt,
  prompts for approval on `ImproveAccept`, then prompts again on
  `Deploy` with `strategy="canary"`. Two prompts, two distinct
  approvals — by design, since one promotes the attempt and the
  other shifts traffic.

## How permissions work

Permissions are a three-tier model:

1. **Read-only tools auto-allow.** `ImproveList`, `ImproveShow`,
   and `ImproveDiff` declare `read_only = True` and short-circuit to
   `allow` before the policy table is consulted. They never prompt.

2. **Mutating tools ask before running.** `EvalRun`, `ImproveRun`,
   `ImproveAccept`, and `Deploy:*` ship as `ask` via the Workbench
   permission preset. The dialog gives three choices: "yes once,"
   "yes always for this conversation," and "no." The "always for
   this conversation" choice persists into `_session_allow` until
   you exit the REPL.

3. **Workspace-level overrides live in `.agentlab/settings.json`**
   under `permissions.rules.allow|ask|deny`. Anything you put there
   beats the in-process preset, so a user who allowlists
   `tool:Deploy:canary` will not get prompted for canary deploys but
   will still get prompted for `tool:Deploy:immediate`. See
   [Tool Permission Reference](r7-tool-permission-reference.md) for
   the full action-string table and override examples.

The session-allow tier (option 2 above) sits at the very top of the
precedence chain — it beats workspace explicit rules — so a
mid-conversation "always allow" decision wins until you exit. The
preset's force-ask layer sits below explicit workspace rules, so a
user who deliberately allowlisted a tool keeps that decision.

## Strict-live mode

Workspaces that opt into `permissions.strict_live: true` in
`.agentlab/settings.json` refuse to launch a conversational Workbench
session unless a real provider key is configured. The intent is CI
and production hardening — if a workspace is supposed to talk to a
real model, silently falling back to the echo provider is a worse
failure than refusing to start.

```json
{
  "permissions": {
    "strict_live": true
  }
}
```

When `strict_live` is true and no provider key is detected, the
runtime constructor raises `MockFallbackError` and the CLI exits
with code `12` (`EXIT_MOCK_FALLBACK`). The error message names
the missing variable explicitly:

```
chat: workspace is strict-live but no provider key is configured.
Set ANTHROPIC_API_KEY (or the appropriate provider key) and retry,
or remove permissions.strict_live from .agentlab/settings.json.
```

The flag only gates the conversational chat runtime. Individual
commands (`agentlab eval`, `agentlab build`, etc.) keep their own
`--strict-live` flag and continue to exit `12` on mock fallback.

## Past conversations

Conversations persist to `.agentlab/conversations.db` (one SQLite
file per workspace). The `agentlab conversation` command group
exposes them headlessly — no REPL required.

```
agentlab conversation list --limit 5
```

Lists the five most recent conversations as
`<id>  <updated_at>  <model>  (<n> messages)`. Pass `--json` for
machine-readable output.

```
agentlab conversation export <id> --format markdown > transcript.md
```

Dumps a conversation as a Markdown transcript suitable for sharing
in a code review or pasting into Slack. Tool results in the
exported transcript are wrapped in
`<tool_result tool="..." status="...">…</tool_result>` fences. Those
fences are a safety hint to anyone reading the transcript: the
content inside is data that came back from a tool, not user
instructions. The same data/instructions distinction is enforced
inside Workbench by the prompt-injection guard, and the export
preserves the convention so re-feeding a transcript into another
LLM session does not silently let tool output rewrite the prompt.

Other subcommands in the group:

- `agentlab conversation show <id>` — full message history in the
  current terminal (or `--json` for the raw record).
- `agentlab conversation resume <id>` — write `<id>` into
  `.agentlab/workbench_session.json` so the next `agentlab` REPL
  launch picks it up as the active conversation.

## Resuming after a crash

Kill the REPL mid-tool-call (Ctrl-C while `Deploy` is running, lid
slammed shut, runaway process killed) and pending tool calls in the
SQLite store are tagged `interrupted` on the next load. Reopen
Workbench and you'll see a one-line resume hint at the top:

```
Conversation conv_a1b2c3 was interrupted with 1 pending tool call.
Type /resume conv_a1b2c3 to continue.
```

Type `/resume` to pick up the most recent conversation, or
`/resume <id>` to pick a specific one. The orchestrator's message
history is rehydrated from SQLite (with each tool-result body
truncated to 600 chars to keep the context window honest — full
output is still browsable via `agentlab conversation show <id>`).
The interrupted tool call is visible as a `[tool: Deploy →
interrupted]` line in the rehydrated history so the model knows
where it stopped.

## Workspace-change notice

If the active config path changes mid-conversation — typically
because you ran `/build` or `/improve` and a new candidate landed —
the Workbench surfaces a one-line warning:

```
  ⚠  Active config switched to configs/v007.yaml. The current
  conversation may be working with stale context. Type /fork to
  start a new conversation, or /resume <old_id> to keep going.
```

`/fork` mints a new conversation row, swaps the bridge to point at
it, and clears the orchestrator's in-memory message buffer. The
previous conversation stays in the SQLite store and remains
addressable via `agentlab conversation show <id>` or `/resume
<id>`. If you ignore the warning, the conversation continues with
the old in-memory context — which is sometimes what you want, but
note that subsequent tool calls will see the new active config and
the model is now operating on potentially stale assumptions.

The warning fires only on a real change (an explicit non-None →
non-None transition). Initial workspace load doesn't trigger it.

## Cost tracking

Every assistant turn updates `WorkbenchSession.cost_ticker_usd`
from the LLM usage report. The status bar shows the running total.
Pricing comes from `cli/llm/capabilities.py`, which holds per-model
input and output costs per million tokens. The calculator accepts
both Anthropic (`input_tokens`/`output_tokens`) and OpenAI
(`prompt_tokens`/`completion_tokens`) usage shapes; an unknown
model or empty usage adds zero rather than blocking the turn.

The number is an **estimate**. Provider pricing changes — the
capabilities table is updated when we notice — and a stale entry
will silently report the wrong number. Treat it as a budget guide,
not a billing document. The provider's own dashboard remains the
source of truth.
