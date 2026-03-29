# Golden Path UX Overhaul Brief

## Mission
Make AutoAgent's happy path dead simple. A new user should go from `pip install` to seeing optimization results in under 5 minutes with zero config. Think `npx create-next-app` or `rails new` — instant gratification.

## Current Problems
1. `autoagent init` scaffolds files but doesn't generate synthetic data — user has to bring their own conversations/evals before anything works
2. No `autoagent demo` or `autoagent quickstart` command that shows the full loop in action
3. No synthetic conversation data to bootstrap eval runs
4. The journey from init → eval → optimize → review requires too many manual steps
5. No progress indicators or colored output to guide the user

## What to Build

### 1. Synthetic Data Generator (`evals/synthetic.py`)
Create a module that generates realistic synthetic data:
- **Conversations**: 50+ synthetic agent conversations across failure types (routing errors, safety violations, quality issues, latency problems, cost overruns)
- **Eval cases**: 20+ eval cases with inputs, expected outputs, and grading criteria
- **Traces**: Synthetic trace data with tool calls, handoffs, and timing
- Each conversation should have realistic user messages, agent responses, tool calls, and outcomes (success/fail with tagged failure reasons)

### 2. `autoagent quickstart` Command
A single command that runs the ENTIRE golden path automatically:
```
autoagent quickstart [--agent-name "My Agent"] [--verbose]
```
This should:
1. Run `init` to scaffold the project
2. Seed synthetic conversations into the DB
3. Seed synthetic eval cases
4. Run an eval suite (with progress bar)
5. Run 3 optimization cycles (with live progress)
6. Show a summary of what improved
7. Print "Next: `autoagent server` to explore results in the web console"

### 3. `autoagent demo` Command
Interactive demo mode that walks through features:
```
autoagent demo
```
Seeds data, runs a single optimize cycle, generates a change card, and opens the web console — all in one command. More visual, less verbose than quickstart.

### 4. Improve `autoagent init` 
- Add `--with-synthetic-data` flag (default: True) to auto-seed conversations and evals
- Add `--agent-name` and `--platform` flags so AUTOAGENT.md is pre-filled
- Better output: use click.style() for colored headers, checkmarks, and progress

### 5. Seed Runbooks on Init
Call `seed_starter_runbooks()` during `init` so the registry is pre-populated with the 7 built-in runbooks.

### 6. Improve CLI Output Throughout
- Add emoji/checkmarks to success messages (✓, ✗, ⚠️)  
- Add `click.progressbar()` to eval runs and optimize cycles
- Color-code metric improvements (green for better, red for worse)
- Add `--json` flag to key commands for scripting

### 7. Web Console: Welcome/Empty States
In the React frontend, ensure every page has a useful empty state:
- Dashboard with no data → "Run `autoagent quickstart` to get started"
- Eval runs empty → "No eval runs yet. Run `autoagent eval run` to create one."
- Each empty state should have the exact CLI command to populate it

## Quality Bar
- All new code must have tests
- `python3 -m pytest tests/ -x -q` must pass with MORE tests than current (1,284)
- `cd web && npx tsc --noEmit` must pass
- The `autoagent quickstart` command must actually work end-to-end (test it!)

## What NOT to Change
- Don't restructure existing modules — this is additive
- Don't change the optimization loop logic
- Don't change the API contract
- Keep backwards compatibility with existing projects

## Files to Create/Modify
- CREATE: `evals/synthetic.py` (synthetic data generator)
- CREATE: `tests/test_synthetic.py`
- CREATE: `tests/test_quickstart.py`
- MODIFY: `runner.py` (add quickstart, demo commands; improve init)
- MODIFY: `web/src/pages/Dashboard.tsx` (empty states)
- MODIFY: `web/src/pages/EvalRuns.tsx` (empty states)
- MODIFY: `web/src/pages/Experiments.tsx` (empty states)
- MODIFY: `web/src/pages/ChangeReview.tsx` (empty states)

## Commit and Push
When done, commit with: `feat: golden path UX — quickstart, synthetic data, demo mode, empty states`
Then push to master.
