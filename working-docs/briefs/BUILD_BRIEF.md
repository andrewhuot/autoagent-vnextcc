# AutoAgent VNext — Self-Healing, Self-Optimizing ADK Agent

## Vision
A Google ADK agent running on Google Cloud that watches itself, fixes itself, and improves itself — following the Karpathy autoresearch pattern applied to multi-agent systems.

NOT a research platform. NOT a dashboard app. An actual self-healing agent system.

## Architecture

```
┌─────────────────────────────────────┐
│  ADK AGENT (Cloud Run)              │
│  - Root orchestrator                │
│  - 3-4 specialist sub-agents        │
│  - Tool integrations                │
│  - Serves conversations via API     │
└──────────┬──────────────────────────┘
           │ logs every conversation
           ▼
┌─────────────────────────────────────┐
│  CONVERSATION STORE (SQLite/BQ)     │
│  - Full conversation logs           │
│  - Outcome signals (success/fail)   │
│  - Latency, token cost, errors      │
│  - Safety violation flags           │
└──────────┬──────────────────────────┘
           │ observer reads periodically
           ▼
┌─────────────────────────────────────┐
│  OBSERVER                           │
│  - Runs on schedule (cron/Cloud Fn) │
│  - Computes health metrics:         │
│    · Success rate (last N convos)   │
│    · Avg latency                    │
│    · Error rate                     │
│    · Safety violation count         │
│    · Cost per conversation          │
│  - Detects anomalies/degradation    │
│  - Classifies failure patterns      │
└──────────┬──────────────────────────┘
           │ if degraded or improvable
           ▼
┌─────────────────────────────────────┐
│  OPTIMIZER (the autoresearch loop)  │
│  - Reads: current agent config,     │
│    recent failures, health metrics  │
│  - Asks LLM: "propose a fix"       │
│  - Generates candidate config       │
│  - Runs eval suite against it       │
│  - Single composite score           │
│  - Accept/reject gate:              │
│    · Must pass safety (hard gate)   │
│    · Must improve score (soft gate) │
│    · Must not regress on any metric │
│      by more than 5%               │
│  - If accepted → canary deploy      │
└──────────┬──────────────────────────┘
           │ if accepted
           ▼
┌─────────────────────────────────────┐
│  DEPLOYER                           │
│  - Saves new config version         │
│  - Canary: route 10% traffic        │
│  - Monitor canary for 1 hour        │
│  - If canary healthy → promote 100% │
│  - If canary degrades → rollback    │
│  - All versions stored + auditable  │
└─────────────────────────────────────┘
```

## What to Build

### 1. Demo ADK Agent (`agent/`)
A working ADK agent with real structure to optimize against:
- **Root orchestrator** that routes to specialists
- **Specialist 1: Customer Support** — answers product questions
- **Specialist 2: Order Management** — handles order lookups, modifications
- **Specialist 3: Recommendations** — suggests products based on context
- **Shared tools**: product catalog lookup, order database, FAQ search
- Uses Google ADK Python SDK (`google-adk`)
- Agent config is externalized (prompts, routing rules, tool configs in YAML/JSON)
- Config is the "train.py" equivalent — what the optimizer edits

### 2. Conversation Logger (`logger/`)
- Middleware/callback that logs every conversation turn
- Stores: conversation_id, turns, agent responses, tool calls, latency_ms, token_count, outcome (success/fail/abandon), safety_flags, error messages, timestamp
- SQLite for local dev, structured for easy BigQuery migration
- Outcome detection: heuristic-based (did agent answer? did user abandon? did tool call fail?)

### 3. Eval Suite (`evals/`)
- 50+ test conversations covering:
  - Happy paths (should succeed)
  - Edge cases (tricky routing)
  - Safety probes (should refuse)
  - Regression cases (previously fixed bugs)
  - Performance cases (should be fast)
- Each test case: input conversation, expected behavior, scoring criteria
- Runner that executes all tests against a config, produces composite score
- Score = weighted average: 40% quality + 25% safety + 20% latency + 15% cost
- Safety is also a HARD GATE — any safety failure = automatic reject regardless of score

### 4. Observer (`observer/`)
- Reads conversation store
- Computes rolling metrics (last 100 conversations):
  - success_rate, avg_latency_ms, error_rate, safety_violation_rate, avg_cost
- Detects: anomaly (metric outside 2σ of baseline), degradation (trending down), opportunity (pattern of similar failures)
- Classifies failures into buckets: routing_error, tool_failure, hallucination, safety_violation, timeout, unhelpful_response
- Outputs: health report + triggered experiment request (if needed)

### 5. Optimizer (`optimizer/`)
THE CORE — this is the autoresearch loop:

```python
def optimize(health_report, current_config, failure_samples, memory):
    # 1. Build context for LLM
    context = {
        "current_config": current_config,
        "health_metrics": health_report.metrics,
        "failure_samples": failure_samples[:10],  # worst recent failures
        "failure_classification": health_report.failure_buckets,
        "past_attempts": memory.recent(limit=20),  # what we already tried
    }
    
    # 2. Ask LLM to propose a fix
    proposal = llm.generate(
        "You are an agent optimization system. Given the current config and failures, "
        "propose a SINGLE targeted change to improve the agent. "
        "Return the modified config section only.",
        context=context
    )
    
    # 3. Validate proposal
    if not config_schema.validate(proposal.new_config):
        memory.log(proposal, status="rejected_invalid")
        return None
    
    # 4. Run eval suite
    baseline_score = eval_suite.run(current_config)
    candidate_score = eval_suite.run(proposal.new_config)
    
    # 5. Safety hard gate
    if candidate_score.safety_failures > 0:
        memory.log(proposal, status="rejected_safety")
        return None
    
    # 6. Improvement gate
    if candidate_score.composite <= baseline_score.composite:
        memory.log(proposal, status="rejected_no_improvement")
        return None
    
    # 7. Regression gate (no metric drops >5%)
    if candidate_score.has_regression(baseline_score, threshold=0.05):
        memory.log(proposal, status="rejected_regression")
        return None
    
    # 8. Accept!
    memory.log(proposal, status="accepted", score_delta=candidate_score.composite - baseline_score.composite)
    return proposal.new_config
```

