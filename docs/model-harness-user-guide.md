# Model Harness User Guide

Last updated: 2026-04-12

This guide explains how to use the AgentLab model harness end to end — from
your first build to iteration, validation, and recovery. It covers both
the CLI and the Workbench UI, and it describes the product as it actually
works today, including where things are still rough.

If you want the 5-minute version, start at [Fastest way to get started](#fastest-way-to-get-started).

## What is the model harness?

The model harness is the execution engine inside AgentLab's Workbench that
manages the full lifecycle of building an agent from a natural-language
brief. When you describe what you want ("Build a customer support agent for
order tracking and refunds"), the harness:

1. **Plans** — generates a structured task tree (instructions, tools,
   guardrails, eval cases, environment source)
2. **Executes** — runs each task, producing artifacts and applying
   operations to a canonical model
3. **Reflects** — runs deterministic quality checks after each task group
4. **Presents** — emits final metrics, validation results, and a handoff
   summary

This cycle is the same whether you use the CLI or the Workbench UI. The
harness also supports **iteration**: you can send follow-up feedback and
it will re-run a focused subset of the plan without rebuilding from
scratch.

The harness works without external API keys. When no live provider is
configured, it uses intelligent deterministic generation seeded from your
brief. This means you can explore the full flow in mock mode before
connecting real LLM providers.

## Key concepts and mental model

### The canonical model

Everything the harness produces is stored in a single structured object
called the **canonical model**. This is the source of truth for your
agent — it contains agents, tools, guardrails, eval suites, and
environment definitions. ADK Python files and CX JSON exports are
downstream compiler output, never the primary record.

### Runs, turns, and iterations

- A **run** is one execution session of the harness. It has a status
  (`queued`, `running`, `reflecting`, `presenting`, `completed`,
  `failed`, `cancelled`) and tracks budget usage (iterations, tokens,
  cost, time).
- A **turn** is one user-initiated interaction within a run. The first
  turn creates the initial build; subsequent turns are follow-ups.
- An **iteration** is one pass through the plan→execute→reflect→present
  cycle within a turn. A turn may contain multiple iterations if
  auto-iterate is enabled or the user manually requests corrections.

### Phases

Every run progresses through these phases in order:

```
queued → planning → executing → reflecting → presenting → terminal
```

In practice, you will see the executing and reflecting phases interleave:
the harness reflects after each *task group* completes (not just at the
end), so you get quality signals incrementally.

### Artifacts

Each completed task produces an **artifact** — a generated piece of your
agent. Artifacts have categories:

| Category      | What it contains                                     |
|---------------|------------------------------------------------------|
| `agent`       | Agent role, instructions, model assignment            |
| `tool`        | Tool schema and implementation source                 |
| `guardrail`   | Safety or policy rule                                 |
| `eval`        | Test case for evaluation                              |
| `environment` | Rendered source code (e.g., `agent.py`)               |
| `note`        | Generic annotation or feedback application            |

Artifacts are versioned. On iteration, the harness generates updated
versions rather than creating entirely new artifacts.

### Budgets

Every run tracks four budget dimensions:

- **Iterations** — how many plan passes have run (default cap: 3)
- **Tokens** — estimated token usage across all generation steps
- **Cost** — estimated cost in USD (approximate, based on ~$0.000003/token)
- **Time** — wall-clock elapsed milliseconds

If any limit is breached, the run emits a `run.budget_exceeded` event
and cancels gracefully. You can set limits when starting a build or
in `agentlab.yaml`.

## Fastest way to get started

### CLI path (< 5 minutes)

```bash
# 1. Create a workspace with demo data
agentlab new my-agent --template customer-support --demo
cd my-agent

# 2. Build an agent from a brief
agentlab build "customer support agent for order tracking, refunds, and cancellations"

# 3. See what was generated
agentlab build show latest
agentlab instruction show
```

That gives you a versioned config, generated eval cases, and a build
artifact. Everything runs in mock mode if you have no API keys set — that
is fine for exploring.

### UI path (< 5 minutes)

```bash
# 1. Start the backend and frontend
./start.sh
# (or: agentlab server  in one terminal, cd web && npm run dev  in another)

# 2. Open the browser
#    http://localhost:5173
```

Navigate to the **Workbench** page (or access it from the sidebar). Type a
brief like "Build a support agent for order tracking and refunds" in the
chat input and press **⌘↵** (or Enter). The harness streams the build
live.

## End-to-end CLI flow

### Step 1: Create a workspace

```bash
agentlab new my-agent --template customer-support --demo
cd my-agent
```

The `--demo` flag seeds reviewable demo data so the review and deploy
surfaces are interesting even before you connect a live runtime. Without
it, you start with a minimal workspace.

### Step 2: Check workspace health

```bash
agentlab status
agentlab doctor
agentlab mode show
```

`status` shows overall health and suggests next commands. `doctor` runs
diagnostic checks. `mode show` tells you whether you are in `mock`,
`live`, or `auto` mode.

**Mock mode is a valid operating mode**, not an error state. AgentLab
auto-detects mock mode when no API keys are set, and the harness
generates domain-aware content deterministically.

### Step 3: Build

```bash
agentlab build "customer support agent for order tracking, refunds, and cancellations"
```

This runs the full harness cycle:
1. Plans a task tree with 5 groups (agent, tools, guardrails, environment,
   eval)
2. Executes each task, generating artifacts
3. Reflects on each group's quality
4. Presents the final result with metrics

The CLI prints progress and writes:
- A versioned config in `configs/`
- Generated eval cases in `evals/cases/`
- A build artifact in `.agentlab/`

### Step 4: Inspect the result

```bash
agentlab build show latest      # summary of what was built
agentlab instruction show       # view the XML root instruction
agentlab instruction validate   # check it for structural issues
agentlab config list            # see all versioned configs
```

### Step 5: Run evals

```bash
agentlab eval run
agentlab eval show latest
```

### Step 6: Iterate

```bash
agentlab optimize --cycles 1
```

If the eval passes, this may report "no optimization needed." If it finds
improvements, it proposes and evaluates a change.

### Step 7: Review and deploy

```bash
agentlab review list
agentlab deploy --auto-review --yes
agentlab deploy status
```

## End-to-end Workbench UI flow

The Workbench is a two-pane interface inspired by Manus-style agent
builders:

```
┌──────────────────────────────────────────────────┐
│  ◂  Project Name   [portable · v1]   ● Running   │  ← top bar
├────────────────────────┬─────────────────────────┤
│  conversation feed     │  artifact viewer        │
│  (plan tree, messages, │  (preview / source /    │
│   artifact cards,      │   diff, category tabs,  │
│   reflection cards)    │   activity timeline)    │
├────────────────────────┤                         │
│  chat input            │                         │
│  [iteration controls]  │                         │
└────────────────────────┴─────────────────────────┘
```

### Step 1: Open the Workbench

Start the app with `./start.sh` and open `http://localhost:5173`. Navigate
to the Workbench page. On first load, the page hydrates a default project
from the server.

### Step 2: Submit a brief

Type your agent description in the chat input at the bottom left. Press
**⌘↵** or **Enter** to start the build.

The build streams in real time:
- The **plan tree** appears in the left pane, showing task groups and
  their statuses (pending → running → done)
- **Assistant narration** streams as the harness works through tasks
- **Artifact cards** appear inline as each task completes
- The **HarnessMetricsBar** in the top bar shows: current phase, step
  progress (e.g., "7/12 steps"), tokens used, estimated cost, and
  elapsed time

### Step 3: Watch the phases

The status pill in the top bar shows the current phase:

| Status pill  | What is happening                                        |
|--------------|----------------------------------------------------------|
| `Starting`   | Request sent, waiting for first event                    |
| `Running`    | Plan received, tasks are executing                       |
| `Reflecting` | Quality checks running on completed task groups          |
| `Presenting` | Final validation, exports, and handoff assembly          |
| `Done`       | Build completed successfully                             |
| `Error`      | Something failed — check the error message               |
| `Cancelled`  | You or a budget limit stopped the run                    |

### Step 4: Explore artifacts

The **right pane** has tabs:

- **Artifacts** — browse generated artifacts by category (all, agent,
  tool, guardrails, eval, environment). Toggle between Preview and Source
  views.
- **Agent** — view the canonical model snapshot
- **Source** — rendered source code
- **Evals** — generated eval cases
- **Trace** — execution trace
- **Activity** — timeline of run events

Click any artifact card in the left pane to focus it in the right pane.
The viewer auto-focuses the newest artifact unless you manually selected
one in the last 3 seconds.

### Step 5: Review reflection results

After each task group completes, a **ReflectionCard** appears in the
conversation feed showing:
- A quality score (0–100, color-coded red/amber/green)
- A list of suggestions with **Apply** buttons

Clicking "Apply" on a suggestion starts a follow-up iteration with that
suggestion as the feedback.

### Step 6: Iterate

Once a build completes, **IterationControls** appear below the chat input:

- **Iterate** button — opens an inline textarea for follow-up feedback
- **Compare with v{N}** — activates diff mode to compare the current
  version against a previous one
- **Version selector** (v1, v2, v3…) — pick which version to diff against

Type your follow-up message and submit. The harness runs a focused delta
plan that only re-executes tasks affected by your feedback, rather than
rebuilding everything.

The iteration history is visible in a collapsible list showing each
iteration's message and artifact count.

### Step 7: Auto-iterate

The chat input includes an **auto-iterate checkbox** and a **max passes
slider** (1–6). When enabled:
- If validation fails after a build pass, the harness automatically starts
  another iteration to fix the issues
- This continues until validation passes or the max iteration cap is
  reached

Default: auto-iterate on, max 3 passes.

### Step 8: Cancel a running build

Click the **Stop** button (visible during running/reflecting/presenting
states) to cancel. This sends a cancel request to the server, which
sets the run status to `cancelled` at the next cooperative boundary.

### Keyboard shortcuts

| Key          | Action                                  |
|--------------|-----------------------------------------|
| `⌘K`         | Focus the chat input                    |
| `⌘↵` / Enter | Submit the current message              |
| `⌘←` / `⌘→`  | Cycle through artifacts in right pane   |

## How runs progress through phases

Here is the detailed sequence of what happens inside a single build run:

### 1. Planning

The harness infers a domain from your brief (e.g., "Refund Support",
"Airline Support", "IT Helpdesk") and builds a nested task tree with
five groups:

1. **Plan** — shape agent scope, role, and instructions
2. **Tools** — design tool schemas, generate source
3. **Guardrails** — identify safety flows, author policy rules
4. **Environment** — render executable source code
5. **Eval** — draft test cases

The tree is emitted as a `plan.ready` event and rendered as an
expandable tree view in the UI.

### 2. Executing

For each leaf task in the tree:
1. Emit `task.started`
2. Generate the artifact (via LLM if configured, or deterministic
   template engine)
3. Emit `task.progress` with a log line
4. Emit `artifact.updated` with the generated content
5. Apply any model operations (adding a tool, updating instructions, etc.)
6. Emit `task.completed`
7. Save a checkpoint

Metrics update every 3 steps (or on the last step) via
`harness.metrics` events.

### 3. Reflecting

After all tasks in a group complete, the harness runs a **deterministic**
reflection — not an LLM call. It checks:
- Were all expected artifacts generated?
- Is each artifact long enough (> 20 characters)?
- Is the artifact category valid?
- Do the artifacts reference keywords from the original brief?

The quality score is computed as:

```
score = max(0.4, (1.0 - issue_count × 0.2) × min(1.0, brief_coverage × 2))
```

The floor is 0.4, so partial results still show a positive signal. A
`reflection.completed` event carries the score and any suggestions.

**Important**: reflection is intentionally fast and cheap. It catches
obvious structural problems (missing artifacts, empty content) but does
not do deep semantic review. Think of it as a quick sanity check, not a
comprehensive audit.

### 4. Presenting

After all tasks and reflections complete:
1. Final `harness.metrics` with total elapsed time, tokens, and cost
2. `build.completed` with all applied operations, the plan ID, and
   metrics
3. Deterministic validation runs (see next section)
4. Export compilation (ADK `.py` and CX `.json`)
5. Compatibility diagnostics for the selected target
6. `run.completed` with the full project snapshot

## Validation, review gates, and handoff summaries

### Deterministic validation

After each build, `run_workbench_validation()` runs three checks:

| Check                    | What it verifies                                  |
|--------------------------|---------------------------------------------------|
| `canonical_model_present`| At least one agent exists in the canonical model  |
| `exports_compile`        | ADK Python and CX JSON exports rendered           |
| `target_compatibility`   | No invalid objects for the selected deploy target |

The result arrives as a `validation.ready` event and is displayed in the
UI. Status is either `passed` or `failed`.

### Review gates

The run envelope includes a `review_gate` field with a promotion status
that can be:

- `draft` — initial output, not yet reviewed
- `reviewed` — human has looked at it
- `candidate` — approved for staging
- `staging` — deployed to staging
- `production` — promoted to production

**Current state**: the review gate infrastructure is present in the data
model, but the full approval workflow is not yet wired into the harness
lifecycle. The `ApprovalRequest` dataclass and SQLite storage exist, but
gating a build on human approval is not enforced automatically. For now,
use the review and deploy CLI commands (or the Improvements page in the
UI) to manage promotions manually.

### Handoff summaries

Each run persists:
- **Turn records** — user-initiated build turns with their own plans,
  artifacts, and statuses
- **Iteration records** — each pass within a turn, with applied
  operations
- **Conversation history** — flat message log preserved across restarts
- **Activity log** — structured events (create, apply, test, rollback)
- **Version history** — config snapshots without full model copies

This means you can reload the Workbench page and see the full
conversation and plan state restored from the server. The handoff data
also provides enough context for an operator to understand what was
built and what state it is in.

## How iteration and follow-up works

### Manual iteration

In the UI, click "Iterate" after a completed build and type your
feedback (e.g., "Add a refund approval tool" or "Make the guardrails
stricter about PII"). The harness:

1. Emits `iteration.started` with the iteration index and follow-up
   message
2. Builds a **delta plan** that routes to the relevant task groups
   (instructions, tools, guardrails, or eval)
3. For each affected artifact, generates an **updated version** rather
   than creating a new artifact from scratch
4. Runs the same reflect→present cycle on the modified artifacts

In the CLI, iteration happens through the optimize loop or by running
another `agentlab build` command.

### Applying reflection suggestions

Each reflection card in the UI includes "Apply" buttons for its
suggestions. Clicking one starts an iteration with that suggestion text
as the follow-up message — it is equivalent to typing the suggestion
yourself.

### Version comparison

After iteration 2+, the IterationControls show a "Compare with v{N}"
button. This activates a **diff view** in the artifact viewer, showing
inline line-level differences between the current version and the
selected comparison version.

## Cancellation, failure, and recovery

### Cancellation

**From the UI**: click the Stop button during any active phase. The
frontend sends `POST /api/workbench/runs/{run_id}/cancel` and aborts the
local SSE stream. The server marks the run as `cancelled` at the next
cooperative checkpoint.

**From budget limits**: if a budget dimension is breached (iterations,
tokens, cost, or time), the server emits `run.budget_exceeded` and
initiates graceful cancellation.

Cancellation is cooperative, not instant. The harness checks for
cancellation between task steps, so it will finish the current step
before stopping.

### Failure

If the harness encounters an error during execution, it emits `run.failed`
with an error message and marks the run as `failed`. The UI transitions
to the `error` state and displays the error message.

Common failure causes:
- Provider API errors (when in live mode)
- Invalid project state
- Internal harness errors

### Crash recovery

If the server process crashes or restarts while a run is active, the
harness has a **stale run recovery** mechanism:

- When a project is loaded, the server checks for runs stuck in active
  states (`queued`, `running`, `reflecting`, `presenting`)
- If a run's `updated_at` timestamp is older than 30 minutes, it is
  marked as `failed` with reason `stale_interrupted`
- A `run.recovered` event is emitted so the UI can display a recovery
  message
- The stale threshold is configurable via the
  `AGENTLAB_WORKBENCH_STALE_RUN_SECONDS` environment variable

**What crash recovery does NOT do**: it does not resume interrupted builds.
The harness saves checkpoints after each completed task (infrastructure
for future resumption), but today, recovery simply marks the stale run as
failed so you can start a new one.

### After a failure or cancellation

You can always start a new build from the same project. The canonical
model, conversation history, and turn records persist, so you are not
starting from zero. In the Workbench UI, just type another message in
the chat input — it begins a new turn on the same project.

## What to trust vs what is still evolving

This section is intentionally candid about the current state.

### Reliable today

- **The plan→execute→reflect→present cycle**: this is the core loop and
  it works end to end in both CLI and UI.
- **Mock mode generation**: produces realistic, domain-aware artifacts
  without requiring API keys. Good for exploration and demos.
- **Real-time streaming**: SSE events flow reliably from server to UI.
  Plan trees, artifact cards, metrics, and messages all update live.
- **Multi-turn conversation**: the UI preserves turns, messages, and
  artifacts across page reloads. The server-side store is durable.
- **Validation checks**: the three deterministic checks
  (canonical_model_present, exports_compile, target_compatibility) run
  after every build.
- **Cancellation**: cooperative cancellation via the Stop button or budget
  limits works as described.
- **Stale run recovery**: interrupted runs are correctly detected and
  marked on project reload.
- **Budget tracking**: iteration, token, cost, and time budgets are
  enforced.

### Best-effort or limited

- **Reflection quality scores**: the deterministic reflection catches
  obvious structural issues but does not deeply evaluate semantic
  quality. A score of 0.85 means the artifacts are structurally present
  and reference the brief — not that the agent will perform well.
- **Review gate enforcement**: the data structures exist (promotion
  status, approval requests), but gating builds on human approval is
  not enforced in the harness lifecycle yet. Use the CLI review commands
  or the Improvements page.
- **Checkpoint resumption**: checkpoints are saved after each task, but
  the harness cannot resume a build from a checkpoint yet. Today,
  checkpoints are observability data.
- **Live LLM generation**: when a provider is configured, the harness
  routes to it for content generation. This path exists and works, but
  the template-based mock generation is more thoroughly tested.
- **Cost estimates**: token counts use a ~4 chars/token approximation and
  cost uses a fixed $0.000003/token rate. These are ballpark figures,
  not billing-accurate.
- **Presentation data**: the `present.ready` event can carry a summary,
  next actions, review gate status, and handoff data. The UI renders
  what it receives, but the server-side assembly for presentation is
  not deeply customizable yet.

### Rough edges

- The "Create agent" button in the Workbench top bar is disabled — the
  promotion flow is under development.
- Auto-iterate can feel opaque when it runs multiple passes without clear
  user visibility into what changed. Watch the iteration history for
  context.
- The activity tab in the artifact viewer is populated by run events but
  can feel sparse for short builds.
- Error messages from failed runs sometimes surface internal details
  rather than user-friendly explanations.

## Practical troubleshooting tips

### "Workbench failed to load"

The Workbench page could not hydrate the default project from the
server. Check that the backend is running:

```bash
agentlab server
# or check: curl http://localhost:8000/docs
```

### The build completes but shows 0 artifacts

This usually means the brief was too vague for the domain inference to
produce meaningful content. Try a more specific brief:

```text
# Instead of:
"Build an agent"

# Try:
"Build a customer support agent that handles order tracking, refund requests, and cancellation flows"
```

### The status pill is stuck on "Running"

If the status does not transition after the stream ends, it may be a
stale connection. Refresh the page — the Workbench will re-hydrate from
the server and the stale run recovery mechanism will mark interrupted
runs as failed after 30 minutes.

### Auto-iterate ran too many passes

Lower the max iterations slider (next to the auto-iterate checkbox) or
disable auto-iterate entirely. The default cap is 3 passes.

### Validation says "exports_compile" failed

The ADK or CX export could not be rendered from the canonical model. This
usually means the model is in an inconsistent state. Try building again
with a clearer brief, or inspect the canonical model via the Agent tab in
the right pane.

### Mock mode vs live mode

If you see `execution_mode: mock` in the metrics or stream data, the
harness is using template-based generation. To switch to live LLM
providers:

```bash
agentlab provider configure
agentlab provider test
agentlab mode set live
```

In the UI, check the Setup page for provider readiness.

### "Run interrupted after process recovery"

This means the server detected a stale run from a previous session. The
run was marked as failed. Start a new build — your project state
(canonical model, conversation, artifacts) is preserved.

## Related docs

- [Quick Start](QUICKSTART_GUIDE.md) — 5-step rapid setup
- [Detailed Guide](DETAILED_GUIDE.md) — full CLI walkthrough
- [UI Quick Start](UI_QUICKSTART_GUIDE.md) — browser walkthrough
- [Core Concepts](concepts.md) — workspace, config versions, modes
- [Harness Engineering](HARNESS_ENGINEERING.md) — internal design
  patterns and eval stack
- [Platform Overview](platform-overview.md) — all product surfaces
- [CLI Reference](cli-reference.md) — complete command listing
- [API Reference](api-reference.md) — REST API endpoints
