# UX Overhaul — Implementation Plan

## Executive Summary

Three features that transform AutoAgent from a research tool into an intuitive product:
1. **Hide Algorithms, Expose Objectives** — Standard/Advanced/Research modes replace algorithm jargon
2. **Playbooks + AUTOAGENT.md** — Uplevel registry into user-facing playbooks with persistent project memory
3. **Reviewable Change Cards** — Git-like diff experience for every optimization proposal

---

## Architecture: How Features Interact

```
AUTOAGENT.md (project memory)
    ↓ read at cycle start
ModeRouter (standard/advanced/research)
    ↓ selects strategy + model routing
Optimizer Loop
    ↓ generates candidates
ChangeCard (wraps ExperimentCard)
    ↓ human reviews
Playbooks (inform AutoFix proposals)
```

- **AUTOAGENT.md → ModeRouter**: Business constraints in AUTOAGENT.md auto-populate guardrails for mode routing
- **AUTOAGENT.md → ChangeCard**: "WHY" reasoning references project memory context
- **Playbooks → AutoFix**: AutoFix suggests relevant playbooks when proposing fixes
- **Modes → ChangeCard**: Metric labels in change cards use new hierarchy (Guardrails/Objectives/Constraints/Diagnostics)

---

## Feature 1: Hide Algorithms, Expose Objectives

### New Files

| File | Purpose |
|------|---------|
| `optimizer/mode_router.py` | Maps (mode, objective, guardrails) → internal SearchStrategy + algorithm config |
| `optimizer/model_routing.py` | Phase-aware model selection (diagnosis/search/eval phases) |

### Modified Files

| File | Changes |
|------|---------|
| `agent/config/runtime.py` | Add `OptimizationConfig` with mode/objective/guardrails/budget/autonomy/allowed_surfaces; keep old fields for backwards compat |
| `optimizer/loop.py` | Accept mode from config, call ModeRouter to resolve strategy before dispatching |
| `optimizer/search.py` | No changes to internals — ModeRouter wraps existing SearchStrategy enum |
| `core/types.py` | Rename MetricLayer display names: HARD_GATE→"Guardrails", OUTCOME→"Objectives", SLO→"Constraints", DIAGNOSTIC→"Diagnostics" |
| `runner.py` | Add `--mode` flag to `optimize` command, deprecation warning for `--strategy`, add `config migrate` subcommand |
| `api/routes/optimize.py` | Accept mode in optimize request |
| `api/server.py` | Pass mode/routing config to Optimizer initialization |
| `web/src/pages/Optimize.tsx` | Mode selector (Standard/Advanced/Research), objective+guardrails form |

### Mode → Strategy Mapping

```python
MODE_STRATEGY_MAP = {
    "standard": SearchStrategy.SIMPLE,    # BootstrapFewShot, conservative
    "advanced": SearchStrategy.ADAPTIVE,  # MIPROv2, Bayesian optimization
    "research": SearchStrategy.FULL,      # HSO + GEPA + SIMBA + Pareto
}
```

### Config Migration (backwards compat)

Old config (`search_strategy: adaptive`) still works. New config (`optimization.mode: advanced`) is preferred. `autoagent config migrate` converts:
- `simple` → `standard`
- `adaptive` → `advanced`
- `full` / `pro` → `research`

### Model Routing (internal)

```python
class PhaseRouter:
    """Select models by optimization phase."""
    PHASES = {
        "diagnosis": {"prefer": "reasoning", "fallback": "default"},
        "search":    {"prefer": "fast", "fallback": "default"},
        "eval":      {"prefer": "pinned", "fallback": "default"},  # hash-locked versions
    }
```

### Metric Relabeling

Display-only change. `MetricLayer` enum values unchanged. Add `display_name` property:
- `HARD_GATE` → "Guardrails"
- `OUTCOME` → "Objectives"
- `SLO` → "Constraints"
- `DIAGNOSTIC` → "Diagnostics"

---

## Feature 2: Playbooks + AUTOAGENT.md

### New Files

| File | Purpose |
|------|---------|
| `registry/playbooks.py` | Playbook model + SQLite-backed PlaybookStore |
| `core/project_memory.py` | Load/save/update AUTOAGENT.md; structured sections parser |
| `api/routes/playbooks.py` | `/api/playbooks/` CRUD |
| `api/routes/memory.py` | `/api/memory/` read/update |
| `web/src/pages/Playbooks.tsx` | Playbook browser (replaces Registry as default) |
| `web/src/pages/ProjectMemory.tsx` | AUTOAGENT.md viewer/editor |

