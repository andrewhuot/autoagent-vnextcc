# Optimization Components Audit

Date: 2026-04-08

## Executive Summary

The current optimization loop does **not** fully cover normal ADK / agent components end to end.

What exists today is a mix of:

- a **broad declared mutation model** in `optimizer/mutations.py`
- a **narrower live optimization path** in `optimizer/loop.py`, `optimizer/search.py`, `optimizer/proposer.py`, `observer/opportunities.py`, `optimizer/nl_editor.py`, and `optimizer/autofix_proposers.py`
- a **narrowest canonical config contract** in `agent/config/schema.py`

The practical result is:

1. The system is strongest on **instructions**, **routing**, and some **basic tool/config tuning**.
2. It is partial on **model**, **context caching**, **memory policy**, and **ADK import/export**.
3. It is nominal or disconnected on **callbacks**, **guardrails/policies**, **tool contracts**, **handoff schemas/artifacts**, **sub-agents/topology/workflow**, and several **context/memory hook** surfaces.
4. External coding-agent seams are already meaningful on the **read/evidence** side, but the **write/optimize** side is fragmented and not yet component-aware.

The shipped inventory currently reports **18 total surfaces**:

- **2 full**
- **8 partial**
- **7 nominal**
- **1 none**

The strongest direction is to move toward a **component-aware canonical agent representation** that sits above the current `AgentConfig`, not to keep adding one-off fields or more prompt-centric mutations.

As a low-risk scaffolding improvement, this audit also adds:

- `optimizer/surface_inventory.py`
- `GET /api/optimize/surfaces`

That endpoint exposes the current surface coverage inventory for the studio, APIs, and external coding agents.

## Scope And Method

This audit traced the current loop from entrypoint to mutation/eval/deploy and then compared that path against the broader agent surfaces present elsewhere in the repo.

Primary evidence paths:

- Optimization loop: `api/routes/optimize.py`, `optimizer/loop.py`, `optimizer/search.py`, `optimizer/proposer.py`
- Mutation surfaces: `optimizer/mutations.py`, `optimizer/mutations_topology.py`
- Failure-to-operator mapping: `observer/opportunities.py`
- Autofix and NL editing: `optimizer/autofix.py`, `optimizer/autofix_proposers.py`, `optimizer/nl_editor.py`
- Canonical config: `agent/config/schema.py`
- ADK parsing/mapping/export: `adk/types.py`, `adk/parser.py`, `adk/mapper.py`, `adk/importer.py`, `adk/exporter.py`
- Runtime primitives not fully integrated into optimization: `adk/callbacks.py`, `adk/memory_bank.py`, `core/handoff.py`, `core/guardrails.py`
- External-agent seams: `api/routes/traces.py`, `api/routes/context.py`, `api/routes/diagnose.py`, `api/routes/adk.py`, `api/routes/connect.py`, `mcp_server/resources.py`, `mcp_server/tools.py`
- Studio merge points: `web/src/components/builder/Inspector.tsx`, `web/src/components/builder/inspector/CodingAgentConfigTab.tsx`, `web/src/pages/AgentStudio.tsx`, `web/src/pages/Improvements.tsx`

## Current Loop Findings

### 1. The live loop is narrower than the declared mutation model

`optimizer.mutations.MutationSurface` declares these surfaces:

- instruction
- few_shot
- tool_description
- model
- generation_settings
- callback
- context_caching
- memory_policy
- routing
- workflow
- skill
- policy
- tool_contract
- handoff_schema

But the live loop reaches only a subset:

- `optimizer.proposer.Proposer._mock_propose()` proposes only `prompts`, `routing`, `thresholds`, and `tools`.
- `optimizer.search._OPERATOR_TO_FAMILY` only wires `routing_edit`, `model_swap`, `callback_patch`, `generation_settings`, `tool_description_edit`, `context_caching`, `memory_policy`, `instruction_rewrite`, and `few_shot_edit` into adaptive search.
- `observer.opportunities._BUCKET_TO_OPERATORS` is narrower again, with only:
  - `tool_description_edit`
  - `routing_edit`
  - `instruction_rewrite`
  - `callback_patch`
  - `generation_settings`
  - `model_swap`
  - `few_shot_edit`
  - `context_caching`
- `optimizer.mutations_topology` keeps workflow/topology operators as experimental `ready=False` stubs.

