# NL Scorer Generation

Create eval scorers from natural language descriptions. No code required -- describe what you want to measure, and AutoAgent generates a structured scorer with weighted dimensions.

## How it works

The NL Scorer pipeline:

1. **Describe** -- You provide a natural language description of your quality criteria
2. **Generate** -- The system generates a `ScorerSpec` with named dimensions, weights, and evaluation criteria
3. **Refine** -- Iterate on the spec by adding or adjusting criteria in plain language
4. **Test** -- Validate the scorer against real trace data
5. **Deploy** -- Use the scorer in your eval suite

## ScorerSpec

A generated scorer is a `ScorerSpec` with one or more dimensions:

```json
{
  "name": "support_quality",
  "dimensions": [
    {
      "name": "empathy",
      "weight": 0.30,
      "description": "Does the response acknowledge the customer's frustration?"
    },
    {
      "name": "accuracy",
      "weight": 0.40,
      "description": "Is the information provided factually correct?"
    },
    {
      "name": "actionability",
      "weight": 0.30,
      "description": "Does the response include clear next steps?"
    }
  ]
}
```

Each dimension has a name, weight (summing to 1.0), and a description that guides scoring.

## CLI commands

### Create a scorer

From an inline description:

```bash
autoagent scorer create "Score customer support responses on empathy, accuracy, and actionability" --name support_quality
```

From a file with detailed criteria:

```bash
autoagent scorer create --from-file criteria.txt --name support_quality
```

### List and inspect

```bash
autoagent scorer list
autoagent scorer show support_quality
```

### Refine iteratively

Add criteria to an existing scorer:

```bash
autoagent scorer refine support_quality "Also penalize responses longer than 3 paragraphs"
```

Each refinement creates a new version of the scorer spec.

### Test against traces

```bash
autoagent scorer test support_quality --trace trace_abc123
```

Output shows per-dimension scores and an aggregate:

```
Scorer: support_quality
Trace:  trace_abc123

  empathy:        0.85  (weight: 0.30)
  accuracy:       0.92  (weight: 0.40)
  actionability:  0.78  (weight: 0.30)
  ─────────────────────
  aggregate:      0.86
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/scorers/create` | Create a scorer from description |
| `GET` | `/api/scorers` | List all scorers |
| `GET` | `/api/scorers/{name}` | Get a scorer spec |
| `POST` | `/api/scorers/{name}/refine` | Refine with additional criteria |
| `POST` | `/api/scorers/{name}/test` | Test against eval data |

### Create via API

```bash
curl -X POST http://localhost:8000/api/scorers/create \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Score on empathy, accuracy, and conciseness",
    "name": "support_quality"
  }'
```

### Refine via API

```bash
curl -X POST http://localhost:8000/api/scorers/support_quality/refine \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Weight accuracy higher than empathy"
  }'
```

## Example workflow

```bash
# 1. Create a scorer for your use case
autoagent scorer create "Evaluate order support responses: correct order info, empathetic tone, clear resolution steps" --name order_support

# 2. Check what was generated
autoagent scorer show order_support

# 3. Refine based on what you see
autoagent scorer refine order_support "Add a dimension for response time appropriateness"

# 4. Test against a real trace
autoagent scorer test order_support --trace trace_abc123

# 5. Iterate until satisfied
autoagent scorer refine order_support "Increase weight of correct order info to 0.5"
autoagent scorer test order_support --trace trace_def456
```

NL Scorers integrate with the eval runner. Once created, they can be referenced in your eval config to score cases alongside the built-in judge stack.
