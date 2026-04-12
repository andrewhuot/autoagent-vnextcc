# AgentLab: Product & Codebase Recommendations

**Date:** 2026-04-12  
**Author:** Claude Opus (architect subagent)  
**Scope:** Full-repo audit synthesis — product, architecture, and roadmap guidance  
**Audience:** Senior engineer / PM building the roadmap

---

## 1. Executive Framing

AgentLab has an ambitious and architecturally sophisticated core: the BUILD-EVAL-OPTIMIZE-REVIEW-DEPLOY loop is well-specified, the eval infrastructure (11-dimension scoring, anti-Goodhart protection, statistical significance testing) is production-grade, and the builder harness faithfully implements its contract. The system demonstrates real engineering depth, not just breadth.

However, the product has a **trust gap**: several documented features (pro mode optimization, AutoFix eval/canary stages, drift-triggered promotion pauses, aggregate context reports) are stubs or unreachable code paths that users will discover are inert. Simultaneously, the system has a **coherence gap**: two review queues, three event systems, three streaming protocols, and 15+ SQLite databases fragment the operator experience into disconnected surfaces.

The highest-leverage work is not building new features. It is (1) closing the trust gap by either making documented features work or removing them from docs/UI, and (2) closing the coherence gap by unifying the review surface and the event model. These two actions would transform AgentLab from "impressive demo, surprising in production" to "reliable platform you can trust with your agent pipeline."

---

## 2. P0: Critical Fixes (Trust Damage)

These are things users can reach through documented paths that either silently fail, produce incorrect output, or break trust in the platform's integrity. Each one should be triaged as "fix or remove from docs/UI."

### 2.1 Pro Mode Optimization is Unreachable

**Problem:** `search_strategy: pro` is rejected by Pydantic validation (`OptimizerRuntimeConfig` allows only `simple|adaptive|full`). Even if the enum were extended, `_optimize_pro()` hardwires `MockProvider`. MIPROv2, GEPA, SIMBA, BootstrapFewShot are implemented but dead.

**Impact:** Users who read docs and set `search_strategy: pro` get a validation crash. Users who select "research" mode in UI expecting advanced algorithms get `SearchStrategy.FULL` (hybrid search), not the documented prompt optimization algorithms.

**Fix (quick, 2-3 days):**
1. Add `"pro"` to the `Literal` type in `agent/config/runtime.py:63`.
2. Map `research` mode to `SearchStrategy.PRO` in `ModeRouter._MODE_STRATEGY_MAP` (or add a fourth "pro" mode to the UI).
3. Remove the `MockProvider` hardwiring in `_optimize_pro()` and wire through the real `LLMRouter`.
4. Add integration test that runs one cycle with `search_strategy: pro` against a mock LLM.

**Alternative (even quicker, 1 day):** Remove all references to "pro" from docs, CHANGELOG, and platform-overview.md. Mark algorithms as internal/experimental. This is honest but leaves value on the table.

**Files:** `agent/config/runtime.py`, `optimizer/loop.py` (`_optimize_pro`), `optimizer/mode_router.py`

---

### 2.2 `search_strategy` in agentlab.yaml is Silently Ignored

**Problem:** The config file setting for `search_strategy` is parsed by `OptimizerRuntimeConfig` but never passed to the `Optimizer` constructor at `api/server.py:245-260`. The optimizer always starts as `SearchStrategy.SIMPLE`.

**Impact:** Any user following documentation to set strategy via config file (the expected path for CI/CD pipelines and persistent configuration) gets no effect. Only the UI mode selector works.

**Fix (quick, 1 day):**
Pass `runtime_config.search_strategy` to the `Optimizer` constructor in `api/server.py`. Add a startup log line confirming active strategy.

**Files:** `api/server.py` (lines 245-260), `optimizer/loop.py` (constructor)

---

### 2.3 AutoFix Pipeline is 4/6 Stages

**Problem:** Documentation describes 6 stages: failure analysis, constrained proposals, human review, apply, eval, canary deploy. `apply()` is a pure config mutation. No eval, no gate check, no canary. `canary_verdict` and `deploy_message` fields always return empty strings.