- Memory is a simple SQLite table: attempt_id, timestamp, change_description, config_diff, status, score_before, score_after
- LLM calls use Gemini (via ADK's built-in LLM access) or mock for testing
- One change at a time (like autoresearch — small, testable diffs)

### 6. Deployer (`deployer/`)
- Config versioning: each accepted config gets a version number, stored in `configs/` directory
- Canary logic (simplified for demo):
  - Write new config as "canary" version
  - Agent reads config with canary awareness (10% of requests use canary)
  - After N conversations on canary, compare metrics
  - If canary metrics >= baseline → promote
  - If worse → rollback to previous version
- All deploys logged with timestamp, config hash, scores

### 7. Runner (`runner.py`)
- Main entry point that ties everything together
- Modes:
  - `run agent` — start the ADK agent server
  - `run observe` — run observer once
  - `run optimize` — run one optimization cycle
  - `run loop` — continuous: observe → optimize → deploy (the full autoresearch loop)
  - `run eval` — run eval suite against current config
  - `run status` — show current health, config version, recent changes

### 8. Tests (`tests/`)
- Unit tests for observer metrics computation
- Unit tests for optimizer accept/reject logic
- Unit tests for eval suite scoring
- Integration test: full loop (mock LLM) — degrade agent → observer detects → optimizer fixes → deployer promotes

## Tech Stack
- **Python 3.11+**
- **Google ADK** (`google-adk` package) for the agent
- **FastAPI** for agent API endpoint
- **SQLite** for conversation store + optimizer memory (local dev)
- **Click or Typer** for CLI
- **Pytest** for tests
- No frontend. CLI + logs only. This is infrastructure, not a dashboard.

## File Structure
```
AutoAgent-VNext/
├── agent/
│   ├── __init__.py
│   ├── root_agent.py          # ADK orchestrator
│   ├── specialists/
│   │   ├── support.py         # Customer support specialist
│   │   ├── orders.py          # Order management specialist
│   │   └── recommendations.py # Recommendation specialist
│   ├── tools/
│   │   ├── catalog.py         # Product catalog tool
│   │   ├── orders_db.py       # Order database tool
│   │   └── faq.py             # FAQ search tool
│   └── config/
│       ├── schema.py          # Config schema + validation
│       ├── base_config.yaml   # Default agent config
│       └── loader.py          # Config loading + canary routing
├── logger/
│   ├── __init__.py
│   ├── middleware.py           # Conversation logging middleware
│   └── store.py               # SQLite conversation store
├── evals/
│   ├── __init__.py
│   ├── runner.py               # Eval suite runner
│   ├── scorer.py               # Composite scoring
│   ├── cases/
│   │   ├── happy_path.yaml     # Success test cases
│   │   ├── edge_cases.yaml     # Tricky routing cases
│   │   ├── safety.yaml         # Safety probe cases
│   │   └── regression.yaml     # Previously fixed bugs
│   └── fixtures/
│       └── mock_data.py        # Mock product/order data
├── observer/
│   ├── __init__.py
│   ├── metrics.py              # Health metric computation
│   ├── anomaly.py              # Anomaly detection
│   └── classifier.py           # Failure classification
├── optimizer/
│   ├── __init__.py
│   ├── loop.py                 # Core optimization loop
│   ├── proposer.py             # LLM-based change proposer
│   ├── gates.py                # Safety/improvement/regression gates
│   └── memory.py               # Optimization attempt memory
├── deployer/
│   ├── __init__.py
│   ├── versioning.py           # Config version management
│   └── canary.py               # Canary deploy logic
├── runner.py                   # CLI entry point
├── configs/                    # Versioned config directory
│   └── v001_base.yaml
├── tests/
│   ├── test_observer.py
│   ├── test_optimizer.py
│   ├── test_evals.py
│   ├── test_deployer.py
│   └── test_integration.py
├── pyproject.toml
├── Dockerfile
├── docker-compose.yaml
└── README.md
```

## What Makes This Different From v5
- v5 is a research platform WITH a dashboard FOR humans to use
- VNext IS the agent — it runs, watches itself, fixes itself
- v5 has MCTS/Pareto/multi-objective theory. VNext has ONE score and accept/reject
- v5 is complex. VNext is Karpathy-simple
- VNext could literally run overnight and improve itself with zero human intervention

## Mock Strategy
- LLM calls: use a mock that returns plausible config changes (for testing without API costs)
- Agent conversations: mock tool responses (no real product DB needed)
- The eval suite tests against mock conversations, not live traffic
- BUT: the architecture is real and ready for real Gemini + real Cloud Run with minimal changes

## Success Criteria
1. `python runner.py run agent` starts a working ADK agent that handles conversations
2. `python runner.py run eval` scores the agent against 50+ test cases
3. `python runner.py run observe` computes health metrics from logged conversations
4. `python runner.py run optimize` proposes and evaluates one improvement
5. `python runner.py run loop --cycles 5` runs 5 optimization cycles and the agent measurably improves
6. Tests pass
7. Docker-compose works
8. The whole thing is under 5,000 lines of actual code (excluding tests)
