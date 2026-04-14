# Claude-Style Auto Mode Guide

AgentLab's interactive CLI now defaults to a Claude Code-inspired live harness for long-running text commands. The goal is simple: when AgentLab is doing real work, you should be able to watch the run unfold, see what stage it is in, queue the next instruction, and understand permission mode without waiting for a wall of post-hoc output.

This guide walks through the workflow end to end: provider setup, live mode, the new terminal UI, queued input, permissions, `optimize`, `loop`, and `full-auto`.

## What changed

Long-running interactive commands now use `--ui auto` by default. In an interactive terminal, `auto` resolves to the Claude-style harness. In CI, pipes, redirects, or machine-readable output modes, `auto` resolves to the classic non-interactive renderer.

The live harness gives you:

- A persistent transcript of important model and tool activity
- A compact active-work line with elapsed time and real metrics when available
- A small task checklist showing completed, active, pending, and failed work
- Collapsed Bash/tool output summaries instead of full log dumps
- A bottom prompt region that remains usable while work is running
- Queued input for follow-up prompts and slash commands
- A visible permission footer with Shift+Tab cycling
- Compact status lines for subagents and parallel work when those events are available

The classic text renderer still exists. JSON and JSON-lines output remain pure and never include prompt UI, footers, spinners, or human tips.

## Quick start

Install AgentLab and create a live-first workspace:

```bash
git clone https://github.com/andrewhuot/agentlab.git agentlab
cd agentlab
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

agentlab init --dir my-agent
cd my-agent
```

New workspaces default to live runtime mode. Add a provider key before running real provider-backed work:

```bash
agentlab provider configure \
  --provider openai \
  --model gpt-4o \
  --api-key sk-...
```

The key is saved to `.agentlab/.env` using the provider's default environment variable, such as `OPENAI_API_KEY`. AgentLab prints the variable name it saved, but it does not print the key value.

You can also use exported environment variables instead:

```bash
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export GOOGLE_API_KEY=AI...
```

Check readiness:

```bash
agentlab doctor
agentlab mode show
agentlab provider test --live
```

## Start the interactive shell

```bash
agentlab shell
```

Because `--ui auto` is the default, this opens the Claude-style shell in a usable TTY. The shell keeps the prompt available while a command is running. If you submit text during active work, AgentLab queues it and shows the queued item immediately.

Examples:

```text
agentlab> Build a refund support agent with PII guardrails
agentlab> /status
agentlab> tighten escalation handling for missing-order cases
```

If the first request is still running, `/status` and the follow-up instruction are queued and drained in order at the next safe boundary. Queued input does not interrupt an already-running provider call.

Force the Claude-style UI:

```bash
agentlab shell --ui claude
```

Use the classic shell:

```bash
agentlab shell --ui classic
```

`--ui claude` requires an interactive terminal. If you use it through a pipe, redirect, or CI job, AgentLab fails clearly and asks you to use `--ui auto` or `--ui classic`.

## Run optimize with live progress

```bash
agentlab eval run
agentlab optimize --cycles 3
```

In an interactive terminal, `optimize` renders as one live session. You should see the current cycle, active stage, task progress, tool summaries, warnings, and metrics as they arrive.

Common options:

```bash
agentlab optimize --cycles 1
agentlab optimize --continuous
agentlab optimize --cycles 3 --ui classic
agentlab optimize --cycles 3 --ui claude
```

Use `--ui classic` when you want the older line-by-line text behavior. Use `--ui claude` when you specifically want the live harness and want a clear failure if no interactive terminal is available.

## Run the continuous loop

```bash
agentlab loop run
```

The loop observes workspace health, proposes improvements, evaluates candidates, and deploys accepted changes according to the loop settings. In the Claude-style harness, each loop pass appears as a compact set of observe, propose, evaluate, deploy, and canary tasks.

Examples:

```bash
agentlab loop run --max-cycles 5
agentlab loop run --delay 60
agentlab loop run --ui classic
```

The harness only shows token, cost, or thinking details when AgentLab has real provider or harness data. It does not invent live metrics.

## Run full-auto as one live session

`full-auto` combines optimize and loop into one long-running autonomous workflow:

```bash
agentlab full-auto --yes
```

With the default `--ui auto`, an interactive terminal gets one coherent live harness session for both stages:

1. Optimize runs the requested number of cycles.
2. Loop continues with observe/propose/evaluate/deploy passes.
3. Permission decisions still come from AgentLab's `PermissionManager`.
4. The footer keeps the current permission mode visible throughout the run.

Useful variants:

```bash
agentlab full-auto --cycles 3 --max-loop-cycles 10 --yes
agentlab full-auto --yes --ui classic
agentlab full-auto --yes --ui claude
```

