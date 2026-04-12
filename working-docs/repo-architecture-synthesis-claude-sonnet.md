# AgentLab Repo Audit — Architecture Synthesis
**Audit date:** 2026-04-12  
**Auditor:** Claude Sonnet 4.6  
**Branch:** audit/full-repo-understanding-claude-sonnet

---

## System Identity

AgentLab is a **closed-loop agent optimization platform**. Its core value proposition is the BUILD → EVAL → OPTIMIZE → REVIEW → DEPLOY cycle. It is a single-tenant, file/SQLite-backed Python application with a React frontend.

The system is architecturally mature in its core optimization loop but production-immature in its operational infrastructure (auth, multi-tenancy, secrets, HA).

---

## Major Subsystems and Responsibilities

```
┌──────────────────────────────────────────────────────────────────┐
│                        WEB CONSOLE                               │
│  React 19 + React Router + Zustand + React Query                │
│  79 pages, 80+ components, 223 API hooks                        │
│  Three streaming protocols: WebSocket / SSE / fetch-stream      │
└────────────────────────────┬─────────────────────────────────────┘
                             │ HTTP / WebSocket / SSE
┌────────────────────────────▼─────────────────────────────────────┐
│                       FASTAPI SERVER                             │
│  api/server.py — lifespan initializes ~40 stores/services        │
│  59 route modules, background TaskManager, /ws WebSocket        │
└──────┬──────────┬──────────┬──────────┬──────────┬──────────────┘
       │          │          │          │          │
  ┌────▼────┐ ┌──▼──────┐ ┌─▼──────┐ ┌─▼──────┐ ┌▼──────────┐
  │BUILDER  │ │OPTIMIZER│ │ EVAL   │ │OBSERVER│ │ DEPLOYER  │
  │HARNESS  │ │  LOOP   │ │RUNNER  │ │        │ │           │
  └────┬────┘ └──┬──────┘ └─┬──────┘ └─┬──────┘ └─┬─────────┘
       │         │           │           │           │
  ┌────▼──────────▼───────────▼───────────▼───────────▼─────────┐
  │                     PERSISTENCE LAYER                        │
  │  15+ SQLite databases + JSON files + filesystem configs       │
  └──────────────────────────────────────────────────────────────┘
```

---

## Subsystem Interplay

### 1. Builder Harness → Workbench Service → API SSE → Frontend

The builder stack converts a natural-language brief into a structured agent configuration.

```
User submits brief
  → POST /api/workbench/build/stream
  → WorkbenchService.run_build_stream()
    → Creates/loads WorkbenchProject (WorkbenchStore JSON)
    → Constructs BuildRequest
    → LiveWorkbenchBuilderAgent.run() [or MockWorkbenchBuilderAgent on failure]
      → HarnessExecutionEngine.run()
        Phase 1: Plan  → _build_plan_tree()      → plan.ready event
        Phase 2: Execute → walk_leaves()
          Per leaf:
            → _generate_step()                   → artifact.updated event
            → _apply_operation_lightweight()       modifies working_model
            → _persist_checkpoint()               writes to project.harness_state.checkpoints[]
        Phase 3: Reflect → _reflect_on_group()   → reflection.completed event
        Phase 4: Present → metrics.finish()       → build.completed event
  → WorkbenchService._process_agent_events()
    → Applies operations to working_model
    → Accumulates artifacts
    → Persists project (WorkbenchStore)
  → FastAPI StreamingResponse → SSE to browser
  → Zustand workbenchStore.dispatchEvent()
    → Plan tree renders in ConversationFeed
    → Artifacts render in ArtifactViewer
```

**Key architectural property:** The harness is deterministic template-first with optional LLM enhancement. If the LLM router fails, `MockWorkbenchBuilderAgent` provides a coherent stream — the UI always receives complete events.

---

### 2. Optimizer Loop → Eval → Gate → Deploy

The core optimization cycle:

```
POST /api/optimize/run
  → Background task via TaskManager
  → Optimizer.run()
    1. OBSERVE:
       - Observer.collect() → HealthReport (failure buckets, scores, latency)
       - OpportunityQueue.get_top_opportunities() → ranked failure clusters
    
    2. PROPOSE (strategy-dependent):
       SIMPLE:
         → Proposer.propose(health, failures) → Proposal (1 candidate)
       ADAPTIVE/FULL:
         → HybridSearchOrchestrator.generate_and_evaluate_candidates()
           - HybridBanditSelector selects operator family (Thompson/UCB)
           - SearchEngine generates N candidates from opportunities + registry
           - EvalRunner evaluates each candidate
           - ConstrainedParetoArchive filters dominated candidates
    
    3. VALIDATE:
       → validate_config(candidate) → AgentConfig schema check
    
    4. EVALUATE:
       → EvalRunner.run(candidate_config) → DimensionScores (11 dimensions)
       → paired_significance(baseline_scores, candidate_scores) → p-value
    
    5. GATE:
       → check_constraints() (hard: safety, regression)
       → AntiGoodhartGuard.check() (holdout regression, judge variance, drift)
    
    6. ACCEPT or REJECT:
       → OptimizationMemory.log(attempt) → optimizer_memory.db
       → ExperimentStore.create(card) → experiments.db
       → OperatorPerformanceTracker.record_outcome() → operator_performance.db
       If accepted + auto-deploy:
         → Deployer.deploy(new_config) → ConfigVersionManager
```

**Key architectural property:** The optimizer loop is fully decoupled from the builder. It reads the current config from `ConfigVersionManager`, generates mutations, evaluates them via `EvalRunner`, and deploys via `Deployer`. The builder produces the initial config; the optimizer iterates on it.

---

### 3. Observer / Evidence Pipeline

The observer stack is responsible for collecting runtime evidence and translating it into actionable optimization signals.

```
Execution traces
  → TraceCollector.record_*() → TraceStore (traces.db)
  → TraceGrader.grade_trace() → SpanGrade (7 graders: routing, tool_selection, 
                                 tool_argument, retrieval_quality, handoff_quality,
                                 memory_use, final_outcome)
  → BlameMap.compute() → BlameCluster[] (grader_name, agent_path, failure_reason)
  
Failure analysis
  → HealthReport (per-cycle failure buckets)
  → FailureClusterer.cluster() → OptimizationOpportunity[]
    → Severity: 0-1, Prevalence, Recency, Business impact
    → Priority score: severity×0.3 + prevalence×0.3 + recency×0.2 + business_impact×0.2
    → Recommended operator families via _BUCKET_TO_OPERATORS map
  → OpportunityQueue persists → opportunities.db

Business outcomes
  → OutcomeStore.log() → outcomes.db
  → OutcomeJoin links trace_id → outcome (lazy join)
```

**Key gap:** BlameMap clusters (grader_name, agent_path, failure_reason) are not consumed by the optimizer's opportunity mapping. The two taxonomies (grader names vs failure families) are independent. This means trace grading results don't feed directly back into operator selection.

---

### 4. Eval Engine Architecture

```
EvalRunner
  ├── Loads TestCase[] from YAML/CSV or EvalSetManager
  ├── Runs agent_fn against each case
  ├── Applies CompositeScorer (11 dimensions):
  │   task_success_rate, response_quality, safety_compliance,
  │   latency_p50/p95/p99, token_cost, tool_correctness,
  │   routing_accuracy, handoff_fidelity, user_satisfaction_proxy
  ├── Caches results by (config_hash, case_hash) → eval_cache.db
  ├── Persists results → eval_results.db
  └── Returns EvalResult with DimensionScores

Anti-Goodhart Protection:
  ├── Fixed holdout: unchanging test set (regression guard)
  ├── Rolling holdout: rotating set (distribution shift guard)
  ├── Judge variance: LLM scorer consistency monitoring
  └── Drift detection: baseline re-anchoring when environment shifts
```

---

### 5. State Flow Across the System