**Impact:** An operator who trusts AutoFix to validate proposals before deploy gets no validation. This is a safety hole disguised as a safety feature.

**Fix (structural, 1-2 weeks):**
1. After `apply()`, trigger an eval run (reuse existing `EvalRunner.run()` path).
2. Gate check: if eval score drops below baseline - threshold, reject the mutation.
3. If accepted, feed into the existing `Deployer.deploy()` canary path.
4. Populate `canary_verdict` and `deploy_message` from the canary result.

**Intermediate fix (quick, 2 days):**
Update docs to say "AutoFix proposes and applies mutations. Eval and canary are manual steps after apply." Remove the fields from the API response or mark them `deprecated`. This is honest and removes the trust gap.

**Files:** `optimizer/autofix.py` (method `apply()`), `api/routes/autofix.py:125-126`

---

### 2.4 Drift Monitor is Not Wired

**Problem:** `DriftMonitor()` constructed with no args (ignoring `drift_threshold: 0.12` from config). Called with `verdicts=[]` so never fires. "Pause auto-promotion on drift" is not implemented.

**Impact:** Users who configure drift thresholds in `agentlab.yaml` are getting zero protection. The judge-ops page shows drift information, but none of the declared behavioral consequences exist.

**Fix (quick, 2-3 days):**
1. Pass `drift_threshold` from `agentlab.yaml` to `DriftMonitor` constructor in `api/server.py:391`.
2. In the drift check endpoint, pass actual verdicts from the eval results store, not `[]`.
3. Wire a `DriftAlert` to the promotion gate in `optimizer/gates.py` — reject proposals when drift exceeds threshold.
4. Either implement SSE emission or remove it from docs.

**Files:** `api/server.py:391`, `judges/drift_monitor.py`, `optimizer/gates.py`

---

### 2.5 Context Aggregate Report is a Stub

**Problem:** `/api/context/report` returns all zeros. CLI `context report` prints a static string.

**Impact:** Low compared to the above (per-trace analysis works), but documented as real. Creates confusion about what the context workbench can do.

**Fix (quick, 3-5 days):**
Aggregate per-trace analysis results from `ContextAnalyzer` across all stored traces. Compute means for utilization, compaction loss, etc. Populate the endpoint. Or: remove from docs/UI and surface a "run per-trace analysis" CTA instead.

**Files:** `api/routes/context.py:86-98`, `context/analyzer.py`

---

### 2.6 Server CWD Dependency is Invisible

**Problem:** Build save, optimize, and deploy all depend on the server process CWD being an AgentLab workspace. If it isn't, users get a 400 error with no recovery path in the UI.

**Impact:** Every new user who runs `agentlab serve` from the wrong directory hits a wall with no explanation. This is the #1 first-run failure mode.

**Fix (quick, 2-3 days):**
1. At server startup, validate CWD is a workspace. If not, log a clear error and either refuse to start or start in read-only mode.
2. Add a health check field: `workspace_valid: bool` with the path.
3. In the UI, if `workspace_valid` is false, show a blocking banner with the path and instructions.
4. Long-term: accept `--workspace /path` as a CLI arg to decouple from CWD.

**Files:** `api/server.py` (startup), `api/routes/health.py`, frontend health display

---

## 3. P1: High-Impact Product Improvements

These are not trust violations but meaningfully incomplete user journeys that reduce the product's value.

### 3.1 Unify the Two Review Queues

**Problem:** `PendingReviewStore` (optimizer proposals, Optimize page) and `ChangeCardStore` (intelligence proposals, Improvements page) are completely separate stores, APIs, and UI surfaces.

**Impact:** An operator must check two pages to see all pending decisions. This splits attention and creates a governance blind spot.

**Fix (structural, 1-2 weeks):**
1. Create a unified `ReviewQueue` abstraction that wraps both stores.
2. Add `GET /api/reviews/all` that returns items from both stores with a `source` discriminator.
3. Build a unified "Review" page (or tab on Dashboard) that shows all pending items.
4. Preserve the existing per-store APIs for backwards compatibility.

**Files:** `optimizer/pending_review_store.py` (or wherever `PendingReviewStore` lives), `api/routes/changes.py` (ChangeCardStore routes)

