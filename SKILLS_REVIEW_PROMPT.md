# Skills as Core Product Primitive — Review & Elevation

## Context
Skills are supposed to be a CORE PRIMITIVE of AutoAgent — not a side feature. They exist in two forms:
- **Build-time skills**: Encode HOW to optimize (mutations, triggers, eval criteria, guardrails, examples)
- **Run-time skills**: Encode WHAT agents can do (tools, instructions, policies, dependencies, test cases)

Read these files first to understand current state:
- `core/skills/` — types, store, loader, composer, validator, marketplace (7 files)
- `optimizer/skill_engine.py` — how skills feed into optimization
- `agent/skill_runtime.py` — how skills execute at runtime
- `cli/skills.py` — CLI commands for skills
- `api/` — find skill-related API routes
- `web/src/pages/` — find skill-related web pages (Skills.tsx, Marketplace?)
- `registry/` — the older registry system (skills, runbooks, contracts)
- `assistant/` — does the assistant builder use skills?
- `SKILLS_ARCHITECTURE_PROMPT.md` or similar docs if they exist

## Goals

### 1. Architecture Audit
- Is `core/skills/` actually used everywhere it should be? Trace imports across the codebase.
- Is there duplication between `core/skills/store.py` and `registry/store.py`? Should registry be merged into or replaced by skills?
- Does `optimizer/skill_engine.py` properly integrate with the optimization loop? Or is it disconnected?
- Does `agent/skill_runtime.py` actually get invoked during agent execution?
- Are skills wired into the Assistant builder flow? When someone builds an agent via prompt, do skills get attached?

### 2. Skills in the Optimization Loop
This is the most important integration. Verify:
- When the optimizer searches for improvements, does it consider skill-based mutations?
- Do skills have triggers that fire based on trace patterns?
- Can the optimizer learn new skills from successful optimizations (skill learning loop)?
- Are skill guardrails enforced during optimization?
- Do experiment cards reference which skills were applied?

### 3. Skills in the Agent Runtime
- When an agent runs, does it load its assigned skills?
- Do run-time skills provide tools/instructions that shape agent behavior?
- Can skills be hot-swapped without redeploying the agent?
- Are skill dependencies resolved correctly?

### 4. Skills in the UI
Skills should be PROMINENT in the web console:
- Is there a dedicated Skills page? Is it in the sidebar navigation?
- Can users browse, search, and install skills from the marketplace?
- Can users create custom skills?
- Do experiment cards show which skills contributed to improvements?
- Does the Assistant builder suggest relevant skills?
- Is the Skills page visually polished (not a placeholder)?

### 5. Skills in CX Agent Studio
- Can skills be exported to CX Agent Studio? (as playbooks, tools, generators)
- Can CX Agent Studio configurations be imported as skills?
- Is there a mapping between skill types and CX concepts?

### 6. Skills in the CLI
- `autoagent skills list` — works?
- `autoagent skills install <name>` — works?
- `autoagent skills create` — works?
- `autoagent skills validate` — works?
- Are YAML skill packs loadable?

### 7. Elevation Plan
After auditing, create a numbered plan to:
1. Fix any broken or disconnected integrations
2. Ensure skills flow through: Builder → Optimizer → Evaluator → Deployer → Runtime
3. Make skills prominent in the UI (sidebar placement, dedicated page quality)
4. Wire skills into the Ghostwriter-competitive features (prompt-to-agent should suggest/attach skills, autonomous loop should use skill mutations)
5. Ensure test coverage for all skill pathways

### 8. After All Changes
1. Run full test suite: `cd tests && python -m pytest -x -q`
2. Fix any failures
3. Commit with message: `feat: elevate skills as core primitive — integration hardening, UI prominence, optimizer wiring`
4. Push to master
