# AutoAgent — Evaluation & Optimization Architecture

*A technical overview for expert review. No prior knowledge of the project assumed.*

---

## What Is AutoAgent?

AutoAgent is a platform that **continuously evaluates and optimizes AI agents in production**. You point it at a deployed agent (initially targeting Google ADK agents), and it runs an autonomous loop: observe the agent's behavior → diagnose failures → propose improvements → evaluate candidates → gate on statistical significance → deploy winners. It runs for days/weeks unattended.

Think of it as an outer optimization loop around an inner agent system — the agent serves users, AutoAgent serves the agent.

---

## 1. How We Evaluate

### 1.1 Scoring Dimensions

We score agent performance across **9 global dimensions**:

| # | Dimension | What It Measures | How It's Computed |
|---|-----------|-----------------|-------------------|
| G1 | Task Success Rate | Did the agent complete the user's goal? | Fraction of eval cases marked `passed` |
| G2 | Response Quality | How good was the final answer? | Mean `quality_score` (0-1, rubric or LLM-judge) |
| G3 | Safety Compliance | Did the agent stay within policy? | Fraction where `safety_passed = True` |
| G4 | Latency (p50/p95/p99) | How fast? | Percentiles from `latency_ms`, normalized inverse against 5s ceiling |
| G5 | Token Cost | How expensive? | Mean tokens, normalized inverse against 2K ceiling |
| G6 | Tool Correctness | Did it call the right tools with right args? | Mean `tool_use_accuracy` (0-1) |
| G7 | Routing Accuracy | Was the query sent to the right specialist? | Fraction where `routing_correct = True` |
| G8 | Handoff Fidelity | Did context survive agent-to-agent transfers? | Fraction where `handoff_context_preserved = True` |
| G9 | User Satisfaction Proxy | Would the user be happy? | Mean `satisfaction_proxy` (0-1, heuristic) |

Plus **per-agent dimensions** (per specialist: unit success, tool precision/recall, policy adherence, avg latency, escalation appropriateness; per orchestrator: first-hop routing accuracy, reroute recovery rate, context forwarding fidelity).

**Default user view**: A simplified 4-metric composite (quality 40%, safety 25%, latency 20%, cost 15%). The 9 dimensions power the internals and are available in detail views.

### 1.2 Constraint vs. Objective Separation

We separate hard constraints from optimization objectives:

- **Hard constraints (binary gate)**: Zero safety failures. All P0 regression cases must pass. If either fails, the candidate is rejected regardless of other scores.
- **Optimization objectives (continuous)**: Quality (55%), latency (25%), cost (20%) — optimized within the feasible set.

Three scoring modes:
- **Weighted**: Original flat weighted sum (backwards compatibility)
- **Constrained**: Hard constraints as gates → weighted objectives within feasible set
- **Lexicographic**: Quality-first, then cost/latency as tiebreakers

### 1.3 Eval Data Pipeline

**Eval set types:**
| Type | Purpose |
|------|---------|
| `golden` | Curated ground-truth cases, never rotated |
| `rolling_holdout` | Rotated periodically to prevent overfitting |
| `challenge` / `adversarial` | Edge cases, prompt injections, policy probes |
| `live_failure_queue` | Bad production traces auto-converted to eval cases |

**Evaluation modes per case:**
- Target response comparison
- Target tool trajectory matching
- Rubric-based response quality (LLM-judge)
- Rubric-based tool-use quality
- Hallucination / groundedness check
- Safety evaluation
- User simulation

**Trace-to-eval conversion**: The `TraceToEvalConverter` watches production traces, identifies failures (tool errors, safety violations, low satisfaction, high latency), and automatically converts them into eval cases with the appropriate evaluation mode. This is intended to be the center of the product — the flywheel that makes evals better over time as the agent sees more real traffic.

### 1.4 Replay Harness

To safely evaluate candidates against historical traces, we classify every tool by side-effect:

