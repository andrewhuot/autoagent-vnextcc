# AI Model Harness Engineering — Research & Apply to AutoAgent

## Context
OpenAI published "Harness Engineering" (https://openai.com/index/harness-engineering/) describing best practices for building the infrastructure around AI model evaluation and optimization. We need to research this and similar work, then apply relevant best practices to AutoAgent.

## Step 1: Research
Fetch and read these resources:
- https://openai.com/index/harness-engineering/ — OpenAI's harness engineering post
- Search for related resources on:
  - "AI eval harness" best practices
  - "LLM evaluation infrastructure" patterns
  - "Agent evaluation frameworks" (2025-2026)
  - Anthropic's eval approaches
  - Google DeepMind eval infrastructure
  - EleutherAI's lm-evaluation-harness
  - METR's agent evaluation work
  - Braintrust, Langsmith, Weights & Biases eval patterns
  - Any "eval ops" or "LLMOps" frameworks

Key topics to look for:
1. **Eval dataset management** — versioning, contamination checks, split strategies
2. **Scorer/grader patterns** — rubrics, LLM-as-judge, human-in-the-loop
3. **Statistical rigor** — confidence intervals, significance testing, effect sizes
4. **Regression detection** — how to catch regressions early
5. **Eval pipeline orchestration** — parallel execution, caching, reproducibility
6. **Metric hierarchies** — primary vs secondary vs guardrail metrics
7. **Human eval integration** — when and how to involve humans
8. **Cost-aware evaluation** — balancing eval thoroughness with API costs
9. **Eval debugging** — understanding why evals fail, trace inspection
10. **Continuous evaluation** — monitoring deployed models, drift detection

## Step 2: Audit AutoAgent
Read the AutoAgent codebase (especially `evals/`, `graders/`, `judges/`, `observer/`, `optimizer/`) and map what we already have vs what best practices recommend.

Create a gap analysis:
| Best Practice | AutoAgent Status | Gap |
|---|---|---|

## Step 3: Implement Improvements
For each significant gap, implement the improvement. Focus on:
- Things that make evals more reliable and trustworthy
- Things that reduce eval costs without sacrificing quality
- Things that improve the developer experience of working with evals
- Things that make AutoAgent's eval infrastructure competitive with OpenAI's

Likely improvements:
- Eval dataset versioning and contamination checks
- Eval caching (don't re-run identical eval+config pairs)
- Confidence intervals on all reported metrics
- Eval cost tracking and budget controls
- Better eval debugging (why did this specific case fail?)
- Eval reproducibility (deterministic seeds, frozen configs)

## Step 4: Write Documentation
Create `docs/HARNESS_ENGINEERING.md` documenting:
- AutoAgent's eval architecture and how it maps to industry best practices
- How to write good evals for your agents
- Eval dataset management guidelines
- Scoring and grading patterns
- When to use LLM judges vs rule-based graders

## After All Changes
1. Run tests: `cd tests && python -m pytest -x -q`
2. Fix failures
3. Commit: `feat: harness engineering best practices — eval caching, versioning, confidence intervals, cost tracking`
4. Push to master

When completely finished, run: openclaw system event --text "Done: Harness engineering best practices applied" --mode now
