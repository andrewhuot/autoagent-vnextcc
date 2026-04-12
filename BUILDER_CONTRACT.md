# Builder Contract — AgentLab Harness

> This file defines the operating behavior contract for the builder agent
> within the AgentLab harness. It is the authoritative reference for what the
> builder does, how it loops, what it reads, what it persists, what counts as
> done, and how it treats skills.
>
> **This file is NOT project memory.** Project memory lives in `AGENTLAB.md`.
> This file defines builder *behavior*, not project *state*.

---

## 1. Builder Identity

The builder is the agent that converts a user's natural-language brief into a
structured agent configuration. It operates within the harness — the execution
environment that provides persistence, event streaming, metrics, and lifecycle
management.

**Role**: Plan, execute, reflect on, and present agent configurations.
**Scope**: One project at a time. One build run at a time per project.
**Authority**: The builder proposes changes. The harness persists them. The
operator (human or automated caller) approves or rejects.

---

## 2. Startup Sequence

When the builder begins a run, it MUST read context in this order:

1. **Build request** — the brief, target platform, environment, and mode
   (`initial`, `follow_up`, or `correction`).
2. **Project state** — the current canonical model (agents, tools, guardrails),
   prior harness state (checkpoints from previous runs), and existing artifacts.
3. **Conversation history** — prior turn messages and summaries for multi-turn
   context (follow-up and correction modes only).
4. **Skill context** — available build-time and runtime skills from the skill
   store, classified by kind. Skills inform but do not control execution.
5. **Domain inference** — the builder infers the domain from the brief text
   to select appropriate templates, tool names, and guardrail patterns.

The builder MUST NOT skip steps 1–3. Steps 4–5 are best-effort: if the skill
store is unavailable or domain inference fails, the builder continues with
defaults.

---

## 3. Loop Phases

Each build run follows four sequential phases:

### Phase 1: Plan
- Build a hierarchical task tree from the brief and inferred domain.
- The tree has two levels: task groups (Plan, Tools, Guardrails, Environment,
  Eval) containing leaf tasks (the actual work units).
- Emit `plan.ready` with the full tree structure.
- The plan is deterministic given the same brief and domain.

### Phase 2: Execute
- Iterate through leaf tasks sequentially.
- For each leaf task:
  - Emit `task.started`.
  - Generate content (LLM-first with template fallback).
  - Apply the resulting operation to the working model.
  - Emit `artifact.updated` with the generated artifact.
  - Emit `task.completed` with applied operations.
  - Save a checkpoint (task ID, artifact ID, operation, step index).
- The working model accumulates state: later tasks see tools/guardrails
  added by earlier tasks.
- Emit `harness.metrics` every 3 steps and on the final step.

### Phase 3: Reflect
- After all leaf tasks in a group complete, assess quality.
- Reflection checks:
  - Artifact count matches leaf count.
  - No artifacts are trivially short (< 20 chars).
  - Brief keywords appear in generated content (coverage ≥ 20%).
- Emit `reflection.completed` with quality score (0.0–1.0) and suggestions.
- Reflection is observational, not a hard gate. Low scores surface issues
  to the operator but do not halt the build.

### Phase 4: Present
- Finalize metrics (mark completion timestamp).
- Emit final `harness.metrics` snapshot.
- Emit `build.completed` with all applied operations, plan ID, and metrics.
- The build is done. The event stream terminates.

---

## 4. Persistence Guarantees

### What is persisted
- **Checkpoints**: After each leaf task completes, a `HarnessCheckpoint` is
  saved to `project.harness_state.checkpoints[]`. Checkpoint failure is
  non-fatal — the build continues.
- **Working model**: Operations accumulate in memory during the run. The final
  model state is persisted by the caller (workbench service) after
  `build.completed`.
- **Events**: All emitted events are published to the event broker for
  durable storage in `builder_session_events`.
- **Artifacts**: Generated artifacts are included in events and accumulated
  by the workbench store.

### What is NOT persisted by the builder
- Intermediate LLM responses (transient).
- Template selection decisions (deterministic, reproducible).
- Reflection scores (emitted as events, not stored separately).

---

## 5. Completion Criteria

A build run is **done** when:
1. All leaf tasks have been executed (step counter equals total).
2. `metrics.finish()` has been called (completion timestamp set).
3. `build.completed` event has been emitted with all operations.

A build run is **NOT done** if:
- Any leaf task has not been attempted.
- The event stream was interrupted before `build.completed`.
- An error event was emitted without a subsequent `build.completed`.

### Iteration
After the initial build completes, the operator may request follow-up
iterations. Each iteration:
- Builds a focused delta plan from the follow-up message.
- Only regenerates affected artifact categories.
- Increments the iteration counter (starting at 2).
- Emits `iteration.started` followed by the standard phase sequence.
- Completes with its own `build.completed` event.

---

## 6. Verification Model

### Builder self-verification
- **Reflection** (Phase 3): Structural quality checks after each task group.
- **Coverage check**: Brief keywords must appear in ≥ 20% of generated content.
- **Artifact validation**: All artifacts must have non-trivial content.

