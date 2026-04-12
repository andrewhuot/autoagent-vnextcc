# Harness Contract & Skills Integration — Analysis

**Date**: 2026-04-12
**Branch**: feat/harness-contract-and-skills-claude

## Current State

### AGENTLAB.md
Minimal project-memory template (agent identity, constraints, patterns). Correctly
*not* overloaded with builder behavior rules. Should remain project memory only.

### Builder/Harness Behavior (implicit, not contracted)
The builder loop lives in `builder/harness.py` (`HarnessExecutionEngine`) and
`builder/workbench_agent.py` (`LiveWorkbenchBuilderAgent`). It follows a
Plan→Execute→Reflect→Present cycle with:
- Domain inference from brief text
- Per-leaf-task execution with checkpointing
- Quality reflection after each task group
- Metrics tracking (tokens, cost, elapsed time)
- Iteration support for follow-up refinements

**Gap**: This behavior is encoded entirely in code. No contract file exists that
a builder (or operator) can read to understand the expected loop behavior,
startup sequence, persistence guarantees, completion criteria, recovery model,
or skill treatment. The implicit contract must be reverse-engineered from ~2K
lines of Python.

### Skills Model
The unified skill system (`core/skills/`) defines `SkillKind.BUILD` and
`SkillKind.RUNTIME` with a shared `Skill` dataclass. Infrastructure is mature:
- `SkillStore` (SQLite persistence)
- `SkillComposer` (multi-skill composition with conflict detection)
- `SkillValidator` (schema + dependency validation)
- `SkillRuntime` (agent/skill_runtime.py — runtime skill loading/application)
- `SkillEngine` (optimizer/skill_engine.py — build-time skill selection/application)
- `SkillLoader` (SKILL.md / YAML / pack loading)
- Full REST API (`api/routes/skills.py`)
- Frontend page (`web/src/pages/Skills.tsx`) with build/runtime tabs

**Gap**: The harness execution engine (`builder/harness.py`) has **zero awareness
of skills**. It generates artifacts using domain templates but never:
- Loads or references the skill store
- Surfaces which skill layer produced an artifact
- Includes skill context in events
- Distinguishes build-time from runtime skills during execution
- Reports active skill layer to the operator

### Shared Contracts
`shared/contracts/` has Python + TypeScript contracts for: skill-record,
build-artifact, deployment-target, experiment-record, release-object. These are
well-structured but the skill record doesn't include a `layer` or `context`
field for harness integration.

### Frontend
`Skills.tsx` has build/runtime tabs and effectiveness tracking. The Workbench
page (the main builder UI) has no skill-layer awareness — artifacts don't show
which skill layer they belong to, and there's no indicator of active skill
context during a build.

## Identified Gaps (Ranked)

| # | Gap | Impact | Fix |
|---|-----|--------|-----|
| 1 | No builder contract file | Operators can't understand or verify builder behavior | Create `BUILDER_CONTRACT.md` |
| 2 | Harness ignores skill store | Build runs don't benefit from or surface skill knowledge | Wire skill context into harness |
| 3 | Events lack skill layer | Operators can't tell if an artifact is build-time or runtime | Add `skill_layer` to events |
| 4 | Frontend has no skill context in workbench | Artifact provenance is opaque | Add skill layer badges |
| 5 | Contract is not machine-loadable | Harness can't verify its own behavior against contract | Add contract loader |

## Architecture Decisions

### Contract file naming: `BUILDER_CONTRACT.md`
- `MODEL_HARNESS.md` — ambiguous ("model" = ML model? canonical model?)
- `BUILDER.md` — too generic (could be build system docs)
- `HARNESS_CONTRACT.md` — misses the builder identity
- **`BUILDER_CONTRACT.md`** — explicit: it's the contract for the builder agent
  operating within the harness. Clear pair with `AGENTLAB.md` (project memory).

### Skill integration scope
The harness should load available skills as context, tag artifacts with their
skill layer, and include skill context in events. It should NOT automatically
apply skills or change the execution flow — that's a future concern. The goal
is visibility and truthfulness, not autonomous skill-driven mutation.