### 2. The canonical config is narrower than both of those

`agent.config.schema.AgentConfig` includes:

- routing
- prompts
- tools
- thresholds
- context_caching
- compaction
- memory_policy
- optimizer settings
- model
- quality_boost

It does **not** include:

- few-shot examples
- generation settings
- callbacks
- policies / guardrails
- tool contracts
- handoff schemas / artifacts
- explicit workflow / topology
- explicit sub-agent structure

That means several declared mutation surfaces are not truly end-to-end optimization surfaces, because the optimizer validates through `AgentConfig` before evaluating/deploying.

### 3. ADK support is real but only partially connected to optimization

The ADK layer knows about more than the optimizer can currently mutate end to end:

- `adk.types.AdkAgent` includes model, instruction, tools, sub_agents, generate_config, and multiple callback hooks.
- `adk.mapper.AdkMapper` only maps prompts, tools, routing derived from sub-agents, generation settings, and model into AgentLab config.
- `adk.exporter.AdkExporter` only writes back instructions, model/generation config, and tool descriptions.

So the repo understands richer ADK structure, but the optimization loop does not yet optimize that richer structure in a canonical, round-trippable way.

### 4. Observability is stronger than mutation coverage

The repo already has meaningful evidence pipelines:

- trace events and search
- blame maps
- trace grading
- context analysis
- diagnose sessions
- opportunity clustering
- eval history

This is important because it means the main gap is **not** lack of evidence. The gap is lack of a **component-aware mutation contract** that connects evidence to real agent components and then back to source/config safely.

## Coverage Matrix

Legend:

- These support levels now match the `support_level` returned by `optimizer.surface_inventory.build_surface_inventory()`.
- `Full`: represented in canonical config and genuinely usable through the current loop
- `Partial`: real support exists, but one or more of config representation, opportunity generation, adaptive reachability, or writeback is missing
- `Nominal`: component exists in the repo and may even have operators, but is not meaningfully end to end in the current loop
- `None`: essentially absent from optimization coverage

| Surface | Current support | Evidence | Missing gap |
|---|---|---|---|
| Instructions | Full | Canonical in `AgentConfig.prompts`; live in simple proposer, adaptive search, NL editor, AutoFix; round-trips through ADK import/export | Still mostly flat-text prompt optimization rather than structured instruction section optimization |
| Routing | Full | Canonical in `AgentConfig.routing`; live in simple proposer, adaptive search, opportunities, NL editor; imported from ADK/connect | ADK export does not write routing changes back into sub-agent topology |
| Tool runtime config | Partial | Canonical in `AgentConfig.tools`; simple proposer and NL editor adjust tool timeouts; adaptive loop can use `tool_description_edit` | Tool operator naming and opportunity mapping are description-oriented, not explicitly runtime-config-oriented |
| Tool descriptions / params | Partial | ADK/connect import and ADK export preserve descriptions; mutation operator can edit tool config | Canonical `AgentConfig` does not preserve descriptions, so this surface is not durable through validation |
| Model selection | Partial | Canonical `model` exists; adaptive search and AutoFix can propose `model_swap`; ADK round-trip supports model | High-risk only, not used by simple proposer, and not linked to richer component evidence |
| Few-shot examples | Partial | Mutation operator exists; adaptive search, opportunities, NL editor, AutoFix can target it | Not in canonical `AgentConfig`; not in ADK round-trip; not durable end to end |
| Generation settings | Partial | Mutation operator exists; adaptive search, opportunities, NL editor, AutoFix target it; ADK mapper/exporter mention generation config | Not in canonical `AgentConfig`; naming is inconsistent between `generation`, `generation_settings`, and `generate_config` |
| Context caching | Partial | Canonical config field exists; adaptive search and opportunity generation can target it | Not represented in ADK/connect flows; not surfaced as a richer context-engineering component |
| Memory policy | Partial | Canonical config field exists; adaptive search can target it | No opportunity mapping, no NL/autofix path, and not connected to runtime memory-bank hooks |
| Thresholds | Partial | Canonical config field exists; simple proposer and NL editor use it | Not a first-class mutation surface; not in adaptive search/operator system |
| Compaction | None | Canonical config field and Context Engineering Studio exist | No mutation surface, no opportunity generation, no writeback path |
| Callbacks | Nominal | Runtime callback registry exists; `callback_patch` operator exists; safety opportunity can recommend it; ADK types know callback hooks | Not in canonical config, not mapped by ADK importer/exporter, no NL/autofix path, no clear writeback contract |
| Guardrails / policies | Nominal | Guardrail registry and policy registry exist; connect adapters can import guardrails; `policy_edit` operator exists | Not in canonical config, not in opportunity generation, not mapped by ADK round-trip, not component-aware in live loop |
| Tool contracts | Nominal | `tool_contract_edit` operator exists; registry has related concepts | No canonical config field, no opportunity mapping, no external round-trip path |
| Handoffs / transfer artifacts | Nominal | `HandoffArtifact`, trace grading, handoff-quality grading, connect adapters import handoffs, `handoff_schema_edit` operator exists | Not in canonical config, not in adaptive search/opportunities, no ADK export path, no live mutation contract |
| Workflow / topology | Nominal | Workflow/topology operators exist in `optimizer.mutations_topology`; ADK types know orchestration types and sub-agents | Operators are experimental `ready=False`; no canonical config representation; no live loop reachability |
| Skills | Nominal | Skill engine, autolearner, and `skill_rewrite` operator exist | Skills are applied around the loop, but not optimized as first-class canonical components in the main config/eval/deploy path |
| Sub-agents / component graph | Nominal | ADK parser/importer can discover sub-agents; connect adapters discover handoffs/agents; studio has an ADK graph tab | Canonical optimization model collapses structure into prompts/routing instead of preserving a real component graph |

