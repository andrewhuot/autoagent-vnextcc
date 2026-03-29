# Executable Skills Registry Brief

## Mission
Upgrade AutoAgent's skills registry from metadata entries to executable optimization strategies. Skills become the core knowledge unit — code + knowledge that the optimizer consults before proposing changes. This is the "npm for agent optimization."

## Current State
- `registry/` module has `RegistryStore` (SQLite CRUD for skills, policies, tool_contracts, handoff_schemas)
- `registry/runbooks.py` has 7 builtin runbooks that reference skill names
- Skills are just string names — no implementation, no structure, no execution logic
- The proposer generates changes from scratch every time, with no structured guidance

## Target Architecture

### Skill = Executable Optimization Knowledge

```python
@dataclass
class Skill:
    """An executable optimization strategy."""
    name: str
    version: int
    description: str
    category: str                    # "routing", "safety", "latency", "quality", "cost"
    platform: str                    # "universal", "cx-agent-studio", "vertex-ai"
    
    # What this skill knows how to optimize
    target_surfaces: list[str]       # ["instructions.retrieval_agent", "routing.rules"]
    
    # Mutation templates — structured guidance for the proposer
    mutations: list[MutationTemplate]
    
    # Before/after examples — few-shot guidance
    examples: list[SkillExample]
    
    # Guardrails — what NOT to do
    guardrails: list[str]
    
    # Success criteria — how to evaluate if the skill worked
    eval_criteria: list[EvalCriterion]
    
    # Trigger conditions — when to apply this skill
    triggers: list[TriggerCondition]
    
    # Metadata
    author: str
    tags: list[str]
    created_at: float
    proven_improvement: float | None  # Average improvement when applied (learned)
    times_applied: int
    success_rate: float              # How often this skill improves scores
```

### MutationTemplate — Structured Proposer Guidance

```python
@dataclass
class MutationTemplate:
    """A templated mutation that a skill knows how to perform."""
    name: str
    mutation_type: str               # "keyword_expansion", "instruction_edit", "threshold_change", etc.
    target_surface: str              # "routing.rules[billing_agent].keywords"
    description: str
    template: str | None             # Optional template string with {placeholders}
    parameters: dict[str, Any]       # Default parameters for this mutation
```

### SkillExample — Before/After Knowledge

```python
@dataclass  
class SkillExample:
    """A proven before/after pair showing what good looks like."""
    name: str
    surface: str
    before: str | dict
    after: str | dict
    improvement: float               # Score improvement this example produced
    context: str                     # When/why this example was effective
```

### TriggerCondition — When to Apply

```python
@dataclass
class TriggerCondition:
    """Condition that suggests this skill should be applied."""
    failure_family: str | None       # "routing_error", "safety_violation", etc.
    metric_name: str | None          # "safety_violation_rate", "avg_latency_ms"
    threshold: float | None          # Apply when metric exceeds this
    operator: str                    # "gt", "lt", "eq"
    blame_pattern: str | None        # Regex match against blame map output
```

### EvalCriterion — Success Measurement

```python
@dataclass
class EvalCriterion:
    """How to measure if a skill application succeeded."""
    metric: str
    target: float
    operator: str                    # "gt", "lt"
    weight: float                    # Importance relative to other criteria
```

## What to Build

### 1. Core Skill Types (`registry/skill_types.py`)
All the dataclasses above. Clean, well-documented, with `to_dict()`/`from_dict()` serialization.

### 2. Skill Store (`registry/skill_store.py`)
SQLite-backed store for skills with:
- `register(skill)` — add or update a skill
- `get(name, version=None)` — get a skill by name (latest version or specific)
- `search(query, category=None, platform=None)` — fuzzy search
- `list(category=None, platform=None, tags=None)` — filtered listing
- `recommend(failure_family, metrics)` — given a failure pattern, recommend skills
- `record_outcome(skill_name, improvement, success)` — track skill effectiveness
- `top_performers(n=10)` — skills ranked by proven_improvement * success_rate

### 3. Builtin Skill Packs (`registry/packs/`)
Create a directory of YAML-defined skill packs:

**Universal Pack** (`registry/packs/universal.yaml`) — 10 skills:
1. `keyword_expansion` — Expand routing keywords based on failure patterns
2. `instruction_hardening` — Strengthen instructions with explicit do/don't rules  
3. `fewshot_optimization` — Add/refine few-shot examples from successful conversations
4. `safety_guardrail_tightening` — Add confidential data patterns, refusal templates
5. `tool_timeout_tuning` — Optimize tool timeouts based on p95 latency data
6. `retry_policy_optimization` — Add/tune retry with backoff for flaky tools
7. `context_pruning` — Reduce context window usage without losing quality
8. `response_compression` — Tighten response length while maintaining helpfulness
9. `routing_disambiguation` — Add disambiguation rules for ambiguous intents
10. `handoff_schema_refinement` — Improve agent-to-agent handoff fidelity

**CX Agent Studio Pack** (`registry/packs/cx_agent_studio.yaml`) — 5 skills:
1. `cx_playbook_instruction_tuning` — Optimize CX playbook instruction format
2. `cx_flow_route_optimization` — Improve Dialogflow CX flow routing
3. `cx_generator_prompt_tuning` — Tune CX generator prompts
4. `cx_entity_extraction_improvement` — Refine entity type definitions
5. `cx_webhook_latency_reduction` — Optimize webhook/fulfillment latency

