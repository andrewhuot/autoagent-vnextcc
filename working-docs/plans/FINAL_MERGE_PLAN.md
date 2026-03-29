# Final Three-Way Merge Plan

## Design Principle
Researcher #2's simplicity thesis: iteration speed > sophistication. Karpathy loop default, 4+2 scoring, binary rubric judges, human escape hatches, cost controls.

## Phase 1: New Files from R2 (Production-Critical)
1. `optimizer/cost_tracker.py` — Per-cycle budget, daily budget, stall detection
2. `optimizer/human_control.py` — Pause/resume/reject/inject/pin state machine
3. `data/event_log.py` — Append-only SQLite event log (14 event types)
4. `data/repositories.py` — Protocol-based TraceRepository/ArtifactRepository (from R1)
5. `api/routes/control.py` — Human control API endpoints
6. `api/routes/events.py` — Event log query API
7. `graders/deterministic.py` — GradeResult base + deterministic assertions
8. `graders/similarity.py` — Token-overlap Jaccard similarity grader
9. `graders/llm_judge.py` — BinaryRubricJudge with majority voting
10. `control/governance.py` — Governance-as-code wrapper (from R1)
11. `web/src/pages/EventLog.tsx` — Event log viewer page

## Phase 2: Modifications to Existing CC Code
12. `core/types.py` — Add AgentGraphVersion.validate() and ToolContractVersion.is_replayable_at()
13. `evals/data_engine.py` — Add CoherenceDetector class
14. `evals/runner.py` — Add difficulty scoring (_difficulty_from_history) and pipeline eval mode
15. `optimizer/loop.py` — Wire cost_tracker, human_control, event_log, immutable_surfaces
16. `autoagent.yaml` — Add budget and human_control sections
17. `runner.py` — Add CLI commands: pause, resume, reject, pin, unpin
18. `api/server.py` — Register control/events routes, wire control_store + event_log to app.state
19. `web/src/pages/Dashboard.tsx` — Replace with R2's simplicity-first scorecard
20. `web/src/App.tsx` — Add /events route
21. `web/src/lib/api.ts` — Add hooks for control, events, scorecard, cost, eval health APIs

## Phase 3: Tests
22. Tests for cost_tracker, human_control, event_log
23. Tests for repositories, governance
24. Tests for graders (similarity, binary rubric judge)
25. Tests for coherence detection, difficulty scoring
26. Tests for loop integration (budget gate, pause gate, immutable surfaces, event logging)
27. Tests for new CLI commands
28. Tests for new API routes

## Phase 4: Verification
29. Run full test suite (551+ existing + new)
30. Build frontend
31. Update ARCHITECTURE_OVERVIEW.md and CHANGELOG.md
32. Commit