## Goal-by-Goal Answers

### Goal 1: Does the current loop look across all normal ADK / agent components?

No.

It looks across a meaningful but incomplete subset:

- instructions
- routing
- some tool config
- model
- context caching
- memory policy
- a few prompt-optimization surfaces

It does **not** fully look across:

- callbacks
- guardrails / policies
- tool descriptions as durable config
- tool contracts
- handoff schemas / artifacts
- workflow / topology / sub-agents
- richer context hooks and runtime memory systems

### Goal 2: Are those components actually candidate mutation/fix surfaces in the live logic?

Only partially.

There are three concentric circles:

1. **Declared mutation surfaces** in the registry
2. **Reachable search/proposer surfaces** in the live loop
3. **Canonical config surfaces** that survive validation and can be deployed

The system is currently strongest only where all three overlap.

### Goal 3: Are there clear integration points for Claude Code, Codex, or Google Antigravity?

Yes on the **read/evidence** side.

Partially on the **writeback** side.

The repo already exposes enough evidence for an external coding agent to inspect:

- traces
- trace grades
- blame clusters
- context analysis
- diagnosis sessions
- optimization history
- ADK import/export previews
- external runtime connect/import
- MCP resources and helper tools

But the repo does **not** yet provide a first-class, component-aware contract for:

- enumerating the canonical optimization surfaces
- binding eval/trace evidence to those exact components
- letting an external coding agent propose a typed patch bundle against those components
- validating that bundle against schema, evals, and round-trip writeback rules

### Goal 4: Strongest implementation direction

Introduce a **component-aware canonical representation** and make everything else adapt to it.

Do **not** keep growing the current system by:

- adding more one-off optimizer operators without canonical config support
- adding more UI tabs without backend component contracts
- adding more framework-specific import/export logic that bypasses a shared representation

## Current Integration Map For External Coding Agents

### Read / inspect seams

| Seam | What an external coding agent can read today | Current quality |
|---|---|---|
| REST: `/api/traces/*` | recent traces, trace search, error traces, trace grades, trace graph, trace promotion | Strong |
| REST: `/api/context/*` | context analysis and simulation | Medium |
| REST: `/api/diagnose*` | clustered diagnosis and conversational diagnose workflow | Medium |
| REST: `/api/optimize/history` | recent optimization attempts and significance stats | Medium |
| REST: `/api/optimize/surfaces` | structured component/surface coverage inventory, including support tiers and live path flags | New, strong as a starting seam |
| REST: `/api/adk/*` | ADK import, export, diff preview, status, deploy | Strong for file-based ADK workflows |
| REST: `/api/connect/*` | import OpenAI Agents, Anthropic, HTTP, or transcript runtimes into a workspace | Strong for ingest, not yet full fidelity |
| MCP resources | configs, traces, evals, skills, dataset stats | Good read-only entrypoint |
| MCP tools | status, explain, diagnose, edit, eval, eval_compare, scaffold_agent, generate_evals | Useful helpers, but not component-aware |

