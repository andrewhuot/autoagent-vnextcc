# AutoAgent VNextCC

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB)
![Tests](https://img.shields.io/badge/tests-pytest-22C55E)
![License](https://img.shields.io/badge/license-Apache%202.0-111827)

AutoAgent VNextCC is a CLI-first agent quality platform for running evals, applying guarded optimizations, and managing canary deployments for ADK-style agents.

The core idea is simple:
- Use the **CLI/API** for fast automation.
- Use the **web console** for visual debugging, comparisons, and stakeholder review.
- Keep every step deterministic, auditable, and versioned.

## Why teams use it
- Run repeatable evals with per-case detail
- Automatically propose and gate config improvements
- Version every config with diff + rollback support
- Monitor canary performance before promotion
- Inspect real conversations to diagnose regressions

## Product Flow

```text
┌────────────────────────────────────────────────────────────────────┐
│                           Operator Layer                           │
│   CLI (autoagent ...)         API (/api/*)         Web Console     │
└───────────────────────────────────┬────────────────────────────────┘
                                    │
                            ┌───────▼────────┐
                            │  Task Manager  │
                            │ (eval/opt/loop)│
                            └───────┬────────┘
                                    │
      ┌─────────────────────────────┼───────────────────────────────┐
      │                             │                               │
┌─────▼──────┐              ┌───────▼────────┐              ┌───────▼────────┐
│ Eval Runner│              │ Observer       │              │ Optimizer      │
│ score cases│              │ health report  │              │ propose+gate   │
└─────┬──────┘              └───────┬────────┘              └───────┬────────┘
      │                             │                               │
      └──────────────────────┬──────┴───────────────┬──────────────┘
                             │                      │
                     ┌───────▼────────┐     ┌───────▼──────────┐
                     │ Config Versions │     │ Canary Deployer  │
                     │ YAML + manifest │     │ promote/rollback │
                     └───────┬────────┘     └───────┬──────────┘
                             │                      │
                     ┌───────▼──────────────────────▼──────────┐
                     │ conversations.db + optimizer_memory.db   │
                     └───────────────────────────────────────────┘
```

## 3-Step Quickstart

```bash
# 1) Install
pip install -e ".[dev]"

# 2) Initialize + run an eval
autoagent init
autoagent eval run --output results.json

# 3) Start API + web console
autoagent server
# Open http://localhost:8000
```

Expected output from `autoagent eval run` looks like:

```text
Full eval suite
  Cases: 42/50 passed
  Quality:   0.7800
  Safety:    1.0000 (0 failures)
  Latency:   0.8500
  Cost:      0.7200
  Composite: 0.8270
```

## Screenshots

Add screenshots to `docs/screenshots/` and reference them in internal docs/PRs.
Suggested captures:
- `dashboard-health.png`
- `eval-detail-table.png`
- `optimize-timeline.png`
- `config-diff.png`
- `deploy-canary.png`

## CLI At A Glance

```bash
autoagent init --template customer-support
autoagent eval run --config configs/v003.yaml
autoagent eval results --file results.json
autoagent optimize --cycles 3
autoagent config list
autoagent config diff 1 3
autoagent deploy --config-version 5 --strategy canary
autoagent loop --max-cycles 20 --stop-on-plateau
autoagent status
autoagent logs --limit 25 --outcome fail
autoagent server
```

## Web Console Pages

- `/` Dashboard
- `/evals` Eval runs
- `/evals/:id` Eval detail
- `/optimize` Optimization history + cycle detail
- `/configs` YAML viewer + diff mode
- `/conversations` Conversation browser
- `/deploy` Deployment + canary status
- `/loop` Continuous loop monitor
- `/settings` Environment + operator shortcuts

## Documentation

- [Getting Started](docs/getting-started.md)
- [Concepts](docs/concepts.md)
- [CLI Reference](docs/cli-reference.md)
- [API Reference](docs/api-reference.md)
- [Web App Guide](docs/app-guide.md)
- [Architecture](docs/architecture.md)
- [Deployment](docs/deployment.md)
- [FAQ](docs/faq.md)
- [CX Agent Studio Integration](docs/cx-agent-studio.md)

## Tech Stack

- Backend: FastAPI + Uvicorn
- CLI: Click
- Frontend: React + Vite + TypeScript + Tailwind
- Data: SQLite (conversation store + optimization memory)
- Tests: pytest

## License

Apache 2.0. See `LICENSE`.
