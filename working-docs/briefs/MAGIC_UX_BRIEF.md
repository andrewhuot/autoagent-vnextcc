# Magic UX Brief — Make the Golden Path Magical

## Overview
Implement 8 features that transform AutoAgent from "nice demo" to "wow, this just works."
All changes are additive — don't break existing functionality.

## Feature 1: Before/After Storytelling in Quickstart
**File: `runner.py`** (modify quickstart + demo commands)

After each optimization cycle, print a plain-English explanation of what changed:
```
  Cycle 1/3 ✓ composite=0.7891 (+0.0657)
    → Improved routing rules for billing queries. Added keywords to reduce misroutes.
```

The proposer already returns `change_description` and `reasoning` on the Proposal object.
Surface these in the quickstart/demo output. After the final summary, print the top 3 changes that had the most impact.

At the very end, print a "story" summary:
```
  ✦ Your agent improved from 0.72 → 0.83 in 3 cycles.
    Key improvements:
    1. Fixed billing routing (12 fewer misroutes)
    2. Tightened safety guardrails
    3. Reduced response latency via tool timeout tuning
```

## Feature 2: Live Streaming During Optimization
**File: `runner.py`** (modify optimize command + quickstart)

Replace the silent "Cycle N/M" with a live narrative:
```
  Cycle 2/3
    ↳ Diagnosing... found 12 routing errors, 3 safety violations
    ↳ Proposing fix for routing_error (dominant failure)
    ↳ Evaluating candidate config...
    ↳ ✓ Accepted: +0.034 improvement (p=0.02)
```

Use `click.echo()` calls at each phase. The data is already available:
- Observer report has failure_buckets
- Proposer returns change_description
- Eval returns scores
- Statistics returns p-value

Create a helper function `_stream_cycle_output(cycle_num, total, report, proposal, score, baseline_score)` that prints the narrative.

## Feature 3: Auto-Open Web Console
**File: `runner.py`** (modify quickstart + demo)

Add `--open/--no-open` flag (default: True) to quickstart and demo commands.
When enabled, after the summary:
1. Start the API server in a background thread
2. Open `http://localhost:8080` in the default browser via `webbrowser.open()`
3. Print "Web console running at http://localhost:8080 — press Ctrl+C to stop"

Use `import webbrowser` and `import threading`. Start the uvicorn server in a daemon thread.
If the server can't start (port in use), just print the "run autoagent server" hint instead.

## Feature 4: "What Next?" Recommendations
**File: `runner.py`** (modify quickstart + demo + new helper)

After optimization summary, analyze the failure distribution and recommend next actions:
```
  ⚡ Recommended next steps:
    1. Routing errors are 34% of failures → autoagent runbook apply fix-retrieval-grounding
    2. 3 safety violations detected → autoagent runbook apply tighten-safety-policy
    3. Latency p95 is 4.2s → autoagent runbook apply reduce-tool-latency
```

Create `_generate_recommendations(report, score)` that:
- Looks at failure_buckets from the observer report
- Maps failure families to runbook names (routing_error → fix-retrieval-grounding, safety_violation → tighten-safety-policy, etc.)
- Returns top-3 sorted by frequency
- Includes the exact CLI command to run

## Feature 5: Rich `autoagent status` Command
**File: `runner.py`** (modify existing status command)

Make it the "git status" of agent optimization:
```
AutoAgent Status
━━━━━━━━━━━━━━━
  Config:     v003 (deployed 2h ago)
  Eval score: 0.8342 (↑ 0.12 from baseline)
  Safety:     1.000 ✓
  Cycles run: 7

  Top failures:
    routing_error    ████████░░  34% (12 conversations)
    quality_issue    ███░░░░░░░  15% (5 conversations)
    safety_violation █░░░░░░░░░   3% (1 conversation)

  Recommended: autoagent runbook apply fix-retrieval-grounding

  Loop: paused | Last cycle: 45m ago
```

