# UX Overhaul — Three Features

## CRITICAL CONTEXT
These three features are a UX maturity leap. They transform AutoAgent from a research tool that exposes internals into a product that feels intuitive. Every decision should ask: "Would a PM or team lead understand this without reading the source code?"

Read the ENTIRE codebase before planning. Understand what exists so you can reshape it, not just bolt things on.

---

## FEATURE 1: Hide Algorithms, Expose Objectives & Guardrails

### The Problem
The product surfaces MIPROv2, GEPA, SIMBA, Pareto, anti-Goodhart, bandits, UCB1, Thompson Sampling, calibration suites — all implementation details. Users don't care about algorithm names. They care about: what am I optimizing, what can't break, how much can I spend, and how autonomous should this be.

### What To Build

**Three user-facing modes** that replace the current `search_strategy` config:

| Mode | Who it's for | What happens internally |
|------|-------------|----------------------|
| **Standard** | Most teams | Simple failure-bucket proposer + BootstrapFewShot. Conservative, predictable. |
| **Advanced** | Teams with eval maturity | Adaptive search + MIPROv2. Bayesian optimization, bandit selection. |
| **Research** | Power users, researchers | Full HSO + GEPA + SIMBA + Pareto archive. All algorithms available. |

**Objective-first configuration** — replace algorithm-centric config with goal-centric config:

```yaml
# OLD (algorithm jargon)
optimizer:
  search_strategy: adaptive
  bandit_policy: ucb1
  pro_mode:
    algorithm: miprov2
    instruction_candidates: 5

# NEW (objective-first)
optimization:
  mode: standard           # standard | advanced | research
  objective: "Maximize task success while keeping latency under 3s"
  guardrails:
    - "Safety score must stay at 1.0"
    - "Cost per conversation must stay under $0.05"
  budget:
    per_cycle: 1.0
    daily: 10.0
  autonomy: supervised     # supervised | semi-auto | autonomous
  allowed_surfaces:        # what can be changed
    - instructions
    - examples
    - tool_descriptions
```

**Autonomy levels:**
- `supervised` — suggest only, human applies every change
- `semi-auto` — auto-apply low-risk changes (instruction edits, example swaps), human reviews high-risk
- `autonomous` — auto-apply everything that passes gates + significance + canary

**Phase-aware model routing** (internal, not user-facing):
- Create `optimizer/model_routing.py`
- **Diagnosis/Planning phase**: Use best available reasoner (Gemini Pro, Claude Opus, GPT-4o)
- **Search/Execution phase**: Use cheaper/faster models (Gemini Flash, Claude Sonnet, GPT-4o-mini)
- **Evaluation/Judging phase**: Pinned model versions for consistency (hash-locked, no silent upgrades)
- This is an internal optimization — users don't configure it directly, but Advanced/Research modes can override

**CLI changes:**
- `autoagent optimize` defaults to Standard mode
- `autoagent optimize --mode advanced`
- `autoagent optimize --mode research` (exposes algorithm selection for power users)
- Old `--strategy` flag still works but is deprecated with a warning

**Config migration:**
- Old `search_strategy: simple/adaptive/full/pro` configs still work (mapped internally)
- New `optimization.mode` is the preferred path
- Write a `autoagent config migrate` command that converts old → new format

**Web changes:**
- Optimize page shows mode selector (Standard/Advanced/Research) instead of strategy dropdown
- Objective + Guardrails + Budget form instead of algorithm config
- Research mode expands to show algorithm details (progressive disclosure)

**Metric hierarchy relabeling** (4-layer stays, labels change):
- Layer 1: Hard Gates → **Guardrails** (in UI/docs/CLI output)
- Layer 2: North-Star Outcomes → **Objectives**
- Layer 3: Operating SLOs → **Constraints**
- Layer 4: Diagnostics → **Diagnostics** (unchanged)

### Implementation Notes
- The strategy routing in `optimizer/search.py` and `optimizer/loop.py` stays — just add a translation layer from mode → strategy
- `optimizer/mode_router.py` — maps (mode, objective, guardrails) → internal strategy + algorithm selection
- `optimizer/model_routing.py` — phase-aware model selection with pinned versions for eval
- Old configs must keep working (backwards compat is mandatory)
- Update `autoagent.yaml` schema to support both old and new formats

---

## FEATURE 2: Uplevel Skills Registry → Playbooks + AUTOAGENT.md

### The Problem
The registry exposes four separate registries (skills, policies, tool contracts, handoff schemas). Users don't think in those categories. They think in playbooks: "fix retrieval grounding," "reduce tool latency," "tighten refusal policy." Also, the system has no persistent project memory — it optimizes generic metrics without knowing the team's goals, constraints, and preferences.

### What To Build

**Playbooks** — the user-facing abstraction that replaces raw registry items:

