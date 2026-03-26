# CI/CD Gate for AutoAgent

Make AutoAgent a CI/CD gate — fail the build if agent quality regresses.

## Quick Start

### 1. Run as CLI

```bash
# Run eval with gate (exit code 0 = pass, 1 = fail)
autoagent eval run --gate --fail-on-regression

# Compare against baseline
autoagent eval run --gate --baseline latest --fail-on-regression

# Allow up to 5% regression
autoagent eval run --gate --threshold 0.05 --fail-on-regression
```

### 2. GitHub Actions Integration

Create `.github/workflows/agent-quality.yml`:

```yaml
name: Agent Quality Gate
on: [push, pull_request]

jobs:
  quality-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: autoagent eval run --gate --fail-on-regression --output results.json
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: eval-results
          path: results.json
```

### 3. Pre-merge Hook

Add to `.git/hooks/pre-push`:

```bash
#!/bin/bash
autoagent eval run --gate --baseline main --fail-on-regression
if [ $? -ne 0 ]; then
    echo "❌ Agent quality gate failed. Push blocked."
    exit 1
fi
```

## Gate Logic

### Hard Gates (Binary)
- ✅ **Safety**: No safety violations
- ✅ **P0 Regressions**: No critical metric regressions

### Soft Gates (Threshold)
- ⚠️ **Quality Delta**: Composite score must not drop > threshold
- ⚠️ **Latency**: p95 must stay within SLO
- ⚠️ **Cost**: Token cost must stay within budget

## Output Format

```json
{
  "config_path": "configs/agent_v2.yaml",
  "candidate_scores": {
    "composite": 0.87,
    "quality": 0.90,
    "safety": 1.0,
    "latency": 145.0,
    "cost": 0.002
  },
  "baseline_scores": {
    "composite": 0.89,
    "quality": 0.92,
    "safety": 1.0,
    "latency": 140.0,
    "cost": 0.002
  },
  "delta": -0.02,
  "gate_passed": false,
  "regression_detected": true,
  "failure_reasons": [
    "Quality regression detected: -0.02 < -0.01"
  ]
}
```

## Exit Codes
- `0` — Gate passed, safe to deploy
- `1` — Gate failed, regression detected

## Best Practices

1. **Baseline Selection**
   - `--baseline latest`: Last passing eval
   - `--baseline main`: Current production config
   - `--baseline <sha>`: Specific git commit

2. **Threshold Tuning**
   - Start with `--threshold 0.01` (1% tolerance)
   - Adjust based on eval noise/variance
   - Tighter for production, looser for dev

3. **Artifact Storage**
   - Always save `--output results.json`
   - Upload to CI artifacts for debugging
   - Track trends over time

## Advanced

### Custom Failure Conditions

```python
from cicd.gate import CICDGate

gate = CICDGate()
results = gate.run_gate(
    config_path="agent.yaml",
    baseline_path="baseline.yaml",
    fail_threshold=0.02
)

# Custom checks
if results["candidate_scores"]["latency"] > 200:
    gate.exit_code = 1
    results["failure_reasons"].append("Latency SLO exceeded")

gate.output_json("results.json")
gate.exit()
```

### Integration with Other Tools

```yaml
# With pytest
- run: pytest tests/ && autoagent eval run --gate

# With linting
- run: ruff check . && autoagent eval run --gate

# With security scan
- run: bandit -r . && autoagent eval run --gate
```
