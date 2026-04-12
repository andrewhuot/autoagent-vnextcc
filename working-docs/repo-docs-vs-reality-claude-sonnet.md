# AgentLab Repo Audit — Docs vs. Reality
**Audit date:** 2026-04-12  
**Auditor:** Claude Sonnet 4.6 (with docs-librarian subagent)  
**Branch:** audit/full-repo-understanding-claude-sonnet

---

## Methodology

This document compares documented promises (from README, feature docs, platform overview, architecture doc) against what the code actually does. Three categories are used:

- **Accurate** — doc matches code closely
- **Partial** — feature exists but is more limited than docs describe
- **Gap** — doc describes something that doesn't exist or is a stub

---

## 1. Prompt Optimization (Pro Mode)

**Source:** `docs/features/prompt-optimization.md`, CHANGELOG 2.5.0

**Doc claims:**
- Set `search_strategy: pro` in `agentlab.yaml` to activate MIPROv2, BootstrapFewShot, GEPA, SIMBA
- `research` optimizer mode uses these advanced algorithms

**Reality:**
- `OptimizerRuntimeConfig.search_strategy` is typed `Literal["simple", "adaptive", "full"]` at `agent/config/runtime.py:63`. The value `"pro"` is rejected by Pydantic validation — the config file cannot legally activate pro mode.
- `ModeRouter._MODE_STRATEGY_MAP` maps `research → SearchStrategy.FULL`, not `SearchStrategy.PRO`. A user selecting "research" mode gets Hybrid Search + curriculum + Pareto, not MIPROv2/GEPA/SIMBA.
- `_optimize_pro()` in `optimizer/loop.py` hardwires `MockProvider` — even if `SearchStrategy.PRO` were reachable, the algorithms would run against mock data, not real providers.
- The four algorithm classes (mipro.py, gepa.py, bootstrap_fewshot.py, simba.py) are implemented but unreachable from any documented user path.

**Classification: Gap — Pro mode algorithms are implemented but unreachable from config, UI, or documented API paths.**

---

## 2. AutoFix Copilot

**Source:** `docs/features/autofix.md`

**Doc claims:**
- AutoFix runs a 6-stage pipeline: failure analysis → constrained proposals → human review → apply → **eval** → **canary deploy**
- "The candidate must pass all gates (safety, regression) and show statistically significant improvement. Successful candidates are deployed via canary."

**Reality:**
- `AutoFixEngine.apply()` at `optimizer/autofix.py:301-326` applies the mutation operator to a config dict and returns the new config.
- No eval run is triggered by `apply()`.
- No gate checks are performed.
- No canary deployment follows.
- `canary_verdict` and `deploy_message` fields in the API response at `api/routes/autofix.py:125-126` are always empty strings.

**Classification: Gap — Stages 5 and 6 (eval + canary deploy) described in docs do not exist. AutoFix is a proposal-and-apply system, not an evaluated pipeline.**

---

## 3. Judge Ops — Drift Monitor

**Source:** `docs/features/judge-ops.md`

**Doc claims:**
- When drift exceeds `drift_threshold`, the system "optionally pauses auto-promotion of experiments scored by the drifting judge"
- "Emits an event via the SSE stream"
- `drift_threshold` and `max_judge_variance` from `agentlab.yaml` control behavior

**Reality:**
- `DriftMonitor()` is constructed in `api/server.py:391` with no arguments. The `drift_threshold: 0.12` from `agentlab.yaml` is not passed to the constructor. `DriftMonitor` uses a hardcoded threshold of `0.1` internally.
- `GET /api/judges/drift` calls `run_all_checks(verdicts=[])` — an empty list — so it will never produce alerts in practice.
- "Pause auto-promotion on drift" is not implemented anywhere in the codebase. No code path connects a `DriftAlert` to halting experiment promotion.
- SSE event emission on drift is not implemented.

**Classification: Gap — Drift monitor runs but uses hardcoded config, receives no real data, and the behavioral consequences (pause promotion, SSE event) are not implemented.**

---

## 4. Context Workbench — Aggregate Report

**Source:** `docs/features/context-workbench.md`