```yaml
# A playbook bundles related skills, policies, and tool contracts
name: fix-retrieval-grounding
description: "Improve retrieval quality and reduce hallucination from RAG"
version: 3
tags: [retrieval, grounding, quality]

# What it includes
skills:
  - retrieval_query_rewriting
  - context_relevance_filtering
policies:
  - no_hallucination_policy
  - citation_required_policy
tool_contracts:
  - vector_search_contract
  - document_retriever_contract

# When to apply
triggers:
  - failure_family: quality_degradation
    root_cause: retrieval_quality
  - blame_cluster: "stale or irrelevant retrieved context"

# What it changes
surfaces:
  - instructions.retrieval_agent
  - examples.retrieval_queries
  - tool_descriptions.vector_search
```

- `registry/playbooks.py` — Playbook model + store (SQLite-backed)
- Playbooks are the primary user-facing unit; raw registry items still exist underneath
- Built-in starter playbooks for common patterns (5-8 included out of the box)
- CLI: `autoagent playbook list`, `autoagent playbook show <name>`, `autoagent playbook apply <name>`, `autoagent playbook create`
- API: `/api/playbooks/` CRUD
- Web: Playbook browser (replaces raw registry browser as default view)
- Progressive disclosure: playbook view by default, click "View components" to see underlying skills/policies/contracts
- AutoFix Copilot should suggest relevant playbooks when proposing fixes

**AUTOAGENT.md** — persistent project memory (like CLAUDE.md):

Create a first-class `AUTOAGENT.md` file that lives in the project root and carries across sessions:

```markdown
# AUTOAGENT.md — Project Memory

## Agent Identity
- Name: Customer Support Agent v4
- Platform: Google ADK on Vertex AI
- Primary use case: E-commerce customer support (orders, returns, shipping)

## Business Constraints
- Response latency must stay under 3 seconds (SLA)
- Safety violations are zero-tolerance (regulated industry)
- Cost per conversation budget: $0.04
- Operating hours: 24/7, English + Spanish

## Known Good Patterns
- Few-shot examples work better than long instructions for this agent
- The returns flow is the highest-impact surface (40% of conversations)
- Tool descriptions need to be very specific — vague descriptions cause wrong tool selection

## Known Bad Patterns
- Don't optimize the greeting — it's brand-mandated and immutable
- Reducing instruction length below 500 tokens causes quality regression
- The order_status tool is flaky between 2-4am UTC (upstream API maintenance)

## Team Preferences
- Prefer instruction edits over model swaps (deployment complexity)
- Always run canary for 2 hours minimum before promotion
- Never auto-deploy changes to safety-related surfaces

## Optimization History
- 2024-03-01: Fixed returns flow routing (quality +12%)
- 2024-03-05: Improved tool descriptions for order_lookup (tool accuracy +8%)
- 2024-03-10: Added few-shot examples for Spanish conversations (quality +15%)
```

Implementation:
- `core/project_memory.py` — Load/save/update AUTOAGENT.md
- Auto-generated on `autoagent init` with sensible template
- Read at start of every optimization cycle — informs mutation selection, surface targeting, constraint enforcement
- Auto-updated after successful optimizations (append to history section)
- Optimizer reads "Known Bad Patterns" to avoid repeating mistakes
- Optimizer reads "Team Preferences" to respect deployment constraints
- Optimizer reads "Business Constraints" to set guardrails automatically
- CLI: `autoagent memory show`, `autoagent memory edit`, `autoagent memory add "Returns flow is highest impact"`
- The optimizer/loop.py should load AUTOAGENT.md at cycle start and pass relevant context to proposers
- AutoFix proposals should reference AUTOAGENT.md context in their reasoning

**Registry simplification:**
- Keep the 4 underlying registries (skills, policies, tool_contracts, handoff_schemas) as implementation
- But the primary CLI/API/Web interface is playbooks
- `autoagent registry` commands still work but are documented as "advanced"
- Web sidebar: "Playbooks" replaces "Registry" as the nav item

---

## FEATURE 3: Reviewable Change Cards (Git-like Diff Experience)

### The Problem
Changes feel like "mutating YAML in a black box." ExperimentCards have 34 fields but the important information is buried. Users need a clear, reviewable change card — like a GitHub PR — for every proposed change.

### What To Build

**ProposedChangeCard** — the user-facing artifact for every optimization proposal:

