# Platform overview

AutoAgent is a continuous optimization platform for AI agents. It watches how your agent performs, figures out what's going wrong, generates targeted fixes, proves they work with statistical testing, and deploys them — in a loop that runs for hours, days, or weeks without intervention.

This page walks through every major subsystem so you know what's available and when to use it.

---

## The optimization loop

Everything in AutoAgent centers on a single closed loop:

```
Trace  →  Diagnose  →  Search  →  Eval  →  Gate  →  Deploy  →  Learn  →  Repeat
```

The loop is fully autonomous but human-interruptible at every stage. You can pause it, pin specific config surfaces from mutation, reject experiments, or set budget caps. When something goes wrong, failures land in a dead letter queue — the loop never crashes.

Each pass through the loop produces a reviewable **experiment card**: a structured record of what was tried, what changed, whether it worked, and how to roll it back.

---

## Tracing and diagnosis

### Trace collection

AutoAgent records structured telemetry from every agent invocation — not just the final answer, but every tool call, agent transfer, state delta, and model call along the way. Traces are stored as hierarchical span trees in SQLite with indexes for fast lookup by trace, session, or agent path.

### Trace grading

Seven span-level graders score individual trace spans for fine-grained diagnosis:

| Grader | What it evaluates |
|--------|-------------------|
| Routing | Was the correct specialist agent selected? |
| Tool selection | Was the right tool chosen for the task? |
| Tool arguments | Were tool arguments correct and complete? |
| Retrieval quality | Did retrieval return relevant, sufficient context? |
| Handoff quality | Was context preserved across agent handoffs? |
| Memory use | Was memory read/written appropriately? |
| Final outcome | Did the span achieve its intended result? |

Each grader returns a score with evidence, so you can see exactly where in a trace the agent went wrong.

### Blame maps

Span-level grades are aggregated into **blame clusters** — groups of related failures organized by root cause. Each cluster gets an impact score based on frequency, severity, and business impact. Trend detection identifies patterns that are getting worse over time.

### Opportunity queue

Blame clusters feed into a ranked opportunity queue that replaces binary "needs optimization" flags with a priority-scored list. Each opportunity includes the failure family, recommended mutation operators, and expected lift. The optimizer pulls from this queue to decide what to fix next.

---

## Search and mutations

### Typed mutations

Nine built-in mutation operators target specific configuration surfaces:

| Operator | What it changes | Risk level |
|----------|----------------|------------|
| Instruction rewrite | Agent instructions | Low |
| Few-shot edit | Example conversations | Low |
| Temperature nudge | Generation settings | Low |
| Tool hint | Tool descriptions | Medium |
| Routing rule | Agent routing logic | Medium |
| Policy patch | Safety/business policies | Medium |
| Model swap | Underlying LLM | High |
| Topology change | Agent graph structure | High |
| Callback patch | Callback handlers | High |

Low-risk mutations can auto-deploy. High-risk mutations always require human review.

### Search strategies

The search engine generates candidate mutations from the opportunity queue. Four strategies are available, from simple to research-grade:

**Simple** — One mutation per cycle, greedy selection. Good for getting started.

**Adaptive** — Bandit-guided operator selection using UCB1 or Thompson sampling. Learns which operators work for which failure families over time.

**Full** — Multi-hypothesis search with curriculum learning. Generates diverse candidates, evaluates in parallel, and rotates holdout sets to prevent overfitting.

**Pro** — Research-grade prompt optimization algorithms:
- **MIPROv2** — Bayesian search over (instruction, example set) pairs
- **BootstrapFewShot** — Teacher-student demonstration bootstrapping (DSPy-inspired)
- **GEPA** — Gradient-free evolutionary prompt adaptation with tournament selection
- **SIMBA** — Simulation-based iterative hill-climbing

---

## Evaluation engine

### Eval modes

Seven evaluation modes cover different aspects of agent quality:

