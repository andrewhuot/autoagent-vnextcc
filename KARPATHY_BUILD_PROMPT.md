# Karpathy-Aligned Features — Three Builds

Read `KARPATHY_ALIGNMENT.md` for full context on why these features matter.

## Feature 1: Self-Play Curriculum Generator

The optimizer should generate progressively harder eval prompts from recent failure clusters. This is the flywheel that makes AutoAgent genuinely self-improving.

### Backend (`optimizer/curriculum_generator.py`)
- `CurriculumGenerator` class that:
  - Takes recent failure clusters from `observer/` (failure traces, categories, evidence)
  - Synthesizes harder eval prompts that stress-test the failure patterns
  - Generates adversarial variants (edge cases, ambiguous inputs, multi-intent)
  - Scores difficulty based on historical pass rates
  - Outputs a `CurriculumBatch` with graded difficulty tiers (easy → medium → hard → adversarial)
- Integrate into the optimization loop: after each cycle, generate new curriculum and add to eval set
- Track curriculum evolution over time (which prompts were generated, which exposed regressions)

### CLI
- `autoagent curriculum generate` — generate a new curriculum batch from recent failures
- `autoagent curriculum list` — show generated batches with difficulty distribution
- `autoagent curriculum apply` — add a batch to the active eval set

### API
- `POST /api/curriculum/generate` — generate batch
- `GET /api/curriculum/batches` — list batches
- `POST /api/curriculum/apply` — apply to eval set

### Web UI
- Add curriculum section to the Evaluate page (or new Curriculum tab)
- Show generated prompts with difficulty badges
- "Generate Harder Tests" button
- Visualization of difficulty progression over time

## Feature 2: Draft → Active Skill Promotion Workflow

Skills auto-learned from optimizations sit as drafts. Add a human review workflow to promote them.

### Backend (`core/skills/promotion.py`)
- `SkillPromotionWorkflow` class:
  - List draft skills with their source (which optimization produced them)
  - Show skill effectiveness metrics (success rate, lift, times triggered)
  - Support approve/edit/reject actions
  - On approve: move to "active" status, add to default skill set
  - On reject: move to "archived" with reason
  - On edit: allow modifying mutations, triggers, guardrails before promoting
- Track promotion history (who approved, when, what was changed)

### CLI
- `autoagent skills review` — interactive review of draft skills
- `autoagent skills promote <id>` — promote a draft to active
- `autoagent skills archive <id>` — archive a draft

### API
- `GET /api/skills/drafts` — list draft skills with metrics
- `POST /api/skills/{id}/promote` — promote to active
- `POST /api/skills/{id}/archive` — archive with reason
- `PATCH /api/skills/{id}` — edit before promoting

### Web UI
- Skills page: add "Drafts for Review" section at top (prominent, with count badge)
- Each draft card shows: source optimization, effectiveness metrics, mutations, triggers
- Approve/Edit/Reject buttons on each card
- Approval flow: click approve → confirmation with summary → promoted toast
- Edit flow: inline editing of skill properties before promoting

## Feature 3: Accept/Reject Audit Dashboard

Show WHY each optimization was accepted or rejected, with full transparency.

### Backend
- Enhance experiment cards with:
  - Per-dimension score deltas (safety: +0.05, quality: +0.12, latency: -0.3s)
  - Gate decisions with reasons (which gates passed/failed and why)
  - Adversarial simulation results (if run)
  - Composite score breakdown (weighted contributions)
  - Timeline of the optimization attempt (proposed → evaluated → gated → accepted/rejected)

### API
- `GET /api/changes/{id}/audit` — full audit trail for a change
- `GET /api/changes/audit-summary` — aggregated accept/reject stats

### Web UI
- Changes page: add audit view for each experiment card
- Click a card → expand to show:
  - Score breakdown visualization (bar chart of dimension contributions)
  - Gate results (green checkmarks / red X for each gate)
  - Before/after comparison per dimension
  - Timeline view of the attempt lifecycle
  - If rejected: clear explanation of what failed
- Summary dashboard at top: accept rate, top rejection reasons, improvement trend

## After All Changes
1. Run full test suite: `cd tests && python -m pytest -x -q`
2. Fix any failures
3. Add tests for all new modules
4. Commit with descriptive message
5. Push to master

When completely finished, run the openclaw notification.