### Modified Files

| File | Changes |
|------|---------|
| `registry/store.py` | Add `playbooks` table to `_TABLES` |
| `runner.py` | Add `playbook` subgroup (list/show/apply/create), `memory` subgroup (show/edit/add), update `init` to generate AUTOAGENT.md |
| `optimizer/loop.py` | Load AUTOAGENT.md at cycle start, pass context to proposers |
| `optimizer/autofix.py` | Reference playbooks when suggesting fixes |
| `api/server.py` | Initialize PlaybookStore + ProjectMemory on startup |
| `web/src/App.tsx` | Add `/playbooks` and `/memory` routes |
| `web/src/components/Layout.tsx` | Rename "Registry" nav → "Playbooks" (keep Registry as sub-item) |

### Playbook Model

```python
@dataclass
class Playbook:
    name: str
    description: str
    version: int
    tags: list[str]
    skills: list[str]        # references to skill registry names
    policies: list[str]      # references to policy registry names
    tool_contracts: list[str] # references to tool contract names
    triggers: list[dict]     # failure_family, root_cause, blame_cluster
    surfaces: list[str]      # what config surfaces this playbook modifies
    metadata: dict
```

### Built-in Starter Playbooks (6)

1. `fix-retrieval-grounding` — RAG quality + hallucination reduction
2. `reduce-tool-latency` — Tool timeout and retry optimization
3. `tighten-safety-policy` — Safety guardrail enforcement
4. `improve-routing-accuracy` — Agent routing precision
5. `optimize-cost-efficiency` — Token/cost reduction without quality loss
6. `enhance-few-shot-examples` — Few-shot example curation

### AUTOAGENT.md Structure

```markdown
# AUTOAGENT.md — Project Memory

## Agent Identity
## Business Constraints
## Known Good Patterns
## Known Bad Patterns
## Team Preferences
## Optimization History
```

Generated on `autoagent init` with template-appropriate defaults. Sections are parsed as structured data for optimizer context.

### Integration with Optimizer

```python
# In optimizer/loop.py optimize():
memory = ProjectMemory.load()
if memory:
    # Pass known bad patterns to avoid repeating mistakes
    proposer.set_avoid_patterns(memory.known_bad_patterns)
    # Pass business constraints as guardrails
    if memory.business_constraints:
        self.immutable_surfaces |= memory.get_immutable_surfaces()
```

---

## Feature 3: Reviewable Change Cards

### New Files

| File | Purpose |
|------|---------|
| `optimizer/change_card.py` | ProposedChangeCard model + store + rendering (terminal/dict/markdown) |
| `optimizer/sandbox.py` | Isolated workspace per candidate (temp dir, clean config copy, cleanup) |
| `optimizer/diff_engine.py` | YAML-aware unified diff, hunk-level operations, color terminal output |
| `api/routes/changes.py` | `/api/changes/` CRUD + hunks + export |
| `web/src/pages/ChangeReview.tsx` | GitHub PR-like review interface |

### Modified Files

| File | Changes |
|------|---------|
| `optimizer/loop.py` | Wrap accepted candidates as ProposedChangeCard |
| `optimizer/autofix.py` | Generate ProposedChangeCards instead of raw proposals |
| `runner.py` | Add `review` subcommand (list/show/apply/reject/edit/export) |
| `api/server.py` | Initialize ChangeCardStore on startup |
| `web/src/App.tsx` | Add `/changes` route |
| `web/src/components/Layout.tsx` | Add "Changes" nav item |

### ProposedChangeCard Model

```python
@dataclass
class ProposedChangeCard:
    card_id: str
    title: str
    why: str                          # Plain English reasoning
    diff: list[DiffHunk]              # Unified diff hunks
    metrics_before: dict[str, float]
    metrics_after: dict[str, float]
    metrics_by_slice: dict[str, dict[str, float]]
    confidence: ConfidenceInfo        # p_value, effect_size, judge_agreement
    risk_class: str
    cost_delta: float
    latency_delta: float
    rollout_plan: str
    rollback_condition: str
    experiment_card_id: str           # Link to underlying ExperimentCard
    status: str                       # pending, applied, rejected
    created_at: float
    # AUTOAGENT.md context used in reasoning
    memory_context: str | None
```

