# Three Features V2 — Implementation Plan

## Architecture Summary

AutoAgent currently has:
- **core/types.py** — Rich domain objects (AgentGraphVersion with nodes/edges, SkillVersion, ToolContractVersion, PolicyPackVersion, GraderBundle, EvalCase, MetricLayer hierarchy)
- **optimizer/mutations.py** — 9 mutation operators with typed surfaces (instruction, few_shot, tool_description, model, etc.)
- **observer/traces.py** — SQLite-backed TraceStore with TraceEvent + TraceSpan
- **evals/scorer.py** — CompositeScorer → ConstrainedScorer → EnhancedScorer → LayeredScorer stack
- **graders/** — DeterministicGrader, SimilarityGrader, BinaryRubricJudge, GraderStack
- **judges/** — Full judge stack (deterministic, rule_based, llm_judge, audit_judge, calibration)
- **core/handoff.py** — HandoffArtifact with field-level scoring, HandoffComparator
- **api/** — FastAPI with routers under api/routes/
- **web/** — React + React Router + TanStack Query

951 existing tests. Target: 1030+.

---

## Feature 1: Modular Registry

### Files to Create
- `registry/__init__.py` — package init, re-exports
- `registry/skills.py` — SkillRegistry CRUD (extends core/types.py SkillVersion)
- `registry/policies.py` — PolicyRegistry CRUD (extends PolicyPackVersion)
- `registry/tool_contracts.py` — ToolContractRegistry CRUD (extends ToolContractVersion)
- `registry/handoff_schemas.py` — HandoffSchemaRegistry CRUD (extends HandoffArtifact)
- `registry/store.py` — SQLite-backed RegistryStore (single DB, multiple tables)
- `tests/test_registry.py` — Tests for all registry operations

### Files to Modify
- `optimizer/mutations.py` — Add 4 new MutationSurface values: skill, policy, tool_contract, handoff_schema
- `api/server.py` — Register registry router
- `api/routes/registry.py` — CRUD endpoints under /api/registry/
- `web/src/App.tsx` — Add Registry route
- `web/src/pages/Registry.tsx` — Registry browser page

### How It Connects
- SkillVersion, PolicyPackVersion, ToolContractVersion already exist in core/types.py — registry wraps them with CRUD + versioning + SQLite persistence
- MutationSurface gains 4 new values so mutations can target specific registry items
- HandoffArtifact from core/handoff.py gets a registry wrapper for schema definitions

### User Journey
1. `autoagent registry import agent_modules.yaml` → bulk import skills/policies/tools/handoffs
2. `autoagent registry list --type skills` → see all registered skills
3. Mutations now target `skill:returns_handling:v3` instead of "the whole prompt"
4. `autoagent registry diff skills returns_handling 2 3` → see what changed between versions

### Non-Goals
- No live syncing between registries across instances
- No permissions/RBAC on registry items
- No registry marketplace/sharing hub

---

## Feature 2: Trace Grading + Root-Cause Blame Map

### Files to Create
- `observer/trace_grading.py` — SpanGrade dataclass + pluggable span graders (routing, tool_selection, tool_argument, retrieval_quality, handoff_quality, memory_use, final_outcome)
- `observer/blame_map.py` — BlameCluster + BlameMap (aggregation, clustering, impact ranking)
- `observer/trace_graph.py` — TraceGraph (DAG from spans, critical path, bottleneck detection)
- `tests/test_trace_grading.py` — Tests for all trace grading + blame map

### Files to Modify
- `api/routes/traces.py` — Add grade/blame/graph endpoints
- `web/src/pages/Traces.tsx` — Enhance with span-level grade annotations + blame map

### How It Connects
- TraceStore already has TraceEvent + TraceSpan — trace grading annotates spans with SpanGrade
- HandoffComparator from core/handoff.py powers the handoff_quality grader
- JudgeVerdict from core/types.py is the output shape for span graders
- BlameMap clusters SpanGrades across traces by (grader_name, agent_path, failure_reason)

### User Journey
1. Quality drops from 0.82 → 0.71
2. `autoagent trace blame --window 24h` → "73% tool_argument errors in order_lookup, 18% routing to wrong specialist"
3. Click into tool_argument cluster → see specific traces with graded spans
4. AutoFix targets: "Fix the order_lookup tool description"

### Non-Goals
- No real-time streaming of span grades (batch only)
- No custom grader plugin system (7 built-in graders cover the common cases)
- No ML-based anomaly detection on blame clusters

---

## Feature 3: Natural Language Scorer Generation

### Files to Create
- `evals/nl_scorer.py` — NLScorer entry point (English → ScorerSpec)
- `evals/nl_compiler.py` — Compilation engine (NL → structured dimensions, pattern matching)
- `evals/scorer_spec.py` — ScorerSpec + ScorerDimension dataclasses, YAML serialization
- `tests/test_nl_scorer.py` — Tests for NL scorer compilation + refinement

### Files to Modify
- `evals/runner.py` — Support loading ScorerSpec as alternative to manual config
- `api/server.py` — Register scorer router
- `api/routes/scorers.py` — CRUD + test + refine endpoints under /api/scorers/
- `web/src/App.tsx` — Add ScorerStudio route
- `web/src/pages/ScorerStudio.tsx` — NL input → live preview of dimensions

### How It Connects
- ScorerDimension maps to GraderSpec in core/types.py (grader_type + config + weight)
- Compiled dimensions plug into the existing graders/ stack (DeterministicGrader for thresholds, BinaryRubricJudge for LLM judgments)
- ScorerSpec is loadable by EvalRunner as an alternative scoring path
- MetricLayer from core/types.py classifies each dimension

### User Journey
1. PM types: "Good means resolves on first contact, doesn't hallucinate, stays professional, responds under 5s"
2. System generates 4 dimensions: first_contact_resolution (quality, w=0.35), no_hallucination (safety, w=0.3), professionalism (quality, w=0.2), latency (SLO, threshold=5000ms)
3. PM reviews, refines: "Also check tool usage" → dimension added
4. `autoagent scorer test my_scorer --trace abc123` → test against real trace
5. Scorer used in all future eval runs

### Non-Goals
- No auto-tuning of dimension weights from data
- No multi-language NL support (English only)
- No visual rubric editor beyond the generated dimensions

---

## Execution Plan

Three parallel sub-agents:
1. **Agent 1**: registry/ package (backend + tests)
2. **Agent 2**: trace grading + blame map (backend + tests)
3. **Agent 3**: NL scorer (backend + tests)

Then sequentially: CLI commands, API routes, web pages, full test suite.
