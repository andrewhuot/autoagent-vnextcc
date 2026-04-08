# Optimization Components Audit

> **Date**: 2026-04-08
> **Branch**: `feat/optimize-components-audit-claude`
> **Scope**: Does the optimizer inspect, mutate, and expose all ADK/agent config surfaces? Are integration seams ready for external coding agents?

---

## Executive Summary

The optimization system is **architecturally strong** — it defines 14 mutation surfaces with typed operators, a multi-strategy search engine (simple → adaptive → full → pro), and an MCP server with 22+ tools for external agent integration. However, there are **critical gaps between what the system _models_ and what the optimizer _actually targets_** in practice. Several first-class config surfaces (guardrails, sub-agent topology, output validators) exist in the domain model but have no mutation operators, no proposer logic, and no MCP tools to inspect or modify them.

**Verdict**: The foundation is solid. The gaps are enumerable and fixable. The biggest risk is that the optimizer silently ignores surfaces that matter most for production agent quality.

---

## Q1: Does the optimization loop inspect all normal ADK/agent config surfaces?

### Surfaces modeled in the domain (`core/types.py`)

| Surface | AgentNodeType / EdgeType | In MutationSurface enum? | Has mutation operator? | Proposer targets it? |
|---------|--------------------------|--------------------------|------------------------|----------------------|
| Instructions / prompts | — (config field) | ✅ `instruction` | ✅ `instruction_rewrite` | ✅ mock + LLM |
| Few-shot examples | — (config field) | ✅ `few_shot` | ✅ `few_shot_edit` | ❌ mock only hits prompts |
| Tool descriptions | `tool_contract` node | ✅ `tool_description` | ✅ `tool_description_edit` | ✅ (tool_failure bucket) |
| Model selection | — (config field) | ✅ `model` | ✅ `model_swap` | ❌ no proposer path |
| Generation settings | — (config field) | ✅ `generation_settings` | ✅ `generation_settings` | ❌ no proposer path |
| Callbacks | — (config field) | ✅ `callback` | ✅ `callback_patch` | ❌ no proposer path |
| Context caching | — (config field) | ✅ `context_caching` | ✅ `context_caching` | ❌ no proposer path |
| Memory policy | `memory` node | ✅ `memory_policy` | ✅ `memory_policy` | ❌ no proposer path |
| Routing rules | `router` node, `routes_to` edge | ✅ `routing` | ✅ `routing_edit` | ✅ (routing_error bucket) |
| Workflow / orchestration | — | ✅ `workflow` | ❌ **no operator** | ❌ |
| Skills | `skill` node | ✅ `skill` | ✅ `skill_rewrite` | ❌ no proposer path |
| Policies / guardrails config | `guardrail` node, `guards` edge | ✅ `policy` | ✅ `policy_edit` | ❌ no proposer path |
| Tool contracts | `tool_contract` node, `uses_tool` edge | ✅ `tool_contract` | ✅ `tool_contract_edit` | ❌ no proposer path |
| Handoff schemas | `handoff_schema` node, `hands_off_to` edge | ✅ `handoff_schema` | ✅ `handoff_schema_edit` | ❌ no proposer path |

### Surfaces in the domain model but **missing from MutationSurface enum entirely**

| Surface | Where it lives | Gap |
|---------|----------------|-----|
| **Guardrail rules** (input/output validators) | `core/guardrails.py`, `core/guardrail_library.py` | `policy` surface exists but targets policy packs, not guardrail chain composition (add/remove/reorder guardrails) |
| **Sub-agent topology** (add/remove specialists) | `multi_agent/patterns.py`, `agent/specialists/` | No mutation surface. Routing edits change _keywords_ but can't add/remove sub-agents |
| **Judge configuration** | `judge` node type, `judged_by` edge | No mutation surface — judges are treated as fixed infrastructure |
| **Output format / response schema** | Implicit in instructions | No dedicated surface — changes are buried in instruction rewrites |
| **Specialist instructions** (per-sub-agent prompts) | `agent/specialists/*.py` | `instruction_rewrite` targets `prompts.root` or named keys, but the mock proposer only touches `root` |