### Write / actuation seams

| Seam | What it can do | Current quality |
|---|---|---|
| `/api/optimize/run` | run the built-in loop | Strong for current narrow surfaces |
| `/api/autofix/*` | generate, apply, reject heuristic proposals | Medium |
| `/api/adk/export` | write optimized changes back to ADK snapshot/output | Medium, narrow surface coverage |
| `/api/reviews/*` | request and submit review decisions | Medium |
| MCP `agentlab_edit` / `agentlab_suggest_fix` | NL-driven config suggestions | Medium-low, narrow surfaces |

### What is still missing for external coding agents

1. A stable **component graph** endpoint, not just configs and traces.
2. A stable **evidence-to-component map**.
3. A **typed patch bundle** contract for external agents.
4. A **round-trip validator** that confirms whether a proposed change survives canonical config validation and framework export.
5. A component-aware review object that combines:
   - touched components
   - evidence references
   - risk
   - eval deltas
   - writeback feasibility

## Proposed Target Architecture

### Design goals

- One canonical representation of the agent that is richer than today’s `AgentConfig`
- Framework adapters that map into and out of that canonical representation
- Evidence linked to components, not only to free-form failure buckets
- One reviewable patch contract usable by internal optimizer logic and external coding agents

### Non-goals

- Do not make raw AST mutation the primary control plane
- Do not add a separate studio-only component model
- Do not replace the current eval, trace, or deploy subsystems

### Options considered

| Option | Description | Pros | Cons |
|---|---|---|---|
| A. Keep extending `AgentConfig` ad hoc | Add missing fields directly to the current schema | Fastest local changes | Grows a leaky config object with inconsistent framework mapping and no clear component graph |
| B. Add a canonical `AgentComponentGraph` / `AgentIR` above `AgentConfig` | Represent instructions, tools, callbacks, policies, handoffs, routing, memory, and topology as typed components | Strongest long-term design, clear external-agent seam, preserves framework adapters | More upfront design work |
| C. Skip canonical IR and mutate framework code directly | Push optimization into ADK/OpenAI/Anthropic code patchers | High theoretical fidelity | High risk, hard to reason about, fragmented, difficult for eval/deploy/review workflows |

### Recommendation

Choose **Option B: canonical component-aware IR**.

Why:

- It matches the repo’s actual breadth: ADK, connect adapters, MCP, studio, trace grading, and review workflows all want richer components than `AgentConfig` can currently express.
- It allows the current loop to stay intact while gradually moving mutation planning and review onto a better substrate.
- It gives Claude Code, Codex, and Antigravity a stable contract that is not tied to one framework’s source layout.

### Recommended architecture

#### 1. Canonical component graph

Introduce a typed representation with component kinds such as:

- `instruction_block`
- `few_shot_set`
- `tool_runtime_config`
- `tool_description`
- `tool_contract`
- `callback_hook`
- `policy_guardrail`
- `routing_rule`
- `handoff_schema`
- `memory_policy`
- `context_policy`
- `generation_settings`
- `model_binding`
- `sub_agent`
- `workflow_edge`

Each component should carry:

- stable `component_id`
- `kind`
- source of truth
- canonical payload
- framework mapping metadata
- writeback support level

#### 2. Evidence linker

Map traces, blame clusters, eval failures, and diagnose output onto component IDs.

That turns today’s generic failure clustering into component-aware opportunities:

- this routing edge is failing
- this callback blocks correct tool use
- this handoff artifact drops key fields
- this policy causes false-positive refusals

#### 3. Mutation planner

Replace today’s operator selection logic with planners that target component kinds explicitly.

A mutation proposal should say:

- touched component IDs
- touched component kinds
- planned patch
- risk class
- required eval slices
- writeback feasibility
- human review requirements

#### 4. Adapters

Framework-specific adapters should only do translation:

- ADK import/export
- OpenAI Agents import/export
- Anthropic runtime import/export
- connected-runtime import

The optimizer should operate on the canonical graph, not on framework-specific structures.

#### 5. External coding-agent contract

Add a first-class API/MCP contract that lets an external coding agent:

