# Live CLI Golden Path Fixes — Claude Opus

## Fix Log

### Fix 1: Domain inference word-boundary bug + telecom domain
**Files**: `builder/workbench.py`
**Changes**:
- `_infer_domain()`: Replaced `"it " in lowered` with regex `re.search(r"\bit\s+(support|helpdesk|...)", lowered)` to prevent false IT Helpdesk matches
- Added new "Billing Support" domain with 10 keywords (billing, phone company, telecom, etc.)
- Added `import re` at function scope

**Tests added**: `tests/test_infer_domain.py` — 18 regression tests covering:
- Word-boundary correctness (5 tests)
- Telecom domain patterns (7 tests)
- Existing domain preservation (6 tests)

### Fix 2: Replace hardcoded "gpt-5.4-mini" with workspace-aware model resolver
**Files**: `builder/workbench.py`
**Changes**:
- Added `_resolve_workspace_agent_model()` — reads active config model from workspace, falls back to "gemini-2.0-flash"
- Replaced all 6 production occurrences of `"gpt-5.4-mini"` in `builder/workbench.py`
- Test files intentionally left unchanged (they test with mock data)

### Fix 3: Enable LLM executor path by adding kind tags to plan tree
**Files**: `builder/workbench_agent.py`
**Changes**:
- Modified `_build_plan_tree()` to accept `kind=` parameter on leaf tasks
- Tagged 7 of 8 leaf tasks with executor kinds: role, instructions, tool_schema, tool_source, guardrail, environment, eval_suite
- "Identify sensitive flows" left untagged (no matching executor schema)

**Result**: 3 of 8 build steps now successfully use LLM-generated content in live mode (confirmed with Gemini).

### Fix 4: Add LLM/template source transparency to CLI output
**Files**: `builder/harness.py`, `cli/workbench_render.py`
**Changes**:
- Modified `_generate_step()` return type to include source indicator ("llm" or "template")
- Added source to `task.completed` event data
- Updated CLI renderer to show `[llm]` or `[template]` suffix on completed tasks

**Result**: Users now see exactly which build steps used real LLM generation vs template fallback.

## Tests Verified
- `tests/test_infer_domain.py` — 18 passed
- `tests/test_workbench_harness_eng.py` — passed
- `tests/test_workbench_hardening.py` — passed
- `tests/test_workbench_streaming.py` — passed
- `tests/test_workbench_agent_live.py` — passed
- `tests/test_workbench_multi_turn.py` — passed
- `tests/test_workbench_eval_optimize_bridge.py` — passed
- `tests/test_agents_api.py` — passed
- **Total: 68+ tests passing**
