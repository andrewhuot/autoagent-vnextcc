# Workbench Model Harness — Architecture

## Overview

The Workbench model harness transforms AgentLab's builder UI from a mock/demo shell into a real agent-building tool. Users submit natural-language briefs, a harness engine plans and executes the build, and the UI shows live progress, artifacts, and iteration controls.

## Core Loop: Plan → Act → Reflect → Present

```
User Brief
    ↓
┌─────────────────────────────────────┐
│  HarnessExecutionEngine             │
│                                     │
│  1. PLAN    → Generate PlanTask tree│
│  2. ACT     → Execute leaf tasks    │
│  3. REFLECT → Assess quality        │
│  4. PRESENT → Emit final artifacts  │
│                                     │
│  Events streamed via SSE ──────────────→ Zustand Store → React UI
└─────────────────────────────────────┘
    ↓
User iterates with follow-up message
    ↓
HarnessExecutionEngine.iterate()
    → Modifies existing plan/artifacts
    → Re-runs changed tasks only
```

## Key Design Decisions

### 1. No External API Keys Required
The harness uses intelligent deterministic generation (not mock/random). It analyzes the brief, infers domain, and generates domain-aware content using templates enhanced with brief context. This means the harness works out of the box for any user.

When real LLM provider keys are available, the harness upgrades to LLM-driven planning and execution using the prompts in `workbench_prompts.py`.

### 2. Same SSE Protocol
All existing events (`plan.ready`, `task.started`, `artifact.updated`, etc.) are preserved. New events are additive:
- `harness.metrics` — periodic metrics updates
- `reflection.completed` — quality assessment per task group
- `iteration.started` — signals a new iteration cycle

### 3. Iteration as First-Class Concept
Users can submit follow-up messages after a build completes. The harness:
- Preserves existing artifacts as `previousVersionArtifacts`
- Generates a delta plan targeting only changed areas
- Bumps version number
- Enables diff view in the artifact viewer

### 4. Checkpointing
Every step saves state to the WorkbenchStore (JSON persistence). A page reload resumes from the last checkpoint via the existing `/projects/{id}/plan` snapshot endpoint.

## File Map

### Backend (Python)
| File | Role |
|------|------|
| `builder/harness.py` | **NEW** — HarnessExecutionEngine, plan/act/reflect/present cycle |
| `builder/workbench_agent.py` | Enhanced LiveWorkbenchBuilderAgent using harness engine |
| `builder/workbench.py` | Updated WorkbenchService with iteration support |
| `api/routes/workbench.py` | New `/build/iterate` endpoint |

### Frontend (TypeScript/React)
| File | Role |
|------|------|
| `web/src/lib/workbench-store.ts` | Harness metrics, iteration state, reflection entries |
| `web/src/lib/workbench-api.ts` | New types, iteration API client |
| `web/src/components/workbench/HarnessMetricsBar.tsx` | **NEW** — metrics display |
| `web/src/components/workbench/IterationControls.tsx` | **NEW** — iteration UI |
| `web/src/components/workbench/ReflectionCard.tsx` | **NEW** — quality reflection cards |
| `web/src/components/workbench/ArtifactViewer.tsx` | Enhanced with diff tab |
| `web/src/pages/AgentWorkbench.tsx` | Wired iteration flow |

## Metrics Tracked
- Steps completed / total steps
- Tokens consumed (estimated for deterministic mode)
- Cost in USD (estimated)
- Wall-clock elapsed time
- Current phase (planning/executing/reflecting/presenting)
- Iteration count

## Tradeoffs
- **Deterministic vs LLM**: Ship deterministic-but-intelligent generation now; LLM integration is ready to plug in
- **Iteration scope**: Full rebuild per iteration (simpler) vs delta-only (complex but faster) — starting with full rebuild with diff comparison
- **Persistence**: JSON file store (existing) vs SQLite (richer) — keeping JSON for workbench state, SQLite for builder objects

## Follow-up Work
- [ ] Real LLM integration via optimizer.providers.LLMRouter
- [ ] Sandbox execution for generated code validation
- [ ] Multi-agent delegation (specialist handoffs during build)
- [ ] Eval suite auto-execution after build
- [ ] Deployment pipeline integration