### Key finding

**13 of 14 mutation surfaces have operators. The `workflow` surface has an enum value but no registered operator.** More critically, only 3 surfaces are reachable from the mock proposer (instructions, routing, tools). The LLM proposer _can_ target any surface via free-form JSON, but has no structured awareness of surfaces like guardrails, callbacks, memory, or handoffs.

**References**:
- `optimizer/mutations.py:40-57` — `MutationSurface` enum (14 values)
- `optimizer/mutations.py:385-586` — `create_default_registry()` (13 operators, missing `workflow`)
- `optimizer/proposer.py:76-196` — `_mock_propose()` (only targets routing, prompts, thresholds, tools)
- `optimizer/proposer.py:198-318` — `_llm_propose()` (free-form, no surface-aware prompting)
- `core/types.py:23-33` — `AgentNodeType` (8 node types including guardrail, judge)
- `core/types.py:64-73` — `EdgeType` (8 edge types)

---

## Q2: Does the mutation/optimization logic actually target those surfaces as first-class candidates?

### The proposer gap

The `Proposer` class has two paths:

1. **Mock proposer** (`_mock_propose`): Deterministic, failure-bucket-driven. Only targets:
   - `routing` (routing_error bucket)
   - `prompts` (unhelpful_response, safety_violation, default)
   - `thresholds` (timeout bucket)
   - `tools` (tool_failure bucket)

   **11 of 14 surfaces are unreachable from the mock proposer.**

2. **LLM proposer** (`_llm_propose`): Sends current config + failure data to an LLM. The system prompt is generic ("propose one high-leverage, safe config improvement") with no enumeration of available surfaces, operators, or constraints. The LLM has to _guess_ what config keys exist.

### The search engine gap

The `HybridSearchOrchestrator` in `optimizer/search.py` does use the full `MutationRegistry`, but:
- The `_OPERATOR_TO_FAMILY` mapping (lines 77-87) only maps 9 of 13 operators. Missing: `skill_rewrite`, `policy_edit`, `tool_contract_edit`, `handoff_schema_edit`.
- These 4 "registry-aware" operators will never be selected by the bandit in adaptive/full mode.

### The skill engine path

The `SkillEngine` (referenced in `optimizer/loop.py:86-91`) provides an alternative optimization path that can compose skills. This is architecturally sound but orthogonal to component-level mutation.

### Verdict

**The mutation registry is well-designed but under-utilized.** The search engine's bandit policy can only select from 9/13 operators. The proposer's mock path only targets 3-4 surfaces. The LLM path is surface-unaware. In practice, **most optimization cycles will only touch instructions, routing, and tool timeouts**.

**References**:
- `optimizer/search.py:77-87` — `_OPERATOR_TO_FAMILY` (9 operators mapped, 4 missing)
- `optimizer/loop.py:223-279` — `_optimize_simple()` flow
- `optimizer/loop.py:357-439` — `_optimize_hybrid()` flow

---

## Q3: Are there clear integration seams for external coding agents?

### What exists

| Integration point | Mechanism | Surfaces exposed | Gap |
|-------------------|-----------|------------------|-----|
| **MCP Server** | JSON-RPC 2.0 over stdio | Status, explain, diagnose, failures, suggest_fix, edit, eval, compare, replay, diff, scaffold, generate_evals, sandbox, inspect_trace, sync_adk | ✅ Good breadth for observe+edit. ❌ No tool to list/select mutation surfaces, no tool to propose+evaluate a candidate config, no tool to read the agent graph IR |
| **CLI connectors** | `cli/mcp_setup.py` | Registers MCP server in Claude Code, Codex, Cursor, Windsurf | ✅ Multi-client support |
| **Multi-agent adapters** | `adapters/*.py` | OpenAI Agents, Anthropic, CX Studio, HTTP webhook | ✅ Import agents. ❌ No "export optimization proposal" adapter |
| **Resources (MCP)** | `mcp_server/resources.py` | Agent configs, traces, eval results, skills, datasets | ✅ Read access. ❌ No agent graph IR resource |
| **Prompts (MCP)** | `mcp_server/prompts.py` | Guided workflows for common tasks | ✅ Good UX layer |

