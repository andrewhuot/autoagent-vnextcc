# Executable Skills Registry — Implementation Plan

## Architecture Overview

The skills registry upgrades AutoAgent's skills from string names to executable optimization strategies. Skills become the core knowledge unit — code + knowledge that the optimizer consults before proposing changes.

**New files**: `registry/skill_types.py`, `registry/skill_store.py`, `registry/skill_loader.py`, `registry/skill_learner.py`, `optimizer/skill_proposer.py`, `registry/packs/universal.yaml`, `registry/packs/cx_agent_studio.yaml`, `api/routes/skills.py`, `web/src/pages/Skills.tsx`

**Modified files**: `registry/__init__.py`, `api/server.py`, `api/routes/__init__.py`, `web/src/App.tsx`, `web/src/components/Sidebar.tsx`, `web/src/lib/types.ts`, `web/src/lib/api.ts`, `tests/test_dependency_layers.py`, `runner.py`

## Conflict Resolution

- **`registry/skills.py`** (existing): The old `SkillRegistry` wraps generic `RegistryStore` CRUD for simple name+instructions skills. It stays untouched. The new `skill_store.py` is a separate, purpose-built store for executable skills with its own table `executable_skills`.
- **`registry/store.py`** existing `skills` table: Used by the old `SkillRegistry`. New `SkillStore` creates its own `executable_skills` table + `skill_outcomes` table.
- **Dependency layers**: `registry` is already Layer 1. New modules (`registry.skill_types`, `registry.skill_store`, `registry.skill_loader`, `registry.skill_learner`) are covered by the existing `registry` prefix. `optimizer.skill_proposer` needs to be added to LAYER_1_PREFIXES.

---

## Track A: Types + Store

### `registry/skill_types.py` — Dataclasses

```python
@dataclass
class MutationTemplate:
    name: str
    mutation_type: str          # "keyword_expansion", "instruction_edit", etc.
    target_surface: str         # "routing.rules[billing_agent].keywords"
    description: str
    template: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MutationTemplate: ...

@dataclass
class SkillExample:
    name: str
    surface: str
    before: str | dict
    after: str | dict
    improvement: float
    context: str

    def to_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillExample: ...

@dataclass
class TriggerCondition:
    failure_family: str | None = None
    metric_name: str | None = None
    threshold: float | None = None
    operator: str = "gt"
    blame_pattern: str | None = None

    def to_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TriggerCondition: ...

@dataclass
class EvalCriterion:
    metric: str
    target: float
    operator: str = "gt"
    weight: float = 1.0

    def to_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalCriterion: ...

@dataclass
class Skill:
    name: str
    version: int
    description: str
    category: str               # "routing", "safety", "latency", "quality", "cost"
    platform: str               # "universal", "cx-agent-studio", "vertex-ai"
    target_surfaces: list[str]
    mutations: list[MutationTemplate]
    examples: list[SkillExample]
    guardrails: list[str]
    eval_criteria: list[EvalCriterion]
    triggers: list[TriggerCondition]
    author: str = "autoagent-builtin"
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    proven_improvement: float | None = None
    times_applied: int = 0
    success_rate: float = 0.0
    status: str = "active"      # "active", "draft", "deprecated"

    def to_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Skill: ...
```

### `registry/skill_store.py` — SQLite Store

```sql
CREATE TABLE IF NOT EXISTS executable_skills (
    name       TEXT    NOT NULL,
    version    INTEGER NOT NULL,
    data       TEXT    NOT NULL,   -- JSON blob of Skill.to_dict()
    category   TEXT    NOT NULL,
    platform   TEXT    NOT NULL,
    status     TEXT    NOT NULL DEFAULT 'active',
    created_at TEXT    NOT NULL,
    PRIMARY KEY (name, version)
);

CREATE TABLE IF NOT EXISTS skill_outcomes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name  TEXT    NOT NULL,
    improvement REAL    NOT NULL,
    success     INTEGER NOT NULL,  -- 0 or 1
    recorded_at TEXT    NOT NULL
);
```

```python
class SkillStore:
    def __init__(self, db_path: str = "registry.db") -> None: ...
    def register(self, skill: Skill) -> tuple[str, int]: ...
    def get(self, name: str, version: int | None = None) -> Skill | None: ...
    def search(self, query: str, category: str | None = None, platform: str | None = None) -> list[Skill]: ...
    def list(self, category: str | None = None, platform: str | None = None, tags: list[str] | None = None, status: str | None = None) -> list[Skill]: ...
    def recommend(self, failure_family: str | None = None, metrics: dict[str, float] | None = None) -> list[Skill]: ...
    def record_outcome(self, skill_name: str, improvement: float, success: bool) -> None: ...
    def top_performers(self, n: int = 10) -> list[Skill]: ...
    def close(self) -> None: ...
```

