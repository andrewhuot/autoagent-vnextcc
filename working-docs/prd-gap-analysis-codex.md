# AgentLab PRD v3 Gap Analysis - Codex

Date: 2026-04-12
Branch: `feat/prd-p0-gap-codex`
PRD: `/tmp/agentlab-product-design-spec-v3.md`

## Executive Summary

The current implementation is much closer to the PRD's near-term Workbench harness than a cold reading of the PRD would imply. The merged base already includes a dedicated `/workbench` surface, canonical Workbench project state, streaming builder runs, multi-turn iteration, durable run envelopes, persisted events, reflection/presentation phases, cancellation, budget telemetry, stale-run recovery, mock/live mode honesty, and ADK/CX export previews.

The highest-priority gaps now are not broad missing surfaces like full ADK/CX fidelity, full optimizer jobs, live production loops, or deployment adapters. Those remain important but are not P0 for this pass. The true P0s are smaller contract and honesty gaps in the Workbench loop:

1. The durable conversation log can duplicate one user brief inside a single turn, weakening the session log as a system-of-record.
2. The frontend optimistic follow-up path clears prior artifacts during iteration, even though the backend preserves them, creating a temporary but serious operator-honesty/data-loss illusion.
3. Completed Workbench runs say a candidate is ready, but the terminal payload lacks an explicit review/promotion gate and resumable handoff summary. That makes promotion constraints implicit at exactly the point where the PRD says human review and provenance must be explicit.
4. The Workbench JSON store can fail open on corrupt state and direct file writes are vulnerable to partial-write loss. That is unacceptable for the current durable Workbench substrate.

## Already Implemented

### Workbench Harness Surface

- `/workbench` exists as an additive Builder-family route.
- The page uses a two-pane Workbench model: conversation and plan activity on the left, canonical state/artifacts/source/evals/trace/activity on the right.
- The backend exposes `/api/workbench` routes for project creation, default hydration, plan snapshots, streaming builds, follow-up iteration, testing, rollback, and cancellation.

### Canonical Model and Compiler Output

- `builder/workbench.py` owns canonical Workbench project state.
- Natural-language plans mutate the canonical model first.
- ADK and CX export previews are compiled from canonical state rather than treated as source of truth.
- Compatibility diagnostics label objects as `portable`, `adk-only`, `cx-only`, or `invalid`.

### Durable Run Lifecycle

- Workbench runs have durable `run_id`, `active_run_id`, status, phase, execution metadata, budget, telemetry summary, events, messages, validation, and presentation fields.
- Stream lifecycle includes `turn.started`, `iteration.started`, `plan.ready`, task events, `build.completed`, `reflect.started`, `reflect.completed`, `validation.ready`, `present.ready`, `turn.completed`, and terminal run events.
- Terminal states include completed, failed, and cancelled.
- Stale in-flight runs are recovered during snapshot hydration.

### Multi-Turn Iteration

- The backend preserves conversation, turns, iteration records, artifacts, plans, validation, and canonical changes across follow-up turns.
- Follow-up streams route to `run_iteration_stream()` when a project already has artifacts.
- The frontend can hydrate persisted conversation and turn state.

### Operator Visibility

- Stream payloads include execution mode, provider, model, budget, telemetry, cancel reasons, failure reasons, and validation summaries.
- The UI surfaces mode and token budget usage in the harness metrics bar.
- Trace and activity tabs expose persisted run event telemetry and reflection summaries.

## Partially Implemented

### Agent Card / IR System of Record

The current Workbench canonical model is real and structured, but it is not yet the full PRD's `agent-card.md` plus canonical IR round-trip system. The right-pane Agent Card tab renders canonical model fields, and generated ADK/CX artifacts exist, but no repo-local `agent-card.md`, `.agentlab/` workspace layout, or `agentlab-progress.json` artifact is materialized for each Workbench project.

This is strategically important, but a full card compiler/round-trip implementation is broader than this P0 pass.

### Session Log and Handoff

Run events, messages, turns, and snapshots are durable. However, the terminal run payload does not yet provide a concise handoff object that tells the next session exactly what to resume, which version was produced, which artifact is active, what gate is blocking promotion, and what operator action comes next.

This is small enough and important enough to address now.

### Review / Promotion Model

The broader repo has optimizer review cards, release candidates, config promotion, deploy/canary commands, and collaboration review primitives. The Workbench terminal state does not yet attach a local review gate to its generated candidate. The UI currently exposes "Candidate ready" once a run completes, but the API does not say whether it is ready for review, blocked by validation/compatibility, or still needs explicit human approval.

This should be made explicit now without building the full PRD promotion subsystem.

### Frontend State Honesty

The backend preserves prior-turn artifacts during follow-up iteration. The frontend store's optimistic `startIteration()` currently clears `artifacts`, causing the UI to temporarily lose prior generated artifacts even though the server state is durable.

