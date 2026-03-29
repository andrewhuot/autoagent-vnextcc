# Builder Workspace — Full Implementation

Read BUILDER_WORKSPACE_PRD.md for the complete product requirements.
Read BUILDER_IMPLEMENTATION_PLAN.md for the architecture overview.

You are building the ENTIRE Builder Workspace — backend AND frontend — in one session. This is a massive feature that transforms AutoAgent into a command center for agent builders.

## What to Build

### Backend: `builder/` Python module

Create these files:

1. **builder/__init__.py** — Module exports

2. **builder/types.py** — Core data model:
   - Enums: ExecutionMode (Ask/Draft/Apply/Delegate), TaskStatus (pending/running/paused/completed/failed/cancelled), ArtifactType (plan/source_diff/adk_graph_diff/skill/guardrail/eval/trace_evidence/benchmark/release), ApprovalScope (once/task/project), SpecialistRole (orchestrator/requirements_analyst/adk_architect/tool_engineer/skill_author/guardrail_author/eval_author/trace_analyst/release_manager)
   - Dataclasses: BuilderProject, BuilderSession, BuilderTask, BuilderProposal, ArtifactRef, ApprovalRequest, WorktreeRef, SandboxRun, EvalBundle, TraceBookmark, ReleaseCandidate
   - Each with full fields, timestamps, IDs

3. **builder/store.py** — SQLite persistence for all builder objects. Tables for projects, sessions, tasks, proposals, artifacts, approvals, worktrees, sandboxes, eval_bundles, trace_bookmarks, release_candidates. Full CRUD operations.

4. **builder/orchestrator.py** — Multi-agent orchestrator that routes user requests to specialist subagents. Tracks active specialist. Handoff protocol between specialists. Uses intent detection to pick the right specialist.

5. **builder/specialists.py** — 9 specialist subagent definitions. Each has: role, description, tools list, permission scope, context template. Specialists: Orchestrator, Requirements Analyst, ADK Architect, Tool/Integration Engineer, Skill Author, Guardrail Author, Eval Author, Trace Analyst, Release Manager.

6. **builder/execution.py** — Task execution engine. Four modes: Ask (read-only, no mutations), Draft (generate plans/artifacts, no writes), Apply (patch worktree + run evals), Delegate (background sandbox). Task lifecycle: create, start, pause, resume, cancel, duplicate, fork. Worktree isolation for delegate mode.

7. **builder/permissions.py** — Permission model. Privileged action types: source_write, external_network, secret_access, deployment, benchmark_spend. Approval card generation. Grant scopes: once, task, project. Human takeover: stop, edit, hand back. Action logging.

8. **builder/artifacts.py** — Artifact card factories. Card types: PlanCard, SourceDiffCard, ADKGraphDiffCard, SkillCard, GuardrailCard, EvalCard, TraceEvidenceCard, BenchmarkCard, ReleaseCard. Each includes provenance: task_id, session_id, skills_used, source_versions, release_candidate_id, timestamp.

9. **builder/projects.py** — BuilderProject manager. CRUD. Instruction inheritance (project → folder → task). Knowledge file management. Skill/eval defaults. Model preferences. Deployment targets.

10. **builder/events.py** — Streaming event system. Event types: message.delta, task.started, task.progress, plan.ready, artifact.updated, eval.started, eval.completed, approval.requested, task.completed, task.failed. SSE serialization.

11. **builder/metrics.py** — Builder metrics: time_to_first_plan, acceptance_rate, revert_rate, eval_coverage_delta, unsafe_action_rate, avg_revisions_per_change. Aggregation from task/session history.

12. **api/routes/builder.py** — FastAPI router with 25+ endpoints:
    - Projects: list, create, get, update, delete
    - Sessions: list, create, get, close
    - Tasks: list, create, get, pause, resume, cancel, duplicate, fork
    - Proposals: list, get, approve, reject, revise
    - Artifacts: list, get, comment
    - Approvals: list, respond
    - Permissions: list_grants, create_grant, revoke_grant
    - Events: SSE stream endpoint
    - Metrics: get builder metrics
    - Specialists: list, invoke specific specialist