```
┌─────────────────────────────────────────────────────┐
│ Proposed Change: Improve returns flow instructions  │
├─────────────────────────────────────────────────────┤
│ WHY: Blame map shows 62% of quality regressions     │
│      trace to returns flow instruction ambiguity.    │
│      AUTOAGENT.md notes returns is highest-impact.   │
│                                                      │
│ WHAT CHANGES:                                        │
│  instructions.returns_agent                          │
│  - "Handle customer returns and refunds"             │
│  + "Handle customer returns and refunds. Always      │
│  +  verify order ID before processing. Check return  │
│  +  eligibility window (30 days). Offer exchange     │
│  +  before refund."                                  │
│                                                      │
│ METRICS (before → after):                            │
│  Objectives:                                         │
│    Task Success:  0.72 → 0.81 (+12.5%)              │
│    Quality:       0.68 → 0.77 (+13.2%)              │
│  Guardrails:                                         │
│    Safety:        1.00 → 1.00 (no change) ✓         │
│  Constraints:                                        │
│    Latency p95:   2.1s → 2.3s (+9.5%)              │
│    Cost/conv:     $0.038 → $0.039 (+2.6%)           │
│                                                      │
│ BY SLICE:                                            │
│    returns_flow:    +18.2% quality                   │
│    shipping_flow:   no change                        │
│    order_flow:      no change                        │
│                                                      │
│ CONFIDENCE:                                          │
│    p-value: 0.003, effect size: 0.125               │
│    Judge agreement: 94% (3/3 judges agree)           │
│                                                      │
│ RISK: low | COST DELTA: +$0.001/conv                │
│                                                      │
│ ROLLOUT: 2h canary → auto-promote if metrics hold   │
│ ROLLBACK: Auto-rollback if safety < 1.0 or          │
│           quality drops > 5% from baseline           │
│                                                      │
│ [Apply] [Reject] [Edit] [View Full Experiment Card] │
└─────────────────────────────────────────────────────┘
```

Implementation:

- `optimizer/change_card.py` — ProposedChangeCard model
  - Fields: title, why (plain English reasoning), diff (unified diff format), metrics_before, metrics_after, metrics_by_slice, confidence (p-value, effect_size, judge_agreement), risk_class, cost_delta, latency_delta, rollout_plan, rollback_condition
  - Generated from ExperimentCard + eval results (translation layer, not replacement)
  - `to_terminal()` — rich terminal rendering for CLI
  - `to_dict()` — API serialization
  - `to_markdown()` — for sharing/documentation

- `optimizer/sandbox.py` — Isolated workspace for candidates
  - Each candidate config gets a sandbox (temp directory with clean config copy)
  - Diff computed against baseline config
  - Hunk-level granularity: individual changes within a config can be reverted independently
  - Sandbox cleanup after accept/reject

- `optimizer/diff_engine.py` — Unified diff generation
  - YAML-aware diffing (not just text diff)
  - Hunk-level operations: accept hunk, reject hunk, edit hunk
  - Inline comments: attach notes to specific changes
  - Color-coded terminal output

**CLI experience:**
- `autoagent review` — show pending change cards in terminal (rich formatting)
- `autoagent review <id>` — show specific change card with full diff
- `autoagent review <id> --apply` — apply the change
- `autoagent review <id> --reject --reason "..."` — reject with reason
- `autoagent review <id> --edit` — open diff in editor for hunk-level modifications
- `autoagent review --export <id>` — export as markdown (for sharing in PRs/docs)

**API:**
- `GET /api/changes` — list pending change cards
- `GET /api/changes/{id}` — get specific change card with full diff
- `POST /api/changes/{id}/apply` — apply
- `POST /api/changes/{id}/reject` — reject with reason
- `PATCH /api/changes/{id}/hunks` — accept/reject individual hunks
- `GET /api/changes/{id}/export` — markdown export

**Web: Change Review page**
- GitHub PR-like interface
- Split or unified diff view
- Hunk-level accept/reject buttons
- Before/after metrics side by side
- Slice-level breakdown
- Confidence visualization
- One-click apply with rollout plan
- Comment thread on changes (for team review)
- "View Full Experiment Card" expandable section (progressive disclosure)

**Integration:**
- AutoFix Copilot generates ProposedChangeCards (not raw ExperimentCards)
- The optimization loop produces change cards for every accepted candidate
- `autoagent review` is the new primary human interaction point
- ExperimentCard still exists underneath (change card wraps it)

---

## EXECUTION

Use `claude --model claude-sonnet-4-5 --dangerously-skip-permissions -p '...'` sub-agents for parallel implementation:

- Agent 1: Feature 1 backend — mode router, model routing, config migration, metric relabeling
- Agent 2: Feature 2 backend — playbooks, AUTOAGENT.md, project memory, registry simplification  
- Agent 3: Feature 3 backend — change cards, sandbox, diff engine
- Agent 4: CLI + API for all three features
- Agent 5: Web pages for all three features

Run `python3 -m pytest tests/ --tb=short -q` after each agent completes.

## DONE CRITERIA
- All three features have backend, CLI, API, and web
- All new code has tests (target: 80+ new tests, total 1200+)
- Full test suite passes
- Old configs still work (backwards compat)
- AUTOAGENT.md template generated on `autoagent init`
- `autoagent review` shows beautiful terminal output
- Git commit + push to origin master
