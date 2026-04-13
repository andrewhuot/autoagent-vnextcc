# Agent Builder Workbench

Build and refine an agent candidate in a live, inspectable workspace before handing that candidate to Eval.

## Overview

Workbench is the inspectable candidate-building surface in the Build area. In the web console, open it from the simple sidebar as **Build -> Workbench**.

It turns a plain-English agent brief into a reviewable candidate config. It gives you a two-pane harness:

- the left pane keeps the conversation, plan, task progress, artifact cards, reflections, and follow-up turns together
- the right pane lets you inspect the generated artifacts, agent card, source previews, eval-related state, trace/activity details, review gate, and handoff evidence

Use it when you want to watch the candidate take shape, inspect generated outputs, and resolve obvious blockers before you run Eval.

Workbench is not a separate agent lifecycle. It is part of Build, but the product journey calls it out because it is the bridge from authoring into Eval:

```text
BUILD -> WORKBENCH -> EVAL -> COMPARE -> OPTIMIZE -> REVIEW -> DEPLOY
```

The important distinction is that Workbench creates and prepares a candidate. Eval measures it. Optimize uses eval results to propose improvements. Improvements and Deploy remain the places where reviewed changes are accepted and shipped.

## When to use Workbench

| Surface | Use it when | What it produces |
|---------|-------------|------------------|
| **Build** | You want the fastest prompt, transcript, builder chat, or XML instruction workflow. | Draft configs, saved artifacts, generated eval actions, and XML instruction edits. |
| **Workbench** | You want an inspectable agent-building harness with plan/task progress, artifacts, validation evidence, review gate state, and an Eval handoff. | A Workbench candidate that can be materialized into a saved config for Eval. |
| **Eval Runs** | You need to score a candidate against eval cases. | Eval run history, pass/fail summaries, and run IDs that downstream tools can trust. |
| **Results Explorer / Compare** | You need case-level diagnosis or a head-to-head decision between versions. | Failure patterns, annotations, exports, run diffs, and pairwise comparison evidence. |
| **Optimize** | You have eval evidence and want AgentLab to generate or test candidate improvements. | Optimization runs and reviewable proposed changes. |
| **Improvements** | You need a human decision queue for opportunities, experiments, proposals, and history. | Accepted, rejected, or pending review decisions. |
| **Deploy** | You are ready to canary, promote, roll back, or push through an integration target. | Rollout state and deployment history. |

A practical rule: use **Build** for quick authoring, **Workbench** when you need a transparent candidate-building session, **Eval** when you need measurement, and **Optimize** only after there is eval evidence to optimize from.

## Core terms

| Term | Meaning |
|------|---------|
| **Candidate config** | The draft agent configuration Workbench is building. It can include agent instructions, tools, guardrails, variables, and generated export previews. |
| **Materialized candidate** | A Workbench candidate saved into the normal AgentLab workspace so Eval can point at a real config path. |
| **Saved config path** | The file path returned by the handoff after materialization. Eval uses this path as the candidate under test. |
| **Target** | The output environment you are building toward, such as portable, ADK, or CX. Target compatibility diagnostics tell you whether generated pieces fit that environment. |
| **Review gate** | A Workbench readiness check that records whether human review is still required or whether blockers exist before promotion. It is not the same thing as the Improvements review queue for optimization proposals. |
| **Session handoff** | A compact summary of the latest run state, evidence, last event, and suggested next operator action. |
| **Eval handoff** | The Workbench bridge that saves the candidate and passes candidate context to Eval Runs. |

## The real workflow

### 1. Open or restore a Workbench project

When the Workbench page loads, it hydrates the latest Workbench project and then loads the current plan snapshot. That restored snapshot can include the plan, artifacts, messages, canonical model, generated exports, compatibility diagnostics, last validation result, activity, active run, run history, conversation turns, harness state, and run summary.

If no Workbench project exists yet, the backend creates a starter draft project so the page has a concrete project to hydrate instead of an empty shell.

