# AgentLab Dependency Layers

## Layer 0: Core (the loop primitives)
> A new reader should understand this in 30 minutes.

| Module | Purpose |
|--------|---------|
| `core/` | Types, handoff artifacts, project memory |
| `agent/config/` | Config schema, runtime config, validation |
| `evals/scorer.py` | Composite scoring |
| `evals/runner.py` | Eval runner (TestCase → scores) |
| `evals/statistics.py` | Statistical significance |
| `optimizer/loop.py` | The optimization loop: propose → eval → accept/reject |
| `optimizer/proposer.py` | Generate config proposals (mock + LLM) |
| `optimizer/mutations.py` | Typed mutation operators |
| `optimizer/experiments.py` | Experiment cards |
| `optimizer/gates.py` | Hard gate checks |
| `optimizer/search.py` | Search strategies (simple/adaptive/full) |
| `optimizer/bandit.py` | Bandit policies (UCB/Thompson) |
| `optimizer/providers.py` | LLM provider routing |
| `observer/metrics.py` | Health reports |
| `observer/classifier.py` | Failure classification |
| `logger/` | Structured logging, conversation store |
| `runner.py` | CLI entry point |

**Rule: Layer 0 modules may only import from Layer 0 or stdlib/PyPI.**

## Layer 1: Advanced Features
> Power-user features. Plugged in via registry, modes, or strategy routing.

| Module | Purpose |
|--------|---------|
| `optimizer/prompt_opt/` | MIPROv2, BootstrapFewShot, GEPA, SIMBA |
| `optimizer/change_card.py` | Reviewable change cards |
| `optimizer/diff_engine.py` | Unified diff generation |
| `optimizer/sandbox.py` | Sandboxed config execution |
| `optimizer/mode_router.py` | Standard/Advanced/Research mode routing |
| `optimizer/model_routing.py` | Phase-aware model selection |
| `optimizer/autofix.py` | AutoFix copilot |
| `optimizer/autofix_proposers.py` | AutoFix proposal strategies |
| `optimizer/curriculum.py` | Curriculum learning |
| `optimizer/pareto.py` | Multi-objective Pareto archive |
| `optimizer/holdout.py` | Anti-Goodhart holdout |
| `observer/trace_grading.py` | Trace-level grading |
| `observer/blame_map.py` | Root-cause blame attribution |
| `observer/trace_graph.py` | Trace DAG visualization |
| `observer/opportunities.py` | Optimization opportunities |
| `observer/anomaly.py` | Anomaly detection |
| `context/` | Context Engineering Studio |
| `judges/` | Judge ops (audit, calibration, drift) |
| `graders/` | Grader stack (calibration, deterministic, LLM, similarity) |
| `evals/nl_compiler.py` | Natural language scorer compiler |
| `evals/nl_scorer.py` | NL-generated scorers |
| `evals/anti_goodhart.py` | Anti-Goodhart guards |
| `registry/` | Runbooks, skills, policies, tool contracts |
| `deployer/` | Canary deployment, release management |
| `control/` | Human control, pause/resume |

**Rule: Layer 1 may import from Layer 0. Layer 0 MUST NOT import from Layer 1.**

## Layer 2: Surface (API + Web)
> User-facing surfaces. Import anything.

| Module | Purpose |
|--------|---------|
| `api/` | FastAPI server + route modules |
| `web/` | React web console |

**Rule: Layer 2 may import from Layer 0 and Layer 1. Neither Layer 0 nor Layer 1 may import from Layer 2.**

## Enforcement

The boundary test at `tests/test_dependency_layers.py` verifies these rules automatically.
Run with: `python3 -m pytest tests/test_dependency_layers.py -v`