This is a genuine P0 because it contradicts the PRD's durable session log principle and can make operators think work was lost.

## Missing But Not P0 Now

- Full Agent Card markdown/IR round-trip compiler.
- Workspace materialization with `agent-card.md`, `.agentlab/`, evals, skills, callbacks, guardrails, candidates, deploy, docs, and `agentlab-progress.json`.
- Full ADK and CX import/export fidelity, including live target overrides for every non-portable construct.
- Fidelity preview for ADK/CX runtime semantics.
- Unified trace store across preview, eval, optimizer, and live traffic.
- Full eval suite tiering, generated eval workflows, slicing, trends, and trace graders inside Workbench.
- Long-running optimizer jobs with planner/generator/evaluator roles, Pareto candidate ranking, variance, budgets, and checkpoints.
- Live production performance loop, drift alerts, shadow compare, and production trace promotion directly inside Workbench.
- Full deploy adapters and rollback records from Workbench.
- Full security vault/broker architecture for runtime credentials.

These remain roadmap-level or follow-up P1/P2 work relative to this branch's already-hardened Workbench base.

## Missing And True P0 Now

### P0-1: Durable Conversation Log Must Not Duplicate User Briefs

Current evidence:
- `WorkbenchService._start_turn()` appends a user message to `project["conversation"]`.
- `run_build_stream()` and `run_iteration_stream()` then call `_append_message(... role="user" ...)`.
- `_append_message()` also appends user messages to `project["conversation"]`.

Impact:
- A single user turn can appear as two user entries in the durable conversation log.
- Future planner context can overweight or repeat prior user instructions.
- The session log is less trustworthy as a system-of-record.

Fix:
- Keep `_start_turn()` responsible for turn structure only, or make `_append_message()` deduplicate conversation entries for the same run/turn/user text.
- Add regression coverage that one completed stream has exactly one user conversation message per turn.

### P0-2: Frontend Follow-Up Iteration Must Preserve Prior Artifacts

Current evidence:
- Backend follow-up iteration preserves artifacts.
- `useWorkbenchStore.startIteration()` sets `artifacts: []`.

Impact:
- The Workbench UI can hide previous artifacts during a follow-up stream.
- Operators see a false loss of state, breaking durable-session trust.

Fix:
- Preserve `state.artifacts` when starting an iteration.
- Keep `previousVersionArtifacts` for diffing.
- Add regression coverage around optimistic iteration state.

### P0-3: Completed Runs Need Explicit Review Gate And Handoff Contract

Current evidence:
- `build_presentation_manifest()` returns `summary`, `artifact_ids`, `active_artifact_id`, `generated_outputs`, `validation_status`, and `next_actions`.
- No terminal `review_gate`, promotion readiness, required human review state, blocking reasons, or resumable handoff object exists.
- The UI can show "Candidate ready" without a durable gate object.

Impact:
- Operators do not have a contract-level answer to "can this be promoted?"
- Human review remains implied rather than explicit.
- The next session lacks a compact handoff summary even though the PRD calls for multi-session continuity.

Fix:
- Add a terminal review gate to the presentation payload and run payload:
  - validation passed/failed
  - target compatibility passed/blocked
  - human review required
  - blocking reasons
  - promotion status, initially `draft`
- Add a handoff summary:
  - project/run/turn/version
  - active artifact
  - last event sequence
  - next operator action
  - resume prompt
- Surface the gate in the Activity tab.
- Add backend and frontend tests.

### P0-4: Workbench Store Must Fail Closed On Corrupt Durable State

Current evidence:
- `WorkbenchStore._load()` returns an empty project map for invalid JSON.
- `WorkbenchStore._write()` writes the full JSON document directly.

Impact:
- A partial write or corrupted store can make the next process believe all Workbench projects disappeared.
- This violates the PRD's durable session and artifact model at the current persistence layer.

Fix:
- Missing files still initialize as an empty store.
- Existing corrupt files raise a clear error instead of silently resetting.
- Writes go through a temporary file and atomic replace.
- Add regression coverage that corrupt state is not erased.

## Selected Implementation Scope

This pass will implement only P0-1 through P0-4. The work is deliberately narrow: it strengthens durable state, operator honesty, and promotion constraints without trying to build the full PRD.

## Not Selected From Parallel Review

Parallel read-only review also identified broader issues around generic builder event persistence, builder chat session persistence, API change-card apply semantics, deploy gating, and studio promotion. These are credible follow-up risks, but they cut across the older Builder/Optimize/Deploy stack rather than the current Workbench P0 loop. This pass addresses the Workbench-facing subset now: explicit review gates and handoff state at the terminal run boundary. A follow-up should unify CLI/API review and deploy gates around a shared candidate contract.