- **Target response** — Does the agent produce the expected output?
- **Target tool trajectory** — Does the agent call the right tools in the right order?
- **Rubric quality** — How well does the response score against defined criteria?
- **Rubric tool use** — How well does tool usage score against criteria?
- **Hallucination** — Does the response contain unsupported claims?
- **Safety** — Does the response violate safety policies?
- **User simulation** — Does a simulated user find the response helpful?

### Dataset management

Eval datasets are split into four types:

- **Golden** — Curated, high-confidence test cases
- **Rolling holdout** — Automatically rotated to prevent overfitting
- **Challenge / adversarial** — Edge cases and adversarial inputs
- **Live failure queue** — Bad production traces converted to eval cases automatically

### Statistical rigor

Every evaluation includes statistical significance testing:

- **Clustered bootstrap** — Accounts for conversation-level correlation
- **Sequential testing** — O'Brien-Fleming alpha spending for early stopping
- **Multiple-hypothesis correction** — Holm-Bonferroni when testing several mutations
- **Judge variance estimation** — Accounts for LLM judge noise in significance calculations
- **Minimum sample size** — Won't declare significance with too few examples

### Anti-Goodhart guards

Three mechanisms prevent your eval scores from becoming meaningless:

- **Holdout rotation** — Tuning, validation, and holdout partitions rotate on a configurable interval
- **Drift detection** — Monitors the gap between tuning and validation scores; flags overfitting
- **Judge variance bounds** — If judge noise exceeds a threshold, the system warns before trusting results

---

## Judge stack

Evaluation scoring uses a tiered judge pipeline. Each tier is faster and cheaper than the next, so expensive LLM judges only run when simpler methods can't decide:

1. **Deterministic** — Pattern matching, keyword checks, schema validation. Instant, zero cost, confidence = 1.0.
2. **Similarity** — Token-overlap Jaccard scoring against reference answers. Fast and cheap.
3. **Binary rubric** — LLM judge with structured yes/no rubric questions. The primary scoring layer for most evals.
4. **Audit judge** — A second LLM from a different model family reviews borderline cases. Catches systematic judge errors.

The judge stack also includes:

- **Versioning** — Track judge changes and their impact on scores over time
- **Drift monitoring** — Detect shifts in judge agreement rates
- **Human feedback calibration** — Corrections from human review improve judge accuracy
- **Position and verbosity bias detection** — Identify systematic biases in LLM judges

---

## Gating and deployment

### Metric hierarchy

Every optimization decision flows through four layers, evaluated top-down:

| Layer | Role | What happens if it fails |
|-------|------|--------------------------|
| **Hard gates** | Safety, auth, state integrity, P0 regressions | Mutation rejected immediately |
| **North-star outcomes** | Task success, groundedness, satisfaction | Must improve to be promoted |
| **Operating SLOs** | Latency, cost, escalation rate | Must stay within bounds |
| **Diagnostics** | Tool correctness, routing accuracy, handoff fidelity | Observed but not gated |

A mutation that improves task success by 12% but trips a safety gate is rejected. No exceptions.

### Experiment cards

Every optimization attempt produces a structured experiment card:

- Hypothesis and target surfaces
- Config SHA for reproducibility
- Risk classification
- Baseline and candidate scores
- Statistical significance (p-value, confidence interval)
- Diff summary and rollback instructions
- Status lifecycle: pending → running → accepted / rejected / archived

Cards form a complete audit trail. You can inspect any past experiment to understand what was tried and why.

### Canary deployment

Winning mutations are deployed via configurable canary rollout:

- Set the percentage of traffic that sees the new config
- Monitor for regressions during rollout
- Promote to full deployment or rollback with one command
- Full deployment history with version tracking

---

## AutoFix copilot

AutoFix analyzes failure patterns and generates constrained improvement proposals. Each proposal includes:

- Root cause analysis with evidence
- Suggested mutation type and target surface
- Expected lift and risk assessment
- Confidence score

Proposals go through a review-before-apply workflow. You see exactly what will change, approve or reject, and track the full proposal lifecycle.

---

## NL scorer generation

Describe what "good" looks like in plain English:

> "The agent should acknowledge the customer's frustration, look up their order, and provide a specific resolution within 3 turns."