- fetch the component graph
- fetch evidence linked to components
- fetch current coverage gaps
- submit a patch bundle
- request eval preview
- receive round-trip/writeback diagnostics

## Prioritized Implementation Plan

### MVP

1. Make surface coverage explicit everywhere.
   - Done in scaffold form with `optimizer/surface_inventory.py` and `GET /api/optimize/surfaces`.
   - Next step: expose the same inventory through MCP resources/tools and the studio inspector.

2. Normalize the canonical config for already-declared surfaces.
   - Add first-class schema support for:
     - few-shot examples
     - generation settings
     - callbacks
     - policies / guardrails
     - handoff schemas
     - tool contracts
   - If that feels too large for one pass, introduce a small `AgentIR` alongside `AgentConfig` and start migrating there.

3. Align import/export naming and round-trip behavior.
   - Resolve `generation` vs `generation_settings` vs `generate_config`.
   - Preserve imported tool descriptions instead of dropping them at validation.
   - Make routing export either real or clearly unsupported.

4. Turn component coverage into a supported backend artifact.
   - Keep one source of truth for surface inventory, component kinds, and writeback support.

### P1

1. Build the canonical component graph.
2. Link opportunities and trace evidence to component IDs.
3. Replace failure-family-only operator selection with component-aware planning.
4. Introduce typed patch bundles and review cards.
5. Add an external-agent patch/eval/review API.

### Later

1. Safe topology optimization for sub-agents and workflow edges.
2. Richer callback and memory-hook optimization.
3. Cross-runtime patch export beyond ADK.
4. Multi-agent system optimization with first-class handoff contracts and topology constraints.

## Merge Recommendations For Ongoing Studio Work

### 1. Use the new surface inventory as the backend truth source

Do not let the studio invent its own notion of “components supported by optimization.”

Instead:

- feed `GET /api/optimize/surfaces` into the builder/inspector and improvement surfaces
- let the UI render:
  - supported surfaces
  - partial surfaces
  - nominal / none surfaces
  - writeback gaps

### 2. Upgrade `CodingAgentConfigTab` into a real component coverage pane

Today it renders only `AGENTS.md` and `CLAUDE.md` text.

It should become the place where studio users and coding agents can see:

- workspace instructions
- optimization surface coverage
- framework import/export fidelity
- missing canonical support
- writeback status

### 3. Reuse the same backend model in `AgentStudio`

`AgentStudio` already frames changes as prompt, policy, routing, and handoff edits.
That is the right product direction, but it is currently largely draft/scaffold logic.

Do not build a separate studio-only draft representation.

Instead:

- make `AgentStudio` generate typed component patch bundles
- run those bundles through the same review/eval/writeback pipeline as optimize/autofix

### 4. Merge Improvements and Studio around one review object

The `Improvements` workflow already has the right high-level stages:

- opportunities
- experiments
- review
- history

The merge should happen around a shared review object that carries:

- touched component IDs
- evidence refs
- diff
- eval deltas
- governance notes
- export/writeback readiness

### 5. Treat traces and context as first-class inputs to studio authoring

The studio should not only author changes. It should also show:

- which traces support the change
- which graders blame the touched component
- whether the component is even canonical/writeback-safe today

That keeps the studio grounded in the same operational truth as the optimize loop.

## Small Improvement Added In This Workstream

To support this direction without risky churn, this audit adds:

- `optimizer/surface_inventory.py`
- `GET /api/optimize/surfaces`
- focused tests in `tests/test_optimize_surface_inventory.py`

The inventory payload now includes:

- per-surface `support_level`
- explicit `optimization_paths`
- explicit `representation_paths`
- summary counts by support tier

This is intentionally small, but it creates a real seam for:

- studio UI integration
- external coding-agent inspection
- future MCP exposure
- audit automation

## Strongest Critique Of Current Coverage

The current system **looks** broader than it really is because the repo contains:

- broad mutation enums
- rich ADK/runtime primitives
- strong observability
- studio/builder scaffolding

But the actual end-to-end optimization contract is still mostly a **prompt-and-basic-config tuner** wrapped in a much larger platform shell.

Until the repo has a canonical component-aware representation that connects:

- evidence
- mutation planning
- schema validation
- framework writeback
- review

it will continue to overstate its optimization coverage relative to what it can actually improve safely and durably.
