# Judge Ops

Judge versioning, drift monitoring, human feedback integration, and calibration analysis. Keep your eval judges accurate and trustworthy over time.

## Judge versioning

Every judge configuration is versioned through `GraderVersionStore`. When you modify a judge's rubric, model, or parameters, a new version is created automatically. You can always trace which judge version scored a given eval run.

Versions are immutable. Rolling back means activating a previous version, not editing history.

## Drift monitoring

The `DriftMonitor` tracks judge agreement rates over time. It compares recent scoring patterns against a baseline window and flags significant shifts.

Key parameters:

```yaml
optimizer:
  drift_threshold: 0.12       # Maximum acceptable agreement rate change
  max_judge_variance: 0.03    # Maximum scoring variance before flagging
```

When drift exceeds the threshold, the system:
- Flags the judge for review
- Optionally pauses auto-promotion of experiments scored by the drifting judge
- Emits an event via the SSE stream

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
autoagent judges calibrate --sample 50

# Calibrate a specific judge
autoagent judges calibrate --judge-id binary_rubric --sample 100
```

## CLI commands

```bash
autoagent judges list          # List judges and versions
autoagent judges calibrate     # Run calibration analysis
autoagent judges drift         # Check for scoring drift
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/judges` | List judges and their versions |
| `POST` | `/api/judges/feedback` | Submit human feedback on a score |
| `GET` | `/api/judges/calibration` | Calibration report |
| `GET` | `/api/judges/drift` | Drift analysis |

## The judge stack

AutoAgent uses a layered judge stack that fires in order:

1. **Deterministic** -- Pattern matching, schema checks (zero cost)
2. **Similarity** -- Embedding comparison against references (low cost)
3. **Binary Rubric** -- LLM-based structured scoring (moderate cost)
4. **Audit Judge** -- Secondary LLM review of borderline cases (higher cost)
5. **Calibration** -- Periodic human agreement analysis (manual)

Each layer only fires when the previous layer is inconclusive. This keeps eval costs low while maintaining scoring accuracy. Judge Ops gives you visibility into how each layer is performing over time.
