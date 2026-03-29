# Builder Workspace PRD

## Product thesis

Build a command center for agent builders:
- conversation is the control plane,
- artifacts are the source of truth,
- every mutating step is inspectable,
- background agent work is isolated and reviewable,
- the user can intervene at any point.

This should feel like Claude Code + Codex + Manus, but oriented around agent systems rather than only source code.

## Design principles

1. **Chat-first, not chat-only.**
   The conversation should drive the workflow, but the real outputs are plan cards, ADK graph diffs, source diffs, skill diffs, eval results, trace evidence, and release candidates.

2. **Every suggestion must resolve to artifacts.**
   No free-floating prose like "I improved the routing." The UI must show what changed, where, why, and how it scored.

3. **Pair mode and delegate mode must both exist.**
   Users need fast conversational iteration for small changes, and long-running background execution for bigger jobs.

4. **The builder agent is itself an agent system.**
   Use an orchestrator plus specialist subagents for architecture, tools, guardrails, evals, traces, and release.

5. **Project context must persist.**
   Builder sessions should inherit instructions, files, skills, permissions, and standards from a persistent project workspace.

6. **Safe by default.**
   Anything that writes code, changes runtime behavior, touches external tools, or deploys must be permissioned and reviewable.

## Primary user jobs

1. "Build me a new ADK agent for X from this English description."
2. "Improve this existing agent; here are the failing traces."
3. "Add a tool, skill, guardrail, or eval suite."
4. "Show me why the agent is underperforming and propose fixes."
5. "Try three variants in parallel and tell me which one wins."
6. "Turn this idea into code, run evals, and prepare a release."
7. "Hand this task to a coding agent backend, then bring the result back here."

## UX model

The correct UX is a hybrid of three modes:
- **Pair mode**: interactive back-and-forth editing, like pair programming.
- **Delegate mode**: long-running background tasks, like Codex app or Manus tasks.
- **Review mode**: artifact inspection and approval, like code review plus eval review.

The workspace should have five persistent regions:
- **Left rail**: projects, agents, sessions, tasks, notifications.
- **Center pane**: conversation timeline.
- **Right inspector**: source diff, ADK graph, evals, traces, skills, guardrails, files.
- **Bottom composer**: prompt, attachments, slash commands, mode picker.
- **Task drawer**: running/background jobs, approvals, blockers.

This should become the default authoring surface, not a side page. Existing pages such as AgentStudio, Assistant, Optimize, Experiments, Change Review, ADK Import, Skills, and Eval detail should become drill-down tabs or linked inspectors inside this workspace rather than separate disconnected flows.

---

## P0 Requirements

### P0-1. Make Builder Workspace the primary authoring surface

The builder should feel like a command center, not a thin chat shell.

**Requirements:**
- Builder Workspace becomes the default landing page for agent projects.
- Consolidate current fragmented authoring flows into one workspace:
  - AgentStudio
  - Assistant
  - Optimize
  - Experiments / Change Review
  - ADK Import / Export
  - relevant parts of Skills / Scorer / Traces / Evals
- Layout must include:
  - Left rail: projects, agents, sessions, tasks, favorites, notifications
  - Center pane: conversation timeline
  - Right inspector: selected artifact/details
  - Bottom composer: prompt, attachments, mode controls, slash commands
  - Task drawer: running/background jobs
- Top bar must expose:
  - active agent/project
  - current environment
  - mode
  - model/backend
  - permission state
  - pause/resume

### P0-2. Support both pair mode and delegate mode

**Requirements:**
- Add four execution modes:
  - Ask: explain/diagnose, no mutation
  - Draft: generate plans/artifacts, no writes
  - Apply: patch worktree + run evals
  - Delegate: background task with sandbox/worktree
- Add Branch as an action that spawns a parallel candidate.
- Every delegated task must run in its own isolated sandbox/worktree.
- Users must be able to: pause, resume, cancel, duplicate, fork a task
- Users must be able to leave the workspace and return without losing task state.
- The UI must stream live task status:
  - current step, active specialist, tool in use
  - elapsed time, estimated remaining work
  - token/cost counters
- Manual takeover must be possible at any time.

### P0-3. Make the conversation artifact-native

**Requirements:**
- Every mutating request must first produce a Plan Card with:
  - goal, assumptions, targeted artifacts/surfaces, expected impact, risk level, required approvals
- Every completed task must produce some combination of:
  - Source Diff Card, ADK Graph Diff Card, Skill Card, Guardrail Card, Eval Card, Trace Evidence Card, Benchmark Card, Release Card
- Every card must be selectable in the inspector.
- Users must be able to comment on any card or diff hunk and request revision.
- Every applied change must carry provenance:
  - task ID, session ID, buildtime skill(s) used, source/eval versions, release candidate ID
- The assistant must cite its evidence: source files, traces, eval runs, benchmark slices, prior accepted experiments

### P0-4. Represent agent-building as a multi-agent ADK workflow

**Requirements:**
- Implement the builder itself as an ADK-native multi-agent workflow.
- Minimum builder roles:
  - Orchestrator, Requirements Analyst, ADK Architect, Tool/Integration Engineer
  - Skill Author, Guardrail Author, Eval Author, Trace Analyst, Release Manager