### 2. Describe the agent candidate

Use the **Build request** input to describe what the agent should do. Workbench streams a harness run for that brief. The input also exposes **Auto-iterate** and **Max passes** controls.

Auto-iterate should be read narrowly. It can run deterministic correction passes when the backend has a known repair operation and budget remains. It is not a general self-healing promise, and it should not be treated as proof that every validation problem will be fixed automatically.

For a strong first request, include the role, main tasks, constraints, tools or systems it should use, escalation rules, and what a good answer should look like. If you need to include long reference material, paste the relevant excerpt into the brief or use another import/build path first; attachments are not currently enabled in the Workbench composer.

### 3. Watch the plan and artifacts

During a run, Workbench streams events such as:

- `plan.ready`
- `task.started`
- `task.progress`
- `message.delta`
- `artifact.updated`
- `task.completed`
- `reflect.started`
- `validation.ready`
- `present.ready`
- `run.completed`

The left pane shows the conversation and task flow. The right pane lets you inspect artifacts and generated source as they appear.

### 4. Review validation, evidence, and the review gate

After the build pass, Workbench runs structural validation and prepares a presentation. This can include:

- validation status and checks
- compatibility diagnostics for the selected target
- generated output previews
- a review gate
- a session handoff
- an Eval and Optimize bridge object

These are useful readiness signals, but they are not the same as eval results. A structurally valid candidate still needs Eval before you can claim that it performs well on the cases that matter.

### 5. Save the candidate and open Eval

Use the bridge state as the decision point:

- if Workbench shows blockers, fix the listed blocker before Eval
- if it says **Save candidate before Eval**, use **Save candidate and open Eval**
- if it says **Ready for Eval**, use **Open Eval with this candidate**

The first action appears when Workbench still needs to materialize the generated config. The second appears after the candidate has a saved config path that Eval can use.

That action calls the Workbench Eval bridge endpoint. The endpoint materializes the generated Workbench config into the real AgentLab workspace and returns typed request payloads for Eval and Optimize.

The endpoint is intentionally conservative:

- it saves the generated config
- it returns an Eval request shape
- it returns an Optimize request template
- it navigates the UI to Eval Runs with Workbench candidate context
- it does **not** start Eval
- it does **not** start Optimize
- it does **not** call AutoFix

### 6. Run Eval outside Workbench

Eval Runs is where the candidate is actually scored. The Workbench handoff can prefill the candidate context, but the eval still runs through the normal Eval surface and API.

You may still need to choose or confirm the eval suite, category, split, dataset, or run settings in Eval Runs. Workbench supplies the candidate context; Eval owns the measurement setup and result.

After the eval completes, the resulting eval run ID becomes the evidence Optimize needs. Until that completed eval exists, Optimize should stay blocked or waiting.

### 7. Continue into Optimize, Improvements, and Deploy

Once a Workbench candidate has a completed eval run, Optimize can use that eval context to work on the failures. Reviewable changes then belong in Improvements. Shipping still belongs in Deploy.

Workbench should make the next step clearer; it should not collapse the whole product into one magic button.

## Readiness states in plain English

Workbench has a few readiness surfaces. The top operator card uses lightweight page evidence. The bridge uses stricter backend blockers.