---

### 3.2 Add "Promote Canary" to the Deploy Page

**Problem:** The Deploy page has canary start and rollback but not promotion. The final step of the deployment workflow requires CLI.

**Impact:** Teams running entirely in the web console cannot complete a canary deployment without switching to terminal.

**Fix (quick, 2 days):**
1. Add a "Promote" button next to "Rollback" in the Deploy page.
2. Wire to `POST /api/deploy/promote` (verify this endpoint exists; if not, add it).
3. Show promotion only when a canary is active.

**Files:** `web/src/pages/Deploy.tsx`, `api/routes/deploy.py`

---

### 3.3 Persist TaskManager State Across Restarts

**Problem:** `TaskManager` is in-memory. Eval runs and optimization tasks vanish after restart. Users see empty state on EvalRuns page.

**Impact:** Any server restart (crash, deploy, dev iteration) wipes the task list. Results are durably stored but not discoverable from the expected page.

**Fix (structural, 3-5 days):**
1. Add a `tasks.db` SQLite store for task metadata (id, type, status, timestamps, result_ref).
2. On startup, load incomplete tasks and mark them as `interrupted` (not `running`).
3. `EvalRuns` page should combine TaskManager live tasks with historical results from `eval_results.db`.
4. Consider making `ResultsExplorer` the primary results surface and deprecating the task-only view.

**Files:** `api/tasks.py`, `web/src/pages/EvalRuns.tsx`

---

### 3.4 Persist Builder Chat Sessions

**Problem:** `BuilderChatService._sessions` is an in-memory dict. Sessions lost on restart.

**Impact:** Users in the middle of iterative build conversations lose all context on server restart.

**Fix (quick, 3-5 days):**
1. Persist sessions to SQLite (builder already has `BuilderStore` with SQLite — add a sessions table).
2. On startup, reload active sessions.
3. Add a session list endpoint so the UI can show recent sessions.

**Files:** `builder/chat_service.py`, `builder/store.py`

---

### 3.5 Connect Import Should Register with Running Server

**Problem:** Importing an agent via Connect/ADK/CX creates a workspace directory that the running server does not track. Linked pages show nothing until restart.

**Impact:** Import completes "successfully" but the linked result pages are empty. User thinks import failed.

**Fix (structural, 3-5 days):**
1. After import, call `ConfigVersionManager.reload()` or `add_workspace()` to incorporate the new config.
2. Alternatively, make the server's workspace scope dynamic (list of tracked paths, not one CWD).
3. At minimum: after import, the result panel should show "Restart server to load this agent" if live registration isn't possible.

**Files:** `adapters/workspace_builder.py`, `deployer/versioning.py` (`ConfigVersionManager`), `api/routes/connect.py`

---

### 3.6 Wire BlameMap into the Optimizer

**Problem:** Blame clusters are computed and visualized but never consumed by the optimizer's FailureClusterer. Two separate taxonomies exist with no bridge.

**Impact:** The system's most detailed failure analysis (per-grader, per-agent-path blame) doesn't improve the optimization loop. The optimizer re-derives a coarser taxonomy independently.

**Fix (structural, 1-2 weeks):**
1. Add a bridge in `observer/opportunities.py` that maps `BlameCluster.grader_name` to the optimizer's failure family taxonomy.
2. Feed blame cluster severity/prevalence directly into `OptimizationOpportunity` scoring.
3. Use `agent_path` from blame clusters to target mutations at specific agent nodes (particularly valuable for multi-agent configs).

**Files:** `observer/blame_map.py`, `observer/opportunities.py`, `optimizer/mutations.py`

---

## 4. P2: Architecture / Codebase Improvements

These are structural improvements to maintainability, reliability, and future scale.

### 4.1 Split runner.py (445KB Single-File CLI)

**Problem:** The entire CLI is one Python file. This is unmaintainable: impossible to navigate, impossible to test in isolation, impossible to assign to different developers.

