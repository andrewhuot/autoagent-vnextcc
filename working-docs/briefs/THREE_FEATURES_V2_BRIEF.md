# Three Features V2 — Registry, Trace Grading, NL Scorer

## CRITICAL DESIGN PRINCIPLES
- **Product sense first.** These features should make AutoAgent dramatically easier to use, not harder.
- **Modular by default.** The whole point of Feature 1 is that mutations target modules, not monoliths. Design accordingly.
- **Show the "why", not just the "what".** Feature 2 exists because teams need root-cause, not more dashboards.
- **Zero-config entry point.** Feature 3 means a PM can type English and get a working scorer. No YAML, no code.
- **Research as needed.** These are frontier features. Read how OpenAI Evals does trace grading. Read how Braintrust/Log10 do NL scorers. Understand before building.

---

## PLANNING PHASE (mandatory, before any code)

1. **Read the existing codebase** to understand where each feature fits:
   - `core/types.py` — existing domain objects (AgentGraphVersion has skills, tools, policies already — understand the current shape)
   - `optimizer/mutations.py` — mutation operators and surfaces (registry must integrate here)
   - `observer/traces.py` — trace events and spans (trace grading extends this)
   - `judges/` and `graders/` — existing grading stack (NL scorer compiles into this)
   - `evals/scorer.py` — CompositeScorer (NL scorer generates these)
   - `evals/runner.py` — how evals run (NL scorer must work here)
   - `optimizer/search.py` — search strategies reference mutations
   - `core/handoff.py` — existing handoff artifacts
   - `api/` and `web/` — existing patterns

2. **Write `THREE_FEATURES_V2_PLAN.md`** with:
   - Exact files to create/modify
   - How each feature connects to existing primitives
   - What you're NOT building
   - User journey for each feature (how does someone actually use this?)

3. **Then implement** using sub-agents.

---

## FEATURE 1: Modular Registry (Skills, Policies, Tool Contracts, Handoff Schemas)

### The Problem
AutoAgent currently treats agent configs as monolithic blobs. Mutations target "the whole prompt" or "the whole config." This plateaus because:
- Changes aren't composable or reusable
- Teams can't share pieces of behavior
- Mutations can't be scoped to the right granularity

### What To Build

**`registry/` package** — a first-class registry for modular agent components:

- `registry/skills.py` — Versioned, reusable skill definitions
  - A skill = (name, version, instruction_text, examples, tool_requirements, constraints)
  - CRUD: register, list, get, update, deprecate
  - Version history with diffs
  - Skills can be shared across agents

- `registry/policies.py` — Policy packs (safety rules, tone guidelines, escalation rules)
  - A policy = (name, version, rules: list[str], enforcement: "hard" | "soft", scope: "global" | "agent-specific")
  - Composable: an agent references multiple policy packs
  - Mutations can target one policy pack without touching others

- `registry/tool_contracts.py` — Tool contract definitions
  - A contract = (tool_name, version, input_schema, output_schema, side_effect_class, replay_mode, description)
  - Extends existing ToolContractVersion in core/types.py
  - Registry tracks which agents use which tools

- `registry/handoff_schemas.py` — Structured handoff definitions
  - A schema = (from_agent, to_agent, required_fields, optional_fields, validation_rules)
  - Extends existing HandoffArtifact in core/handoff.py
  - Validates handoffs at eval time

- `registry/store.py` — SQLite-backed persistence for all registry items
  - Single store, multiple tables (skills, policies, tool_contracts, handoff_schemas)
  - Version tracking, search, dependency resolution

**Integration with mutations:**
- New mutation surfaces: `skill`, `policy`, `tool_contract`, `handoff_schema`
- Mutations target specific registry items by (name, version), not "the whole agent"
- Example: `instruction_rewrite` on skill "returns_handling" v3, not on "the system prompt"

**CLI:**
- `autoagent registry list [--type skills|policies|tools|handoffs]`
- `autoagent registry show <type> <name> [--version N]`
- `autoagent registry add <type> <name> --file <path>`
- `autoagent registry diff <type> <name> <v1> <v2>`
- `autoagent registry import <path>` — bulk import from YAML/JSON

**API:** CRUD endpoints under `/api/registry/`
**Web:** Registry browser page with search, version history, dependency graph

### User Journey
1. Team imports their agent's skills/policies from a YAML file: `autoagent registry import agent_modules.yaml`
2. AutoAgent mutations now target specific skills: "Rewrite the returns_handling skill instruction"
3. When a mutation improves a skill, the new version is registered automatically
4. Teams can export and share improved skills across agents

---

## FEATURE 2: Trace Grading + Root-Cause Blame Map

### The Problem
Current eval gives run-level scores ("quality: 0.78"). Teams don't know WHY — was it a routing failure? Bad tool arguments? Stale memory? Poor handoff? They need span-level diagnosis that clusters into actionable blame.

### What To Build

**`observer/trace_grading.py`** — Span-level grading on trace graphs:

Pluggable graders that annotate individual spans within a trace:
- **Routing grader** — Did the agent route to the correct specialist? Score routing decisions.
- **Tool selection grader** — Did the agent pick the right tool? Was it necessary?
- **Tool argument grader** — Were the tool arguments correct/complete?
- **Retrieval quality grader** — Was retrieved context relevant and sufficient?
- **Handoff quality grader** — Did the handoff preserve necessary context? (Uses HandoffComparator from core/handoff.py)
- **Memory use grader** — Was memory stale? Was relevant memory retrieved?
- **Final outcome grader** — Did the agent achieve the goal?

Each grader returns: `SpanGrade(span_id, grader_name, score: float, passed: bool, evidence: str, failure_reason: str | None)`