### What's missing for coding-agent integration

1. **No structured "optimization brief" endpoint** — an external agent can call `agentlab_diagnose` and `agentlab_get_failures` separately, but there's no single tool that returns: current config + failure analysis + available mutation surfaces + past attempts + eval scores. This is what a coding agent needs to make an informed proposal.

2. **No "propose and evaluate" tool** — `agentlab_edit` applies a NL edit, but there's no tool that takes a structured config patch, runs it through the eval pipeline, and returns pass/fail with statistical significance. The coding agent has to orchestrate `agentlab_edit` → `agentlab_eval` → `agentlab_diff` manually.

3. **No agent graph IR access** — the `AgentGraphVersion` (`core/types.py`) is a rich representation of the agent topology, but it's not exposed via MCP. A coding agent can't inspect which sub-agents exist, how they're connected, or what guardrails guard which paths.

4. **No mutation surface catalog** — the `MutationRegistry` lists all available operators with risk classes, preconditions, and descriptions, but this isn't exposed via any API. A coding agent can't discover what changes are _possible_.

**References**:
- `mcp_server/tools.py:729-820` — `TOOL_REGISTRY` (22 tools registered)
- `mcp_server/server.py:1-131` — MCP protocol handler
- `mcp_server/resources.py` — Resource provider
- `cli/mcp_setup.py` — Multi-client MCP registration

---

## Q4: What is the best path to make the optimizer component-aware and coding-agent-friendly?

### Target Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    External Coding Agents                    │
│         (Claude Code, Codex, Cursor, Windsurf)              │
│                                                             │
│  1. agentlab_optimization_brief  ← NEW: full context dump   │
│  2. agentlab_list_surfaces       ← NEW: mutation catalog     │
│  3. agentlab_propose_candidate   ← NEW: structured proposal  │
│  4. agentlab_evaluate_candidate  ← NEW: eval + significance  │
│  5. agentlab_agent_graph         ← NEW: topology inspector   │
└──────────────┬──────────────────────────────────────────────┘
               │ MCP (JSON-RPC 2.0)
               ▼