`--yes` acknowledges the dangerous full-auto workflow. If permissions already allow `full_auto.run`, AgentLab can proceed according to the current permission configuration; otherwise, the acknowledgement gate remains authoritative.

## Permission modes

The live footer always shows the current permission mode:

```text
bypass permissions on (shift+tab to cycle)
```

Use Shift+Tab in the live shell to cycle supported modes. If your terminal does not send Shift+Tab, use slash commands or the normal permissions CLI:

```bash
agentlab permissions show
agentlab permissions set default
agentlab permissions set acceptEdits
agentlab permissions set dontAsk
agentlab permissions set bypass
```

The footer is a display and keybinding layer. It does not bypass `PermissionManager`; existing permission checks remain the source of truth.

## UI mode reference

Long-running interactive commands accept:

```bash
--ui auto
--ui claude
--ui classic
```

| Mode | Behavior |
|------|----------|
| `auto` | Default. Uses Claude-style UI in an interactive TTY outside CI; otherwise uses classic text. |
| `claude` | Forces the Claude-style UI and fails clearly without a usable interactive terminal. |
| `classic` | Uses the old text/spinner behavior. Useful for scripts, logs, and terminals that do not work well with live prompt regions. |

You can also set:

```bash
export AGENTLAB_CLI_UI=auto
export AGENTLAB_CLI_UI=claude
export AGENTLAB_CLI_UI=classic
```

Command-line `--ui` values take precedence over the environment variable.

## Structured output stays machine-readable

The live UI is only for human text output. Machine-readable modes are intentionally isolated:

```bash
agentlab optimize --output-format json
agentlab optimize --output-format stream-json
agentlab loop run --output-format stream-json
agentlab workbench build "..." --output-format stream-json
```

These modes never render prompt UI, permission footers, spinners, tips, or collapsed terminal fragments. `stream-json` remains valid JSON lines only.

## API key workflows

For first-run setup, use one of these paths.

### Save a key through AgentLab

```bash
agentlab provider configure --provider openai --model gpt-4o --api-key sk-...
```

This updates:

- `.agentlab/providers.yaml`
- `agentlab.yaml`
- `.agentlab/.env`

It also flips the runtime config away from mock mode for the configured provider profile.

### Use an environment variable

```bash
export OPENAI_API_KEY=sk-...
agentlab provider configure --provider openai --model gpt-4o
agentlab provider test --live
```

### Stay in mock mode intentionally

```bash
agentlab init --dir mock-agent --mode mock
cd mock-agent
agentlab mode set mock
```

Mock mode remains useful for demos, tests, and offline exploration. Live mode is the default for new workspaces, but mock mode is still explicit and supported.

## What to watch while it runs

The live harness is designed to make long-running model work inspectable:

- **Transcript:** durable messages worth reading later
- **Active line:** current stage, elapsed time, thinking state, and real metrics when known
- **Task list:** the current prioritized checklist, with older completed work collapsed when space is tight
- **Tool summaries:** command, elapsed time, line count, exit status, and recent output tail
- **Queued input:** follow-up prompts and slash commands waiting for the next safe boundary
- **Footer:** permission mode and keybinding hint

If a command emits subagent progress, the renderer shows compact agent lines with agent name, state, last action/tool, and counters when available.

## Troubleshooting

### The Claude-style UI did not appear

Check whether the command is running in a real TTY:

```bash
agentlab optimize --cycles 1 --ui claude
```

If this fails with an interactive-terminal error, use a normal terminal window or fall back to:

```bash
agentlab optimize --cycles 1 --ui classic
```

### Output is being parsed by another tool

Use JSON output instead of text:

```bash
agentlab optimize --output-format stream-json
```

Do not combine machine parsing with the live prompt UI.

### Shift+Tab does not cycle permissions

Some terminals do not send Shift+Tab to prompt_toolkit. Use:

```bash
agentlab permissions set acceptEdits
```

Then restart the shell or continue with the configured permission mode.

### A queued prompt did not affect the current provider call

That is expected. Queued input drains after the active turn or at a safe stage boundary. It does not mutate an in-flight provider request.

### Provider calls are not live

Run:

```bash
agentlab mode show
agentlab provider list
agentlab provider test --live
agentlab doctor
```

If no key is configured, save one:

```bash
agentlab provider configure --provider openai --model gpt-4o --api-key sk-...
```

## Recommended daily workflow

```bash
agentlab init --dir support-agent
cd support-agent
agentlab provider configure --provider openai --model gpt-4o --api-key sk-...
agentlab doctor

agentlab shell
# Build or revise from the live prompt.

agentlab eval run
agentlab optimize --cycles 3
agentlab review list
agentlab full-auto --cycles 3 --max-loop-cycles 10 --yes
```

Use the live UI when a human is watching the work. Use classic or structured output when another program is watching it.