Use Unicode block chars (█░) for the bar chart. Pull data from:
- Deployer for config version
- EvalRunner history for latest score
- Observer for failure buckets
- Control state for loop status

## Feature 6: Visual Diffs in Web Console
**File: `web/src/pages/ChangeReview.tsx`** (modify)

Enhance the change review page to show actual syntax-highlighted diffs:
- Render `diff_hunks` as green/red lines (like GitHub PR diffs)
- Use a `<pre>` block with CSS classes: `.diff-add { background: #e6ffed; color: #22863a }` and `.diff-remove { background: #ffeef0; color: #cb2431 }`
- Show before/after metric comparison as a mini bar chart
- Each hunk should have Accept/Reject buttons
- Add a "Summary" card at the top: "This change improves routing accuracy by modifying 2 config sections"

Also create a reusable `DiffViewer` component at `web/src/components/DiffViewer.tsx`:
```tsx
interface DiffViewerProps {
  hunks: DiffHunk[];
  onAccept?: (hunkId: string) => void;
  onReject?: (hunkId: string) => void;
}
```

## Feature 7: `autoagent explain` Command
**File: `runner.py`** (add new command)

```
autoagent explain [--verbose]
```

Generates a plain-English summary of the agent's current state. In mock mode, build it from data:
```
Your Agent: Support Bot (Google ADK)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Overall health: Good (0.83/1.00)

Your agent handles 85% of queries correctly. The main weakness is
billing routing, which accounts for 34% of all failures. The optimizer
has run 7 cycles and improved quality by 12% from the initial baseline.

Strengths:
  ✓ Safety compliance: 100% — zero violations
  ✓ Tech support routing: 95% accuracy
  ✓ Response quality: above threshold

Weaknesses:
  ✗ Billing routing: 66% accuracy (34% failure rate)
  ✗ Tool latency: p95 at 4.2s (target: 3.0s)

Recommendation: Focus on routing accuracy. Run:
  autoagent runbook apply fix-retrieval-grounding
```

Build this from observer report + eval scores + config history. No LLM needed for mock mode.

## Feature 8: `autoagent replay` Command
**File: `runner.py`** (add new command)

```
autoagent replay [--limit N]
```

Prints the optimization evolution like `git log --oneline`:
```
AutoAgent Optimization History
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  v007  0.8342  ✓ +0.02  Tightened safety guardrails          2h ago
  v006  0.8156  ✓ +0.03  Reduced tool timeout from 10s to 5s  5h ago
  v005  0.7891  ✓ +0.07  Fixed billing routing keywords       8h ago
  v004  0.7234  ✗ -0.01  [rejected] Over-aggressive pruning   8h ago
  v003  0.7340  ✓ +0.05  Added tech support few-shot examples  1d ago
  v002  0.6891  ✓ +0.04  Initial routing improvements          1d ago
  v001  0.6500  ─  ─     Baseline config                       1d ago
```

Pull from experiment history in the DB. Show config version, score, delta, change description, and relative time.

## Implementation Notes

- All CLI output should use `click.style()` for colors and `click.echo()` for output
- Keep existing tests passing — run `python3 -m pytest tests/ -x -q` frequently
- Add tests for the new helpers: `_stream_cycle_output`, `_generate_recommendations`, replay data formatting
- Run `cd web && npx tsc --noEmit` to verify TypeScript
- The dependency layer test must still pass — don't import Layer 1 modules in Layer 0

## When Done

1. Run full test suite: `python3 -m pytest tests/ -x -q` (must pass, target: more than 1,339)
2. Run TypeScript check: `cd web && npx tsc --noEmit` (must pass)  
3. Run dependency layers: `python3 -m pytest tests/test_dependency_layers.py -v` (must pass)
4. Commit: `feat: magic UX — storytelling, streaming, recommendations, status, explain, replay, visual diffs`
5. Push to master
6. Then run: `openclaw system event --text "Done: magic UX — 8 features shipped" --mode now`
