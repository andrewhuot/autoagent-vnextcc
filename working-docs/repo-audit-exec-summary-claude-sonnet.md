# AgentLab Repo Audit — Executive Summary
**Audit date:** 2026-04-12  
**Auditor:** Claude Sonnet 4.6 (with Claude Opus 4.6 recommendations pass)  
**Branch:** audit/full-repo-understanding-claude-sonnet  
**Scope:** Full-repo audit — architecture, journeys, docs vs reality, product + codebase recommendations

---

## What This Is

AgentLab is a **closed-loop agent optimization platform**. Its core value proposition is the BUILD → EVAL → OPTIMIZE → REVIEW → DEPLOY cycle for AI agents. It is:
- A Python backend (FastAPI, ~46,600 lines)
- A React frontend (79 pages, ~6,000 lines)
- A CLI with ~30 command groups
- A FastAPI server with 59 route modules
- An MCP server (22 tools exposing the full platform to coding agents)
- Single-tenant, SQLite-backed, local-first (also deployable to Cloud Run / Fly.io)

The system is at version 3.0.0 as of the CHANGELOG, with a test suite of 1,131 tests (240 Python test files, 53 frontend test files, 11 Playwright E2E specs).

---

## Major Repo Sections Understood

| Section | What it does |
|---------|-------------|
| `builder/` | Workbench builder — converts NL brief to agent config via Plan→Execute→Reflect→Present harness |
| `optimizer/` | Optimization loop — observe failures, propose mutations, eval, gate, deploy |
| `evals/` | Eval infrastructure — 11-dim scoring, anti-Goodhart protection, statistics |
| `observer/` | Observability — traces, opportunity queue, blame map, trace grading |
| `api/` | FastAPI server — 59 route modules, 40+ stores/services initialized at startup |
| `web/` | React frontend — 79 pages, Zustand + React Query + three streaming protocols |
| `deployer/` | Canary deployment — versioning, canary logic, lineage |
| `registry/` | Modular registry — skills, policies, tool contracts, handoff schemas |
| `judges/` | Judge versioning, calibration, drift monitoring |
| `context/` | Context window workbench — per-trace analysis, compaction simulation |
| `mcp_server/` | MCP server — 22 tools + 5 prompts + 3 resource types |
| `adk/`, `cx_studio/`, `adapters/` | External agent imports — ADK, Dialogflow CX, OpenAI Agents, HTTP |
| `policy_opt/` | Policy optimization stubs (DPO/RLHF, Vertex backends) |
| `multi_agent/`, `a2a/` | Multi-agent teams and A2A protocol (low test coverage) |
| `runner.py` | Single-file CLI entrypoint (445KB — significant maintainability concern) |

---

## Main User Journeys (Status)

| Journey | Status | Key gap |
|---------|--------|---------|
| New user setup | Works with friction | No workspace init from UI; hard handoff to CLI |
| Build → save agent | Works | Builder chat sessions not persistent across restarts |
| Eval → inspect results | Works | Task history vanishes on restart (ephemeral TaskManager) |
| Optimize → review → deploy | Works with gaps | Two separate review queues; canary promote CLI-only |
| Connect (import ADK/CX) | Broken end-to-end | Imported agents don't register with running server |
| CX Studio | Works with friction | Two overlapping CX surfaces with no handoff |
| Improvements / Review | Incomplete | Only shows intelligence proposals, not optimizer proposals |

---

## Architecture: Core Strengths

1. **Builder contract faithfully implemented** — BUILDER_CONTRACT.md is a precise spec; `harness.py` closely implements all phases, events, checkpoints, and fallbacks.
2. **Rich eval infrastructure** — 11-dimension scoring, anti-Goodhart dual holdout, statistical significance, judge calibration. This is production-grade.
3. **Layered persistence** — Most operational state durably persisted to SQLite. Reliability primitives (checkpoints, dead letters, watchdog, graceful shutdown) are solid.
4. **Mock-first design** — Entire system runs without API keys. Good for dev/demo/CI.
5. **Strong MCP surface** — 22 tools expose the full platform to coding agents.

## Architecture: Core Risks

1. **SQLite only** — 15+ distinct databases, no multi-instance support, not cloud-native scalable.
2. **No auth/RBAC in production** — `auth.py`, `rbac.py`, `multi_tenant.py` are stubs, not wired into middleware.
3. **Server CWD as invisible dependency** — Build/optimize/deploy all fail silently if the server isn't started from a workspace directory.
4. **Ephemeral state** — Task status, canary metrics, builder sessions are in-memory. Server restarts degrade active workflows.
5. **Three separate event systems** — EventBroker, EventLog, WebSocket — no unified bus.
6. **runner.py is 445KB** — Single-file CLI, blocking parallel development.

---

## Key Gaps: Docs vs Reality

Seven significant gaps between documented behavior and actual implementation:

