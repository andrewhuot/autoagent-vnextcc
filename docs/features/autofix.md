# AutoFix Copilot

Automated failure analysis and constrained repair proposals. AutoFix identifies why your agent is failing, generates targeted fix proposals, and applies them through a reviewed mutation pipeline.

## How it works

AutoFix runs a four-stage pipeline:

```
failure analysis → constrained proposals → human review → apply
```

1. **Failure analysis.** Scans recent conversation failures, classifies them by type (tool failure, routing error, safety violation, etc.), and identifies the most impactful patterns.

2. **Constrained proposals.** Generates mutation proposals that target the identified failure patterns. Each proposal is constrained to a single surface (instruction, tool description, routing, etc.) and declares its expected impact.

3. **Human review.** Proposals are queued for review. You can inspect each proposal's rationale, affected surface, and confidence score before applying.

4. **Apply.** Applies the mutation to a candidate config. The original config is preserved for rollback.

### What happens after apply

After AutoFix applies a mutation, the candidate config is saved but **not automatically evaluated or deployed**. To validate the fix:

1. Run an eval: `agentlab eval run` or `POST /api/eval/run`
2. Compare results against baseline: `agentlab eval results`
3. If improvement is confirmed, deploy via canary: `agentlab deploy canary` or `POST /api/deploy/canary`

These steps use the same eval and deployment infrastructure as the standard optimization loop — they are simply not auto-triggered by AutoFix. This keeps the operator in control of when evaluation budget is spent and when changes go live.

## CLI commands

Generate proposals from recent failures:

```bash
agentlab autofix suggest
```

Review and apply a proposal:

```bash
agentlab autofix apply fix_001
```

View past proposals and outcomes:

```bash
agentlab autofix history --limit 20
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
agentlab status

# 2. Generate fix proposals
agentlab autofix suggest
# → Proposal fix_001: Rewrite support instruction to handle order lookup edge case
# → Proposal fix_002: Add tool description for refund API
# → Confidence: 0.82, 0.71

# 3. Apply the highest-confidence fix
agentlab autofix apply fix_001

# 4. Verify the fix improved things
agentlab eval run --output after_fix.json
agentlab eval results --file after_fix.json

# 5. Deploy if satisfied
agentlab deploy canary

# 6. Check history
agentlab autofix history
```

AutoFix proposals respect pinned surfaces. If you have pinned `safety_instructions`, no proposal will modify that surface.