| State type | Location | Lifetime | Shared? |
|-----------|----------|----------|---------|
| Active agent config | `configs/vNNN.yaml` + manifest | Until replaced | CLI + API |
| Canary config | `CanaryManager` (memory) | Until restart | API only |
| Eval results | `eval_results.db` | Durable | CLI + API |
| Eval task status | `TaskManager` (memory) | Until restart | API only |
| Optimization memory | `optimizer_memory.db` | Durable | CLI + API |
| Experiment records | `experiments.db` | Durable | CLI + API |
| Optimizer proposals | `PendingReviewStore` (file) | Until reviewed/expired | API only |
| Intelligence proposals | `ChangeCardStore` (SQLite) | Durable | API only |
| Traces | `traces.db` | Durable | CLI + API |
| Opportunities | `opportunities.db` | Durable | CLI + API |
| Builder sessions | `BuilderChatService._sessions` | Until restart | API only |
| Workbench projects | `workbench.json` | Durable | API only |
| Builder events | `builder_events.db` | Durable | API only |

**Key pattern:** Most long-term operational state (results, memory, traces, experiments) is durably persisted to SQLite. Most live operational state (tasks, canary metrics, chat sessions) is in-memory and ephemeral across restarts.

---

### 6. Event System Architecture

Three distinct event systems coexist:

**EventBroker** (builder/events.py)
- In-memory deque (maxlen=2000) for live SSE + SQLite for durability
- 11 event types: task lifecycle + content events
- Bridges to `EventLog` on lifecycle events

**EventLog** (data/event_log.py)
- System-wide append-only audit trail
- 26 standardized event types across all subsystems
- Indexed by type, timestamp, session_id, cycle_id

**WebSocket** (api/server.py `/ws`)
- `ConnectionManager` broadcasts to all connected clients
- Used for short event types: `eval_complete`, `loop_status_update`, `optimize_complete`, `optimize_pending_review`

**EventSource/SSE** (builder and workbench routes)
- Per-stream, per-request connection
- Full harness event sequence

**Key gap:** These three event systems are not unified. A consumer who wants to watch the full lifecycle of a build-then-eval-then-optimize cycle must subscribe to multiple channels. There is no single event bus.

---

### 7. Skill Architecture

Two distinct skill systems coexist without clear unification:

**Core Skills** (`core/skills/`, `stores/skill_store_config.py`)
- `SkillKind.BUILD` — optimization strategies (mutation operators, eval criteria)
- `SkillKind.RUNTIME` — agent capabilities (tools, instructions, policies)
- Stored in `.agentlab/skills.db` (canonical path, shared between CLI and API)
- Loaded at harness startup as context; reported in `skill_context` of build events
- Build-time skills inform the harness but are applied by the optimizer, not the harness

**Registry Skills** (`registry/`, `registry/skill_store.py`)
- `ExecutableSkillStore` — skills with versioning, CRUD, diff, bulk import
- Serves `/api/registry/`, `/api/skills/` endpoints
- Skills, policies, tool_contracts, handoff_schemas

**Practical gap:** The two systems are architecturally separate and have different purpose. Core skills provide context to the harness and optimizer. Registry skills are a management API for operators. The connection between "available registry skills" and "optimizer selects which operators to apply" is not formally wired.

---

### 8. Config Versioning and Deployment

```
AgentConfig (schema in agent/config/schema.py)
  Fields: routing, prompts, tools, thresholds, context_caching,
          compaction, memory_policy, model, quality_boost,
          optimizer_settings
  
ConfigVersionManager (deployer/versioning.py)
  ├── configs/manifest.json — tracks active_version, canary_version, all versions
  ├── configs/vNNN.yaml — immutable version snapshots
  ├── Versioning: sequential v001, v002, ...
  ├── State: active | canary | retired | rolled_back
  └── Content hash: SHA256 for deduplication

CanaryManager (deployer/canary.py)
  ├── 10% traffic to canary (conceptual — no actual traffic splitting)
  ├── Requires 10 minimum conversations to decide
  ├── Promotes if canary ≥ 95% of baseline quality
  ├── Rolls back if quality drops below threshold
  └── 1-hour max canary duration
```

**Important note on canary:** The canary is conceptual — the system tracks which config version is "canary" and collects metrics, but there is no actual infrastructure-level traffic splitting. The canary designation is semantic; real traffic routing would require integration with an actual API gateway or routing layer.

---

### 9. Mutation Surface Coverage

