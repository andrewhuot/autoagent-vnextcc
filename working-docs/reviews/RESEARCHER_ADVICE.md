# AI Researcher Feedback — Raw

Viewed through a Karpathy-style lens, the document is pointed in the right direction, but it is a bit too eager to build sophisticated optimization machinery before the measurement substrate is fully grounded. The main lesson from recent OpenAI and Anthropic material is that strong agent improvement starts with task-specific evals, trace logging, real-failure flywheels, and human-calibrated graders; for stateful agents in particular, Anthropic argues you should usually grade end states rather than exact trajectories, while OpenAI now treats traces and trace grading as first-class workflow-level debugging tools. My headline recommendation is: build AutoAgent as an eval-native experimentation system around versioned agent graphs, skills, tool contracts, and stateful sandbox replay. The first-class objects should be AgentGraphVersion, SkillVersion, ToolContractVersion, PolicyPackVersion, Trace, EnvironmentSnapshot, GraderBundle, EvalCase, CandidateVariant, and ArchiveEntry. The moat is not "we mutate prompts." The moat is "we can faithfully replay, grade, and safely improve real enterprise agent workflows." That also lines up with where both OpenAI and Anthropic are going with skills/procedures, trace-centric evaluation, and governance-as-code.

## What to Keep
The outer loop is right. The typed mutation registry is right. The live-failure-to-eval flywheel is right. Experiment cards, holdouts, canaries, and rollback handles are all exactly the sort of discipline this kind of system needs.

## What to Change

### 1. Stop treating all 9 metrics as peers
Split into four layers:
1. Hard gates: safety/policy, authorization/privacy, state integrity, P0 regressions
2. North-star outcomes: end-state task success, grounded answer quality, calibrated user satisfaction / human effort saved
3. Operating SLOs: latency, cost, escalation rate
4. Diagnostics: tool correctness, routing, handoff fidelity, recovery rate, clarification quality, judge disagreement

Missing metrics: state integrity / business invariant correctness, groundedness / evidence fidelity.

### 2. Make end state the unit of truth
Canonical eval object: (task, environment snapshot, grader bundle, expected end state, diagnostic trace features). Exact tool trajectory matching should be optional and sparse. Replace side-effect classification with richer replayability matrix: deterministic stub, recorded stub with freshness window, live sandbox clone, simulator, forbidden. Build digital-twin adapters for stateful enterprise systems.

### 3. Turn handoff fidelity into structured artifacts
Handoffs should be structured artifacts with: goal, constraints, known facts, unresolved questions, allowed tools, expected deliverable, evidence refs.

### 4. Treat LLM-as-judge as a product subsystem
Judge stack: deterministic/executable/state-check graders first → rule-based validators → frozen primary LLM judge → human review for calibration. Don't use same model family as proposer and judge. Build judge calibration suite as first-class dataset.

### 5. Search like a bounded research loop
Optimization unit: one failure family × one mutation surface × one bounded eval bundle × one short experiment loop. Make Pareto archive central. Use breadth/depth split (cheap proposer, stronger critic). Mutation generator should ingest structured critiques, not just binary pass/fail.

### 6. Keep auto-change surface deliberately narrow
Auto-deploy: instruction blocks, few-shot examples, tool descriptions, routing thresholds, memory policies, guardrail thresholds, maybe lightweight skill edits. PR/manual: model swaps, topology changes, code patches, new tools. De-emphasize topology as optimization surface.

### 7. Simplify stats default, strengthen reporting
Default: paired comparison, clustered by conversation/user/env, effect size + 95% CI, explicit power targets. No n>=30 rule. O'Brien-Fleming for online canaries only. Severity tiers for safety. Add negative controls aggressively.

### 8. Treat infrastructure as part of the experiment
Three planes: control (experiments, archive, policies), execution (stateless replay workers), data (object storage + relational metadata). SQLite for dev, Postgres + blob for production.

## Architecture to Build
1. Canonical internal IR for agent systems (framework-neutral AgentGraph IR)
2. Trace + artifact plane (spans, state diffs, handoff artifacts, large artifacts by ref)
3. Eval compiler (PII scrub, dedup, reproducibility, business impact, root-cause tags, solvability check, negative controls, 5 suite types)
4. Stateful sandbox layer (per-tool replay mode/validator/sandbox policy, cloned envs, state diffs, business invariants)
5. Small-diff improvement engine (cheap proposer, stronger critic, frozen judge, audit judge, constrained Pareto, contextual bandit)
6. Release manager with real governance (hard gates → hidden holdout → slice checks → canary → rollback)
7. Training escalation path (recommend SFT/DPO/RFT for stable high-volume failure families)