### DiffHunk Model

```python
@dataclass
class DiffHunk:
    hunk_id: str
    surface: str              # e.g., "instructions.returns_agent"
    old_value: str
    new_value: str
    status: str               # pending, accepted, rejected
```

### Sandbox Isolation

```python
class CandidateSandbox:
    """Isolated workspace for candidate evaluation."""

    def __init__(self, baseline_config: dict):
        self.work_dir = tempfile.mkdtemp(prefix="autoagent_sandbox_")
        self._save_baseline(baseline_config)

    def apply_mutation(self, mutation: dict) -> dict:
        """Apply mutation in sandbox, return modified config."""

    def compute_diff(self) -> list[DiffHunk]:
        """YAML-aware diff between baseline and candidate."""

    def cleanup(self):
        """Remove sandbox directory."""
```

### CLI Experience

```
$ autoagent review
┌─────────────────────────────────────────────────────┐
│ 3 pending changes                                    │
├─────────────────────────────────────────────────────┤
│ #1 Improve returns flow instructions     [low risk]  │
│ #2 Optimize tool description clarity     [low risk]  │
│ #3 Swap model for cost efficiency        [med risk]  │
└─────────────────────────────────────────────────────┘

$ autoagent review abc123
[Full change card with diff, metrics, confidence]

$ autoagent review abc123 --apply
Applied change abc123. Rollout: 2h canary → auto-promote.
```

---

## Backwards Compatibility Strategy

| Component | Backwards Compat Approach |
|-----------|--------------------------|
| `search_strategy` config | Still works — ModeRouter falls back to direct strategy lookup |
| `--strategy` CLI flag | Deprecated with warning, maps to `--mode` internally |
| `autoagent registry` commands | Still work, documented as "advanced" |
| `/api/registry/*` endpoints | Still work, playbooks endpoints added alongside |
| `ExperimentCard` | Still exists, ChangeCard wraps it |
| Old `autoagent.yaml` format | Parsed alongside new `optimization:` section |
| `MetricLayer` enum values | Unchanged — only display names change |

---

## User Journeys

### Journey 1: PM Sets Up Optimization (Feature 1)

```
$ autoagent init
→ Creates AUTOAGENT.md with template
→ "Edit AUTOAGENT.md with your agent's identity and constraints"

$ cat autoagent.yaml
optimization:
  mode: standard
  objective: "Maximize task success while keeping latency under 3s"
  guardrails:
    - "Safety score must stay at 1.0"
  budget:
    per_cycle: 1.0
  autonomy: supervised

$ autoagent optimize
→ "Mode: Standard | Objective: Maximize task success..."
→ Runs conservative BootstrapFewShot optimization
→ Generates ProposedChangeCard

$ autoagent review
→ Shows readable change card with why/what/metrics
```

### Journey 2: Team Lead Applies Playbook (Feature 2)

```
$ autoagent playbook list
  fix-retrieval-grounding     Improve RAG quality, reduce hallucination
  reduce-tool-latency         Optimize tool timeout and retry settings
  tighten-safety-policy       Enforce safety guardrails
  ...

$ autoagent playbook show fix-retrieval-grounding
  Skills: retrieval_query_rewriting, context_relevance_filtering
  Policies: no_hallucination_policy, citation_required_policy
  Triggers: quality_degradation + retrieval_quality root cause

$ autoagent playbook apply fix-retrieval-grounding
  Applied playbook. 2 skills, 2 policies registered.
  Run 'autoagent optimize' to evaluate impact.
```

### Journey 3: Engineer Reviews Change (Feature 3)

```
$ autoagent review abc123
┌──────────────────────────────────────────────┐
│ Proposed Change: Improve returns flow        │
│ WHY: Blame map shows 62% quality regression  │
│      AUTOAGENT.md notes returns = highest    │
│      impact surface.                         │
│                                              │
│ WHAT CHANGES:                                │
│  instructions.returns_agent                  │
│  - "Handle customer returns and refunds"     │
│  + "Handle customer returns and refunds.     │
│  +  Always verify order ID..."               │
│                                              │
│ Objectives:  Task Success 0.72 → 0.81 (+12%)│
│ Guardrails:  Safety 1.00 → 1.00 ✓           │
│ Constraints: Latency 2.1s → 2.3s            │
│ Confidence:  p=0.003, effect=0.125           │
│                                              │
│ [Apply] [Reject] [Edit] [Export]             │
└──────────────────────────────────────────────┘

$ autoagent review abc123 --apply
Applied. Rollout: 2h canary → auto-promote if metrics hold.
```