The optimizer can only mutate surfaces that exist in the canonical `AgentConfig` schema.

| Surface | Status | Notes |
|---------|--------|-------|
| Instructions/prompts | Full | Core to all optimizer paths |
| Routing rules | Full | In AgentConfig, live in all paths |
| Tool descriptions | Partial | Only descriptions, not full tool config |
| Model selection | Partial | High-risk, not in simple proposer |
| Generation settings | Partial | Naming inconsistency across codebase |
| Context caching | Partial | In AgentConfig, not in ADK export |
| Memory policy | Partial | In AgentConfig, no opportunity generation |
| Few-shot examples | Nominal | Operator exists, not in AgentConfig schema |
| Callbacks | Nominal | Operator exists, not in schema |
| Policies/guardrails | Nominal | Operators exist, not in schema |
| Tool contracts | Nominal | Operator exists, no canonical support |
| Handoff schemas | Nominal | Operators exist, not in schema |
| Workflow/topology | Nominal | Experimental, `supports_autodeploy=False` |
| Skills | Nominal | Engine exists, not optimized as first-class |

**Key insight:** 2 surfaces fully covered, 6 partial, 6 nominal. The optimizer is strongest where `AgentConfig`, `MutationRegistry`, `Proposer`, and `EvalRunner` all align — which is the instructions/routing core.

---

### 10. LLM Provider Architecture

```
LLMRouter (optimizer/llm_router.py)
  ├── Auto-detects available providers from env vars
  ├── Falls back to mock if no keys found
  ├── Configured via agentlab.yaml models list
  ├── Three providers: OpenAI (gpt-4o), Anthropic (claude-sonnet-4-5), Google (gemini-2.5-pro)
  └── Retry: max 3 attempts, 0.5-8s backoff with jitter

MockProvider
  ├── Deterministic responses (no randomness, no API calls)
  ├── Default when no API keys present
  └── Hardwired in _optimize_pro() — bypasses real provider even when live
```

---

### 11. Multi-Agent Architecture

The system supports multi-agent topologies in its data model but not comprehensively in its optimization loop.

**Data model support:**
- `AgentNode` (router, specialist, guardrail, skill, memory, etc.)
- `AgentEdge` (routes_to, delegates_to, guards, uses_tool, etc.)
- `AgentGraphVersion` — immutable graph IR with content hash

**Optimizer support:**
- Opportunities can target specific `agent_path` segments
- Blame clusters include `agent_path` in their key
- Mutation operators work on flat `AgentConfig`, not graph-structured configs

**Gap:** The typed graph IR (`AgentNode/AgentEdge`) is defined but not the canonical mutation target. Optimization operates on flat AgentConfig dicts, not on the graph. Multi-agent topology optimization operators exist but are marked experimental and `supports_autodeploy=False`.

---

### 12. MCP Server Integration

```
mcp_server/server.py
  ├── 22 tool definitions + 5 prompts + 3 resource types
  ├── Tools: agentlab_status, agentlab_eval_run, agentlab_optimize, 
  │          agentlab_edit, agentlab_suggest_fix, agentlab_registry_*,
  │          agentlab_deploy_*, agentlab_config_*, agentlab_trace_*,
  │          agentlab_context_*, agentlab_adk_*, agentlab_skill_*
  ├── Prompts: optimize, debug, review_changes, generate_eval, health_check
  ├── Resources: config//{version_id}, trace//{trace_id}, eval//{run_id}
  └── Communicates with AgentLab API on localhost:8000
```

The MCP server exposes AgentLab to coding agents (Claude Code, Codex, Cursor). Read operations are strong; write operations are limited to `agentlab_edit` (NL surface) and `agentlab_suggest_fix` (heuristic proposals). There is no typed patch bundle contract for external agents to submit structured config mutations.

---

### 13. Architecture Tensions

**Tension 1: Single-workspace design vs multi-agent management**
The server is initialized against one workspace directory (CWD at startup). Connect/Import creates new workspace directories. The running server is unaware of imported workspaces. This tension is visible in every import-then-use journey.

