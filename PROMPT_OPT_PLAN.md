# Prompt Optimization Implementation Plan

## Overview
Add `pro` search strategy to the optimizer, implementing real DSPy-inspired prompt optimization algorithms (MIPROv2, BootstrapFewShot) with GEPA/SIMBA stubs. Gated behind `search_strategy: pro` — existing simple/adaptive/full paths untouched.

## Architecture

```
optimizer/prompt_opt/
├── __init__.py              # Public API exports
├── bootstrap_fewshot.py     # BootstrapFewShot algorithm
├── mipro.py                 # MIPROv2 algorithm
├── surrogate.py             # Bayesian surrogate model (kNN + UCB)
├── strategy.py              # ProSearchStrategy (orchestrator)
├── types.py                 # Shared types (PromptCandidate, OptimizationResult, etc.)
├── gepa.py                  # GEPA stub
└── simba.py                 # SIMBA stub
```

## Integration Points

### 1. SearchStrategy enum (`optimizer/search.py:51-56`)
Add `PRO = "pro"` to the existing enum. No other changes to search.py.

### 2. Optimizer loop (`optimizer/loop.py:167-169`)
Add routing: `if self.search_strategy == SearchStrategy.PRO: return self._optimize_pro(...)`.
New `_optimize_pro()` method delegates to `ProSearchStrategy`.

### 3. EvalRunner (`evals/runner.py`)
Used as-is. Call `eval_runner.run(config=candidate_config)` and `eval_runner.run_cases()` for scoring.

### 4. LLMRouter (`optimizer/providers.py`)
Used for teacher/student LLM calls. MockProvider for testing.

### 5. MutationOperator (`optimizer/mutations.py`)
`instruction_rewrite` and `few_shot_edit` operators already exist. Pro strategy applies mutations through these operators.

## Implementation Order

### Phase 1: Types & Surrogate (foundation)
- `optimizer/prompt_opt/types.py` — PromptCandidate, OptimizationResult, ProConfig
- `optimizer/prompt_opt/surrogate.py` — BayesianSurrogate (kNN + UCB acquisition)

### Phase 2: Algorithms (parallel)
- `optimizer/prompt_opt/bootstrap_fewshot.py` — BootstrapFewShot
- `optimizer/prompt_opt/mipro.py` — MIPROv2

### Phase 3: Strategy & Integration
- `optimizer/prompt_opt/strategy.py` — ProSearchStrategy
- `optimizer/prompt_opt/gepa.py` — GEPA stub
- `optimizer/prompt_opt/simba.py` — SIMBA stub
- `optimizer/prompt_opt/__init__.py` — exports
- Patch `optimizer/search.py` — add PRO enum value
- Patch `optimizer/loop.py` — add pro routing

### Phase 4: Tests
- `tests/test_bootstrap_fewshot.py` — 12+ tests
- `tests/test_mipro.py` — 12+ tests
- `tests/test_surrogate.py` — 8+ tests
- `tests/test_pro_strategy.py` — 10+ tests (integration + stubs)

## Algorithm Details

### BootstrapFewShot
1. Load training cases from EvalRunner
2. Run teacher model on each case to generate demonstrations
3. Score each demonstration via eval
4. Select top-k demonstrations by quality score
5. Compile into few-shot prompt (instruction + examples)
6. Re-evaluate compiled prompt to confirm improvement
7. Return best (instruction, examples) as PromptCandidate

### MIPROv2
1. **Instruction proposal**: Use LLM meta-prompting to generate N instruction variants from task description + failure patterns
2. **Few-shot proposal**: Bootstrap example sets (reuse BootstrapFewShot)
3. **Joint search**: Bayesian optimization over (instruction_idx × example_set_idx)
   - Surrogate: kNN weighted estimation of untried candidates
   - Acquisition: UCB = score_estimate + exploration_bonus / sqrt(n_similar)
4. **Budget-aware**: Track LLM costs, stop when budget exhausted
5. **Early stopping**: Stop if no improvement for N consecutive rounds
6. Return best (instruction, examples) pair

### Bayesian Surrogate (~100 lines)
- Observations: list of (config_hash, eval_score)
- Estimate for untried: weighted average of k-nearest by Jaccard similarity on config features
- UCB: estimate + C / sqrt(1 + n_times_similar)
- No scipy/sklearn dependencies

## Config Schema
```yaml
optimizer:
  search_strategy: pro
  pro_mode:
    algorithm: auto  # auto | miprov2 | bootstrap_fewshot | gepa | simba
    instruction_candidates: 5
    example_candidates: 3
    max_eval_rounds: 10
    teacher_model: null
```

## Test Target
862 existing + 42+ new = 904+ passing tests
