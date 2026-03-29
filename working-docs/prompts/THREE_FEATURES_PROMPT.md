# Three Feature Implementation Brief

## CRITICAL CONSTRAINTS
- **Simplicity above all else.** If a feature makes the product harder to understand, cut it.
- **You do NOT have to implement everything.** Ship the 80% that matters. Skip the 20% that adds complexity without proportional value.
- **Maintain the existing code style, test patterns, and architecture conventions.**
- **Every new module needs tests.** Target 90%+ coverage on new code.
- **CLI-first.** Every feature must be usable from the CLI. Web console is for visualization.
- **Keep the README honest.** Update it when done.

## PLANNING PHASE (do this FIRST, before any code)

1. Read the existing codebase thoroughly:
   - `optimizer/mutations.py` (typed mutations — AutoFix builds on this)
   - `judges/` and `graders/` packages (Judge Ops extends these)
   - `core/types.py` (domain objects — context workbench needs new types here)
   - `optimizer/loop.py` (the main loop — AutoFix integrates here)
   - `observer/traces.py` (tracing — context workbench reads these)
   - `api/` routes and `web/src/pages/` (existing patterns for new endpoints/pages)
   - `evals/` package (eval pipeline — all three features touch this)
   - `data/event_log.py` (event system)
   - `optimizer/human_control.py` (human escape hatches)
   - `tests/` (test patterns)

2. Write a plan as `THREE_FEATURES_PLAN.md` with:
   - Exactly which files you'll create/modify
   - What you're intentionally NOT building (and why)
   - Risk assessment for each feature
   - Dependency order

3. Only then start implementation.

## FEATURE 1: AutoFix Copilot

### What it is
A constrained, legible improvement proposer. It feels like a smart research assistant, not an opaque self-modifying system. Every proposal is small, reviewable, and reversible.

### What to build
- `optimizer/autofix.py` — AutoFix engine
  - Proposes small, targeted changes: instruction edits, example swaps, routing threshold tweaks, memory policy changes, tool description fixes, skill-level updates
  - Each proposal is a typed mutation (reuse `optimizer/mutations.py`)
  - Every proposal includes: expected lift estimate, affected eval slices, risk class, cost impact estimate, diff preview
  - Proposals go through: offline eval → significance gate → canary → promotion
- `optimizer/autofix_proposers.py` — Individual proposer strategies
  - Failure-pattern proposer (clusters failures → targeted fix)
  - Regression proposer (detects regressions → rollback or patch)
  - Cost-optimization proposer (finds cheaper model/prompt combos)
  - Each proposer is a simple class with `propose(opportunity) -> List[AutoFixProposal]`
- CLI commands:
  - `autoagent autofix suggest` — generate proposals without applying
  - `autoagent autofix apply <proposal-id>` — apply with eval + canary
  - `autoagent autofix history` — see past proposals and outcomes
- API endpoints:
  - `POST /api/autofix/suggest` — trigger proposal generation
  - `GET /api/autofix/proposals` — list proposals
  - `POST /api/autofix/apply/{id}` — apply a proposal
  - `GET /api/autofix/history` — past proposals with outcomes
- Web page: `AutoFix` page showing proposals with diff previews, lift estimates, and apply/reject buttons
- Integration with Google Vertex Prompt Optimizer (stub — `optimizer/autofix_vertex.py`)

### What NOT to build
- No autonomous apply-without-review mode (always human-in-the-loop for v1)
- No fine-tuning proposals (just prompt/config level)
- No multi-step compound mutations (one change at a time)

## FEATURE 2: Judge Ops

### What it is
Judge reliability as a product area. Teams can see how their judges are performing, calibrate against human labels, and improve grading quality over time.

### What to build
- `judges/versioning.py` — Grader versioning
  - Version grader configs (rubric text, model, temperature)
  - Track which grader version produced which scores
  - Diff between grader versions
- `judges/drift_monitor.py` — Judge drift detection
  - Track agreement rates over time windows
  - Alert when judge behavior shifts (model update, prompt drift)
  - Position bias and verbosity bias monitors (extend existing `judges/calibration.py`)
- `judges/human_feedback.py` — Human-vs-judge calibration
  - Accept human corrections on individual judgments
  - Compute human-judge agreement rate
  - Disagreement sampling: surface cases where judge and human disagree most
  - SME workflow: correct judgments, add rubric dimensions, promote slices to regression suites
- CLI commands:
  - `autoagent judges list` — show active judges with version and agreement stats
  - `autoagent judges calibrate --sample 50` — sample cases for human review
  - `autoagent judges drift` — show drift report
- API endpoints:
  - `GET /api/judges` — list judges with stats
  - `POST /api/judges/feedback` — submit human correction
  - `GET /api/judges/calibration` — calibration dashboard data
  - `GET /api/judges/drift` — drift metrics
- Web page: `Judge Ops` page with calibration dashboard, drift charts, disagreement queue

### What NOT to build
- No automated judge retraining (just monitoring + human feedback for v1)
- No judge A/B testing framework (overkill for now)

## FEATURE 3: Context Engineering Workbench

### What it is
A diagnostic and tuning tool for agent context failures. Many agent failures aren't intelligence failures — they're context failures (too much context, bad compaction, stale memory, weak handoffs).

### What to build
- `context/analyzer.py` — Context analysis engine
  - Measure context window utilization per turn (tokens used vs available)
  - Detect context growth patterns (linear, exponential, sawtooth from compaction)
  - Score handoff summaries (information retention, key fact preservation)
  - Identify context-correlated failures (failures that spike when context > N tokens)
- `context/simulator.py` — Context simulation
  - Simulate compaction strategies on real traces
  - Compare context budgets against outcomes
  - Memory TTL/pinning experiments (what if we kept X longer / dropped Y sooner)
- `context/metrics.py` — Context-specific metrics
  - Context utilization ratio
  - Compaction loss score (info lost during compaction)
  - Handoff fidelity (structured handoff completeness)
  - Memory staleness (age of oldest active memory vs relevance)
- CLI commands:
  - `autoagent context analyze --trace <id>` — analyze context for a trace
  - `autoagent context simulate --strategy <name>` — simulate compaction
  - `autoagent context report` — aggregate context health report
- API endpoints:
  - `GET /api/context/analysis/{trace_id}` — context analysis for a trace
  - `POST /api/context/simulate` — run compaction simulation
  - `GET /api/context/report` — aggregate metrics
- Web page: `Context Workbench` page with context growth visualization, compaction simulator, handoff scorer

### What NOT to build
- No real-time context interception (analysis only, on recorded traces)
- No automatic context policy optimization (show insights, let humans tune)
- No token-level attention visualization (too complex, marginal value)

## EXECUTION

Use `claude --model claude-sonnet-4-5` sub-agents for parallel implementation:
- Agent 1: AutoFix (backend + tests)
- Agent 2: Judge Ops (backend + tests)  
- Agent 3: Context Workbench (backend + tests)
- Then: API routes, CLI commands, web pages (can be sequential or parallel)

Run `python3 -m pytest tests/ --tb=short -q` after each feature to ensure nothing breaks.

## DONE CRITERIA
- All three features have backend modules, CLI commands, API endpoints, and web pages
- All new code has tests
- Full test suite passes (baseline: 735)
- Git commit with conventional commit message
- Brief summary of what was built and what was intentionally skipped