| State or label | What it means | What to do next |
|----------------|---------------|-----------------|
| **Candidate needed** | No canonical Workbench candidate exists yet. | Describe the agent in Workbench. |
| **Needs validation** | A candidate exists, but validation or presentation is not finished. | Let the run finish or inspect the blocking state. |
| **Ready** | The page has build evidence, such as a completed run or passed validation. | Prepare to run Eval, but do not treat this as production proof. |
| **Draft only** | The bridge does not see a completed generated config to evaluate. | Finish a Workbench run that produces a generated config. |
| **Eval blocked** | Workbench found blockers such as failed validation, invalid compatibility diagnostics, missing generated config, or review-gate blockers. | Resolve the listed blockers before Eval. |
| **Save candidate before Eval** | The candidate passed Workbench checks, but Eval needs a saved config path. | Materialize the candidate with **Save candidate and open Eval**. |
| **Ready for Eval** | The candidate is saved and the Eval request can point at a config path. | Open Eval with this candidate and start an eval run. |
| **Eval candidate not ready** | Optimize cannot start because the candidate is not saved for Eval yet. | Save the candidate and run Eval first. |
| **Run Eval before Optimize** | A saved candidate exists, but Optimize is waiting for a completed eval run. | Run Eval and use the resulting eval run ID. |
| **Ready for Optimize** | A completed eval run ID exists for the Workbench candidate. | Start Optimize from that eval run. |
| **Review required** | Workbench produced a review gate that expects human review before promotion. | Inspect the review gate and run Eval before promotion. |
| **Blocked** | A review gate or validation check found a required blocker. | Fix the specific reason shown in the UI. |
| **Interrupted** | A run was cancelled or recovered as stale/interrupted after process recovery. | Review preserved artifacts and start a follow-up turn or new run. |

The word **Ready** is intentionally scoped. **Ready for Eval** means the candidate can be evaluated. It does not mean the candidate is approved, optimized, or deployable.

## Restart and history behavior

Workbench keeps enough durable project and run state to make refreshes and restarts understandable:

- the page reloads project state from the backend instead of relying only on browser memory
- conversation turns and generated artifacts are restored into the Workbench feed
- the activity tab can show session handoff, evidence, review gate, and bridge details
- stale in-flight runs are marked as interrupted historical snapshots instead of continuing to look live

This is durable hydration, not true checkpoint resume. If the server restarts during an active run, Workbench can recover the run record, last events, artifacts, and handoff state. It does not automatically continue execution from the next incomplete task.

The user-facing expectation should be:

1. refresh or restart does not erase the last known Workbench state
2. interrupted work is labeled honestly
3. the operator can inspect what happened and start a follow-up turn
4. the harness does not pretend an interrupted run kept executing

## What Workbench does not do

Workbench is intentionally bounded.

- It does **not** replace Build. Build remains the faster authoring and XML instruction workflow.
- It does **not** run Eval inside the Workbench page. It hands a materialized candidate to Eval Runs.
- It does **not** start Optimize directly after a build. Optimize waits for a completed eval run.
- It does **not** call AutoFix as part of the handoff.
- It does **not** automatically approve, promote, deploy, or canary a candidate.
- It does **not** prove the agent improved just because structural validation passed.
- It does **not** provide a general autonomous correction loop for every failure class.
- It does **not** automatically resume execution after server restart.
- It does **not** currently support attachments in the Workbench composer.

These boundaries are product features, not shortcomings to hide. They keep eval budget, optimization, review, and deployment under operator control.

## Handling common blockers

| Blocker type | What it usually means | Practical next step |
|--------------|-----------------------|---------------------|
| **Missing generated config** | The run did not produce a candidate config that Eval can use. | Finish the run, revise the brief, or start a new Workbench turn. |
| **Validation failed** | Workbench structural checks did not pass. | Open Activity, read the failed checks, and correct the candidate before handoff. |
| **Invalid target compatibility** | The candidate uses something the selected target cannot support. | Change the target, remove or revise the unsupported tool/feature, or ask Workbench for a compatible follow-up. |
| **Review-gate blocker** | Human review or another required gate is still outstanding. | Inspect the review gate in Activity and resolve the listed reason before promotion. |
| **Waiting for eval** | Optimize has no completed eval run ID for this candidate. | Run Eval first, then start Optimize from the eval context. |

## Practical example

Suppose you want to build a customer support agent for refund escalations.

1. Open **Workbench**.
2. Enter a brief:

```text
Build a customer support agent that handles refund escalations, checks order history, explains policy limits, and escalates high-risk cases to a human reviewer.
```

