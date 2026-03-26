# Getting Started

Get AutoAgent VNextCC running in under five minutes. This guide takes you from install to your first optimization cycle.

## Prerequisites

- **Python 3.11+** (3.12 recommended)
- **pip** (bundled with Python)
- API keys for at least one LLM provider (OpenAI, Anthropic, or Google)

## Install

Clone the repo and install in development mode:

```bash
git clone https://github.com/your-org/autoagent-vnextcc.git
cd autoagent-vnextcc
pip install -e ".[dev]"
```

Verify the install:

```bash
autoagent --version
```

## Initialize a project

Scaffold a new project with a starter template:

```bash
autoagent init --template customer-support
```

This creates:

```
configs/v001_base.yaml    # Base agent configuration
evals/cases/              # Eval test cases
agent/config/             # Agent config schema
```

The `customer-support` template includes a multi-specialist agent with support, orders, and recommendations routing. Use `--template minimal` for a bare scaffold.

## Run your first eval

Evaluate the base configuration against the test suite:

```bash
autoagent eval run --output results.json
```

The eval runner executes every test case, scores quality/safety/latency/cost, and writes a composite score. To target a specific category:

```bash
autoagent eval run --category happy_path --output results.json
```

## Read results

```bash
autoagent eval results --file results.json
```

Output shows pass rate, quality score, safety failures, latency, cost, and composite score.

## Start optimization

Run three optimization cycles. Each cycle proposes a mutation, evaluates it, and promotes or rejects:

```bash
autoagent optimize --cycles 3
```

The optimizer uses failure analysis from your conversation history to generate targeted improvements.

## Run the full loop

For continuous optimization with automatic plateau detection:

```bash
autoagent loop --max-cycles 20 --stop-on-plateau
```

The loop orchestrates the full cycle: trace, diagnose, search, eval, gate, deploy, learn, repeat. It stops automatically when improvements plateau.

Additional scheduling options:

```bash
# Run on a 5-minute interval
autoagent loop --schedule interval --interval-minutes 5

# Run on a cron schedule
autoagent loop --schedule cron --cron "*/10 * * * *"

# Resume from a checkpoint
autoagent loop --resume --checkpoint-file .autoagent/loop_checkpoint.json
```

## Start the web console

Launch the API server and web dashboard:

```bash
autoagent server
```

Open [http://localhost:8000](http://localhost:8000) for the web console. The API is available at `http://localhost:8000/api/`.

Options:

```bash
autoagent server --host 0.0.0.0 --port 9000 --reload
```

## Configuration

All settings live in `autoagent.yaml` at the project root:

```yaml
optimizer:
  strategy: round_robin
  search_strategy: simple          # simple | adaptive | full | pro
  holdout_rotation_interval: 5
  drift_threshold: 0.12
  models:
    - provider: openai
      model: gpt-4o
      api_key_env: OPENAI_API_KEY

loop:
  schedule_mode: continuous
  interval_minutes: 5.0
  checkpoint_path: .autoagent/loop_checkpoint.json

eval:
  history_db_path: eval_history.db
  significance_alpha: 0.05

budget:
  per_cycle_dollars: 1.0
  daily_dollars: 10.0
  stall_threshold_cycles: 5

human_control:
  immutable_surfaces: ["safety_instructions"]
```

Set API keys via environment variables referenced in the config (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`).

## Next steps

- [Core Concepts](concepts.md) -- understand the eval loop, metric hierarchy, and search strategies
- [CLI Reference](cli-reference.md) -- every command and flag
- [API Reference](api-reference.md) -- complete REST API surface
- [AutoFix Copilot](features/autofix.md) -- automated failure repair
- [Judge Ops](features/judge-ops.md) -- judge versioning and drift monitoring
- [Context Workbench](features/context-workbench.md) -- context window analysis
- [Pro-Mode Optimization](features/prompt-optimization.md) -- MIPROv2, GEPA, SIMBA, BootstrapFewShot
- [Modular Registry](features/registry.md) -- skills, policies, tool contracts, handoff schemas
- [Trace Grading](features/trace-grading.md) -- span-level grading and blame maps
- [NL Scorer](features/nl-scorer.md) -- create scorers from natural language