---

## Execution Plan

### Agent 1: Feature 1 Backend
- `optimizer/mode_router.py` — ModeRouter class, mode→strategy mapping, objective parsing
- `optimizer/model_routing.py` — PhaseRouter class, phase-aware model selection
- `agent/config/runtime.py` — Add OptimizationConfig to RuntimeConfig
- `core/types.py` — Add display_name to MetricLayer
- Config migration utility function

### Agent 2: Feature 2 Backend
- `registry/playbooks.py` — Playbook model + PlaybookStore
- `core/project_memory.py` — ProjectMemory class, AUTOAGENT.md parser/writer
- `registry/store.py` — Add playbooks table
- 6 built-in starter playbooks (YAML definitions)
- Integration hooks in optimizer/loop.py and autofix.py

### Agent 3: Feature 3 Backend
- `optimizer/change_card.py` — ProposedChangeCard + ChangeCardStore + rendering
- `optimizer/sandbox.py` — CandidateSandbox isolation
- `optimizer/diff_engine.py` — YAML-aware diff + DiffHunk operations
- Integration with optimizer/loop.py (wrap candidates as change cards)

### Agent 4: CLI + API
- `runner.py` — Add review, playbook, memory subcommands; update optimize with --mode; add config migrate; update init for AUTOAGENT.md
- `api/routes/changes.py` — Change card CRUD + hunks + export
- `api/routes/playbooks.py` — Playbook CRUD
- `api/routes/memory.py` — Project memory read/update
- `api/server.py` — Initialize new stores
- `api/models.py` — New request/response models

### Agent 5: Web Pages
- `web/src/pages/ChangeReview.tsx` — Change card review (PR-like)
- `web/src/pages/Playbooks.tsx` — Playbook browser
- `web/src/pages/ProjectMemory.tsx` — AUTOAGENT.md editor
- Update Optimize.tsx — Mode selector
- Update App.tsx, Layout.tsx — New routes and nav

### Agent 6: Tests
- Tests for all new modules (target 80+ new tests)
- Integration tests for mode→strategy routing
- Integration tests for playbook apply flow
- Integration tests for change card lifecycle

---

## File Inventory (New Files)

```
optimizer/mode_router.py          # Feature 1
optimizer/model_routing.py        # Feature 1
registry/playbooks.py             # Feature 2
core/project_memory.py            # Feature 2
registry/starter_playbooks/       # Feature 2 (6 YAML files)
optimizer/change_card.py          # Feature 3
optimizer/sandbox.py              # Feature 3
optimizer/diff_engine.py          # Feature 3
api/routes/changes.py             # Feature 3 API
api/routes/playbooks.py           # Feature 2 API
api/routes/memory.py              # Feature 2 API
web/src/pages/ChangeReview.tsx    # Feature 3 Web
web/src/pages/Playbooks.tsx       # Feature 2 Web
web/src/pages/ProjectMemory.tsx   # Feature 2 Web
tests/test_mode_router.py         # Feature 1 Tests
tests/test_model_routing.py       # Feature 1 Tests
tests/test_playbooks.py           # Feature 2 Tests
tests/test_project_memory.py      # Feature 2 Tests
tests/test_change_card.py         # Feature 3 Tests
tests/test_sandbox.py             # Feature 3 Tests
tests/test_diff_engine.py         # Feature 3 Tests
tests/test_review_cli.py          # CLI Tests
tests/test_changes_api.py         # API Tests
tests/test_playbooks_api.py       # API Tests
tests/test_memory_api.py          # API Tests
```

## Done Criteria

- [ ] All three features have backend, CLI, API, and web
- [ ] 80+ new tests, total 1200+
- [ ] Full test suite passes
- [ ] Old configs/commands still work (backwards compat verified)
- [ ] AUTOAGENT.md template generated on `autoagent init`
- [ ] `autoagent review` shows beautiful terminal output
- [ ] Metric labels use new hierarchy in all user-facing output