3. Watch the plan and streamed task output.
4. Inspect the generated agent card and source previews.
5. Check the Activity tab for validation, evidence, review gate, and handoff state.
6. If Workbench shows **Draft only** or **Eval blocked**, resolve the listed blocker before moving on.
7. If it shows **Save candidate before Eval**, use **Save candidate and open Eval**.
8. In Eval Runs, start an eval for the materialized candidate.
9. Choose or confirm the eval suite and run settings in Eval Runs.
10. If the eval fails important cases, use the completed eval run as the basis for Optimize.
11. Review resulting proposals in Improvements before deploying anything.

The healthy path is not "Workbench made it, ship it." The healthy path is "Workbench built a candidate, Eval measured it, Optimize improved it if needed, Improvements captured the human decision, and Deploy shipped the reviewed version."

## CLI workflow

Workbench is also available from the CLI for terminal-first agent iteration.

```bash
agentlab workbench create "Build a customer support agent that handles refund escalations."
agentlab workbench build "Build a customer support agent that handles refund escalations."
agentlab workbench show
agentlab workbench iterate "Add a regression eval for refund requests with missing order ids."
agentlab workbench save
agentlab eval run --config <saved-config-path>
```

Useful commands:

| Command | Purpose |
|---------|---------|
| `agentlab workbench create "..."` | Create a new Workbench project from a brief. |
| `agentlab workbench build "..."` | Run the Workbench build loop for a brief. |
| `agentlab workbench show` | Inspect the candidate card, artifacts, validation, and bridge readiness. |
| `agentlab workbench status` | Show a compact readiness and next-step view. |
| `agentlab workbench iterate "..."` | Add a follow-up turn to the latest Workbench project. |
| `agentlab workbench save` | Materialize the candidate into the normal workspace config path for Eval. |
| `agentlab workbench bridge --json` | Print the typed Eval/Optimize bridge payload for automation. |
| `agentlab workbench plan "..."` | Plan changes without executing them. |
| `agentlab workbench test` | Run deterministic structural validation. |
| `agentlab workbench list` | List all Workbench projects. |

The CLI follows the same boundary as the web Workbench. `workbench save` writes the generated config into `configs/`, writes generated eval cases, sets the saved candidate as the active local config, and returns Eval/Optimize handoff data. It does not start Eval or Optimize.

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/workbench/projects/default` | Return the newest Workbench project or create a starter draft. |
| `GET` | `/api/workbench/projects/{project_id}/plan` | Hydrate the plan, artifacts, messages, active run, harness state, and run summary. |
| `POST` | `/api/workbench/build/stream` | Stream a fresh Workbench build run as server-sent events. |
| `POST` | `/api/workbench/build/iterate` | Stream a follow-up iteration on an existing Workbench project. |
| `POST` | `/api/workbench/projects/{project_id}/bridge/eval` | Materialize a Workbench candidate and return Eval/Optimize handoff payloads. |
| `POST` | `/api/workbench/runs/{run_id}/cancel` | Request server-side cancellation for an active Workbench run. |

## Troubleshooting

### Workbench says Candidate needed

No candidate has been generated yet. Enter a brief in the Workbench composer.

### Workbench says Save candidate before Eval

The generated candidate passed Workbench checks, but Eval needs a saved config path. Use the Workbench handoff action to materialize the candidate.

### Workbench says Run Eval before Optimize

That is expected. Optimize requires completed eval evidence for the candidate. Go to Eval Runs, run the eval, and then start Optimize from the eval context.

### A restored run is marked Interrupted

Workbench recovered a historical snapshot after refresh or server restart. Inspect the last event, artifacts, and session handoff, then start a follow-up turn or new run.

## Related docs

- [UI Quick Start](../UI_QUICKSTART_GUIDE.md)
- [App Guide](../app-guide.md)
- [Platform Overview](../platform-overview.md)
- [Prompt Optimization](prompt-optimization.md)
- [AutoFix Copilot](autofix.md)
