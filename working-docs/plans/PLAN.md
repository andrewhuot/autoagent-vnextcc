# AutoAgent VNextCC — Implementation Plan

## Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Frontend | React + Vite + TypeScript | Simpler than Next.js, no SSR needed for dev tool |
| Styling | Tailwind CSS | Matches Linear/Vercel aesthetic, utility-first |
| State | React Query + Zustand | React Query for server state, Zustand for UI state |
| Charts | Recharts | Lightweight, React-native, good for sparklines |
| Router | React Router v6 | Standard, well-known |
| Backend | FastAPI (existing) | Already started, good WebSocket support |
| WebSocket | FastAPI WebSocket | Real-time eval/optimize/loop progress |
| CLI | Click (existing) | Already started, enhance with subcommands |
| API Docs | FastAPI auto-generated | OpenAPI/Swagger at /docs |
| Testing | Playwright (frontend), Pytest (backend) | As specified in brief |

## Build Order & Phases

### Phase 1: Backend API Layer (foundation for everything)
**Files to create/modify:**
1. `api/__init__.py` — API package
2. `api/routes/eval.py` — `/api/eval/*` endpoints
3. `api/routes/optimize.py` — `/api/optimize/*` endpoints
4. `api/routes/config.py` — `/api/config/*` endpoints
5. `api/routes/health.py` — `/api/health` endpoint
6. `api/routes/conversations.py` — `/api/conversations` endpoints
7. `api/routes/deploy.py` — `/api/deploy/*` endpoints
8. `api/routes/loop.py` — `/api/loop/*` endpoints
9. `api/websocket.py` — WebSocket for real-time progress
10. `api/models.py` — Pydantic request/response models
11. `api/tasks.py` — Background task manager for long-running ops
12. `api/server.py` — Main FastAPI app (replace agent/server.py)

### Phase 2: Frontend Shell + Dashboard
**Files to create:**
1. `web/` — Vite project scaffold
2. `web/src/App.tsx` — Router + layout
3. `web/src/components/Layout.tsx` — Sidebar + header
4. `web/src/pages/Dashboard.tsx` — Health score, metrics, recent activity
5. `web/src/lib/api.ts` — API client + React Query hooks
6. `web/src/lib/websocket.ts` — WebSocket client

### Phase 3: Frontend Pages (parallel build)
1. `web/src/pages/EvalRuns.tsx` — List eval runs
2. `web/src/pages/EvalDetail.tsx` — Single run results
3. `web/src/pages/Optimize.tsx` — Optimization trigger + history
4. `web/src/pages/Configs.tsx` — Config versions + diff
5. `web/src/pages/Conversations.tsx` — Log browser
6. `web/src/pages/Deploy.tsx` — Deployment management
7. `web/src/pages/LoopMonitor.tsx` — Live loop progress
8. `web/src/pages/Settings.tsx` — Configuration

### Phase 4: Enhanced CLI
**Modify:** `runner.py` → full command set with subcommands

### Phase 5: Documentation
**Create:** `docs/` with 9 files

### Phase 6: Docker + Polish
1. `Dockerfile`
2. `docker-compose.yaml`
3. Playwright tests for all pages
4. End-to-end verification

## Dependencies
```
Phase 1 (API) → Phase 2 (Frontend shell) → Phase 3 (Pages)
Phase 1 (API) → Phase 4 (CLI) [parallel with Phase 2-3]
Phase 1-4 → Phase 5 (Docs)
Phase 1-5 → Phase 6 (Polish)
```

## Scope Estimates
- Phase 1: ~1200 lines (API layer)
- Phase 2: ~600 lines (frontend shell)
- Phase 3: ~2400 lines (8 pages)
- Phase 4: ~400 lines (CLI enhancement)
- Phase 5: ~2000 lines (docs)
- Phase 6: ~300 lines (Docker + tests)
- **Total: ~7000 lines new code**