| Class | Description | Auto-replay? |
|-------|-------------|-------------|
| `pure` | Deterministic, no external calls | ✅ Yes |
| `read_only_external` | Reads external state, no mutations | ✅ Yes |
| `write_external_reversible` | Mutations with rollback | ❌ No (manual only) |
| `write_external_irreversible` | Destructive mutations | ❌ No |

Baseline tool I/O is recorded during live operation and stubbed during replay. Only `pure` and `read_only_external` tools are eligible for automatic replay.

---

## 2. How We Optimize

### 2.1 The Core Loop

```
1. TRACE     → Collect structured events (tool calls, state deltas, errors, transfers)
2. DIAGNOSE  → Cluster failures by signature (tool errors, transfer chains, latency spikes, safety flags)
3. QUEUE     → Rank optimization opportunities: severity × prevalence × recency × business_impact
4. SEARCH    → Generate diverse candidate mutations, rank by predicted lift/risk/novelty
5. REPLAY    → Shadow-evaluate candidates against recorded traces
6. GATE      → Hard constraints first, then objective improvement
7. STATS     → Statistical significance testing (see §2.4)
8. DEPLOY    → Canary deployment with experiment card tracking
9. LEARN     → Record which mutation operators work for which failure families
10. REPEAT
```

### 2.2 Mutation Operators

Instead of treating every change as a generic "config delta," we have a **typed mutation registry**. Each operator has a defined surface, risk class, preconditions, validator, and rollback strategy:

| Operator | Surface | Risk | Auto-deploy? |
|----------|---------|------|-------------|
| Instruction rewrite | `instruction` | low | yes |
| Few-shot edit | `few_shot` | low | yes |
| Tool description/schema edit | `tool_description` | medium | yes |
| Model swap | `model` | high | no |
| Generation settings | `generation_settings` | low | yes |
| Callback patch | `callback` | high | no |
| Context caching (threshold/TTL) | `context_caching` | medium | yes |
| Memory policy | `memory_policy` | medium | yes |
| Routing edit | `routing` | medium | yes |
| Topology change | `topology` | high | no (PR-only) |

Google Vertex prompt optimizers (zero-shot, few-shot, data-driven) are wrapped as first-class operators (currently stubbed — need Vertex credentials).

### 2.3 Search Engine

The optimizer generates **multiple hypotheses per cycle**, not one:

1. **Cluster failures** from the ranked opportunity queue
2. **Generate diverse candidate mutations** from the operator registry (one per failure cluster)
3. **Rank candidates** by predicted lift, risk, and novelty
4. **Evaluate top K** under a fixed eval budget
5. **Learn** which operator families work for which failure clusters (stored in optimizer memory)
6. **Reject re-runs** — memory of failed ideas prevents repeating bad changes

The search currently uses a **failure-bucket → operator mapping** as its core heuristic. The proposer identifies the dominant failure bucket (e.g., "tool errors" or "safety violations") and selects the most promising operator family. This is fast and predictable but doesn't do principled exploration/exploitation.

**In progress (parallel build running now):** Hybrid Search Orchestrator with bandit-guided experiment selection (UCB/Thompson sampling for which agent/surface to optimize), curriculum learning (easy clusters first), and a Constrained Pareto Archive for multi-objective candidate comparison.

### 2.4 Statistical Gating

We gate every promotion decision on statistical significance. The current layer includes:

| Method | Purpose |
|--------|---------|
| **Paired sign-flip permutation test** | Primary significance test (p < α) with minimum effect size threshold |
| **Clustered bootstrap** | Resamples whole conversations/users to respect within-cluster correlation. Returns CI, effect size, power estimate |
| **O'Brien-Fleming sequential testing** | Alpha-spending function for multi-look experiments (prevents peeking problem) |
| **Holm-Bonferroni correction** | Controls family-wise error rate when testing multiple candidates per batch |
| **Minimum sample size checks** | Per-metric adequacy (default: 30 samples minimum) |
| **Judge variance estimation** | Bootstrap estimate of LLM-judge inconsistency |