AutoAgent converts this into a structured `ScorerSpec` with named dimensions, rubric criteria, and weight distribution. You can refine the scorer iteratively and test it against real traces before using it in production evals.

---

## Context engineering workbench

Diagnostics for agent context window usage:

- **Growth pattern detection** — Identifies linear, exponential, sawtooth, or stable growth
- **Utilization analysis** — How much of the context window is actually used
- **Failure correlation** — Links context state (size, staleness) to failure patterns
- **Compaction simulation** — Test aggressive, balanced, and conservative compaction strategies before deploying them

---

## Registry

A versioned registry for four types of agent configuration:

| Type | What it stores | Example |
|------|---------------|---------|
| **Skills** | Instruction bundles with examples and constraints | "Handle refund requests" |
| **Policies** | Hard and soft enforcement rules | "Never reveal internal pricing" |
| **Tool contracts** | Tool schemas with side-effect classification | "order_lookup: read-only, 4s timeout" |
| **Handoff schemas** | Routing rules with validation | "billing queries → billing_agent" |

All entries are versioned with SQLite-backed storage. Supports import/export, search, version diffing, and deprecation.

---

## Intelligence studio

Build agents from conversation data rather than from scratch:

1. **Upload** a ZIP archive with transcripts (JSON, CSV, or TXT)
2. **Analyze** — AutoAgent classifies intents, maps transfer reasons, extracts procedures, and generates FAQs
3. **Research** — Run deep quantified analysis with root-cause ranking and evidence
4. **Ask** — Query your conversation data in natural language ("Why are people transferring to live support?")
5. **Build** — One-click agent generation from conversation patterns
6. **Optimize** — Autonomous loop: select top insight → draft change → simulate → deploy

### Knowledge mining

Successful conversations are mined for durable knowledge assets — FAQ entries, procedure documentation, and best-practice patterns that feed back into agent instructions.

---

## Assistant builder

Chat-based agent building for when you want to describe your agent in natural language rather than writing config files:

- Multi-modal ingestion: upload transcripts, SOPs, audio recordings, images
- Automatic intent extraction and journey mapping
- Auto-generated tools, escalation logic, and guardrails
- Real-time artifact preview as you iterate

---

## Simulation sandbox

Test agents against synthetic scenarios before deploying:

- **Persona generation** — Create diverse user personas with different intents, communication styles, and edge cases
- **Stress testing** — High-volume synthetic conversations to find breaking points
- **Scenario planning** — What-if analysis for proposed changes

---

## Skills system

A unified abstraction for both optimization strategies and agent capabilities:

**Build-time skills** are mutation templates the optimizer uses — routing fixes, safety patches, latency tuning recipes. Each skill tracks its own effectiveness and auto-retires when it stops working.

**Run-time skills** are executable agent capabilities — API integrations, handoffs, specialized tools. They compose with dependency resolution and conflict detection.

Skills can be discovered, installed, composed, and published. The recommendation engine suggests skills based on your agent's current failure patterns.

---

## Human controls

The optimization loop is designed to run autonomously, but you're always in control:

| Command | What it does |
|---------|-------------|
| `autoagent pause` | Pause the loop immediately |
| `autoagent resume` | Resume from where you left off |
| `autoagent pin <surface>` | Lock a config surface from mutation |
| `autoagent unpin <surface>` | Unlock a surface |
| `autoagent reject <id>` | Reject and rollback an experiment |

You can also configure immutable surfaces in `autoagent.yaml` — for example, locking `safety_instructions` so the optimizer can never touch them.

---

## Cost controls

Budget management is built into the loop:

- **Per-cycle budget** — Maximum spend per optimization cycle
- **Daily budget** — Maximum spend per day
- **Stall detection** — If the Pareto frontier hasn't improved in N cycles, the loop pauses
- **Cost tracking** — SQLite-backed ledger of every API call with per-model cost accounting

---

## Integrations

### Google CX Agent Studio

Bidirectional integration with Google's Contact Center AI:

