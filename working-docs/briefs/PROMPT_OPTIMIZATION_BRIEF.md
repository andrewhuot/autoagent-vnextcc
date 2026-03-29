# Pro-Mode Prompt Optimization Brief

## Mission
Build a genuine, research-grade prompt optimization module gated behind `search_strategy: pro` in config and `autoagent optimize --strategy pro` on CLI. The happy path (`simple`/`adaptive`/`full`) stays COMPLETELY untouched.

## What This Is
Real prompt optimization using established algorithms from the DSPy ecosystem and recent research. Not stubs. Not mocks. Genuine implementations that can actually optimize prompts when given an eval set and an LLM.

## Architecture Constraints
- New package: `optimizer/prompt_opt/` with clean `__init__.py`
- Integrates via the existing `SearchEngine` strategy routing in `optimizer/search.py` — add `pro` as a new strategy
- Uses existing `EvalRunner`, `Gates`, significance testing, and canary deployment
- Does NOT modify simple/adaptive/full code paths
- All new code gets tests

## Algorithms to Implement

### 1. BootstrapFewShot (IMPLEMENT FULLY)
DSPy's foundational algorithm. Core idea:
- Run teacher model on training examples to generate high-quality demonstrations
- Select best demonstrations via eval scoring
- Compile them into few-shot prompts
- Re-evaluate to confirm improvement

Implementation:
- `optimizer/prompt_opt/bootstrap_fewshot.py`
- Uses the project's existing `LLMRouter` for teacher/student calls
- Generates candidate few-shot examples from eval cases
- Scores each example set via `EvalRunner`
- Returns the best prompt + examples as a typed mutation

### 2. MIPROv2 (IMPLEMENT FULLY)
Multi-prompt Instruction Proposal and Optimization v2. Core idea:
- Generate multiple instruction candidates via LLM meta-prompting
- Generate multiple few-shot example sets via bootstrapping
- Use Bayesian optimization (surrogate model) to search the joint space of (instruction × examples)
- Evaluate candidates efficiently with early stopping

Implementation:
- `optimizer/prompt_opt/mipro.py`
- Instruction proposal: use LLM to generate N instruction variants given task description + failure patterns
- Few-shot proposal: bootstrap examples (reuse BootstrapFewShot)
- Search: simplified Bayesian optimization — use a surrogate that tracks (instruction_idx, example_set_idx) → eval score, proposes next candidates via UCB acquisition
- Budget-aware: respect `budget.per_cycle_dollars` and stop when budget exhausted
- Returns best (instruction, examples) pair as typed mutation

### 3. GEPA — Gradient-free Evolutionary Prompt Adaptation (STUB with clear extension points)
- `optimizer/prompt_opt/gepa.py`
- Stub class with `optimize()` that raises `NotImplementedError("GEPA: evolutionary prompt adaptation not yet implemented — see arxiv.org/abs/...")`
- Include docstring explaining the algorithm: population of prompts, fitness = eval score, crossover = LLM-based prompt merging, mutation = LLM-based prompt perturbation

### 4. SIMBA — Simulation-Based Prompt Optimization (STUB with clear extension points)
- `optimizer/prompt_opt/simba.py`
- Same pattern as GEPA stub
- Docstring: uses simulated user interactions to evaluate prompt quality, trains a reward model on simulated outcomes

## Key Module: ProSearchStrategy
- `optimizer/prompt_opt/strategy.py`
- Implements the same interface as existing search strategies in `optimizer/search.py`
- Orchestrates: opportunity analysis → algorithm selection → prompt optimization → eval → gate → experiment card
- Algorithm selection logic:
  - Default: MIPROv2 (best general-purpose)
  - If budget is tight: BootstrapFewShot (cheaper, fewer LLM calls)
  - If explicitly configured: any algorithm by name
- Config integration:
  ```yaml
  optimizer:
    search_strategy: pro
    pro_mode:
      algorithm: auto  # auto | miprov2 | bootstrap_fewshot | gepa | simba
      instruction_candidates: 5
      example_candidates: 3
      max_eval_rounds: 10
      teacher_model: null  # defaults to primary model
  ```

## Bayesian Surrogate for MIPROv2
Keep it simple. No scipy/sklearn dependency:
- Track all (config_hash, eval_score) observations
- For each untried candidate, estimate score via weighted k-nearest neighbors in observation space
- UCB acquisition: score_estimate + exploration_bonus / sqrt(times_similar_tried)
- This is a ~100-line module, not a full GP implementation

## CLI Integration
- `autoagent optimize --strategy pro` — runs pro-mode optimization
- `autoagent optimize --strategy pro --algorithm bootstrap_fewshot` — force specific algorithm
- Existing `--strategy simple/adaptive/full` unchanged

## API Integration
- Extend `POST /api/optimize/run` to accept `strategy: "pro"` in request body
- No new endpoints needed

## Web Integration
- On the Optimize page, when strategy=pro, show algorithm name and search progress
- Minimal — just ensure existing page doesn't break

## Testing Strategy
- Unit tests for BootstrapFewShot with mock LLM (verify example selection logic, scoring, mutation output)
- Unit tests for MIPROv2 with mock LLM (verify instruction generation, surrogate model, budget enforcement, early stopping)
- Unit tests for surrogate model (verify UCB acquisition, observation tracking)
- Integration test: pro strategy routes through SearchEngine correctly
- Stub tests: GEPA/SIMBA raise NotImplementedError
- Target: 40+ new tests

## Research References (read these to understand the algorithms)
- DSPy paper: https://arxiv.org/abs/2310.03714 (BootstrapFewShot, MIPRO)
- MIPROv2: https://arxiv.org/abs/2406.11695
- DSPy source: https://github.com/stanfordnlp/dspy (optimizers/ directory)
- The key insight: these are not magic — they're systematic search over (instruction × examples) space with eval-driven selection

## PLANNING PHASE
1. Read `optimizer/search.py` thoroughly — understand the strategy interface
2. Read `optimizer/loop.py` — understand how strategies are selected and called
3. Read `evals/runner.py` — understand the eval interface you'll call
4. Read `optimizer/providers.py` — understand LLMRouter for teacher/student calls
5. Read `optimizer/mutations.py` — understand how to emit typed mutations
6. Write `PROMPT_OPT_PLAN.md` with exact file list and implementation order
7. Then implement, test-first where possible

## EXECUTION
Use `claude --model claude-sonnet-4-5 --dangerously-skip-permissions -p '...'` sub-agents for parallel work:
- Agent 1: BootstrapFewShot + tests
- Agent 2: MIPROv2 + surrogate + tests
- Agent 3: Strategy + integration + stubs + tests
Then converge, run full test suite, commit, push.

## DONE CRITERIA
- `python3 -m pytest tests/ --tb=short -q` passes (baseline 862 + 40 new = 900+)
- `autoagent optimize --strategy pro` works end-to-end with mock LLM
- simple/adaptive/full strategies completely unchanged
- Git commit + push to origin master