**Doc claims:**
- `GET /api/context/report` returns aggregate context health: utilization, failure correlation, handoff efficiency
- CLI example: `agentlab context report` outputs "Growth pattern: exponential (3 agents), Average utilization: 78%, Failure correlation: moderate (r=0.42)"

**Reality:**
- `api/routes/context.py:86-98` is a hardcoded stub returning all zeros: `{"utilization_ratio": 0.0, "compaction_loss": 0.0, "avg_handoff_fidelity": 0.0, "memory_staleness": 0.0, "status": "healthy", "recommendations": []}`
- CLI `context report` at `runner.py:6584` echoes a static string: "Run 'agentlab context analyze --trace <id>' for per-trace analysis." No computed output.

**What does work:** Per-trace analysis via `GET /api/context/analysis/{trace_id}` and `ContextAnalyzer.analyze_trace()` are real and functional. The compaction simulator is real. The gap is only the *aggregate* report surface.

**Classification: Gap — Aggregate report endpoint and CLI command are stubs. Per-trace analysis works.**

---

## 5. Context Workbench — Handoff Scoring

**Source:** `docs/features/context-workbench.md`

**Doc claims:**
- `ContextAnalyzer` computes "handoff scoring — how efficiently context is transferred between agents during handoffs"

**Reality:**
- `context/analyzer.py:263` has a `score_handoff()` method, but it is not called from `analyze_trace()`.
- `ContextAnalysis` dataclass has no `handoff_efficiency` field.
- `avg_handoff_fidelity` in the stub report endpoint is hardcoded to 0.0.

**Classification: Gap — Handoff scoring exists as dead code, not wired into the analysis pipeline.**

---

## 6. BlameMap → Optimizer Feedback Loop

**Source:** `docs/features/trace-grading.md`, platform-overview.md

**Doc claims:**
- BlameMap results "feed into the optimization loop: BlameMap identifies the highest-impact failure cluster, the optimizer generates a mutation targeting that cluster"

**Reality:**
- `BlameMap.compute()` is called by `GET /api/traces/blame` and the Blame Map frontend page.
- The optimizer's opportunity generation (`observer/opportunities.py`) uses its own `FailureClusterer` with a separate taxonomy (failure families: tool_error, routing_failure, etc.).
- Blame cluster `grader_name` and `agent_path` are never consumed by the optimizer's `FailureClusterer` or `_BUCKET_TO_OPERATORS` mapping.
- There is no code path connecting a `BlameCluster` to operator selection.

**Classification: Gap — Blame clusters are computed and visualized but don't feed back into the optimizer. The described feedback loop doesn't exist.**

---

## 7. Research Mode Algorithm Selection

**Source:** `docs/platform-overview.md`, mode documentation

**Doc claims:**
- `research` mode provides "full algorithm options" — MIPROv2, GEPA, SIMBA
- `algorithm_overrides` dict in `ResolvedStrategy` includes `enable_gepa: True`, `enable_simba: True` for research mode

**Reality:**
- `ModeRouter._MODE_STRATEGY_MAP` maps `research → SearchStrategy.FULL` (not `SearchStrategy.PRO`)
- `ResolvedStrategy.algorithm_overrides` is set with `enable_gepa: True`, `enable_simba: True` in `mode_router.py` but these keys are never read by the optimizer loop
- Research mode uses `HybridSearchOrchestrator` + `ConstrainedParetoArchive` — substantive, but not the declared advanced algorithms

**Classification: Partial — Research mode activates a real, sophisticated search strategy, just not the one documented. The algorithm_overrides dict is set but ignored.**

---

## 8. `search_strategy` in `agentlab.yaml`

**Source:** `docs/architecture.md` — "`agentlab.yaml` is the runtime control file" for optimizer settings

**Doc claims:**
- Setting `search_strategy: adaptive` or `search_strategy: full` in `agentlab.yaml` controls which search strategy the optimizer uses

**Reality:**
- `OptimizerRuntimeConfig` does parse `search_strategy` from `agentlab.yaml` correctly
- But in `api/server.py:245-260`, the `Optimizer` is initialized without passing `search_strategy` from the runtime config
- The `Optimizer` always starts as `SearchStrategy.SIMPLE` regardless of `agentlab.yaml`
- The UI mode selector in the Optimize page controls strategy correctly via API payload; the config file setting is silently ignored