A candidate must clear **both a fixed holdout and a rolling holdout** before promotion.

### 2.5 Experiment Cards

Every optimization attempt produces a machine-readable **experiment card**:

```
hypothesis: "Adding product-lookup examples to few-shot will reduce tool errors"
touched_surfaces: [few_shot]
touched_agents: [product_specialist]
diff_summary: "+3 few-shot examples for product lookup"
baseline_sha: abc123
candidate_sha: def456
risk_class: low
eval_set_versions: {golden: v3, rolling: v7}
replay_set_hash: sha256:...
significance_p_value: 0.012
significance_delta: +0.08 quality
deployment_policy: auto
rollback_handle: exp-2026-03-23-001
total_experiment_cost: $0.47
status: accepted
```

### 2.6 Deployment

Accepted candidates are deployed via canary with monitoring. High-risk mutations (model swaps, callback patches, topology changes) require manual approval. Rollback is automatic if post-deploy metrics regress.

---

## 3. Persistence & Reliability

- **SQLite** for all structured data (traces, evals, experiments, opportunities, optimizer memory, dead letter queue)
- **YAML** for agent configs with version history
- **JSON** for loop checkpoints (resume after crash)
- **Single-process** — no Celery, Redis, or Kafka. The optimization loop is inherently sequential; SQLite handles persistence
- **Graceful shutdown** (SIGTERM/SIGINT → finish current cycle → exit)
- **Dead letter queue** for failed cycles (logged, not lost)
- **Watchdog** for stall detection
- **Structured JSON logging** with rotation (5MB × 5)

---

## 4. What We'd Like Your Feedback On

### On Evaluation:
1. **Is the 9-dimension framework the right set of dimensions?** Are we missing anything critical? Are any redundant?
2. **Is the constraint/objective separation sound?** Safety and P0 regression as hard gates, everything else as continuous objectives.
3. **Is our trace-to-eval conversion approach viable at scale?** Auto-converting bad production traces into eval cases.
4. **Is the replay harness with side-effect classification sufficient?** Or do we need something more sophisticated for safe offline evaluation?
5. **How should we handle LLM-as-judge reliability?** We have judge variance estimation, but is that enough to trust automated quality scoring?

### On Optimization:
6. **Is the failure-bucket → operator mapping a reasonable starting heuristic?** Before we have the full bandit-guided search.
7. **Is our statistical gating layer appropriate for continuous agent optimization?** Permutation test + clustered bootstrap + sequential testing + multiple-hypothesis correction.
8. **What's the right explore/exploit strategy?** We're building bandit-guided selection — is UCB/Thompson the right approach, or should we consider something else?
9. **How should we handle the multi-objective tradeoff?** Weighted sum vs. Pareto front vs. lexicographic — what works best in practice for agent optimization?
10. **What failure modes should we be most worried about?** Goodhart's Law, reward hacking, eval contamination, optimizer collapse, etc.

### On Architecture:
11. **Is the single-process / SQLite design a mistake?** Should we plan for distributed eval from the start?
12. **What's missing that would make this useful in production at a real company?**

---

## 5. Relevant Context

- **Target agents**: Google ADK (Agent Development Kit) multi-agent systems initially. ADK exposes mutable surfaces at agent, app, callback, tool, workflow, caching, compaction, and memory layers.
- **Default LLM for optimization**: Gemini 2.5 Pro (proposer + judge). Multi-model support available.
- **Scale target**: Single-agent to ~10-agent trees. Not designed for 100+ agent swarms.
- **Deployment context**: Enterprise customer support, commerce, and internal agents.

---

*Repository: https://github.com/andrewhuot/autoagent-vnextcc*
*Branch: `feat/p0-architectural-overhaul`*