Each skill YAML:
```yaml
name: keyword_expansion
version: 1
description: Expand routing keywords based on failure analysis
category: routing
platform: universal
target_surfaces:
  - routing.rules.*.keywords
mutations:
  - name: add_missing_keywords
    mutation_type: keyword_expansion
    target_surface: routing.rules.{agent}.keywords
    description: Add semantically related keywords to reduce routing misses
    template: "Analyze misrouted conversations and identify keywords that should route to {agent}"
    parameters:
      max_keywords_to_add: 10
      require_semantic_similarity: true
examples:
  - name: billing_keyword_fix
    surface: routing.rules[billing_agent].keywords
    before: ["billing", "account", "subscription"]
    after: ["billing", "account", "subscription", "invoice", "charge", "refund", "payment", "receipt", "credit"]
    improvement: 0.12
    context: "40% of billing queries were misrouted because keywords missed common billing terms"
guardrails:
  - Never remove existing working keywords
  - Keep total keywords under 30 per agent to avoid false positives
  - Verify new keywords don't overlap with other agents' keywords
eval_criteria:
  - metric: routing_accuracy
    target: 0.85
    operator: gt
    weight: 1.0
triggers:
  - failure_family: routing_error
    metric_name: routing_accuracy
    threshold: 0.85
    operator: lt
author: autoagent-builtin
tags: [routing, keywords, core]
```

### 4. Skill Loader (`registry/skill_loader.py`)
Load skills from YAML files and register them:
- `load_pack(path)` — load a YAML pack file, return list of Skills
- `install_pack(path, store)` — load and register all skills from a pack
- `install_builtin_packs(store)` — install universal + cx packs
- `export_skill(skill, path)` — export a skill to YAML for sharing

### 5. Proposer Integration (`optimizer/skill_proposer.py`)
A skill-aware proposer that wraps the existing proposer:
- Before generating a proposal, query the skill store for relevant skills
- Include skill mutations, examples, and guardrails in the LLM context
- After a successful optimization, call `record_outcome()` to track effectiveness
- Prefer skills with high `proven_improvement` and `success_rate`

This does NOT replace the existing proposer — it wraps it with skill context.

### 6. Skill Learning (`registry/skill_learner.py`)
When an optimization succeeds:
- Analyze the config diff to identify what changed
- Match the change pattern against existing skills
- If no match: create a DRAFT skill from the successful change
- If match: update the skill's `times_applied`, `success_rate`, and `proven_improvement`
- Draft skills require human approval before becoming active (`status: draft|active|deprecated`)

### 7. CLI Commands
```
autoagent skill list [--category routing] [--platform cx-agent-studio]
autoagent skill show <name> [--version N]
autoagent skill recommend                    # Recommend skills based on current failures
autoagent skill apply <name>                 # Apply a skill (run 1 optimization cycle guided by this skill)
autoagent skill install <path>               # Install a skill pack from YAML
autoagent skill export <name> [--output FILE]
autoagent skill stats                        # Show skill effectiveness leaderboard
autoagent skill learn                        # Analyze recent optimizations and create draft skills
```

### 8. API Endpoints
```
GET    /api/skills                           # List skills
GET    /api/skills/{name}                    # Get skill detail
GET    /api/skills/recommend                 # Get recommendations for current state
POST   /api/skills/{name}/apply              # Apply a skill (triggers optimization)
GET    /api/skills/stats                     # Skill effectiveness leaderboard
POST   /api/skills/install                   # Install from YAML upload
```

### 9. Web Console Page (`web/src/pages/Skills.tsx`)
A skills marketplace-style page:
- Grid of skill cards with: name, category badge, success rate, times applied, proven improvement
- Filter by category (routing, safety, latency, quality, cost) and platform
- Click a skill → detail view with mutations, examples, guardrails, performance history
- "Apply" button on each skill → confirmation modal → triggers optimization
- "Recommended" section at top based on current failure patterns
- Skill effectiveness chart (sparkline showing improvement over time)

### 10. Update Dependency Layers
`registry/skill_types.py`, `registry/skill_store.py`, `registry/skill_loader.py`, `registry/skill_learner.py` are Layer 1 (advanced).
`optimizer/skill_proposer.py` is Layer 1.
Update `tests/test_dependency_layers.py` accordingly.

## Implementation Tracks for Sub-Agents

**Track A — Types + Store**: `registry/skill_types.py`, `registry/skill_store.py`, `tests/test_skill_store.py`
**Track B — Packs + Loader**: `registry/packs/universal.yaml`, `registry/packs/cx_agent_studio.yaml`, `registry/skill_loader.py`, `tests/test_skill_loader.py`
**Track C — Proposer + Learner**: `optimizer/skill_proposer.py`, `registry/skill_learner.py`, `tests/test_skill_proposer.py`, `tests/test_skill_learner.py`
**Track D — CLI + API**: CLI commands in `runner.py`, `api/routes/skills.py`, `tests/test_skills_api.py`
**Track E — Web Console**: `web/src/pages/Skills.tsx`, `web/src/lib/types.ts` additions, `web/src/lib/api.ts` hooks

## Quality Bar
- `python3 -m pytest tests/ -x -q` — must pass with MORE tests than current
- `cd web && npx tsc --noEmit` — must pass
- `python3 -m pytest tests/test_dependency_layers.py -v` — must pass
- Builtin packs must load without errors
- `autoagent skill list` must show all 15 builtin skills
- `autoagent skill recommend` must return relevant skills based on failure state

## When Done
Commit: `feat: executable skills registry — types, store, packs, proposer integration, skill learning, CLI/API/web`
Push to master.
Run: `openclaw system event --text "Done: executable skills registry — 15 builtin skills, proposer integration, skill learning" --mode now`
