# Judge Ops

Judge versioning, drift monitoring, human feedback integration, and calibration analysis. Keep your eval judges accurate and trustworthy over time.

## Judge versioning

Every judge configuration is versioned through `GraderVersionStore`. When you modify a judge's rubric, model, or parameters, a new version is created automatically. You can always trace which judge version scored a given eval run.

Versions are immutable. Rolling back means activating a previous version, not editing history.

## Drift monitoring

The `DriftMonitor` tracks judge agreement rates over time. It compares recent scoring patterns against a baseline window and flags significant shifts.

Key parameters (configured in `agentlab.yaml`):

```yaml
optimizer:
  drift_threshold: 0.12       # Maximum acceptable agreement rate change
  max_judge_variance: 0.03    # Maximum scoring variance before flagging
```

The `drift_threshold` value is passed to the DriftMonitor at server startup and controls the sensitivity of drift detection.

### What drift detection does

When drift exceeds the configured threshold, the system generates a `DriftAlert` containing:
- The affected grader ID
- Alert type (agreement drift, position bias, or verbosity bias)
- Severity score (0.0–1.0)
- Historical vs recent agreement rates

Alerts are returned via `GET /api/judges/drift`.

### What drift detection does NOT do (yet)

- **Auto-pause promotion** — Drift alerts do not currently block or pause experiment promotion. Operators must check drift status manually and decide whether to pause optimization.
- **SSE event emission** — Drift alerts are not currently pushed via SSE. Poll the drift endpoint to check status.

These capabilities are planned for a future release.

## Human feedback

`HumanFeedbackStore` collects human corrections on judge scores. When a human reviews a judge's output, that feedback is stored and used for calibration.

Submit feedback via the API:

```bash
curl -X POST http://localhost:8000/api/judges/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "judge_id": "demo_quality_judge",
    "case_id": "case_42",
    "judge_score": 0.4,
    "human_score": 1.0,
    "human_notes": "This response should have passed."
  }'
```

## Calibration analysis

Calibration compares judge scores against human labels to compute:

- **Agreement rate** -- How often the judge matches human judgment
- **Bias** -- Whether the judge systematically scores higher or lower
- **Variance** -- How consistent the judge is on similar inputs

Run calibration from the CLI:

```bash
# Calibrate all judges against a 50-case sample
agentlab judges calibrate --sample 50

# Calibrate a specific judge
agentlab judges calibrate --judge-id binary_rubric --sample 100
```

## CLI commands

```bash
agentlab judges list          # List judges and versions
agentlab judges calibrate     # Run calibration analysis
agentlab judges drift         # Check for scoring drift
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/judges` | List judges and their versions |
| `POST` | `/api/judges/feedback` | Submit human feedback on a score |
| `GET` | `/api/judges/calibration` | Calibration report |
| `GET` | `/api/judges/drift` | Drift analysis (includes configured threshold) |

## The judge stack

AgentLab uses a layered judge stack that fires in order:

1. **Deterministic** -- Pattern matching, schema checks (zero cost)
2. **Similarity** -- Embedding comparison against references (low cost)
3. **Binary Rubric** -- LLM-based structured scoring (moderate cost)
4. **Audit Judge** -- Secondary LLM review of borderline cases (higher cost)
5. **Calibration** -- Periodic human agreement analysis (manual)

Each layer only fires when the previous layer is inconclusive. This keeps eval costs low while maintaining scoring accuracy. Judge Ops gives you visibility into how each layer is performing over time.
