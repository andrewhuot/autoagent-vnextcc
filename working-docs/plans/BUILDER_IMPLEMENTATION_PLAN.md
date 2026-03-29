# Builder Workspace Implementation Plan

## Architecture Overview

This PRD requires 5 parallel workstreams that can be built independently and then wired together:

### Stream 1: Backend Data Model + API (Python)
New module: `builder/` with core data model + API routes under `/api/builder/*`

**Files to create:**
- `builder/__init__.py` — exports
- `builder/types.py` — BuilderProject, BuilderSession, BuilderTask, BuilderProposal, ArtifactRef, ApprovalRequest, WorktreeRef, SandboxRun, EvalBundle, TraceBookmark, ReleaseCandidate
- `builder/store.py` — SQLite persistence for all builder objects
- `builder/orchestrator.py` — Multi-agent orchestrator (routes to specialists)
- `builder/specialists.py` — 9 specialist subagent definitions (Requirements, Architect, Tool Engineer, Skill Author, Guardrail Author, Eval Author, Trace Analyst, Release Manager)
- `builder/execution.py` — Execution engine: Ask/Draft/Apply/Delegate modes, task lifecycle, sandbox/worktree management
- `builder/permissions.py` — Permission model: once/task/project grants, approval cards, privileged action detection
- `builder/artifacts.py` — Artifact card generation: PlanCard, SourceDiffCard, ADKGraphDiffCard, SkillCard, GuardrailCard, EvalCard, TraceEvidenceCard, BenchmarkCard, ReleaseCard
- `builder/projects.py` — BuilderProject manager: instructions, knowledge files, skill/eval defaults, model preferences
- `builder/events.py` — SSE + WebSocket streaming event types
- `builder/metrics.py` — Builder-specific metrics: time to first plan, acceptance rate, revert rate, etc.
- `api/routes/builder.py` — FastAPI routes for all builder endpoints

### Stream 2: Frontend — Workspace Layout Shell (React/TSX)
The main workspace layout with 5 persistent regions.

**Files to create:**
- `web/src/pages/BuilderWorkspace.tsx` — Main workspace page (becomes default landing)
- `web/src/components/builder/LeftRail.tsx` — Projects, agents, sessions, tasks, favorites, notifications
- `web/src/components/builder/ConversationPane.tsx` — Center conversation timeline with artifact cards inline
- `web/src/components/builder/Inspector.tsx` — Right inspector: tabs for diff, ADK graph, evals, traces, skills, guardrails, files
- `web/src/components/builder/Composer.tsx` — Bottom composer: prompt, attachments, mode picker, slash commands
- `web/src/components/builder/TaskDrawer.tsx` — Running/background jobs, approvals, blockers
- `web/src/components/builder/TopBar.tsx` — Active agent/project, environment, mode, model, permissions, pause/resume
- `web/src/components/builder/index.ts` — Barrel exports

### Stream 3: Frontend — Artifact Cards + Interactive Widgets (React/TSX)
All the card types and interactive actions that live in the conversation.

