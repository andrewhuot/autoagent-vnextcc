# AgentLab Quick Start

Get from clone to a working AgentLab workspace in a few minutes.

## Prerequisites

- Python 3.11+
- Node.js 20+ if you want the web UI or local frontend dev tools

## Install

```bash
git clone https://github.com/andrewhuot/agentlab.git agentlab
cd agentlab
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 1. Create a workspace

```bash
agentlab new my-agent --template customer-support --demo
cd my-agent
```

Why `--demo`?

- it seeds reviewable demo data
- it makes the review and deploy surfaces interesting on a brand-new workspace
- it keeps the first walkthrough reproducible even before you connect a live runtime

## 2. Inspect the default XML instruction

New workspaces start with an XML root instruction in `prompts.root`.

```bash
agentlab instruction show
agentlab instruction validate
```

If you want to replace the draft from a short brief:

```bash
agentlab instruction generate --brief "customer support agent for order tracking and refunds" --apply
agentlab instruction validate
```

## 3. Build the first config

```bash
agentlab build "customer support agent for order tracking, refunds, and cancellations"
```

This stages a new config, generates build artifacts, and writes starter eval cases you can run immediately.

## 4. Improve: the unified loop (recommended)

`agentlab improve` is the one command that owns the full lifecycle from
"I have an agent" to "I shipped a measured improvement." Each step
threads the same `attempt_id` through eval → optimize → deploy →
measurement, so you can always trace a live release back to the
proposal that created it.

```bash
agentlab improve run configs/my-agent.yaml
```

This runs eval, runs one optimization cycle, and shows you the top
proposal (with its `attempt_id` and diff). If it looks right:

```bash
agentlab improve accept <attempt_id>
```

Canary-deploys the config tied to that attempt and schedules a
post-deploy measurement. After the canary window settles:

```bash
agentlab improve measure <attempt_id>
```

Runs a fresh eval against the live config and records the actual
`composite_delta`. You can now trace the full chain:

```bash
agentlab improve lineage <attempt_id>
# eval_run → attempt → deployment → measurement

agentlab improve diff <attempt_id>
# full config diff + rationale

agentlab improve list
# every attempt with its status and deployment state
```

### Running pieces individually

If you want to drive each step by hand instead of through `improve run`:

```bash
agentlab eval run          # just the eval
agentlab optimize --cycles 1   # just the optimizer
agentlab deploy --auto-review --yes  # deploy the latest accepted config
```

All three still emit lineage events, so `agentlab improve lineage` and
`agentlab improve list` reflect their output regardless of whether you
went through the unified command or the per-step commands.

Pass `agentlab optimize --explain-strategy` to see one rationale line per ranked strategy (effectiveness scores from reflection plus any epsilon-greedy exploration pick). Composite scoring weights live in `agentlab.yaml` under `eval.composite.weights` and are inspected/mutated via `agentlab eval weights show|set|validate`; every `CompositeScore` snapshots the weights it was scored under, so historical scores re-render stably even after the yaml changes. When a real provider key is configured, the pairwise LLM judge is used for `a_vs_b` comparisons (with a 30-day SQLite cache at `.agentlab/llm_judge_cache.db`); the heuristic judge remains the default and fallback.

## Trusting the loop: strict-live mode

By default, every AgentLab command (`build`, `eval run`, `optimize`,
`improve run`) will fall back to deterministic mock execution when a
live provider isn't configured or a provider call fails mid-flight.
This is fine for smoke testing, but catastrophic in CI: a green eval
against mock doesn't mean the agent works against the real provider.

Pass `--strict-live` to force a hard failure instead:

```bash
agentlab improve run configs/my-agent.yaml --strict-live
agentlab eval run --strict-live
agentlab build "my agent description" --strict-live
agentlab optimize --cycles 3 --strict-live
```

`--strict-live` flows from `improve run` into the underlying eval and
optimize steps automatically, so you only need to set it in one place.

If any step would have silently fallen back to a mock, AgentLab now exits
with code `12` and prints the warnings that would have been swallowed.
This makes it safe to wire `--strict-live` into CI gates.

Other exit codes worth knowing:

- `13` — deploy was attempted on a workspace whose latest eval verdict is Degraded or Needs Attention. Either run `agentlab eval run` after a fix, or override with `--force-deploy-degraded --reason "<reason>"`.
- `14` — live mode requested but no provider credentials are configured. Run `agentlab doctor` for setup help.

### Diagnosing why mock mode kicked in

`agentlab doctor` now tells you WHY you're in mock mode:

- **Disabled** — live; all good.
- **Configured** — your `agentlab.yaml` says `optimizer.use_mock: true`. Set it to `false` when you're ready for production.
- **Missing provider key** — no `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY` / `GEMINI_API_KEY` detected. Export one and rerun, or paste one during `agentlab init`.

## What next?

- `agentlab improve list` — see every proposal, its status, and deployment state
- `agentlab improve lineage <attempt_id>` — trace an attempt's full chain
- `agentlab status` — see workspace health and next recommended commands
- `agentlab build show latest` — inspect the latest build artifact
- `agentlab instruction edit` — open the active XML instruction in your editor
- `agentlab instruction migrate` — convert an older plain-text instruction to XML
- `agentlab shell` — open the interactive shell
- `agentlab advanced` — see the broader command surface
- [XML Instructions](xml-instructions.md) — full XML authoring and override workflow
- [Detailed Guide](DETAILED_GUIDE.md) — full CLI walkthrough
- [UI Quick Start](UI_QUICKSTART_GUIDE.md) — browser walkthrough

## Troubleshooting

**`agentlab: command not found`**

Activate the virtualenv again:

```bash
source .venv/bin/activate
which agentlab
```

**`No workspace found`**

You are outside a workspace directory. Either `cd` into the workspace you created, or create one with:

```bash
agentlab new my-agent --template customer-support
```

**Provider credentials missing**

That is okay. AgentLab auto-detects mock mode when no API keys are set. To switch to live providers later:

```bash
agentlab provider configure
agentlab provider test
agentlab mode set live
```

**`No candidate config version available to deploy`**

Stage or accept a version first:

```bash
agentlab build "Describe your agent"
```

or

```bash
agentlab review apply pending
```

or

```bash
agentlab optimize --cycles 1
```
