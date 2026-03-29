# AutoAgent VNextCC — P0 Architectural Overhaul

## Your Mission

You are rebuilding AutoAgent VNextCC's core architecture based on 12 P0 feature requests in `P0_FEATURE_REQUESTS.md`. This is a heavy refactor of backend, frontend, and architecture. Read that file first.

## Phase 1: Planning (do this FIRST before any code)

1. Read ALL existing code — understand the current architecture deeply:
   - `src/` (Python backend — optimizer, evals, agent, logger, API)
   - `web/` (React frontend — 9 pages, 20 components)
   - `ARCHITECTURE_OVERVIEW.md`
   - `autoagent.yaml` (config)
   - All test files

2. Create `P0_IMPLEMENTATION_PLAN.md` with:
   - For each of the 12 features: what changes, which files, estimated complexity
   - Dependencies between features (what must come first)
   - What to KEEP vs REPLACE vs REFACTOR
   - Execution order (dependency-aware)
   - What we intentionally simplify or defer (maintain user journey simplicity)
   - Architecture diagrams (ASCII) for the new system

3. Key design principles to maintain:
   - **Gemini-first**: Gemini 2.5 Pro is the default model
   - **Single-process**: No Celery/Redis/Kafka — SQLite for persistence
   - **Headless-first**: CLI + API primary, web console for insight
   - **Karpathy-simple where possible**: Don't over-engineer what can be kept simple
   - **User journey simplicity**: A user should still be able to `autoagent init` → `autoagent run` → see results

## Phase 2: Execution

After the plan is written and reviewed (by you), execute it. Use sub-agents for parallel independent work streams.

### Work Stream Architecture (suggested — adjust based on your plan):
- **Stream A**: Core domain models (MutationOperator registry, ExperimentCard, OpportunityQueue, SideEffectClasses)
- **Stream B**: Trace/diagnosis engine (ADK events, OTEL spans, trace-to-eval pipeline)
- **Stream C**: Search engine + statistical layer (multi-hypothesis, sequential testing, clustered bootstrap)
- **Stream D**: Frontend updates (new pages/components for opportunity queue, experiment cards, replay harness, trace viewer)

### For each stream:
- Write code with full type hints (Python 3.11+, TypeScript strict)
- Update/add tests (pytest for backend, Vitest for frontend)
- Update API endpoints as needed
- Update CLI commands as needed
- Update `autoagent.yaml` schema
- Update docs

## Phase 3: Integration & Verification

1. Merge all streams
2. Run full test suite — fix any failures
3. Build frontend — fix any TypeScript errors
4. Update `ARCHITECTURE_OVERVIEW.md` with new architecture
5. Write `CHANGELOG.md` entry for this release
6. Commit with conventional commit message

## Constraints

- Do NOT break the existing `autoagent optimize` → `autoagent deploy` flow
- Do NOT add Celery, Redis, Kafka, or any external service dependencies
- Do NOT switch away from Gemini as default model
- SQLite remains the persistence layer (Postgres as upgrade path only)
- Keep the web console clean and Apple/Linear-inspired
- Feature 10 (Google prompt optimizers) can be stubbed with TODO — we don't have Vertex credentials here
- Feature 12 (workflow/topology) should be marked experimental in code and UI

## When Done

Run: `openclaw system event --text "Done: AutoAgent VNextCC P0 overhaul — [summary of what changed, file counts, test counts]" --mode now`