**Files to create:**
- `web/src/components/builder/cards/PlanCard.tsx` — Goal, assumptions, targets, impact, risk, approvals
- `web/src/components/builder/cards/SourceDiffCard.tsx` — Inline diff with comment/revise
- `web/src/components/builder/cards/ADKGraphDiffCard.tsx` — Before/after agent graph visualization
- `web/src/components/builder/cards/SkillCard.tsx` — Skill manifest, provenance, effectiveness
- `web/src/components/builder/cards/GuardrailCard.tsx` — Attached scope, failure examples, trips
- `web/src/components/builder/cards/EvalCard.tsx` — Trajectory/outcome quality, hard-gate, cost/latency
- `web/src/components/builder/cards/TraceEvidenceCard.tsx` — Span timeline, blame, evidence links
- `web/src/components/builder/cards/BenchmarkCard.tsx` — Benchmark comparison
- `web/src/components/builder/cards/ReleaseCard.tsx` — Release candidate details
- `web/src/components/builder/cards/ApprovalCard.tsx` — Approve/Reject/Revise actions
- `web/src/components/builder/cards/CompareView.tsx` — Baseline vs candidate comparison
- `web/src/components/builder/cards/index.ts` — Barrel exports
- `web/src/components/builder/widgets/ActionButton.tsx` — Approve, Reject, Revise, Run evals, etc.
- `web/src/components/builder/widgets/SlashCommandMenu.tsx` — /plan, /improve, /trace, etc.
- `web/src/components/builder/widgets/FormWidget.tsx` — Structured forms for tool config, env vars, etc.
- `web/src/components/builder/widgets/ModeSelector.tsx` — Ask/Draft/Apply/Delegate mode picker
- `web/src/components/builder/widgets/SpecialistRoster.tsx` — Live builder roster panel
- `web/src/components/builder/widgets/PermissionsPanel.tsx` — Current grants + permission actions
- `web/src/components/builder/widgets/CommandPaletteExtended.tsx` — Extended command palette
- `web/src/components/builder/widgets/index.ts` — Barrel exports

### Stream 4: Frontend — Inspector Tabs (React/TSX)
Right-panel inspector tabs for tools, skills, guardrails, files, coding agent config.

**Files to create:**
- `web/src/components/builder/inspector/ToolsTab.tsx` — Tool browser with attach/detach
- `web/src/components/builder/inspector/RuntimeSkillsTab.tsx` — Runtime skills browser
- `web/src/components/builder/inspector/BuildtimeSkillsTab.tsx` — Buildtime skills browser (search, preview, install, pin)
- `web/src/components/builder/inspector/GuardrailsTab.tsx` — Guardrails browser with scope visualization
- `web/src/components/builder/inspector/FilesTab.tsx` — Project files browser
- `web/src/components/builder/inspector/CodingAgentConfigTab.tsx` — AGENTS.md, CLAUDE.md renderer with scope
- `web/src/components/builder/inspector/EvalResultsTab.tsx` — Eval results with before/after
- `web/src/components/builder/inspector/TraceViewerTab.tsx` — Trace span timeline
- `web/src/components/builder/inspector/InstructionsMemoryTab.tsx` — Project memory, AUTOAGENT.md
- `web/src/components/builder/inspector/index.ts` — Barrel exports

### Stream 5: Integration + Tests (Python + TSX)
Wire everything together, update routing, add tests.

**Files to create/modify:**
- `web/src/lib/builder-api.ts` — API client for all builder endpoints
- `web/src/lib/builder-types.ts` — TypeScript types matching Python data model
- `web/src/lib/builder-websocket.ts` — WebSocket client for streaming events
- `web/src/App.tsx` — Updated routing: BuilderWorkspace as default, existing pages as drill-down
- `web/src/components/Layout.tsx` — Updated layout for workspace mode
- `web/src/components/Sidebar.tsx` — Updated sidebar with builder-first navigation
- `api/server.py` — Register builder routes
- `tests/test_builder_store.py` — Builder data model tests
- `tests/test_builder_api.py` — Builder API endpoint tests
- `tests/test_builder_orchestrator.py` — Orchestrator + specialist routing tests
- `tests/test_builder_execution.py` — Execution mode tests
- `tests/test_builder_permissions.py` — Permission model tests
- `tests/test_builder_artifacts.py` — Artifact card generation tests
- `tests/test_builder_projects.py` — Project persistence tests
- `tests/test_builder_metrics.py` — Builder metrics tests

## Dispatch Strategy

5 CC Sonnet sessions, each with clear scope:
1. **Backend** — `builder/` module + `api/routes/builder.py` + all backend tests
2. **Layout** — Workspace shell + TopBar + LeftRail + ConversationPane + Inspector + Composer + TaskDrawer
3. **Cards** — All artifact cards + interactive widgets + specialist roster
4. **Inspector** — All inspector tabs + coding agent config
5. **Integration** — API client, types, websocket, App.tsx routing, Sidebar updates, server.py wiring