- Each specialist subagent must have: separate context window, scoped tools, scoped permissions, clear responsibility
- The user must be able to see which specialist is currently active.
- The user must be able to explicitly invoke a specialist.
- The orchestrator must use existing buildtime skills and runtime skills as tools/primitives.
- The UI must show a live "builder roster" panel with status for each specialist.

### P0-5. Introduce Builder Projects with persistent instructions and knowledge

**Requirements:**
- Add a first-class Builder Project object.
- A Builder Project must include:
  - master instruction, attached knowledge files, buildtime skills, runtime skills
  - deployment targets, benchmark/eval defaults, permission defaults, preferred models/backends
- Every new conversation/task in a project inherits project context automatically.
- The UI must provide an Instructions & Memory panel for:
  - project memory, builder memory, AGENTS.md, CLAUDE.md, AUTOAGENT.md
- The UI must show scope/inheritance: project-wide, folder-specific, task-specific
- The UI must support attachments in chat: traces, SOPs, source trees, eval files, screenshots, diagrams, archives

### P0-6. Surface AGENTS.md, CLAUDE.md, and buildtime skills as first-class UI objects

**Requirements:**
- Add a dedicated Coding Agent Config tab.
- The tab must: render AGENTS.md, render CLAUDE.md, show directory scope, show precedence/override behavior
- Add a Buildtime Skills browser: searchable, previewable, installable, pin-able, invokable from chat
- The builder agent must be able to: generate new buildtime skills, update existing ones, export to SKILL.md
- The UI must show which memory/instruction files were actually loaded into the current task.

### P0-7. Inline evals, traces, and observability must live in the conversation

**Requirements:**
- Any mutating task must automatically run: targeted smoke tests, relevant eval slice(s), hard-gate checks
- The conversation must show before/after results inline.
- Eval cards must distinguish: trajectory quality, outcome quality, hard-gate status, cost/latency changes
- Trace cards must support: span timeline, blame/failure family, evidence links, one-click promote-to-eval
- Add a Compare view for "baseline vs candidate."
- Add a "Why did you propose this?" action that opens the full evidence chain.
- A mutating task cannot be marked "ready to apply" without an attached eval bundle.

### P0-8. Make skills, tools, and guardrails visible and editable from chat

**Requirements:**
- Add right-inspector tabs for: tools, runtime skills, buildtime skills, guardrails
- The builder must handle requests like:
  - "add a runtime skill for refunds"
  - "use the buildtime skill that writes evals"
  - "attach a PII guardrail to all sub-agents"
- Skills must show: manifest, provenance, permissions, effectiveness, security status
- Guardrails must show: where attached, inherited scope, failure examples, recent trips
- Users must be able to create, edit, attach, and detach all of these from the conversation.

### P0-9. Add explicit permissions, approvals, and human takeover

**Requirements:**
- All privileged actions must surface approval cards:
  - source writes, external network/tool use, secret access, deployment, benchmark spend above threshold
- Add a live Permissions panel with current grants.
- Users must be able to grant: once, for this task, for this project
- Users must be able to take over: stop agent execution, open artifact in editor, make manual changes, hand control back
- All builder actions must be logged and replayable.
- Protected environments must require stronger approvals than dev/sandbox environments.

### P0-10. Use chat-native widgets and actions, not plain text prompts

**Requirements:**
- Message types must support interactive widgets.
- Minimum widget/action set:
  - Approve, Reject, Revise, Run evals, Compare candidates, Promote trace
  - Create skill, Attach guardrail, Open diff, Create PR, Roll back
- Support structured forms inside the thread for: new tool config, benchmark selection, environment variables, deployment settings
- Add slash commands:
  - /plan, /improve, /trace, /eval, /skill, /guardrail, /compare
  - /branch, /deploy, /rollback, /memory, /permissions
- Add command-palette equivalents for non-terminal users.

### P0-11. Define a first-class session/task/proposal data model

**Requirements:**
- Add these core objects:
  - BuilderProject, BuilderSession, BuilderTask, BuilderProposal
  - ArtifactRef, ApprovalRequest, WorktreeRef, SandboxRun
  - EvalBundle, TraceBookmark, ReleaseCandidate
- Each builder response must resolve to one or more objects above.
- Add streaming event types:
  - message.delta, task.started, task.progress, plan.ready
  - artifact.updated, eval.started, eval.completed
  - approval.requested, task.completed, task.failed
- Add new APIs under /api/builder/*.
- SSE and WebSocket must both be supported.
- The UI must reconnect cleanly after refresh and resume task state.

### P0-12. The builder agent itself must be observable and evaluable

**Requirements:**
- Trace every builder session with the same observability model used elsewhere.
- Add builder-specific metrics:
  - time to first plan, acceptance rate, revert rate
  - eval coverage delta, unsafe action rate, average revisions per accepted change
- Add a builder eval suite:
  - ambiguous spec resolution, safe mutation behavior, correct artifact selection
  - diff quality, eval-authoring quality
- Builder sessions must themselves be promotable into regression tests.
