# AutoAgent VNextCC — Final Three-Way Merge

## Context

Three parallel builds implemented researcher feedback on AutoAgent VNextCC. You need to merge the best of all three into one production-grade result. This is the convergence session.

**The three builds:**
1. **CC Opus (Researcher #1)** — THIS REPO, current state. 551 tests. Deep domain objects, judge subsystem, release manager, training escalation, layered scorer.
2. **Codex R1 (Researcher #1)** — at `/Users/andrew/Desktop/AutoAgent-VNextCC-Codex2/`. 389 tests. Three-plane architecture, repository pattern, governance wrapper.
3. **Codex R2 (Researcher #2 — Simplicity)** — at `/Users/andrew/Desktop/AutoAgent-VNextCC-Codex3/`. 451 tests. Cost controls, human escape hatches, event log, coherence detection, difficulty scoring, binary rubric judge, simplified dashboard.

## Design Philosophy for the Merge

**Researcher #2's simplicity thesis must be the guiding principle.** Their core insight: "The power of this system comes from iteration speed and cycle count, not from the sophistication of any single component." and "The companies that win at agentic AI won't be the ones with the cleverest optimization algorithms. They'll be the ones who run the most iterations of a good-enough loop against a high-quality eval set."

This means:
- The **simple Karpathy loop** is the DEFAULT and RECOMMENDED path. Advanced search (bandits, Pareto, curriculum) is opt-in for power users.
- `constrained` scoring mode becomes the DEFAULT. `weighted` and `lexicographic` are kept for backwards compat but marked deprecated.
- The optimizer searches over **4 primary metrics + 2 hard constraints**, not 9 flat dimensions. Diagnostics (tool correctness, routing, handoff) are for root-cause analysis only, never optimized directly.
- LLM-as-judge uses **binary rubric questions** (yes/no) for routine evaluation, not 1-5 scales. Full evidence-span evaluation reserved for promotion decisions.
- The judge MUST be a **different model family** than the proposer. Enforce this in config validation.
- **Human escape hatches are non-negotiable** for production: pause, reject, pin surfaces as immutable.
- **Cost controls are non-negotiable** for production: per-cycle budget, daily budget, diminishing returns detection.
- **Eval difficulty scoring** prevents wasting cycles on saturated or unsolvable cases.
- **Coherence detection** catches multi-turn failures invisible to single-turn evals.

## What to Keep from CC Opus (Backbone — 551 tests)

Keep ALL existing code and tests. Then enhance with:

### From Researcher #2's build (highest priority — production-critical):

1. **`optimizer/cost_tracker.py`** (190 lines) — Copy from R2 (`/Users/andrew/Desktop/AutoAgent-VNextCC-Codex3/optimizer/cost_tracker.py`). Per-cycle budget, daily budget, cost-per-improvement, diminishing returns detection. Wire into the optimization loop.

2. **`optimizer/human_control.py`** (100 lines) — Copy from R2. Pause/resume, reject promoted candidates, inject manual mutations, pin/unpin immutable surfaces. Wire into the optimization loop (loop checks `paused` before each cycle, checks `immutable_surfaces` before applying mutations).

3. **`data/event_log.py`** (129 lines) — Copy from R2. Append-only SQLite event log. 14 event types. Wire into loop, deployer, and API. Every significant system action gets logged.

4. **`api/routes/control.py`** — Copy from R2. Human control API endpoints (pause, resume, pin, reject).

5. **`api/routes/events.py`** — Copy from R2. Event log query API endpoints.

6. **Coherence detection** — Merge R2's `CoherenceDetector` class into this repo's `evals/data_engine.py`. Detects: "I already told you", repeated questions, self-contradiction, user re-explains context. Tags failures as `coherence_failure`.

7. **Eval difficulty scoring** — Merge R2's `EvalSetHealthMonitor` and `difficulty_score` into `evals/data_engine.py` and `evals/runner.py`. Tracks pass rate history per case. Flags saturated (always pass), unsolvable (always fail), and high-leverage (30-70% pass rate) cases.

8. **`graders/similarity.py`** (35 lines) — Copy from R2. Semantic similarity grading. Wire into the grader stack as the middle tier between deterministic and LLM judge.

9. **`graders/llm_judge.py`** (BinaryRubricJudge, 121 lines) — Copy from R2. Binary yes/no rubric questions with majority voting and model-family conflict detection. This becomes the DEFAULT routine judge. CC's existing `judges/llm_judge.py` (evidence spans, full analysis) becomes the PROMOTION judge used only for final deployment decisions.

10. **Dashboard rewrite** — Take R2's `web/src/pages/Dashboard.tsx` (414 lines). 2 hard constraints + 4 primary metrics prominently displayed. Diagnostics in collapsible "Why?" panel. This is the right default UX.

11. **`web/src/pages/EventLog.tsx`** (66 lines) — Copy from R2. Event log viewer page.

12. **CLI commands** — Add from R2's implementation:
    - `autoagent pause` / `autoagent resume`
    - `autoagent reject <experiment_id>`
    - `autoagent pin <surface>` / `autoagent unpin <surface>`

13. **autoagent.yaml additions** — From R2:
    ```yaml
    budget:
      per_cycle_dollars: 1.0
      daily_dollars: 10.0
      stall_threshold_cycles: 5
    human_control:
      immutable_surfaces: ["safety_instructions"]
    ```

### From Researcher #1 Codex build (structural improvements):

14. **`data/repositories.py`** (101 lines) — Copy from R1 (`/Users/andrew/Desktop/AutoAgent-VNextCC-Codex2/data/repositories.py`). Protocol-based `TraceRepository` and `ArtifactRepository` with SQLite implementations. Postgres-ready interfaces.

15. **`AgentGraphVersion.validate()`** — Merge from R1 into `core/types.py`. Graph integrity validation (duplicate node IDs, dangling edges).

16. **`ToolContractVersion.is_replayable_at()`** — Merge from R1 into `core/types.py`. Time-aware freshness checking for recorded stubs.

17. **`control/governance.py`** (18 lines) — Copy from R1. Thin governance-as-code wrapper.

### Changes to Existing CC Code:

18. **Default scoring mode** — Change default from `"constrained"` being one option to being THE default. Add deprecation comments on `weighted` and `lexicographic`.

19. **Default search strategy** — Make `simple` (Karpathy loop) the explicit default and recommended path. Add comments: "Start here. Add `adaptive` after 100+ experiment cards show which operators work. Add `full` after genuine quality/cost tradeoffs are observed."

20. **Loop integration** — Wire cost_tracker, human_control, and event_log into `optimizer/loop.py`:
    - Check `human_control.paused` before each cycle
    - Check `cost_tracker.can_spend()` before each cycle
    - Check `human_control.immutable_surfaces` before applying mutations
    - Log every significant action to event_log
    - Detect diminishing returns (N cycles with no improvement → pause + alert)

21. **Multi-agent end-to-end eval** — When mutating a single agent, always evaluate the FULL pipeline end-to-end. Add `pipeline_eval` concept from R2.

22. **Exact model versioning** — Record exact API model version strings in experiment cards, not just "Gemini 2.5 Pro". Add `model_version_hash` field.

## Execution

1. Read ALL THREE codebases thoroughly before writing any code
2. Plan the merge (write FINAL_MERGE_PLAN.md)
3. Execute — copy new files, merge additions into existing files, wire integrations
4. Write tests for all new integration code
5. Run FULL test suite — 551+ existing tests must pass, plus new ones
6. Build frontend — must be clean
7. Update ARCHITECTURE_OVERVIEW.md
8. Update CHANGELOG.md
9. Commit: `feat: final three-way merge — production-ready with simplicity-first design`

## Constraints

- ALL 551 existing CC tests must pass after merge
- No new infrastructure dependencies
- SQLite stays
- Gemini stays default for proposer; judge default should be configurable as different family
- Simple Karpathy loop = default. Advanced = opt-in.
- Frontend stays Apple/Linear aesthetic
- `autoagent run` works identically to before with simple mode

## When Done

Run: `openclaw system event --text "Done: Final three-way merge — [test count] tests, [summary]" --mode now`