| Feature | Gap |
|---------|-----|
| Pro mode optimization (MIPROv2/GEPA/SIMBA) | `search_strategy: pro` rejected by Pydantic; `_optimize_pro()` uses MockProvider; unreachable from any user path |
| `search_strategy` in agentlab.yaml | Parsed but not passed to Optimizer constructor; silently ignored |
| AutoFix eval + canary stages | `apply()` is a pure config mutation; no eval, no gates, no canary; fields always return empty strings |
| Drift monitor | Uses hardcoded threshold, receives empty verdicts list, "pause on drift" behavior doesn't exist |
| Context aggregate report | Stub endpoint returning all zeros; CLI prints static string |
| BlameMap → optimizer feedback | Blame clusters computed but never consumed by optimizer FailureClusterer |
| Context handoff scoring | `score_handoff()` implemented but not called from `analyze_trace()` |

**Common pattern:** Most gaps are "last-mile wiring" — the data structures and algorithms exist, but the config values aren't passed through and the outputs aren't consumed by downstream systems.

---

## Top Recommendations (from Opus pass)

### P0 — Fix before next user-facing release

1. **Wire `search_strategy` to Optimizer** (1 day) — `api/server.py:245-260` passes hardcoded value; pass `runtime_config.search_strategy`
2. **Fix pro mode OR remove from docs** (2-3 days) — Add `"pro"` to Literal type + wire real LLMRouter, OR honest documentation update
3. **Wire drift monitor** (2-3 days) — Pass `drift_threshold` from config; pass real verdicts list
4. **Update AutoFix docs to match reality** (1 day) — Remove stages 5-6 from docs or implement them
5. **Add workspace validation at startup** (2-3 days) — Detect bad CWD, show blocking banner in UI, add `--workspace` flag
6. **Fix context report OR remove from docs** (1-3 days)

### P1 — Core journey improvements (next sprint)

1. **Unified review queue** — Single operator surface for all pending decisions
2. **Canary promote button in Deploy page** — Complete the deployment workflow in web UI
3. **Persist TaskManager to SQLite** — Eval/optimize history survives restarts
4. **Persist builder chat sessions** — Build sessions survive restarts
5. **Fix Connect import to register with running server** — Imported agents visible immediately
6. **Wire BlameMap into optimizer** — Close the trace grading → optimization feedback loop

### P2 — Architecture cleanup

1. Split `runner.py` into per-command modules (1-2 weeks)
2. Split `api.ts` into domain modules (1 week)
3. Consolidate 15+ SQLite databases into ~5 logical groups
4. Unify three event systems behind single EventLog
5. Standardize on SSE for all streaming (eliminate fetch-stream)
6. Delete dead code: backup files, stub routes, disconnected algorithms

### P3 — Product expansion

1. Multi-agent graph optimization (realize the `AgentNode`/`AgentEdge` IR)
2. MCP typed patch bundle contract (external agents submit structured config mutations)
3. Workspace init from web UI (eliminate first-run CLI requirement)

---

## Remaining Uncertainty

Areas where the audit has lower confidence:

1. **`a2a/` and `multi_agent/` modules** — both have zero tests and were not deeply audited. Their production readiness is unknown.
2. **`policy_opt/` backends** — described as stubs requiring Vertex credentials; not validated against real Vertex APIs.
3. **CX Studio end-to-end** — the GCP integration requires live credentials; functional correctness of the sync/deploy flow was not end-to-end verified.
4. **Real-world LLM provider behavior** — all key builder/optimizer paths were traced in mock mode; edge cases with live providers (rate limiting, partial responses, timeouts) were not validated.
5. **Canary traffic split semantics** — the system treats canary as semantic (version designation), not as real traffic routing. Whether this is sufficient for real production use cases depends on the deployment target.

---

## Branch and Commit

All audit documents written to `working-docs/` on branch `audit/full-repo-understanding-claude-sonnet`:

| File | Contents |
|------|---------|
| `working-docs/repo-audit-inventory-claude-sonnet.md` | Directory map, module inventory, API route index, persistence map |
| `working-docs/repo-user-journeys-claude-sonnet.md` | 8 user/operator journeys with frontend, API, backend, and gap analysis |
| `working-docs/repo-architecture-synthesis-claude-sonnet.md` | Subsystem interplay, state flow, contracts, persistence, tensions |
| `working-docs/repo-docs-vs-reality-claude-sonnet.md` | 17 feature areas compared against code; gap table with classifications |
| `working-docs/repo-product-and-codebase-recommendations-opus.md` | Opus architect recommendations: P0–P3 + roadmap phases |
| `working-docs/repo-audit-exec-summary-claude-sonnet.md` | This document |

---

## What Was Verified

- Read and analyzed: README, BUILDER_CONTRACT.md, CHANGELOG, OPTIMIZATION_COMPONENTS_AUDIT.md, agentlab.yaml, pyproject.toml, Dockerfile, docker-compose.yaml, all deploy/ scripts
- Explored and mapped: all 59 API route modules, builder/ stack, optimizer/ stack, evals/ stack, observer/ stack, web/ frontend (pages, components, lib)
- Tested (code-level): specific code paths in harness.py, workbench.py, loop.py, autofix.py, context/analyzer.py, judges/drift_monitor.py, mode_router.py, api/server.py constructor calls
- Key docs read: docs/platform-overview.md, docs/architecture.md, docs/concepts.md, all docs/features/ files, docs/QUICKSTART_GUIDE.md, docs/DETAILED_GUIDE.md
- What was NOT run: live server, live LLM calls, end-to-end test suite execution, Playwright E2E tests