### Harness-level verification
- **Checkpoint integrity**: Each step saves a checkpoint before proceeding.
- **Event completeness**: The stream must end with `build.completed` or an
  error event — never silently.
- **Metrics accuracy**: Token/cost estimates are approximate but directionally
  correct.

### What the builder does NOT verify
- Semantic correctness of generated agent configurations.
- Whether generated tools actually work at runtime.
- Whether guardrails are sufficient for the use case.
These are the operator's responsibility, aided by the eval system.

---

## 7. Recovery and Handoffs

### Crash recovery
- If a build is interrupted mid-execution, checkpoints in
  `harness_state.checkpoints[]` record where execution stopped.
- Stale tasks (stuck in RUNNING/PAUSED for > 30 minutes) are marked FAILED
  with `recovery_reason: "stale_interrupted"`.
- The harness does not automatically resume from checkpoints. The operator
  must initiate a new build or iteration.

### Iteration handoff
- After a completed build, the builder retains:
  - `_previous_artifacts` — all artifacts from prior iterations.
  - `_previous_plan` — the last plan structure.
  - `_iteration` counter — incremented after each completed run.
- Follow-up iterations receive the full prior context and produce deltas.

### Error handling
- LLM generation failures fall back to template-based content.
- Template failures produce empty artifacts (flagged by reflection).
- Checkpoint persistence failures are silently absorbed.
- Catastrophic failures in `LiveWorkbenchBuilderAgent` fall back to
  `MockWorkbenchBuilderAgent` so the UI always receives a coherent stream.

---

## 8. Skill Treatment

Skills are first-class harness concepts divided into two layers:

### Build-time skills (`kind: "build"`)
- **What they are**: Optimization strategies that modify agent configurations
  during development. Examples: keyword expansion, safety hardening,
  routing fixes.
- **Key components**: Mutation operators, trigger conditions, eval criteria.
- **How the harness treats them**: The harness loads available build-time
  skills at startup as context. It reports them in the `skill_context`
  section of events. It does NOT automatically apply them — that is the
  optimizer's job (`optimizer/skill_engine.py`).
- **Operator visibility**: Build-time skills appear in event metadata with
  `skill_layer: "build"`. The operator can see which build-time skills are
  available and could be relevant to the current build.

### Runtime skills (`kind: "runtime"`)
- **What they are**: Agent capabilities deployed at runtime. Examples:
  order lookup, refund processing, identity verification.
- **Key components**: Tool definitions, instructions, policies, test cases.
- **How the harness treats them**: The harness loads available runtime skills
  at startup as context. Artifacts that define agent tools or capabilities
  are tagged with `skill_layer: "runtime"`. The harness reports which
  runtime skills are relevant to the generated agent configuration.
- **Operator visibility**: Runtime skills appear in event metadata with
  `skill_layer: "runtime"`. The operator can see which runtime skills
  the generated agent will have access to.

### Skill layer in artifacts
Every artifact emitted by the harness includes a `skill_layer` field:
- `"build"` — artifact was produced by or relates to a build-time skill.
- `"runtime"` — artifact defines a runtime capability for the agent.
- `"none"` — artifact is not skill-specific (e.g., environment config).

### Skill context in events
The `build.completed` event includes a `skill_context` summary:
```json
{
  "build_skills_available": 5,
  "runtime_skills_available": 3,
  "build_skills_relevant": ["safety_hardening", "keyword_expansion"],
  "runtime_skills_relevant": ["order_lookup"],
  "skill_store_loaded": true
}
```

---

## 9. Event Contract Summary

| Event | Phase | Data |
|-------|-------|------|
| `plan.ready` | Plan | `{plan, skill_context?}` |
| `message.delta` | Plan | `{task_id, text}` |
| `task.started` | Execute | `{task_id}` |
| `task.progress` | Execute | `{task_id, note}` |
| `artifact.updated` | Execute | `{task_id, artifact, skill_layer}` |
| `task.completed` | Execute | `{task_id, operations}` |
| `harness.metrics` | Execute/Present | `{steps_completed, total_steps, ...}` |
| `reflection.completed` | Reflect | `{task_id, quality_score, suggestions}` |
| `iteration.started` | Iterate | `{project_id, iteration, message}` |
| `build.completed` | Present | `{project_id, operations, plan_id, harness_metrics, skill_context}` |

---

## 10. Relationship to Other Files

| File | Role | Relationship |
|------|------|-------------|
| `AGENTLAB.md` | Project memory | Builder reads but does not write. Separate concern. |
| `BUILDER_CONTRACT.md` | This file | Defines builder behavior. |
| `builder/harness.py` | Implementation | Implements the contract's loop phases. |
| `builder/contract.py` | Contract loader | Parses this file for machine use. |
| `core/skills/types.py` | Skill model | Defines SkillKind (BUILD, RUNTIME). |
| `core/skills/store.py` | Skill persistence | Source of skill context at startup. |
| `builder/workbench_agent.py` | Agent adapter | Wires harness into the workbench. |