**Tension 2: Rich data model vs flat config**
`AgentGraphVersion` and `AgentNode/AgentEdge` are rich graph models. `AgentConfig` is a flat dict. Optimization operates on the flat schema. The graph model is defined but not the optimization target.

**Tension 3: Multiple event systems**
EventBroker (builder), EventLog (system), WebSocket (UI) are three separate systems. They serve different consumers but have overlapping concerns (lifecycle events are bridged from EventBroker to EventLog, but the WebSocket isn't bridged). Consuming the full system lifecycle requires subscribing to all three.

**Tension 4: Two review queues**
`PendingReviewStore` (optimizer proposals) and `ChangeCardStore` (intelligence proposals) serve the same operator role but use different storage, different API routes, and different UI surfaces. Unifying them would require a significant refactor.

**Tension 5: Claimed vs live mutation surfaces**
The `MutationRegistry` declares ~14 surfaces. The `AgentConfig` schema supports ~10. The optimizer actively produces mutations for ~4-9 (strategy-dependent). The surface inventory doc (`OPTIMIZATION_COMPONENTS_AUDIT.md`) is an honest self-assessment of this gap, but docs-facing materials (feature docs) describe the full declared set without noting the limitations.

---

### 14. Reliability Infrastructure

`optimizer/reliability.py` provides:
- `LoopCheckpointStore` — JSON checkpoint after each cycle
- `DeadLetterQueue` — failed cycles stored to SQLite
- `LoopWatchdog` — detects stale tasks (>30 min), marks FAILED
- `ResourceMonitor` — warns at >2GB RAM, >90% CPU
- `GracefulShutdown` — SIGTERM handler flushes checkpoint before exit

These are well-implemented and production-appropriate. The gap is that they operate at the optimization loop level; the API server itself has no equivalent graceful shutdown for in-flight HTTP requests.

---

### 15. Operational Mode System

Three modes: `mock` / `live` / `auto`

| Mode | LLM calls | Agent execution | Use case |
|------|-----------|-----------------|---------|
| mock | Deterministic fake | Template-based | Dev, demo, testing |
| live | Real provider APIs | Real or mock | Production |
| auto | Auto-detect | Real if keys present | Default safe start |

Mode is determined at server startup by `_resolve_runtime_use_mock()` in `cli/bootstrap.py`. The health endpoint reports `mock_mode: bool`. Mock mode is appropriate for development but the degradation to mock is **not prominently surfaced** in the UI — the MockModeBanner component exists but is conditional on the health check response.

---

## Summary: Architecture Strengths and Risks

### Strengths
1. **Well-defined builder contract:** `BUILDER_CONTRACT.md` is a precise behavioral spec, and the implementation closely matches it. Events, phases, checkpoints, fallbacks — all correctly implemented.
2. **Rich eval infrastructure:** 11-dimension scoring, anti-Goodhart protection, statistical significance testing, judge calibration — a serious eval stack.
3. **Layered persistence:** Most important operational state is durably persisted to SQLite. Not great for scale, but reliable for single-tenant use.
4. **Mock-first development:** The entire system runs without API keys, making dev/demo/testing straightforward.
5. **Reliability primitives:** Checkpoints, dead letters, watchdog, graceful shutdown are all present and functional.
6. **Comprehensive MCP surface:** 22 tools exposing the full platform to coding agents.

### Risks
1. **SQLite only:** No multi-instance support. Not suitable for cloud-native horizontal scaling.
2. **No auth/RBAC in production:** `auth.py`, `rbac.py`, `multi_tenant.py` exist as stubs but are not integrated.
3. **Server CWD dependency:** Invisible to UI users; many journeys fail silently if CWD is wrong.
4. **Ephemeral state:** Task status, canary metrics, builder sessions are in-memory. Server restarts break active operations.
5. **Surface coverage gap:** The optimizer can only mutate a subset of the surfaces it declares. Docs overstate reach.
6. **No unified event bus:** Three separate event systems require consumers to subscribe to multiple channels for complete lifecycle visibility.
7. **Pro mode unusable:** `SearchStrategy.PRO` (MIPROv2/GEPA/SIMBA) is unreachable from config file or UI; `_optimize_pro()` hardwires `MockProvider`.