**Fix (structural, 1-2 weeks):**
1. Create `cli/` subpackage with one module per command group (eval, optimize, deploy, build, registry, connect, cx, adk, etc.).
2. Use Click's `@group.command()` pattern to compose from separate files.
3. Keep `runner.py` as a thin entrypoint that imports and assembles groups.
4. This can be done incrementally: move one command group per PR.

**Priority rationale:** This is blocking parallel development. Any PR that touches CLI will conflict with any other CLI PR.

---

### 4.2 Split api.ts (105KB, 223+ Hooks)

**Problem:** Frontend API layer is a single file. Same issues as runner.py — merge conflicts, impossible to navigate, no domain boundaries.

**Fix (structural, 1 week):**
1. Create `lib/api/` directory with domain modules: `eval.ts`, `optimize.ts`, `deploy.ts`, `builder.ts`, `registry.ts`, etc.
2. Re-export from `lib/api/index.ts` for backwards compatibility.
3. Each module owns its types, queries, and mutations for one domain.

---

### 4.3 Consolidate SQLite Databases

**Problem:** 15+ separate SQLite databases. Fragmented backup, fragmented migration, fragmented connection management.

**Fix (structural, 2-3 weeks, can be phased):**

Phase 1 (quick): Add a `backup` CLI command that snapshots all databases atomically.

Phase 2 (medium): Merge databases that serve the same subsystem:
- `eval_results.db` + `eval_cache.db` + `datasets.db` -> `eval.db`
- `traces.db` + `knowledge.db` + `opportunities.db` -> `observer.db`
- `optimizer_memory.db` + `experiments.db` + `cost_tracker.db` -> `optimizer.db`
- `builder_events.db` + `skills.db` -> `builder.db`
- `event_log.db` + `outcomes.db` -> `platform.db`

Phase 3 (long-term): If multi-instance is needed, add a PostgreSQL adapter behind a repository interface. The current single-tenant SQLite design is fine for local/single-instance use.

---

### 4.4 Unify Event Systems

**Problem:** `EventBroker` (builder, in-memory deque), `EventLog` (system, SQLite), and WebSocket broadcasts are disconnected. No single event bus.