### Test: `tests/test_skill_store.py`
- test_register_and_get
- test_list_by_category
- test_list_by_platform
- test_search
- test_recommend_by_failure_family
- test_recommend_by_metric
- test_record_outcome_updates_stats
- test_top_performers
- test_version_increment
- test_skill_serialization_roundtrip

---

## Track B: YAML Packs + Loader

### `registry/packs/universal.yaml` — 10 skills
### `registry/packs/cx_agent_studio.yaml` — 5 skills

Each follows the YAML structure from the brief.

### `registry/skill_loader.py`

```python
def load_pack(path: str | Path) -> list[Skill]: ...
def install_pack(path: str | Path, store: SkillStore) -> int: ...
def install_builtin_packs(store: SkillStore) -> int: ...
def export_skill(skill: Skill, path: str | Path) -> None: ...
```

### Test: `tests/test_skill_loader.py`
- test_load_universal_pack (10 skills)
- test_load_cx_pack (5 skills)
- test_install_builtin_packs (15 total)
- test_export_and_reimport_roundtrip
- test_install_idempotent

---

## Track C: Proposer Integration + Learner

### `optimizer/skill_proposer.py`

```python
class SkillAwareProposer:
    """Wraps the existing Proposer with skill context."""
    def __init__(self, proposer: Proposer, skill_store: SkillStore) -> None: ...
    def propose(self, current_config, health_metrics, failure_samples, failure_buckets, past_attempts, **kwargs) -> Proposal | None: ...
    def _get_relevant_skills(self, failure_buckets, health_metrics) -> list[Skill]: ...
    def _build_skill_context(self, skills: list[Skill]) -> dict[str, Any]: ...
    def record_outcome(self, skill_name: str, improvement: float, success: bool) -> None: ...
```

### `registry/skill_learner.py`

```python
@dataclass
class DraftSkill:
    skill: Skill
    source_attempt_id: str
    confidence: float

class SkillLearner:
    def __init__(self, skill_store: SkillStore) -> None: ...
    def analyze_optimization(self, config_diff: dict, attempt: dict) -> DraftSkill | None: ...
    def match_existing_skill(self, config_section: str, change_description: str) -> Skill | None: ...
    def update_skill_stats(self, skill_name: str, improvement: float, success: bool) -> None: ...
    def learn_from_history(self, recent_attempts: list[dict]) -> list[DraftSkill]: ...
```

### Tests: `tests/test_skill_proposer.py`, `tests/test_skill_learner.py`

---

## Track D: CLI + API

### CLI: `runner.py` — new `skill` group

```
@cli.group("skill")
def skill_group(): ...

@skill_group.command("list")
@skill_group.command("show")
@skill_group.command("recommend")
@skill_group.command("apply")
@skill_group.command("install")
@skill_group.command("export")
@skill_group.command("stats")
@skill_group.command("learn")
```

### API: `api/routes/skills.py`

```python
router = APIRouter(prefix="/api/skills", tags=["skills"])

GET  /api/skills              — list skills (query params: category, platform, status)
GET  /api/skills/recommend    — recommend skills for current failures
GET  /api/skills/stats        — skill effectiveness leaderboard
GET  /api/skills/{name}       — get skill detail
POST /api/skills/{name}/apply — apply a skill
POST /api/skills/install      — install from YAML
```

### Test: `tests/test_skills_api.py`

---

## Track E: Web Console

### `web/src/pages/Skills.tsx`
- Grid of skill cards with name, category badge, success rate, times applied, proven improvement
- Filter by category and platform
- Click skill → detail with mutations, examples, guardrails
- "Apply" button → confirmation modal → triggers optimization
- "Recommended" section at top
- Sparkline for skill effectiveness

### Types added to `web/src/lib/types.ts`:
```typescript
export interface ExecutableSkill { ... }
export interface SkillMutation { ... }
export interface SkillExample { ... }
export interface SkillStats { ... }
```

### Hooks added to `web/src/lib/api.ts`:
```typescript
export function useSkills(params) { ... }
export function useSkill(name) { ... }
export function useSkillRecommendations() { ... }
export function useSkillStats() { ... }
export function useApplySkill() { ... }
```

---

## Integration Checklist

1. Wire `Skills` page into `App.tsx` route `/skills`
2. Add `Skills` nav item to `Sidebar.tsx` (Puzzle icon)
3. Register `skills` API router in `api/server.py`
4. Import `skills` in `api/routes/__init__.py`
5. Update `registry/__init__.py` to export new types
6. Add `optimizer.skill_proposer` to LAYER_1_PREFIXES in `tests/test_dependency_layers.py`
7. Call `install_builtin_packs()` in `api/server.py` lifespan
8. Initialize `SkillStore` in `api/server.py` lifespan
