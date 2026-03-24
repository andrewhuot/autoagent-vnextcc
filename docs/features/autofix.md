# AutoFix Copilot

Automated failure analysis and constrained repair proposals. AutoFix identifies why your agent is failing, generates targeted fix proposals, and applies them through a gated deployment pipeline.

## How it works

AutoFix runs a six-stage pipeline:

```
failure analysis → constrained proposals → human review → apply → eval → canary deploy
```

1. **Failure analysis.** Scans recent conversation failures, classifies them by type (tool failure, routing error, safety violation, etc.), and identifies the most impactful patterns.

2. **Constrained proposals.** Generates mutation proposals that target the identified failure patterns. Each proposal is constrained to a single surface (instruction, tool description, routing, etc.) and declares its expected impact.

3. **Human review.** Proposals are queued for review. You can inspect each proposal's rationale, affected surface, and confidence score before applying.

4. **Apply.** Applies the mutation to a candidate config. The original config is preserved for rollback.

5. **Eval.** Runs the full eval suite against the candidate config. The candidate must pass all gates (safety, regression) and show statistically significant improvement.

6. **Canary deploy.** Successful candidates are deployed via canary. Traffic is gradually shifted, and the system monitors for regressions before full promotion.

## CLI commands

Generate proposals from recent failures:

```bash
autoagent autofix suggest
```

Review and apply a proposal:

```bash
autoagent autofix apply fix_001
```

View past proposals and outcomes:

```bash
autoagent autofix history --limit 20
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/autofix/suggest` | Generate fix proposals |
| `GET` | `/api/autofix/proposals` | List pending proposals |
| `POST` | `/api/autofix/apply/{id}` | Apply a proposal |
| `GET` | `/api/autofix/history` | History of applied fixes |

## Example workflow

```bash
# 1. Check what's failing
autoagent status

# 2. Generate fix proposals
autoagent autofix suggest
# → Proposal fix_001: Rewrite support instruction to handle order lookup edge case
# → Proposal fix_002: Add tool description for refund API
# → Confidence: 0.82, 0.71

# 3. Apply the highest-confidence fix
autoagent autofix apply fix_001

# 4. Verify the fix improved things
autoagent eval run --output after_fix.json
autoagent eval results --file after_fix.json

# 5. Check history
autoagent autofix history
```

AutoFix proposals respect pinned surfaces. If you have pinned `safety_instructions`, no proposal will modify that surface.