**Classification: Gap — Config file setting for search_strategy has no effect at server startup. Only the UI mode selector works.**

---

## 9. Trace Grading System

**Source:** `docs/features/trace-grading.md`

**Doc claims:**
- 7 span-level graders: routing, tool_selection, tool_argument, retrieval_quality, handoff_quality, memory_use, final_outcome
- `TraceGrader` orchestrator with automatic applicability detection
- Blame Map feeds into the optimization loop

**Reality (accurate parts):**
- All 7 grader classes exist and are substantive
- `TraceGrader` orchestrator with `_GRADER_APPLICABILITY` map exists
- Blame Map computes correctly with impact scoring and trend detection
- API endpoints work: `GET /api/traces/blame`, `GET /api/traces/{id}/grades`

**Gaps (noted above):**
- BlameMap → optimizer feedback loop not implemented

**Classification: Partial — Trace grading is real and complete; the downstream connection to the optimizer is the gap.**

---

## 10. NL Scorer

**Source:** `docs/features/nl-scorer.md`

**Doc claims:**
- Create eval scorers from natural language descriptions
- List, show, refine (versioned), test against sample results
- CLI: `agentlab scorer create|list|show|refine|test`
- API: 5 endpoints under `/api/scorers/`

**Reality:**
- All 5 API endpoints exist and are wired
- `NLScorer` is initialized in `api/server.py`
- All CLI commands exist at `runner.py:8384-8493`
- Feature is well-implemented

**Classification: Accurate.**

---

## 11. Registry

**Source:** `docs/features/registry.md`

**Doc claims:**
- Full CRUD, versioning, diff, bulk import, search for 4 item types: skills, policies, tool_contracts, handoff_schemas
- CLI: `agentlab registry list|show|add|diff|import`
- API: 6 endpoints under `/api/registry/`

**Reality:**
- All endpoints real and functional
- CLI commands exist and work
- Diff, versioning, deprecation all implemented

**Minor naming drift:** Doc says CLI uses `tools` for `tool_contracts` and `handoffs` for `handoff_schemas`. CLI aliases translate correctly; direct API callers need internal names. Not a functional gap.

**Classification: Accurate.**

---

## 12. MCP Server Tool Count

**Source:** README.md — "22 tools plus prompts/resources"

**Reality:**
- 22 tools confirmed in `mcp_server/tools.py`
- 5 prompts confirmed in `mcp_server/prompts.py`
- 3 resource types confirmed

**Classification: Accurate.**

---

## 13. Optimization Modes (Standard/Advanced/Research)

**Source:** `docs/platform-overview.md`

**Doc claims:**
- Product exposes three modes: standard, advanced, research
- Each maps to increasing optimization complexity

**Reality:**
- UI Optimize page has `type OptimizeMode = 'standard' | 'advanced' | 'research'`
- `ModeRouter` maps to `SIMPLE`, `ADAPTIVE`, `FULL` respectively
- Each mode activates a substantively more complex strategy

**Classification: Accurate (but research ≠ advanced prompt algorithms as noted above).**

---

## 14. Multi-Agent Graph Model

**Source:** CHANGELOG 2.0.0, architecture docs

**Doc claims:**
- `AgentNode` and `AgentEdge` types for multi-agent topologies
- Optimizer can target specific `agent_path` segments
- Workflow/topology optimization operators

**Reality:**
- `AgentNode`/`AgentEdge`/`AgentGraphVersion` types exist in `core/types.py` — well-defined graph IR
- Blame clusters do include `agent_path` in their key
- Topology mutation operators exist in `optimizer/mutations_topology.py`
- Topology operators are all marked `supports_autodeploy=False` and experimental
- Optimizer core loop operates on flat `AgentConfig`, not graph IR

**Classification: Partial — Graph model is defined, blame analysis uses agent_path, but optimization operates on flat config; multi-agent topology optimization is experimental only.**

---

## 15. Reliability Infrastructure

**Source:** CHANGELOG 2.0.0+, architecture docs

**Doc claims:**
- Dead letter queue, checkpoint store, watchdog, resource monitor, graceful shutdown

**Reality:**
- All 5 components exist in `optimizer/reliability.py` and are substantive
- All initialized at server startup
- Checkpoint, dead letters, watchdog timeout, resource warnings all implemented

