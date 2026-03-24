# Core Concepts

The mental models behind AutoAgent VNextCC. Read this before diving into features.

## The Eval Loop

AutoAgent runs a closed-loop optimization cycle:

```
trace → diagnose → search → eval → gate → deploy → learn → repeat
```

1. **Trace** -- Collect conversation traces and span-level telemetry
2. **Diagnose** -- Classify failures, build blame maps, identify optimization opportunities
3. **Search** -- Generate candidate mutations targeting diagnosed weaknesses
4. **Eval** -- Run candidates against the eval suite with statistical significance testing
5. **Gate** -- Check safety gates, regression gates, and holdout validation
6. **Deploy** -- Promote winning configs via canary or immediate deployment
7. **Learn** -- Record outcomes in optimization memory for future search
8. **Repeat** -- Loop until plateau, budget exhaustion, or human stop

Each cycle is autonomous but human-interruptible at every stage.

## 4-Layer Metric Hierarchy

Metrics are organized into four layers, evaluated top-down. A failure at a higher layer blocks promotion regardless of lower-layer scores.

| Layer | Purpose | Examples |
|-------|---------|----------|
| **Hard Gates** | Binary pass/fail, non-negotiable | Safety violation rate = 0%, no regressions on pinned surfaces |
| **North-Star Outcomes** | Primary optimization targets | Task success rate, response quality, composite score |
| **Operating SLOs** | Operational guardrails | Latency p95 < 2s, cost per conversation < $0.05 |
| **Diagnostics** | Debugging signals, not gated | Tool correctness, routing accuracy, handoff fidelity, failure buckets |

The optimizer maximizes north-star outcomes subject to hard gates and SLO constraints.

## Typed Mutations

The mutation registry defines 9 operator classes, each targeting a specific configuration surface:

| Operator | Surface | Risk Class |
|----------|---------|------------|
| Rewrite instruction | `instruction` | medium |
| Add/remove few-shot examples | `few_shot` | low |
| Modify tool descriptions | `tool_description` | medium |
| Swap model | `model` | high |
| Tune generation settings | `generation_settings` | low |
| Adjust callbacks | `callback` | medium |
| Context caching policy | `context_caching` | low |
| Memory policy | `memory_policy` | medium |
| Routing changes | `routing` | high |

Every operator declares preconditions, a validator function, rollback strategy, estimated eval cost, and whether it supports auto-deploy. The risk class determines gate strictness: `critical` mutations always require human approval.

## Experiment Cards

Every optimization attempt is tracked as an experiment card:

```python
ExperimentCard(
    experiment_id="exp_a1b2c3",
    hypothesis="Rewriting the support instruction to be more concise will reduce latency",
    config_sha="abc123",
    baseline_scores={"composite": 0.82},
    candidate_scores={"composite": 0.86},
    significance=0.03,       # p-value from bootstrap test
    status="promoted",       # pending → evaluated → promoted | rejected | archived
)
```

Cards form an audit trail. You can inspect any past experiment to understand what was tried, what worked, and why.

## Judge Stack

Eval scoring uses a layered judge stack, applied in order:

1. **Deterministic** -- Pattern matching, keyword checks, schema validation. Fast, zero-cost.
2. **Similarity** -- Embedding-based comparison against reference answers. Low cost.
3. **Binary Rubric** -- LLM judge with structured rubric. Scores quality on defined criteria.
4. **Audit Judge** -- Secondary LLM review of borderline cases. Catches judge errors.
5. **Calibration** -- Periodic human-vs-judge agreement analysis. Tracks judge drift over time.

Higher layers only fire when lower layers are inconclusive. This keeps eval costs low while maintaining accuracy.

## Search Strategies

Four search strategies, increasing in sophistication:

| Strategy | Description | Best For |
|----------|-------------|----------|
| `simple` | Deterministic proposer, single candidate per cycle | Getting started, low budget |
| `adaptive` | Multi-hypothesis search with bandit-based family selection | Most production use |
| `full` | Adaptive + curriculum learning + Pareto archive | Complex multi-objective optimization |
| `pro` | Research-grade prompt optimization (MIPROv2, BootstrapFewShot, GEPA, SIMBA) | Maximum quality, higher budget |

Set the strategy in `autoagent.yaml`:

```yaml
optimizer:
  search_strategy: adaptive
```

## Anti-Goodhart Guards

Three mechanisms prevent metric gaming (Goodhart's Law):

**Holdout rotation.** A rotating holdout set is excluded from optimization and used for validation. The holdout rotates every N cycles (default: 5) so the optimizer never fully adapts to any fixed subset.

**Drift detection.** The drift monitor tracks judge agreement rates over time. If a judge's scoring pattern shifts beyond the threshold (default: 0.12), the system flags it and optionally pauses optimization.

**Judge variance.** If variance across judge calls exceeds the threshold (default: 0.03), the experiment is flagged for human review rather than auto-promoted.

## Cost Controls

Three budget mechanisms prevent runaway spend:

```yaml
budget:
  per_cycle_dollars: 1.0         # Max spend per optimization cycle
  daily_dollars: 10.0            # Max daily aggregate spend
  stall_threshold_cycles: 5      # Pause after N cycles with no improvement
```

The cost tracker records actual spend per cycle (LLM calls, eval runs). When the daily budget is exhausted or stall is detected, the loop pauses automatically and emits a notification.

## Human Escape Hatches

Humans retain full control at all times:

| Command | Effect |
|---------|--------|
| `autoagent pause` | Immediately pause the optimization loop |
| `autoagent resume` | Resume a paused loop |
| `autoagent pin <surface>` | Lock a config surface (e.g., `safety_instructions`) -- optimizer cannot modify it |
| `autoagent unpin <surface>` | Unlock a previously pinned surface |
| `autoagent reject <experiment_id>` | Reject and roll back a specific experiment |

Pinned surfaces and the pause state persist across restarts via `.autoagent/human_control.json`. The `immutable_surfaces` list in config defines surfaces that can never be modified, even by explicit unpin.