┌─────────────────────────────────────────────────────────────┐
│                    AgentLab Core                             │
│                                                             │
│  MutationRegistry ← add workflow operator, fix bandit map   │
│  Proposer         ← surface-aware prompting for LLM path    │
│  SearchEngine     ← map all 13+ operators to families       │
│  EvalRunner       ← expose candidate eval as atomic op      │
│  AgentGraphVersion ← expose via MCP resource                │
└─────────────────────────────────────────────────────────────┘
```

### Staged Implementation Plan

#### Stage 1: Fix internal gaps (low risk, high leverage)
1. **Add `workflow` mutation operator** to `create_default_registry()` — the enum value exists but no operator is registered.
2. **Map all 13 operators to families** in `_OPERATOR_TO_FAMILY` (`optimizer/search.py:77-87`) — add `skill_rewrite`, `policy_edit`, `tool_contract_edit`, `handoff_schema_edit`.
3. **Add `guardrail_edit` mutation surface and operator** — the guardrail system (`core/guardrails.py`) is rich but invisible to the optimizer.
4. **Add `sub_agent_topology` mutation surface** — enable adding/removing specialists, not just editing routing keywords.

#### Stage 2: Make the proposer surface-aware (medium risk)
5. **Enhance `_llm_propose` system prompt** to enumerate available surfaces, their risk classes, and which ones have been recently changed. Currently it's a generic "propose one improvement" prompt.
6. **Expand `_mock_propose` failure-bucket mapping** to cover more surfaces (e.g., memory_policy for context-related failures, callback for lifecycle issues).

#### Stage 3: MCP integration seams for coding agents (low risk, high value)
7. **`agentlab_optimization_brief` tool** — returns current config + health metrics + failure clusters + available mutation surfaces + past 10 attempts + eval baseline. One call gives a coding agent everything it needs.
8. **`agentlab_list_surfaces` tool** — returns the `MutationRegistry` catalog: operator names, surfaces, risk classes, descriptions, preconditions.
9. **`agentlab_propose_candidate` tool** — accepts a structured config patch + change description, validates it, and returns a preview (diff, risk assessment, estimated eval cost).
10. **`agentlab_evaluate_candidate` tool** — accepts a candidate config, runs eval, compares to baseline with statistical significance, returns pass/fail verdict.
11. **`agentlab_agent_graph` tool** — returns the `AgentGraphVersion` serialized as JSON: all nodes, edges, and their types.

#### Stage 4: Advanced coding-agent patterns (future)
12. **Batch proposal API** — let coding agents submit multiple candidate configs for parallel evaluation.
13. **Structured feedback loop** — after eval, return per-case results so the coding agent can iterate on specific failures.
14. **Git-aware proposals** — coding agents working in a worktree can propose changes that include both config mutations and code changes (e.g., new tool implementations).

---

## Gap Matrix

| # | Gap | Severity | Stage | Files to change |
|---|-----|----------|-------|-----------------|
| G1 | ~~`workflow` MutationSurface has no operator~~ **FIXED** | Medium | 1 | `optimizer/mutations.py` |
| G2 | ~~4 operators unmapped in bandit family selector~~ **FIXED** | High | 1 | `optimizer/search.py` |
| G3 | No guardrail mutation surface/operator | High | 1 | `optimizer/mutations.py` |
| G4 | No sub-agent topology mutation | Medium | 1 | `optimizer/mutations.py` |
| G5 | Mock proposer only targets 3-4 surfaces | Medium | 2 | `optimizer/proposer.py` |
| G6 | LLM proposer has no surface awareness | High | 2 | `optimizer/proposer.py` |
| G7 | No optimization brief MCP tool | High | 3 | `mcp_server/tools.py` |
| G8 | No mutation catalog MCP tool | High | 3 | `mcp_server/tools.py` |
| G9 | No propose/evaluate MCP tools | High | 3 | `mcp_server/tools.py` |
| G10 | No agent graph MCP tool | Medium | 3 | `mcp_server/tools.py` |
| G11 | Judge config not optimizable | Low | 4 | `optimizer/mutations.py` |
| G12 | No batch proposal API | Low | 4 | `mcp_server/tools.py`, `optimizer/loop.py` |

---

## Key Risks

1. **Silent surface blindness** — The optimizer runs successfully but never touches guardrails, memory, handoffs, callbacks, or sub-agent topology. Users may believe these are being optimized when they aren't.
2. **Bandit starvation** — 4 of 13 operators can never be selected in adaptive/full mode due to missing family mappings. These are the newest and most sophisticated operators (skill, policy, tool_contract, handoff_schema).
3. **LLM proposer drift** — Without surface-aware prompting, the LLM proposer will converge on instruction rewrites (the easiest, most familiar change) and ignore structural changes.
4. **MCP surface gap** — External coding agents have observe+edit capabilities but no propose+evaluate workflow. They can't participate in the optimization loop as first-class actors.

---

## Appendix: File Reference Index

| File | Lines | Role in optimization |
|------|-------|---------------------|
| `optimizer/mutations.py` | 587 | Mutation surfaces, operators, registry factory |
| `optimizer/proposer.py` | 319 | Mock + LLM proposal generation |
| `optimizer/search.py` | ~800 | Multi-hypothesis search, bandit selection |
| `optimizer/loop.py` | ~600+ | Optimization cycle orchestrator |
| `core/types.py` | ~250 | Agent graph IR (nodes, edges, versions) |
| `core/guardrails.py` | ~130 | Guardrail primitives |
| `core/guardrail_library.py` | large | Pre-built guardrail implementations |
| `core/handoff.py` | — | Handoff schema |
| `mcp_server/tools.py` | ~820 | MCP tool implementations + registry |
| `mcp_server/server.py` | ~165 | MCP protocol handler |
| `mcp_server/resources.py` | — | MCP resource provider |
| `agent/config/base_config.yaml` | — | Agent config template |
| `adk/callbacks.py` | — | Callback lifecycle hooks |
| `adk/parser.py` | — | ADK agent JSON parser |
| `multi_agent/patterns.py` | — | Multi-agent topology patterns |