### Frontend: React/TypeScript

Create these files:

13. **web/src/lib/builder-types.ts** — TypeScript types matching all Python dataclasses and enums.

14. **web/src/lib/builder-api.ts** — API client with fetch for all builder endpoints. Error handling. Typed responses.

15. **web/src/lib/builder-websocket.ts** — WebSocket client for streaming events. Auto-reconnect. Typed event handlers.

16. **web/src/pages/BuilderWorkspace.tsx** — Main workspace page with 5 regions:
    - Left rail (260px, collapsible): projects, agents, sessions, tasks, notifications
    - Center pane: conversation timeline with inline artifact cards
    - Right inspector (380px, collapsible): tabbed detail views
    - Bottom composer: prompt input, mode selector, attachments, slash commands
    - Task drawer: running jobs, approvals, completed tasks
    - Top bar: project/agent selector, environment, mode, model, permissions, pause/resume
    Use CSS Grid. State management with React hooks. This should feel like VS Code / Linear.

17. **web/src/components/builder/TopBar.tsx** — Project selector, environment dropdown, mode indicator, model selector, permission state, pause/resume.

18. **web/src/components/builder/LeftRail.tsx** — Collapsible sidebar with project tree, sessions, tasks, favorites, notifications.

19. **web/src/components/builder/ConversationPane.tsx** — Chat timeline with specialist indicators, inline cards, streaming, auto-scroll.

20. **web/src/components/builder/Inspector.tsx** — Right panel with tabs: Overview, Diff, ADK Graph, Evals, Traces, Skills, Guardrails, Files, Config.

21. **web/src/components/builder/Composer.tsx** — Input area with mode selector, attachments, slash command trigger, send button.

22. **web/src/components/builder/TaskDrawer.tsx** — Running tasks, progress, approvals, completed tasks.

23-33. **web/src/components/builder/cards/** — 11 card components:
    PlanCard, SourceDiffCard, ADKGraphDiffCard, SkillCard, GuardrailCard, EvalCard, TraceEvidenceCard, BenchmarkCard, ReleaseCard, ApprovalCard, CompareView

34-40. **web/src/components/builder/widgets/** — 7 widget components:
    ActionButton, SlashCommandMenu, FormWidget, ModeSelector, SpecialistRoster, PermissionsPanel, CommandPaletteExtended

41-49. **web/src/components/builder/inspector/** — 9 inspector tabs:
    ToolsTab, RuntimeSkillsTab, BuildtimeSkillsTab, GuardrailsTab, FilesTab, CodingAgentConfigTab, EvalResultsTab, TraceViewerTab, InstructionsMemoryTab

50. **Update web/src/App.tsx** — Add BuilderWorkspace routes (/ and /builder/*), keep all existing routes
51. **Update web/src/components/Sidebar.tsx** — Add Builder Workspace as first nav item
52. **Update api/server.py** — Register builder routes

### Tests

53-60. **tests/test_builder_*.py** — 8 test files covering store, API, orchestrator, execution, permissions, artifacts, projects, metrics.

## Design Requirements

- Dark theme (existing dark navy/charcoal palette)
- Inter font, neutral grays (existing design tokens)
- Linear/Vercel/VS Code aesthetic
- Cards look like GitHub PR review cards
- All interactive elements have hover states and transitions
- Loading skeletons for async content
- Empty states with helpful prompts
- Responsive panels

## Quality Standards

- Every file complete — no stubs, no TODOs, no placeholders
- Production-quality code
- Proper TypeScript types
- Proper Python type hints
- Tests must pass

When completely finished with everything, run all builder tests:
```
cd /Users/andrew/Desktop/AutoAgent-VNextCC && .venv/bin/pytest tests/test_builder_*.py -v 2>&1 | tail -40
```

Then signal completion:
```
openclaw system event --text "Done: Codex Builder Workspace — full backend (builder/ module, 11 files) + full frontend (40+ components) + 8 test files + integration wiring" --mode now
```