**Classification: Accurate.**

---

## 16. Anti-Goodhart Guardrails

**Source:** CHANGELOG 2.1.0

**Doc claims:**
- Dual holdout (fixed + rolling), holdout rotation, drift-aware baseline re-anchoring, judge variance estimation and rejection thresholds

**Reality:**
- All 4 mechanisms implemented in `evals/anti_goodhart.py`
- Connected to optimizer loop in `optimizer/loop.py`
- Configuration values from `agentlab.yaml` (holdout_tolerance, drift_threshold, max_judge_variance) ARE properly consumed here (unlike drift_monitor, which doesn't consume them)

**Classification: Accurate.**

---

## 17. Canary Deployment

**Source:** README, `docs/deployment.md`

**Doc claims:**
- Canary, release, rollback, auto-review-and-deploy
- `agentlab deploy canary` → 10% traffic → auto-promote or rollback

**Reality (partial):**
- Canary deploy mechanics implemented in `deployer/canary.py`
- CLI has full canary lifecycle: start, status, promote, rollback
- UI Deploy page has start and rollback; **missing promote action**
- "10% traffic" is conceptual — no infrastructure-level traffic splitting

**Classification: Partial — Core canary lifecycle is real; UI is missing promote; traffic splitting is semantic not actual.**

---

## Summary Table

| Feature Area | Classification | Key Gap |
|-------------|---------------|---------|
| Pro-mode prompt optimization (MIPROv2/GEPA/SIMBA) | Gap | Unreachable from config, UI, or any user path; `_optimize_pro()` uses MockProvider |
| Research mode uses advanced algorithms | Gap → Partial | Research mode uses FULL strategy, not PRO; algorithm_overrides dict is ignored |
| `search_strategy` in `agentlab.yaml` | Gap | Config value parsed but not passed to Optimizer at server startup |
| AutoFix eval + canary deploy stages | Gap | Apply() is a pure config mutation; no eval or canary in autofix path |
| AutoFix `canary_verdict` / `deploy_message` fields | Gap | Always empty strings in API response |
| Drift monitor pause-on-drift, SSE event | Gap | Not implemented anywhere |
| Drift monitor uses configured thresholds | Gap | Hardcoded 0.1; agentlab.yaml value ignored |
| Context report (aggregate) | Gap | Stub endpoint returning all zeros |
| Context handoff scoring | Gap | `score_handoff()` is dead code |
| BlameMap → optimizer feedback loop | Gap | Two separate taxonomies; no code path from BlameCluster to operator selection |
| Trace grading (7 graders) | Accurate | — |
| BlameMap computation + visualization | Accurate | — |
| NL Scorer | Accurate | — |
| Registry (CRUD, versioning, diff) | Accurate | — |
| MCP server (22 tools, 5 prompts) | Accurate | — |
| Optimization modes (standard/advanced/research) | Accurate | — |
| Reliability infrastructure | Accurate | — |
| Anti-Goodhart guardrails | Accurate | — |
| Canary deployment | Partial | UI missing promote; traffic splitting is conceptual |
| Multi-agent topology optimization | Partial | Graph IR defined; optimizer uses flat AgentConfig |
| Mutation surface coverage | Partial | 2 full / 6 partial / 6 nominal; docs describe full declared set without noting limits |

---

## Recurring Pattern: Implementation-Reality Gap

Several gaps share a common pattern:
1. A feature is architected and documented
2. The data structures, classes, and endpoints are created
3. The "connective tissue" — passing config values, wiring the output of one system to the input of another — is missing

Examples:
- `drift_threshold` is in `agentlab.yaml` → parsed by `OptimizerRuntimeConfig` → **not passed to `DriftMonitor`**
- `search_strategy` is in `agentlab.yaml` → parsed by `OptimizerRuntimeConfig` → **not passed to `Optimizer` constructor**
- `BlameCluster` is computed from traces → **not consumed by `FailureClusterer`**
- `algorithm_overrides` is set in `ResolvedStrategy` → **not read by optimizer loop**
- `score_handoff()` is implemented in `ContextAnalyzer` → **not called from `analyze_trace()`**

These are "last-mile wiring" gaps, not fundamental architectural problems. The data structures and logic exist; they just aren't connected end-to-end.