**Fix (structural, 2-3 weeks):**
1. Make `EventLog` the single durable store for all events (it's already SQLite-backed).
2. `EventBroker` becomes a live window over `EventLog` — reads recent events from DB, holds latest in memory for SSE.
3. WebSocket broadcasts become consumers of `EventLog` writes (trigger on insert).
4. All event types get a unified schema: `{id, type, source, session_id, timestamp, payload}`.

**Benefit:** Single query API for "what happened in this session" across build/eval/optimize/deploy.

---

### 4.5 Delete Dead Code and Stubs

**Problem:** Backup files (`ChangeReview.tsx.backup`, `EvalRuns.tsx.backup`), stub routes (`auth.py`, `rbac.py`, `billing.py`, `metering.py`, `sla.py`, `multi_tenant.py`), dead code (`score_handoff()`, `algorithm_overrides` dict).

**Fix (quick, 1 day):**
1. Delete backup files.
2. Move stub routes to a `_future/` directory or delete with a comment in README about planned features.
3. Either wire `score_handoff()` into `analyze_trace()` or delete it.
4. Either read `algorithm_overrides` in the optimizer loop or remove it from `ModeRouter`.

**Rationale:** Dead code erodes trust in the codebase. Developers waste time reading code that doesn't execute. Stubs that look like real routes confuse auditors and new team members.

---

### 4.6 Add Tests for Untested Modules

**Problem:** `a2a/` (0 tests), `multi_agent/` (0 tests), `logger/` (0 tests).

**Fix (structural, 1-2 weeks):**
1. Prioritize `multi_agent/` — if this is meant to be a core feature (multi-agent graph optimization), it needs test coverage before further development.
2. `a2a/` is a protocol implementation — test the handler/discovery contract against the A2A spec.
3. `logger/` is lower priority but should have basic middleware coverage.

---

### 4.7 Standardize Streaming Protocols

**Problem:** Three streaming protocols coexist — WebSocket (global events), SSE (builder/workbench), fetch-stream (workbench). Different reconnection semantics, different error handling, different client code.

**Fix (structural, 2-3 weeks):**
1. Converge on SSE for all real-time streams (it's HTTP-native, works through proxies, auto-reconnects).
2. Keep WebSocket only for bidirectional needs (if any exist — currently all broadcasts are server-to-client).
3. Eliminate fetch-stream in favor of EventSource.
4. Provide a single `useEventStream(channel)` React hook that handles reconnection, buffering, and dispatch.

---

## 5. P3: Product Expansion Opportunities

These are not fixes or improvements to existing features but areas where investment would meaningfully increase user value.

### 5.1 Multi-Agent Graph Optimization (Realize the IR)

The `AgentNode`/`AgentEdge` graph IR exists. Blame analysis uses `agent_path`. Topology mutation operators exist (marked experimental). But the optimizer loop operates on flat `AgentConfig`.

**Opportunity:** Make the graph IR the primary optimization target for multi-agent configs. This would differentiate AgentLab from any competitor: not just prompt optimization, but topology optimization (add/remove/reroute agents, change delegation patterns).

**Investment:** 3-4 weeks. Requires: graph-aware mutation operators, per-node eval scoring, topology-level gate checks.

---

### 5.2 MCP Typed Patch Bundle Contract

The MCP server exposes 22 tools to coding agents, but write operations are limited to `agentlab_edit` (natural language) and `agentlab_suggest_fix` (heuristic). There is no structured contract for an external agent to submit a config patch with provenance.

**Opportunity:** Define a `patch_bundle` schema (targeted mutations + rationale + eval evidence) that coding agents can submit through MCP. This turns every Claude Code / Codex session into a potential optimization contributor — the agent proposes a structured change, AgentLab evals it, human reviews it.

**Investment:** 1-2 weeks for the contract + MCP tool + review queue integration.

---

### 5.3 Workspace Init from Web UI

Currently `agentlab init` is CLI-only. This is the first thing a new user needs to do, and the web UI cannot help them.

**Opportunity:** Add `POST /api/workspace/init` that creates the directory structure. The Setup page becomes the complete onboarding surface — no terminal required for basic use.

**Investment:** 2-3 days. The `cli/workspace.py` logic already exists; expose it through the API.

---

### 5.4 Multi-Workspace Support

The server is locked to one CWD. Users with multiple agents (common) must run multiple server instances or restart between projects.

**Opportunity:** Add a workspace switcher. Server tracks a list of workspace paths. `ConfigVersionManager` scopes to the active workspace. UI shows a workspace selector in the header.

**Investment:** 1-2 weeks. Significant refactor of server initialization path.

---

### 5.5 Canary with Real Traffic Splitting

The current canary is semantic — no actual infrastructure-level traffic split. For teams deploying agents as APIs, this limits the canary to being a mental model rather than an operational tool.

**Opportunity:** Integrate with an API gateway (or provide a lightweight proxy) that routes X% of traffic to the canary config. Collect real production metrics, not just eval metrics.

**Investment:** 3-4 weeks. Requires significant new infrastructure (proxy, metrics collection, decision engine). Consider partnering with existing gateway solutions rather than building from scratch.

---

## 6. What to Stop Doing

### 6.1 Stop Documenting Features That Don't Work

The fastest way to restore trust is to align docs with reality. Right now, docs describe pro mode, AutoFix eval+canary, drift-triggered promotion pauses, and aggregate context reports as working features. They are not. Either implement them or remove them from docs. Half-implemented features documented as complete are worse than no feature at all.

### 6.2 Stop Adding New Stub Routes

`auth.py`, `rbac.py`, `billing.py`, `metering.py`, `sla.py`, `multi_tenant.py` are all stub files that ship in the codebase. They create the impression that these features are partially implemented. They are not. Move them to a `_roadmap/` directory or delete them. When the time comes to implement auth, start fresh from the actual requirements.

### 6.3 Stop Building New Surfaces Without Connecting Them

The pattern of "implement algorithm X, don't wire it into the loop" (MIPROv2, GEPA, SIMBA, `score_handoff()`, `algorithm_overrides`) creates technical debt that looks like features. Every new capability should have a clear integration path before implementation begins.

### 6.4 Stop Maintaining Backup Files in Version Control

`ChangeReview.tsx.backup`, `EvalRuns.tsx.backup` should not exist. That is what git history is for.

### 6.5 Reconsider the Three-Streaming-Protocol Approach

Adding a third streaming protocol (fetch-stream) on top of WebSocket and SSE increased client complexity without clear benefit. Standardize before adding more real-time surfaces.

---

## 7. Roadmap Priorities

If forced to sequence work into three phases:

### Phase 1: Trust Restoration (2-3 weeks)

**Goal:** Every documented feature either works or is removed from docs. Users can trust that what the platform claims, it delivers.

| Item | Effort | Impact |
|------|--------|--------|
| Fix `search_strategy` config passthrough | 1 day | Unblocks config-driven workflows |
| Wire pro mode OR remove from docs | 2-3 days | Eliminates validation crashes + false advertising |
| Fix drift monitor wiring | 2-3 days | Activates judge safety guardrail |
| Update AutoFix docs to match reality | 1 day | Honest product surface |
| Add workspace validation + banner at startup | 2-3 days | Eliminates #1 first-run failure |
| Delete backup files + stub routes | 1 day | Clean codebase signal |
| Fix context aggregate report OR remove | 3 days | Honest product surface |

**Exit criteria:** `agentlab doctor` reports all documented features as functional. No user path leads to a stub with no error message.

---

### Phase 2: Journey Coherence (3-4 weeks)

**Goal:** Core user journeys (build, eval, optimize, review, deploy) work end-to-end without gaps, restarts, or page-hopping.

| Item | Effort | Impact |
|------|--------|--------|
| Persist TaskManager to SQLite | 3-5 days | Eval/optimize history survives restarts |
| Persist builder chat sessions | 3-5 days | Build sessions survive restarts |
| Unify review queues | 1-2 weeks | Single operator decision surface |
| Add canary promote to Deploy page | 2 days | Complete deploy workflow in UI |
| Fix connect import registration | 3-5 days | Import workflow actually works end-to-end |
| Wire BlameMap into optimizer | 1-2 weeks | Closes the feedback loop |

**Exit criteria:** An operator can complete BUILD-EVAL-OPTIMIZE-REVIEW-DEPLOY entirely in the web UI without restarting the server or switching to CLI.

---

### Phase 3: Platform Maturity (4-6 weeks)

**Goal:** Codebase is maintainable for a growing team, and the platform's unique differentiators (graph optimization, MCP integration) are realized.

| Item | Effort | Impact |
|------|--------|--------|
| Split runner.py into CLI modules | 1-2 weeks | Unblocks parallel CLI development |
| Split api.ts into domain modules | 1 week | Unblocks parallel frontend development |
| Unify event systems | 2-3 weeks | Single observability surface |
| Consolidate SQLite databases | 2-3 weeks | Simplified ops, backup, migration |
| Standardize on SSE streaming | 2-3 weeks | Simplified client, better reliability |
| Multi-agent graph optimization MVP | 3-4 weeks | Major differentiator |
| MCP patch bundle contract | 1-2 weeks | Turns external agents into optimization contributors |
| Add tests for a2a/, multi_agent/ | 1-2 weeks | Safety net for core features |

**Exit criteria:** New developer can onboard in <1 day. Single `agentlab backup` command captures all state. Event log provides unified session history.

---

## Summary of Key Principles

1. **Trust before features.** A platform that claims less but delivers reliably is worth more than one that claims everything and delivers partially.

2. **Coherence before expansion.** Two review queues, three event systems, and three streaming protocols are symptoms of building breadth without integration. Consolidate before adding.

3. **Wire before implement.** The pattern of implementing algorithms/stores/endpoints without connecting them to the user-facing loop creates a codebase that is larger than its effective surface area. Every new capability should have a wiring plan before implementation.

4. **Persistence is not optional.** In-memory state (tasks, canary metrics, chat sessions) creates a fragile system where any restart degrades the user experience. The platform already has excellent SQLite infrastructure — use it consistently.

5. **Docs are product surface.** Documentation that describes features which don't work is worse than no documentation. Treat docs as part of the release: if the feature ships incomplete, the docs must reflect the actual state.