- **Import** — Pull CX agents into AutoAgent (generativeSettings, tools, examples, flows, test cases)
- **Export** — Push optimized configs back to CX format with snapshot preservation
- **Deploy** — One-click deploy to CX environments
- **Widget builder** — Generate embeddable chat widgets

### Google Agent Development Kit (ADK)

Import ADK agents from Python source via AST parsing. AutoAgent extracts instructions, tools, routing, and generation settings while preserving your code style. Export patches back, or deploy directly to Cloud Run or Vertex AI.

### MCP server

Model Context Protocol integration exposes 10 tools to AI coding assistants (Claude Code, Cursor, Windsurf): status, eval_run, optimize, config_list, config_show, config_diff, deploy, conversations_list, trace_grade, memory_show.

### CI/CD gates

Integrate AutoAgent into your deployment pipeline. Run evals as a CI check, gate deployments on score thresholds, and get automated PR comments with eval results.

---

## Web console

39 pages served at `http://localhost:8000`, organized by workflow:

### Observe
- **Dashboard** — Health pulse, journey timeline, metric cards, recommendations
- **Traces** — Span-level trace viewer with filtering
- **Blame Map** — Failure clustering and root cause attribution
- **Conversations** — Browse agent conversations with outcome filtering
- **Event Log** — Real-time system event timeline

### Optimize
- **Optimize** — Trigger cycles, view experiment history
- **Live Optimize** — Real-time SSE streaming with phase indicators
- **AutoFix** — AI-generated fix proposals with apply/reject
- **Opportunities** — Ranked optimization queue by impact
- **Experiments** — Experiment cards with diffs and statistics

### Evaluate
- **Eval Runs** — Run history with comparison mode
- **Eval Detail** — Per-case results with pass/fail breakdown
- **Judge Ops** — Judge versioning, calibration, drift monitoring
- **Scorer Studio** — Create eval scorers from natural language

### Build
- **Agent Studio** — Natural language config editing
- **Intelligence Studio** — Transcript-to-agent pipeline
- **Assistant** — Chat-based agent building
- **Sandbox** — Synthetic scenario testing
- **What-If** — Counterfactual scenario planning

### Manage
- **Configs** — Version browser with YAML viewer and side-by-side diffs
- **Registry** — Skills, policies, tools, handoff schemas
- **Deploy** — Canary controls and deployment history
- **Loop Monitor** — Cycle-by-cycle progress and watchdog health
- **Skills** — Optimization strategy browser with effectiveness tracking
- **Runbooks** — Curated fix bundles with one-click apply
- **Settings** — Runtime configuration and keyboard shortcuts

---

## CLI

70+ commands across 30+ groups. Every command supports `--help`, and major commands support `--json` for structured output. See the [CLI reference](cli-reference.md) for the complete list.

## API

200+ endpoints across 39 route modules, with OpenAPI docs at `/docs`. WebSocket at `/ws` for real-time updates and SSE at `/api/events` and `/api/optimize/stream` for live streaming. See the [API reference](api-reference.md) for the full endpoint list.

---

## Multi-model support

AutoAgent works with multiple LLM providers simultaneously. Configure them in `autoagent.yaml` and the optimizer uses them for judge diversity, mutation generation, and A/B evaluation:

| Provider | Models | Notes |
|----------|--------|-------|
| Google | Gemini 2.5 Pro, Gemini 2.5 Flash | Default provider |
| OpenAI | GPT-4o, GPT-4o-mini, o1, o3 | |
| Anthropic | Claude Sonnet 4.5, Claude Haiku 3.5 | |
| OpenAI-compatible | Any compatible endpoint | Custom base URL |
| Mock | Deterministic responses | No API key needed |

---

## Reliability

The platform is designed for multi-day unattended operation:

- **Checkpointing** — Loop state is saved after every cycle; restarts resume where they left off
- **Dead letter queue** — Failed cycles are queued for retry or inspection, never dropped
- **Watchdog** — Configurable timeout kills stuck cycles
- **Graceful shutdown** — SIGTERM completes the current cycle before stopping
- **Resource monitoring** — Warnings when memory or CPU exceed configured thresholds
- **Structured logging** — JSON log rotation with configurable size limits
