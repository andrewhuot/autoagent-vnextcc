# VP Demo Implementation Plan

## Overview
Create a VP-ready demo that tells a compelling 5-minute story showcasing AutoAgent's full power: diagnose → fix → deploy.

## Current State
- `autoagent demo` exists as a single command (runner.py:2957)
- `evals/synthetic.py` has generic failure templates
- README has quickstart section but no VP demo script

## Changes Required

### 1. Create VP Demo Data Module
**File:** `evals/vp_demo_data.py` (~400 lines)

**Hand-crafted conversations (41 total):**
- 15 billing misroutes (user asks about invoice/refund/charge, gets routed to tech_support)
- 3 safety violations (bot reveals internal pricing tiers)
- 8 high-latency conversations (tool timeouts on order_lookup)
- 10 successful conversations (to show baseline functionality)
- 5 quality issues (vague/unhelpful responses)

**Each conversation has:**
- Realistic multi-turn dialogue
- Named users (Sarah M., James K., etc.)
- Specific order numbers, product references
- Emotional arcs (frustration → escalation in failures)

**API:**
```python
def generate_vp_demo_dataset(seed: int = 42) -> SyntheticDataset
```

### 2. Refactor Demo Command Structure
**File:** `runner.py`

**Current:** `@cli.command("demo")` (single command)
**New:** `@cli.group("demo")` with subcommands:
- `demo quickstart` (rename existing demo logic)
- `demo vp` (new VP demo)

### 3. Build VP Demo Command
**File:** `runner.py`

```python
@demo.command("vp")
@click.option("--agent-name", default="Acme Support Bot")
@click.option("--company", default="Acme Corp")
@click.option("--no-pause", is_flag=True)
@click.option("--web", is_flag=True)
def demo_vp(...)
```

**5-Act Structure with Rich CLI Output:**

**Act 1: Broken Agent (30s)**
- Load VP demo dataset with deterministic seed
- Print dramatic health report with RED indicators
- Overall score: 0.62 (CRITICAL)
- Show 3 top issues with impact counts

**Act 2: Diagnosis (60s)**
- Run observer.observe()
- Print root cause analysis in bordered boxes
- Show 3 issues with fix confidence

**Act 3: Self-Healing (90s)**
- Run 3 optimization cycles with streaming output
- Pause 0.5-1s between cycles (skip with --no-pause)
- Show score improvements: 0.62 → 0.74 → 0.81 → 0.87
- Display accepted changes with visual feedback (✨, ✅)

**Act 4: Review (60s)**
- Print change cards with before/after diffs
- Show statistical confidence (p-values)
- Display impact metrics

**Act 5: Results (30s)**
- Before/after comparison table
- Summary of resolved issues
- Next steps (server, cx deploy, replay)
- If --web: auto-start server and open browser

### 4. Add VP Demo Section to README
**File:** `README.md`

Add new section after "Quickstart":

```markdown
## VP Demo

5-minute presentation-ready demo with dramatic storytelling...

### Running the Demo
...

### Presenter Script
Act 1: [What to say]
Act 2: [What to say]
...

### Expected Output
[Screenshots/samples]

### Talking Points
- Wow moment 1: Root cause diagnosis
- Wow moment 2: Self-healing optimization
- Wow moment 3: Statistical validation

### FAQ / Objection Handling
Q: How does it know what to fix?
A: ...
```

### 5. Add Tests
**File:** `tests/test_vp_demo.py` (~50 lines)

```python
def test_vp_demo_data_deterministic():
    """VP demo data is deterministic with fixed seed."""

def test_vp_demo_runs_end_to_end():
    """Demo vp --no-pause completes without errors."""

def test_vp_demo_score_progression():
    """VP demo shows expected score progression."""
```

## Implementation Sequence

### Phase 1: Data (Track A - Sonnet Agent)
1. Create `evals/vp_demo_data.py`
2. Hand-craft 41 realistic conversations
3. Implement `generate_vp_demo_dataset()` function
4. Test data generation is deterministic

### Phase 2: CLI Command (Track B - Sonnet Agent)
1. Refactor runner.py demo from command to group
2. Move existing demo logic to `demo quickstart` subcommand
3. Implement `demo vp` with 5-act structure
4. Add rich CLI formatting (boxes, colors, progress)
5. Add dramatic pauses with --no-pause flag
6. Add --web flag for auto-server-start

### Phase 3: Documentation (Track C - Sonnet Agent)
1. Add VP Demo section to README.md
2. Write presenter script with talking points
3. Add FAQ and objection handling
4. Include expected output examples

### Phase 4: Integration & Testing
1. Wire vp_demo_data into demo_vp command
2. Run end-to-end test with --no-pause
3. Verify all 3 agents' work integrates cleanly
4. Add tests in tests/test_vp_demo.py

### Phase 5: Quality Assurance
1. Run full test suite: `python3 -m pytest tests/ -x -q`
2. Manual run: `autoagent demo vp --no-pause`
3. Manual run with web: `autoagent demo vp --web --no-pause`
4. Verify README instructions are accurate

## Success Criteria
- ✅ `autoagent demo vp --no-pause` runs cleanly in <5 min
- ✅ `autoagent demo vp --web` auto-opens web console
- ✅ All pytest tests pass
- ✅ Demo output matches brief's visual specifications
- ✅ README has complete presenter script
- ✅ Deterministic output (same seed → same story)

## Files Changed
- CREATE: `evals/vp_demo_data.py`
- CREATE: `tests/test_vp_demo.py`
- MODIFY: `runner.py` (refactor demo structure, add vp subcommand)
- MODIFY: `README.md` (add VP Demo section)

## Quality Gates
1. All existing tests still pass
2. New tests for VP demo pass
3. Manual end-to-end run successful
4. README instructions validated

## Commit Plan
```
feat: VP-ready demo — curated scenario, storytelling output, presenter script

- Create evals/vp_demo_data.py with 41 hand-crafted conversations
- Refactor 'autoagent demo' to group with 'quickstart' and 'vp' subcommands
- Implement 5-act demo with dramatic CLI formatting and pauses
- Add --web flag to auto-start server after demo
- Document presenter script, talking points, and FAQ in README
- Add tests for deterministic data and end-to-end demo flow

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```
