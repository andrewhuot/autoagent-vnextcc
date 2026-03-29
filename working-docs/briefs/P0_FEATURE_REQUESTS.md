# AutoAgent VNextCC — P0 Feature Requests

These are P0 changes required before calling the product production-ready. They represent a heavy refactor of architecture, backend, and frontend. We should maintain simplicity in the user journey — not every detail needs to be accepted verbatim, but the spirit of each request must be addressed.

---

## 1. Typed Mutation Registry (replace "one config change" abstraction)

Create a `MutationOperator` registry with fields: `surface`, `risk_class`, `preconditions`, `validator`, `rollback_strategy`, `estimated_eval_cost`, `supports_autodeploy`. 

First-party operators should cover:
- Instruction rewrites
- Few-shot edits
- Tool description/schema edits
- Model swaps
- Generation-setting changes
- Callback patches
- Context-caching/compaction changes
- Memory policy changes
- Routing/workflow edits

This matches ADK because ADK exposes mutable surfaces at agent, app, callback, tool, workflow, caching, compaction, and memory layers. `before_model_callback` can inject few-shot examples, change model config, implement guardrails, or short-circuit the model call.

## 2. Patch-based Candidates with Experiment Cards

Primary artifact = reviewable patch + machine-readable experiment card. Not "candidate config v17."

Card fields: `hypothesis`, `touched_surfaces`, `touched_agents`, `diff_summary`, `eval_set_versions`, `replay_set_hash`, `baseline_sha`, `candidate_sha`, `risk_class`, `deployment_policy`, `rollback_handle`, `total_experiment_cost`.

Mirrors autoresearch: constrained editable surfaces, fixed budgets, keep/discard behavior, branch advancement.

## 3. ADK Event/Trace-based Diagnosis

Replace shallow Logger/Observer with ADK Events, callbacks, and OTEL spans instrumentation. Capture:
- Tool-call requests, tool responses, state deltas, artifact deltas, errors
- Long-running tool markers, partial/final responses, agent-to-agent transfers
- Per-event/span: `invocation_id`, `session_id`, `agent_path`, `branch`, `tool_origin`, `latency`, `tokens`, `user_outcome_labels`

Google ADK docs: basic I/O monitoring is insufficient for complex agents. ADK events are immutable records. BigQuery analytics plugin models high-volume lifecycle events.

## 4. Ranked Opportunity Queue (replace `needs_optimization: bool`)

Observer emits `OptimizationOpportunity` objects:
- `cluster_id`, `failure_family`, `affected_agent_path`, `affected_surface_candidates`
- `severity`, `prevalence`, `recency`, `business_impact`
- `sample_traces`, `recommended_operator_families`

Cluster by trace summaries + structured signatures (tool errors, transfer chains, latency spikes, safety flags). Separate queues for drift, new failure modes, and cost/latency optimization.

## 5. Trace-to-Eval Data Engine (center of the product)

Workflow: observe bad production traces → convert to eval cases → replay on baseline and candidate.

Four eval-set types: `golden`, `rolling_holdout`, `challenge/adversarial`, `live_failure_queue`.

Evaluation modes per case: target response, target tool trajectory, rubric-based response quality, rubric-based tool-use quality, hallucination/groundedness, safety, user simulation.

ADK already provides criteria for exact tool trajectory matching, rubric-based quality, hallucination, safety, and user simulation.

## 6. Replay and Shadow Harness with Side-Effect Classes

Record baseline tool I/O, stub tools on replay when possible. Classify every tool:
- `pure` — deterministic, no external calls
- `read_only_external` — reads external state, no mutations
- `write_external_reversible` — mutations with rollback
- `write_external_irreversible` — destructive mutations

Only `pure` and `read_only_external` eligible for automatic replay. ADK session rewind is best-effort only.

## 7. Separate Constraints from Objectives in Scoring

Current design: safety is both a hard gate AND 25% of weighted composite — conceptually wrong.

Fix: safety, policy, P0 regression = hard constraints. Then optimize task success/quality first, cost/latency second within feasible set. Support lexicographic and constrained optimization modes (not just static weighted sum).

ADK eval criteria separate safety, hallucination, tool-use quality, trajectory correctness, and final-response quality.

## 8. Statistical Layer for Continuous Search

Beyond paired bootstrap, add:
- Minimum sample-size requirements per metric family
- Clustered bootstrap by conversation/user
- Sequential-testing control (for multi-day runs)
- Multiple-hypothesis correction across candidate batches
- Judge-variance estimation (repeated judging on subset)

Store: effect size, confidence interval, power estimate in run record. Require improvement to clear BOTH fixed holdout AND rolling holdout before promotion.

## 9. Multi-Hypothesis Search Engine (replace single LLM proposal)

Each cycle should:
1. Cluster failures
2. Generate diverse candidate mutations
3. Rank by predicted lift/risk/novelty
4. Evaluate top K under fixed budget
5. Learn which operator families work for which failure clusters

Keep memory of failed ideas (no re-running bad changes). Budget-aware, iterative, explicit keep/discard.

## 10. Google Prompt Optimizer Integration

Wrap Vertex's prompt optimizers as first-class operators:
- Zero-shot: quick prompt cleanup
- Few-shot: labeled bad examples + feedback
- Data-driven: larger dataset, optimize instructions/demonstrations against metrics

Save: optimizer config, input dataset version, target model, produced instructions as experiment artifacts.

## 11. Context & Memory Policies as Optimization Surfaces

Operators for:
- Context caching thresholds/TTL/use-count
- Context compaction interval/overlap/summarizer model
- Memory preload vs on-demand retrieval
- Memory write-back policy
- Session-state templating

ADK supports app-level context caching, session-event compaction with configurable summarization, PreloadMemory and LoadMemory tools.

## 12. Workflow/Topology Optimization (ADK 2.0 experimental)

Diagnose and optimize agent topology: transfer loops, bad routing, unnecessary parallelism, missing deterministic steps, over-generalist root agents.

Stable mutations: target current ADK workflow agents (Sequential, Loop, Parallel) and multi-agent compositions.

Graph-based and dynamic workflows = experimental-only (ADK 2.0 alpha). Any topology change = PR-only, not auto-promoted.