**`observer/blame_map.py`** — Root-cause clustering:
- Aggregate span grades across traces
- Cluster failures by (grader_name, agent_path, failure_reason)
- Compute blame attribution: "62% of quality regressions trace to routing changes in returns flows"
- Rank blame clusters by impact (severity × frequency)
- Time-series: is this blame cluster growing or shrinking?

**`observer/trace_graph.py`** — Trace as a directed graph:
- Nodes = spans (agent invocations, tool calls, handoffs)
- Edges = causal dependencies (parent span → child span)
- Enables graph-level analysis: critical path, bottleneck detection

**CLI:**
- `autoagent trace grade <trace-id>` — grade all spans in a trace, show blame
- `autoagent trace blame [--window 24h]` — show top blame clusters
- `autoagent trace graph <trace-id>` — show trace graph structure

**API:**
- `GET /api/traces/{id}/grades` — span-level grades for a trace
- `GET /api/traces/blame` — blame map with clustering
- `GET /api/traces/{id}/graph` — trace graph structure

**Web:** 
- Trace detail page enhanced with span-level grade annotations
- Blame map dashboard: treemap or ranked list of failure clusters with drill-down
- Click a blame cluster → see the traces that contribute

### User Journey
1. Team sees quality dropped from 0.82 to 0.71
2. `autoagent trace blame` shows: "73% of new failures from tool_argument errors in order_lookup, 18% from routing to wrong specialist"
3. Team clicks into the tool_argument cluster, sees specific traces with graded spans
4. AutoFix Copilot can now target mutations precisely: "Fix the order_lookup tool description"

---

## FEATURE 3: Natural Language Scorer Generation

### The Problem
Writing eval rubrics requires engineering effort — YAML configs, understanding scorer APIs, knowing what dimensions to measure. PMs and agent owners know what "good" looks like but can't express it as code. This is the #1 adoption blocker for eval-driven development.

### What To Build

**`evals/nl_scorer.py`** — Natural language to structured scorer compiler:

Flow:
1. User describes success criteria in English: "The agent should answer the customer's question accurately, not make up information, respond in under 3 seconds, and always offer to help with something else"
2. NL Scorer parses this into structured rubric dimensions:
   - `accuracy`: "Answer matches ground truth or is factually correct" (quality, weight=0.4)
   - `no_hallucination`: "Does not fabricate information" (safety, weight=0.3)
   - `latency`: "Response time under 3 seconds" (latency, threshold=3000ms)
   - `follow_up`: "Offers additional assistance" (quality, weight=0.15)
3. Each dimension becomes a grader (deterministic where possible, LLM judge where necessary)
4. Compiled into a `ScorerSpec` that the eval pipeline can execute
5. User can review, edit, and version the generated scorer

**`evals/nl_compiler.py`** — The compilation engine:
- Uses LLMRouter to parse NL criteria → structured dimensions
- Pattern matching for common criteria types:
  - Latency/speed → deterministic threshold grader
  - Accuracy/correctness → LLM judge with reference comparison
  - Safety/hallucination → deterministic safety checks + LLM judge
  - Tone/style → LLM judge with rubric
  - Completeness → LLM judge with checklist
- Generates grader configs that plug into existing `graders/` stack
- Iterative refinement: "Add a dimension for empathy" → recompile

**`evals/scorer_spec.py`** — The compiled scorer artifact:
- `ScorerSpec(name, version, dimensions: list[ScorerDimension], source_nl: str, compiled_at: timestamp)`
- `ScorerDimension(name, description, grader_type, grader_config, weight, layer: MetricLayer)`
- Serializable to YAML for version control
- Can be loaded by EvalRunner as an alternative to manual scorer config

**CLI:**
- `autoagent scorer create "The agent should..."` — interactive NL scorer creation
- `autoagent scorer create --from-file criteria.txt` — from file
- `autoagent scorer list` — list compiled scorers
- `autoagent scorer show <name>` — show dimensions and config
- `autoagent scorer test <name> --trace <id>` — test scorer against a real trace
- `autoagent scorer refine <name> "Also check for empathy"` — add/modify dimensions

**API:**
- `POST /api/scorers/create` — compile NL description to scorer
- `GET /api/scorers` — list scorers
- `GET /api/scorers/{name}` — show scorer details
- `POST /api/scorers/{name}/test` — test against a trace
- `POST /api/scorers/{name}/refine` — refine with additional NL input

**Web:**
- Scorer studio page: text area for NL input, live preview of generated dimensions
- Edit individual dimensions after generation
- Test scorer against sample traces with visual results
- "Use this scorer" button that activates it for eval runs

### User Journey
1. PM types: "Good means the agent resolves the issue on first contact, doesn't ask the customer to repeat themselves, stays professional, and doesn't take longer than 5 seconds"
2. System generates 4 scorer dimensions with appropriate grader types
3. PM reviews: "I also care about whether it uses the right tools" → refines
4. Scorer is saved and used in all future eval runs
5. When AutoFix runs, it optimizes against these PM-defined criteria

---

## EXECUTION

Use `claude --model claude-sonnet-4-5 --dangerously-skip-permissions -p '...'` sub-agents:
- Agent 1: Registry package (backend + tests)
- Agent 2: Trace grading + blame map (backend + tests)
- Agent 3: NL scorer generation (backend + tests)
- Then: CLI commands, API routes, web pages

Run `python3 -m pytest tests/ --tb=short -q` after each feature.

## DONE CRITERIA
- All three features have backend modules, CLI commands, API endpoints, and web pages
- All new code has tests
- Full test suite passes (baseline: 951 + target 80+ new = 1030+)
- Git commit with conventional commit message
- Push to current branch
