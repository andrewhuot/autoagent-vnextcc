# Workbench Harness Claude-Code Audit - Codex

Date: 2026-04-12

Branch: `feat/workbench-harness-claude-code-audit-codex`

Primary reference: <https://code.claude.com/docs/en/how-claude-code-works>

## Executive Verdict

AgentLab Workbench has a useful foundation for a real coding-agent harness: durable run envelopes, replayable events, persisted messages, validation, handoff manifests, target compatibility checks, stale-run recovery, cancellation, budgets, review gates, and explicit live/mock metadata. It is substantially more than a demo-only chat surface.

The main remaining risk is that several user-visible affordances imply a stronger long-running agent loop than the implementation actually provides. In particular, `auto_iterate` is presented as autonomous correction but is not wired into the validation result, task completion can look more conclusive than its evidence supports, recovery is honest about stale failure but not true resumability, and frontend hydration hides some of the durable state operators would need to trust a long run after refresh.

The highest-value fix for this pass is to make the advertised iteration loop evidence-driven for a deterministic class of failures, then expose the durable state more truthfully in the Workbench UI/store. This gives operators a concrete reason to believe that a run can improve itself instead of merely producing a more polished terminal summary.

## Claude-Code-Like Qualities Used As Audit Criteria

- Explore, plan, act, verify, and repeat as separate operational states.
- Durable local session state that can be resumed, inspected, or handed off after compaction, refresh, or interruption.
- Tool-backed changes and artifacts that correspond to real state transitions.
- Truthful progress and completion semantics: terminal success should mean the requested work was performed and passed relevant checks, not merely that a stream ended.
- Interruptibility and operator control without losing provenance.
- Iteration that improves the artifact or agent based on evidence from validation, execution, tests, evals, or review.

## What Already Works

- `builder/workbench.py` persists run envelopes with run status, phase, messages, events, validation, presentation, telemetry, and budget fields.
- `run.completed` is the terminal stream event; the frontend no longer treats `build.completed` as final success.
- Workbench emits reflect, validation, present, and handoff data after the build pass.
- Stale active runs are recovered as failed/interrupted instead of silently shown as running.
- Compatibility checks distinguish at least one important class of target-invalid tools.
- The right-pane Workbench has evolved beyond artifact gallery state into agent card, source, evals, trace, and activity surfaces.
- Existing tests cover many run lifecycle, persistence, cancellation, budget, and frontend store transitions.

## Major Logical Gaps

### 1. `auto_iterate` Is Advertised But Not A Real Correction Loop

The API, docs, and frontend copy state that `auto_iterate=True` lets the service run corrective iterations after validation, capped by `max_iterations`. The backend accepts those fields but does not use validation failure to launch another pass. Current tests permit one `iteration.started` event, so a no-op autonomous loop still passes.

Practical effect: an operator can enable autonomous iteration and believe the harness will self-correct, while the run actually performs one pass and stops.

Severity: High.

### 2. Completion Still Leans Too Much On Structural Validation

Workbench validation currently checks that a canonical model exists, exports compile, and target compatibility passes. That is useful, but not equivalent to proving that the requested agent improved. A task can emit `task.completed` with weak evidence and still advance the plan. Older Builder execution code also allows task completion without strong artifact/eval/approval evidence.

Practical effect: a run can become "completed" because the structure is valid, even if the work was shallow.

Severity: High.

### 3. Recovery Is Durable Hydration, Not True Resume

Run envelopes and checkpoints are valuable for operator trust. However, checkpoints are not currently consumed to skip completed work, replay operations, or continue from the next incomplete task. Stale recovery truthfully marks interrupted runs as failed, but any language implying resumable execution should remain conservative until a real resume path exists.

Practical effect: refresh and handoff are useful, but not yet equivalent to Claude-Code-like continuation.

Severity: High.

### 4. Live/Mock Provenance Can Drift

Live agent surfaces can fall back to deterministic mock behavior while the durable run metadata may still carry the original live provider/model context. That weakens auditability because generated output can appear to have live-model provenance when it did not.

Practical effect: operators may trust live execution evidence that actually came from fallback generation.

Severity: High.

### 5. Workbench And Optimizer Are Adjacent Rather Than Connected

Agent Improver and optimize flows exist, but Workbench terminal output does not produce a structured optimizer handoff containing validation evidence, generated config/export pointers, review gate state, and next eval recommendations. The system can tell an operator to run evals, but it does not make the next improvement loop first-class.

Practical effect: repeated usage may stall in manual copy/paste or superficial iteration rather than converging through eval-driven improvement.

Severity: Medium-High.

### 6. Frontend Hydration Drops Some Operator-Trust State

The backend exposes handoff/checkpoint/run-summary fields, but the frontend store and Activity view do not consistently preserve or render them. Live trace events are also less durable in the in-memory active run than the backend event ledger.

Practical effect: the backend may know why a run is safe or unsafe, while the operator UI still feels like a transient stream.

Severity: Medium.

## Optimizer / Improver Decision

The optimizer should be connected more directly, but not by running a full optimizer pass inline after every Workbench build. That would blur responsibilities and make a long-running build harder to reason about.

The pragmatic integration point is a structured Workbench improvement handoff:

- capture validation status, failed checks, target, export names, generated config identity, review gate state, and recommended eval suite;
- surface whether the Workbench run produced a runnable candidate or only a draft;
- give Agent Improver / Optimize a concrete input contract instead of relying on UI narration;
- only launch optimizer execution when the operator chooses that next step or when an explicit automation setting is enabled.

This should flow through the existing Eval Runs to Optimize path rather than AutoFix. The optimizer API already has a real scoped `eval_run_id` path that converts completed eval failures into optimizer samples and runs baseline/candidate comparison. By contrast, the live optimize stream is simulated telemetry, AutoFix is heuristic proposal/apply state, and QuickFix is preview-only. Workbench should therefore produce a typed eval/optimizer handoff instead of passing its structural validation result directly into AutoFix.

This pass should start with an evidence-driven local correction loop and better handoff visibility. Full optimizer handoff can follow once the terminal candidate/eval contract is stronger.

## Selected Fix Slice

This implementation pass will focus on fewer high-leverage fixes:

1. Add a regression proving `auto_iterate=True` must run a second correction iteration when validation fails for a repairable target-compatibility issue.
2. Add operation support needed for deterministic repair of invalid tools.
3. Wire Workbench validation failure into an autonomous correction pass, capped by `max_iterations`, with distinct correction iteration events and durable artifacts/events.
4. Keep `auto_iterate=False` as honest one-pass behavior.
5. Preserve and render more durable state in frontend store/API paths where low-risk.

## Deferred Risks

- True checkpoint-based resume still needs a dedicated design and endpoint.
- Terminal success should eventually require stronger execution evidence per task, not only structural validation.
- Live-to-mock fallback provenance needs explicit terminal metadata or fail-closed behavior.
- Shared Python/TypeScript Workbench contracts should be promoted for run events, handoff, harness metrics, and evidence.
- Optimizer handoff should become a typed API path once Workbench terminal candidate semantics are stronger.
