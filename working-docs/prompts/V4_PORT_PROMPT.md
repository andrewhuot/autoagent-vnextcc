# AutoAgent VNextCC — Port v4 Research into Production

## Mission

Port the best ideas from AutoAgent v4 Research into VNextCC's existing architecture. The goal is to make the optimizer and evals dramatically more effective WITHOUT changing the user experience. The UX stays simple (`autoagent init` → `autoagent run` → see results). The internals get much smarter.

## What to Port

### 1. 9-Dimension Evaluation Framework (from v4 EVALUATION_FRAMEWORK.md)

Read `~/Desktop/AutoAgent-v4-Research/EVALUATION_FRAMEWORK.md` (580 lines) thoroughly.

Port these dimensions into VNextCC's scorer:
- **G1**: Task success rate
- **G2**: Response quality
- **G3**: Safety compliance rate
- **G4**: Latency (p50, p95, p99)
- **G5**: Token cost
- **G6**: Tool correctness rate
- **G7**: Routing accuracy
- **G8**: Handoff fidelity
- **G9**: User satisfaction proxy

Plus per-agent dimensions:
- Per specialist: unit success, tool precision/recall, policy adherence, avg latency, escalation appropriateness
- Per orchestrator: first-hop routing accuracy, reroute recovery rate, context forwarding fidelity
- Per shared agent: min performance across consumers, performance variance

**Key constraint**: The existing 4-dimension composite (quality/safety/latency/cost) should remain as the DEFAULT "simple mode" view. The 9 dimensions are the internal engine — the composite is still what users see unless they opt into detailed mode. Don't overwhelm the UI.

### 2. Constrained Pareto Archive (from v4 V4_PROPOSAL.md)

Read `~/Desktop/AutoAgent-v4-Research/V4_PROPOSAL.md` (507 lines).

Port the Constrained Pareto Archive (CPA):
- Separate feasible and infeasible candidate sets explicitly
- Proper Pareto dominance checks
- Replace single-best-candidate selection with Pareto front
- Auto-select the "knee point" for deployment recommendation (user still sees one recommendation, but Pareto front is available in detail view)

### 3. Hybrid Search Orchestrator (from v4 V4_PROPOSAL.md)

Port the HSO concept but keep it simple:
- Three operator families: MCTS-style exploration, local parameter tuning (BO-lite), diversity injection
- Adaptive operator selection based on observed hit rates
- Principled explore/exploit balancing
- Budget-aware experiment allocation

Wire this INTO the existing `optimizer/search.py` — don't replace it, enhance it. The multi-hypothesis generation already there is good; add the operator selection and learning loop on top.

### 4. Anti-Goodhart Mechanisms (from v4 EVALUATION_FRAMEWORK.md)

Port:
- Holdout rotation (swap holdout sets periodically to prevent overfitting)
- Drift-aware re-baselining (detect when baseline degrades, trigger re-baseline)
- Judge variance estimation (already partially in VNextCC stats, enhance it)
- Require candidates to pass BOTH fixed AND rolling holdouts

### 5. Top Novel Contributions (from NOVEL_CONTRIBUTIONS.md)

Read `~/Desktop/AutoAgent-v4-Research/NOVEL_CONTRIBUTIONS.md` (2034 lines). Cherry-pick what's implementable NOW:
- **Bandit-guided experiment selection** — replace uniform allocation with UCB/Thompson sampling for which agent/surface to optimize next
- **Curriculum learning** — start with easy failure clusters, graduate to harder ones (cheap early wins → hard problems later)

DON'T port (too complex for now): agent genome, differentiable architectures, NAS, self-play, agent tree compiler.

### 6. Keep the Clean Failure-Bucket Proposer

The VNext proposer's clean `failure_bucket → proposal` mapping is pragmatic and works great. Keep it as the "simple mode" / fast-path proposer. The HSO search engine is the "advanced mode" that sits alongside it. Config should let users choose:
```yaml
optimizer:
  search_strategy: simple  # simple | adaptive | full
```
- `simple` = original failure-bucket proposer (fast, predictable)
- `adaptive` = HSO with bandit selection (smarter, more eval cost)
- `full` = HSO + curriculum + Pareto archive (maximum optimization, maximum cost)

## How to Execute

1. **Read all v4 research docs first** — understand the full picture before coding
2. **Read all existing VNextCC code** — know what you're enhancing
3. **Plan the changes** — write a brief plan (which files, what changes)
4. **Implement** — use sub-agents for parallel work:
   - Agent A: Enhanced scorer (9 dimensions + per-agent) + Pareto archive
   - Agent B: HSO search engine + bandit selection + curriculum
   - Agent C: Anti-Goodhart mechanisms + holdout rotation + drift detection
   - Agent D: Frontend updates (detail views for Pareto front, dimensions — keep default view simple)
5. **Integrate and test** — merge, run all tests, build frontend
6. **Update docs** — ARCHITECTURE_OVERVIEW.md, README, CHANGELOG

## Constraints

- **DO NOT change the default UX** — `autoagent run` should work exactly as before with `search_strategy: simple`
- **DO NOT break existing tests** — 193 tests must still pass, plus new ones
- **DO NOT add external dependencies** — no new pip packages beyond what's already used
- **Keep Gemini-first** — all LLM calls default to Gemini
- **Keep single-process** — no Celery/Redis
- **Keep Apple/Linear frontend aesthetic** — new detail views should match existing design

## When Done

Run: `openclaw system event --text "Done: v4 research port — [summary of what changed, dimensions, test counts]" --mode now`
