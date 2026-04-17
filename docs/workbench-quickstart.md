# Workbench Quickstart

The AgentLab Workbench is a persistent interactive terminal app:
streaming transcript, slash-command surface, natural-language tool-use,
and live status bar. This guide is the short path from install to
productive use. For the full command reference, see
[CLI Workbench](cli/workbench.md). For the conversational (LLM) layer,
see [Conversational Workbench](r7-workbench-as-agent.md).

## Launch

```
agentlab
```

That's it. The Workbench opens on your default workspace (the
directory containing `.agentlab/`). Type `?` for shortcuts, `/help` for
the full slash-command list, and `/exit` (or `ctrl-d`) to leave.

If `agentlab` isn't on your PATH, run it out of the project venv:

```
/path/to/agentlab/.venv/bin/agentlab
```

## Three things to try first

1. `/eval` — runs the current eval suite. You'll see the case-grid
   progress widget light up as cases complete.
2. `/improve list` — lists queued improvement attempts. If this is a
   fresh workspace, it'll be empty.
3. `what is my current eval verdict?` — natural-language query. The
   Workbench picks an `EvalRun` or `ImproveList` tool, runs it, and
   summarizes the answer. See
   [Conversational Workbench](r7-workbench-as-agent.md).

## R4 Workbench widgets (Slice B/C)

The R4 slice adds inline widgets and slash commands for working with
eval runs, failures, and improvement attempts without leaving the
Workbench.

### Eval case-grid progress

During `/eval`, a compact grid renders one cell per eval case and
color-codes them as cases complete (green=pass, red=fail,
yellow=running, grey=pending). The grid stays inline in the transcript
so you can scroll back and see the final pass/fail pattern for a run.

```
/eval
```

### Failure preview cards

When a case fails, a preview card is rendered inline immediately after
the grid. Each card shows the failing input, the expected vs. observed
output, and a one-line **fix hint** pulled from the failure analyzer —
a starting point for the next `/improve` attempt rather than a full
diagnosis.

```
/eval                # run eval; failure cards render inline automatically
```

### Cost ticker

The status bar carries a `Cost: $X.XX` segment that sums LLM spend
across the current Workbench session: both conversational turns and
LLM-backed slash commands (`/improve analyze`, `/improve propose`,
etc.). It resets when the Workbench session restarts.

Nothing to invoke — the ticker updates automatically after each
assistant turn.

### `/attempt-diff <attempt_id>`

Opens a three-pane diff view for a proposed improvement attempt:
baseline config, candidate config, and the eval delta (per-case score
change, failure-category breakdown). Use it to understand what an
attempt is actually proposing before you accept it.

```
/attempt-diff att_2026_04_17_abc123
```

### `/lineage <id>`

Renders an ancestry tree for any lineage id — an eval run, an attempt,
a deployment, or a measurement. The tree shows the full chain (eval
run -> proposed attempt -> deployment -> post-deploy measurement) so
you can trace where any artifact came from.

```
/lineage att_2026_04_17_abc123
```

### `/improve accept <id> --edit`

Accepting an attempt normally writes the candidate config straight into
the workspace. Passing `--edit` opens the candidate YAML in your
`$EDITOR` first so you can hand-tune the proposal (tweak a prompt,
drop a risky tool, relax a constraint) before the accept completes.
Exit the editor with unsaved changes to abort the accept.

```
/improve accept att_2026_04_17_abc123 --edit
```

## Where to go next

- [Continuous Mode](continuous-mode.md) — run the improvement loop as a
  background daemon with regression / drift alerts.
- [Conversational Workbench](r7-workbench-as-agent.md) — natural-language
  tool use over the same command surface.
- [Tool Permission Reference](r7-tool-permission-reference.md) — how to
  configure `strict-live`, per-tool allowlists, and approvals.
